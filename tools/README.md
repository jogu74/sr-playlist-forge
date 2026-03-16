Place bundled Android Platform Tools here when preparing a release build.

Recommended Windows layout:

- `tools/adb.exe`
- `tools/AdbWinApi.dll`
- `tools/AdbWinUsbApi.dll`

Alternative layout also supported by the app:

- `tools/platform-tools/adb.exe`
- `tools/platform-tools/AdbWinApi.dll`
- `tools/platform-tools/AdbWinUsbApi.dll`

At runtime the app first tries system `adb`, then falls back to these bundled locations.
