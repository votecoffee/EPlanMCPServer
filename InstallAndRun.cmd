@echo off
setlocal
pushd "%~dp0" || exit /b 1

if exist ".venv\Scripts\python.exe" goto existing_environment
where py >nul 2>nul
if errorlevel 1 goto try_python
py -3.13 --version >nul 2>nul
if errorlevel 1 goto default_python_launcher
py -3.13 "scripts\launcher.py" %*
goto finished

:default_python_launcher
py -3 "scripts\launcher.py" %*
goto finished

:try_python
where python >nul 2>nul
if errorlevel 1 goto missing_python
python "scripts\launcher.py" %*
goto finished

:existing_environment
".venv\Scripts\python.exe" "scripts\launcher.py" %*
goto finished

:missing_python
echo Python 3.11 or newer is required. Install Python, then run this file again. 1>&2
popd
exit /b 1

:finished
set "launcher_exit=%errorlevel%"
popd
exit /b %launcher_exit%
