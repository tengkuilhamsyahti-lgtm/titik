"""Geodesi dan GPX untuk Titik.

Semua jarak dalam meter, semua sudut dalam derajat, semua titik berupa
tuple ``(lat, lon)``. Memakai model bola berjari-jari rata-rata bumi —
akurasinya ~0.3% dan itu jauh lebih presisi daripada GPS konsumen.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

EARTH_RADIUS_M = 6_371_008.8

Point = tuple[float, float]


# --------------------------------------------------------------------------
# Validasi
# --------------------------------------------------------------------------

def valid(lat: float, lon: float) -> bool:
    """True bila koordinat masuk akal."""
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return False
    if math.isnan(lat) or math.isnan(lon) or math.isinf(lat) or math.isinf(lon):
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def clamp_lat(lat: float) -> float:
    return max(-90.0, min(90.0, lat))


def wrap_lon(lon: float) -> float:
    """Bungkus bujur ke rentang [-180, 180)."""
    return (lon + 180.0) % 360.0 - 180.0


# --------------------------------------------------------------------------
# Jarak, arah, proyeksi
# --------------------------------------------------------------------------

def haversine(a: Point, b: Point) -> float:
    """Jarak lingkaran besar antara dua titik, dalam meter."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def bearing(a: Point, b: Point) -> float:
    """Arah awal dari a ke b, derajat searah jarum jam dari utara [0, 360)."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def destination(origin: Point, bearing_deg: float, distance_m: float) -> Point:
    """Titik hasil bergerak sejauh ``distance_m`` ke arah ``bearing_deg``."""
    if distance_m == 0:
        return origin
    lat1, lon1 = math.radians(origin[0]), math.radians(origin[1])
    brg = math.radians(bearing_deg)
    ang = distance_m / EARTH_RADIUS_M

    lat2 = math.asin(
        math.sin(lat1) * math.cos(ang) + math.cos(lat1) * math.sin(ang) * math.cos(brg)
    )
    lon2 = lon1 + math.atan2(
        math.sin(brg) * math.sin(ang) * math.cos(lat1),
        math.cos(ang) - math.sin(lat1) * math.sin(lat2),
    )
    return (clamp_lat(math.degrees(lat2)), wrap_lon(math.degrees(lon2)))


def interpolate(a: Point, b: Point, t: float) -> Point:
    """Titik pada fraksi ``t`` (0..1) sepanjang segmen a→b."""
    t = max(0.0, min(1.0, t))
    if t == 0.0:
        return a
    if t == 1.0:
        return b
    return destination(a, bearing(a, b), haversine(a, b) * t)


def path_length(points: Sequence[Point]) -> float:
    """Total panjang polyline dalam meter."""
    return sum(haversine(points[i], points[i + 1]) for i in range(len(points) - 1))


def jitter(point: Point, radius_m: float, rng) -> Point:
    """Geser titik secara acak dalam radius tertentu.

    Meniru derau GPS konsumen. Memakai distribusi seragam di dalam cakram
    (akar dari u, bukan u, supaya tidak menumpuk di tengah).
    """
    if radius_m <= 0:
        return point
    brg = rng.uniform(0.0, 360.0)
    dist = radius_m * math.sqrt(rng.random())
    return destination(point, brg, dist)


# --------------------------------------------------------------------------
# GPX
# --------------------------------------------------------------------------

_GPX_NS = "http://www.topografix.com/GPX/1/1"


def parse_gpx(text: str) -> list[Point]:
    """Ambil semua titik dari GPX: trkpt lebih dulu, lalu rtept, lalu wpt.

    Dibuat permisif — banyak GPX di alam liar punya namespace aneh atau
    tanpa namespace sama sekali, jadi kita cocokkan berdasarkan nama tag
    tanpa peduli namespace-nya.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"GPX tidak bisa dibaca: {exc}") from exc

    def collect(tag: str) -> list[Point]:
        out: list[Point] = []
        for el in root.iter():
            if el.tag.rsplit("}", 1)[-1] != tag:
                continue
            lat, lon = el.get("lat"), el.get("lon")
            if lat is None or lon is None:
                continue
            try:
                lat_f, lon_f = float(lat), float(lon)
            except ValueError:
                continue
            if valid(lat_f, lon_f):
                out.append((lat_f, lon_f))
        return out

    for tag in ("trkpt", "rtept", "wpt"):
        pts = collect(tag)
        if pts:
            return pts
    raise ValueError("GPX tidak memuat satu pun titik (trkpt/rtept/wpt).")


def build_gpx(
    points: Iterable[Point],
    name: str = "Rute Titik",
    flavor: str = "track",
    speed_kmh: float = 5.0,
) -> str:
    """Rangkai polyline menjadi dokumen GPX 1.1.

    ``flavor="track"`` menulis ``<trkpt>`` di dalam ``<trk><trkseg>``. Ini
    bentuk baku yang dipahami hampir semua aplikasi peta dan olahraga.

    ``flavor="xcode"`` menulis ``<wpt>`` datar di akar dokumen, masing-masing
    dengan ``<time>``. Xcode hanya membaca ``<wpt>`` untuk simulasi lokasi —
    tag ``<trk>`` dan ``<rte>`` diabaikannya — dan ia menyimpulkan kecepatan
    gerak dari selisih waktu antar titik berurutan. Jadi stempel waktu di
    sini dihitung mundur dari ``speed_kmh``: makin cepat yang diminta, makin
    rapat jaraknya.
    """
    pts = list(points)
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    if flavor == "xcode":
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<gpx version="1.1" creator="Titik" xmlns="{_GPX_NS}">',
            f"  <!-- {_esc(name)} — untuk Xcode: Product > Scheme > Edit Scheme >",
            "       Run > Options > Allow Location Simulation, lalu pilih berkas ini. -->",
        ]
        mps = max(0.1, float(speed_kmh) / 3.6)
        elapsed = 0.0
        for i, (lat, lon) in enumerate(pts):
            if i > 0:
                elapsed += haversine(pts[i - 1], pts[i]) / mps
            t = (now + timedelta(seconds=elapsed)).strftime("%Y-%m-%dT%H:%M:%SZ")
            lines.append(f'  <wpt lat="{lat:.7f}" lon="{lon:.7f}">')
            lines.append(f"    <time>{t}</time>")
            lines.append("  </wpt>")
        lines += ["</gpx>", ""]
        return "\n".join(lines)

    if flavor != "track":
        raise ValueError("flavor harus 'track' atau 'xcode'.")

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<gpx version="1.1" creator="Titik" xmlns="{_GPX_NS}">',
        "  <metadata>",
        f"    <name>{_esc(name)}</name>",
        f"    <time>{stamp}</time>",
        "  </metadata>",
        "  <trk>",
        f"    <name>{_esc(name)}</name>",
        "    <trkseg>",
    ]
    for lat, lon in pts:
        lines.append(f'      <trkpt lat="{lat:.7f}" lon="{lon:.7f}"></trkpt>')
    lines += ["    </trkseg>", "  </trk>", "</gpx>", ""]
    return "\n".join(lines)


def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# --------------------------------------------------------------------------
# Parsing koordinat yang diketik manusia
# --------------------------------------------------------------------------

def parse_coords(text: str) -> Point | None:
    """Baca "lat, lon" dari input bebas.

    Menerima "-6.2088, 106.8456", "-6.2088 106.8456", dan juga URL Google
    Maps yang memuat pola ``@lat,lon``.
    """
    if not text:
        return None
    s = text.strip()

    if "@" in s:
        s = s.split("@", 1)[1]

    cleaned = []
    for ch in s:
        if ch.isdigit() or ch in "+-.":
            cleaned.append(ch)
        else:
            cleaned.append(" ")
    parts = [p for p in "".join(cleaned).split() if p not in ("+", "-", ".", "")]

    for i in range(len(parts) - 1):
        try:
            lat, lon = float(parts[i]), float(parts[i + 1])
        except ValueError:
            continue
        if valid(lat, lon):
            return (lat, lon)
    return None
