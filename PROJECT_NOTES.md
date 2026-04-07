# Project Notes

## Parked Issues

### USB eject warning after closing app

Status: Parked until we have more tester data.

What we know:
- A tester saw a Windows dialog saying the `ADB Interface` device could not be stopped because a program was still using it.
- The tester had already closed SR Playlist Forge.
- The headset was still connected by USB.
- `adb.exe` remained running until it was killed manually in Task Manager.
- We do not yet know for certain whether the tester used any Forge Quest-related action in that session.
- We also do not yet know whether Forge launched `adb.exe`, or whether another app already had ADB running.

Next questions when we revisit:
- Did SR Playlist Forge start `adb.exe`, or was it already running before Forge was opened?
- Were any other ADB-using tools open, such as SideQuest or Meta Quest Developer Hub?
- Did the tester use any Quest-related feature in Forge during that session?
- Which exact Forge build/version was running when this happened?
- Does the issue reproduce consistently, or was it a one-off event?

Likely investigation area:
- App startup and shutdown behavior around ADB detection/polling.
- Whether any background ADB process is left running after window close.
