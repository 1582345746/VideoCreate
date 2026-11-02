[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Source, [Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference = 'Stop'
$vcSource = [IO.Path]::GetFullPath($Source).TrimEnd('\')
$vcTarget = [IO.Path]::GetFullPath($Destination).TrimEnd('\')
if ([IO.Path]::GetFileName($vcSource) -ne 'GrokVideoSkill' -or [IO.Path]::GetFileName($vcTarget) -ne 'VideoCreate' -or
    (Split-Path -Parent $vcSource) -ne (Split-Path -Parent $vcTarget)) { throw 'Expected adjacent legacy and VideoCreate directories.' }
if (Test-Path -LiteralPath $vcTarget) { throw 'Destination exists; refusing to merge or overwrite.' }
$vcSourceItem = Get-Item -LiteralPath $vcSource -Force
if (($vcSourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
    -not (Test-Path -LiteralPath (Join-Path $vcSource '.git') -PathType Container)) { throw 'Expected a physical primary repository.' }

# Windows keeps a running application's working directory open without delete
# sharing. Move the checked children, then turn the empty old directory into a
# junction in place; the application can keep its existing directory handle.
Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class VideoCreateWorkspaceJunction {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern SafeFileHandle CreateFile(string name, uint access, uint share, IntPtr security, uint mode, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool DeviceIoControl(SafeFileHandle h, uint code, byte[] input, uint size, IntPtr output, uint outputSize, out uint returned, IntPtr overlapped);
    public static void Set(string path, string target) {
        byte[] sub=Encoding.Unicode.GetBytes(@"\??\"+target), display=Encoding.Unicode.GetBytes(target);
        byte[] buffer=new byte[16+sub.Length+2+display.Length+2];
        Array.Copy(BitConverter.GetBytes(0xA0000003u),0,buffer,0,4);
        Array.Copy(BitConverter.GetBytes((ushort)(buffer.Length-8)),0,buffer,4,2);
        Array.Copy(BitConverter.GetBytes((ushort)sub.Length),0,buffer,10,2);
        Array.Copy(BitConverter.GetBytes((ushort)(sub.Length+2)),0,buffer,12,2);
        Array.Copy(BitConverter.GetBytes((ushort)display.Length),0,buffer,14,2);
        Array.Copy(sub,0,buffer,16,sub.Length);
        Array.Copy(display,0,buffer,16+sub.Length+2,display.Length);
        using(var h=CreateFile(path,0x40000000,7,IntPtr.Zero,3,0x02200000,IntPtr.Zero)) {
            if(h.IsInvalid) throw new Win32Exception(Marshal.GetLastWin32Error());
            uint returned;
            if(!DeviceIoControl(h,0x000900A4,buffer,(uint)buffer.Length,IntPtr.Zero,0,out returned,IntPtr.Zero))
                throw new Win32Exception(Marshal.GetLastWin32Error());
        }
    }
}
'@
$vcChildren = @(Get-ChildItem -LiteralPath $vcSource -Force)
foreach ($vcChild in $vcChildren) {
    if ([IO.Path]::GetFullPath($vcChild.FullName) -ne (Join-Path $vcSource $vcChild.Name)) { throw 'Unexpected child path.' }
}
New-Item -ItemType Directory -Path $vcTarget | Out-Null
$vcMoved = [Collections.Generic.List[string]]::new()
try {
    foreach ($vcChild in $vcChildren) {
        Move-Item -LiteralPath $vcChild.FullName -Destination (Join-Path $vcTarget $vcChild.Name)
        $vcMoved.Add($vcChild.Name)
    }
    if (@(Get-ChildItem -LiteralPath $vcSource -Force).Count -ne 0) { throw 'Source changed during migration; rolling back.' }
    [VideoCreateWorkspaceJunction]::Set($vcSource, $vcTarget)
} catch {
    $vcError = $_
    foreach ($vcName in $vcMoved) {
        if (Test-Path -LiteralPath (Join-Path $vcSource $vcName)) { throw 'Rollback target is occupied; files preserved in both roots for inspection.' }
        Move-Item -LiteralPath (Join-Path $vcTarget $vcName) -Destination (Join-Path $vcSource $vcName)
    }
    if (@(Get-ChildItem -LiteralPath $vcTarget -Force).Count -eq 0) { Remove-Item -LiteralPath $vcTarget }
    throw $vcError
}
$vcReceiptRoot = Join-Path $vcTarget 'analysis-frames\videocreate-migration'
New-Item -ItemType Directory -Path $vcReceiptRoot -Force | Out-Null
[ordered]@{ok=$true; source=$vcSource; physical_root=$vcTarget; compatibility='junction'; moved_children=@($vcMoved); copied_files=0} |
    ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $vcReceiptRoot 'workspace-migration.json') -Encoding UTF8
Get-Item -LiteralPath $vcSource,$vcTarget | Select-Object FullName,Attributes,LinkType,Target
