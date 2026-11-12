@echo off
rem ONE double-click: Alain captures papers with your Edge if possible.
rem If no browser is found, he downloads his own (ONE TIME) and retries.
cd /d "%~dp0"
set ALAIN_BROWSER_CHANNEL=
python alain.py
if errorlevel 1 (
  echo.
  echo No browser found - downloading Alain's own browser now.
  echo This is ONE TIME only, about 150 MB. Please wait...
  python -m playwright install chromium
  echo.
  echo Retrying Alain...
  python alain.py
)

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
