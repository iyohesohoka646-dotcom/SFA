param([Parameter(Mandatory=$true)][int]$OwnerProcessId,[Parameter(Mandatory=$true)][long]$OwnerWindowHandle)
$ErrorActionPreference='Stop'
Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class OwnedFolderDialog {
 public delegate bool Visitor(IntPtr window, IntPtr context);
 [DllImport("user32.dll")] public static extern bool EnumWindows(Visitor visit, IntPtr context);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
 [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr window, uint command);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr window, StringBuilder text, int size);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr window, StringBuilder text, int size);
 [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);
}
'@
$deadline=[DateTime]::UtcNow.AddSeconds(8)
$found=[System.Collections.Generic.List[IntPtr]]::new()
$ownedCaptions=[System.Collections.Generic.List[string]]::new()
do {
 $found.Clear()
 [OwnedFolderDialog]::EnumWindows({param($window,$context)
  [uint32]$ownerId=0
  [void][OwnedFolderDialog]::GetWindowThreadProcessId($window,[ref]$ownerId)
  $owner=[OwnedFolderDialog]::GetWindow($window,4)
  if(($ownerId -eq $OwnerProcessId -or $owner.ToInt64() -eq $OwnerWindowHandle) -and [OwnedFolderDialog]::IsWindowVisible($window)){
   $className=[Text.StringBuilder]::new(256);$caption=[Text.StringBuilder]::new(256)
   [void][OwnedFolderDialog]::GetClassName($window,$className,256)
   [void][OwnedFolderDialog]::GetWindowText($window,$caption,256)
   $ownedCaptions.Add($className.ToString()+':'+$caption.ToString())
   if($className.ToString() -eq '#32770' -and $owner.ToInt64() -eq $OwnerWindowHandle){$found.Add($window)}
  }
  return $true
 },[IntPtr]::Zero) | Out-Null
 if($found.Count){break}
 Start-Sleep -Milliseconds 100
} while([DateTime]::UtcNow -lt $deadline)
if($found.Count -ne 1){Write-Output ($ownedCaptions | Select-Object -Unique | ConvertTo-Json -Compress);throw 'Expected exactly one visible directory dialog owned by the tested application'}
[void][OwnedFolderDialog]::SendMessage($found[0],0x0010,[IntPtr]::Zero,[IntPtr]::Zero)
@{native_directory_dialog_visible=$true;owned_window_verified=$true;cancel_sent=$true} | ConvertTo-Json -Compress
