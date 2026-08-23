# FileServe

An ASP.NET Core application for IIS that serves files from a folder **outside** the
application directory.

```
GET https://files.contoso.com/files/reports/2026/q1.csv
                              └── RequestPath      └── path inside the vault

                    reads  D:\SharedFiles\reports\2026\q1.csv
                           └── FileVault:RootPath
```

The application is deployed to `C:\inetpub\FileServe`; the files it serves live
somewhere else entirely and are never copied into the site.

## Requirements

* Windows Server with the IIS role installed
* **.NET 8 Hosting Bundle** on the server — not just the runtime. The Hosting Bundle
  is what registers `AspNetCoreModuleV2` with IIS.
  <https://dotnet.microsoft.com/download/dotnet/8.0> → *Hosting Bundle*
* .NET 8 SDK, if you publish on the server rather than copying a build across

## Deploy

From an **elevated** PowerShell session, in a checkout of this repository:

```powershell
cd deploy
.\Install-FileServe.ps1 -VaultPath D:\SharedFiles -Hostname files.contoso.com
```

That script publishes the app, creates the IIS site and app pool, writes `RootPath`
into the published `appsettings.json`, and grants the app pool identity read access
to the vault folder. It is idempotent — re-run it to deploy an update.

Verify:

```powershell
curl http://files.contoso.com/healthz
curl http://files.contoso.com/files/some-file.pdf
```

`/healthz` echoes back the resolved root path, which is the fastest way to confirm
the app is reading the configuration you think it is.

### HTTPS

The install script creates an HTTP binding only. Add TLS once the certificate is in
the machine store:

```powershell
New-WebBinding -Name FileServe -Protocol https -Port 443 -HostHeader files.contoso.com -SslFlags 1
```

## Configuration

All settings live under the `FileVault` section of `appsettings.json`:

| Setting | Default | Purpose |
| --- | --- | --- |
| `RootPath` | *(required)* | Absolute path of the folder to serve |
| `RequestPath` | `/files` | URL prefix. `""` serves the vault at the site root |
| `AllowedExtensions` | `[]` | If non-empty, an allowlist — nothing else is served |
| `BlockedExtensions` | `.config .exe .dll .ps1 .bat .cmd .pfx .key` | Never served |
| `EnableDirectoryBrowsing` | `false` | Render an HTML index for folder URLs |
| `ForceDownload` | `false` | Send `Content-Disposition: attachment` |
| `ServeUnknownFileTypes` | `true` | Serve extensions with no known MIME type |
| `DefaultContentType` | `application/octet-stream` | Used when the type is unknown |
| `ContentTypeMappings` | `{ ".log": "text/plain" }` | Add or override MIME types |
| `IncludeHiddenFiles` | `false` | Include hidden/system files |
| `CacheMaxAgeSeconds` | `0` | `Cache-Control: max-age`. `0` sends `no-cache` |
| `HealthPath` | `/healthz` | Reserved; a file of this name can never shadow it |

Backslashes are escape characters in JSON, so Windows paths must be doubled:

```json
{
  "FileVault": {
    "RootPath": "D:\\SharedFiles",
    "RequestPath": "/files",
    "AllowedExtensions": [ ".pdf", ".csv", ".png" ]
  }
}
```

Forward slashes also work (`"D:/SharedFiles"`) and avoid the escaping entirely.

Any setting can be overridden without editing the file, using `__` as the nesting
separator — as an environment variable in `web.config`:

```xml
<environmentVariable name="FileVault__RootPath" value="D:\SharedFiles" />
```

### Serving at the site root

Set `RequestPath` to an empty string and files answer directly under the domain:

```
https://files.contoso.com/reports/2026/q1.csv  ->  D:\SharedFiles\reports\2026\q1.csv
```

## Permissions

This is the step that breaks most deployments. The app pool runs as the virtual
account `IIS AppPool\FileServe`, which has no access to `D:\SharedFiles` until granted:

```powershell
.\deploy\Grant-VaultAccess.ps1 -VaultPath D:\SharedFiles -AppPoolName FileServe
```

**A UNC path needs different handling.** `IIS AppPool\...` is a machine-local account
and cannot authenticate to another server, so NTFS ACLs on the share will not help.
Either run the pool as a domain account with share and NTFS read access, or keep a
local copy and point `RootPath` at that.

## Security

The application is read-only — anything other than `GET` and `HEAD` returns `405`.

Requests are checked before any disk access ([FileVaultGuard.cs](src/FileServe/FileVaultGuard.cs)),
and rejections return `404` rather than `403` so responses never confirm what exists
on disk. Blocked: path traversal, backslashes and NUL in the path, alternate data
stream syntax (`file.txt::$DATA`), reserved DOS device names (`CON`, `LPT1`, …),
segments with trailing dots or spaces (which Windows silently strips, sidestepping
the extension policy), and anything failing the extension allow/block lists.

Note that `RootPath` is served **in full**, including every subfolder. Point it at a
folder that holds only what should be public, and set `AllowedExtensions` when the
answer is "only PDFs".

There is no authentication. To require a login, enable Windows Authentication on the
site in IIS, or put the app behind whatever gateway you already run.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| **500.19** | `web.config` unreadable, or the Hosting Bundle is not installed |
| **500.30** | App failed to start — usually `RootPath` missing or not readable |
| **502.5** | Worker process crashed, or the installed runtime is not .NET 8 |
| **404.11** | A file name contains `%`; set `allowDoubleEscaping="true"` in `web.config` |
| **404 on every file** | `RootPath` wrong, or the app pool identity lacks access |
| **404 on one folder** | IIS hidden segments — `web.config` already unblocks `bin`/`App_Data` |

The startup log names the resolved root path and the identity in play. To capture it,
set `stdoutLogEnabled="true"` in [web.config](src/FileServe/web.config), create a
`logs` folder in the app directory, reproduce, then read `logs\stdout_*.log`.
Turn it back off afterwards — it grows without bound.

## Local development

```powershell
dotnet run --project src\FileServe
```

Uses `appsettings.Development.json`, which serves `C:\Temp\SharedFiles` at
<http://localhost:5080/files> with directory browsing on.

## Layout

```
src/FileServe/
  Program.cs             pipeline: health -> guard -> static files -> 404
  FileVaultOptions.cs    configuration model and startup validation
  FileVaultGuard.cs      path and extension checks, ahead of disk access
  web.config             IIS handler, request filtering, error pass-through
deploy/
  Install-FileServe.ps1  publish + create site/pool + permissions
  Grant-VaultAccess.ps1  grant the pool identity access to the vault
```

## Why an application rather than a virtual directory

An IIS virtual directory pointing at `D:\SharedFiles` also serves files from outside
the site, with no code. Choose this application instead when you want the extension
allow/block policy, the hardened path checks, structured logging of refusals, forced
downloads, or a place to add authentication and per-file rules later. For simply
exposing a folder wholesale, a virtual directory is less to maintain.
