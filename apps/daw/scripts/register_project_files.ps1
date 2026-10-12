param([Parameter(Mandatory=$true)][string]$Executable)
$ErrorActionPreference='Stop'
if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { throw 'The Joljak executable is missing.' }
$Executable=(Get-Item -LiteralPath $Executable).FullName
$values=@{
    'Software\Classes\.joljak'='Joljak.Project'
    'Software\Classes\Joljak.Project'='Joljak Project'
    'Software\Classes\Joljak.Project\DefaultIcon'=('"'+$Executable+'",0')
    'Software\Classes\Joljak.Project\shell\open\command'=('"'+$Executable+'" "%1"')
}
foreach($name in $values.Keys) {
    $key=[Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($name)
    try { $key.SetValue('', $values[$name], [Microsoft.Win32.RegistryValueKind]::String) }
    finally { $key.Dispose() }
}
$key=[Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Software\Classes\.joljak\OpenWithProgids')
try { $key.SetValue('Joljak.Project', '', [Microsoft.Win32.RegistryValueKind]::String) }
finally { $key.Dispose() }
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class JoljakFileAssociation { [DllImport("shell32.dll")] public static extern void SHChangeNotify(uint change, uint flags, IntPtr first, IntPtr second); }'
[JoljakFileAssociation]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
Write-Host 'Registered .joljak project files for this Windows user.'
