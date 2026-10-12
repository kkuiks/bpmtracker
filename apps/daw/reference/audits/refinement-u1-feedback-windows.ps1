$ErrorActionPreference='Stop'
$Repo=Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
$Audit=Join-Path $env:LOCALAPPDATA 'Joljak\audit\refinement-u1-feedback-20261011'
# Reuse the audit-owned Electron and retained Python runtime; owner apps are separate.
$Application=Join-Path $env:LOCALAPPDATA 'Joljak\audit\refinement-u1-20261011\application'
New-Item -ItemType Directory -Force -Path $Audit | Out-Null
$Existing=& (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'scripts\start_windows.ps1') -PrepareOnly
$env:JOLJAK_PYTHON=Join-Path $Existing 'resources\python\python.exe'
$Exe=Join-Path $Application 'Joljak.exe'
if (-not (Test-Path -LiteralPath $Exe) -or -not (Test-Path -LiteralPath $env:JOLJAK_PYTHON)) {throw 'Prepare the retained U1 audit runtime first.'}
if (Get-Process -Name Joljak -ErrorAction SilentlyContinue | Where-Object {$_.Path -eq $Exe}) {throw 'The audit application is still running.'}
$Target=Join-Path $Application 'resources\app'
if (Test-Path -LiteralPath $Target) {Remove-Item -LiteralPath $Target -Recurse -Force}
Copy-Item -LiteralPath (Join-Path $Repo 'dist\Joljak-win-x64\resources\app') -Destination (Join-Path $Application 'resources') -Recurse
Copy-Item -LiteralPath (Join-Path $Repo '.daw-state\refinement-u1-20261011\media') -Destination $Audit -Recurse -Force
$env:JOLJAK_U1_EXE=$Exe
$env:JOLJAK_U1_AUDIT=$Audit
$env:JOLJAK_PLAYWRIGHT=Join-Path $Repo '.daw-runtime\audit-tools\playwright-core'
$env:ELECTRON_RUN_AS_NODE='1'
Remove-Item Env:JOLJAK_DEV_URL -ErrorAction SilentlyContinue
& $Exe (Join-Path $PSScriptRoot 'refinement-u1-feedback-windows.cjs') | Out-Host
$Result=$LASTEXITCODE
$Evidence=Join-Path $Repo '.daw-state\refinement-u1-feedback-20261011'
New-Item -ItemType Directory -Force -Path $Evidence | Out-Null
Get-ChildItem $Audit -File | ForEach-Object {Copy-Item -LiteralPath $_.FullName -Destination $Evidence -Force}
exit $Result
