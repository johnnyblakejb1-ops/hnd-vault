@echo off
rem ONE double-click: Alain captures papers (using your Edge - no big download),
rem then pushes them to GitHub. Bea on GitHub stitches the PDFs automatically.
cd /d "%~dp0"
set ALAIN_BROWSER_CHANNEL=msedge
python alain.py
call capture.bat
