$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$launcherPath = Join-Path $projectRoot 'Onyx.exe'
$buildScript = Join-Path $PSScriptRoot 'Compila-Onyx.ps1'

if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) {
    if (-not (Test-Path -LiteralPath $buildScript -PathType Leaf)) {
        throw "Compilatore di Onyx non trovato: $buildScript"
    }
    & $buildScript
}

if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) {
    throw "Applicazione Onyx non trovata: $launcherPath"
}

$appLogPath = Join-Path $projectRoot 'logs\onyx-app.log'
$gestureLogPath = Join-Path $projectRoot 'logs\onyx-gestures.log'
$startedAt = [DateTime]::UtcNow
$startedAtUnixMs = ([DateTimeOffset]$startedAt).ToUnixTimeMilliseconds()
$launcher = Start-Process -FilePath $launcherPath -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
$startupDeadline = [DateTime]::UtcNow.AddSeconds(15)
$startupLogged = $false
$gestureHookInstalled = $false

while ([DateTime]::UtcNow -lt $startupDeadline) {
    $launcher.Refresh()
    if ($launcher.HasExited) {
        throw "Onyx.exe è terminato durante l'avvio (codice $($launcher.ExitCode)). Controlla logs\onyx-app.log."
    }
    if (Test-Path -LiteralPath $appLogPath -PathType Leaf) {
        $startupLogged = (Get-Item -LiteralPath $appLogPath).LastWriteTimeUtc -ge $startedAt
    }

    if ((Test-Path -LiteralPath $gestureLogPath -PathType Leaf) -and
        (Get-Item -LiteralPath $gestureLogPath).LastWriteTimeUtc -ge $startedAt) {
        try {
            $hookLines = Get-Content -LiteralPath $gestureLogPath -Tail 80 -ErrorAction Stop
            foreach ($line in $hookLines) {
                if ($line -match '^(?<timestamp>\d+)\s+hook installato centro=' ) {
                    [long]$hookTimestamp = 0
                    if ([long]::TryParse($Matches.timestamp, [ref]$hookTimestamp) -and $hookTimestamp -ge $startedAtUnixMs) {
                        $gestureHookInstalled = $true
                        break
                    }
                }
            }
        } catch {
            $gestureHookInstalled = $false
        }
    }

    if ($startupLogged -and $gestureHookInstalled) { break }
    Start-Sleep -Milliseconds 250
}

if (-not $startupLogged) {
    & taskkill.exe /PID $launcher.Id /T /F | Out-Null
    throw "Onyx.exe non ha registrato l'avvio in logs\onyx-app.log entro 15 secondi."
}

if (-not $gestureHookInstalled) {
    if (-not $launcher.HasExited) {
        & taskkill.exe /PID $launcher.Id /T /F | Out-Null
    }
    throw "Onyx.exe ha avviato il motore, ma il log non conferma il hook del notch in logs\onyx-gestures.log entro 15 secondi."
}

Write-Output 'Onyx avviato: motore vocale e hook del notch sono attivi. Da lì puoi mettere in pausa l''ascolto o uscire.'
