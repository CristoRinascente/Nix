$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$stopScript = Join-Path $PSScriptRoot 'Ferma-Onyx.ps1'
$buildScript = Join-Path $PSScriptRoot 'Compila-Interfaccia-Onyx.ps1'
$launcherBuildScript = Join-Path $PSScriptRoot 'Compila-Onyx.ps1'
$startScript = Join-Path $PSScriptRoot 'Avvia-Onyx.ps1'
$launcherPath = Join-Path $projectRoot 'Onyx.exe'
$launcherSourcePath = Join-Path $projectRoot 'Azioni\OnyxTray.cs'
$launcherIconPath = Join-Path $projectRoot 'UI\assets\ONIX_Taskbar_Icon.ico'

foreach ($scriptPath in @($stopScript, $buildScript, $launcherBuildScript, $startScript, $launcherSourcePath, $launcherIconPath)) {
    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
        throw "Script necessario non trovato: $scriptPath"
    }
}

& $stopScript

# A restart must also release the tray singleton; otherwise the new launcher
# only displays “Onyx è già avviato” and leaves the listener paused.
$trayProcesses = @(
    Get-Process -Name 'Onyx' -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Path -and [string]::Equals($_.Path, $launcherPath, [StringComparison]::OrdinalIgnoreCase)
        }
)
foreach ($trayProcess in $trayProcesses) {
    Stop-Process -Id $trayProcess.Id -Force
    try { $trayProcess.WaitForExit(5000) } catch { }
    if (Get-Process -Id $trayProcess.Id -ErrorAction SilentlyContinue) {
        throw "Non sono riuscito a chiudere la tray Onyx (PID $($trayProcess.Id))."
    }
}

& $buildScript

$launcherNeedsBuild = -not (Test-Path -LiteralPath $launcherPath -PathType Leaf)
if (-not $launcherNeedsBuild) {
    $launcherWriteTime = (Get-Item -LiteralPath $launcherPath).LastWriteTimeUtc
    $launcherChangedInputs = @($launcherSourcePath, $launcherIconPath) | Where-Object {
        (Get-Item -LiteralPath $_).LastWriteTimeUtc -gt $launcherWriteTime
    }
    $launcherNeedsBuild = @($launcherChangedInputs).Count -gt 0
}

if ($launcherNeedsBuild) {
    & $launcherBuildScript
} else {
    Write-Output 'Launcher Onyx già aggiornato; salto la ricompilazione C#.'
}

& $startScript
