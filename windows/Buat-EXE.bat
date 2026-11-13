@echo off
setlocal enabledelayedexpansion
title Titik - Membangun Titik.exe
color 0B
cd /d "%~dp0\.."

echo.
echo   ============================================
echo      Membangun Titik.exe
echo   ============================================
echo.
echo   Hasilnya satu berkas mandiri di folder dist\
echo   yang jalan tanpa Python terpasang.
echo.
echo   Butuh internet dan beberapa menit.
echo.

rem ---- Python -------------------------------------------------------
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY ( python --version >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo   [X] Python tidak ditemukan.
  echo.
  echo   Pasang Python 3.9+ dari python.org dan centang
  echo   "Add Python to PATH" saat memasang.
  echo.
  pause & exit /b 1
)
for /f "tokens=2" %%v in ('%PY% --version 2^>^&1') do set "PYVER=%%v"
echo   [1/4] Python %PYVER%

rem ---- Lingkungan ---------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo   [2/4] Membuat lingkungan terisolasi...
  %PY% -m venv .venv
  if errorlevel 1 ( echo   [X] Gagal membuat lingkungan. & pause & exit /b 1 )
) else (
  echo   [2/4] Lingkungan sudah ada.
)
set "VPY=.venv\Scripts\python.exe"

rem ---- Perkakas -----------------------------------------------------
echo   [3/4] Memasang PyInstaller dan pymobiledevice3...
"%VPY%" -m pip install --quiet --upgrade pip
"%VPY%" -m pip install --quiet --upgrade pyinstaller pymobiledevice3
if errorlevel 1 (
  echo.
  echo   [X] Pemasangan gagal. Periksa koneksi internet atau proxy.
  echo.
  pause & exit /b 1
)

rem ---- Build --------------------------------------------------------
echo   [4/4] Membangun ^(3-6 menit, layar akan ramai^)...
echo.

"%VPY%" -m PyInstaller ^
  --onefile ^
  --name Titik ^
  --icon "windows\titik.ico" ^
  --version-file "windows\version_info.txt" ^
  --add-data "titik\web;titik\web" ^
  --collect-all pymobiledevice3 ^
  --console ^
  --noconfirm ^
  --clean ^
  run_titik.py

if errorlevel 1 (
  echo.
  echo   [X] Build gagal. Gulir ke atas untuk melihat pesannya.
  echo.
  pause & exit /b 1
)

if not exist "dist\Titik.exe" (
  echo.
  echo   [X] Build selesai tetapi dist\Titik.exe tidak ada.
  echo.
  pause & exit /b 1
)

rem ---- Uji cepat ----------------------------------------------------
echo.
echo   Menguji hasilnya...
"dist\Titik.exe" --version
if errorlevel 1 (
  echo   [!] Exe terbangun tetapi gagal dijalankan. Laporkan pesan di atas.
) else (
  echo   [OK] Exe berjalan.
)

echo.
echo   ============================================
echo      Selesai:  dist\Titik.exe
echo   ============================================
echo.
echo   Klik dua kali untuk menjalankan, atau dari Command Prompt:
echo.
echo      dist\Titik.exe --backend mock      ^(coba tanpa perangkat^)
echo      dist\Titik.exe --backend adb       ^(emulator Android^)
echo      dist\Titik.exe --backend feed --lan ^(uji aplikasi sendiri^)
echo.
echo   Windows SmartScreen mungkin memperingatkan saat pertama dibuka,
echo   karena berkasnya tidak ditandatangani digital. Klik "More info"
echo   lalu "Run anyway". Itu normal untuk program buatan sendiri.
echo.
pause
