$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

try {
    $cartella = Join-Path (Split-Path -Parent $PSScriptRoot) 'Screenshot'
    $ultimo = Get-ChildItem -LiteralPath $cartella -Filter '*.png' -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc, Name -Descending |
        Select-Object -First 1
    if (-not $ultimo) {
        throw 'Non trovo screenshot da copiare.'
    }

    $immagine = [System.Drawing.Image]::FromFile($ultimo.FullName)
    $bitmap = [System.Drawing.Bitmap]::new($immagine)
    try {
        [System.Windows.Forms.Clipboard]::SetImage($bitmap)
    }
    finally {
        $bitmap.Dispose()
        $immagine.Dispose()
    }

    if (-not [System.Windows.Forms.Clipboard]::ContainsImage()) {
        throw "Windows non ha confermato la copia dell'immagine negli appunti."
    }

    [pscustomobject]@{
        Ok = $true
        Messaggio = "Ho copiato negli appunti l'ultimo screenshot: $($ultimo.Name)."
    } | ConvertTo-Json -Compress
}
catch {
    [pscustomobject]@{ Ok = $false; Messaggio = $_.Exception.Message } | ConvertTo-Json -Compress
    exit 1
}
