@echo off
setlocal
set "HERE=%~dp0"
set "PYW="

rem DPET_PYW: explicit interpreter, highest priority (dev / acceptance)
if defined DPET_PYW set "PYW=%DPET_PYW%"

rem 1) portable runtime shipped inside the folder - makes the package self-contained
if not defined PYW if exist "%HERE%runtime\pythonw.exe" set "PYW=%HERE%runtime\pythonw.exe"

rem 2) pythonw / python found on PATH
if not defined PYW for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW for /f "delims=" %%i in ('where python 2^>nul') do if not defined PYW set "PYW=%%i"

rem 3) py launcher - take pythonw.exe sitting next to its interpreter
if not defined PYW for /f "delims=" %%i in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do if not defined PYBIN set "PYBIN=%%i"
if not defined PYW if defined PYBIN for %%j in ("%PYBIN%") do if exist "%%~dpjpythonw.exe" set "PYW=%%~dpjpythonw.exe"

if not defined PYW goto nopython

rem preflight: the chosen interpreter must actually be able to import PyQt5
"%PYW%" -c "import PyQt5" 2>nul
if errorlevel 1 goto nopyqt

start "" "%PYW%" "%HERE%src\deepseek_pet.py"
exit /b 0

:nopython
echo.
echo   [X] Python not found.
echo       Install Python 3.9+ ^(tick "Add python.exe to PATH"^), then run:
echo           pip install pyqt5
echo.
echo       Alternatives:
echo         - put a pythonw.exe into the "runtime" folder next to this file
echo         - set DPET_PYW to the full path of an existing pythonw.exe
echo.
pause
exit /b 1

:nopyqt
echo.
echo   [X] PyQt5 is missing for this interpreter:
echo       %PYW%
echo.
echo       Install it with:   pip install pyqt5
echo       Or set DPET_PYW to an interpreter that already has PyQt5.
echo.
pause
exit /b 1
