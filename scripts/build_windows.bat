@echo off
setlocal

cd /d %~dp0\..

set "PYTHON_LAUNCHER="
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PYTHON_LAUNCHER=py -3"

if not defined PYTHON_LAUNCHER (
  python -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PYTHON_LAUNCHER=python"
)

if not defined PYTHON_LAUNCHER (
  for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
    if exist "%%~fD\python.exe" set "PYTHON_LAUNCHER="%%~fD\python.exe""
  )
)

if not defined PYTHON_LAUNCHER (
  echo Python 3.10 or newer was not found.
  exit /b 1
)

%PYTHON_LAUNCHER% -m pip install --disable-pip-version-check -r requirements-build.txt
if errorlevel 1 exit /b %errorlevel%

%PYTHON_LAUNCHER% scripts\generate_icons.py --windows --input icon.png
if errorlevel 1 exit /b %errorlevel%

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
mkdir build

set ADDDATA=--add-data "%CD%\assets;assets" --add-data "%CD%\icon.png;."
if exist tools set ADDDATA=%ADDDATA% --add-data "%CD%\tools;tools"

%PYTHON_LAUNCHER% -m PyInstaller ^
  --noconfirm ^
  --onefile ^
  --windowed ^
  --clean ^
  --additional-hooks-dir "%CD%\hooks" ^
  --collect-data UnityPy ^
  --hidden-import UnityPy ^
  --exclude-module numpy ^
  --exclude-module pandas ^
  --exclude-module scipy ^
  --exclude-module sqlalchemy ^
  --exclude-module PIL._avif ^
  --exclude-module PIL.AvifImagePlugin ^
  --specpath build ^
  --icon "%CD%\assets\icon.ico" ^
  --name "SR Playlist Forge" ^
  %ADDDATA% ^
  synth_playlist_editor.py

if errorlevel 1 exit /b %errorlevel%

echo Built Windows app at: %CD%\dist\SR Playlist Forge.exe
endlocal
