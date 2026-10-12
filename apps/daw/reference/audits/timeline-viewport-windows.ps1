param([switch]$Probe, [switch]$CursorOnly, [switch]$PlaybackOnly)
$ErrorActionPreference='Stop'
$Repo=Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
$Audit=Join-Path $env:LOCALAPPDATA 'Joljak\audit\timeline-viewport-20261011'
$Application=Join-Path $env:LOCALAPPDATA 'Joljak\audit\refinement-u1-20261011\application'
New-Item -ItemType Directory -Force -Path $Audit | Out-Null
$Existing=& (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'scripts\start_windows.ps1') -PrepareOnly
$env:JOLJAK_PYTHON=Join-Path $Existing 'resources\python\python.exe'
$Exe=Join-Path $Application 'Joljak.exe'
if (-not (Test-Path -LiteralPath $Exe)) {throw 'Prepare the retained U1 audit runtime first.'}
if (Get-Process -Name Joljak -ErrorAction SilentlyContinue | Where-Object {$_.Path -eq $Exe}) {throw 'The audit application is still running.'}
$Target=Join-Path $Application 'resources\app'
if (Test-Path -LiteralPath $Target) {Remove-Item -LiteralPath $Target -Recurse -Force}
Copy-Item -LiteralPath (Join-Path $Repo 'dist\Joljak-win-x64\resources\app') -Destination (Join-Path $Application 'resources') -Recurse
$env:JOLJAK_UI_EXE=$Exe
$env:JOLJAK_UI_AUDIT=$Audit
$env:JOLJAK_UI_PROJECT=Join-Path $env:LOCALAPPDATA 'Joljak\audit\refinement-u1-feedback-20261011\Feedback review.joljak'
$env:JOLJAK_UI_PROBE=if($Probe){'1'}else{'0'}
$env:JOLJAK_UI_CURSOR_ONLY=if($CursorOnly){'1'}else{'0'}
$env:JOLJAK_UI_PLAYBACK_ONLY=if($PlaybackOnly){'1'}else{'0'}
$env:JOLJAK_PLAYWRIGHT=Join-Path $Repo '.daw-runtime\audit-tools\playwright-core'
$env:ELECTRON_RUN_AS_NODE='1'
Remove-Item Env:JOLJAK_DEV_URL -ErrorAction SilentlyContinue
& $Exe (Join-Path $PSScriptRoot 'timeline-viewport-windows.cjs') | Out-Host
$Result=$LASTEXITCODE
$Evidence=Join-Path $Repo '.daw-state\timeline-viewport-20261011'
New-Item -ItemType Directory -Force -Path $Evidence | Out-Null
Get-ChildItem $Audit -File | ForEach-Object {Copy-Item -LiteralPath $_.FullName -Destination $Evidence -Force}
exit $Result
