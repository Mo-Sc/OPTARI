@echo off
title PATARI Uninstaller
echo ===================================================
echo     PATARI Environment Cleanup Tool
echo ===================================================
echo.
if exist "patari-windows.exe" (
    echo Removing PATARI
    patari.exe self remove
    echo.
    echo SUCCESS: The environment cache has been completely removed!
    echo.
    echo You can drag 'patari.exe' and this uninstaller to the Recycle Bin.
) else (
    echo ERROR: Could not find 'patari.exe'.
    echo Please make sure this uninstaller is in the exact same folder as the PATARI app.
)

echo.
pause