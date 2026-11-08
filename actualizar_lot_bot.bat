@echo off
rem LOT Bot - actualizar a la ultima version de GitHub (doble clic).
rem Normalmente no hace falta: LOT Bot avisa solo y se actualiza con un clic.
rem Sirve para la primera vez o si el boton «Actualizar» no funciona.
cd /d "%~dp0"
set "GIT="
where git >nul 2>&1 && set "GIT=git"
if not defined GIT if exist "%ProgramFiles%\Git\cmd\git.exe" set "GIT=%ProgramFiles%\Git\cmd\git.exe"
if not defined GIT if exist "%LOCALAPPDATA%\Programs\Git\cmd\git.exe" set "GIT=%LOCALAPPDATA%\Programs\Git\cmd\git.exe"
if not defined GIT for /d %%D in ("%LOCALAPPDATA%\GitHubDesktop\app-*") do if exist "%%D\resources\app\git\cmd\git.exe" set "GIT=%%D\resources\app\git\cmd\git.exe"
if not defined GIT (
    echo No se encuentra git. Instala Git para Windows o GitHub Desktop y vuelve a probar.
    pause
    exit /b 1
)
echo Descargando la ultima version de LOT Bot...
"%GIT%" stash push -m "LOT Bot: cambios locales antes de actualizar" >nul 2>&1
rem Si existe el canal «estable» en GitHub, se sigue ese; si no, la rama de esta copia.
"%GIT%" ls-remote --exit-code --heads origin estable >nul 2>&1
if errorlevel 1 (
    "%GIT%" pull --ff-only
) else (
    "%GIT%" fetch origin estable && "%GIT%" merge --ff-only origin/estable
)
if errorlevel 1 (
    echo.
    echo No se ha podido actualizar. Revisa el mensaje de arriba o contacta con soporte.
    pause
    exit /b 1
)
if exist ".venv\Scripts\python.exe" (
    echo Comprobando componentes...
    ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
)
echo.
echo LOT Bot esta actualizado. Abriendolo...
call "%~dp0iniciar_lot_bot.bat"
