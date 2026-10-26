param([switch]$VisualOnly)
$ErrorActionPreference='Stop'
$Repo=Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
$Audit=Join-Path $env:LOCALAPPDATA 'BPMTracker\audit\refinement-u1-20261011'
$Application=Join-Path $Audit 'application'
New-Item -ItemType Directory -Force -Path $Audit | Out-Null
$Existing=& (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'scripts\start_windows.ps1') -PrepareOnly
$env:BPMTRACKER_PYTHON=Join-Path $Existing 'resources\python\python.exe'
if (-not (Test-Path -LiteralPath $env:BPMTRACKER_PYTHON)) {throw 'Retained Windows Python runtime is required.'}
$Exe=Join-Path $Application 'BPMTracker.exe'
if (Get-Process -Name BPMTracker -ErrorAction SilentlyContinue | Where-Object {$_.Path -eq $Exe}) {throw 'The previous U1 audit application is still running.'}
if (-not (Test-Path -LiteralPath $Exe)) {
    New-Item -ItemType Directory -Force -Path $Application | Out-Null
    Expand-Archive -LiteralPath (Join-Path $Repo '.daw-runtime\electron-v44.5.1-win32-x64.zip') -DestinationPath $Application
    Rename-Item -LiteralPath (Join-Path $Application 'electron.exe') -NewName 'BPMTracker.exe'
}
$Target=Join-Path $Application 'resources\app'
if (Test-Path -LiteralPath $Target) {Remove-Item -LiteralPath $Target -Recurse -Force}
Copy-Item -LiteralPath (Join-Path $Repo 'dist\BPMTracker-win-x64\resources\app') -Destination (Join-Path $Application 'resources') -Recurse
Copy-Item -LiteralPath (Join-Path $Repo '.daw-state\refinement-u1-20261011\media') -Destination $Audit -Recurse -Force
$env:BPMTRACKER_U1_EXE=$Exe
$env:BPMTRACKER_U1_AUDIT=$Audit
$env:BPMTRACKER_U1_VISUAL_ONLY=if ($VisualOnly) {'1'} else {'0'}
$env:BPMTRACKER_PLAYWRIGHT=Join-Path $Repo '.daw-runtime\audit-tools\playwright-core'
$env:ELECTRON_RUN_AS_NODE='1'
Remove-Item Env:BPMTRACKER_DEV_URL -ErrorAction SilentlyContinue
& $Exe (Join-Path $PSScriptRoot 'refinement-u1-windows.cjs') | Out-Host
$Result=$LASTEXITCODE
$Evidence=Join-Path $Repo '.daw-state\refinement-u1-20261011'
Get-ChildItem $Audit -File | ForEach-Object {Copy-Item -LiteralPath $_.FullName -Destination $Evidence -Force}
exit $Result
