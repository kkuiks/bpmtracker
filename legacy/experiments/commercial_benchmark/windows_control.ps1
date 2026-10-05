param(
    [Parameter(Mandatory=$true)][ValidateSet('focus','click','keys','capture')][string]$Action,
    [Parameter(Mandatory=$true)][long]$WindowHandle,
    [int]$X = 0,
    [int]$Y = 0,
    [string]$Keys = "",
    [string]$OutputPath = "",
    [switch]$Maximize,
    [switch]$Screen
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if (-not ('BenchWindow' -as [type])) { Add-Type @'
using System;
using System.Collections.Generic;
using System.Text;
using System.Runtime.InteropServices;
public static class BenchWindow {
    [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr value);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int command);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr info);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out Rect rect);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
    [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h,StringBuilder b,int n);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr h,StringBuilder b,int n);
    delegate bool EnumCallback(IntPtr h,IntPtr param);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumCallback fn,IntPtr param);
    public class Info {public long Handle; public string Title,Class; public bool Enabled;}
    public static Info[] List(uint wanted) {
        var found=new List<Info>();
        EnumWindows((h,p)=> {uint pid;GetWindowThreadProcessId(h,out pid);
            if(pid==wanted && IsWindowVisible(h)) {var title=new StringBuilder(1024);var cls=new StringBuilder(256);
                GetWindowText(h,title,1024);GetClassName(h,cls,256);
                found.Add(new Info {Handle=h.ToInt64(),Title=title.ToString(),Class=cls.ToString(),Enabled=IsWindowEnabled(h)});
            } return true;},IntPtr.Zero);
        return found.ToArray();
    }
    public struct Rect { public int Left, Top, Right, Bottom; }
}
'@
}
[void][BenchWindow]::SetProcessDpiAwarenessContext([IntPtr](-4))
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$target = [IntPtr]$WindowHandle
[uint32]$targetId=0
[void][BenchWindow]::GetWindowThreadProcessId($target,[ref]$targetId)
if (-not $targetId) { throw "Target window no longer exists" }
if ($Action -eq 'focus') {
    $mode=9
    if($Maximize){$mode=3}
    [void][BenchWindow]::ShowWindow($target,$mode)
    $shell=New-Object -ComObject WScript.Shell
    [void]$shell.AppActivate([int]$targetId)
    [void][BenchWindow]::SetForegroundWindow($target)
}
if ($Action -in @('click','keys')) {
    [uint32]$foregroundId=0
    [void][BenchWindow]::GetWindowThreadProcessId([BenchWindow]::GetForegroundWindow(),[ref]$foregroundId)
    if ($foregroundId -ne $targetId) { throw "Foreground application changed; input was not sent" }
    if ($Action -eq 'click') {
        $rect=New-Object BenchWindow+Rect
        [void][BenchWindow]::GetWindowRect($target,[ref]$rect)
        if($X -lt $rect.Left -or $X -ge $rect.Right -or $Y -lt $rect.Top -or $Y -ge $rect.Bottom) { throw "Click lies outside target window" }
        [void][BenchWindow]::SetCursorPos($X,$Y)
        [BenchWindow]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
        [BenchWindow]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
    } else {
        [System.Windows.Forms.SendKeys]::SendWait($Keys)
    }
}
if ($Action -eq 'capture') {
    $rect=New-Object BenchWindow+Rect
    [void][BenchWindow]::GetWindowRect($target,[ref]$rect)
    $bitmap=New-Object System.Drawing.Bitmap(($rect.Right-$rect.Left),($rect.Bottom-$rect.Top))
    $graphics=[System.Drawing.Graphics]::FromImage($bitmap)
    if ($Screen) {
        [uint32]$foregroundId=0
        [void][BenchWindow]::GetWindowThreadProcessId([BenchWindow]::GetForegroundWindow(),[ref]$foregroundId)
        if ($foregroundId -ne $targetId) { throw "Foreground application changed; screen was not captured" }
        $graphics.CopyFromScreen($rect.Left,$rect.Top,0,0,$bitmap.Size)
    } else {
        $dc=$graphics.GetHdc()
        try {$printed=[BenchWindow]::PrintWindow($target,$dc,2)} finally {$graphics.ReleaseHdc($dc)}
    }
    $bitmap.Save($OutputPath,[System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose();$bitmap.Dispose()
}
[uint32]$activeId=0
$active=[BenchWindow]::GetForegroundWindow()
[void][BenchWindow]::GetWindowThreadProcessId($active,[ref]$activeId)
$bounds=New-Object BenchWindow+Rect
[void][BenchWindow]::GetWindowRect($target,[ref]$bounds)
[pscustomobject]@{Action=$Action;TargetProcessId=$targetId;ForegroundProcessId=$activeId;ForegroundHandle=$active.ToInt64();TargetRect=@($bounds.Left,$bounds.Top,$bounds.Right,$bounds.Bottom);Capture=$OutputPath} | ConvertTo-Json
