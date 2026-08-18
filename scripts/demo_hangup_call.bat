@echo off
rem Hang up the call simulated by demo_incoming_call.bat (double-click, no need to wait for the 12s auto-dismiss)
set ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe
if not exist "%ADB%" set ADB=adb
"%ADB%" shell input keyevent KEYCODE_ENDCALL
