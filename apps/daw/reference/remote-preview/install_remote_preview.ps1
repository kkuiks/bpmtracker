param(
    [string]$BaseUrl = 'http://127.0.0.1:8998/__bpmtracker_preview__',
    [string]$InstallDirectory
)
$ErrorActionPreference = 'Stop'
if (-not $InstallDirectory) {
    $InstallDirectory = Join-Path $env:LOCALAPPDATA 'BPMTracker\remote-preview'
}
$InstallDirectory = [System.IO.Path]::GetFullPath($InstallDirectory)
$appDirectory = Join-Path $InstallDirectory 'BPMTracker-win-x64'
$executable = Join-Path $appDirectory 'BPMTracker.exe'
$launcher = Join-Path $appDirectory 'Start Remote Preview.cmd'
$running = Get-Process BPMTracker -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $executable }
if ($running) {
    throw 'Close the preview BPMTracker window before updating its application files.'
}
New-Item -ItemType Directory -Force -Path $InstallDirectory | Out-Null
$curl = (Get-Command curl.exe -CommandType Application -ErrorAction Stop).Source
Write-Host ('Installation folder: {0}' -f $InstallDirectory)

function Receive-BPMTrackerArchive {
    param([string]$RemoteName, [string]$LocalName, [switch]$Resume)
    $url = $BaseUrl.TrimEnd('/') + '/' + $RemoteName
    $destination = Join-Path $InstallDirectory $LocalName
    $partial = $destination + '.download'
    $headers = Invoke-WebRequest -UseBasicParsing -Method Head -Uri $url
    $expected = [long]$headers.Headers['Content-Length']
    if ($expected -le 0) { throw ('The download size is missing for {0}.' -f $RemoteName) }
    if (Test-Path -LiteralPath $partial) {
        if (-not $Resume -or (Get-Item -LiteralPath $partial).Length -gt $expected) {
            Remove-Item -LiteralPath $partial -Force
        }
    }
    $received = if (Test-Path -LiteralPath $partial) { (Get-Item -LiteralPath $partial).Length } else { 0 }
    if ($received -lt $expected) {
        if ($received -gt 0) { Write-Host ('Resuming {0} at {1:N1} MiB.' -f $RemoteName, ($received / 1MB)) }
        & $curl --fail --location --retry 3 --retry-delay 2 --continue-at - --output $partial $url
        if ($LASTEXITCODE -ne 0) {
            throw 'Download interrupted. Keep VS Code connected and forward port 8998. Run this installer again to resume.'
        }
    }
    if ((Get-Item -LiteralPath $partial).Length -ne $expected) {
        throw ('Download is incomplete for {0}. Run this installer again to resume.' -f $RemoteName)
    }
    Move-Item -LiteralPath $partial -Destination $destination -Force
    return $destination
}

$runtimeArchive = Join-Path $InstallDirectory 'runtime.zip'
$runtimePresent = (Test-Path -LiteralPath $executable) -and
    (Test-Path -LiteralPath (Join-Path $appDirectory 'resources\python\python.exe')) -and
    (Test-Path -LiteralPath (Join-Path $appDirectory 'resources\analysis\final0.ckpt'))
if (-not $runtimePresent) {
    if (-not (Test-Path -LiteralPath $runtimeArchive)) {
        Write-Host 'Downloading the Windows runtime once (approximately 527 MiB).'
        $runtimeArchive = Receive-BPMTrackerArchive 'BPMTracker-win-x64.zip' 'runtime.zip' -Resume
    }
    Write-Host 'Extracting the Windows runtime. Please wait.'
    Expand-Archive -LiteralPath $runtimeArchive -DestinationPath $InstallDirectory -Force
}
Write-Host 'Downloading the current application and preview launcher.'
$appArchive = Receive-BPMTrackerArchive 'BPMTracker-remote-preview-app.zip' 'app.zip'
Expand-Archive -LiteralPath $appArchive -DestinationPath $InstallDirectory -Force
if (-not (Test-Path -LiteralPath $executable) -or -not (Test-Path -LiteralPath $launcher)) {
    throw ('Installation is incomplete. Expected BPMTracker.exe and Start Remote Preview.cmd in {0}.' -f $appDirectory)
}
Write-Host ''
Write-Host 'Installed. Keep VS Code connected and forward remote port 8998 to local 127.0.0.1:8998.'
Write-Host ('Launcher: {0}' -f $launcher)
Write-Host 'Double-click Start Remote Preview.cmd in the folder opening now.'
Write-Host 'Audio, projects and analysis run on this Windows PC.'
Invoke-Item -LiteralPath $appDirectory
