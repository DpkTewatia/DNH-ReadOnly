<#
.SYNOPSIS
    Grants an IIS application pool identity read access to the served folder.

.DESCRIPTION
    The application pool runs as "IIS AppPool\<name>" by default. That virtual account
    is local to the machine, so it can read local folders once granted, but it cannot
    authenticate to a UNC share. This script grants local access and warns when the
    target is a UNC path.

.EXAMPLE
    .\Grant-VaultAccess.ps1 -VaultPath D:\SharedFiles -AppPoolName FileServe
#>
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$VaultPath,

    [string]$AppPoolName = 'FileServe',

    # Grant Modify instead of ReadAndExecute. The app never writes, so this is only
    # useful if another process on this box maintains the folder.
    [switch]$AllowWrite
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $VaultPath)) {
    throw "VaultPath '$VaultPath' does not exist."
}

if ($VaultPath.StartsWith('\')) {
    Write-Warning @"
'$VaultPath' is a UNC path. The virtual account 'IIS AppPool\$AppPoolName' cannot
authenticate to another machine, so file-level ACLs here will not help.

Either:
  * Run the pool as a domain account that has share + NTFS read access, or
  * Map the content locally and point FileVault:RootPath at the local path.
"@
    return
}

$identity = "IIS AppPool\$AppPoolName"
$rights = if ($AllowWrite) { 'Modify' } else { 'ReadAndExecute' }

$acl = Get-Acl -LiteralPath $VaultPath

$rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    $identity,
    $rights,
    'ContainerInherit, ObjectInherit',   # apply to subfolders and files
    'None',
    'Allow'
)

$acl.SetAccessRule($rule)
Set-Acl -LiteralPath $VaultPath -AclObject $acl

Write-Host "Granted '$identity' $rights on '$VaultPath'." -ForegroundColor Green
