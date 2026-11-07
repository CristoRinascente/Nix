param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('status', 'set')]
    [string]$Azione,
    [ValidateRange(0, 100)]
    [int]$Luminosita = 0
)

$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

function Leggi-Luminosita {
    $monitor = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness | Select-Object -First 1
    if (-not $monitor) { throw 'Windows non espone la luminosità del display.' }
    return [int]$monitor.CurrentBrightness
}

try {
    if ($Azione -eq 'status') {
        [pscustomobject]@{ Ok = $true; Messaggio = 'Luminosità letta.'; Brightness = (Leggi-Luminosita) } | ConvertTo-Json -Compress
        exit 0
    }

    $methods = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | Select-Object -First 1
    if (-not $methods) { throw 'Windows non espone il controllo della luminosità del display.' }
    $null = $methods | Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{ Timeout = 1; Brightness = $Luminosita }
    Start-Sleep -Milliseconds 250
    $actual = Leggi-Luminosita
    if ([Math]::Abs($actual - $Luminosita) -gt 2) { throw "Il display non ha confermato il valore richiesto ($actual%)." }
    [pscustomobject]@{ Ok = $true; Messaggio = "Luminosità impostata al $actual%."; Brightness = $actual } | ConvertTo-Json -Compress
}
catch {
    [pscustomobject]@{ Ok = $false; Messaggio = $_.Exception.Message } | ConvertTo-Json -Compress
    exit 1
}
