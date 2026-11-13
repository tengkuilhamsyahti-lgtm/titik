"""Mesin simulasi lokasi Titik.

Satu thread latar menghitung posisi pada 10 Hz dan mendorongnya ke
perangkat pada laju yang jauh lebih santai (default 1 Hz, sama seperti
GPS sungguhan). Memisahkan dua laju ini membuat peta di layar bergerak
mulus tanpa membanjiri kanal DVT.

Mode:
    idle      — tidak ada lokasi yang disimulasikan
    fixed     — satu titik tetap (teleport)
    route     — menyusuri polyline dengan kecepatan tertentu
    joystick  — bergerak terus ke arah tertentu
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import geo
from .backends import BackendError, DeviceInfo, LocationBackend

TICK_HZ = 10.0
TICK = 1.0 / TICK_HZ

MIN_SPEED_KMH = 0.5
MAX_SPEED_KMH = 300.0
MIN_PUSH_INTERVAL = 0.25
MAX_PUSH_INTERVAL = 10.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass
class EngineState:
    mode: str = "idle"
    position: geo.Point | None = None
    route: list[geo.Point] = field(default_factory=list)
    leg: int = 0                  # indeks segmen yang sedang dijalani
    leg_progress_m: float = 0.0   # jarak yang sudah ditempuh di segmen ini
    speed_kmh: float = 5.0
    loop_mode: str = "once"       # once | repeat | pingpong
    direction: int = 1            # 1 maju, -1 mundur (untuk pingpong)
    paused: bool = False
    heading: float = 0.0          # untuk joystick
    joystick_speed_kmh: float = 5.0
    push_interval: float = 1.0
    jitter_m: float = 0.0
    pushes: int = 0
    last_push_at: float = 0.0
    last_error: str = ""
    finished: bool = False


class Engine:
    """Pembungkus stateful di atas sebuah ``LocationBackend``."""

    def __init__(
        self,
        backend: LocationBackend,
        device: DeviceInfo,
        on_event: Callable[[str, dict], None] | None = None,
        seed: int | None = None,
    ) -> None:
        self.backend = backend
        self.device = device
        self.state = EngineState()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._rng = random.Random(seed)
        self._on_event = on_event or (lambda kind, payload: None)
        self._history: list[dict[str, Any]] = []
        self._thread = threading.Thread(target=self._loop, name="titik-engine", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------
    # Perintah publik
    # ------------------------------------------------------------------

    def teleport(self, lat: float, lon: float, label: str = "") -> None:
        if not geo.valid(lat, lon):
            raise ValueError("Koordinat di luar jangkauan yang sah.")
        with self._lock:
            s = self.state
            s.mode = "fixed"
            s.position = (float(lat), float(lon))
            s.route = []
            s.leg = 0
            s.leg_progress_m = 0.0
            s.paused = False
            s.finished = False
            self._record(lat, lon, label or "Teleport")
        self._push_now()

    def start_route(
        self,
        points: list[geo.Point],
        speed_kmh: float = 5.0,
        loop_mode: str = "once",
    ) -> None:
        pts = [(float(a), float(b)) for a, b in points if geo.valid(a, b)]
        if len(pts) < 2:
            raise ValueError("Rute butuh minimal dua titik yang sah.")
        if loop_mode not in ("once", "repeat", "pingpong"):
            raise ValueError("loop_mode harus once, repeat, atau pingpong.")
        with self._lock:
            s = self.state
            s.mode = "route"
            s.route = pts
            s.leg = 0
            s.leg_progress_m = 0.0
            s.direction = 1
            s.speed_kmh = _clamp(float(speed_kmh), MIN_SPEED_KMH, MAX_SPEED_KMH)
            s.loop_mode = loop_mode
            s.paused = False
            s.finished = False
            s.position = pts[0]
            self._record(pts[0][0], pts[0][1], "Rute dimulai")
        self._push_now()

    def set_speed(self, speed_kmh: float) -> None:
        with self._lock:
            self.state.speed_kmh = _clamp(float(speed_kmh), MIN_SPEED_KMH, MAX_SPEED_KMH)

    def pause(self) -> None:
        with self._lock:
            self.state.paused = True

    def resume(self) -> None:
        with self._lock:
            if self.state.mode in ("route", "joystick"):
                self.state.paused = False
                self.state.finished = False

    def joystick(self, heading: float, speed_kmh: float, active: bool) -> None:
        with self._lock:
            s = self.state
            if s.position is None:
                raise ValueError(
                    "Tentukan posisi awal dulu (teleport) sebelum memakai joystick."
                )
            s.heading = float(heading) % 360.0
            s.joystick_speed_kmh = _clamp(float(speed_kmh), 0.0, MAX_SPEED_KMH)
            if active and s.joystick_speed_kmh > 0:
                s.mode = "joystick"
                s.paused = False
                s.finished = False
            elif s.mode == "joystick":
                s.mode = "fixed"

    def settings(self, push_interval: float | None = None, jitter_m: float | None = None) -> None:
        with self._lock:
            if push_interval is not None:
                self.state.push_interval = _clamp(
                    float(push_interval), MIN_PUSH_INTERVAL, MAX_PUSH_INTERVAL
                )
            if jitter_m is not None:
                self.state.jitter_m = _clamp(float(jitter_m), 0.0, 50.0)

    def stop(self) -> None:
        """Hentikan simulasi dan kembalikan perangkat ke GPS asli."""
        with self._lock:
            s = self.state
            s.mode = "idle"
            s.route = []
            s.position = None
            s.paused = False
            s.finished = False
            s.leg = 0
            s.leg_progress_m = 0.0
        try:
            self.backend.clear()
            with self._lock:
                self.state.last_error = ""
            self._on_event("cleared", {})
        except BackendError as exc:
            with self._lock:
                self.state.last_error = str(exc)
            raise

    def shutdown(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        try:
            self.backend.clear()
        except Exception:  # noqa: BLE001
            pass
        self.backend.close()

    # ------------------------------------------------------------------
    # Introspeksi
    # ------------------------------------------------------------------

    def _course_speed_locked(self) -> tuple[float, float]:
        """Arah tempuh (derajat) dan laju (m/d) saat ini.

        Arah -1 berarti tidak diketahui, meniru konvensi ``CLLocation.course``
        dan ``Location.hasBearing`` ketika perangkat diam.
        """
        s = self.state
        if s.paused or s.mode in ("idle", "fixed"):
            return -1.0, 0.0
        if s.mode == "joystick":
            return s.heading, s.joystick_speed_kmh / 3.6
        if s.mode == "route" and len(s.route) >= 2:
            n = len(s.route)
            a_i, b_i = (s.leg, s.leg + 1) if s.direction == 1 else (s.leg + 1, s.leg)
            if 0 <= a_i < n and 0 <= b_i < n:
                return geo.bearing(s.route[a_i], s.route[b_i]), s.speed_kmh / 3.6
        return -1.0, 0.0

    def feed(self) -> dict[str, Any]:
        """Bentuk ringkas untuk dikonsumsi aplikasi yang sedang diuji."""
        with self._lock:
            s = self.state
            course, speed = self._course_speed_locked()
            if s.position is None:
                return {"active": False, "mode": s.mode, "ts": time.time()}
            return {
                "active": True,
                "mode": s.mode,
                "lat": s.position[0],
                "lon": s.position[1],
                "course": round(course, 2),
                "speed": round(speed, 3),
                "accuracy": round(max(5.0, s.jitter_m), 1),
                "ts": time.time(),
            }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            s = self.state
            total = geo.path_length(s.route) if len(s.route) > 1 else 0.0
            done = self._distance_done_locked()
            course, speed_mps = self._course_speed_locked()
            return {
                "course": round(course, 2),
                "speed_mps": round(speed_mps, 3),
                "mode": s.mode,
                "paused": s.paused,
                "finished": s.finished,
                "position": {"lat": s.position[0], "lon": s.position[1]} if s.position else None,
                "route": [{"lat": a, "lon": b} for a, b in s.route],
                "route_total_m": round(total, 1),
                "route_done_m": round(done, 1),
                "route_percent": round(100.0 * done / total, 1) if total > 0 else 0.0,
                "speed_kmh": round(s.speed_kmh, 1),
                "loop_mode": s.loop_mode,
                "direction": s.direction,
                "heading": round(s.heading, 1),
                "joystick_speed_kmh": round(s.joystick_speed_kmh, 1),
                "push_interval": s.push_interval,
                "jitter_m": s.jitter_m,
                "pushes": s.pushes,
                "last_error": s.last_error,
                "device": self.device.to_dict(),
                "backend": self.backend.name,
                "history": list(reversed(self._history[-25:])),
            }

    def _distance_done_locked(self) -> float:
        s = self.state
        if len(s.route) < 2:
            return 0.0
        done = sum(
            geo.haversine(s.route[i], s.route[i + 1])
            for i in range(min(s.leg, len(s.route) - 1))
        )
        return done + s.leg_progress_m

    def _record(self, lat: float, lon: float, label: str) -> None:
        self._history.append(
            {"lat": round(lat, 6), "lon": round(lon, 6), "label": label, "at": time.time()}
        )
        del self._history[:-200]

    # ------------------------------------------------------------------
    # Thread
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        next_tick = time.monotonic()
        while not self._stop.is_set():
            next_tick += TICK
            try:
                self._advance(TICK)
                self._maybe_push()
            except Exception as exc:  # noqa: BLE001 - thread tidak boleh mati
                with self._lock:
                    self.state.last_error = str(exc)
            sleep_for = next_tick - time.monotonic()
            if sleep_for > 0:
                self._stop.wait(sleep_for)
            else:
                next_tick = time.monotonic()  # kita tertinggal, reset jadwal

    def _advance(self, dt: float) -> None:
        """Gerakkan posisi maju selama ``dt`` detik."""
        with self._lock:
            s = self.state
            if s.paused or s.mode in ("idle", "fixed"):
                return

            if s.mode == "joystick":
                if s.position is None or s.joystick_speed_kmh <= 0:
                    return
                step = s.joystick_speed_kmh / 3.6 * dt
                s.position = geo.destination(s.position, s.heading, step)
                return

            if s.mode == "route":
                self._advance_route_locked(s.speed_kmh / 3.6 * dt)

    def _advance_route_locked(self, remaining_m: float) -> None:
        s = self.state
        n = len(s.route)
        if n < 2:
            return

        guard = 0
        while remaining_m > 0 and guard < 10_000:
            guard += 1
            if s.direction == 1:
                a_i, b_i = s.leg, s.leg + 1
            else:
                a_i, b_i = s.leg + 1, s.leg

            if not (0 <= a_i < n and 0 <= b_i < n):
                self._finish_route_locked()
                return

            a, b = s.route[a_i], s.route[b_i]
            seg_len = geo.haversine(a, b)

            if seg_len <= 0.01:  # segmen kembar, lompati
                if not self._next_leg_locked():
                    return
                continue

            room = seg_len - s.leg_progress_m
            if remaining_m < room:
                s.leg_progress_m += remaining_m
                s.position = geo.interpolate(a, b, s.leg_progress_m / seg_len)
                return

            remaining_m -= room
            s.position = b
            s.leg_progress_m = 0.0
            if not self._next_leg_locked():
                return

    def _next_leg_locked(self) -> bool:
        """Pindah ke segmen berikutnya. False bila rute selesai/berhenti."""
        s = self.state
        last_leg = len(s.route) - 2

        if s.direction == 1:
            if s.leg < last_leg:
                s.leg += 1
                return True
            # Sudah di ujung akhir
            if s.loop_mode == "repeat":
                s.leg = 0
                s.position = s.route[0]
                return True
            if s.loop_mode == "pingpong":
                s.direction = -1
                s.leg = last_leg
                return True
            self._finish_route_locked()
            return False

        # direction == -1
        if s.leg > 0:
            s.leg -= 1
            return True
        if s.loop_mode == "pingpong":
            s.direction = 1
            s.leg = 0
            return True
        self._finish_route_locked()
        return False

    def _finish_route_locked(self) -> None:
        s = self.state
        s.finished = True
        s.paused = True
        s.mode = "fixed"
        s.leg_progress_m = 0.0
        self._on_event("route_finished", {})

    # ------------------------------------------------------------------
    # Pengiriman ke perangkat
    # ------------------------------------------------------------------

    def _maybe_push(self) -> None:
        with self._lock:
            s = self.state
            if s.mode == "idle" or s.position is None:
                return
            if s.mode == "fixed" and s.last_push_at > 0 and not s.finished:
                return  # titik tetap cukup dikirim sekali
            now = time.monotonic()
            if now - s.last_push_at < s.push_interval:
                return
            s.last_push_at = now
        self._push_now()

    def _push_now(self) -> None:
        with self._lock:
            s = self.state
            if s.position is None:
                return
            point = s.position
            jit = s.jitter_m
            s.last_push_at = time.monotonic()
        if jit > 0:
            point = geo.jitter(point, jit, self._rng)
        try:
            self.backend.set_location(point[0], point[1])
            with self._lock:
                self.state.pushes += 1
                self.state.last_error = ""
        except BackendError as exc:
            with self._lock:
                self.state.last_error = str(exc)
            self._on_event("backend_error", {"message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.state.last_error = f"{type(exc).__name__}: {exc}"
