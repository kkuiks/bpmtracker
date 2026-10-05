# Scoped helpers for the benchmark's own Cubase projects. No preferences or
# project timing settings are changed here.
param([int]$TargetProcessId=24972)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
$script:benchProcess=$TargetProcessId
$script:driver=Join-Path $PSScriptRoot 'windows_control.ps1'
$bootstrap=(Get-Process -Id $script:benchProcess).MainWindowHandle
& $script:driver -Action capture -WindowHandle $bootstrap -OutputPath ([System.IO.Path]::Combine([System.IO.Path]::GetTempPath(),'joljak-cubase-bootstrap.png')) | Out-Null

function Bench-Windows { @([BenchWindow]::List($script:benchProcess)) }
function Bench-Project {
    $w=@(Bench-Windows | Where-Object {$_.Title.StartsWith('Cubase Pro Project -')})
    if($w.Count -ne 1){throw "Expected exactly one benchmark project: $($w.Title -join ', ')"}
    $w[0].Handle
}
function Bench-Wait([scriptblock]$Condition,[string]$Reason,[double]$Seconds=60) {
    $timer=[Diagnostics.Stopwatch]::StartNew()
    while($timer.Elapsed.TotalSeconds -lt $Seconds) {
        if(& $Condition){return}
        Start-Sleep -Milliseconds 200
    }
    throw "Timed out: $Reason; windows: $((Bench-Windows).Title -join ', ')"
}
function Bench-Ready([long]$Handle) {
    [BenchWindow]::IsWindow([IntPtr]$Handle) -and [BenchWindow]::IsWindowEnabled([IntPtr]$Handle) -and
      -not @(Bench-Windows | Where-Object {$_.Title -in @('Tempo Detection','Import Audio','Activating Project','Opening Project')}).Count
}
function Bench-Keys([long]$Handle,[string]$Value) {
    & $script:driver -Action keys -WindowHandle $Handle -Keys $Value | Out-Null
}
function Bench-Click([long]$Handle,[int]$X,[int]$Y) {
    & $script:driver -Action click -WindowHandle $Handle -X $X -Y $Y | Out-Null
    Start-Sleep -Milliseconds 130
}
function Bench-Capture([long]$Handle,[string]$Path) {
    & $script:driver -Action capture -WindowHandle $Handle -OutputPath $Path | Out-Null
}
function Bench-NoticeDigest([string]$Path) {
    $bitmap=[Drawing.Bitmap]::FromFile($Path)
    try {
        if($bitmap.Width -ne 673 -or $bitmap.Height -ne 155){return ''}
        $crop=$bitmap.Clone((New-Object Drawing.Rectangle(55,40,580,55)),[Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $stream=New-Object IO.MemoryStream
        try {
            $crop.Save($stream,[Drawing.Imaging.ImageFormat]::Png)
            $sha=[Security.Cryptography.SHA256]::Create()
            try {([BitConverter]::ToString($sha.ComputeHash($stream.ToArray()))).Replace('-','')} finally {$sha.Dispose()}
        } finally {$crop.Dispose();$stream.Dispose()}
    } finally {$bitmap.Dispose()}
}
function Bench-AckTempoNotice([string]$EvidenceFolder) {
    $dialog=@(Bench-Windows | Where-Object {$_.Title -eq 'Cubase Pro'})
    if($dialog.Count -ne 1){throw 'Unexpected native message state'}
    $path=Join-Path $EvidenceFolder 'native-tempo-notice.png'
    Bench-Capture $dialog[0].Handle $path
    $template=Join-Path (Split-Path (Split-Path (Split-Path $EvidenceFolder))) 'gui\031-juno-native-message.png'
    $actual=Bench-NoticeDigest $path;$known=Bench-NoticeDigest $template
    if(-not $actual -or $actual -ne $known){throw 'Unrecognized native message; screenshot retained, no action sent'}
    # Exact message visually reviewed: multiple tempos detected; use Smooth
    # Tempo only if constant tempo is assumed. Acknowledge; never smooth.
    Bench-Keys $dialog[0].Handle '{ENTER}'
}
function Bench-Focus([long]$Handle) {
    & $script:driver -Action focus -WindowHandle $Handle -Maximize | Out-Null
}
function Bench-FileDialog([long]$Project,[string]$Path) {
    Bench-Wait { @(Bench-Windows | Where-Object {$_.Class -eq '#32770' -and $_.Title -match 'Save|Export|Import|Open'}).Count -gt 0 } 'native file dialog' 10
    Bench-Keys $Project ('^a'+$Path+'{ENTER}')
    Bench-Wait { @(Bench-Windows | Where-Object {$_.Class -eq '#32770' -and $_.Title -match '^Save As$|^Export Tempo Track$|^Import Audio$|^Open$'}).Count -eq 0 } 'file dialog closes' 20
    Start-Sleep -Milliseconds 500
}
function Bench-ExportTempo([long]$Project,[string]$Path) {
    if(Test-Path -LiteralPath $Path){throw 'Refusing to overwrite tempo export'}
    Bench-Click $Project 27 42
    Bench-Click $Project 80 387
    Bench-Click $Project 423 787
    Bench-FileDialog $Project $Path
    Bench-Wait { Test-Path -LiteralPath $Path } 'tempo export file' 10
}
function Bench-Analyze([long]$Project,[string]$EvidenceFolder) {
    # Tempo Detection selects Time Warp globally. Clicking the next waveform
    # with that tool would edit tempo. Select the track header, then use the
    # project's Select All command instead; the fresh project has one event.
    Bench-Click $Project 640 279
    Bench-Keys $Project '^a'
    Bench-Click $Project 142 42
    Bench-Click $Project 232 519
    Bench-Click $Project 615 545
    Bench-Wait { @(Bench-Windows | Where-Object {$_.Title -eq 'Tempo Detection Panel'}).Count -eq 1 } 'tempo panel' 10
    $panel=(Bench-Windows | Where-Object {$_.Title -eq 'Tempo Detection Panel'}).Handle
    $r=New-Object BenchWindow+Rect
    [void][BenchWindow]::GetWindowRect([IntPtr]$panel,[ref]$r)
    Bench-Capture $panel (Join-Path $EvidenceFolder 'panel-before.png')
    $timer=[Diagnostics.Stopwatch]::StartNew()
    Bench-Click $panel ($r.Left+168) ($r.Top+181)
    # The project is disabled while native detection runs. Poll the actual
    # progress window and owner enable state instead of assuming a sleep means
    # detection completed.
    Start-Sleep -Milliseconds 600
    Bench-Wait { (Bench-Ready $Project) -or @(Bench-Windows | Where-Object {$_.Title -eq 'Cubase Pro'}).Count -eq 1 } 'automatic tempo detection completion' 180
    $elapsed=$timer.Elapsed.TotalSeconds
    if(@(Bench-Windows | Where-Object {$_.Title -eq 'Cubase Pro'}).Count -eq 1) {
        Bench-AckTempoNotice $EvidenceFolder
        Bench-Wait { Bench-Ready $Project } 'native information acknowledged' 10
    }
    Bench-Capture $panel (Join-Path $EvidenceFolder 'panel-after.png')
    Bench-Click $panel ($r.Right-23) ($r.Top+21)
    $elapsed
}

function Bench-ExportTrack([long]$Project,[string]$Path) {
    if(Test-Path -LiteralPath $Path){throw 'Refusing to overwrite track export'}
    Bench-Click $Project 27 42
    Bench-Click $Project 80 387
    Bench-Click $Project 423 467
    Bench-Wait { @(Bench-Windows | Where-Object {$_.Title -eq 'Export Selected Tracks'}).Count -eq 1 } 'track export options' 10
    $dialog=(Bench-Windows | Where-Object {$_.Title -eq 'Export Selected Tracks'}).Handle
    $r=New-Object BenchWindow+Rect
    [void][BenchWindow]::GetWindowRect([IntPtr]$dialog,[ref]$r)
    # Reference our already isolated PCM copy; no further copy or conversion.
    Bench-Click $dialog ($r.Left+58) ($r.Top+125)
    Bench-Click $dialog ($r.Left+478) ($r.Top+250)
    Bench-FileDialog $Project $Path
    Bench-Wait { Test-Path -LiteralPath $Path } 'track XML file' 10
}

function Bench-OpenBlank([string]$Path) {
    $projects=@(Bench-Windows | Where-Object {$_.Title.StartsWith('Cubase Pro Project -')})
    if($projects.Count -gt 1){throw 'Unexpected additional project; refusing to close'}
    if($projects.Count -eq 1) {
        if($projects[0].Title -notmatch '^Cubase Pro Project - (empty(48)?|s[0-9]{2}-raw)$') {throw 'Refusing to close an unowned project'}
        Bench-Focus $projects[0].Handle
        Bench-Keys $projects[0].Handle '^s'
        Start-Sleep -Milliseconds 400
        Bench-Keys $projects[0].Handle '^w'
        Bench-Wait {
            @(Bench-Windows | Where-Object {$_.Title -in @('Cubase Pro Hub','Cubase Pro')}).Count -gt 0
        } 'close state' 15
        $prompt=@(Bench-Windows | Where-Object {$_.Title -eq 'Cubase Pro'})
        if($prompt.Count -eq 1) {
            # Native save-on-close prompt, reached only from the controlled
            # benchmark project's Close command. Save its own CPR, never close
            # or save an unrelated user project.
            Bench-Keys $prompt[0].Handle '{ENTER}'
        }
    }
    Bench-Wait { @(Bench-Windows | Where-Object {$_.Title -eq 'Cubase Pro Hub'}).Count -eq 1 } 'own project closes to Hub' 15
    $hub=(Bench-Windows | Where-Object {$_.Title -eq 'Cubase Pro Hub'}).Handle
    Bench-Focus $hub
    Bench-Keys $hub '^o'
    Bench-FileDialog $hub $Path
    $expected='Cubase Pro Project - '+[IO.Path]::GetFileNameWithoutExtension($Path)
    Bench-Wait {
        $p=@(Bench-Windows | Where-Object {$_.Title -eq $expected})
        $p.Count -eq 1 -and $p[0].Enabled -and [BenchWindow]::GetForegroundWindow().ToInt64() -eq $p[0].Handle
    } 'blank project activation' 30
    $project=Bench-Project
    Bench-Focus $project
    Start-Sleep -Milliseconds 500
    $project
}

function Bench-Import([long]$Project,[string]$Path) {
    Bench-Click $Project 27 42
    Bench-Click $Project 80 364
    Bench-Click $Project 410 363
    Bench-FileDialog $Project $Path
    Bench-Wait { (Bench-Ready $Project) -and [BenchWindow]::GetForegroundWindow().ToInt64() -eq $Project } 'source import' 30
    Start-Sleep -Milliseconds 500
}
