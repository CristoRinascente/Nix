$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPaths = @(
    (Join-Path $projectRoot '.venv\Scripts\python.exe'),
    (Join-Path $projectRoot '.venv\Scripts\pythonw.exe')
)
$interfacePath = Join-Path $projectRoot 'UI\BloomSource\src-tauri\target\onyx-ui-build-v5\release\onyx-ui.exe'
$logDirectory = Join-Path $projectRoot 'logs'
$pidFile = Join-Path $logDirectory 'onyx.pid'

# The PID file can be stale or missing after a forced exit. Find only Python
# processes launched from this project's private virtual environment.
$listeners = @(
    Get-Process -Name @('python', 'pythonw') -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Path -and ($pythonPaths -contains $_.Path)
        }
)
$interfaceProcesses = @(
    Get-Process -Name 'onyx-ui' -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Path -and [string]::Equals($_.Path, $interfacePath, [StringComparison]::OrdinalIgnoreCase)
        }
)

if (Test-Path -LiteralPath $pidFile -PathType Leaf) {
    $processId = 0
    if ([int]::TryParse((Get-Content -LiteralPath $pidFile -Raw), [ref]$processId) -and $processId -gt 0) {
        $pidProcess = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($pidProcess) {
            if (-not $pidProcess.Path -or
                -not ($pythonPaths | Where-Object {
                    [string]::Equals($_, $pidProcess.Path, [StringComparison]::OrdinalIgnoreCase)
                })) {
                throw "Il PID $processId non corrisponde all'interprete Python di Onyx; non ho terminato il processo."
            }
            $listeners += $pidProcess
        }
    }
}

$processes = @(@($listeners) + @($interfaceProcesses) | Sort-Object -Property Id -Unique)
if ($processes.Count -eq 0) {
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    Write-Output 'Onyx era già terminato.'
    exit 0
}

foreach ($process in $processes) {
    & taskkill.exe /PID $process.Id /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $stillRunning = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
        if ($stillRunning) {
            throw "Non sono riuscito a fermare il processo Onyx (PID $($process.Id))."
        }
    }
}

Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
Write-Output 'Motore Python e interfaccia Onyx fermati.'
