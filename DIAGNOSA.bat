@echo off
cd /d "%~dp0"
set "LOG=%~dp0diagnosa.txt"

echo ================================================ > "%LOG%"
echo  DIAGNOSA TITIK                                 >> "%LOG%"
echo  %DATE% %TIME%                                  >> "%LOG%"
echo ================================================ >> "%LOG%"
echo. >> "%LOG%"

echo [folder kerja] >> "%LOG%"
echo %CD% >> "%LOG%"
echo. >> "%LOG%"

echo [uji: py -3 --version] >> "%LOG%"
py -3 --version >> "%LOG%" 2>&1
echo   errorlevel=%ERRORLEVEL% >> "%LOG%"
echo. >> "%LOG%"

echo [uji: python --version] >> "%LOG%"
python --version >> "%LOG%" 2>&1
echo   errorlevel=%ERRORLEVEL% >> "%LOG%"
echo. >> "%LOG%"

echo [uji: python3 --version] >> "%LOG%"
python3 --version >> "%LOG%" 2>&1
echo   errorlevel=%ERRORLEVEL% >> "%LOG%"
echo. >> "%LOG%"

echo [lokasi: where python] >> "%LOG%"
where python >> "%LOG%" 2>&1
echo. >> "%LOG%"

echo [lokasi: where py] >> "%LOG%"
where py >> "%LOG%" 2>&1
echo. >> "%LOG%"

echo [isi folder] >> "%LOG%"
dir /b >> "%LOG%" 2>&1
echo. >> "%LOG%"

echo [PATH] >> "%LOG%"
echo %PATH% >> "%LOG%"
echo. >> "%LOG%"

echo [selesai] >> "%LOG%"

echo.
echo   ============================================
echo      Diagnosa selesai.
echo   ============================================
echo.
echo   Berkas diagnosa.txt sudah dibuat di folder ini.
echo   Beri tahu Claude, dan dia akan membacanya sendiri.
echo.
echo   Ringkasan cepat:
echo.
py -3 --version 2>nul || python --version 2>nul || echo   ^>^> PYTHON TIDAK DITEMUKAN ^<^<
echo.
pause
