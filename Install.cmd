@echo off
setlocal DisableDelayedExpansion
call "%~dp0InstallAndRun.cmd" --install-only %*
exit /b %errorlevel%
