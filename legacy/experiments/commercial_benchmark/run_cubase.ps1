param(
    [Parameter(Mandatory=$true)][string]$RunRoot,
    [int]$TargetProcessId=24972,
    [string]$Only=''
)
. (Join-Path $PSScriptRoot 'cubase_session.ps1') -TargetProcessId $TargetProcessId
$inputs=Get-Content -LiteralPath (Join-Path $RunRoot 'inputs.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$out=Join-Path $RunRoot 'products\cubase-pro15'
foreach($row in $inputs.rows) {
    $name=[IO.Path]::GetFileNameWithoutExtension($row.neutral_name)
    if($Only -and $name -notin $Only.Split(',')){continue}
    $dir=Join-Path $out $name
    [void][IO.Directory]::CreateDirectory($dir)
    $receipt=Join-Path $dir 'capture-receipt.json'
    if(Test-Path -LiteralPath $receipt) {
        $prior=Get-Content -LiteralPath $receipt -Raw -Encoding UTF8 | ConvertFrom-Json
        if($prior.status -ne 'captured' -or $prior.working_sha256 -ne $row.working_copy.working_sha256){throw 'Resume receipt mismatch'}
        Write-Output "REUSED $name"
        continue
    }
    $timer=[Diagnostics.Stopwatch]::StartNew()
    $start=[DateTime]::UtcNow.ToString('o')
    try {
        $blank=if($row.source.sample_rate -eq 48000){'empty48.cpr'}elseif($row.source.sample_rate -eq 44100){'empty.cpr'}else{throw 'Unsupported source rate'}
        $template=Join-Path $out ('blank\'+$blank)
        $cpr=Join-Path $dir ($name+'-raw.cpr')
        $smt=Join-Path $dir ($name+'-raw.smt')
        $track=Join-Path $dir ($name+'-track.xml')
        foreach($p in @($cpr,$smt,$track)) {if(Test-Path -LiteralPath $p){throw "Partial run exists; preserve it and inspect before retry: $p"}}
        $h=Bench-OpenBlank $template
        Bench-Keys $h '^+s'
        Bench-FileDialog $h $cpr
        Bench-Import $h $row.windows_working_audio
        Bench-Capture $h (Join-Path $dir 'imported.png')
        $analysis=Bench-Analyze $h $dir
        Bench-Keys $h '^s'
        Start-Sleep -Milliseconds 400
        Bench-ExportTempo $h $smt
        Bench-ExportTrack $h $track
        Bench-Capture $h (Join-Path $dir 'native-result.png')
        $result=[ordered]@{
            status='captured';neutral_name=$row.neutral_name;id=$row.id;
            working_sha256=$row.working_copy.working_sha256;source=$row.source;
            template_sha256=(Get-FileHash -LiteralPath $template -Algorithm SHA256).Hash.ToLower();
            project_sample_rate=$row.source.sample_rate;
            start_utc=$start;end_utc=[DateTime]::UtcNow.ToString('o');
            native_analysis_observed_seconds=$analysis;capture_workflow_seconds=$timer.Elapsed.TotalSeconds;
            timing_resolution_seconds=0.2;manual_musical_corrections=$false;
            automatic_meter_detection=$false;signature_placeholder='1/4, excluded from predictions';
            outputs=@($cpr,$smt,$track) | ForEach-Object {
                @{path=$_;sha256=(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLower()}
            }
        }
        $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receipt -Encoding UTF8
        Write-Output ("CAPTURED {0} native={1:F3}s workflow={2:F3}s" -f $name,$analysis,$timer.Elapsed.TotalSeconds)
    } catch {
        $failure=[ordered]@{status='capture_failed';neutral_name=$row.neutral_name;id=$row.id;start_utc=$start;error=$_.Exception.Message;windows=(Bench-Windows)}
        $failure | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $dir 'capture-failure.json') -Encoding UTF8
        throw
    }
}
