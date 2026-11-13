@echo off
rem Mode feed: untuk menguji aplikasi Anda sendiri.
rem Tanpa Developer Mode, tanpa Mac, tanpa kabel.
cd /d "%~dp0"
call "Jalankan-Titik.bat" --backend feed --lan
