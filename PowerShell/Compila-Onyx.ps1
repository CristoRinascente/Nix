$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$sourcePath = Join-Path $projectRoot 'Azioni\OnyxTray.cs'
$iconPath = Join-Path $projectRoot 'UI\assets\ONIX_Taskbar_Icon.ico'
$outputPath = Join-Path $projectRoot 'Onyx.exe'
$compilerPath = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'

if (-not (Test-Path -LiteralPath $compilerPath -PathType Leaf)) {
    $compilerPath = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
}
if (-not (Test-Path -LiteralPath $compilerPath -PathType Leaf)) {
    throw 'Non trovo il compilatore C# incluso in Windows.'
}
if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
    throw "Codice C# non trovato: $sourcePath"
}
if (-not (Test-Path -LiteralPath $iconPath -PathType Leaf)) {
    throw "Icona Onyx non trovata: $iconPath"
}

& $compilerPath /nologo /target:winexe /platform:anycpu /optimize+ `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll `
    "/win32icon:$iconPath" "/out:$outputPath" $sourcePath
if ($LASTEXITCODE -ne 0) {
    throw "Compilazione di Onyx non riuscita (codice $LASTEXITCODE)."
}

Write-Output "Applicazione Onyx compilata: $outputPath"
