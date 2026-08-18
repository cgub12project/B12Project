@echo off
setlocal

rem ============================================================
rem  FLASH demo helper: simulate a "high risk incoming call"
rem  to trigger the floating warning overlay.
rem
rem  Usage: just double-click (defaults to 0955888777, high risk,
rem  fake investment scam, 8 community reports already seeded).
rem  Or pass a different number as an argument, e.g.:
rem    demo_incoming_call.bat 0912345678   (mid-risk demo)
rem
rem  Requirement: the emulator must already be running, and the
rem  FLASH app must have been logged into at least once.
rem ============================================================

set NUMBER=%1
if "%NUMBER%"=="" set NUMBER=0955888777

set ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe
if not exist "%ADB%" set ADB=adb

echo [1/4] Checking emulator connection...
"%ADB%" get-state >nul 2>&1
if errorlevel 1 (
    echo No connected emulator/device found. Start the Android emulator first.
    pause
    exit /b 1
)

echo [2/4] Granting overlay permission (needed again after a wipe-data/reinstall, harmless if already granted)...
"%ADB%" shell appops set com.frauddetector SYSTEM_ALERT_WINDOW allow

echo [3/4] Setting FLASH as the default call screening app (same reason as above)...
"%ADB%" shell cmd role add-role-holder android.app.role.CALL_SCREENING com.frauddetector

echo [4/4] Simulating an incoming call from %NUMBER% (the red warning card should pop up at the bottom in a few seconds)...
"%ADB%" emu gsm call %NUMBER%

echo.
echo Done. Tap Decline on screen to hang up, or run demo_hangup_call.bat.
pause
