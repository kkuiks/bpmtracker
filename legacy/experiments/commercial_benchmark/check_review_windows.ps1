param([string]$RunRoot,[int]$DebugPort=9226)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.Encoding]::UTF8
$targets=Invoke-RestMethod ("http://127.0.0.1:$DebugPort/json")
$page=@($targets | Where-Object {$_.type -eq 'page' -and $_.url -eq 'http://localhost:8985/review/index.html'})
if($page.Count -ne 1){throw 'Expected own isolated review tab'}
$socket=New-Object Net.WebSockets.ClientWebSocket
$cancel=New-Object Threading.CancellationTokenSource
$cancel.CancelAfter(120000)
[void]$socket.ConnectAsync([Uri]$page[0].webSocketDebuggerUrl,$cancel.Token).GetAwaiter().GetResult()
$script:messageId=0
function Review-CDP([string]$Method,$Params=@{}) {
    $script:messageId++
    $id=$script:messageId
    $bytes=[Text.Encoding]::UTF8.GetBytes((@{id=$id;method=$Method;params=$Params}|ConvertTo-Json -Depth 20 -Compress))
    $socket.SendAsync([ArraySegment[byte]]::new($bytes),[Net.WebSockets.WebSocketMessageType]::Text,$true,$cancel.Token).GetAwaiter().GetResult()
    while($true) {
        $stream=New-Object IO.MemoryStream
        try {
            do {
                $buffer=New-Object byte[] 65536
                $received=$socket.ReceiveAsync([ArraySegment[byte]]::new($buffer),$cancel.Token).GetAwaiter().GetResult()
                $stream.Write($buffer,0,$received.Count)
            } while(-not $received.EndOfMessage)
            $reply=[Text.Encoding]::UTF8.GetString($stream.ToArray())|ConvertFrom-Json
        } finally {$stream.Dispose()}
        if($reply.id -eq $id) {
            if($reply.error){throw ($reply.error|ConvertTo-Json -Compress)}
            return $reply.result
        }
    }
}
$expression=@'
(async()=>{
 for(let i=0;i<100&&!data;i++)await new Promise(r=>setTimeout(r,100));
 if(!data||data.cases.length!==21||document.querySelectorAll('#rows tr').length!==21)throw Error('21-case rendering failed');
 document.getElementById('songs').value='20';document.getElementById('songs').dispatchEvent(new Event('change'));
 await load();await play();document.getElementById('ref').click();
 document.getElementById('seek').value='5';document.getElementById('seek').dispatchEvent(new Event('input'));
 await new Promise(r=>setTimeout(r,150));
 if(!playing||mode!=='reference'||Math.abs(position()-5)>.6||gains.cubase.gain.value!==0||gains.reference.gain.value<=0)throw Error('Playback/mode/seek failure');
 const guitarDuration=buffers.source.duration;stop();
 choose(14);if(!document.getElementById('scope').textContent.includes(String.fromCodePoint(0xbbf8,0xce21,0xc815)))throw Error('Unmeasured runtime display failed');
 choose(4);await load();
 if(Math.abs(buffers.source.duration-current.duration)>1/context.sampleRate)throw Error('Float32 source duration changed');
 const float32Duration=buffers.source.duration;
 choose(1);await load();await play();await new Promise(r=>setTimeout(r,100));stop();
 return {renderedCases:21,playback:true,quarterReferenceSwitch:true,seek:true,guitarDuration,
 float32SourceDecoded:true,float32Duration,unmeasuredRuntimeDisplayed:true,nocturneSourceAndClicksDecoded:true,contextSampleRate:context.sampleRate};
})()
'@
$result=Review-CDP 'Runtime.evaluate' @{expression=$expression;awaitPromise=$true;returnByValue=$true}
if($result.exceptionDetails){throw ($result.exceptionDetails|ConvertTo-Json -Depth 10 -Compress)}
$result.result.value | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $RunRoot 'browser-validation.json') -Encoding UTF8
$screenshot=Review-CDP 'Page.captureScreenshot' @{format='png';captureBeyondViewport=$true}
[IO.File]::WriteAllBytes((Join-Path $RunRoot 'review-browser.png'),[Convert]::FromBase64String($screenshot.data))
try {Review-CDP 'Browser.close' | Out-Null} catch {}
$socket.Dispose();$cancel.Dispose()
$result.result.value | ConvertTo-Json -Depth 5 -Compress
