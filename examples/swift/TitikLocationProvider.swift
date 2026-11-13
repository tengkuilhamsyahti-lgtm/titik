//
//  TitikLocationProvider.swift
//
//  Penyedia lokasi yang membaca feed Titik, untuk build internal.
//
//  ────────────────────────────────────────────────────────────────────
//  PENTING — cara menggerbangnya
//  ────────────────────────────────────────────────────────────────────
//  Berkas ini SENGAJA TIDAK memakai `#if DEBUG`. Build TestFlight dibuat
//  dengan konfigurasi Release, jadi gerbang DEBUG justru akan membuang
//  kode ini persis di build yang Anda butuhkan.
//
//  Yang benar: buat konfigurasi build tersendiri (mis. "Beta"), lalu di
//  Build Settings → Swift Compiler - Custom Flags → Active Compilation
//  Conditions, tambahkan `TITIK_FEED_ENABLED` HANYA untuk konfigurasi
//  Debug dan Beta. Biarkan konfigurasi Release App Store bersih.
//
//  Dengan begitu: build TestFlight (Beta) memuatnya dan tidak memerlukan
//  Developer Mode, sementara build App Store tidak memuat satu byte pun
//  dari kode ini.
//

import CoreLocation
import Foundation

// MARK: - Kontrak

/// Satu-satunya hal yang boleh dilihat kode aplikasi Anda. Tukar
/// implementasinya, dan seluruh fitur berbasis lokasi ikut berpindah.
protocol LocationProviding: AnyObject {
    var onUpdate: ((CLLocation) -> Void)? { get set }
    var onFailure: ((Error) -> Void)? { get set }
    func start()
    func stop()
}

// MARK: - Produksi

final class SystemLocationProvider: NSObject, LocationProviding {
    var onUpdate: ((CLLocation) -> Void)?
    var onFailure: ((Error) -> Void)?

    private let manager = CLLocationManager()

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBest
    }

    func start() {
        manager.requestWhenInUseAuthorization()
        manager.startUpdatingLocation()
    }

    func stop() {
        manager.stopUpdatingLocation()
    }
}

extension SystemLocationProvider: CLLocationManagerDelegate {
    func locationManager(_ m: CLLocationManager, didUpdateLocations locs: [CLLocation]) {
        guard let last = locs.last else { return }
        onUpdate?(last)
    }

    func locationManager(_ m: CLLocationManager, didFailWithError error: Error) {
        onFailure?(error)
    }
}

#if TITIK_FEED_ENABLED

// MARK: - Pengujian

/// Menyambung ke aliran SSE Titik dan memancarkan setiap posisi sebagai
/// `CLLocation` biasa. Dari sudut pandang aplikasi, tidak ada bedanya
/// dengan GPS sungguhan.
final class TitikLocationProvider: LocationProviding {
    var onUpdate: ((CLLocation) -> Void)?
    var onFailure: ((Error) -> Void)?

    private let feedURL: URL
    private var task: Task<Void, Never>?

    /// - Parameter feedURL: mis. `http://192.168.1.10:8787/feed/stream`
    init(feedURL: URL) {
        self.feedURL = feedURL
    }

    func start() {
        stop()
        task = Task { [weak self] in
            guard let self else { return }
            var backoff: UInt64 = 1
            while !Task.isCancelled {
                do {
                    try await self.consume()
                    backoff = 1
                } catch is CancellationError {
                    return
                } catch {
                    self.onFailure?(error)
                    // Titik mungkin belum menyala, atau laptopnya tidur.
                    // Coba lagi dengan jeda menaik sampai 16 detik.
                    try? await Task.sleep(nanoseconds: backoff * 1_000_000_000)
                    backoff = min(backoff * 2, 16)
                }
            }
        }
    }

    func stop() {
        task?.cancel()
        task = nil
    }

    private func consume() async throws {
        var request = URLRequest(url: feedURL)
        request.timeoutInterval = .infinity
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")

        let (bytes, response) = try await URLSession.shared.bytes(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }

        for try await line in bytes.lines {
            guard line.hasPrefix("data:") else { continue }
            let payload = line.dropFirst(5).trimmingCharacters(in: .whitespaces)
            guard
                let data = payload.data(using: .utf8),
                let frame = try? JSONDecoder().decode(Frame.self, from: data),
                frame.active, let lat = frame.lat, let lon = frame.lon
            else { continue }

            let location = CLLocation(
                coordinate: CLLocationCoordinate2D(latitude: lat, longitude: lon),
                altitude: 0,
                horizontalAccuracy: frame.accuracy ?? 5,
                verticalAccuracy: -1,
                course: frame.course ?? -1,
                speed: frame.speed ?? -1,
                timestamp: Date()
            )
            await MainActor.run { self.onUpdate?(location) }
        }
    }

    private struct Frame: Decodable {
        let active: Bool
        let lat: Double?
        let lon: Double?
        let course: Double?
        let speed: Double?
        let accuracy: Double?
    }
}

#endif

// MARK: - Pabrik

enum LocationProviderFactory {
    /// Pakai ini di seluruh aplikasi alih-alih membuat `CLLocationManager`
    /// langsung. Di build App Store, cabang Titik tidak ikut dikompilasi.
    static func make() -> LocationProviding {
        #if TITIK_FEED_ENABLED
        // Diisi lewat skema Xcode (Run → Arguments → Environment Variables)
        // atau lewat layar pengaturan internal yang menulis ke UserDefaults.
        let raw = ProcessInfo.processInfo.environment["TITIK_FEED"]
            ?? UserDefaults.standard.string(forKey: "TitikFeedURL")
        if let raw, let url = URL(string: raw) {
            return TitikLocationProvider(feedURL: url)
        }
        #endif
        return SystemLocationProvider()
    }
}

//
//  Pemakaian:
//
//      let provider = LocationProviderFactory.make()
//      provider.onUpdate = { location in
//          viewModel.apply(location)
//      }
//      provider.start()
//
//  Catatan App Transport Security: feed berjalan di HTTP polos. Untuk
//  build Beta, tambahkan NSAllowsLocalNetworking ke Info.plist dari
//  konfigurasi itu — JANGAN NSAllowsArbitraryLoads, dan jangan di
//  Info.plist produksi.
//
