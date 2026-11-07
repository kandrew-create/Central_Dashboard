# Convert the Windows timezone through its installed ICU data, without guessing
# from the current UTC offset (which loses historical daylight-saving rules).
function Get-CollectorWindowsTimezone {
    $windowsZone = (Get-TimeZone).Id
    $ianaZone = ''
    try {
        $clockSettings = Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\TimeZoneInformation' -ErrorAction Stop
        if ($clockSettings.DynamicDaylightTimeDisabled -eq 1) {
            return [PSCustomObject]@{ WindowsId=$windowsZone; IanaId='' }
        }
        if (-not ('Linker.CollectorTimeZone' -as [type])) {
            Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
namespace Linker {
    public static class CollectorTimeZone {
        [DllImport("icu.dll", CharSet=CharSet.Unicode, CallingConvention=CallingConvention.Cdecl)]
        public static extern int ucal_getTimeZoneIDForWindowsID(string winid, int length,
            [MarshalAs(UnmanagedType.LPStr)] string region, StringBuilder result, int capacity, ref int status);
    }
}
'@
        }
        $buffer = New-Object System.Text.StringBuilder 128
        $status = 0
        $length = [Linker.CollectorTimeZone]::ucal_getTimeZoneIDForWindowsID($windowsZone, -1, $null, $buffer, 128, [ref]$status)
        if ($status -le 0 -and $length -gt 0 -and $length -lt 128) { $ianaZone = $buffer.ToString() }
    } catch {
        # Keep detection optional. A failed conversion must never guess a zone
        # or prevent opening the existing Collector for recovery.
    }
    return [PSCustomObject]@{ WindowsId=$windowsZone; IanaId=$ianaZone }
}
