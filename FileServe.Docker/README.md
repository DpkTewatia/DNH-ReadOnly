# FileServe.Docker

A containerised, read-only HTTP file server. It serves the images and `.txt` files in
a folder you mount into the container, and nothing else: the content policy is an
allowlist, so anything that is not an image or a text file is a 404 even if it sits in
the same folder.

This is the Linux/Docker sibling of the IIS deployment in [`../src/FileServe`](../src/FileServe).
The policy code (`FileVaultGuard`, `VaultFileProvider`, `FileVaultOptions`) is the same;
only `Program.cs` and the configuration differ, dropping the IIS pieces and defaulting
to a `/data` mount point.

This folder is also what CI deploys: the Jenkins pipeline for
**oldmedia.c-sharpcorner.com** (`jenkins-pipelines/ci/oldmedia.c-sharpcorner.com`)
builds this project with its own Dockerfile, mounts the host's media folder at
`/vault` instead of `/data`, and replaces `appsettings.json` with the config that
pipeline writes. Keep that in mind when changing the settings below — the
deployment does not read them.

## Quick start

```bash
cd FileServe.Docker

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

## Serving your own folder

Point the volume at the folder that holds the files, and keep the `:ro` suffix so the
container cannot write to it:

```yaml
volumes:
  - /srv/company-images:/data:ro     # Linux/macOS host
  - D:\SharedFiles:/data:ro          # Windows host
```

Nothing is baked into the image — the folder is read at request time, so files you add
to it appear immediately without a rebuild.

## Configuration

Every setting lives in the `FileVault` section of `src/FileServe/appsettings.json`, and
each one can be overridden by an environment variable using `__` as the section
separator (`FileVault__RequestPath`). The ones worth knowing:

| Setting | Default here | Notes |
| --- | --- | --- |
| `RootPath` | `/data` | The mount point inside the container. |
| `RequestPath` | `/files` | URL prefix. Set it to `""` to serve at the site root (`/sample.png`). |
| `AllowedExtensions` | images + `.txt` | The whole policy. Empty means "no allowlist", which falls back to the block lists only. |
| `EnableDirectoryBrowsing` | `true` | Set to `false` to require callers to know the exact file name. |
| `ForceDownload` | `false` | `true` sends `Content-Disposition: attachment`, so browsers download rather than render. |
| `CacheMaxAgeSeconds` | `3600` | `0` sends `no-cache` instead. |
| `IncludeHiddenFiles` | `false` | Dotfiles stay invisible; `.env` and friends are blocked by name regardless. |

Adding a file type is a one-line change, e.g. to also serve PDFs:

```yaml
environment:
  FileVault__AllowedExtensions__0: .png
  FileVault__AllowedExtensions__1: .jpg
  FileVault__AllowedExtensions__2: .txt
  FileVault__AllowedExtensions__3: .pdf
```

Overriding an array from the environment replaces it index by index, so list every
extension you want — it is usually clearer to edit `appsettings.json` instead.

`.svg` is deliberately not in the allowlist: an SVG can contain script, and serving one
inline runs that script on this origin. Add it only if you also set `ForceDownload`.

## What the server refuses

- Anything whose extension is not in `AllowedExtensions` → 404.
- `.env`, `web.config`, `appsettings*.json`, keys, archives of source, and the other
  built-in block lists in `FileVaultOptions.cs` → 404, even if the extension were allowed.
- `bin`, `obj`, `.git`, `node_modules` and similar folders → not traversed, and omitted
  from directory listings.
- Path traversal (`../`), reserved device names, and paths with characters that are not
  valid in a file name → 404.
- Anything that is not `GET` or `HEAD` → 405.

Refusals are logged with the reason and the caller's IP, and answered with 404 rather
than 403 so the response never confirms what exists on disk.

## Running it without compose

```bash
docker build -t fileserve .
docker run -d --name fileserve -p 8080:8080 \
  -v /srv/company-images:/data:ro \
  -e FileVault__RequestPath=/files \
  fileserve
```

## Behind a reverse proxy

`UseForwardedHeaders` is enabled but trusts loopback only, which is what you want by
default: a spoofed `X-Forwarded-For` from a real client is ignored. The cost is that a
proxy on another host is ignored too, so refusals are logged with the proxy's IP rather
than the caller's. To trust a specific proxy, add it in `Program.cs`:

```csharp
builder.Services.Configure<ForwardedHeadersOptions>(o =>
{
    o.ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto;
    o.KnownNetworks.Add(new IPNetwork(IPAddress.Parse("10.0.0.0"), 8));  // your proxy's network
});
```

TLS belongs at the proxy — the container speaks plain HTTP on 8080 by design.

## Notes on the image

- Multi-stage build on `dotnet/sdk:8.0-alpine`, running on `dotnet/aspnet:8.0-alpine`.
  Alpine is safe because the app sets `InvariantGlobalization`, so it needs no ICU.
- Runs as the non-root `app` user (uid 1654) that the .NET base images ship with, with
  a read-only root filesystem, all capabilities dropped and `no-new-privileges`.
- `HEALTHCHECK` polls `/healthz` every 30s, so `docker ps` reports the container
  unhealthy if the mount disappears or the app stops responding.
- If the mounted folder is missing or unreadable by uid 1654, the app logs the reason
  and exits at startup instead of 404-ing every request. On a Linux host that usually
  means the folder needs `chmod o+rx` (or a matching `user:` in compose).

## Local development without Docker

```bash
cd src/FileServe
FileVault__RootPath=$(pwd)/../../files dotnet run
```

Needs the .NET 8 runtime. On a machine that only has a newer one, add
`DOTNET_ROLL_FORWARD=LatestMajor` to that command — the container always has the
matching runtime, so this only affects local runs.
