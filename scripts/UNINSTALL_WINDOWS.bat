@echo off
title OPTARI Uninstaller
echo ===================================================
echo     OPTARI Environment Cleanup Tool
echo ===================================================
echo.
for %%F in ("%~dp0optari*.exe") do if exist "%%~fF" (
    echo Removing OPTARI from "%%~nxF"
    "%%~fF" self remove
    echo.
    echo SUCCESS: The environment cache has been completely removed!
    echo.
    echo You can drag "%%~nxF" and this uninstaller to the Recycle Bin.
    goto :done
)

echo ERROR: Could not find an executable starting with 'optari'.
echo Please make sure this uninstaller is in the exact same folder as the OPTARI app.

:done
echo.
pause