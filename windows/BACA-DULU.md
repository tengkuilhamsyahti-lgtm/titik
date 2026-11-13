# Titik di Windows

## Cara tercepat

Buka folder `windows\`, lalu klik dua kali salah satu berkas ini.

| Berkas | Untuk apa |
|---|---|
| **Mode-Demo.bat** | Mencoba antarmukanya tanpa perangkat apa pun. **Mulai dari sini.** |
| **Mode-Feed-untuk-Pengembang.bat** | Menguji aplikasi Anda sendiri. Tanpa Developer Mode. |
| **Mode-Android.bat** | Emulator Android lewat adb. |
| **Jalankan-Titik.bat** | iPhone/iPad fisik. Butuh Developer Mode. |
| **Buat-EXE.bat** | Membangun `Titik.exe` mandiri (sekali saja). |

Saat pertama dijalankan, skripnya akan:

1. Mencari Python di komputer Anda
2. Membuat lingkungan terisolasi di folder `.venv\` — **tidak mengubah Python sistem Anda**
3. Memasang `pymobiledevice3` ke dalam lingkungan itu
4. Menjalankan Titik dan membuka browser

Butuh sekitar 30 detik sekali saja. Jalan berikutnya langsung menyala.

## Kalau Python belum ada

Skripnya akan memberi tahu. Pasang dari [python.org](https://www.python.org/downloads/),
versi 3.9 atau lebih baru.

**Satu hal yang paling sering terlewat:** centang **"Add Python to PATH"** di layar
pertama penginstal. Tanpa itu, skrip tidak akan menemukannya.

## Membuat Titik.exe

Jalankan `Buat-EXE.bat`. Hasilnya satu berkas mandiri di `dist\Titik.exe` yang bisa
dijalankan di komputer mana pun tanpa Python terpasang.

Butuh beberapa menit, dan hanya perlu dilakukan sekali.

Windows SmartScreen kemungkinan akan memperingatkan saat Anda membukanya, karena
berkasnya tidak ditandatangani secara digital. Itu normal untuk program yang Anda
bangun sendiri — klik **More info** lalu **Run anyway**. Menandatanganinya butuh
sertifikat kode berbayar.

## Menghapus

Hapus saja seluruh foldernya. Tidak ada yang ditulis ke registry, tidak ada layanan
yang dipasang, tidak ada berkas sistem yang disentuh. Satu-satunya jejak di luar
folder ini adalah `%USERPROFILE%\.titik\favorites.json`, yang menyimpan favorit Anda.

## Kalau macet

**Jendela langsung tertutup.** Jalankan lewat Command Prompt supaya pesannya terbaca:

```
cd C:\path\ke\titik-app
windows\Jalankan-Titik.bat
```

**"'py' is not recognized"** — Python belum di PATH. Pasang ulang dengan opsi
"Add Python to PATH" tercentang.

**Pemasangan pymobiledevice3 gagal** — biasanya firewall kantor atau proxy. Mode
Demo dan Mode Feed tetap jalan tanpa paket itu.

**Perangkat iOS tidak terdeteksi** — pasang iTunes versi desktop dari Apple
(bukan dari Microsoft Store). Driver USB-nya ikut terpasang bersamanya, dan
Windows memerlukannya untuk bicara dengan iPhone.

**iOS 17+ minta tunnel** — buka PowerShell **sebagai Administrator** lalu jalankan:

```
pymobiledevice3 remote tunneld --userspace
```

Biarkan jendela itu terbuka, lalu jalankan Titik di jendela lain.

## Catatan kejujuran

Skrip-skrip ini ditulis dengan cermat tetapi **belum pernah dijalankan di Windows**
— dibuat di lingkungan Linux. Logikanya lurus dan tidak eksotis, tapi kalau ada yang
meleset, kirimkan isi jendelanya dan saya perbaiki.
