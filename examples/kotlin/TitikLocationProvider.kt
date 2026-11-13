package com.example.location

/*
 * Penyedia lokasi yang membaca feed Titik, untuk build internal Android.
 *
 * Menggerbangnya: taruh berkas ini di source set `debug` atau di source
 * set khusus (mis. `beta`), bukan di `main`. Dengan begitu build release
 * Play Store tidak memuatnya sama sekali, dan Anda tidak perlu
 * mengandalkan ProGuard untuk membuangnya.
 *
 *   src/main/java/...   → LocationProviding + SystemLocationProvider
 *   src/beta/java/...   → TitikLocationProvider + pabriknya
 *
 * Hanya memakai pustaka standar dan Coroutines; tidak butuh OkHttp.
 */

import android.annotation.SuppressLint
import android.content.Context
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import kotlin.coroutines.cancellation.CancellationException
import kotlin.coroutines.coroutineContext

// ---------------------------------------------------------------- kontrak

interface LocationProviding {
    fun start(onUpdate: (Location) -> Unit, onFailure: (Throwable) -> Unit = {})
    fun stop()
}

// -------------------------------------------------------------- produksi

class SystemLocationProvider(private val context: Context) : LocationProviding {

    private var listener: LocationListener? = null

    @SuppressLint("MissingPermission")
    override fun start(onUpdate: (Location) -> Unit, onFailure: (Throwable) -> Unit) {
        val manager = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        val l = LocationListener { onUpdate(it) }
        listener = l
        try {
            manager.requestLocationUpdates(LocationManager.GPS_PROVIDER, 1000L, 0f, l)
        } catch (t: Throwable) {
            onFailure(t)
        }
    }

    override fun stop() {
        listener?.let { l ->
            val manager = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
            manager.removeUpdates(l)
        }
        listener = null
    }
}

// -------------------------------------------------------------- pengujian

/**
 * Menarik posisi dari aliran SSE Titik dan memancarkannya sebagai
 * [Location] biasa.
 *
 * @param feedUrl mis. "http://192.168.1.10:8787/feed/stream".
 *   Dari emulator Android, host adalah 10.0.2.2, bukan 127.0.0.1.
 */
class TitikLocationProvider(
    private val feedUrl: String,
    private val scope: CoroutineScope,
) : LocationProviding {

    private var job: Job? = null

    override fun start(onUpdate: (Location) -> Unit, onFailure: (Throwable) -> Unit) {
        stop()
        job = scope.launch(Dispatchers.IO) {
            var backoffSeconds = 1L
            while (isActive) {
                try {
                    consume(onUpdate)
                    backoffSeconds = 1L
                } catch (c: CancellationException) {
                    throw c
                } catch (t: Throwable) {
                    onFailure(t)
                    delay(backoffSeconds * 1000)
                    backoffSeconds = (backoffSeconds * 2).coerceAtMost(16)
                }
            }
        }
    }

    override fun stop() {
        job?.cancel()
        job = null
    }

    private suspend fun consume(onUpdate: (Location) -> Unit) {
        val conn = (URL(feedUrl).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            setRequestProperty("Accept", "text/event-stream")
            connectTimeout = 5_000
            readTimeout = 0          // aliran tidak pernah selesai sendiri
            doInput = true
        }
        try {
            if (conn.responseCode != 200) error("Feed menjawab ${conn.responseCode}")
            conn.inputStream.bufferedReader().use { reader ->
                while (true) {
                    coroutineContext.ensureActive()
                    val line = reader.readLine() ?: break
                    if (!line.startsWith("data:")) continue
                    parse(line.removePrefix("data:").trim())?.let(onUpdate)
                }
            }
        } finally {
            conn.disconnect()
        }
    }

    private fun parse(payload: String): Location? {
        val json = runCatching { JSONObject(payload) }.getOrNull() ?: return null
        if (!json.optBoolean("active", false)) return null
        if (!json.has("lat") || !json.has("lon")) return null

        return Location("titik").apply {
            latitude = json.getDouble("lat")
            longitude = json.getDouble("lon")
            accuracy = json.optDouble("accuracy", 5.0).toFloat()
            time = System.currentTimeMillis()
            elapsedRealtimeNanos = android.os.SystemClock.elapsedRealtimeNanos()

            val course = json.optDouble("course", -1.0)
            if (course >= 0) bearing = course.toFloat()

            val mps = json.optDouble("speed", -1.0)
            if (mps >= 0) speed = mps.toFloat()
        }
    }
}

// ----------------------------------------------------------------- pabrik

object LocationProviderFactory {

    /**
     * Dipanggil dari kode aplikasi alih-alih membuat LocationManager
     * langsung. Di source set release, kembalikan SystemLocationProvider
     * tanpa syarat.
     */
    fun make(context: Context, scope: CoroutineScope): LocationProviding {
        val feed = context
            .getSharedPreferences("titik", Context.MODE_PRIVATE)
            .getString("feedUrl", null)
            ?: System.getenv("TITIK_FEED")

        return if (!feed.isNullOrBlank()) {
            TitikLocationProvider(feed, scope)
        } else {
            SystemLocationProvider(context)
        }
    }
}

/*
 * Catatan cleartext: feed berjalan di HTTP polos. Android 9+ memblokirnya
 * secara baku. Tambahkan network security config HANYA di source set
 * debug/beta:
 *
 *   <!-- src/beta/res/xml/network_security_config.xml -->
 *   <network-security-config>
 *     <domain-config cleartextTrafficPermitted="true">
 *       <domain includeSubdomains="true">10.0.2.2</domain>
 *       <domain includeSubdomains="true">192.168.0.0</domain>
 *     </domain-config>
 *   </network-security-config>
 *
 * Jangan pernah pasang cleartextTrafficPermitted="true" global di manifest
 * produksi.
 */
