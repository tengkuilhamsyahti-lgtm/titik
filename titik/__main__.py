"""Titik — titik masuk baris perintah.

    python -m titik                     # deteksi perangkat otomatis
    python -m titik --backend mock      # coba antarmuka tanpa iPhone
    python -m titik --port 9000         # ganti port
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

from . import __version__, __app_name__
from .backends import BackendError, resolve_backend
from .engine import Engine
from .server import build_server, lan_address

BANNER = """
  ╭───────────────────────────────────────╮
  │   t i t i k  ·  pengubah lokasi GPS   │
  │   v{version:<35}│
  ╰───────────────────────────────────────╯
""".strip("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="titik",
        description=f"{__app_name__} — ubah lokasi GPS perangkat Anda sendiri.",
    )
    parser.add_argument("--backend", default="auto",
                        choices=["auto", "api", "cli", "adb", "feed", "mock"],
                        help="auto (default), api/cli untuk iOS, adb untuk Android, "
                             "feed untuk menyuntik ke aplikasi sendiri, mock untuk uji tanpa perangkat")
    parser.add_argument("--udid", default=None, help="pilih perangkat tertentu (UDID atau serial adb)")
    parser.add_argument("--host", default="127.0.0.1", help="alamat ikat (default 127.0.0.1)")
    parser.add_argument("--lan", action="store_true",
                        help="ikat ke semua antarmuka agar perangkat lain di jaringan "
                             "bisa menjangkau feed; menimpa --host")
    parser.add_argument("--port", type=int, default=8787, help="port (default 8787)")
    parser.add_argument("--no-browser", action="store_true", help="jangan buka browser otomatis")
    parser.add_argument("--version", action="version", version=f"{__app_name__} {__version__}")
    args = parser.parse_args(argv)

    print(BANNER.format(version=__version__))
    print()

    if args.lan:
        args.host = "0.0.0.0"

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"  ! Mengikat ke {args.host} membuka Titik ke jaringan lain.")
        print("    Siapa pun yang bisa menjangkau alamat ini bisa menggerakkan")
        print("    lokasi perangkat Anda. Pakai hanya di jaringan tepercaya.\n")

    print(f"  Backend     : {args.backend}")
    print("  Menyambung  : ...", end="\r", flush=True)

    try:
        backend, device = resolve_backend(args.backend, args.udid)
    except BackendError as exc:
        print("  Menyambung  : gagal      \n")
        print(f"{exc}\n")
        return 2

    label = device.name or device.product or device.udid[:12] or "perangkat"
    if device.ios_version:
        osname = "Android" if device.backend == "adb" else "iOS"
        label += f" ({osname} {device.ios_version})"
    print(f"  Menyambung  : {label} lewat {device.backend}        ")
    for note in device.notes:
        print(f"  Catatan     : {note}")

    engine = Engine(backend, device)

    try:
        httpd = build_server(engine, args.host, args.port)
    except OSError as exc:
        engine.shutdown()
        print(f"\n  Tidak bisa membuka port {args.port}: {exc}")
        print("  Coba port lain dengan --port 9000")
        return 3

    shown_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    url = f"http://{shown_host}:{args.port}/"
    print(f"\n  Antarmuka   : {url}")

    if args.backend == "feed" or args.lan:
        lan = lan_address() if args.host == "0.0.0.0" else None
        feed_host = lan or shown_host
        print(f"  Feed JSON   : http://{feed_host}:{args.port}/feed/location")
        print(f"  Feed aliran : http://{feed_host}:{args.port}/feed/stream")
        if args.backend == "feed" and not args.lan:
            print("  Petunjuk    : tambahkan --lan agar ponsel di jaringan yang")
            print("                sama bisa menjangkau feed ini.")

    print("  Tekan Ctrl+C untuk berhenti dan mengembalikan GPS asli.\n")

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Menutup, mengembalikan lokasi asli ...")
    finally:
        httpd.shutdown()
        httpd.server_close()
        engine.shutdown()
        print("  Selesai.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
