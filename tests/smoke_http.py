"""Uji asap HTTP: jalankan server sungguhan dengan backend mock dan
tembak setiap endpoint. Jalankan: python3 tests/smoke_http.py
"""

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from titik import geo
from titik.backends import resolve_backend
from titik.engine import Engine
from titik.server import build_server

PORT = 8899
BASE = f"http://127.0.0.1:{PORT}"

passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}  {detail}")


def call(path, body=None, token=None, expect=200):
    req = urllib.request.Request(BASE + path)
    if token is not None:
        req.add_header("X-Titik-Token", token)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
        req.method = "POST"
    try:
        with urllib.request.urlopen(req, data, timeout=10) as r:
            return r.status, json.loads(r.read().decode()) if "json" in r.headers.get("Content-Type", "") else r.read()
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def main():
    backend, device = resolve_backend("mock")
    engine = Engine(backend, device, seed=3)
    httpd = build_server(engine, "127.0.0.1", PORT)
    token = httpd.titik_token
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)

    try:
        print("\nHalaman statis")
        st, body = call("/")
        check("GET / mengembalikan 200", st == 200)
        check("token disuntikkan ke HTML", b"__TITIK_TOKEN__" not in body and token.encode() in body)
        st, _ = call("/style.css")
        check("GET /style.css", st == 200)
        st, _ = call("/app.js")
        check("GET /app.js", st == 200)
        st, _ = call("/favicon.svg")
        check("GET /favicon.svg", st == 200)
        st, _ = call("/logo.svg")
        check("GET /logo.svg", st == 200)

        print("\nKeamanan")
        st, _ = call("/api/status")
        check("API tanpa token ditolak 403", st == 403, f"dapat {st}")
        st, _ = call("/api/status", token="token-palsu")
        check("API dengan token salah ditolak", st == 403, f"dapat {st}")
        st, r = call("/../../etc/passwd")
        check("path traversal ditolak", st in (403, 404), f"dapat {st}")
        st, r = call("/api/entah-apa", token=token)
        check("endpoint tak dikenal -> 404", st == 404)

        print("\nTeleport")
        st, r = call("/api/teleport", {"lat": -6.2088, "lon": 106.8456, "label": "Monas"}, token)
        check("teleport berhasil", st == 200 and r["ok"], str(r)[:120])
        check("mode jadi fixed", r["mode"] == "fixed")
        check("posisi benar", abs(r["position"]["lat"] + 6.2088) < 1e-9)
        check("backend menerima titik", backend.last == (-6.2088, 106.8456), str(backend.last))
        check("riwayat terisi", r["history"] and r["history"][0]["label"] == "Monas")

        st, r = call("/api/teleport", {"lat": 95, "lon": 0}, token)
        check("lat di luar jangkauan ditolak", st == 400, str(r)[:100])
        st, r = call("/api/teleport", {"lat": "abc", "lon": 0}, token)
        check("lat bukan angka ditolak", st == 400)
        st, r = call("/api/teleport", {}, token)
        check("tanpa koordinat ditolak", st == 400)

        print("\nParsing koordinat")
        st, r = call("/api/parse", {"text": "https://maps.google.com/@-6.9,107.6,14z"}, token)
        check("URL Google Maps terbaca", st == 200 and abs(r["lat"] + 6.9) < 1e-6, str(r)[:100])
        st, r = call("/api/parse", {"text": "entah apa"}, token)
        check("teks tanpa koordinat ditolak", st == 400)

        print("\nRute")
        a = (-6.2088, 106.8456)
        pts = [{"lat": a[0], "lon": a[1]}]
        for brg, d in ((0, 400), (90, 400), (180, 400)):
            nxt = geo.destination(a, brg, d)
            pts.append({"lat": nxt[0], "lon": nxt[1]})
        st, r = call("/api/route/start", {"points": pts, "speed_kmh": 108, "loop_mode": "once"}, token)
        check("rute dimulai", st == 200 and r["mode"] == "route", str(r)[:120])
        # Kaki 1 lurus 400 m; kaki 2 dan 3 diagonal, masing-masing ~400*sqrt(2).
        expected = 400 + 2 * 400 * (2 ** 0.5)
        check("total jarak cocok dengan hitungan tangan",
              abs(r["route_total_m"] - expected) < 5,
              f"{r.get('route_total_m')} vs {expected:.1f}")

        time.sleep(1.2)
        st, r = call("/api/status", token=token)
        check("rute bergerak maju", r["route_done_m"] > 15, str(r.get("route_done_m")))
        moved = r["route_done_m"]
        check("backend menerima banyak pembaruan", backend.calls > 2, str(backend.calls))

        st, r = call("/api/route/pause", {}, token)
        check("jeda diterima", st == 200 and r["paused"])
        time.sleep(0.5)
        st, r = call("/api/status", token=token)
        check("progres beku saat jeda", abs(r["route_done_m"] - moved) < 20, f"{moved} -> {r['route_done_m']}")

        st, r = call("/api/route/resume", {}, token)
        check("lanjut diterima", st == 200 and not r["paused"])
        st, r = call("/api/speed", {"speed_kmh": 20}, token)
        check("ganti kecepatan", st == 200 and r["speed_kmh"] == 20.0)

        st, r = call("/api/route/start", {"points": [{"lat": 0, "lon": 0}], "speed_kmh": 5}, token)
        check("rute satu titik ditolak", st == 400)
        st, r = call("/api/route/start", {"points": "bukan larik"}, token)
        check("points bukan larik ditolak", st == 400)
        st, r = call("/api/route/start", {"points": [{"lat": 0, "lon": 0}, {"lat": 999, "lon": 0}]}, token)
        check("titik tak sah di rute ditolak", st == 400)

        print("\nJoystick")
        call("/api/teleport", {"lat": 0, "lon": 0}, token)
        st, r = call("/api/joystick", {"heading": 90, "speed_kmh": 108, "active": True}, token)
        check("joystick aktif", st == 200 and r["mode"] == "joystick", str(r)[:120])
        time.sleep(0.8)
        st, r = call("/api/status", token=token)
        check("bergerak ke timur", r["position"]["lon"] > 0.0001, str(r["position"]))
        check("tidak menyimpang ke utara/selatan", abs(r["position"]["lat"]) < 0.0001)
        st, r = call("/api/joystick", {"heading": 0, "speed_kmh": 0, "active": False}, token)
        check("joystick dilepas", st == 200 and r["mode"] == "fixed")

        print("\nPengaturan")
        st, r = call("/api/settings", {"push_interval": 2.5, "jitter_m": 8}, token)
        check("pengaturan tersimpan", st == 200 and r["push_interval"] == 2.5 and r["jitter_m"] == 8.0)
        st, r = call("/api/settings", {"push_interval": 9999}, token)
        check("interval dibatasi", r["push_interval"] <= 10.0)
        call("/api/settings", {"jitter_m": 0}, token)

        print("\nGPX")
        gpx = geo.build_gpx([(-6.2, 106.8), (-6.3, 106.9), (-6.4, 107.0)], "Uji")
        st, r = call("/api/gpx/import", {"gpx": gpx}, token)
        check("impor GPX", st == 200 and len(r["points"]) == 3, str(r)[:120])
        check("panjang terhitung", r["length_m"] > 1000)
        st, r = call("/api/gpx/import", {"gpx": "<gpx></gpx>"}, token)
        check("GPX kosong ditolak", st == 400)
        st, r = call("/api/gpx/import", {"gpx": ""}, token)
        check("GPX string kosong ditolak", st == 400)
        st, r = call("/api/gpx/export", {"points": [{"lat": 1, "lon": 2}, {"lat": 3, "lon": 4}]}, token)
        check("ekspor GPX", st == 200 and "<trkpt" in r["gpx"])
        check("GPX hasil ekspor bisa dibaca ulang", len(geo.parse_gpx(r["gpx"])) == 2)

        print("\nFavorit")
        st, r = call("/api/favorites/place", {"name": "Monas", "lat": -6.1754, "lon": 106.8272}, token)
        check("simpan tempat", st == 200 and r["item"]["name"] == "Monas", str(r)[:120])
        place_id = r["item"]["id"]
        st, r = call("/api/favorites/route", {"name": "Keliling", "points": [{"lat": 1, "lon": 2}, {"lat": 3, "lon": 4}]}, token)
        check("simpan rute", st == 200 and len(r["item"]["points"]) == 2)
        route_id = r["item"]["id"]
        st, r = call("/api/favorites", token=token)
        check("daftar favorit berisi keduanya", any(p["id"] == place_id for p in r["places"])
              and any(x["id"] == route_id for x in r["routes"]))
        st, r = call("/api/favorites/delete", {"kind": "places", "id": place_id}, token)
        check("hapus tempat", st == 200)
        st, r = call("/api/favorites/delete", {"kind": "routes", "id": route_id}, token)
        check("hapus rute", st == 200)
        st, r = call("/api/favorites/delete", {"kind": "places", "id": "tidak-ada"}, token)
        check("hapus item tak ada ditolak", st == 400)
        st, r = call("/api/favorites", token=token)
        check("favorit kembali bersih", not any(p["id"] == place_id for p in r["places"]))

        print("\nHenti")
        st, r = call("/api/stop", {}, token)
        check("stop berhasil", st == 200 and r["mode"] == "idle", str(r)[:120])
        check("backend dikosongkan", backend.last is None and backend.cleared > 0)

        print("\nFeed untuk aplikasi yang diuji")
        call("/api/teleport", {"lat": -6.2088, "lon": 106.8456}, token)

        # Sengaja TANPA token: ini yang dikonsumsi aplikasi di perangkat lain.
        req = urllib.request.Request(BASE + "/feed/location")
        with urllib.request.urlopen(req, timeout=5) as r:
            cors = r.headers.get("Access-Control-Allow-Origin")
            feed = json.loads(r.read().decode())
        check("feed bisa dibaca tanpa token", feed["active"] is True, str(feed)[:120])
        check("koordinat benar", abs(feed["lat"] + 6.2088) < 1e-9)
        check("header CORS ada", cors == "*", str(cors))
        check("diam berarti course -1", feed["course"] == -1.0 and feed["speed"] == 0.0)
        for key in ("accuracy", "ts", "mode"):
            check(f"feed memuat '{key}'", key in feed)

        # Preflight dari klien berbasis browser.
        req = urllib.request.Request(BASE + "/feed/location", method="OPTIONS")
        with urllib.request.urlopen(req, timeout=5) as r:
            check("preflight OPTIONS dijawab", r.status == 204, str(r.status))
            check("preflight mengizinkan GET", "GET" in (r.headers.get("Access-Control-Allow-Methods") or ""))

        # Rute berjalan harus memunculkan arah dan laju di feed.
        east = geo.destination((-6.2088, 106.8456), 90, 3000)
        call("/api/route/start", {
            "points": [{"lat": -6.2088, "lon": 106.8456}, {"lat": east[0], "lon": east[1]}],
            "speed_kmh": 36, "loop_mode": "once"}, token)
        time.sleep(0.4)
        with urllib.request.urlopen(BASE + "/feed/location", timeout=5) as r:
            moving = json.loads(r.read().decode())
        check("feed melaporkan arah timur", abs(moving["course"] - 90) < 1.5, str(moving.get("course")))
        check("feed melaporkan 10 m/d", abs(moving["speed"] - 10.0) < 0.2, str(moving.get("speed")))

        # Aliran SSE.
        req = urllib.request.Request(BASE + "/feed/stream")
        req.add_header("Accept", "text/event-stream")
        frames = []
        try:
            with urllib.request.urlopen(req, timeout=6) as r:
                check("aliran memakai tipe event-stream",
                      "text/event-stream" in (r.headers.get("Content-Type") or ""))
                deadline = time.time() + 3.0
                while time.time() < deadline and len(frames) < 3:
                    line = r.readline()
                    if not line:
                        break
                    line = line.decode().strip()
                    if line.startswith("data:"):
                        frames.append(json.loads(line[5:].strip()))
        except Exception as exc:  # noqa: BLE001
            check("aliran SSE terbaca", False, str(exc)[:120])
        check("aliran mengirim beberapa bingkai", len(frames) >= 2, f"dapat {len(frames)}")
        if len(frames) >= 2:
            check("posisi berubah antar bingkai",
                  frames[-1]["lon"] != frames[0]["lon"],
                  f"{frames[0].get('lon')} -> {frames[-1].get('lon')}")
        call("/api/stop", {}, token)

        print("\nEkspor GPX untuk Xcode")
        pts = [{"lat": -6.2, "lon": 106.8}, {"lat": -6.3, "lon": 106.9}]
        st, r = call("/api/gpx/export", {"points": pts, "flavor": "xcode", "speed_kmh": 20}, token)
        check("ekspor xcode berhasil", st == 200)
        check("memakai wpt", "<wpt" in r["gpx"] and "<trkpt" not in r["gpx"])
        check("tiap titik berstempel waktu", r["gpx"].count("<time>") == 2)
        st, r = call("/api/gpx/export", {"points": pts, "flavor": "track"}, token)
        check("ekspor track masih memakai trkpt", "<trkpt" in r["gpx"])
        st, r = call("/api/gpx/export", {"points": pts, "flavor": "kml"}, token)
        check("flavor tak dikenal ditolak", st == 400)

        print("\nKetahanan")
        req = urllib.request.Request(BASE + "/api/teleport", method="POST")
        req.add_header("X-Titik-Token", token)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, b"{bukan json", timeout=5) as rr:
                st = rr.status
        except urllib.error.HTTPError as e:
            st = e.code
        check("JSON rusak -> 400", st == 400, f"dapat {st}")

        st, r = call("/api/route/start", {"points": [{"lat": 0, "lon": 0}] * 10_001}, token)
        check("rute kelewat panjang ditolak", st == 400)

    finally:
        httpd.shutdown()
        httpd.server_close()
        engine.shutdown()

    print(f"\n{'=' * 52}")
    print(f"  lolos: {passed}   gagal: {failed}")
    print("=" * 52)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
