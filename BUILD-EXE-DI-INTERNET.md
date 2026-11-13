# Membangun Titik.exe lewat internet

Tanpa memasang Python, tanpa memasang apa pun di komputer Anda. Komputer
Windows milik GitHub yang membangunnya, Anda tinggal mengunduh hasilnya.

Gratis. Repositori publik tidak dibatasi menit sama sekali; repositori
privat dapat jatah bulanan yang jauh lebih dari cukup untuk ini.

---

## Langkah

### 1. Buat repositori

Buka [github.com/new](https://github.com/new).

- **Repository name**: `titik`
- **Private** kalau tidak ingin orang lain melihatnya — Actions tetap jalan
- Jangan centang apa pun di bagian "Initialize this repository"
- Klik **Create repository**

### 2. Unggah berkasnya

Di halaman repositori yang baru, klik **uploading an existing file**.

Buka folder `Titik` di komputer Anda, pilih **semua isinya**, lalu seret
ke jendela browser. Tunggu sampai semua terunggah, lalu klik
**Commit changes**.

> **Penting: folder `.github` sering tidak ikut terseret.**
>
> Windows menyembunyikan folder yang namanya diawali titik, jadi folder
> `.github` mungkin tidak terlihat dan tidak ikut terunggah. Periksa
> setelah mengunggah — kalau tidak ada, buat manual:
>
> 1. Di repositori, klik **Add file** → **Create new file**
> 2. Di kotak nama berkas, ketik persis:
>    `.github/workflows/build-windows.yml`
>    (GitHub otomatis membuat foldernya saat Anda mengetik garis miring)
> 3. Buka `.github/workflows/build-windows.yml` di komputer Anda dengan
>    Notepad, salin seluruh isinya, tempel ke kotak editor GitHub
> 4. Klik **Commit changes**

### 3. Jalankan build

1. Klik tab **Actions** di repositori Anda
2. Kalau muncul tombol hijau "I understand my workflows, go ahead and
   enable them", klik itu
3. Di daftar kiri, pilih **Bangun Titik.exe (Windows)**
4. Klik **Run workflow** → **Run workflow**

Tunggu 3–6 menit. Titik hijau berarti berhasil.

### 4. Unduh exe-nya

Klik hasil build yang baru selesai. Gulir ke bawah ke bagian
**Artifacts**, lalu klik **Titik-windows-x64**.

Yang terunduh adalah berkas zip berisi `Titik.exe`. **Ekstrak dulu** —
jangan jalankan dari dalam zip.

---

## Yang dilakukan workflow ini

1. Menyiapkan Python 3.12 di Windows
2. Memasang PyInstaller
3. Memasang `pymobiledevice3` untuk dukungan iOS — kalau gagal, build
   tetap lanjut dan exe-nya tetap berfungsi untuk mode mock, feed, dan
   adb (Android)
4. **Menjalankan 60 uji unit** — build berhenti kalau ada yang gagal,
   jadi exe yang rusak tidak akan pernah sampai ke Anda
5. Membangun exe satu berkas dengan ikon dan metadata versi
6. **Menjalankan exe-nya** untuk memastikan benar-benar bisa dijalankan
7. Mengunggah hasilnya

Langkah 4 dan 6 itu yang membedakannya dari sekadar membungkus kode:
Anda tidak akan mengunduh exe yang gagal start.

---

## Setelah exe-nya ada

```
Titik.exe --backend mock          coba tanpa perangkat
Titik.exe --backend adb           emulator Android
Titik.exe --backend feed --lan    uji aplikasi Anda sendiri
Titik.exe --backend auto          iPhone fisik
```

Atau klik dua kali saja untuk mode otomatis.

Windows SmartScreen akan memperingatkan saat pertama dibuka karena
berkasnya tidak ditandatangani digital. Klik **More info** → **Run
anyway**. Itu normal; menandatanganinya butuh sertifikat berbayar.

---

## Kalau build gagal

Klik langkah yang gagal di halaman Actions — lognya lengkap dan
menunjukkan baris persisnya. Kirimkan ke Claude, dan dia bisa
memperbaiki workflow-nya.

---

## Satu peringatan

Ada situs-situs yang menawarkan "konversi Python ke exe online" dengan
cara mengunggah kode Anda. **Jangan pakai itu.** Anda menyerahkan kode
sumber ke pihak yang tidak dikenal, dan exe yang Anda terima kembali
tidak bisa Anda verifikasi isinya — itu vektor malware yang umum.

GitHub Actions berbeda: Anda melihat seluruh resepnya di
`build-windows.yml`, lognya terbuka, dan hasilnya dibangun dari kode
Anda sendiri di mesin yang bisa Anda audit.
