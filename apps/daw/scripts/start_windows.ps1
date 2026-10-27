param(
    [switch]$PrepareOnly,
    [switch]$Source,
    [string]$DevUrl,
    [string]$CacheRoot,
    [string]$Project
)
$ErrorActionPreference = 'Stop'
$app = Split-Path $PSScriptRoot -Parent
$repository = Split-Path (Split-Path $app -Parent) -Parent
if (-not $CacheRoot) { $CacheRoot = Join-Path $env:LOCALAPPDATA 'BPMTracker\development' }
$package = Get-Content (Join-Path $app 'package.json') -Raw | ConvertFrom-Json
$runtimeId = "electron-$($package.devDependencies.electron)-python-3.12.10-cpu-v1"
$runtime = Join-Path $CacheRoot $runtimeId
$bundle = Join-Path $runtime 'BPMTracker-win-x64'
$marker = Join-Path $runtime 'assembled.json'
if (-not (Test-Path $marker)) {
    $zip = Join-Path $repository 'dist\BPMTracker-win-x64.zip'
    if (-not (Test-Path $zip)) { throw 'Assemble dist/BPMTracker-win-x64.zip first.' }
    Write-Host 'First start: preparing the local Windows runtime. This is needed only once.'
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    Expand-Archive -LiteralPath $zip -DestinationPath $runtime -Force
    if (-not (Test-Path "$bundle\BPMTracker.exe") -or -not (Test-Path "$bundle\resources\python\python.exe")) {
        throw 'The portable archive did not contain the expected Windows runtime.'
    }
    @{ runtime = $runtimeId } | ConvertTo-Json | Set-Content $marker -Encoding UTF8
}
$executable = Join-Path $bundle 'BPMTracker.exe'
$running = Get-Process BPMTracker -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $executable }
if ($running) {
    if ($PrepareOnly) { Write-Output $bundle; exit 0 }
    if ($Project) {
        $installed=Get-Content (Join-Path $bundle 'resources\app\package.json') -Raw | ConvertFrom-Json
        if ($installed.version -ne $package.version) { throw 'Close BPMTracker and relaunch once to update project-file opening.' }
        Start-Process -FilePath $executable -WorkingDirectory $bundle -ArgumentList ('"'+$Project+'"')
        exit 0
    }
    Write-Host 'BPMTracker is already open. Close its window and start again to refresh the current build.'
    exit 0
}
$target = Join-Path $bundle 'resources\app'
if (-not $Source -and -not $PrepareOnly -and -not (Test-Path "$app\dist\index.html")) { throw 'Run npm run build in apps/daw first.' }
# A packaged Electron executable loads resources/app. Passing a source directory
# as argv does not replace that app. Refresh application and analysis source;
# keep the installed Python/model runtime for both built and Vite modes.
foreach ($directory in @('dist','electron','backend')) {
    if (Test-Path "$app\$directory") {
        # Keep only the current generated UI assets. Never touch media, project
        # workspace, Python or model caches while refreshing an application.
        if (Test-Path "$target\$directory") {
            Remove-Item -LiteralPath "$target\$directory" -Recurse -Force
        }
        New-Item -ItemType Directory -Force -Path "$target\$directory" | Out-Null
        Copy-Item "$app\$directory\*" "$target\$directory" -Recurse -Force
    }
}
$manifest = @{ name = 'bpmtracker-daw'; productName = 'BPMTracker'; version = $package.version; main = 'electron/main.cjs' } | ConvertTo-Json
[System.IO.File]::WriteAllText((Join-Path $target 'package.json'), $manifest, [System.Text.UTF8Encoding]::new($false))
$payloadScript = Join-Path $PSScriptRoot 'analysis_payload.py'
& (Join-Path $bundle 'resources\python\python.exe') $payloadScript --target (Join-Path $bundle 'resources\analysis')
if ($LASTEXITCODE -ne 0) { throw 'Analysis source refresh failed. The app was not started.' }
if ($PrepareOnly) { Write-Output $bundle; exit 0 }
& (Join-Path $PSScriptRoot 'register_project_files.ps1') -Executable $executable
if ($Source -and $DevUrl) { $env:BPMTRACKER_DEV_URL = $DevUrl }
else { Remove-Item Env:BPMTRACKER_DEV_URL -ErrorAction SilentlyContinue }
Write-Host 'Starting the current BPMTracker build.'
# VS Code launches its tooling with Electron's Node mode. Do not inherit that
# mode when starting the actual desktop application. This affects this child only.
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
if ($Project) { Start-Process -FilePath $executable -WorkingDirectory $bundle -ArgumentList ('"'+$Project+'"') }
else { Start-Process -FilePath $executable -WorkingDirectory $bundle }
