@echo off
setlocal

cd /d %~dp0\..

py -m pip install --upgrade pip
py -m pip install -r requirements-build.txt
py scripts\generate_icons.py --windows --input icon.png

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

py -m PyInstaller ^
  --noconfirm ^
  --onefile ^
  --windowed ^
  --clean ^
  --icon assets\icon.ico ^
  --name "SR Playlist Forge" ^
  synth_playlist_editor.py

echo Built Windows app at: %CD%\dist\SR Playlist Forge.exe
endlocal
