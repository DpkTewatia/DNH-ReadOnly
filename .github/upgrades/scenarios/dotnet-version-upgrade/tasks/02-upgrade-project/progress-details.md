# Task 02-upgrade-project: Progress Details

## Summary
Updated FileServe.csproj from `net8.0` to `net9.0` and verified the one behavioral
change flagged by the assessment — `UseForwardedHeaders()` — against a running
.NET 9 process. No source code changes were required.

## Changes Made
- `src/FileServe/FileServe.csproj` — `TargetFramework`: `net8.0` → `net9.0`
- `src/FileServe/Properties/PublishProfiles/FolderProfile.pubxml` — `TargetFramework`
  and `PublishUrl` updated to `net9.0`
- `README.md` — Hosting Bundle / SDK prerequisites and the 502.5 troubleshooting row
  now reference .NET 9, download link points at `dotnet/9.0`
- `deploy/Install-FileServe.ps1` — AspNetCoreModuleV2 preflight message now directs
  the operator to the .NET 9 Hosting Bundle

No changes to `Program.cs`, `FileVaultGuard.cs`, `FileVaultOptions.cs` or
`VaultFileProvider.cs` — all 640 lines compiled unchanged.

## Verification

### Build
`dotnet build FileServe.sln -c Release` → **0 errors, 0 warnings**
(`TreatWarningsAsErrors` is enabled, so a clean build is a meaningful signal here.)

`FileServe.runtimeconfig.json` confirms the produced app targets
`Microsoft.NETCore.App` / `Microsoft.AspNetCore.App` 9.0.

### Behavioral change: UseForwardedHeaders()
Ran the published .NET 9 binary against a scratch vault and exercised the middleware
directly. The refusal log line in `Program.cs` reports
`context.Connection.RemoteIpAddress`, which is what the middleware rewrites, so it
serves as the observation point.

Bound to loopback (`127.0.0.1:5199`) — the connection is a known proxy by default,
so forwarded headers are expected to apply:

| Request headers | Remote IP seen by the app |
| --- | --- |
| *(none)* | `127.0.0.1` (real connection) |
| `X-Forwarded-For: 203.0.113.45` | `203.0.113.45` |
| `X-Forwarded-For: 198.51.100.7, 203.0.113.45` | `203.0.113.45` (rightmost, ForwardLimit 1) |
| `X-Forwarded-For: 192.0.2.10` + `X-Forwarded-Proto: https` | `192.0.2.10` |
| `X-Forwarded-For: 192.0.2.99` + `X-Forwarded-Prefix: /files` | `192.0.2.99`, prefix ignored |

`X-Forwarded-Prefix` is correctly ignored: the app enables only
`XForwardedFor | XForwardedProto`, so the header does not become `PathBase` and the
request path is still evaluated as `/app.config`.

Bound to a non-loopback address (`192.168.1.43:5200`) to test the spoofing guard
described in the comment at `Program.cs:16-18`:

| Request headers | Remote IP seen by the app |
| --- | --- |
| `X-Forwarded-For: 203.0.113.45` | `192.168.1.43` — **spoofed value ignored** |

The loopback-only `KnownProxies` default still holds under .NET 9: a forwarded header
from a client that is not a known proxy is discarded. The security property the code
comment relies on is unchanged.

### Functional smoke test
| Request | Result |
| --- | --- |
| `GET /healthz` | 200, correct root and requestPath JSON |
| `GET /test.txt` | 200 |
| `GET /app.config` (blocked name pattern) | 404 |
| `POST /test.txt` | 405 with `Allow: GET, HEAD` |

## Issues Resolved
None — no incompatibilities surfaced. The assessment's prediction (0 incompatible
packages, 0 binary/source incompatible APIs, 1 behavioral change) held exactly.

## Build Status
Release build: **succeeded, 0 errors, 0 warnings**.
