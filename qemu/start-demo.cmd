@echo off
setlocal
cd /d "%~dp0"
set "DEMO_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%DEMO_PYTHON%" goto bundled
where py >nul 2>nul
if not errorlevel 1 goto pylauncher
where python >nul 2>nul
if not errorlevel 1 goto pythonpath
echo Python 3.11+ with Tkinter is required. See DEMO.md.
pause
exit /b 1
:bundled
"%DEMO_PYTHON%" -B "%~dp0demo.py"
goto result
:pylauncher
py -3 -B "%~dp0demo.py"
goto result
:pythonpath
python -B "%~dp0demo.py"
:result
if not errorlevel 1 exit /b 0
echo Demo exited with an error. See the message above and DEMO.md.
pause
exit /b 1
