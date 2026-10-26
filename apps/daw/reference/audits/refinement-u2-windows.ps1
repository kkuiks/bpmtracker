param([switch]$ContextOnly, [switch]$KeyboardOnly, [switch]$MapOnly)
$ErrorActionPreference='Stop'
$Repo=Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
$Audit=Join-Path $env:LOCALAPPDATA 'BPMTracker\audit\refinement-u2-20261011'
# Refresh only the closed audit-owned application. The owner's preview is separate.
$Application=Join-Path $env:LOCALAPPDATA 'BPMTracker\audit\refinement-u1-20261011\application'
New-Item -ItemType Directory -Force -Path $Audit | Out-Null
$Existing=& (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'scripts\start_windows.ps1') -PrepareOnly
$env:BPMTRACKER_PYTHON=Join-Path $Existing 'resources\python\python.exe'
$Exe=Join-Path $Application 'BPMTracker.exe'
if (-not (Test-Path -LiteralPath $Exe) -or -not (Test-Path -LiteralPath $env:BPMTRACKER_PYTHON)) {throw 'The retained audit runtime is unavailable.'}
if (Get-Process -Name BPMTracker -ErrorAction SilentlyContinue | Where-Object {$_.Path -eq $Exe}) {throw 'The audit application is still running.'}
$Target=Join-Path $Application 'resources\app'
if (Test-Path -LiteralPath $Target) {Remove-Item -LiteralPath $Target -Recurse -Force}
Copy-Item -LiteralPath (Join-Path $Repo 'dist\BPMTracker-win-x64\resources\app') -Destination (Join-Path $Application 'resources') -Recurse
$env:BPMTRACKER_U2_EXE=$Exe
$env:BPMTRACKER_U2_AUDIT=$Audit
$env:BPMTRACKER_U2_MEDIA=Join-Path $env:LOCALAPPDATA 'BPMTracker\audit\refinement-u1-20261011\media'
$env:BPMTRACKER_U2_CONTEXT_ONLY=if ($ContextOnly) {'1'} else {'0'}
$env:BPMTRACKER_U2_KEYBOARD_ONLY=if ($KeyboardOnly) {'1'} else {'0'}
$env:BPMTRACKER_U2_MAP_ONLY=if ($MapOnly) {'1'} else {'0'}
$env:BPMTRACKER_PLAYWRIGHT=Join-Path $Repo '.daw-runtime\audit-tools\playwright-core'
$env:ELECTRON_RUN_AS_NODE='1'
Remove-Item Env:BPMTRACKER_DEV_URL -ErrorAction SilentlyContinue
& $Exe (Join-Path $PSScriptRoot 'refinement-u2-windows.cjs') | Out-Host
$Result=$LASTEXITCODE
$Evidence=Join-Path $Repo '.daw-state\refinement-u2-20261011'
New-Item -ItemType Directory -Force -Path $Evidence | Out-Null
Get-ChildItem $Audit -File | ForEach-Object {Copy-Item -LiteralPath $_.FullName -Destination $Evidence -Force}
exit $Result
