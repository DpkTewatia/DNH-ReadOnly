"""The policy rules, tested on their own: no disk, no HTTP."""

import pytest

from app.config import VaultConfig
from app.guard import is_servable


def cfg(**overrides):
    config = VaultConfig(root_path="/vault", **overrides)
    config._normalize()
    return config


@pytest.mark.parametrize(
    "path",
    [
        "/photo.png",
        "/2012/07/logo.png",
        "/notes.txt",
        "/a folder/with spaces.png",
        "/",
        "",
    ],
)
def test_ordinary_paths_pass(path):
    assert is_servable(path, cfg(), False) is None


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/../etc/passwd", "path traversal"),
        ("/sub/../../x.png", "path traversal"),
        ("/./x.png", "path traversal"),
        ("/web.config.", "dot or space"),
        ("/trailing .png ", "dot or space"),
        ("/con.png", "reserved device name"),
        ("/sub/aux", "reserved device name"),
        ("/back\\slash.png", "not valid in a file name"),
        ("/colon:name.png", "not valid in a file name"),
        ("/star*.png", "not valid in a file name"),
    ],
)
def test_structurally_unsafe_paths_are_refused(path, expected):
    reason = is_servable(path, cfg(), False)
    assert reason is not None and expected in reason


@pytest.mark.parametrize(
    "path",
    [
        "/run.sh",
        "/app.dll",
        "/web.config",
        "/dump.sql.bak",
        "/id_rsa",
        "/appsettings.Production.json",
        "/secrets.json",
        "/site.key",
        "/backup.old",
    ],
)
def test_block_lists_refuse_sensitive_files(path):
    assert is_servable(path, cfg(), False) is not None


def test_every_suffix_is_checked_not_only_the_last():
    # A name ending in something harmless does not get the file past the
    # extension rules: each dot-separated suffix is checked, not just the last.
    assert is_servable("/web.config.png", cfg(), False) is not None
    assert is_servable("/site.key.png", cfg(), False) is not None
    assert is_servable("/dump.sqlite.txt", cfg(), False) is not None


def test_name_patterns_match_the_whole_name_only():
    # Deliberate, and inherited from the .NET policy this replaces:
    # "appsettings*.json" matches the file itself, not a copy of it renamed to
    # an image. ".json" is not a blocked extension, so this one is served --
    # which is harmless, because what comes back is typed as the .png it is.
    assert is_servable("/appsettings.json", cfg(), False) is not None
    assert is_servable("/appsettings.json.png", cfg(), False) is None


@pytest.mark.parametrize("path", ["/bin/x.png", "/node_modules/a/b.png", "/.git/config.png", "/obj/x.png"])
def test_blocked_directories_are_never_traversed(path):
    assert is_servable(path, cfg(), False) is not None


def test_allowlist_is_the_whole_policy_when_set():
    config = cfg(allowed_extensions=[".png", ".txt"])

    assert is_servable("/a.png", config, False) is None
    assert is_servable("/a.txt", config, False) is None
    assert is_servable("/a.pdf", config, False) is not None
    assert is_servable("/a.bmp", config, False) is not None
    assert is_servable("/noextension", config, False) is not None


def test_allowlist_matches_the_last_extension_only_and_ignores_case():
    config = cfg(allowed_extensions=[".PNG"])

    assert is_servable("/a.png", config, False) is None
    assert is_servable("/a.PnG", config, False) is None
    # Still subject to the block lists: ".config" is one of them.
    assert is_servable("/web.config.png", config, False) is not None


def test_blocked_names_still_apply_inside_an_allowlist():
    config = cfg(allowed_extensions=[".json"])
    assert is_servable("/appsettings.json", config, False) is not None


def test_hidden_files_follow_the_flag():
    assert is_servable("/.hidden.png", cfg(), False) is not None
    assert is_servable("/.well-known/x.png", cfg(), False) is not None
    assert is_servable("/.hidden.png", cfg(include_hidden_files=True), False) is None


def test_last_segment_is_judged_as_a_folder_when_the_caller_says_so():
    # "id_rsa" is refused as a file name, but a folder of that name is only
    # judged against the folder rules.
    assert is_servable("/id_rsa", cfg(), True) is None
    assert is_servable("/id_rsa", cfg(), False) is not None

    # A trailing slash is an unambiguous folder request whatever the caller says.
    assert is_servable("/id_rsa/", cfg(), False) is None
