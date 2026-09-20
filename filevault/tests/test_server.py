"""The server end to end, against a real folder on disk."""

import os

import pytest
from starlette.testclient import TestClient

from app.config import ConfigError, VaultConfig
from app.main import create_app

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415408d76360f8cf000001030100184ddd8f0000000049454e44ae426082"
)


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "photo.png").write_bytes(PNG)
    (tmp_path / "notes.txt").write_text("old media text\n")
    (tmp_path / "web.config").write_text("<configuration/>")
    (tmp_path / ".env").write_text("SECRET=1")
    (tmp_path / "report.pdf").write_text("%PDF-1.4")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "tool.png").write_bytes(PNG)
    return tmp_path


def client(vault, **overrides):
    settings = dict(
        root_path=str(vault),
        allowed_extensions=[".png", ".txt"],
        content_type_mappings={".png": "image/png", ".txt": "text/plain; charset=utf-8"},
        cache_max_age_seconds=3600,
    )
    settings.update(overrides)

    config = VaultConfig(**settings)
    config._normalize()
    config.validate()

    return TestClient(create_app(config))


# ── serving ──────────────────────────────────────────────────────────────────

def test_serves_an_allowlisted_image(vault):
    response = client(vault).get("/images/photo.png")

    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "public,max-age=3600"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_serves_text(vault):
    response = client(vault).get("/notes.txt")

    assert response.status_code == 200
    assert response.text == "old media text\n"
    assert response.headers["content-type"] == "text/plain; charset=utf-8"


def test_head_returns_the_headers_without_a_body(vault):
    response = client(vault).head("/images/photo.png")

    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["content-length"] == str(len(PNG))


def test_range_request_returns_partial_content(vault):
    response = client(vault).get("/images/photo.png", headers={"range": "bytes=0-7"})

    assert response.status_code == 206
    assert response.content == PNG[:8]


def test_conditional_request_returns_304(vault):
    first = client(vault).get("/images/photo.png")
    etag = first.headers["etag"]

    second = client(vault).get("/images/photo.png", headers={"if-none-match": etag})

    assert second.status_code == 304
    assert second.content == b""


def test_missing_file_is_a_json_404(vault):
    response = client(vault).get("/images/nope.png")

    assert response.status_code == 404
    assert response.json()["message"] == "File not found."


def test_only_get_and_head_are_allowed(vault):
    response = client(vault).post("/notes.txt")

    assert response.status_code == 405
    assert "GET" in response.headers["allow"]


# ── refusals ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "path",
    [
        "/web.config",          # blocked name and blocked extension
        "/.env",                # blocked name, and hidden
        "/report.pdf",          # not in the allowlist
        "/bin/tool.png",        # blocked folder
        "/images/",             # directory browsing is off
        "/",                    # ditto, at the root
    ],
)
def test_refused_paths_are_404(vault, path):
    assert client(vault).get(path).status_code == 404


def test_traversal_out_of_the_vault_is_refused(vault, tmp_path):
    (tmp_path.parent / "outside.png").write_bytes(PNG)

    # The client normalises "..", so the encoded form is what actually reaches
    # the app; both must be refused.
    assert client(vault).get("/../outside.png").status_code == 404
    assert client(vault).get("/%2e%2e/outside.png").status_code == 404


def test_symlink_pointing_out_of_the_vault_is_refused(vault, tmp_path):
    secret = tmp_path.parent / "secret.png"
    secret.write_bytes(PNG)
    os.symlink(str(secret), str(vault / "link.png"))

    assert client(vault).get("/link.png").status_code == 404


def test_symlink_inside_the_vault_still_works(vault):
    os.symlink(str(vault / "images" / "photo.png"), str(vault / "alias.png"))

    assert client(vault).get("/alias.png").status_code == 200


def test_unknown_type_is_refused_rather_than_guessed(vault):
    (vault / "thing.xyz").write_text("data")
    no_allowlist = client(vault, allowed_extensions=[])

    assert no_allowlist.get("/thing.xyz").status_code == 404

    guessing = client(vault, allowed_extensions=[], serve_unknown_file_types=True)
    response = guessing.get("/thing.xyz")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/octet-stream")


# ── reserved health path ─────────────────────────────────────────────────────

def test_health_reports_the_vault(vault):
    body = client(vault).get("/healthz").json()

    assert body["status"] == "ok"
    assert body["root"] == os.path.realpath(str(vault))


def test_a_file_named_healthz_cannot_shadow_the_health_endpoint(vault):
    (vault / "healthz").write_text("not the health endpoint")

    assert client(vault).get("/healthz").json()["status"] == "ok"


# ── request path prefix ──────────────────────────────────────────────────────

def test_request_path_moves_the_vault_under_a_prefix(vault):
    prefixed = client(vault, request_path="/files")

    assert prefixed.get("/files/notes.txt").status_code == 200
    assert prefixed.get("/notes.txt").status_code == 404
    assert prefixed.get("/healthz").status_code == 200


# ── directory browsing ───────────────────────────────────────────────────────

def test_directory_listing_hides_what_it_cannot_serve(vault):
    browsing = client(vault, enable_directory_browsing=True)
    body = browsing.get("/").text

    assert "notes.txt" in body
    assert "images/" in body
    assert "web.config" not in body
    assert "report.pdf" not in body
    assert "bin" not in body


def test_directory_without_a_trailing_slash_redirects(vault):
    browsing = client(vault, enable_directory_browsing=True)
    response = browsing.get("/images", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/images/"


# ── force download ───────────────────────────────────────────────────────────

def test_force_download_sends_an_attachment(vault):
    response = client(vault, force_download=True).get("/notes.txt")

    assert response.headers["content-disposition"].startswith("attachment")
    assert "notes.txt" in response.headers["content-disposition"]


# ── startup ──────────────────────────────────────────────────────────────────

def test_a_missing_vault_fails_at_startup(tmp_path):
    config = VaultConfig(root_path=str(tmp_path / "nope"))

    with pytest.raises(ConfigError) as error:
        create_app(config)

    assert "does not exist" in str(error.value)


def test_a_vault_that_overlaps_the_application_is_refused():
    config = VaultConfig(root_path=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    with pytest.raises(ConfigError) as error:
        create_app(config)

    assert "overlaps the application directory" in str(error.value)
