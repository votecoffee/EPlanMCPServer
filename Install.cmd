@echo off
setlocal
call "%~dp0InstallAndRun.cmd" --install-only %*
exit /b %errorlevel%
