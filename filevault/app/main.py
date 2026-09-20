"""A read-only HTTP file server for a folder outside the application directory.

There is no routing beyond a reserved health path and a catch-all: this serves
files and nothing else, so the policy runs ahead of every response and a file
called "healthz" can never shadow the health endpoint.
"""

from __future__ import annotations

import logging
import os
from email.utils import parsedate
from typing import Optional

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from .config import ConfigError, VaultConfig
from .vault import Vault

logger = logging.getLogger("filevault")


def create_app(config: Optional[VaultConfig] = None) -> Starlette:
    cfg = VaultConfig.load() if config is None else config
    _check_root(cfg)

    vault = Vault(cfg)

    async def health(request: Request) -> Response:
        return JSONResponse(
            {
                "status": "ok",
                "root": vault.root,
                "requestPath": cfg.request_path or "/",
            }
        )

    async def serve(request: Request) -> Response:
        url_path = request.url.path
        sub_path = url_path

        if cfg.request_path:
            if not (url_path == cfg.request_path or url_path.startswith(cfg.request_path + "/")):
                # Outside the prefix entirely: nothing here claims that URL.
                return _not_found(request)
            sub_path = url_path[len(cfg.request_path):] or "/"

        resolved = vault.resolve(sub_path)

        if resolved.refused:
            # 404 rather than 403, so the response does not confirm what exists
            # on disk. The reason goes to the log instead.
            logger.warning(
                "Refused %s %s from %s: %s",
                request.method,
                url_path,
                request.client.host if request.client else "-",
                resolved.reason,
            )
            return _not_found(request)

        if resolved.kind == "missing":
            return _not_found(request)

        if resolved.kind == "directory":
            if not cfg.enable_directory_browsing:
                return _not_found(request)

            if not url_path.endswith("/"):
                # Without this the relative links in the listing resolve against
                # the parent folder.
                return Response(status_code=307, headers={"location": url_path + "/"})

            body = vault.listing_html(resolved.path, url_path)
            return HTMLResponse(body, headers={"cache-control": "no-cache", "x-content-type-options": "nosniff"})

        content_type = vault.content_type(resolved.path)
        if content_type is None:
            # serve_unknown_file_types is off and nothing maps this extension.
            # Refusing beats guessing: the allowlist and the mappings are meant
            # to be edited together.
            logger.warning("Refused %s %s: no content type for this extension", request.method, url_path)
            return _not_found(request)

        stat_result = os.stat(resolved.path)

        headers = {
            "cache-control": (
                "public,max-age={0}".format(cfg.cache_max_age_seconds)
                if cfg.cache_max_age_seconds > 0
                else "no-cache"
            ),
            # The vault is an allowlist of known types, so a browser sniffing
            # its way to some other one is never something we asked for.
            "x-content-type-options": "nosniff",
        }

        response = FileResponse(
            resolved.path,
            media_type=content_type,
            headers=headers,
            stat_result=stat_result,
            filename=os.path.basename(resolved.path) if cfg.force_download else None,
            content_disposition_type="attachment" if cfg.force_download else "inline",
        )

        if _is_not_modified(request, response):
            return Response(status_code=304, headers=_conditional_headers(response))

        return response

    routes = [
        Route(cfg.health_path, health, methods=["GET", "HEAD"]),
        Route("/{path:path}", serve, methods=["GET", "HEAD"]),
    ]

    app = Starlette(routes=routes)
    app.state.config = cfg
    app.state.vault = vault

    logger.info(
        "Serving %s at %s (directory browsing: %s, forced download: %s)",
        vault.root,
        cfg.request_path or "/",
        cfg.enable_directory_browsing,
        cfg.force_download,
    )
    logger.info(
        "Content policy: %s, %d blocked extensions, %d blocked name patterns, %d blocked folders",
        "allowlist of {0} extensions".format(len(cfg.allowed_extensions))
        if cfg.allowed_extensions
        else "no extension allowlist",
        len(cfg.blocked_extensions),
        len(cfg.blocked_file_names),
        len(cfg.blocked_directories),
    )

    return app


def _not_found(request: Request) -> Response:
    return JSONResponse(
        {"status": 404, "message": "File not found.", "path": request.url.path},
        status_code=404,
    )


def _is_not_modified(request: Request, response: FileResponse) -> bool:
    """The conditional-GET check the static file handler did for us before."""
    try:
        if_none_match = request.headers.get("if-none-match")
        etag = response.headers.get("etag")
        if if_none_match and etag and etag in [tag.strip() for tag in if_none_match.split(",")]:
            return True

        if_modified_since = parsedate(request.headers.get("if-modified-since"))
        last_modified = parsedate(response.headers.get("last-modified"))
        if if_modified_since is not None and last_modified is not None and if_modified_since >= last_modified:
            return True
    except (KeyError, ValueError, TypeError):
        return False

    return False


def _conditional_headers(response: FileResponse) -> dict:
    """The subset of the file's headers a 304 is allowed to carry."""
    keep = ("cache-control", "content-location", "date", "etag", "expires", "vary", "last-modified")
    return {name: value for name, value in response.headers.items() if name in keep}


def _check_root(cfg: VaultConfig) -> None:
    """Refuse to start rather than 404 on every request."""
    root = os.path.realpath(cfg.root_path)

    if not os.path.isdir(root):
        # In a container this is nearly always a missing volume mount, or a host
        # folder the container's non-root user cannot read.
        raise ConfigError(
            "root_path '{0}' does not exist inside the container, or is not readable by uid {1}. "
            "Check the volume mount and the host folder's permissions.".format(root, os.getuid())
        )

    # Serving the application's own code would expose this source and the
    # configuration file beside it. The block lists would refuse both (".py" is
    # a blocked extension, "config.json" a blocked name), but a vault that
    # contains the app is a mistake worth failing on rather than relying on the
    # lists to paper over.
    #
    # The comparison is against the package directory, not the project root, so
    # a sample folder sitting beside the code -- ./files during local
    # development -- is still servable.
    package_dir = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
    if root == package_dir or root.startswith(package_dir + os.sep) or package_dir.startswith(root + os.sep):
        raise ConfigError(
            "root_path '{0}' overlaps the application directory '{1}'. "
            "The served folder must be entirely outside the application.".format(root, package_dir)
        )
