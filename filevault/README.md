# FileVault

A containerised, read-only HTTP file server. It serves the images and `.txt`
files in a folder you mount into the container, and nothing else: the content
policy is an allowlist, so anything that is not an allowed type is a 404 even if
it sits in the same folder.

This is the Python replacement for the containerised .NET file server. The IIS
deployment in [`../src/FileServe`](../src/FileServe) is unchanged and still the
Windows story; this folder is what runs in Docker, and what CI deploys to
**oldmedia.c-sharpcorner.com** (`jenkins-pipelines/ci/oldmedia.c-sharpcorner.com`).

## Quick start

```bash
cd filevault

# Put your own content in ./files (or edit the volume in docker-compose.yml)
docker compose up --build
```

Then:

| URL | What it returns |
| --- | --- |
| http://localhost:8080/files/ | Directory listing of the mounted folder |
| http://localhost:8080/files/hello.txt | The text file |
| http://localhost:8080/files/images/sample.png | The image |
| http://localhost:8080/healthz | `{"status":"ok",...}` — used by the container health check |

Fetching from a script is an ordinary GET:

```bash
curl -O http://localhost:8080/files/images/sample.png
curl http://localhost:8080/files/hello.txt
```

Range requests, `ETag`/`Last-Modified` and conditional GETs all work, so large
files resume and video seeks; a repeat request with `If-None-Match` gets a 304.

## Serving your own folder

Point the volume at the folder that holds the files, and keep the `:ro` suffix
so the container cannot write to it:

```yaml
volumes:
  - /srv/company-images:/data:ro     # Linux/macOS host
  - D:\SharedFiles:/data:ro          # Windows host
```

Nothing is baked into the image — the folder is read at request time, so files
you add to it appear immediately without a rebuild.

## Configuration

Settings are the fields of `VaultConfig` in [`app/config.py`](app/config.py),
applied in three layers: built-in defaults, then a JSON file if one is given
(`FILEVAULT_CONFIG=/app/config.json`, which is how the deploy pipeline injects
its settings — see [`config.example.json`](config.example.json)), then
environment variables.

An environment variable is `FILEVAULT_` plus the field name in upper case. Lists
are comma-separated, maps are JSON, booleans are `true`/`false`.

| Setting | Default | Notes |
| --- | --- | --- |
| `root_path` | `/data` | The mount point inside the container. |
| `request_path` | `""` | URL prefix. `docker-compose.yml` sets `/files`; empty serves at the site root. |
| `allowed_extensions` | none | **The whole policy when set.** Empty means block-lists only. |
| `enable_directory_browsing` | `false` | On, a folder URL returns an index listing only what it can serve. |
| `force_download` | `false` | `true` sends `Content-Disposition: attachment`. |
| `cache_max_age_seconds` | `0` | `0` sends `no-cache` instead. |
| `serve_unknown_file_types` | `false` | Off, an extension with no known type is refused rather than guessed. |
| `include_hidden_files` | `false` | Dotfiles stay invisible; `.env` and friends are blocked by name regardless. |
| `health_path` | `/healthz` | Reserved — a file of this name can never shadow it. |

```bash
# Add a type: list every extension you want, the variable replaces the list.
FILEVAULT_ALLOWED_EXTENSIONS=".png,.jpg,.txt,.pdf"
```

`.svg` is deliberately not in the sample allowlist: an SVG can contain script,
and serving one inline runs that script on this origin. Add it only behind a
`Content-Security-Policy` that neuters it, or with `force_download` on.

## What the server refuses

- Anything whose extension is not in `allowed_extensions` → 404.
- `.env`, `web.config`, `appsettings*.json`, keys, source files and the other
  block lists in [`app/config.py`](app/config.py) → 404, even if the extension
  would otherwise be allowed. Every dot-separated suffix is checked, so
  `web.config.png` is refused for containing `.config`.
- `bin`, `obj`, `.git`, `node_modules` and similar folders → not traversed, and
  omitted from listings.
- Path traversal, paths with characters that are not valid in a file name,
  segments ending in a dot or space, and Windows device names → 404.
- A symlink whose target resolves outside the vault → 404.
- Anything that is not `GET` or `HEAD` → 405.

Refusals are logged with the reason and the caller's IP, and answered with 404
rather than 403 so the response never confirms what exists on disk. The policy
is applied twice — once against the spelling in the URL, once against the
resolved path — which is what catches a link pointing at a blocked name.

## Tests

The policy is the part worth testing, so it is tested on its own as well as
through the server:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest            # 61 tests
```

[`tests/test_guard.py`](tests/test_guard.py) covers the rules in isolation;
[`tests/test_server.py`](tests/test_server.py) runs them through real requests
against a temporary folder — range requests, conditional GETs, symlink escapes,
the reserved health path, and directory listings that hide what they cannot
serve.

## Running it without compose

```bash
docker build -t filevault .
docker run -d --name filevault -p 8080:8080 \
  -v /srv/company-images:/data:ro \
  -e FILEVAULT_REQUEST_PATH=/files \
  filevault
```

Or without Docker at all:

```bash
pip install -r requirements.txt
FILEVAULT_ROOT_PATH=$(pwd)/files uvicorn app.asgi:app --port 8080
```

## Behind a reverse proxy

The container speaks plain HTTP on 8080 and binds to loopback on the host; TLS
and the public vhost belong at nginx. uvicorn runs with `--proxy-headers` and
`FORWARDED_ALLOW_IPS=*`, which is safe **only** because the published port is
`127.0.0.1`-only and nginx is the sole route in. If you ever publish the port
publicly, set `FORWARDED_ALLOW_IPS` to the proxy's address, or the caller IP in
the refusal log becomes whatever the caller claims.

## Notes on the image

- `python:3.12-slim`, no build stage: ~120MB, and a rebuild is a `pip install`
  rather than a .NET SDK restore and publish.
- Runs as uid 1654 with a read-only root filesystem, all capabilities dropped
  and `no-new-privileges`. The mounted folder must be readable by that uid.
- `HEALTHCHECK` polls `/healthz` with the interpreter that is already in the
  image, so no curl or wget has to be installed.
- If the mounted folder is missing or unreadable, the app exits at startup with
  the reason instead of 404-ing every request. On a Linux host that usually
  means the folder needs `chmod o+rx`.
- Content typing uses Python's built-in table only — the system `mime.types`
  files are deliberately not read, so a file is typed the same on a developer's
  machine as in the image. Anything the table does not know goes in
  `content_type_mappings`.
