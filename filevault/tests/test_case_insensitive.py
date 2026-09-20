"""Requests whose casing differs from the disk still find the file.

The vault came off NTFS, where case never mattered, so old links use whatever
spelling the page author typed. On the Linux deploy host those paths do not
exist as written.

macOS is case-insensitive, so on a developer machine the exact-spelling stat
succeeds for any casing and the fallback never runs. `case_sensitive_vault`
overrides the one stat the resolver uses, which makes the Mac behave like the
deploy host and exercises the code that actually matters there.
"""

import os

import pytest
from starlette.testclient import TestClient

from app.config import VaultConfig
from app.main import create_app
from app.vault import Vault

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415408d76360f8cf000001030100184ddd8f0000000049454e44ae426082"
)


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "UploadFile" / "2012").mkdir(parents=True)
    (tmp_path / "UploadFile" / "2012" / "Logo.PNG").write_bytes(PNG)
    (tmp_path / "UploadFile" / "ReadMe.txt").write_text("notes\n")
    (tmp_path / "Web.Config").write_text("<configuration/>")
    return tmp_path


def skip_unless_filesystem_is_case_sensitive(tmp_path):
    """Two names differing only by case have to be able to coexist.

    They cannot on macOS, where the second write lands in the first file, so the
    tests that need both skip here and run on the Linux deploy host.
    """
    (tmp_path / "case_probe").write_text("lower")
    (tmp_path / "CASE_PROBE").write_text("upper")

    both_exist = (tmp_path / "case_probe").read_text() == "lower"

    (tmp_path / "case_probe").unlink()
    if both_exist:
        (tmp_path / "CASE_PROBE").unlink()

    if not both_exist:
        pytest.skip("filesystem is case-insensitive; this needs two names differing only by case")


def case_sensitive_vault(monkeypatch):
    """Make Vault._exists agree only with the exact spelling on disk."""

    def exact_only(self, path):
        if not os.path.lexists(path):
            return False

        # Walk back up, checking each component against the real listing, so a
        # path differing only in case reports missing the way Linux would.
        parts = []
        current = path
        while current.startswith(self.root) and current != self.root:
            current, name = os.path.split(current)
            parts.append(name)

        current = self.root
        for name in reversed(parts):
            try:
                if name not in os.listdir(current):
                    return False
            except OSError:
                return False
            current = os.path.join(current, name)

        return True

    monkeypatch.setattr(Vault, "_exists", exact_only)


def client(vault, **overrides):
    settings = dict(
        root_path=str(vault),
        allowed_extensions=[".png", ".txt"],
        content_type_mappings={".png": "image/png", ".txt": "text/plain; charset=utf-8"},
    )
    settings.update(overrides)

    config = VaultConfig(**settings)
    config._normalize()
    config.validate()

    return TestClient(create_app(config))


# ── the fallback itself, independent of the host filesystem ──────────────────

def test_find_folded_returns_the_name_on_disk(vault):
    v = Vault(VaultConfig(root_path=str(vault)))

    assert v.find_folded(str(vault), "uploadfile") == "UploadFile"
    assert v.find_folded(str(vault), "UPLOADFILE") == "UploadFile"
    assert v.find_folded(str(vault), "UploadFile") == "UploadFile"
    assert v.find_folded(str(vault), "nothing-like-this") is None


def test_locate_walks_every_segment(vault, monkeypatch):
    case_sensitive_vault(monkeypatch)
    v = Vault(VaultConfig(root_path=str(vault)))

    located = v.locate(["uploadfile", "2012", "logo.png"])

    assert located is not None
    assert os.path.basename(located) == "Logo.PNG"
    assert os.path.exists(located)


def test_locate_prefers_the_exact_spelling(vault, monkeypatch):
    skip_unless_filesystem_is_case_sensitive(vault)
    # Two names differing only by case; the exactly-spelled request must not be
    # answered with the other one.
    (vault / "UploadFile" / "note.txt").write_text("lower\n")
    (vault / "UploadFile" / "NOTE.txt").write_text("upper\n")
    case_sensitive_vault(monkeypatch)

    v = Vault(VaultConfig(root_path=str(vault)))

    assert open(v.locate(["UploadFile", "note.txt"])).read() == "lower\n"
    assert open(v.locate(["UploadFile", "NOTE.txt"])).read() == "upper\n"


def test_locate_is_deterministic_when_only_case_differs(vault, monkeypatch):
    skip_unless_filesystem_is_case_sensitive(vault)
    (vault / "UploadFile" / "note.txt").write_text("lower\n")
    (vault / "UploadFile" / "NOTE.txt").write_text("upper\n")
    case_sensitive_vault(monkeypatch)

    v = Vault(VaultConfig(root_path=str(vault)))
    picked = {os.path.basename(v.locate(["UploadFile", "NoTe.TxT"])) for _ in range(5)}

    assert len(picked) == 1


def test_locate_returns_none_when_nothing_matches(vault, monkeypatch):
    case_sensitive_vault(monkeypatch)
    v = Vault(VaultConfig(root_path=str(vault)))

    assert v.locate(["uploadfile", "2012", "missing.png"]) is None


def test_the_flag_turns_it_off(vault, monkeypatch):
    case_sensitive_vault(monkeypatch)
    v = Vault(VaultConfig(root_path=str(vault), case_insensitive=False))

    assert v.locate(["uploadfile", "2012", "logo.png"]) is None
    assert v.locate(["UploadFile", "2012", "Logo.PNG"]) is not None


# ── through the server ───────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "path",
    [
        "/UploadFile/2012/Logo.PNG",   # exactly as stored
        "/uploadfile/2012/logo.png",   # all lower
        "/UPLOADFILE/2012/LOGO.PNG",   # all upper
        "/UploadFile/2012/logo.PNG",   # mixed
    ],
)
def test_any_casing_serves_the_image(vault, monkeypatch, path):
    case_sensitive_vault(monkeypatch)
    response = client(vault).get(path)

    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"


def test_case_folding_does_not_open_a_way_past_the_policy(vault, monkeypatch):
    case_sensitive_vault(monkeypatch)
    c = client(vault)

    # Web.Config is on disk; no casing of it may be served, whether or not the
    # requested spelling matches. The block lists were already case-insensitive
    # -- this proves the folded lookup did not route around them.
    assert c.get("/Web.Config").status_code == 404
    assert c.get("/web.config").status_code == 404
    assert c.get("/WEB.CONFIG").status_code == 404


def test_request_path_prefix_ignores_case(vault, monkeypatch):
    case_sensitive_vault(monkeypatch)
    c = client(vault, request_path="/files")

    assert c.get("/files/UploadFile/ReadMe.txt").status_code == 200
    assert c.get("/Files/uploadfile/readme.txt").status_code == 200
    assert c.get("/FILES/UPLOADFILE/README.TXT").status_code == 200
