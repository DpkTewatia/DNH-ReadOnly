"""Configuration for the folder that lives outside the application directory.

Layered the way the .NET app layered appsettings.json: built-in defaults, then a
JSON file if one is present, then environment variables. The JSON file is how the
deployment pipeline injects its settings; the environment variables are for
docker-compose and for one-off overrides.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Optional

# Server-side source, configuration, credentials, executables, databases and the
# backup/editor leftovers that usually shadow one of those. Applied after
# allowed_extensions, and matched against every dot-separated suffix rather than
# only the last, so "web.config.bak" is refused for containing ".config".
DEFAULT_BLOCKED_EXTENSIONS: List[str] = [
    # Server-side source and markup
    ".cs", ".vb", ".fs", ".cshtml", ".vbhtml", ".razor",
    ".aspx", ".ascx", ".asax", ".ashx", ".asmx", ".master", ".svc", ".axd",
    ".asp", ".asa", ".cdx",
    ".jsp", ".jspx", ".php", ".php5", ".phtml", ".py", ".rb", ".pl", ".cgi",

    # Configuration and project files
    ".config", ".settings", ".pubxml", ".publishsettings", ".user",
    ".csproj", ".vbproj", ".fsproj", ".sln", ".props", ".targets", ".nuspec",

    # Credentials, keys and certificates
    ".pfx", ".p12", ".key", ".pem", ".cer", ".crt", ".der",
    ".jks", ".keystore", ".env", ".ovpn", ".rdp", ".ppk", ".kdbx",

    # Executables and scripts
    ".exe", ".dll", ".msi", ".com", ".scr", ".jar",
    ".bat", ".cmd", ".ps1", ".psm1", ".psd1", ".vbs", ".wsf", ".sh",

    # Databases
    ".mdf", ".ldf", ".sdf", ".mdb", ".accdb", ".db", ".sqlite", ".sqlite3",

    # Backups and editor leftovers, which usually shadow one of the above
    ".bak", ".backup", ".old", ".orig", ".save", ".swp", ".tmp",
]

# Names that are never served whatever their extension, so a sensitive file with
# an otherwise legitimate extension ("appsettings.Production.json") is still
# refused. "*" and "?" work; matching ignores case.
DEFAULT_BLOCKED_FILE_NAMES: List[str] = [
    "appsettings*.json", "secrets*.json", "launchsettings.json",
    "*.deps.json", "*.runtimeconfig.json", "*.staticwebassets*.json",
    "web.config*", "app.config*", "machine.config*", "packages.config",
    "connectionstrings*", "global.asax*",
    ".env*", ".htaccess", ".htpasswd", ".npmrc", ".netrc", ".git*", ".dockerignore",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*", "*.pub",
    "thumbs.db", "desktop.ini",
    "config.json",  # this app's own configuration file
]

# Folder names that are never traversed. A request whose path contains one of
# these segments is refused, and listings omit them.
DEFAULT_BLOCKED_DIRECTORIES: List[str] = [
    "bin", "obj", "App_Data", "App_Code", "App_GlobalResources", "App_LocalResources",
    ".git", ".svn", ".hg", ".vs", ".vscode", ".idea", "node_modules", "__pycache__",
]

# mimetypes reads /etc/mime.types when it exists, which the slim image does not
# ship, and its built-in table has gaps that vary by Python version. These are
# the ones this server actually cares about; config can override any of them.
BUILTIN_CONTENT_TYPES: Dict[str, str] = {
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".ico": "image/x-icon",
    ".heic": "image/heic",
    ".txt": "text/plain; charset=utf-8",
}


class ConfigError(ValueError):
    """Raised for a configuration that cannot serve anything sensibly."""


@dataclass
class VaultConfig:
    #: Absolute path of the folder to serve. Must sit outside the application
    #: directory -- the app refuses to start if the two overlap.
    root_path: str = "/data"

    #: URL prefix the files are exposed under. "" serves them at the site root,
    #: "/files" at https://host/files/<name>.
    request_path: str = ""

    #: While this is non-empty it is the whole policy: nothing outside it is
    #: served, and the block lists below never come into play. Matched against
    #: the final extension only.
    allowed_extensions: List[str] = field(default_factory=list)

    blocked_extensions: List[str] = field(default_factory=lambda: list(DEFAULT_BLOCKED_EXTENSIONS))
    blocked_file_names: List[str] = field(default_factory=lambda: list(DEFAULT_BLOCKED_FILE_NAMES))
    blocked_directories: List[str] = field(default_factory=lambda: list(DEFAULT_BLOCKED_DIRECTORIES))

    #: Serve files whose extension has no known type, using default_content_type.
    serve_unknown_file_types: bool = False
    default_content_type: str = "application/octet-stream"

    #: Render an HTML index when a folder rather than a file is requested.
    enable_directory_browsing: bool = False

    #: Send Content-Disposition: attachment so browsers download instead of
    #: rendering inline.
    force_download: bool = False

    #: Include dotfiles. Turning this on does not expose blocked names: ".env"
    #: and ".git*" are on the block list in their own right.
    include_hidden_files: bool = False

    #: Cache-Control max-age for served files. 0 sends no-cache instead.
    cache_max_age_seconds: int = 0

    #: Extra or overriding type mappings, e.g. {".log": "text/plain"}.
    content_type_mappings: Dict[str, str] = field(default_factory=dict)

    #: Match a request against the names on disk ignoring case when the exact
    #: spelling is not there. The vault came off NTFS, which is case-insensitive,
    #: so old links point at spellings the Linux filesystem does not have; without
    #: this they 404. Costs one extra stat per segment on a miss, and a cached
    #: directory index the first time a folder is reached by the wrong case.
    case_insensitive: bool = True

    #: Liveness endpoint. Reserved, so a file of this name can never shadow it.
    health_path: str = "/healthz"

    # ── loading ──────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, config_path: Optional[str] = None, environ: Optional[Dict[str, str]] = None) -> "VaultConfig":
        """Defaults, then the JSON file if there is one, then the environment."""
        environ = os.environ if environ is None else environ

        if config_path is None:
            config_path = environ.get("FILEVAULT_CONFIG", "")

        cfg = cls()

        if config_path:
            with open(config_path, "r", encoding="utf-8") as handle:
                cfg._apply_mapping(json.load(handle), source=config_path)

        cfg._apply_environment(environ)
        cfg._normalize()
        cfg.validate()

        return cfg

    def _apply_mapping(self, data: Dict[str, Any], source: str) -> None:
        known = {f.name: f for f in fields(self)}

        for key, value in data.items():
            # Keys starting with "//" are the comment convention carried over
            # from the appsettings.json this replaced.
            if key.startswith("//"):
                continue

            if key not in known:
                raise ConfigError("{0}: unknown setting '{1}'".format(source, key))

            setattr(self, key, value)

    def _apply_environment(self, environ: Dict[str, str]) -> None:
        for f in fields(self):
            raw = environ.get("FILEVAULT_" + f.name.upper())
            if raw is None:
                continue

            if f.type == "bool" or isinstance(getattr(self, f.name), bool):
                setattr(self, f.name, raw.strip().lower() in ("1", "true", "yes", "on"))
            elif isinstance(getattr(self, f.name), int):
                setattr(self, f.name, int(raw))
            elif isinstance(getattr(self, f.name), list):
                # Comma-separated. An empty value means an empty list, which for
                # allowed_extensions means "no allowlist" -- so it is spelled out
                # rather than arrived at by accident.
                setattr(self, f.name, [part.strip() for part in raw.split(",") if part.strip()])
            elif isinstance(getattr(self, f.name), dict):
                setattr(self, f.name, json.loads(raw))
            else:
                setattr(self, f.name, raw)

    def _normalize(self) -> None:
        self.allowed_extensions = [_as_extension(e) for e in self.allowed_extensions]
        self.blocked_extensions = [_as_extension(e) for e in self.blocked_extensions]
        self.blocked_file_names = [p.lower() for p in self.blocked_file_names]

        mappings = dict(BUILTIN_CONTENT_TYPES)
        for extension, content_type in self.content_type_mappings.items():
            mappings[_as_extension(extension)] = content_type
        self.content_type_mappings = mappings

        self.root_path = os.path.normpath(self.root_path) if self.root_path else self.root_path
        self.request_path = self.request_path.rstrip("/") if self.request_path != "/" else ""

    def validate(self) -> None:
        """Fail loudly rather than come up serving nothing."""
        failures: List[str] = []

        if not self.root_path.strip():
            failures.append("root_path is required.")
        elif not os.path.isabs(self.root_path):
            failures.append("root_path must be an absolute path, but was '{0}'.".format(self.root_path))

        if self.request_path and not self.request_path.startswith("/"):
            failures.append("request_path must start with '/' or be empty, but was '{0}'.".format(self.request_path))

        if not self.health_path.startswith("/"):
            failures.append("health_path must start with '/', but was '{0}'.".format(self.health_path))

        if failures:
            raise ConfigError(" ".join(failures))


def _as_extension(value: str) -> str:
    value = value.strip().lower()
    return value if value.startswith(".") else "." + value
