@echo off
setlocal enabledelayedexpansion
title Titik - Pengubah Lokasi GPS
color 0B
cd /d "%~dp0\.."

echo.
echo   ============================================
echo      t i t i k  -  pengubah lokasi GPS
echo   ============================================
echo.

rem ---- 1. Cari Python ----------------------------------------------
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY ( python --version >nul 2>&1 && set "PY=python" )

if not defined PY (
  echo   [X] Python tidak ditemukan.
  echo.
  echo   Pasang Python 3.9 atau lebih baru dari python.org
  echo   JANGAN LUPA centang "Add Python to PATH" saat memasang.
  echo.
  echo   Setelah terpasang, tutup jendela ini dan jalankan lagi.
  echo.
  pause
  exit /b 1
)

for /f "tokens=2" %%v in ('%PY% --version 2^>^&1') do set "PYVER=%%v"
echo   [1/4] Python %PYVER% ditemukan.

rem ---- 2. Siapkan lingkungan terisolasi -----------------------------
if not exist ".venv\Scripts\python.exe" (
  echo   [2/4] Menyiapkan lingkungan ^(sekali saja, ~30 detik^)...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo   [X] Gagal membuat lingkungan virtual.
    pause
    exit /b 1
  )
) else (
  echo   [2/4] Lingkungan sudah siap.
)

set "VPY=.venv\Scripts\python.exe"

rem ---- 3. Pasang dependensi ----------------------------------------
"%VPY%" -c "import pymobiledevice3" >nul 2>&1
if errorlevel 1 (
  echo   [3/4] Memasang pymobiledevice3 ^(butuh internet^)...
  "%VPY%" -m pip install --quiet --upgrade pip
  "%VPY%" -m pip install --quiet --upgrade pymobiledevice3
  if errorlevel 1 (
    echo.
    echo   [!] Pemasangan gagal. Periksa koneksi internet.
    echo       Titik tetap bisa dijalankan dalam mode demo.
    echo.
  )
) else (
  echo   [3/4] Dependensi sudah terpasang.
)

rem ---- 4. Jalankan --------------------------------------------------
echo   [4/4] Menjalankan Titik...
echo.
echo   Browser akan terbuka sendiri.
echo   Tutup jendela ini atau tekan Ctrl+C untuk berhenti.
echo.

"%VPY%" -m titik %*

echo.
echo   Titik berhenti.
pause
