@echo off
python "%~dp0..\build_release.py" %*
exit /b %errorlevel%

