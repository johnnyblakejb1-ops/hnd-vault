@echo off
rem ONE double-click: Alain captures papers (using your Edge - no big download).
rem After 'q', he pushes to GitHub - or shows you how if git is missing.
cd /d "%~dp0"
set ALAIN_BROWSER_CHANNEL=msedge
python alain.py

where git >nul 2>nul
if %errorlevel%==0 (
  call capture.bat
) else (
  echo.
  echo Git is not installed - NO PROBLEM. Upload by hand instead:
  echo   1. The upload page just opened in your browser.
  echo   2. Drag the 'screenshots' folder into that page.
  echo   3. Click 'Commit changes'. Bea stitches automatically after.
  start "" "%~dp0screenshots"
  start "" "https://github.com/johnnyblakejb1-ops/hnd-vault/upload/main"
  pause
)
