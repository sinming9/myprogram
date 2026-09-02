@echo off
rem =============================================================
rem  ASCII ONLY - do not put Korean text in this file.
rem  Windows cmd parses .bat using the ANSI codepage (CP949 on
rem  Korean Windows); UTF-8 Korean text corrupts command parsing
rem  and breaks constructs like FOR/IN/DO.
rem  All Korean messages are printed by the Python script instead.
rem =============================================================
setlocal
cd /d "%~dp0"
chcp 65001 >nul

set "PY="

py -3 -c "import sys;sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"

if not defined PY (
  python -c "import sys;sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>nul
  if not errorlevel 1 set "PY=python"
)

if not defined PY (
  python3 -c "import sys;sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>nul
  if not errorlevel 1 set "PY=python3"
)

if not defined PY goto NOPY

%PY% "업로드_준비.py"
goto END

:NOPY
echo =============================================================
echo  Python 3.9 or newer was not found on this PC.
echo =============================================================
echo.
echo  1. Download Python from  https://www.python.org/downloads/
echo  2. During install, CHECK  "Add python.exe to PATH"
echo  3. Close this window, open it again, run this file again
echo.
pause

:END
endlocal
