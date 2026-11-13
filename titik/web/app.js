/* Titik — antarmuka web */
(function () {
  "use strict";

  const TOKEN = window.TITIK_TOKEN || "";
  const $ = (id) => document.getElementById(id);

  // ------------------------------------------------------------ keadaan
  let waypoints = [];        // [{lat, lon}] yang sedang disusun
  let last = null;           // snapshot status terakhir dari server
  let activeTab = "teleport";
  let pendingPick = null;    // titik hasil klik peta di tab Teleport
  let stickActive = false;

  // ------------------------------------------------------------- jaring
  async function api(path, body) {
    const opts = {
      method: body === undefined ? "GET" : "POST",
      headers: { "X-Titik-Token": TOKEN },
    };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    let data;
    try { data = await res.json(); }
    catch { throw new Error("Server menjawab dengan bentuk yang tidak terduga."); }
    if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }

  function toast(msg, kind) {
    const el = document.createElement("div");
    el.className = "toast" + (kind ? " " + kind : "");
    el.textContent = msg;
    $("toasts").appendChild(el);
    setTimeout(() => {
      el.style.transition = "opacity .3s";
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 320);
    }, kind === "err" ? 7000 : 3200);
  }

  const fail = (e) => toast(e.message || String(e), "err");

  // --------------------------------------------------------------- peta
  let map = null, meMarker = null, routeLine = null, wpLayer = null, pickMarker = null;

  function initMap() {
    if (typeof L === "undefined") {
      $("map").innerHTML =
        '<div class="map-fallback"><strong>Peta tidak bisa dimuat.</strong>' +
        "<span>Titik mengambil pustaka peta dari internet. Periksa koneksi, " +
        "lalu muat ulang halaman ini. Semua fungsi lain tetap berjalan lewat " +
        "kotak koordinat di tab Teleport.</span></div>";
      return;
    }

    map = L.map("map", { zoomControl: true, attributionControl: true })
      .setView([-6.2088, 106.8456], 12);

    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
      maxZoom: 20,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> ' +
        '&copy; <a href="https://carto.com/attributions">CARTO</a>',
    }).addTo(map);

    wpLayer = L.layerGroup().addTo(map);

    map.on("click", (ev) => {
      const p = { lat: +ev.latlng.lat.toFixed(6), lon: +ev.latlng.lng.toFixed(6) };
      if (activeTab === "rute") {
        waypoints.push(p);
        renderWaypoints();
      } else {
        pendingPick = p;
        $("coordIn").value = `${p.lat}, ${p.lon}`;
        if (pickMarker) pickMarker.remove();
        pickMarker = L.circleMarker([p.lat, p.lon], {
          radius: 7, color: "#818CF8", weight: 2, fillColor: "#818CF8", fillOpacity: .35,
        }).addTo(map);
      }
    });
  }

  function drawPosition(pos) {
    if (!map || !pos) return;
    const ll = [pos.lat, pos.lon];
    if (!meMarker) {
      meMarker = L.marker(ll, {
        icon: L.divIcon({ className: "", html: '<div class="me-dot"></div>', iconSize: [18, 18], iconAnchor: [9, 9] }),
        interactive: false,
        zIndexOffset: 1000,
      }).addTo(map);
      map.setView(ll, Math.max(map.getZoom(), 15));
    } else {
      meMarker.setLatLng(ll);
    }
  }

  function drawRoute(points) {
    if (!map) return;
    const latlngs = points.map((p) => [p.lat, p.lon]);
    if (routeLine) routeLine.remove();
    routeLine = latlngs.length > 1
      ? L.polyline(latlngs, { color: "#22D3EE", weight: 3, opacity: .75, dashArray: "1 7", lineCap: "round" }).addTo(map)
      : null;

    wpLayer.clearLayers();
    latlngs.forEach((ll, i) => {
      L.circleMarker(ll, {
        radius: 5, color: "#818CF8", weight: 2, fillColor: "#0B1020", fillOpacity: 1,
      }).bindTooltip(String(i + 1), { permanent: false }).addTo(wpLayer);
    });
  }

  // -------------------------------------------------------- daftar titik
  function renderWaypoints() {
    const ul = $("wpList");
    ul.innerHTML = "";
    if (!waypoints.length) {
      ul.innerHTML = '<li class="empty">Belum ada titik. Klik di peta.</li>';
    } else {
      waypoints.forEach((p, i) => {
        const li = document.createElement("li");
        li.className = "wp";
        li.innerHTML =
          `<span class="wp-idx">${i + 1}</span>` +
          `<span class="wp-co">${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}</span>`;
        const del = document.createElement("button");
        del.className = "wp-del";
        del.textContent = "×";
        del.title = "Hapus titik ini";
        del.onclick = () => { waypoints.splice(i, 1); renderWaypoints(); };
        li.appendChild(del);
        ul.appendChild(li);
      });
    }
    if (last && last.mode !== "route") drawRoute(waypoints);
  }

  // ------------------------------------------------------------- status
  function applyStatus(s) {
    last = s;

    // Perangkat
    const d = s.device || {};
    const dot = $("devDot");
    dot.className = "dot " + (s.last_error ? "err" : (s.backend === "mock" ? "mock" : "live"));
    $("devName").textContent = d.name || d.product || "Perangkat";
    $("devMeta").textContent =
      [d.product, d.ios_version ? "iOS " + d.ios_version : null, "backend " + (s.backend || "?")]
        .filter(Boolean).join(" · ");

    const noteEl = $("devNote");
    const notes = (d.notes || []).slice();
    if (s.last_error) notes.unshift("⚠ " + s.last_error);
    if (notes.length) { noteEl.hidden = false; noteEl.textContent = notes.join("\n\n"); }
    else { noteEl.hidden = true; }

    // Bilah status
    const MODES = { idle: "Diam", fixed: "Titik tetap", route: "Menyusuri rute", joystick: "Joystick" };
    $("stMode").textContent = (MODES[s.mode] || s.mode) + (s.paused && s.mode === "route" ? " (jeda)" : "");
    $("stPos").textContent = s.position
      ? `${s.position.lat.toFixed(5)}, ${s.position.lon.toFixed(5)}` : "—";
    $("stProg").textContent = s.route_total_m > 0
      ? `${fmtDist(s.route_done_m)} / ${fmtDist(s.route_total_m)}` : "—";
    $("stPush").textContent = s.pushes;
    $("progBar").style.width = (s.route_total_m > 0 ? s.route_percent : 0) + "%";

    drawPosition(s.position);
    if (s.mode === "route" && s.route && s.route.length > 1) drawRoute(s.route);

    $("btnRoutePause").textContent = s.paused ? "Lanjut" : "Jeda";
    $("btnRoutePause").disabled = s.mode !== "route" && !(s.mode === "fixed" && s.finished);
  }

  function fmtDist(m) {
    return m >= 1000 ? (m / 1000).toFixed(2) + " km" : Math.round(m) + " m";
  }

  async function poll() {
    try { applyStatus(await api("/api/status")); }
    catch (e) { /* server mungkin sedang sibuk; coba lagi siklus berikutnya */ }
  }

  // ----------------------------------------------------------- favorit
  async function loadFavorites() {
    let data;
    try { data = await api("/api/favorites"); } catch (e) { return fail(e); }

    const places = $("favPlaces");
    places.innerHTML = data.places.length ? "" : '<div class="empty">Belum ada tempat tersimpan.</div>';
    data.places.slice().reverse().forEach((it) => {
      places.appendChild(favRow(it.name, `${it.lat}, ${it.lon}`,
        () => doTeleport(it.lat, it.lon, it.name),
        () => removeFav("places", it.id)));
    });

    const routes = $("favRoutes");
    routes.innerHTML = data.routes.length ? "" : '<div class="empty">Belum ada rute tersimpan.</div>';
    data.routes.slice().reverse().forEach((it) => {
      routes.appendChild(favRow(it.name, `${it.points.length} titik`,
        () => { waypoints = it.points.map((p) => ({ lat: p.lat, lon: p.lon })); renderWaypoints(); switchTab("rute"); toast("Rute dimuat ke penyusun."); },
        () => removeFav("routes", it.id)));
    });
  }

  function favRow(name, meta, onPick, onDel) {
    const row = document.createElement("div");
    row.className = "fav";
    row.innerHTML = `<div class="fav-body"><div class="fav-name"></div><div class="fav-meta"></div></div>`;
    row.querySelector(".fav-name").textContent = name;
    row.querySelector(".fav-meta").textContent = meta;
    row.onclick = onPick;
    const del = document.createElement("button");
    del.className = "wp-del";
    del.textContent = "×";
    del.title = "Hapus";
    del.onclick = (e) => { e.stopPropagation(); onDel(); };
    row.appendChild(del);
    return row;
  }

  async function removeFav(kind, id) {
    try { await api("/api/favorites/delete", { kind, id }); await loadFavorites(); }
    catch (e) { fail(e); }
  }

  function renderHistory() {
    const box = $("histList");
    const h = (last && last.history) || [];
    box.innerHTML = h.length ? "" : '<div class="empty">Belum ada riwayat.</div>';
    h.slice(0, 12).forEach((it) => {
      box.appendChild(favRow(it.label || "Titik", `${it.lat}, ${it.lon}`,
        () => doTeleport(it.lat, it.lon), () => {}));
    });
  }

  // ------------------------------------------------------------- aksi
  async function doTeleport(lat, lon, label) {
    try {
      applyStatus(await api("/api/teleport", { lat, lon, label: label || "" }));
      if (map) map.setView([lat, lon], Math.max(map.getZoom(), 15));
      toast("Lokasi dipindahkan.", "ok");
    } catch (e) { fail(e); }
  }

  async function teleportFromInput() {
    const raw = $("coordIn").value.trim();
    if (!raw) return toast("Isi koordinat dulu, atau klik di peta.", "err");
    try {
      const p = await api("/api/parse", { text: raw });
      await doTeleport(p.lat, p.lon);
      if (pickMarker) { pickMarker.remove(); pickMarker = null; }
    } catch (e) { fail(e); }
  }

  // ---------------------------------------------------------- joystick
  function setupStick() {
    const pad = $("stick"), knob = $("knob");
    let dragging = false, R = 0;

    const reset = () => {
      knob.style.transform = "translate(0,0)";
      knob.textContent = "0";
    };

    function update(ev) {
      const r = pad.getBoundingClientRect();
      R = r.width / 2 - 25;
      const dx = ev.clientX - (r.left + r.width / 2);
      const dy = ev.clientY - (r.top + r.height / 2);
      const dist = Math.min(Math.hypot(dx, dy), R);
      const ang = Math.atan2(dx, -dy);                 // 0 = utara
      const kx = Math.sin(ang) * dist, ky = -Math.cos(ang) * dist;
      knob.style.transform = `translate(${kx}px, ${ky}px)`;

      const heading = (ang * 180 / Math.PI + 360) % 360;
      const frac = R > 0 ? dist / R : 0;
      const speed = Math.round(frac * (+$("stickMax").value));
      knob.textContent = speed;

      send(heading, speed, speed > 0);
    }

    let lastSend = 0, queued = null;
    function send(heading, speed, active) {
      queued = { heading, speed_kmh: speed, active };
      const now = Date.now();
      if (now - lastSend < 160) return;              // batasi laju ke server
      lastSend = now;
      const q = queued; queued = null;
      api("/api/joystick", q).then(applyStatus).catch(fail);
    }

    pad.addEventListener("pointerdown", (ev) => {
      if (!last || !last.position) {
        return toast("Tentukan posisi awal lewat tab Teleport dulu.", "err");
      }
      dragging = true; stickActive = true;
      pad.classList.add("dragging");
      pad.setPointerCapture(ev.pointerId);
      update(ev);
    });
    pad.addEventListener("pointermove", (ev) => { if (dragging) update(ev); });

    const release = () => {
      if (!dragging) return;
      dragging = false; stickActive = false;
      pad.classList.remove("dragging");
      reset();
      api("/api/joystick", { heading: 0, speed_kmh: 0, active: false }).then(applyStatus).catch(fail);
    };
    pad.addEventListener("pointerup", release);
    pad.addEventListener("pointercancel", release);

    $("btnStickStop").onclick = release;
    reset();
  }

  // ------------------------------------------------------------- tab
  function switchTab(name) {
    activeTab = name;
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.dataset.pane === name));
    document.querySelectorAll(".pane").forEach((p) => p.classList.toggle("on", p.id === "pane-" + name));
    if (name === "fav") { loadFavorites(); renderHistory(); }
    if (name === "rute") renderWaypoints();
  }

  // ------------------------------------------------------------- GPX
  function download(filename, text) {
    const blob = new Blob([text], { type: "application/gpx+xml" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  // ------------------------------------------------------------ pasang
  function wire() {
    document.querySelectorAll(".tab").forEach((t) => {
      t.onclick = () => switchTab(t.dataset.pane);
    });

    $("btnTeleport").onclick = teleportFromInput;
    $("coordIn").addEventListener("keydown", (e) => { if (e.key === "Enter") teleportFromInput(); });

    $("btnSavePlace").onclick = async () => {
      const p = pendingPick || (last && last.position) || null;
      if (!p) return toast("Pilih titik di peta atau pindahkan lokasi dulu.", "err");
      const name = prompt("Nama tempat ini?", "");
      if (name === null) return;
      try {
        await api("/api/favorites/place", { name, lat: p.lat, lon: p.lon });
        toast("Tersimpan ke favorit.", "ok");
        if (activeTab === "fav") loadFavorites();
      } catch (e) { fail(e); }
    };

    $("btnStop").onclick = async () => {
      try {
        applyStatus(await api("/api/stop", {}));
        if (meMarker) { meMarker.remove(); meMarker = null; }
        toast("GPS perangkat dikembalikan ke lokasi asli.", "ok");
      } catch (e) { fail(e); }
    };

    // Rute
    $("btnClearWp").onclick = () => { waypoints = []; renderWaypoints(); };
    $("btnUndoWp").onclick = () => { waypoints.pop(); renderWaypoints(); };

    $("btnRouteStart").onclick = async () => {
      if (waypoints.length < 2) return toast("Butuh minimal dua titik.", "err");
      try {
        applyStatus(await api("/api/route/start", {
          points: waypoints,
          speed_kmh: +$("spdRange").value,
          loop_mode: $("loopSel").value,
        }));
        toast("Rute dimulai.", "ok");
      } catch (e) { fail(e); }
    };

    $("btnRoutePause").onclick = async () => {
      const endpoint = (last && last.paused) ? "/api/route/resume" : "/api/route/pause";
      try { applyStatus(await api(endpoint, {})); } catch (e) { fail(e); }
    };

    $("btnSaveRoute").onclick = async () => {
      if (waypoints.length < 2) return toast("Butuh minimal dua titik.", "err");
      const name = prompt("Nama rute ini?", "");
      if (name === null) return;
      try {
        await api("/api/favorites/route", { name, points: waypoints });
        toast("Rute tersimpan.", "ok");
      } catch (e) { fail(e); }
    };

    $("spdRange").oninput = (e) => {
      $("spdVal").textContent = e.target.value + " km/j";
      if (last && last.mode === "route") api("/api/speed", { speed_kmh: +e.target.value }).catch(() => {});
    };
    $("stickMax").oninput = (e) => { $("stickMaxVal").textContent = e.target.value + " km/j"; };

    $("pushRange").oninput = (e) => {
      $("pushVal").textContent = (+e.target.value).toFixed(2).replace(/0$/, "") + " d";
      api("/api/settings", { push_interval: +e.target.value }).catch(() => {});
    };
    $("jitRange").oninput = (e) => {
      $("jitVal").textContent = e.target.value + " m";
      api("/api/settings", { jitter_m: +e.target.value }).catch(() => {});
    };

    // GPX
    $("btnGpxImport").onclick = () => $("gpxFile").click();
    $("gpxFile").onchange = async (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      try {
        const text = await file.text();
        const res = await api("/api/gpx/import", { gpx: text });
        waypoints = res.points;
        renderWaypoints();
        switchTab("rute");
        if (map && waypoints.length) {
          map.fitBounds(waypoints.map((p) => [p.lat, p.lon]), { padding: [40, 40] });
        }
        toast(`${res.points.length} titik dimuat (${fmtDist(res.length_m)}).`, "ok");
      } catch (err) { fail(err); }
      e.target.value = "";
    };

    $("gpxFlavor").onchange = (e) => {
      $("gpxHint").textContent = e.target.value === "xcode"
        ? "Xcode hanya membaca tag wpt dan menyimpulkan kecepatan dari selisih waktu, "
          + "jadi kecepatan di atas ikut tertulis ke berkasnya."
        : "Bentuk GPX yang dipahami hampir semua aplikasi.";
    };

    $("btnGpxExport").onclick = async () => {
      const pts = waypoints.length > 1 ? waypoints : (last && last.route) || [];
      if (pts.length < 2) return toast("Tidak ada rute untuk diekspor.", "err");
      const flavor = $("gpxFlavor").value;
      try {
        const res = await api("/api/gpx/export", {
          points: pts,
          name: "Rute Titik",
          flavor,
          speed_kmh: +$("spdRange").value,
        });
        download(flavor === "xcode" ? "rute-titik-xcode.gpx" : "rute-titik.gpx", res.gpx);
        if (flavor === "xcode") {
          toast("Tersimpan. Di Xcode: Product > Scheme > Edit Scheme > Run > "
                + "Options > Allow Location Simulation, lalu pilih berkas ini.", "ok");
        }
      } catch (e) { fail(e); }
    };
  }

  // -------------------------------------------------------------- mulai
  document.addEventListener("DOMContentLoaded", () => {
    initMap();
    setupStick();
    wire();
    renderWaypoints();
    poll().then(() => { if (last && last.position && map) map.setView([last.position.lat, last.position.lon], 15); });
    setInterval(poll, 700);
  });
})();
