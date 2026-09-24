@echo off
title PATARI Uninstaller
echo ===================================================
echo     PATARI Environment Cleanup Tool
echo ===================================================
echo.
for %%F in ("%~dp0patari*.exe") do if exist "%%~fF" (
    echo Removing PATARI from "%%~nxF"
    "%%~fF" self remove
    echo.
    echo SUCCESS: The environment cache has been completely removed!
    echo.
    echo You can drag "%%~nxF" and this uninstaller to the Recycle Bin.
    goto :done
)

echo ERROR: Could not find an executable starting with 'patari'.
echo Please make sure this uninstaller is in the exact same folder as the PATARI app.

:done
echo.
pause