"""Backend perangkat untuk Titik.

Tiga implementasi di balik satu antarmuka:

* ``MockBackend``  — tidak menyentuh perangkat apa pun. Untuk menguji
  seluruh aplikasi tanpa iPhone tercolok.
* ``ApiBackend``   — memakai modul Python pymobiledevice3 dengan sesi
  yang dipertahankan. Cepat, cocok untuk simulasi rute.
* ``CliBackend``   — memanggil executable ``pymobiledevice3``. Lambat
  (satu proses per perintah) tapi kontraknya jauh lebih stabil.

``resolve_backend("auto")`` mencoba API lebih dulu, lalu CLI, lalu
menyerah dengan pesan yang menjelaskan apa yang kurang.

CATATAN KEJUJURAN: jalur Mock sudah diuji menyeluruh. Jalur API dan CLI
ditulis mengikuti dokumentasi pymobiledevice3 11.x tetapi belum diuji
terhadap perangkat iOS fisik di sini. Perlakukan percobaan pertama Anda
sebagai bagian dari pengujian.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any


class BackendError(RuntimeError):
    """Kegagalan yang bisa dijelaskan ke pengguna."""


@dataclass
class DeviceInfo:
    udid: str = ""
    name: str = ""
    product: str = ""
    ios_version: str = ""
    connection: str = ""
    backend: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def ios_major(self) -> int:
        try:
            return int(str(self.ios_version).split(".", 1)[0])
        except (ValueError, IndexError):
            return 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ios_major"] = self.ios_major
        return d


# --------------------------------------------------------------------------
# Antarmuka
# --------------------------------------------------------------------------

class LocationBackend:
    """Kontrak minimal yang harus dipenuhi setiap backend."""

    name = "base"

    def connect(self) -> DeviceInfo:
        raise NotImplementedError

    def set_location(self, lat: float, lon: float) -> None:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


# --------------------------------------------------------------------------
# Mock
# --------------------------------------------------------------------------

class MockBackend(LocationBackend):
    """Perangkat palsu. Mencatat apa yang dikirim, tidak melakukan apa pun."""

    name = "mock"

    def __init__(self, latency_ms: float = 25.0) -> None:
        self.latency = latency_ms / 1000.0
        self.last: tuple[float, float] | None = None
        self.calls = 0
        self.cleared = 0
        self._lock = threading.Lock()

    def connect(self) -> DeviceInfo:
        return DeviceInfo(
            udid="00000000-MOCKDEVICE0001",
            name="iPhone Simulasi",
            product="iPhone17,2",
            ios_version="26.1",
            connection="mock",
            backend=self.name,
            notes=["Backend mock — tidak ada perangkat nyata yang disentuh."],
        )

    def set_location(self, lat: float, lon: float) -> None:
        if self.latency:
            time.sleep(self.latency)
        with self._lock:
            self.last = (lat, lon)
            self.calls += 1

    def clear(self) -> None:
        with self._lock:
            self.last = None
            self.cleared += 1


# --------------------------------------------------------------------------
# Feed
# --------------------------------------------------------------------------

class FeedBackend(LocationBackend):
    """Tidak mendorong ke perangkat mana pun — menyiarkan untuk diambil.

    Dipakai ketika aplikasi yang diuji adalah milik Anda sendiri. Alih-alih
    memalsukan lokasi di level sistem (yang di iOS mensyaratkan Developer
    Mode), aplikasi Anda menyambung ke endpoint feed Titik dan memakainya
    sebagai sumber lokasi pada build debug.

    Keuntungannya bukan cuma soal Developer Mode: pengujian jadi
    deterministik, jalan di CI tanpa perangkat, dan bisa mensimulasikan
    keadaan yang mustahil dibuat dari luar — akurasi memburuk, sinyal
    hilang, lompatan posisi.
    """

    name = "feed"

    def __init__(self) -> None:
        self.last: tuple[float, float] | None = None
        self.calls = 0
        self.cleared = 0
        self._lock = threading.Lock()

    def connect(self) -> DeviceInfo:
        return DeviceInfo(
            udid="feed",
            name="Aplikasi yang diuji",
            product="HTTP feed",
            connection="feed",
            backend=self.name,
            notes=[
                "Mode feed: tidak ada perangkat yang disentuh. Titik "
                "menyiarkan posisi di /feed/location dan /feed/stream; "
                "aplikasi Anda yang menariknya.",
            ],
        )

    def set_location(self, lat: float, lon: float) -> None:
        with self._lock:
            self.last = (lat, lon)
            self.calls += 1

    def clear(self) -> None:
        with self._lock:
            self.last = None
            self.cleared += 1


# --------------------------------------------------------------------------
# Android (adb)
# --------------------------------------------------------------------------

class AdbBackend(LocationBackend):
    """Android lewat adb — berjalan di Windows, Linux, maupun macOS.

    Untuk emulator dipakai ``adb emu geo fix``, yang menyuntik lokasi
    langsung ke radio GPS virtual. Untuk perangkat fisik, Android butuh
    aplikasi penyedia mock location yang dipilih di Developer Options;
    backend ini mendeteksi dan mengatakannya daripada gagal diam-diam.

    Catatan: ``geo fix`` menerima BUJUR lebih dulu, baru LINTANG. Urutan
    terbalik dari kebiasaan, dan itu sumber bug yang sering terjadi.
    """

    name = "adb"
    TIMEOUT = 25

    def __init__(self, serial: str | None = None) -> None:
        self.serial = serial
        self._exe: str | None = None
        self._is_emulator = False

    def _adb(self, args: list[str], timeout: int | None = None) -> str:
        if self._exe is None:
            exe = shutil.which("adb")
            if not exe:
                raise BackendError(
                    "Perintah 'adb' tidak ditemukan di PATH. Pasang Android "
                    "Platform Tools, lalu pastikan foldernya masuk PATH."
                )
            self._exe = exe
        cmd = [self._exe]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += args
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout or self.TIMEOUT
            )
        except subprocess.TimeoutExpired as exc:
            raise BackendError(f"adb kehabisan waktu: {' '.join(args)}") from exc
        if proc.returncode != 0:
            raise BackendError(
                f"adb {' '.join(args[:2])} gagal.\n\n"
                f"{(proc.stderr or proc.stdout or '').strip()[:400]}"
            )
        return proc.stdout

    def connect(self) -> DeviceInfo:
        raw = self._adb(["devices", "-l"], timeout=20)
        devices = []
        for line in raw.splitlines()[1:]:
            line = line.strip()
            if not line or "\tdevice" not in line and " device " not in line:
                continue
            devices.append(line.split()[0])
        if not devices:
            raise BackendError(
                "Tidak ada perangkat Android terdeteksi.\n"
                "Untuk emulator: jalankan dulu dari Android Studio.\n"
                "Untuk perangkat fisik: nyalakan USB debugging di Developer "
                "Options, colokkan kabel, lalu setujui dialog di layar."
            )
        if self.serial and self.serial not in devices:
            raise BackendError(f"Perangkat {self.serial} tidak ada di daftar adb.")
        self.serial = self.serial or devices[0]
        self._is_emulator = self.serial.startswith("emulator-")

        def prop(key: str) -> str:
            try:
                return self._adb(["shell", "getprop", key], timeout=15).strip()
            except BackendError:
                return ""

        info = DeviceInfo(
            udid=self.serial,
            name=prop("ro.product.model") or self.serial,
            product=prop("ro.product.device"),
            ios_version=prop("ro.build.version.release"),
            connection="emulator" if self._is_emulator else "USB",
            backend=self.name,
        )
        if not self._is_emulator:
            info.notes.append(
                "Perangkat Android fisik: Android hanya menerima lokasi palsu "
                "dari aplikasi yang dipilih sebagai 'mock location app' di "
                "Developer Options. Tanpa itu, perintah di bawah akan "
                "dijalankan tetapi lokasinya tidak berubah. Untuk pengujian "
                "aplikasi sendiri, mode --backend feed lebih dapat diandalkan."
            )
        return info

    def set_location(self, lat: float, lon: float) -> None:
        if self._is_emulator:
            # Perhatikan urutannya: bujur dulu, baru lintang.
            self._adb(["emu", "geo", "fix", f"{lon:.7f}", f"{lat:.7f}"], timeout=15)
            return
        raise BackendError(
            "Perangkat Android fisik tidak bisa disuntik lokasi langsung lewat "
            "adb. Android mensyaratkan aplikasi penyedia mock location yang "
            "dipilih di Developer Options. Gunakan emulator, atau jalankan "
            "Titik dengan --backend feed dan konsumsi feed-nya dari aplikasi "
            "Anda."
        )

    def clear(self) -> None:
        # Tidak ada perintah 'unfix'. Lokasi nyata kembali sendiri begitu
        # emulator menerima pembaruan dari sumber lain atau di-restart.
        return


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

class CliBackend(LocationBackend):
    """Memanggil executable pymobiledevice3 sebagai subprocess.

    Satu proses per perintah, jadi hitung ~1-3 detik per pembaruan. Cukup
    untuk teleport, terlalu lambat untuk rute mulus — karena itu
    ``resolve_backend`` lebih memilih API bila tersedia.
    """

    name = "cli"
    TIMEOUT = 45

    def __init__(self, udid: str | None = None) -> None:
        self.udid = udid
        self._base: list[str] | None = None
        self._info: DeviceInfo | None = None

    # -- penemuan executable --------------------------------------------

    def _executable(self) -> list[str]:
        if self._base is not None:
            return self._base
        exe = shutil.which("pymobiledevice3")
        if exe:
            self._base = [exe]
        else:
            # Fallback: modul di interpreter yang sedang berjalan.
            probe = subprocess.run(
                [sys.executable, "-m", "pymobiledevice3", "version"],
                capture_output=True, text=True, timeout=self.TIMEOUT,
            )
            if probe.returncode != 0:
                raise BackendError(
                    "Executable 'pymobiledevice3' tidak ditemukan di PATH dan "
                    "tidak bisa dipanggil sebagai modul. Jalankan: "
                    "pip install -U pymobiledevice3"
                )
            self._base = [sys.executable, "-m", "pymobiledevice3"]
        return self._base

    def _run(self, args: list[str], timeout: int | None = None) -> str:
        cmd = self._executable() + args
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout or self.TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            raise BackendError(f"Perintah kehabisan waktu: {' '.join(args)}") from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise BackendError(_humanize(detail, args))
        return proc.stdout

    # -- antarmuka ------------------------------------------------------

    def connect(self) -> DeviceInfo:
        raw = self._run(["usbmux", "list"], timeout=30)
        devices = _parse_json_loose(raw)
        if not devices:
            raise BackendError(
                "Tidak ada perangkat iOS terdeteksi. Pastikan kabel USB "
                "tersambung, perangkat tidak terkunci, dan Anda sudah "
                "menekan 'Trust' di layar iPhone."
            )
        chosen = devices[0]
        if self.udid:
            match = [d for d in devices if d.get("Identifier") == self.udid
                     or d.get("UniqueDeviceID") == self.udid]
            if not match:
                raise BackendError(f"Perangkat dengan UDID {self.udid} tidak ditemukan.")
            chosen = match[0]

        info = DeviceInfo(
            udid=str(chosen.get("Identifier") or chosen.get("UniqueDeviceID") or ""),
            name=str(chosen.get("DeviceName") or ""),
            product=str(chosen.get("ProductType") or ""),
            ios_version=str(chosen.get("ProductVersion") or ""),
            connection=str(chosen.get("ConnectionType") or "USB"),
            backend=self.name,
        )
        self.udid = info.udid or self.udid
        if info.ios_major >= 17:
            info.notes.append(
                "iOS 17+ butuh tunnel. pymobiledevice3 11.x membangunnya "
                "otomatis lewat jalur userspace (tanpa sudo). Bila gagal, "
                "jalankan 'sudo pymobiledevice3 lockdown start-tunnel' "
                "di terminal terpisah."
            )
        self._info = info
        return info

    def _loc_args(self) -> list[str]:
        major = self._info.ios_major if self._info else 17
        if major and major < 17:
            return ["developer", "simulate-location"]
        return ["developer", "dvt", "simulate-location"]

    def _target(self) -> list[str]:
        return ["--udid", self.udid] if self.udid else []

    def set_location(self, lat: float, lon: float) -> None:
        self._run(self._loc_args() + ["set"] + self._target() + ["--", str(lat), str(lon)])

    def clear(self) -> None:
        self._run(self._loc_args() + ["clear"] + self._target())


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

class ApiBackend(LocationBackend):
    """Sesi pymobiledevice3 yang dipertahankan hidup.

    Membuka DVT sekali lalu memakai ulang kanalnya, jadi satu pembaruan
    lokasi hanya butuh milidetik — inilah yang membuat simulasi rute
    terasa mulus.

    Impor dilakukan secara toleran: nama modul internal pymobiledevice3
    sesekali berpindah antar rilis mayor, jadi kita coba beberapa jalur
    yang diketahui sebelum menyerah.
    """

    name = "api"

    def __init__(self, udid: str | None = None) -> None:
        self.udid = udid
        self._lock = threading.Lock()
        self._service = None      # DvtSecureSocketProxyService
        self._sim = None          # LocationSimulation atau DtSimulateLocation
        self._rsd = None
        self._lockdown = None
        self._info: DeviceInfo | None = None

    # -- impor toleran ---------------------------------------------------

    @staticmethod
    def _imp(paths: list[tuple[str, str]], what: str):
        last = None
        for module, attr in paths:
            try:
                mod = __import__(module, fromlist=[attr])
                return getattr(mod, attr)
            except (ImportError, AttributeError) as exc:
                last = exc
        raise BackendError(
            f"Tidak menemukan {what} di pymobiledevice3 yang terpasang "
            f"({last}). Coba 'pip install -U pymobiledevice3', atau "
            f"jalankan Titik dengan --backend cli."
        )

    def _probe(self) -> None:
        try:
            __import__("pymobiledevice3")
        except ImportError as exc:
            raise BackendError(
                "Paket pymobiledevice3 belum terpasang. Jalankan: "
                "pip install -U pymobiledevice3"
            ) from exc

    # -- antarmuka -------------------------------------------------------

    def connect(self) -> DeviceInfo:
        self._probe()
        create_using_usbmux = self._imp(
            [("pymobiledevice3.lockdown", "create_using_usbmux")],
            "create_using_usbmux",
        )
        try:
            lockdown = create_using_usbmux(serial=self.udid) if self.udid else create_using_usbmux()
        except Exception as exc:  # noqa: BLE001 - pustaka melempar banyak tipe
            raise BackendError(
                "Gagal menyambung lewat usbmux. Pastikan iPhone tercolok, "
                f"tidak terkunci, dan sudah di-'Trust'. Detail: {exc}"
            ) from exc

        values = dict(getattr(lockdown, "all_values", None) or getattr(lockdown, "short_info", {}) or {})
        info = DeviceInfo(
            udid=str(values.get("UniqueDeviceID") or self.udid or ""),
            name=str(values.get("DeviceName") or ""),
            product=str(values.get("ProductType") or ""),
            ios_version=str(values.get("ProductVersion") or ""),
            connection="USB",
            backend=self.name,
        )
        self._lockdown = lockdown
        self.udid = info.udid or self.udid
        self._info = info

        if info.ios_major >= 17:
            self._open_dvt_modern(info)
        else:
            self._open_legacy()
        return info

    def _open_dvt_modern(self, info: DeviceInfo) -> None:
        """iOS >= 17: butuh RemoteServiceDiscovery lewat tunnel."""
        rsd = None
        try:
            get_tunneld_devices = self._imp(
                [
                    ("pymobiledevice3.tunneld", "get_tunneld_devices"),
                    ("pymobiledevice3.tunneld.api", "get_tunneld_devices"),
                ],
                "get_tunneld_devices",
            )
            found = get_tunneld_devices() or []
            for cand in found:
                cand_udid = getattr(cand, "udid", None) or getattr(cand, "identifier", None)
                if not self.udid or not cand_udid or cand_udid == self.udid:
                    rsd = cand
                    break
        except BackendError:
            pass
        except Exception:  # noqa: BLE001
            rsd = None

        if rsd is None:
            raise BackendError(
                "iOS 17+ memerlukan tunnel tepercaya dan belum ada yang aktif.\n"
                "Buka terminal terpisah lalu jalankan salah satu:\n"
                "  pymobiledevice3 remote tunneld --userspace     (tanpa sudo)\n"
                "  sudo pymobiledevice3 remote tunneld            (klasik)\n"
                "Biarkan terminal itu terbuka, lalu tekan Sambungkan Ulang di Titik.\n"
                "Alternatif: jalankan Titik dengan --backend cli."
            )

        DvtService = self._imp(
            [
                ("pymobiledevice3.services.dvt.dvt_secure_socket_proxy",
                 "DvtSecureSocketProxyService"),
            ],
            "DvtSecureSocketProxyService",
        )
        LocationSimulation = self._imp(
            [
                ("pymobiledevice3.services.dvt.instruments.location_simulation",
                 "LocationSimulation"),
            ],
            "LocationSimulation",
        )
        service = DvtService(lockdown=rsd)
        service.__enter__()
        self._rsd = rsd
        self._service = service
        self._sim = LocationSimulation(service)
        info.notes.append("Tunnel RSD aktif, kanal DVT terbuka.")

    def _open_legacy(self) -> None:
        """iOS < 17: layanan simulate-location lama lewat lockdown."""
        DtSimulateLocation = self._imp(
            [
                ("pymobiledevice3.services.simulate_location", "DtSimulateLocation"),
                ("pymobiledevice3.services.dt_simulate_location", "DtSimulateLocation"),
            ],
            "DtSimulateLocation",
        )
        self._sim = DtSimulateLocation(lockdown=self._lockdown)

    def set_location(self, lat: float, lon: float) -> None:
        if self._sim is None:
            raise BackendError("Backend API belum tersambung.")
        with self._lock:
            try:
                self._sim.set(lat, lon)
            except Exception as exc:  # noqa: BLE001
                raise BackendError(f"Gagal mengirim lokasi: {exc}") from exc

    def clear(self) -> None:
        if self._sim is None:
            return
        with self._lock:
            try:
                self._sim.clear()
            except Exception as exc:  # noqa: BLE001
                raise BackendError(f"Gagal mengosongkan lokasi: {exc}") from exc

    def close(self) -> None:
        with self._lock:
            if self._service is not None:
                try:
                    self._service.__exit__(None, None, None)
                except Exception:  # noqa: BLE001
                    pass
            self._service = None
            self._sim = None
            self._rsd = None
            self._lockdown = None


# --------------------------------------------------------------------------
# Pemilihan
# --------------------------------------------------------------------------

def resolve_backend(choice: str = "auto", udid: str | None = None) -> tuple[LocationBackend, DeviceInfo]:
    """Kembalikan backend yang sudah tersambung beserta info perangkatnya."""
    choice = (choice or "auto").lower()

    if choice == "mock":
        b = MockBackend()
        return b, b.connect()
    if choice == "feed":
        b = FeedBackend()
        return b, b.connect()
    if choice == "adb":
        b = AdbBackend(udid)
        return b, b.connect()
    if choice == "api":
        b = ApiBackend(udid)
        return b, b.connect()
    if choice == "cli":
        b = CliBackend(udid)
        return b, b.connect()
    if choice != "auto":
        raise BackendError(f"Backend tidak dikenal: {choice}")

    problems: list[str] = []
    for cls in (ApiBackend, CliBackend):
        backend = cls(udid)
        try:
            info = backend.connect()
            if problems:
                info.notes.append("Backend API dilewati: " + problems[0])
            return backend, info
        except BackendError as exc:
            problems.append(str(exc))
            backend.close()
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{cls.__name__}: {exc}")
            backend.close()

    raise BackendError(
        "Tidak ada backend perangkat yang bisa dipakai.\n\n"
        + "\n\n".join(f"- {p}" for p in problems)
        + "\n\nUntuk mencoba antarmuka Titik tanpa perangkat, jalankan "
          "dengan --backend mock."
    )


# --------------------------------------------------------------------------
# Bantuan
# --------------------------------------------------------------------------

def _parse_json_loose(raw: str) -> list[dict]:
    """Ambil daftar JSON dari stdout yang mungkin bercampur log."""
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end <= start:
            return []
        try:
            data = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            return []
    if isinstance(data, dict):
        return [data]
    return [d for d in data if isinstance(d, dict)]


_HINTS = (
    ("developermode", "Developer Mode belum aktif di iPhone. Buka Settings > "
                      "Privacy & Security > Developer Mode, nyalakan, lalu restart perangkat."),
    ("developer mode", "Developer Mode belum aktif di iPhone. Buka Settings > "
                       "Privacy & Security > Developer Mode, nyalakan, lalu restart perangkat."),
    ("invalidservice", "Layanan developer tidak terjangkau — biasanya tunnel iOS 17+ "
                       "belum berjalan. Jalankan 'pymobiledevice3 remote tunneld --userspace'."),
    ("imagenotmounted", "Developer Disk Image belum ter-mount. Jalankan "
                        "'pymobiledevice3 mounter auto-mount'."),
    ("not mounted", "Developer Disk Image belum ter-mount. Jalankan "
                    "'pymobiledevice3 mounter auto-mount'."),
    ("passwordrequired", "iPhone sedang terkunci. Buka kuncinya lalu coba lagi."),
    ("pairingdialog", "Konfirmasi dialog 'Trust This Computer' di layar iPhone."),
    ("notrusted", "Komputer ini belum dipercaya perangkat. Cabut-colok kabel lalu "
                  "tekan 'Trust' di iPhone."),
    ("permission", "Akses ditolak. Pada Windows gunakan terminal Administrator; "
                   "pada macOS/Linux coba dengan sudo, atau pakai tunnel userspace."),
)


def _humanize(detail: str, args: list[str]) -> str:
    low = detail.lower().replace(" ", "")
    for needle, hint in _HINTS:
        if needle.replace(" ", "") in low:
            return f"{hint}\n\n(detail: {detail[:400]})"
    return f"Perintah '{' '.join(args[:3])}' gagal.\n\n{detail[:600]}"
