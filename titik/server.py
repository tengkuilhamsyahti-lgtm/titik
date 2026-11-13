"""Server lokal Titik: API JSON + penyajian antarmuka web.

Memakai ``http.server`` dari pustaka standar — tanpa Flask, tanpa
FastAPI. Satu-satunya dependensi eksternal proyek ini adalah
pymobiledevice3 itu sendiri, dan itu pun hanya dibutuhkan saat Anda
benar-benar menyentuh perangkat.

Server hanya mengikat ke 127.0.0.1. Ini bukan layanan jaringan.
"""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import geo
from .backends import BackendError
from .engine import Engine

def _web_dir() -> Path:
    """Lokasi berkas antarmuka.

    Di bawah PyInstaller, berkas data diekstrak ke folder sementara yang
    ditunjuk sys._MEIPASS, dan __file__ tidak lagi menunjuk ke disk nyata.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "titik" / "web"  # type: ignore[attr-defined]
    return Path(__file__).parent / "web"


WEB_DIR = _web_dir()
STORE_DIR = Path(os.environ.get("TITIK_HOME", Path.home() / ".titik"))
STORE_FILE = STORE_DIR / "favorites.json"

MAX_BODY = 4 * 1024 * 1024  # 4 MiB, cukup untuk GPX besar


# --------------------------------------------------------------------------
# Penyimpanan favorit
# --------------------------------------------------------------------------

class Store:
    """Favorit dan rute tersimpan dalam satu berkas JSON."""

    def __init__(self, path: Path = STORE_FILE) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, list] = {"places": [], "routes": []}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = {
                    "places": list(raw.get("places") or []),
                    "routes": list(raw.get("routes") or []),
                }
        except (OSError, json.JSONDecodeError):
            pass  # berkas belum ada atau rusak — mulai dari kosong

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass  # tidak fatal; favorit sekadar kenyamanan

    def all(self) -> dict[str, list]:
        with self._lock:
            return json.loads(json.dumps(self._data))

    def add_place(self, name: str, lat: float, lon: float) -> dict:
        item = {
            "id": secrets.token_hex(6),
            "name": (name or "Tanpa nama").strip()[:80],
            "lat": round(float(lat), 6),
            "lon": round(float(lon), 6),
            "at": time.time(),
        }
        with self._lock:
            self._data["places"].append(item)
            del self._data["places"][:-200]
            self._save()
        return item

    def add_route(self, name: str, points: list[dict]) -> dict:
        item = {
            "id": secrets.token_hex(6),
            "name": (name or "Rute tanpa nama").strip()[:80],
            "points": [{"lat": round(p["lat"], 6), "lon": round(p["lon"], 6)} for p in points],
            "at": time.time(),
        }
        with self._lock:
            self._data["routes"].append(item)
            del self._data["routes"][:-100]
            self._save()
        return item

    def remove(self, kind: str, item_id: str) -> bool:
        if kind not in ("places", "routes"):
            return False
        with self._lock:
            before = len(self._data[kind])
            self._data[kind] = [x for x in self._data[kind] if x.get("id") != item_id]
            changed = len(self._data[kind]) != before
            if changed:
                self._save()
        return changed


# --------------------------------------------------------------------------
# Handler
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "Titik"
    sys_version = ""

    engine: Engine
    store: Store
    token: str

    # -- utilitas -------------------------------------------------------

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        if os.environ.get("TITIK_VERBOSE"):
            super().log_message(fmt, *args)

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"ok": False, "error": message}, status)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("Content-Length tidak sah.")
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("Isi permintaan terlalu besar.")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"JSON tidak sah: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Isi permintaan harus berupa objek JSON.")
        return data

    def _authorized(self) -> bool:
        """Lindungi dari situs web mana pun yang iseng menembak localhost.

        Browser bisa mengirim permintaan lintas-asal ke 127.0.0.1, jadi
        API tetap butuh token meski hanya mendengar di localhost. Token
        disuntikkan ke index.html saat halaman disajikan, dan tidak
        pernah diekspos lewat endpoint tersendiri.
        """
        return secrets.compare_digest(self.headers.get("X-Titik-Token", ""), self.token)

    # -- GET ------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path

        if path.startswith("/feed"):
            return self._feed(path)

        if path.startswith("/api/"):
            if not self._authorized():
                return self._error("Token tidak sah.", 403)
            return self._api_get(path)

        return self._serve_static(path)

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Preflight untuk klien feed berbasis browser."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    # -- feed -----------------------------------------------------------

    def _feed(self, path: str) -> None:
        """Siaran posisi untuk aplikasi yang sedang diuji.

        Sengaja tanpa token: yang mengonsumsinya adalah aplikasi Anda di
        perangkat lain, dan menaruh rahasia di dalam build debug hanya
        memindahkan masalah. Yang terekspos pun cuma satu koordinat palsu
        yang Anda tentukan sendiri, dan endpoint ini hanya bisa dibaca.
        """
        if path == "/feed/location":
            payload = json.dumps(self.engine.feed(), ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload)
            return

        if path == "/feed/stream":
            return self._feed_stream()

        return self._error("Endpoint feed tidak dikenal.", 404)

    def _feed_stream(self) -> None:
        """Server-Sent Events: satu baris JSON tiap kali posisi berubah."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        last_sent = None
        idle_ticks = 0
        try:
            while not self.server.titik_stopping:  # type: ignore[attr-defined]
                payload = self.engine.feed()
                key = (payload.get("lat"), payload.get("lon"),
                       payload.get("active"), payload.get("course"))
                if key != last_sent or idle_ticks >= 30:
                    # Kirim ulang tiap ~15 detik meski diam, supaya proxy
                    # dan klien tahu koneksinya masih hidup.
                    self.wfile.write(
                        b"data: " + json.dumps(payload).encode() + b"\n\n")
                    self.wfile.flush()
                    last_sent = key
                    idle_ticks = 0
                else:
                    idle_ticks += 1
                time.sleep(0.5)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # klien menutup koneksi; itu normal

    def _api_get(self, path: str) -> None:
        if path == "/api/status":
            return self._json({"ok": True, **self.engine.snapshot()})
        if path == "/api/favorites":
            return self._json({"ok": True, **self.store.all()})
        return self._error("Endpoint tidak dikenal.", 404)

    def _serve_static(self, path: str) -> None:
        if path in ("/", ""):
            path = "/index.html"

        rel = path.lstrip("/")
        target = (WEB_DIR / rel).resolve()
        try:
            target.relative_to(WEB_DIR.resolve())
        except ValueError:
            return self._error("Dilarang.", 403)
        if not target.is_file():
            return self._error("Tidak ditemukan.", 404)

        data = target.read_bytes()
        if target.name == "index.html":
            data = data.replace(b"__TITIK_TOKEN__", self.token.encode())

        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"

        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # -- POST / DELETE ---------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            return self._error("Tidak ditemukan.", 404)
        if not secrets.compare_digest(self.headers.get("X-Titik-Token", ""), self.token):
            return self._error("Token tidak sah.", 403)

        try:
            body = self._body()
        except ValueError as exc:
            return self._error(str(exc))

        try:
            return self._api_post(path, body)
        except (ValueError, KeyError, TypeError) as exc:
            return self._error(str(exc))
        except BackendError as exc:
            return self._error(str(exc), 502)

    def _api_post(self, path: str, body: dict) -> None:
        eng = self.engine

        if path == "/api/teleport":
            lat, lon = _coords(body)
            eng.teleport(lat, lon, body.get("label", ""))
            return self._ok()

        if path == "/api/route/start":
            points = _points(body.get("points"))
            eng.start_route(
                points,
                speed_kmh=float(body.get("speed_kmh", 5.0)),
                loop_mode=str(body.get("loop_mode", "once")),
            )
            return self._ok()

        if path == "/api/route/pause":
            eng.pause()
            return self._ok()

        if path == "/api/route/resume":
            eng.resume()
            return self._ok()

        if path == "/api/speed":
            eng.set_speed(float(body.get("speed_kmh", 5.0)))
            return self._ok()

        if path == "/api/joystick":
            eng.joystick(
                heading=float(body.get("heading", 0.0)),
                speed_kmh=float(body.get("speed_kmh", 5.0)),
                active=bool(body.get("active", False)),
            )
            return self._ok()

        if path == "/api/settings":
            eng.settings(
                push_interval=_opt_float(body.get("push_interval")),
                jitter_m=_opt_float(body.get("jitter_m")),
            )
            return self._ok()

        if path == "/api/stop":
            eng.stop()
            return self._ok()

        if path == "/api/gpx/import":
            text = body.get("gpx")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Isi GPX kosong.")
            pts = geo.parse_gpx(text)
            return self._json({
                "ok": True,
                "points": [{"lat": a, "lon": b} for a, b in pts],
                "length_m": round(geo.path_length(pts), 1),
            })

        if path == "/api/gpx/export":
            pts = _points(body.get("points"))
            flavor = str(body.get("flavor") or "track")
            if flavor not in ("track", "xcode"):
                raise ValueError("flavor harus 'track' atau 'xcode'.")
            return self._json({
                "ok": True,
                "gpx": geo.build_gpx(
                    pts,
                    body.get("name") or "Rute Titik",
                    flavor=flavor,
                    speed_kmh=float(body.get("speed_kmh", 5.0)),
                ),
            })

        if path == "/api/parse":
            found = geo.parse_coords(str(body.get("text", "")))
            if not found:
                raise ValueError("Tidak menemukan koordinat pada teks itu.")
            return self._json({"ok": True, "lat": found[0], "lon": found[1]})

        if path == "/api/favorites/place":
            lat, lon = _coords(body)
            return self._json({"ok": True, "item": self.store.add_place(
                str(body.get("name", "")), lat, lon)})

        if path == "/api/favorites/route":
            pts = _points(body.get("points"))
            return self._json({"ok": True, "item": self.store.add_route(
                str(body.get("name", "")),
                [{"lat": a, "lon": b} for a, b in pts])})

        if path == "/api/favorites/delete":
            kind = str(body.get("kind", ""))
            item_id = str(body.get("id", ""))
            if not self.store.remove(kind, item_id):
                raise ValueError("Item tidak ditemukan.")
            return self._ok()

        return self._error("Endpoint tidak dikenal.", 404)

    def _ok(self) -> None:
        self._json({"ok": True, **self.engine.snapshot()})


# --------------------------------------------------------------------------
# Validasi masukan
# --------------------------------------------------------------------------

def _coords(body: dict) -> tuple[float, float]:
    try:
        lat = float(body["lat"])
        lon = float(body["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Butuh 'lat' dan 'lon' berupa angka.") from exc
    if not geo.valid(lat, lon):
        raise ValueError("Koordinat di luar jangkauan yang sah.")
    return lat, lon


def _points(raw: Any) -> list[geo.Point]:
    if not isinstance(raw, list):
        raise ValueError("'points' harus berupa larik.")
    if len(raw) > 10_000:
        raise ValueError("Rute terlalu panjang (maksimum 10.000 titik).")
    out: list[geo.Point] = []
    for i, p in enumerate(raw):
        if isinstance(p, dict):
            lat, lon = p.get("lat"), p.get("lon")
        elif isinstance(p, (list, tuple)) and len(p) >= 2:
            lat, lon = p[0], p[1]
        else:
            raise ValueError(f"Titik ke-{i} tidak berbentuk benar.")
        try:
            lat_f, lon_f = float(lat), float(lon)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Titik ke-{i} bukan angka.") from exc
        if not geo.valid(lat_f, lon_f):
            raise ValueError(f"Titik ke-{i} di luar jangkauan yang sah.")
        out.append((lat_f, lon_f))
    return out


def _opt_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    return float(v)


# --------------------------------------------------------------------------
# Pembuatan server
# --------------------------------------------------------------------------

def build_server(engine: Engine, host: str = "127.0.0.1", port: int = 8787) -> ThreadingHTTPServer:
    token = secrets.token_urlsafe(24)
    store = Store()

    handler = type("BoundHandler", (Handler,), {
        "engine": engine,
        "store": store,
        "token": token,
    })

    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    httpd.titik_token = token          # type: ignore[attr-defined]
    httpd.titik_stopping = False       # type: ignore[attr-defined]

    # Aliran SSE menahan threadnya, jadi shutdown() harus memberi tahu
    # mereka untuk berhenti; tanpa ini Ctrl+C akan menggantung.
    original_shutdown = httpd.shutdown

    def shutdown() -> None:
        httpd.titik_stopping = True    # type: ignore[attr-defined]
        original_shutdown()

    httpd.shutdown = shutdown          # type: ignore[method-assign]
    return httpd


def lan_address() -> str | None:
    """Alamat IP komputer ini di jaringan lokal, untuk dicolok ke ponsel."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Tidak ada paket yang benar-benar dikirim; ini hanya cara menanyakan
        # ke tabel routing antarmuka mana yang dipakai ke luar.
        s.connect(("192.0.2.1", 9))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
