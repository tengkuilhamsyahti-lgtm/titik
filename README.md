<div align="center">
<img src="titik/web/logo.svg" width="180" alt="Titik">

**Ubah lokasi GPS perangkat Anda sendiri — tanpa jailbreak, tanpa langganan.**
</div>

---

## Apa ini

Titik adalah pengubah lokasi GPS untuk iPhone dan iPad, berjalan di komputer
Anda sendiri. Ia memakai layanan *developer* resmi Apple (`DVTSimulateLocation`)
lewat [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) — mekanisme
yang sama persis dengan yang dipakai Xcode untuk mensimulasikan lokasi saat
menguji aplikasi.

Tidak ada jailbreak. Tidak ada modifikasi iOS. Tidak ada login Apple ID.
Tidak ada server kami — tidak ada server kami sama sekali.

### Fitur

| | |
|---|---|
| **Teleport** | Satu klik ke titik mana pun. Tempel koordinat atau tautan Google Maps. |
| **Rute** | Susun jalur multi-titik, atur kecepatan 1–120 km/j, berhenti / ulang / bolak-balik. |
| **Joystick** | Kendali arah real-time dengan tuas lingkar. |
| **GPX** | Impor jalur dari aplikasi olahraga, ekspor rute buatan Anda. |
| **Favorit** | Simpan tempat dan rute yang sering dipakai. |
| **Realisme** | Atur interval pengiriman dan derau posisi agar menyerupai GPS sungguhan. |

---

## Jalankan

### Windows

Klik dua kali **`windows\Mode-Demo.bat`**. Skripnya menyiapkan segalanya sendiri.
Selengkapnya di [`windows\BACA-DULU.md`](windows/BACA-DULU.md), termasuk cara
membangun `Titik.exe` mandiri.

### macOS dan Linux

```bash
# 1. Pasang dependensi
pip install -U pymobiledevice3

# 2. Coba antarmukanya dulu tanpa perangkat apa pun
python -m titik --backend mock

# 3. Kalau sudah cocok, colokkan iPhone lalu
python -m titik
```

Browser akan terbuka sendiri di `http://127.0.0.1:8787`.
Tekan `Ctrl+C` untuk berhenti — GPS perangkat otomatis dikembalikan ke aslinya.

```
python -m titik --backend {auto|api|cli|adb|feed|mock}
python -m titik --udid <UDID>     # perangkat tertentu (UDID iOS atau serial adb)
python -m titik --lan             # agar perangkat lain di jaringan bisa menjangkau feed
python -m titik --port 9000       # ganti port
python -m titik --no-browser      # jangan buka browser
```

**Mengembangkan aplikasi sendiri?** Lompat ke
[Untuk pengembang](#untuk-pengembang-menguji-aplikasi-sendiri) — ada jalur yang
tidak memerlukan Developer Mode sama sekali.

---

## Persiapan sekali jalan di iPhone

**1. Nyalakan Developer Mode** (iOS 16 ke atas)

`Settings` → `Privacy & Security` → `Developer Mode` → aktifkan → perangkat akan
restart. Menu ini baru muncul setelah komputer pernah menyambung sekali, jadi
colokkan kabelnya dulu kalau belum terlihat.

**2. Percayai komputer ini**

Colokkan kabel, buka kunci iPhone, tekan **Trust** saat ditanya.

**3. Untuk iOS 17 ke atas: tunnel**

iOS 17 memindahkan layanan developer ke protokol RemoteXPC yang butuh tunnel
tepercaya. pymobiledevice3 11.x biasanya membangunnya sendiri. Kalau Titik
mengeluh tunnel tidak ada, buka terminal **terpisah** dan biarkan terbuka:

```bash
pymobiledevice3 remote tunneld --userspace      # tanpa sudo
sudo pymobiledevice3 remote tunneld             # kalau yang atas gagal
```

Di Windows, gunakan terminal **Administrator** untuk perintah bersudo itu.

---

## Lima backend

| Backend | Untuk | Butuh Developer Mode? |
|---|---|---|
| `api` | iPhone/iPad fisik, jalur cepat | Ya |
| `cli` | iPhone/iPad fisik, jalur cadangan | Ya |
| `adb` | Emulator Android | Tidak |
| `feed` | Aplikasi Anda sendiri, platform apa pun | **Tidak** |
| `mock` | Mencoba antarmuka tanpa perangkat | Tidak |

`auto` mencoba `api` lalu `cli`.

**`api`** — mengimpor modul Python pymobiledevice3 dan mempertahankan satu sesi
DVT tetap terbuka. Satu pembaruan lokasi hanya butuh milidetik, jadi inilah yang
membuat rute bergerak mulus.

**`cli`** — memanggil executable `pymobiledevice3` sebagai subprocess. Satu proses
per perintah, jadi hitung 1–3 detik per pembaruan: cukup untuk teleport, terlalu
lambat untuk rute. Kontraknya jauh lebih stabil terhadap perubahan internal
pustaka, jadi dipakai sebagai cadangan.

**`adb`** — Android lewat `adb emu geo fix`. Berjalan di Windows dan Linux, bukan
hanya macOS. Perangkat Android fisik tidak didukung: Android hanya menerima lokasi
palsu dari aplikasi yang dipilih sebagai mock location provider di Developer
Options, jadi pakai `feed` untuk itu.

**`feed`** — lihat bagian berikut.

**`mock`** — tidak menyentuh perangkat apa pun. Gunakan untuk mencoba antarmuka,
atau untuk memastikan masalah ada di sisi perangkat dan bukan di Titik.

---

## Untuk pengembang: menguji aplikasi sendiri

Kalau yang Anda uji adalah aplikasi buatan sendiri, **jangan palsukan di level
sistem sama sekali.** Mode `feed` membalik arah alirannya: Titik menyiarkan posisi
lewat HTTP, dan aplikasi Anda yang mengambilnya sebagai sumber lokasi pada build
internal.

```bash
python -m titik --backend feed --lan
```

```
Feed JSON   : http://192.168.1.10:8787/feed/location
Feed aliran : http://192.168.1.10:8787/feed/stream
```

Peta, penyusun rute, joystick, dan kendali kecepatan bekerja seperti biasa —
hanya tujuan pengirimannya yang berbeda.

### Kenapa ini lebih baik

- **Tanpa Developer Mode.** Build TestFlight berjalan tanpanya, jadi pengujian di
  iPhone fisik tetap mungkin.
- **Tanpa Mac.** Berjalan dari Windows atau Linux.
- **Deterministik.** Tidak ada tunnel yang putus, tidak ada DDI yang gagal mount.
- **Jalan di CI** tanpa perangkat sama sekali.
- **Bisa menguji yang mustahil dipalsukan dari luar**: akurasi memburuk, sinyal
  hilang, lompatan posisi, izin ditolak. Spoofing sistem tidak menyentuh itu.

### Bentuk datanya

```json
{
  "active": true,
  "mode": "route",
  "lat": -6.2088, "lon": 106.8456,
  "course": 90.0,
  "speed": 10.0,
  "accuracy": 5.0,
  "ts": 1763000000.0
}
```

`course` dalam derajat dari utara dan `speed` dalam meter per detik, keduanya `-1`
bila tidak diketahui — mengikuti konvensi `CLLocation` dan `Location` Android, jadi
bisa dipetakan langsung.

`/feed/stream` mengirim bentuk yang sama sebagai Server-Sent Events setiap kali
posisi berubah, plus denyut tiap ~15 detik saat diam.

Kedua endpoint sengaja **tanpa token**: yang mengonsumsinya adalah aplikasi Anda di
perangkat lain, dan menaruh rahasia di dalam build debug hanya memindahkan masalah.
Yang terekspos pun hanya satu koordinat palsu yang Anda tentukan sendiri, dan
keduanya hanya bisa dibaca.

### Klien siap pakai

Ada di `examples/`, tinggal ditempel:

| Berkas | Untuk |
|---|---|
| `examples/swift/TitikLocationProvider.swift` | iOS native |
| `examples/kotlin/TitikLocationProvider.kt` | Android native |
| `examples/typescript/titikLocation.ts` | React Native, Expo, Capacitor, web |

Ketiganya memakai pola yang sama: satu protokol `LocationProviding`, satu
implementasi sistem, satu implementasi Titik, dan satu pabrik yang memilih di
antaranya. Kode aplikasi Anda hanya melihat protokolnya.

**Satu hal yang paling sering salah:** jangan menggerbangnya dengan `#if DEBUG`.
Build TestFlight memakai konfigurasi Release, jadi gerbang DEBUG akan membuang
kode ini persis di build yang Anda butuhkan. Buat konfigurasi tersendiri (mis.
"Beta") dengan flag kompilasinya sendiri. Detailnya ada di komentar tiap berkas
contoh, termasuk pengecualian App Transport Security dan cleartext yang benar.

### Alamat host dari tiap lingkungan

| Dari | Host |
|---|---|
| Simulator iOS | `127.0.0.1` |
| Emulator Android | `10.0.2.2` |
| Perangkat fisik di WiFi yang sama | IP LAN komputer Anda (dicetak oleh `--lan`) |

### Untuk simulasi lokasi bawaan Xcode

Ekspor rute dalam format Xcode — Titik menulis tag `<wpt>` dengan stempel waktu,
karena Xcode mengabaikan `<trk>` dan `<rte>`, dan menyimpulkan kecepatan dari
selisih waktu antar titik. Pilih **Xcode (wpt + waktu)** di tab Rute, lalu di
Xcode: Product → Scheme → Edit Scheme → Run → Options → Allow Location Simulation.

---

## Kalau macet

| Pesan | Artinya |
|---|---|
| `Tidak ada perangkat iOS terdeteksi` | Kabel longgar, perangkat terkunci, atau belum menekan Trust. Coba kabel lain — banyak kabel murah hanya bisa mengisi daya. |
| `Developer Mode belum aktif` | Ikuti langkah 1 di atas. |
| `iOS 17+ memerlukan tunnel` | Jalankan `pymobiledevice3 remote tunneld --userspace` di terminal terpisah. |
| `Developer Disk Image belum ter-mount` | Jalankan `pymobiledevice3 mounter auto-mount`. |
| Lokasi kembali sendiri setelah beberapa menit | Biasanya tunnel putus. Periksa terminal tunneld; coba port USB lain. |
| Peta tidak muncul | Titik mengambil pustaka peta Leaflet dari internet. Periksa koneksi. Kotak koordinat di tab Teleport tetap berfungsi tanpa peta. |

Jalankan dengan `TITIK_VERBOSE=1` untuk melihat log permintaan.

---

## Catatan keamanan

Server hanya mengikat ke `127.0.0.1` dan setiap panggilan API butuh token acak
yang dibuat baru tiap kali dijalankan serta disuntikkan langsung ke halaman.
Tanpa token itu, situs web lain yang Anda buka tidak bisa menembak API ini meski
sama-sama di localhost.

Jangan jalankan dengan `--host 0.0.0.0` kecuali Anda paham konsekuensinya:
siapa pun di jaringan yang sama akan bisa menggerakkan lokasi perangkat Anda.

Favorit disimpan di `~/.titik/favorites.json`. Tidak ada data yang dikirim ke
mana pun. Satu-satunya lalu lintas keluar adalah ke penyedia peta
(unpkg untuk Leaflet, CARTO/OpenStreetMap untuk petaknya).

---

## Yang perlu Anda tahu sebelum memakainya

**Game AR melarang ini.** Pokémon GO dan sejenisnya melarang pemalsuan lokasi di
syarat layanannya, dengan sistem tiga pelanggaran yang berujung penghapusan akun
permanen. Deteksinya ada di sisi perilaku akun, bukan di sisi alat — jadi tidak
ada alat mana pun, termasuk ini, yang membuatnya aman. Jangan pakai Titik untuk
itu kecuali Anda siap kehilangan akunnya.

**Memalsukan lokasi bukan tindakan netral.** Beberapa layanan memakai lokasi
untuk kepatuhan hukum, keselamatan, atau penetapan harga. Memalsukannya bisa
melanggar kontrak yang Anda sepakati, dan di beberapa konteks bisa jadi penipuan.
Gunakan untuk pengujian aplikasi Anda sendiri, untuk privasi, atau untuk hal lain
yang Anda yakini sah.

**Perangkat orang lain bukan urusan Anda.** Titik hanya bekerja pada perangkat
yang tercolok secara fisik dan sudah Anda percayai. Biarkan begitu.

---

## Struktur

```
titik/
  __main__.py     baris perintah, penyalaan
  backends.py     lima jalur (api / cli / adb / feed / mock)
  engine.py       mesin keadaan + thread simulasi
  geo.py          haversine, interpolasi, GPX, parsing koordinat
  server.py       server HTTP lokal + API JSON + feed
  web/            antarmuka (Leaflet, tanpa framework)
examples/
  swift/          penyedia lokasi iOS
  kotlin/         penyedia lokasi Android
  typescript/     penyedia lokasi React Native / web
windows/
  *.bat           peluncur sekali-klik + pembangun EXE
run_titik.py      titik masuk untuk PyInstaller
tests/
  test_titik.py   60 uji unit
  smoke_http.py   73 pemeriksaan ujung-ke-ujung
```

Jalankan ujinya:

```bash
python -m unittest discover -s tests -v
python tests/smoke_http.py
```

---

## Status

| Bagian | Status |
|---|---|
| Mesin, geodesi, GPX, server, feed | 60 uji unit + 73 pemeriksaan HTTP, semua lolos |
| `feed` dan `mock` | Teruji penuh |
| `api`, `cli` (iOS fisik) | Ditulis dari dokumentasi pymobiledevice3 11.x, **belum diuji ke perangkat** |
| `adb` (Android) | Logika perintah teruji, **belum diuji ke emulator** |
| Klien contoh | Ditulis dengan cermat, **belum dikompilasi** — tidak ada Xcode/Android SDK di sini |
| Skrip Windows | Ditulis dengan cermat, **belum dijalankan di Windows** — dibuat di Linux |

Anggap percobaan pertama Anda ke perangkat sungguhan sebagai bagian dari
pengujian, dan laporkan apa yang terjadi.

Dibangun di atas [pymobiledevice3](https://github.com/doronz88/pymobiledevice3)
oleh doronz88, yang mengerjakan bagian tersulitnya.
