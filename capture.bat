@echo off
rem Alain just ran on your PC — push his captures to the repo.
rem Bea on GitHub stitches the PDFs automatically after this.
cd /d "%~dp0"
git add screenshots
git commit -m "alain: new captures from home PC"
git pull --rebase
git push
echo.
echo Pushed. Bea will stitch automatically - check the Actions tab.
pause
