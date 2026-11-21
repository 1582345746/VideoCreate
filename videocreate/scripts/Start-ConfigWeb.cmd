@echo off
setlocal DisableDelayedExpansion
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0config-web.ps1" %*
set "vcConfigWebExitCode=%errorlevel%"
if not "%vcConfigWebExitCode%"=="0" pause
exit /b %vcConfigWebExitCode%
