param(
    [switch]$PrepareOnly,
    [switch]$Source,
    [string]$DevUrl,
    [string]$CacheRoot
)
$ErrorActionPreference = 'Stop'
$app = Split-Path $PSScriptRoot -Parent
$repository = Split-Path (Split-Path $app -Parent) -Parent
if (-not $CacheRoot) { $CacheRoot = Join-Path $env:LOCALAPPDATA 'Joljak\development' }
$package = Get-Content (Join-Path $app 'package.json') -Raw | ConvertFrom-Json
$runtimeId = "electron-$($package.devDependencies.electron)-python-3.12.10-cpu-v1"
$runtime = Join-Path $CacheRoot $runtimeId
$bundle = Join-Path $runtime 'Joljak-win-x64'
$marker = Join-Path $runtime 'assembled.json'
if (-not (Test-Path $marker)) {
    $zip = Join-Path $repository 'dist\Joljak-win-x64.zip'
    if (-not (Test-Path $zip)) { throw 'Assemble dist/Joljak-win-x64.zip first.' }
    Write-Host 'First start: preparing the local Windows runtime. This is needed only once.'
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    Expand-Archive -LiteralPath $zip -DestinationPath $runtime -Force
    if (-not (Test-Path "$bundle\Joljak.exe") -or -not (Test-Path "$bundle\resources\python\python.exe")) {
        throw 'The portable archive did not contain the expected Windows runtime.'
    }
    @{ runtime = $runtimeId } | ConvertTo-Json | Set-Content $marker -Encoding UTF8
}
if ($PrepareOnly) { Write-Output $bundle; exit 0 }
$executable = Join-Path $bundle 'Joljak.exe'
$running = Get-Process Joljak -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $executable }
if ($running) {
    Write-Host 'Joljak is already open. Close its window and start again to refresh the current build.'
    exit 0
}
$target = Join-Path $bundle 'resources\app'
if (-not $Source -and -not (Test-Path "$app\dist\index.html")) { throw 'Run npm run build in apps/daw first.' }
# A packaged Electron executable loads resources/app. Passing a source directory
# as argv does not replace that app. Refresh the small application files only;
# keep the installed Python/model runtime for both built and Vite modes.
foreach ($directory in @('dist','electron','backend')) {
    if (Test-Path "$app\$directory") {
        # Keep only the current generated UI assets. Never touch media, project
        # workspace, Python or model caches while refreshing an application.
        if ($directory -eq 'dist' -and (Test-Path "$target\dist")) {
            Remove-Item -LiteralPath "$target\dist" -Recurse -Force
        }
        New-Item -ItemType Directory -Force -Path "$target\$directory" | Out-Null
        Copy-Item "$app\$directory\*" "$target\$directory" -Recurse -Force
    }
}
$manifest = @{ name = 'joljak-daw'; productName = 'Joljak'; version = $package.version; main = 'electron/main.cjs' } | ConvertTo-Json
[System.IO.File]::WriteAllText((Join-Path $target 'package.json'), $manifest, [System.Text.UTF8Encoding]::new($false))
if ($Source -and $DevUrl) { $env:JOLJAK_DEV_URL = $DevUrl }
else { Remove-Item Env:JOLJAK_DEV_URL -ErrorAction SilentlyContinue }
Write-Host 'Starting the current Joljak build.'
# VS Code launches its tooling with Electron's Node mode. Do not inherit that
# mode when starting the actual desktop application. This affects this child only.
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
Start-Process -FilePath $executable -WorkingDirectory $bundle
