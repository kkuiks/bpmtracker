param(
    [int]$DebugPort,
    [string]$ExpectedHost,
    [string]$ExpressionPath,
    [string]$InputDataJson='',
    [string]$CapturePath='',
    [switch]$CloseBrowser
)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.Encoding]::UTF8
$targets=Invoke-RestMethod ("http://127.0.0.1:$DebugPort/json")
$page=@($targets | Where-Object {$_.type -eq 'page' -and ([Uri]$_.url).Scheme -eq 'https' -and ([Uri]$_.url).Host -eq $ExpectedHost})
if($page.Count -ne 1){throw 'Expected exactly one task-owned tab on the allowed HTTPS host'}
$socket=New-Object Net.WebSockets.ClientWebSocket
$cancel=New-Object Threading.CancellationTokenSource
$cancel.CancelAfter(30000)
try {
    [void]$socket.ConnectAsync([Uri]$page[0].webSocketDebuggerUrl,$cancel.Token).GetAwaiter().GetResult()
    $script:messageId=0
    function Task-CDP([string]$Method,$Params=@{}) {
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
    $expression=[IO.File]::ReadAllText($ExpressionPath)
    if($InputDataJson) {
        $data=($InputDataJson | ConvertFrom-Json | ConvertTo-Json -Depth 10 -Compress)
        $expression='('+$expression+')('+$data+')'
    }
    $result=Task-CDP 'Runtime.evaluate' @{expression=$expression;awaitPromise=$true;returnByValue=$true}
    if($result.exceptionDetails){throw ($result.exceptionDetails|ConvertTo-Json -Depth 10 -Compress)}
    $result.result.value | ConvertTo-Json -Depth 10
    if($CapturePath) {
        $shot=Task-CDP 'Page.captureScreenshot' @{format='png';captureBeyondViewport=$true}
        [IO.File]::WriteAllBytes($CapturePath,[Convert]::FromBase64String($shot.data))
    }
    if($CloseBrowser) {try {Task-CDP 'Browser.close' | Out-Null} catch {}}
} finally {$socket.Dispose();$cancel.Dispose()}
