param(
    [Parameter(Mandatory = $true)]
    [string]$Percorso,
    [switch]$Finestra
)

$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

[StructLayout(LayoutKind.Sequential)]
public struct OnyxRect {
    public int Left;
    public int Top;
    public int Right;
    public int Bottom;
}

public static class OnyxForegroundWindow {
    [DllImport("user32.dll")] private static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] private static extern bool GetWindowRect(IntPtr hWnd, out OnyxRect rect);
    [DllImport("user32.dll")] private static extern bool IsIconic(IntPtr hWnd);
    [DllImport("user32.dll")] private static extern bool SetProcessDPIAware();
    [DllImport("dwmapi.dll")] private static extern int DwmGetWindowAttribute(IntPtr hWnd, int attribute, out OnyxRect value, int size);

    public static void EnableDpiAwareness() { SetProcessDPIAware(); }

    public static OnyxRect GetBounds() {
        EnableDpiAwareness();
        IntPtr handle = GetForegroundWindow();
        if (handle == IntPtr.Zero) throw new InvalidOperationException("Non trovo una finestra attiva da catturare.");
        if (IsIconic(handle)) throw new InvalidOperationException("La finestra attiva è ridotta a icona.");

        OnyxRect bounds;
        int result = DwmGetWindowAttribute(handle, 9, out bounds, Marshal.SizeOf(typeof(OnyxRect)));
        if (result != 0 || bounds.Right <= bounds.Left || bounds.Bottom <= bounds.Top) {
            if (!GetWindowRect(handle, out bounds)) throw new InvalidOperationException("Non riesco a leggere le dimensioni della finestra attiva.");
        }
        if (bounds.Right <= bounds.Left || bounds.Bottom <= bounds.Top) throw new InvalidOperationException("La finestra attiva non ha dimensioni valide.");
        return bounds;
    }
}
'@

$cartella = Split-Path -Parent $Percorso
if (-not (Test-Path -LiteralPath $cartella)) {
    New-Item -ItemType Directory -Path $cartella -Force | Out-Null
}

if ($Finestra) {
    $area = [OnyxForegroundWindow]::GetBounds()
    $sinistra = $area.Left
    $alto = $area.Top
    $larghezza = $area.Right - $area.Left
    $altezza = $area.Bottom - $area.Top
    $messaggio = 'Screenshot della finestra salvato.'
}
else {
    [OnyxForegroundWindow]::EnableDpiAwareness()
    $area = [System.Windows.Forms.SystemInformation]::VirtualScreen
    $sinistra = $area.Left
    $alto = $area.Top
    $larghezza = $area.Width
    $altezza = $area.Height
    $messaggio = 'Screenshot dello schermo salvato.'
}

if ($larghezza -le 0 -or $altezza -le 0) {
    throw "Dimensioni dell'area da catturare non valide."
}

$bitmap = [System.Drawing.Bitmap]::new($larghezza, $altezza)
$grafica = [System.Drawing.Graphics]::FromImage($bitmap)
try {
    $grafica.CopyFromScreen(
        $sinistra,
        $alto,
        0,
        0,
        $bitmap.Size,
        [System.Drawing.CopyPixelOperation]::SourceCopy
    )
    $bitmap.Save($Percorso, [System.Drawing.Imaging.ImageFormat]::Png)
}
finally {
    $grafica.Dispose()
    $bitmap.Dispose()
}

if (-not (Test-Path -LiteralPath $Percorso -PathType Leaf)) {
    throw 'Il file dello screenshot non è stato creato.'
}

[pscustomobject]@{ Ok = $true; Messaggio = $messaggio } | ConvertTo-Json -Compress
