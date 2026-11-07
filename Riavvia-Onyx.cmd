@echo off
setlocal
cd /d "%~dp0"
set "log=%~dp0logs\riavvio.log"
if not exist "%~dp0logs" mkdir "%~dp0logs"
echo ==== Riavvio %date% %time% ==== > "%log%"
echo Arresto, compilazione interfaccia e avvio Onyx.>> "%log%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0PowerShell\Riavvia-Onyx.ps1" >> "%log%" 2>&1
set "exitCode=%ERRORLEVEL%"
echo.>> "%log%"
echo Codice uscita: %exitCode%>> "%log%"
if not "%exitCode%"=="0" (
  echo Riavvio non riuscito. Dettagli in logs\riavvio.log
  type "%log%"
  if "%ONYX_BACKGROUND%"=="1" exit /b %exitCode%
  pause
)
exit /b %exitCode%
