"""The content policy: which paths, folders and file names may leave the vault.

Applied twice, as it was in the .NET original. Once against the spelling in the
URL, so a refusal is logged before anything touches the disk, and once against
the resolved path with definite knowledge of whether the target is a file or a
folder. The second pass is what catches a symlink pointing at a blocked name,
and, on a case-insensitive filesystem, a request whose spelling differs from the
name on disk.

Every function returns None when the path may be served, or a short reason when
it may not. The reason is for the log, never for the response: refusals are
answered with 404 so the response does not confirm what exists on disk.
"""

from __future__ import annotations

import fnmatch
import posixpath
from typing import List, Optional

from .config import VaultConfig

# The URL separator is "/", so a literal backslash is always suspect; NUL
# truncates the path in some downstream APIs; the rest are not valid in a file
# name on Windows, which is where this vault's contents came from.
FORBIDDEN_CHARS = frozenset('<>|*:"\\\x00')

# Kept from the Windows original deliberately: these names still address devices
# if the vault is ever served from, or synchronised to, a Windows host. The cost
# is that a genuine "aux.png" is refused, which has not happened yet.
RESERVED_DEVICE_NAMES = frozenset(
    ["con", "prn", "aux", "nul"]
    + ["com{0}".format(i) for i in range(1, 10)]
    + ["lpt{0}".format(i) for i in range(1, 10)]
)


def is_servable(sub_path: str, config: VaultConfig, treat_last_segment_as_directory: bool) -> Optional[str]:
    """Check a whole request path against the policy.

    ``sub_path`` is the decoded path relative to the vault root, e.g.
    "/reports/q1.pdf". Callers that cannot tell whether the last segment is a
    file or a folder should pass True -- the resolver re-checks with the real
    answer before anything is served.
    """
    if not sub_path or sub_path == "/":
        return None

    for char in sub_path:
        if char in FORBIDDEN_CHARS:
            return "path contains a character that is not valid in a file name"

    segments = [s for s in sub_path.split("/") if s]
    if not segments:
        return None

    # A trailing slash is an unambiguous folder request.
    last_is_directory = treat_last_segment_as_directory or sub_path.endswith("/")

    for index, segment in enumerate(segments):
        reason = _structural_refusal(segment)
        if reason is not None:
            return reason

        is_last = index == len(segments) - 1

        if not is_last or last_is_directory:
            if is_blocked_directory_name(segment, config):
                return "folder '{0}' is in blocked_directories".format(segment)
        else:
            reason = file_name_refusal(segment, config)
            if reason is not None:
                return reason

    if not config.include_hidden_files:
        for segment in segments:
            if segment.startswith("."):
                return "'{0}' is hidden and include_hidden_files is off".format(segment)

    return None


def _structural_refusal(segment: str) -> Optional[str]:
    """Path-shape checks that apply to folders and files alike."""
    if segment in (".", ".."):
        return "path traversal"

    # "web.config." and "web.config " both resolve to "web.config" on Windows,
    # which would otherwise sidestep every name and extension rule below.
    if segment.endswith(".") or segment.endswith(" "):
        return "path segment ends with a dot or space"

    stem = segment.split(".", 1)[0].lower()
    if stem in RESERVED_DEVICE_NAMES:
        return "path segment '{0}' is a reserved device name".format(segment)

    return None


def is_blocked_directory_name(name: str, config: VaultConfig) -> bool:
    lowered = name.lower()
    return any(lowered == blocked.lower() for blocked in config.blocked_directories)


def file_name_refusal(name: str, config: VaultConfig) -> Optional[str]:
    """Apply the allowlist, then the name block list, then the extension list."""
    extension = posixpath.splitext(name)[1].lower()

    if config.allowed_extensions and extension not in config.allowed_extensions:
        if not extension:
            return "file has no extension and allowed_extensions is set"
        return "extension '{0}' is not in allowed_extensions".format(extension)

    lowered = name.lower()
    for pattern in config.blocked_file_names:
        # fnmatchcase against two lowered strings rather than fnmatch, whose
        # case sensitivity follows the host filesystem and would make this
        # policy behave differently on the developer's Mac and on the server.
        if fnmatch.fnmatchcase(lowered, pattern):
            return "name matches blocked_file_names pattern '{0}'".format(pattern)

    # Every suffix is checked, not just the last, so "web.config.bak" and
    # "appsettings.json.old" are caught by ".config" and by the name patterns.
    parts = lowered.split(".")
    blocked = set(config.blocked_extensions)
    for part in parts[1:]:
        if "." + part in blocked:
            return "extension '.{0}' is in blocked_extensions".format(part)

    return None


def visible_entries(names: List[str], config: VaultConfig, is_directory) -> List[str]:
    """Filter a directory listing, so it never names a file it cannot serve."""
    visible = []

    for name in sorted(names):
        if not config.include_hidden_files and name.startswith("."):
            continue

        if is_directory(name):
            if not is_blocked_directory_name(name, config) and _structural_refusal(name) is None:
                visible.append(name)
        elif _structural_refusal(name) is None and file_name_refusal(name, config) is None:
            visible.append(name)

    return visible
