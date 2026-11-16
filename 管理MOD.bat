@echo off
setlocal
set "PS=pwsh.exe"
where pwsh.exe >nul 2>nul || set "PS=powershell.exe"
if "%~1"=="" (
    "%PS%" -ExecutionPolicy Bypass -NoProfile -Command "$s = Get-ChildItem -LiteralPath '%~dp0' -Filter '*.ps1' | Select-Object -First 1; if ($s) { & $s.FullName -Interactive }"
) else (
    "%PS%" -ExecutionPolicy Bypass -NoProfile -Command "$s = Get-ChildItem -LiteralPath '%~dp0' -Filter '*.ps1' | Select-Object -First 1; if ($s) { & $s.FullName %* }"
)
