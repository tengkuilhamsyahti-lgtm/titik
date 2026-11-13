/**
 * Penyedia lokasi yang membaca feed Titik.
 *
 * Untuk React Native, Expo, Capacitor, Cordova, atau web. Tidak ada
 * dependensi — hanya `fetch` dan `EventSource` bawaan.
 *
 * Menggerbangnya: pilih implementasi lewat variabel lingkungan saat build
 * (`process.env.TITIK_FEED`), supaya bundler menghapus cabang Titik dari
 * build produksi lewat dead-code elimination. Jangan menggerbangnya lewat
 * pemeriksaan runtime saja — kodenya akan tetap ikut terkirim.
 */

export interface Fix {
  lat: number;
  lon: number;
  /** Derajat searah jarum jam dari utara; -1 bila tidak diketahui. */
  course: number;
  /** Meter per detik; -1 bila tidak diketahui. */
  speed: number;
  /** Radius akurasi horizontal dalam meter. */
  accuracy: number;
  timestamp: number;
}

export interface LocationProvider {
  start(onFix: (fix: Fix) => void, onError?: (err: Error) => void): void;
  stop(): void;
}

// --------------------------------------------------------------- produksi

export class SystemLocationProvider implements LocationProvider {
  private watchId: number | null = null;

  start(onFix: (fix: Fix) => void, onError?: (err: Error) => void): void {
    this.stop();
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      onError?.(new Error("Geolocation tidak tersedia di runtime ini."));
      return;
    }
    this.watchId = navigator.geolocation.watchPosition(
      (p) =>
        onFix({
          lat: p.coords.latitude,
          lon: p.coords.longitude,
          course: p.coords.heading ?? -1,
          speed: p.coords.speed ?? -1,
          accuracy: p.coords.accuracy ?? 5,
          timestamp: p.timestamp,
        }),
      (e) => onError?.(new Error(e.message)),
      { enableHighAccuracy: true, maximumAge: 0, timeout: 10_000 },
    );
  }

  stop(): void {
    if (this.watchId !== null) {
      navigator.geolocation.clearWatch(this.watchId);
      this.watchId = null;
    }
  }
}

// ------------------------------------------------------------- pengujian

interface Frame {
  active: boolean;
  lat?: number;
  lon?: number;
  course?: number;
  speed?: number;
  accuracy?: number;
}

function toFix(frame: Frame): Fix | null {
  if (!frame.active || frame.lat === undefined || frame.lon === undefined) {
    return null;
  }
  return {
    lat: frame.lat,
    lon: frame.lon,
    course: frame.course ?? -1,
    speed: frame.speed ?? -1,
    accuracy: frame.accuracy ?? 5,
    timestamp: Date.now(),
  };
}

/**
 * @param baseUrl mis. "http://192.168.1.10:8787"
 *   Dari emulator Android, host adalah 10.0.2.2.
 *   Dari simulator iOS, 127.0.0.1 berfungsi langsung.
 */
export class TitikLocationProvider implements LocationProvider {
  private source: EventSource | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private stopped = true;

  constructor(private readonly baseUrl: string) {}

  start(onFix: (fix: Fix) => void, onError?: (err: Error) => void): void {
    this.stop();
    this.stopped = false;

    // EventSource memberi pembaruan seketika, tetapi tidak ada di React
    // Native tanpa polyfill. Kalau absen, jatuh ke polling 1 Hz — laju
    // yang sama dengan GPS sungguhan, jadi tidak ada yang hilang.
    if (typeof EventSource !== "undefined") {
      this.startStream(onFix, onError);
    } else {
      this.startPolling(onFix, onError);
    }
  }

  private startStream(onFix: (fix: Fix) => void, onError?: (e: Error) => void): void {
    const source = new EventSource(`${this.baseUrl}/feed/stream`);
    this.source = source;

    source.onmessage = (event: MessageEvent) => {
      try {
        const fix = toFix(JSON.parse(event.data) as Frame);
        if (fix) onFix(fix);
      } catch {
        /* bingkai rusak; lewati saja */
      }
    };

    source.onerror = () => {
      // EventSource menyambung ulang sendiri. Kita hanya melaporkan
      // sekali per putusnya koneksi supaya log tidak banjir.
      if (!this.stopped) onError?.(new Error("Feed Titik terputus; mencoba menyambung ulang."));
    };
  }

  private startPolling(onFix: (fix: Fix) => void, onError?: (e: Error) => void): void {
    let failing = false;
    const tick = async () => {
      if (this.stopped) return;
      try {
        const res = await fetch(`${this.baseUrl}/feed/location`, {
          headers: { Accept: "application/json" },
        });
        if (!res.ok) throw new Error(`Feed menjawab ${res.status}`);
        const fix = toFix((await res.json()) as Frame);
        if (fix) onFix(fix);
        failing = false;
      } catch (err) {
        if (!failing) {
          failing = true;
          onError?.(err instanceof Error ? err : new Error(String(err)));
        }
      }
    };
    void tick();
    this.timer = setInterval(tick, 1000);
  }

  stop(): void {
    this.stopped = true;
    this.source?.close();
    this.source = null;
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }
}

// ----------------------------------------------------------------- pabrik

export function makeLocationProvider(): LocationProvider {
  // Dibaca saat build. Di build produksi nilainya undefined, dan bundler
  // membuang seluruh cabang beserta kelas TitikLocationProvider.
  const feed =
    typeof process !== "undefined" ? process.env?.TITIK_FEED : undefined;

  if (feed) {
    return new TitikLocationProvider(feed);
  }
  return new SystemLocationProvider();
}

/*
 * Pemakaian:
 *
 *   const provider = makeLocationProvider();
 *   provider.start(
 *     (fix) => store.setPosition(fix),
 *     (err) => console.warn("lokasi:", err.message),
 *   );
 *
 * Jalankan dengan:
 *   TITIK_FEED=http://192.168.1.10:8787 npm start
 *
 * Catatan cleartext: feed memakai HTTP polos, jadi iOS dan Android
 * memblokirnya secara baku. Lihat catatan di contoh Swift dan Kotlin
 * untuk pengecualian yang benar — dan terapkan hanya di konfigurasi
 * build internal.
 */
