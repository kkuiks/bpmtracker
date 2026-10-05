param(
    [int]$TargetProcessId,
    [string]$CapturePath = "",
    [int]$Limit = 300
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class ProbeDpi {
    [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr value);
}
'@
[void][ProbeDpi]::SetProcessDpiAwarenessContext([IntPtr](-4))
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Drawing
$root = [System.Windows.Automation.AutomationElement]::RootElement
$condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $TargetProcessId)
$windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $condition)
$output = @()
for ($i = 0; $i -lt $windows.Count; $i++) {
    $window = $windows.Item($i)
    $controls = @()
    $all = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
    for ($j = 0; $j -lt [Math]::Min($all.Count, $Limit); $j++) {
        try {
            $node = $all.Item($j).Current
            $controls += [pscustomobject]@{ Index=$j; Name=$node.Name; Type=$node.ControlType.ProgrammaticName; Class=$node.ClassName; Id=$node.AutomationId; Enabled=$node.IsEnabled; Offscreen=$node.IsOffscreen; Rect=@($node.BoundingRectangle.X,$node.BoundingRectangle.Y,$node.BoundingRectangle.Width,$node.BoundingRectangle.Height) }
        } catch { }
    }
    $bounds = $window.Current.BoundingRectangle
    $output += [pscustomobject]@{ Name=$window.Current.Name; Handle=$window.Current.NativeWindowHandle; Rect=@($bounds.X,$bounds.Y,$bounds.Width,$bounds.Height); DescendantCount=$all.Count; Controls=$controls }
    if ($CapturePath -and $i -eq 0 -and $bounds.Width -gt 0 -and $bounds.Height -gt 0) {
        $bitmap = New-Object System.Drawing.Bitmap([int]$bounds.Width,[int]$bounds.Height)
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $graphics.CopyFromScreen([int]$bounds.X,[int]$bounds.Y,0,0,$bitmap.Size)
        $bitmap.Save($CapturePath,[System.Drawing.Imaging.ImageFormat]::Png)
        $graphics.Dispose(); $bitmap.Dispose()
    }
}
[pscustomobject]@{ TargetProcessId=$TargetProcessId; Windows=$output } | ConvertTo-Json -Depth 7
