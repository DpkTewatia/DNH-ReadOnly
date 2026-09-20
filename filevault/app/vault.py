"""Turning a request path into a file on disk, or into a refusal."""

from __future__ import annotations

import html
import mimetypes
import os
import posixpath
from dataclasses import dataclass
from typing import List, Optional

from . import guard
from .config import VaultConfig

# Built-in table only, with the system's mime.types files deliberately not read:
# macOS ships one that types ".xyz" as chemical/x-xyz and the slim image ships
# none at all, so reading them would make the same file servable on one host and
# refused on the other. Anything this table does not know belongs in
# content_type_mappings, where it is visible.
_MIME_TYPES = mimetypes.MimeTypes(filenames=())


@dataclass
class Resolved:
    #: "file", "directory", "missing" or "refused".
    kind: str
    path: Optional[str] = None
    reason: Optional[str] = None

    @property
    def refused(self) -> bool:
        return self.kind == "refused"


class Vault:
    def __init__(self, config: VaultConfig) -> None:
        self.config = config
        # realpath once at startup: every resolved path is compared against
        # this, so if the root itself is a symlink the comparison still holds.
        self.root = os.path.realpath(config.root_path)

    def resolve(self, sub_path: str) -> Resolved:
        """Resolve a path relative to the vault root, applying the policy twice."""
        # Pass one, on the spelling in the URL. From a URL alone a trailing
        # segment without an extension is more likely a folder than an
        # extensionless file; guessing wrong only skips an early refusal,
        # because pass two re-checks with the real answer.
        last_segment = sub_path.rsplit("/", 1)[-1]
        guessed_directory = not posixpath.splitext(last_segment)[1]

        reason = guard.is_servable(sub_path, self.config, guessed_directory)
        if reason is not None:
            return Resolved("refused", reason=reason)

        segments = [s for s in sub_path.split("/") if s]
        candidate = os.path.join(self.root, *segments) if segments else self.root
        real = os.path.realpath(candidate)

        # A symlink inside the vault pointing outside it resolves to a path that
        # is not under the root. The .NET original caught this through the
        # relative path starting with ".."; this is the same check, spelled out.
        if real != self.root and not real.startswith(self.root + os.sep):
            return Resolved("refused", reason="resolved path leaves the vault")

        if os.path.isdir(real):
            kind = "directory"
        elif os.path.isfile(real):
            kind = "file"
        else:
            # Missing paths fall through as an ordinary 404 rather than a logged
            # refusal: there is nothing to refuse.
            return Resolved("missing")

        # Pass two, on the real path, with the real file-or-folder answer. This
        # is what judges an extensionless "id_rsa" correctly, and what catches a
        # link whose own name passes but whose target's name does not.
        relative = os.path.relpath(real, self.root)
        resolved_sub_path = "/" if relative == "." else "/" + relative.replace(os.sep, "/")

        reason = guard.is_servable(resolved_sub_path, self.config, kind == "directory")
        if reason is not None:
            return Resolved("refused", reason=reason)

        return Resolved(kind, path=real)

    def content_type(self, path: str) -> Optional[str]:
        """The type to send, or None when nothing sensible is known."""
        extension = os.path.splitext(path)[1].lower()

        mapped = self.config.content_type_mappings.get(extension)
        if mapped:
            return mapped

        guessed, _ = _MIME_TYPES.guess_type(path)
        if guessed:
            return guessed

        return self.config.default_content_type if self.config.serve_unknown_file_types else None

    def entries(self, directory: str) -> List[str]:
        """Names in a folder that the policy would actually serve."""
        try:
            names = os.listdir(directory)
        except OSError:
            return []

        return guard.visible_entries(
            names,
            self.config,
            lambda name: os.path.isdir(os.path.join(directory, name)),
        )

    def listing_html(self, directory: str, url_path: str) -> str:
        """A plain index for a folder, listing only what can be served."""
        url_path = url_path if url_path.endswith("/") else url_path + "/"
        rows = []

        if url_path.rstrip("/") not in ("", self.config.request_path):
            rows.append('<li><a href="../">../</a></li>')

        for name in self.entries(directory):
            is_directory = os.path.isdir(os.path.join(directory, name))
            href = html.escape(name, quote=True) + ("/" if is_directory else "")
            rows.append('<li><a href="{0}">{1}</a></li>'.format(href, html.escape(name) + ("/" if is_directory else "")))

        title = html.escape(url_path)

        return (
            "<!doctype html>\n"
            '<html lang="en"><head><meta charset="utf-8">'
            "<title>Index of {0}</title>"
            "<style>body{{font:14px/1.6 system-ui,sans-serif;margin:2rem}}"
            "ul{{list-style:none;padding:0}}a{{text-decoration:none}}</style>"
            "</head><body><h1>Index of {0}</h1><ul>{1}</ul></body></html>\n"
        ).format(title, "".join(rows))
