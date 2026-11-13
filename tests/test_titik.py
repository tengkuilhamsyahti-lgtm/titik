"""Uji Titik. Jalankan: python -m unittest discover -s tests -v"""

import sys
import time
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from titik import geo                                   # noqa: E402
from titik.backends import MockBackend, resolve_backend  # noqa: E402
from titik.engine import Engine                          # noqa: E402

JAKARTA = (-6.2088, 106.8456)
BANDUNG = (-6.9175, 107.6191)
SURABAYA = (-7.2575, 112.7521)


class TestGeo(unittest.TestCase):
    def test_haversine_known_distance(self):
        # Jakarta–Bandung kira-kira 120 km garis lurus.
        d = geo.haversine(JAKARTA, BANDUNG)
        self.assertGreater(d, 115_000)
        self.assertLess(d, 125_000)

    def test_haversine_symmetric_and_zero(self):
        self.assertAlmostEqual(geo.haversine(JAKARTA, BANDUNG),
                               geo.haversine(BANDUNG, JAKARTA), places=6)
        self.assertAlmostEqual(geo.haversine(JAKARTA, JAKARTA), 0.0, places=6)

    @staticmethod
    def angle_gap(a, b):
        """Selisih dua sudut secara melingkar: 359.9° dan 0° hanya beda 0.1°."""
        return abs((a - b + 180) % 360 - 180)

    def test_destination_roundtrip(self):
        """Bergerak lalu mengukur harus kembali ke jarak semula."""
        for brg in (0, 45, 97, 180, 271, 359):
            for dist in (1, 50, 1_000, 25_000):
                end = geo.destination(JAKARTA, brg, dist)
                self.assertAlmostEqual(geo.haversine(JAKARTA, end), dist, delta=max(0.05, dist * 1e-6))
                self.assertLess(self.angle_gap(geo.bearing(JAKARTA, end), brg), 0.3,
                                f"arah menyimpang pada {brg}° sejauh {dist} m")

    def test_interpolate_midpoint(self):
        mid = geo.interpolate(JAKARTA, BANDUNG, 0.5)
        total = geo.haversine(JAKARTA, BANDUNG)
        self.assertAlmostEqual(geo.haversine(JAKARTA, mid), total / 2, delta=1.0)
        self.assertAlmostEqual(geo.haversine(mid, BANDUNG), total / 2, delta=1.0)

    def test_interpolate_endpoints(self):
        self.assertEqual(geo.interpolate(JAKARTA, BANDUNG, 0.0), JAKARTA)
        self.assertEqual(geo.interpolate(JAKARTA, BANDUNG, 1.0), BANDUNG)

    def test_path_length_adds_up(self):
        pts = [JAKARTA, BANDUNG, SURABAYA]
        expect = geo.haversine(JAKARTA, BANDUNG) + geo.haversine(BANDUNG, SURABAYA)
        self.assertAlmostEqual(geo.path_length(pts), expect, places=6)

    def test_validation(self):
        self.assertTrue(geo.valid(-6.2, 106.8))
        self.assertTrue(geo.valid(90, 180))
        self.assertFalse(geo.valid(91, 0))
        self.assertFalse(geo.valid(0, 181))
        self.assertFalse(geo.valid(float("nan"), 0))
        self.assertFalse(geo.valid("abc", 0))

    def test_wrap_lon(self):
        self.assertAlmostEqual(geo.wrap_lon(190), -170)
        self.assertAlmostEqual(geo.wrap_lon(-190), 170)
        self.assertAlmostEqual(geo.wrap_lon(106.8), 106.8)

    def test_antimeridian_crossing(self):
        """Bergerak ke timur melewati bujur 180 tidak boleh meledak."""
        near = (0.0, 179.99)
        end = geo.destination(near, 90, 5_000)
        self.assertTrue(geo.valid(*end))
        self.assertLess(end[1], 0)  # sudah menyeberang ke bujur negatif
        self.assertAlmostEqual(geo.haversine(near, end), 5_000, delta=1.0)

    def test_jitter_within_radius(self):
        import random
        rng = random.Random(7)
        for _ in range(300):
            p = geo.jitter(JAKARTA, 10.0, rng)
            self.assertLessEqual(geo.haversine(JAKARTA, p), 10.01)
        self.assertEqual(geo.jitter(JAKARTA, 0, rng), JAKARTA)


class TestCoordParsing(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(geo.parse_coords("-6.2088, 106.8456"), (-6.2088, 106.8456))
        self.assertEqual(geo.parse_coords("-6.2088 106.8456"), (-6.2088, 106.8456))

    def test_google_maps_url(self):
        url = "https://www.google.com/maps/@-6.2088,106.8456,15z"
        self.assertEqual(geo.parse_coords(url), (-6.2088, 106.8456))

    def test_rejects_garbage(self):
        self.assertIsNone(geo.parse_coords(""))
        self.assertIsNone(geo.parse_coords("tidak ada angka di sini"))
        self.assertIsNone(geo.parse_coords("999, 999"))


class TestGpx(unittest.TestCase):
    def test_roundtrip(self):
        pts = [JAKARTA, BANDUNG, SURABAYA]
        parsed = geo.parse_gpx(geo.build_gpx(pts, "Uji"))
        self.assertEqual(len(parsed), 3)
        for a, b in zip(pts, parsed):
            self.assertAlmostEqual(a[0], b[0], places=6)
            self.assertAlmostEqual(a[1], b[1], places=6)

    def test_parses_without_namespace(self):
        raw = ('<gpx><trk><trkseg>'
               '<trkpt lat="-6.2" lon="106.8"/><trkpt lat="-6.3" lon="106.9"/>'
               '</trkseg></trk></gpx>')
        self.assertEqual(geo.parse_gpx(raw), [(-6.2, 106.8), (-6.3, 106.9)])

    def test_falls_back_to_waypoints(self):
        raw = '<gpx><wpt lat="1" lon="2"/><wpt lat="3" lon="4"/></gpx>'
        self.assertEqual(geo.parse_gpx(raw), [(1.0, 2.0), (3.0, 4.0)])

    def test_rejects_empty_and_broken(self):
        with self.assertRaises(ValueError):
            geo.parse_gpx("<gpx></gpx>")
        with self.assertRaises(ValueError):
            geo.parse_gpx("bukan xml sama sekali <<<")

    def test_escapes_name(self):
        out = geo.build_gpx([JAKARTA], 'Rute "A" & <B>')
        self.assertNotIn("<B>", out)
        self.assertIn("&amp;", out)


class EngineCase(unittest.TestCase):
    """Basis dengan engine bermesin mock dan pengiriman cepat."""

    def setUp(self):
        self.backend = MockBackend(latency_ms=0)
        self.engine = Engine(self.backend, self.backend.connect(), seed=1)
        self.engine.settings(push_interval=0.25)

    def tearDown(self):
        self.engine.shutdown()

    def wait_until(self, pred, timeout=6.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if pred():
                return True
            time.sleep(0.03)
        return False


class TestEngineBasics(EngineCase):
    def test_teleport_pushes_once(self):
        self.engine.teleport(*JAKARTA)
        self.assertEqual(self.backend.last, JAKARTA)
        s = self.engine.snapshot()
        self.assertEqual(s["mode"], "fixed")
        self.assertEqual(s["position"]["lat"], JAKARTA[0])

        before = self.backend.calls
        time.sleep(0.8)
        self.assertEqual(self.backend.calls, before,
                         "titik tetap tidak boleh dikirim berulang kali")

    def test_teleport_rejects_bad_coords(self):
        with self.assertRaises(ValueError):
            self.engine.teleport(95.0, 0.0)

    def test_stop_clears_device(self):
        self.engine.teleport(*JAKARTA)
        self.engine.stop()
        self.assertEqual(self.backend.cleared, 1)
        self.assertIsNone(self.backend.last)
        self.assertEqual(self.engine.snapshot()["mode"], "idle")

    def test_history_records(self):
        self.engine.teleport(*JAKARTA, label="Monas")
        hist = self.engine.snapshot()["history"]
        self.assertEqual(hist[0]["label"], "Monas")


class TestRoute(EngineCase):
    def test_requires_two_points(self):
        with self.assertRaises(ValueError):
            self.engine.start_route([JAKARTA], 10)

    def test_rejects_bad_loop_mode(self):
        with self.assertRaises(ValueError):
            self.engine.start_route([JAKARTA, BANDUNG], 10, loop_mode="zigzag")

    def test_travels_at_requested_speed(self):
        """36 km/j = 10 m/d. Setelah 1 detik harus menempuh ~10 m."""
        start = (0.0, 0.0)
        end = geo.destination(start, 90, 2_000)
        self.engine.start_route([start, end], speed_kmh=36.0)
        time.sleep(1.0)
        done = self.engine.snapshot()["route_done_m"]
        # Toleransi longgar: penjadwal thread tidak pernah presisi.
        self.assertGreater(done, 6.0)
        self.assertLess(done, 15.0)

    def test_stays_on_the_line(self):
        """Posisi tengah jalan harus berada di segmen, bukan melenceng."""
        a = (0.0, 0.0)
        b = geo.destination(a, 45, 1_000)
        self.engine.start_route([a, b], speed_kmh=108.0)   # 30 m/d
        time.sleep(0.6)
        pos = self.engine.snapshot()["position"]
        p = (pos["lat"], pos["lon"])
        # Jarak dari a + jarak ke b harus ~ panjang segmen bila p di garis.
        detour = geo.haversine(a, p) + geo.haversine(p, b) - geo.haversine(a, b)
        self.assertLess(abs(detour), 1.0)

    def test_finishes_and_stops(self):
        a = (0.0, 0.0)
        b = geo.destination(a, 0, 30)          # 30 m
        self.engine.start_route([a, b], speed_kmh=108.0)   # 30 m/d -> ~1 detik
        self.assertTrue(self.wait_until(lambda: self.engine.snapshot()["finished"]))
        s = self.engine.snapshot()
        self.assertEqual(s["mode"], "fixed")
        self.assertAlmostEqual(s["position"]["lat"], b[0], places=5)

    def test_repeat_wraps_around(self):
        a = (0.0, 0.0)
        b = geo.destination(a, 0, 20)
        self.engine.start_route([a, b], speed_kmh=108.0, loop_mode="repeat")
        # Harus tetap berjalan melewati titik akhir tanpa pernah "selesai".
        time.sleep(1.6)
        s = self.engine.snapshot()
        self.assertFalse(s["finished"])
        self.assertEqual(s["mode"], "route")

    def test_pingpong_reverses(self):
        a = (0.0, 0.0)
        b = geo.destination(a, 0, 25)
        self.engine.start_route([a, b], speed_kmh=108.0, loop_mode="pingpong")
        self.assertTrue(self.wait_until(
            lambda: self.engine.snapshot()["direction"] == -1, timeout=4.0))
        self.assertFalse(self.engine.snapshot()["finished"])

    def test_multi_leg_progress_is_monotonic(self):
        a = (0.0, 0.0)
        pts = [a, geo.destination(a, 0, 40), geo.destination(a, 90, 40), geo.destination(a, 180, 40)]
        self.engine.start_route(pts, speed_kmh=72.0)
        seen = []
        for _ in range(12):
            time.sleep(0.12)
            seen.append(self.engine.snapshot()["route_done_m"])
        for earlier, later in zip(seen, seen[1:]):
            self.assertGreaterEqual(later + 0.01, earlier)

    def test_duplicate_points_do_not_hang(self):
        """Segmen dengan panjang nol pernah jadi sumber loop tak hingga."""
        a = (0.0, 0.0)
        pts = [a, a, a, geo.destination(a, 0, 20), geo.destination(a, 0, 20)]
        self.engine.start_route(pts, speed_kmh=108.0)
        self.assertTrue(self.wait_until(lambda: self.engine.snapshot()["finished"], timeout=5.0))

    def test_pause_freezes_progress(self):
        a = (0.0, 0.0)
        self.engine.start_route([a, geo.destination(a, 0, 5_000)], speed_kmh=108.0)
        time.sleep(0.3)
        self.engine.pause()
        time.sleep(0.05)
        frozen = self.engine.snapshot()["route_done_m"]
        time.sleep(0.6)
        self.assertAlmostEqual(self.engine.snapshot()["route_done_m"], frozen, delta=0.6)
        self.engine.resume()
        time.sleep(0.4)
        self.assertGreater(self.engine.snapshot()["route_done_m"], frozen)

    def test_speed_change_applies_live(self):
        a = (0.0, 0.0)
        self.engine.start_route([a, geo.destination(a, 0, 10_000)], speed_kmh=3.6)  # 1 m/d
        time.sleep(0.5)
        slow = self.engine.snapshot()["route_done_m"]
        self.engine.set_speed(180.0)   # 50 m/d
        time.sleep(0.5)
        fast = self.engine.snapshot()["route_done_m"] - slow
        self.assertGreater(fast, slow * 3)


class TestJoystick(EngineCase):
    def test_needs_a_starting_point(self):
        with self.assertRaises(ValueError):
            self.engine.joystick(0, 10, True)

    def test_moves_in_the_right_direction(self):
        self.engine.teleport(0.0, 0.0)
        self.engine.joystick(heading=90, speed_kmh=108.0, active=True)   # timur, 30 m/d
        time.sleep(0.7)
        pos = self.engine.snapshot()["position"]
        self.assertGreater(pos["lon"], 0.0001)                # bergerak ke timur
        self.assertAlmostEqual(pos["lat"], 0.0, places=4)     # tidak menyimpang

    def test_release_stops_movement(self):
        self.engine.teleport(0.0, 0.0)
        self.engine.joystick(90, 108.0, True)
        time.sleep(0.3)
        self.engine.joystick(90, 0, False)
        time.sleep(0.05)
        here = self.engine.snapshot()["position"]
        time.sleep(0.5)
        there = self.engine.snapshot()["position"]
        self.assertAlmostEqual(here["lon"], there["lon"], places=6)


class TestSettings(EngineCase):
    def test_push_interval_is_clamped(self):
        self.engine.settings(push_interval=999)
        self.assertLessEqual(self.engine.snapshot()["push_interval"], 10.0)
        self.engine.settings(push_interval=0.001)
        self.assertGreaterEqual(self.engine.snapshot()["push_interval"], 0.25)

    def test_speed_is_clamped(self):
        self.engine.set_speed(99_999)
        self.assertLessEqual(self.engine.snapshot()["speed_kmh"], 300.0)

    def test_jitter_offsets_what_is_sent(self):
        self.engine.settings(jitter_m=20.0)
        self.engine.teleport(0.0, 0.0)
        sent = self.backend.last
        self.assertIsNotNone(sent)
        d = geo.haversine((0.0, 0.0), sent)
        self.assertLessEqual(d, 20.01)
        # Posisi logis tetap bersih; hanya yang dikirim yang digeser.
        self.assertEqual(self.engine.snapshot()["position"]["lat"], 0.0)


class TestXcodeGpx(unittest.TestCase):
    """Xcode hanya membaca <wpt>; <trk> dan <rte> diabaikannya."""

    def test_uses_wpt_not_trkpt(self):
        out = geo.build_gpx([JAKARTA, BANDUNG], flavor="xcode")
        self.assertIn("<wpt", out)
        self.assertNotIn("<trkpt", out)
        self.assertNotIn("<trk>", out)
        self.assertNotIn("<rte", out)

    def test_every_point_has_a_time(self):
        out = geo.build_gpx([JAKARTA, BANDUNG, SURABAYA], flavor="xcode")
        self.assertEqual(out.count("<wpt"), 3)
        self.assertEqual(out.count("<time>"), 3)

    def test_timestamps_encode_requested_speed(self):
        """Xcode menyimpulkan kecepatan dari selisih waktu antar titik."""
        import re
        a = (0.0, 0.0)
        b = geo.destination(a, 90, 3_600)   # 3.6 km
        out = geo.build_gpx([a, b], flavor="xcode", speed_kmh=36.0)  # 10 m/d
        stamps = re.findall(r"<time>(.+?)</time>", out)
        self.assertEqual(len(stamps), 2)
        t0 = datetime.strptime(stamps[0], "%Y-%m-%dT%H:%M:%SZ")
        t1 = datetime.strptime(stamps[1], "%Y-%m-%dT%H:%M:%SZ")
        gap = (t1 - t0).total_seconds()
        self.assertAlmostEqual(gap, 360.0, delta=2.0)   # 3600 m / 10 m per d

    def test_faster_speed_means_closer_timestamps(self):
        import re
        a = (0.0, 0.0)
        b = geo.destination(a, 0, 1_000)

        def gap(speed):
            stamps = re.findall(r"<time>(.+?)</time>",
                                geo.build_gpx([a, b], flavor="xcode", speed_kmh=speed))
            return (datetime.strptime(stamps[1], "%Y-%m-%dT%H:%M:%SZ")
                    - datetime.strptime(stamps[0], "%Y-%m-%dT%H:%M:%SZ")).total_seconds()

        self.assertGreater(gap(5), gap(50))

    def test_track_flavor_still_default(self):
        out = geo.build_gpx([JAKARTA, BANDUNG])
        self.assertIn("<trkpt", out)
        self.assertNotIn("<wpt", out)

    def test_rejects_unknown_flavor(self):
        with self.assertRaises(ValueError):
            geo.build_gpx([JAKARTA], flavor="kml")

    def test_xcode_output_is_valid_xml_and_reparses(self):
        out = geo.build_gpx([JAKARTA, BANDUNG], flavor="xcode")
        parsed = geo.parse_gpx(out)     # jatuh ke wpt
        self.assertEqual(len(parsed), 2)


class TestFeed(EngineCase):
    def test_idle_feed_is_inactive(self):
        f = self.engine.feed()
        self.assertFalse(f["active"])
        self.assertEqual(f["mode"], "idle")

    def test_fixed_feed_has_no_course_or_speed(self):
        self.engine.teleport(*JAKARTA)
        f = self.engine.feed()
        self.assertTrue(f["active"])
        self.assertAlmostEqual(f["lat"], JAKARTA[0])
        self.assertEqual(f["course"], -1.0)   # diam = arah tidak diketahui
        self.assertEqual(f["speed"], 0.0)

    def test_route_feed_reports_bearing_and_speed(self):
        a = (0.0, 0.0)
        b = geo.destination(a, 90, 2_000)     # tepat ke timur
        self.engine.start_route([a, b], speed_kmh=36.0)
        time.sleep(0.3)
        f = self.engine.feed()
        self.assertAlmostEqual(f["course"], 90.0, delta=1.0)
        self.assertAlmostEqual(f["speed"], 10.0, delta=0.1)   # 36 km/j = 10 m/d

    def test_joystick_feed_reports_heading(self):
        self.engine.teleport(0.0, 0.0)
        self.engine.joystick(heading=225, speed_kmh=18.0, active=True)
        f = self.engine.feed()
        self.assertAlmostEqual(f["course"], 225.0, delta=0.1)
        self.assertAlmostEqual(f["speed"], 5.0, delta=0.1)

    def test_pause_zeroes_speed(self):
        a = (0.0, 0.0)
        self.engine.start_route([a, geo.destination(a, 0, 5_000)], speed_kmh=36)
        self.engine.pause()
        f = self.engine.feed()
        self.assertEqual(f["speed"], 0.0)
        self.assertEqual(f["course"], -1.0)

    def test_accuracy_follows_jitter(self):
        self.engine.teleport(*JAKARTA)
        self.assertGreaterEqual(self.engine.feed()["accuracy"], 5.0)
        self.engine.settings(jitter_m=18)
        self.assertAlmostEqual(self.engine.feed()["accuracy"], 18.0, delta=0.1)

    def test_backend_records_without_touching_a_device(self):
        from titik.backends import FeedBackend
        b = FeedBackend()
        info = b.connect()
        self.assertEqual(info.backend, "feed")
        b.set_location(1.0, 2.0)
        self.assertEqual(b.last, (1.0, 2.0))
        b.clear()
        self.assertIsNone(b.last)


class TestAdbBackend(unittest.TestCase):
    def test_missing_adb_gives_actionable_error(self):
        import shutil as _shutil
        from titik.backends import AdbBackend, BackendError
        real = _shutil.which
        _shutil.which = lambda name: None
        try:
            with self.assertRaises(BackendError) as ctx:
                AdbBackend().connect()
            self.assertIn("adb", str(ctx.exception).lower())
            self.assertIn("PATH", str(ctx.exception))
        finally:
            _shutil.which = real

    def test_physical_device_refuses_with_explanation(self):
        from titik.backends import AdbBackend, BackendError
        b = AdbBackend("R58N1234ABC")
        b._exe = "/bin/true"
        b._is_emulator = False
        with self.assertRaises(BackendError) as ctx:
            b.set_location(1.0, 2.0)
        self.assertIn("mock location", str(ctx.exception).lower())

    def test_emulator_sends_longitude_first(self):
        """geo fix memakai urutan bujur-lintang; membaliknya adalah bug klasik."""
        from titik.backends import AdbBackend
        b = AdbBackend("emulator-5554")
        b._exe = "/bin/true"
        b._is_emulator = True
        seen = []
        b._adb = lambda args, timeout=None: seen.append(args) or ""
        b.set_location(-6.2088, 106.8456)
        self.assertEqual(seen[0][:3], ["emu", "geo", "fix"])
        self.assertTrue(seen[0][3].startswith("106."), f"bujur harus dulu: {seen[0]}")
        self.assertTrue(seen[0][4].startswith("-6."), f"lintang harus kedua: {seen[0]}")


class TestBackendResolution(unittest.TestCase):
    def test_mock_resolves(self):
        backend, info = resolve_backend("mock")
        self.assertEqual(backend.name, "mock")
        self.assertEqual(info.ios_major, 26)
        backend.close()

    def test_feed_resolves(self):
        backend, info = resolve_backend("feed")
        self.assertEqual(backend.name, "feed")
        self.assertTrue(info.notes)
        backend.close()

    def test_unknown_backend_raises(self):
        from titik.backends import BackendError
        with self.assertRaises(BackendError):
            resolve_backend("teleportasi-kuantum")

    def test_device_info_parses_version(self):
        from titik.backends import DeviceInfo
        self.assertEqual(DeviceInfo(ios_version="17.4.1").ios_major, 17)
        self.assertEqual(DeviceInfo(ios_version="").ios_major, 0)
        self.assertEqual(DeviceInfo(ios_version="sembarang").ios_major, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
