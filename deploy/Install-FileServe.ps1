<#
.SYNOPSIS
    Publishes FileServe, creates the IIS site and app pool, and wires up permissions.

.DESCRIPTION
    Run this on the Windows Server, from a checkout of this repository, in an elevated
    PowerShell session. It is idempotent: re-running it updates the existing site.

.EXAMPLE
    .\Install-FileServe.ps1 -VaultPath D:\SharedFiles -Hostname files.contoso.com

.EXAMPLE
    # Serve at the site root instead of under /files
    .\Install-FileServe.ps1 -VaultPath D:\SharedFiles -RequestPath ''
#>
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    # The folder outside the application directory whose contents get served.
    [Parameter(Mandatory)]
    [string]$VaultPath,

    # URL prefix. '/files' -> https://host/files/report.pdf. '' -> https://host/report.pdf
    [string]$RequestPath = '/files',

    [string]$SiteName = 'FileServe',
    [string]$AppPoolName = 'FileServe',

    # Where the compiled application is deployed to. Deliberately NOT the vault folder.
    [string]$PhysicalPath = 'C:\inetpub\FileServe',

    # Host header for the binding. Omit to bind to all hostnames on the port.
    [string]$Hostname,

    [int]$Port = 80
)

$ErrorActionPreference = 'Stop'
Import-Module WebAdministration

$repoRoot = Split-Path -Parent $PSScriptRoot
$projectPath = Join-Path $repoRoot 'src\FileServe\FileServe.csproj'

if (-not (Test-Path -LiteralPath $projectPath)) {
    throw "Could not find $projectPath. Run this script from the repository's deploy folder."
}

if (-not (Test-Path -LiteralPath $VaultPath)) {
    throw "VaultPath '$VaultPath' does not exist."
}

# --- Preflight: the ASP.NET Core Module must be present ---------------------------
if (-not (Get-WebGlobalModule -Name 'AspNetCoreModuleV2' -ErrorAction SilentlyContinue)) {
    throw @"
The ASP.NET Core Module (AspNetCoreModuleV2) is not registered with IIS.
Install the .NET 8 Hosting Bundle, then re-run this script:
  https://dotnet.microsoft.com/download/dotnet/8.0 -> 'Hosting Bundle'
Restart IIS afterwards with: net stop was /y; net start w3svc
"@
}

# --- Publish ----------------------------------------------------------------------
Write-Host "Publishing to $PhysicalPath ..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $PhysicalPath | Out-Null

# Stop the pool first so the DLLs are not locked by a running worker process.
if ((Get-Website -Name $SiteName -ErrorAction SilentlyContinue) -and
    (Get-WebAppPoolState -Name $AppPoolName -ErrorAction SilentlyContinue).Value -eq 'Started') {
    Stop-WebAppPool -Name $AppPoolName
    Start-Sleep -Seconds 2
}

dotnet publish $projectPath --configuration Release --output $PhysicalPath
if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed with exit code $LASTEXITCODE." }

# --- Point the published config at the vault --------------------------------------
$settingsPath = Join-Path $PhysicalPath 'appsettings.json'
$settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
$settings.FileVault.RootPath = $VaultPath
$settings.FileVault.RequestPath = $RequestPath
$settings | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $settingsPath -Encoding utf8

Write-Host "Configured RootPath=$VaultPath RequestPath=$(if ($RequestPath) { $RequestPath } else { '/' })"

# --- App pool ---------------------------------------------------------------------
if (-not (Test-Path "IIS:\AppPools\$AppPoolName")) {
    New-WebAppPool -Name $AppPoolName | Out-Null
    Write-Host "Created app pool '$AppPoolName'."
}

# ASP.NET Core runs out of IIS's managed pipeline entirely, so the pool must be
# set to 'No Managed Code'.
Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name managedRuntimeVersion -Value ''
Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name startMode -Value 'AlwaysRunning'

# --- Site -------------------------------------------------------------------------
if (-not (Get-Website -Name $SiteName -ErrorAction SilentlyContinue)) {
    $newSite = @{
        Name         = $SiteName
        PhysicalPath = $PhysicalPath
        ApplicationPool = $AppPoolName
        Port         = $Port
    }
    if ($Hostname) { $newSite.HostHeader = $Hostname }

    New-Website @newSite | Out-Null
    Write-Host "Created site '$SiteName' on port $Port."
}
else {
    Set-ItemProperty "IIS:\Sites\$SiteName" -Name physicalPath -Value $PhysicalPath
    Set-ItemProperty "IIS:\Sites\$SiteName" -Name applicationPool -Value $AppPoolName
    Write-Host "Updated existing site '$SiteName'."
}

# --- Permissions ------------------------------------------------------------------
& (Join-Path $PSScriptRoot 'Grant-VaultAccess.ps1') -VaultPath $VaultPath -AppPoolName $AppPoolName

# The app folder itself needs read access for the worker process to load the DLLs.
$appAcl = Get-Acl -LiteralPath $PhysicalPath
$appAcl.SetAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
    "IIS AppPool\$AppPoolName", 'ReadAndExecute', 'ContainerInherit, ObjectInherit', 'None', 'Allow')))
Set-Acl -LiteralPath $PhysicalPath -AclObject $appAcl

Start-WebAppPool -Name $AppPoolName -ErrorAction SilentlyContinue
Start-Website -Name $SiteName -ErrorAction SilentlyContinue

$probeHost = if ($Hostname) { $Hostname } else { 'localhost' }
Write-Host ''
Write-Host "Done. Verify with:" -ForegroundColor Green
Write-Host "  curl http://${probeHost}:$Port/healthz"
Write-Host "  curl http://${probeHost}:$Port$RequestPath/<some-file-in-the-vault>"
Write-Host ''
Write-Host "For HTTPS, add a binding with a certificate:" -ForegroundColor Yellow
Write-Host "  New-WebBinding -Name $SiteName -Protocol https -Port 443 -HostHeader $probeHost -SslFlags 1"
