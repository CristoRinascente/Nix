$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$bloomRoot = Join-Path $projectRoot 'UI\BloomSource'
$tauriRoot = Join-Path $bloomRoot 'src-tauri'
$targetDirectory = Join-Path $tauriRoot 'target\onyx-ui-build-v5'
$env:CARGO_TARGET_DIR = $targetDirectory
$localTools = Join-Path $projectRoot '.tools'
$localCargo = Join-Path $localTools 'cargo\bin'
$localRustup = Join-Path $localTools 'rustup'
$localBun = Join-Path $localTools 'bun.exe'

if (Test-Path -LiteralPath $localCargo -PathType Container) {
    $env:CARGO_HOME = Join-Path $localTools 'cargo'
    $env:RUSTUP_HOME = $localRustup
    $env:Path = "$localCargo;$env:Path"
}

$bunCommand = Get-Command bun -ErrorAction SilentlyContinue
if ($bunCommand) {
    $bunCommand = $bunCommand.Source
} elseif (Test-Path -LiteralPath $localBun -PathType Leaf) {
    $bunCommand = $localBun
} else {
    throw "Non trovo Bun. Installa Bun oppure colloca bun.exe in $localTools."
}

$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vsInstall = if (Test-Path -LiteralPath $vswhere) {
    & $vswhere -latest -products '*' -property installationPath
}
if (-not $vsInstall) {
    $vsInstall = Get-ChildItem (Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio') -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Get-ChildItem $_.FullName -Directory -ErrorAction SilentlyContinue } |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'VC\Auxiliary\Build\vcvars64.bat') } |
        Select-Object -First 1 -ExpandProperty FullName
}
if ($vsInstall) {
    $vcvars = Join-Path $vsInstall 'VC\Auxiliary\Build\vcvars64.bat'
    if (Test-Path -LiteralPath $vcvars) {
        $environment = & $env:ComSpec /d /c "call `"$vcvars`" >nul && set"
        if ($LASTEXITCODE -eq 0) {
            foreach ($entry in $environment) {
                $separator = $entry.IndexOf('=')
                if ($separator -gt 0) {
                    $name = $entry.Substring(0, $separator)
                    $value = $entry.Substring($separator + 1)
                    Set-Item -Path "Env:$name" -Value $value
                }
            }
        }
    }
}

foreach ($tool in @('cargo', 'rustc')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "Non trovo '$tool'. Installa Bun e Rust stable con target MSVC, poi riapri PowerShell."
    }
}

Push-Location $bloomRoot
try {
    $soundDirectory = Join-Path $bloomRoot 'public\sounds'
    New-Item -ItemType Directory -Force -Path $soundDirectory | Out-Null
    Copy-Item -LiteralPath (Join-Path $projectRoot 'Suoni\in.mp3') -Destination (Join-Path $soundDirectory 'in.mp3') -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot 'Suoni\out.mp3') -Destination (Join-Path $soundDirectory 'out.mp3') -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot 'Suoni\Non ho capito.mp3') -Destination (Join-Path $soundDirectory 'non-ho-capito.mp3') -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot 'Suoni\allarme timer.mp3') -Destination (Join-Path $soundDirectory 'allarme-timer.mp3') -Force
    & $bunCommand install
    if ($LASTEXITCODE -ne 0) { throw "bun install non riuscito (codice $LASTEXITCODE)." }

    & $bunCommand run tauri build --no-bundle
    if ($LASTEXITCODE -ne 0) { throw "Compilazione dell'interfaccia Onyx non riuscita (codice $LASTEXITCODE)." }
}
finally {
    Pop-Location
}

$interfacePath = Join-Path $targetDirectory 'release\onyx-ui.exe'
if (-not (Test-Path -LiteralPath $interfacePath -PathType Leaf)) {
    throw "La compilazione è terminata ma non trovo l'eseguibile: $interfacePath"
}
Write-Output "Interfaccia Onyx compilata: $interfacePath"
