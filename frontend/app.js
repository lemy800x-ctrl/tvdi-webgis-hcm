"use strict";

/* =========================================================
   1. HẰNG SỐ VÀ MÀU SẮC TVDI
   ========================================================= */

const PALETTE = [
  "#066b00", "#0bc400", "#0ce100", "#00ff00",
  "#ffff00", "#ffcc00", "#ff6600", "#ff0000"
];

const NODATA = "#9aa7b3";

const LEVELS = [
  { label: "Rất ẩm", mid: 0.1 },
  { label: "Ẩm", mid: 0.3 },
  { label: "Trung bình", mid: 0.5 },
  { label: "Khô", mid: 0.7 },
  { label: "Rất khô", mid: 0.9 }
];

const MONTH_NAMES = [
  "T1","T2","T3","T4","T5","T6",
  "T7","T8","T9","T10","T11","T12"
];

/* =========================================================
   2. TIỆN ÍCH
   ========================================================= */

const $ = (id) => document.getElementById(id);

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function colorFor(v) {
  if (v === null || v === undefined || v === "" || !Number.isFinite(Number(v))) {
    return NODATA;
  }
  const val = Math.min(Math.max(Number(v), 0), 1);
  const t = val * (PALETTE.length - 1);
  const i = Math.min(Math.floor(t), PALETTE.length - 2);
  const f = t - i;
  const a = hexToRgb(PALETTE[i]);
  const b = hexToRgb(PALETTE[i + 1]);
  const c = a.map((x, k) => Math.round(x + (b[k] - x) * f));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

function fmt(v, d = 2) {
  if (v === null || v === undefined || v === "" || !Number.isFinite(Number(v))) return "-";
  return Number(v).toLocaleString("vi-VN", {
    minimumFractionDigits: d, maximumFractionDigits: d
  });
}

function periodText(p) {
  return `Tháng ${p.thang}/${p.nam}`;
}

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(props).forEach(([k, v]) => {
    if (k === "text") node.textContent = v;
    else if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  });
  children.forEach((child) => node.append(child));
  return node;
}

function getLevelLabel(val) {
  if (val === null || val === undefined) return "Chưa có";
  if (val < 0.2) return "Rất ẩm";
  if (val < 0.4) return "Ẩm";
  if (val < 0.6) return "Trung bình";
  if (val < 0.8) return "Khô";
  return "Rất khô";
}

// Gửi JWT Token qua Authorization Header
function adminHeaders() {
  const token = sessionStorage.getItem("admin_token");
  return token ? { "Authorization": `Bearer ${token}` } : {};
}

function isAdmin() {
  return !!sessionStorage.getItem("admin_token");
}

// Hàm gọi API có tự động xử lý lỗi 401 (Token hết hạn)
async function api(path, options = {}) {
  const opts = { ...options };
  opts.headers = { ...(opts.headers || {}), ...adminHeaders() };
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw new Error("Không kết nối được máy chủ. Kiểm tra backend đã chạy chưa.");
  }
  
  if (!res.ok) {
    // FIX LỖI 2: Nếu Token hết hạn (401), tự động xóa và đăng xuất
    if (res.status === 401) {
      if (sessionStorage.getItem("admin_token")) {
        sessionStorage.removeItem("admin_token");
        if (typeof refreshAuthUI === "function") refreshAuthUI();
      }
    }
    
    let detail = `Lỗi ${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

/* =========================================================
   3. TRẠNG THÁI ỨNG DỤNG
   ========================================================= */

const state = {
  periods: [],
  idx: 0,
  wardCode: null,
  wardSeries: null,
  live: [],
  map: null,
  layer: null,
  fitted: false,
  wardChart: null,
  edgeChart: null,
  animationTimer: null,
};

/* =========================================================
   4. BẢN ĐỒ LEAFLET
   ========================================================= */

function initMap() {
  state.map = L.map("map", { zoomControl: true }).setView([10.85, 106.75], 9);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19
  }).addTo(state.map);

  state.map.on("mousemove", (e) => {
    const { lat, lng } = e.latlng;
    if ($("map-coordinate")) {
      $("map-coordinate").textContent = `Tọa độ: ${lat.toFixed(5)}°N, ${lng.toFixed(5)}°E`;
    }
  });
  state.map.on("mouseout", () => {
    if ($("map-coordinate")) {
      $("map-coordinate").textContent = "Tọa độ: di chuyển con trỏ trên bản đồ";
    }
  });
}

function wardStyle(feature) {
  const p = feature.properties || {};
  const selected = p.ward_code === state.wardCode;
  return {
    fillColor: colorFor(p.tvdi_mean),
    fillOpacity: 0.82,
    color: selected ? "#1b2a38" : "#ffffff",
    weight: selected ? 2.5 : 0.7
  };
}

function renderMap(geojson) {
  if (state.layer) state.layer.remove();

  state.layer = L.geoJSON(geojson, {
    style: wardStyle,
    onEachFeature(feature, layer) {
      const p = feature.properties || {};
      const name = p.ward_name || p.fullname || p.name || "Chưa xác định";
      const value = p.tvdi_mean;
      const noData = value === null || value === undefined || value === "" || !Number.isFinite(Number(value));

      const tip = el("div", {}, [
        el("b", { text: name }),
        el("div", {
          text: noData ? "Không có dữ liệu" : `TVDI ${fmt(value)} — ${p.level_label || ""}`
        }),
        el("div", {
          text: `LST ${fmt(p.lst_mean)} · NDVI ${fmt(p.ndvi_mean)}`
        })
      ]);

      layer.bindTooltip(tip, { sticky: true, className: "ward-tip" });
      layer.on("click", () => selectWard(p.ward_code));
    }
  }).addTo(state.map);

  if (!state.fitted && geojson.features && geojson.features.length) {
    state.map.fitBounds(state.layer.getBounds(), { padding: [20, 20] });
    state.fitted = true;
  }
}

/* =========================================================
   5. THANH THỜI GIAN
   ========================================================= */

function buildStrip() {
  const strip = $("strip");
  if (!strip) return;
  strip.replaceChildren();

  const byYear = new Map();
  state.periods.forEach((p, i) => {
    if (!byYear.has(p.nam)) byYear.set(p.nam, []);
    byYear.get(p.nam).push([p, i]);
  });

  byYear.forEach((items, year) => {
    const cells = el("div", { class: "cells" });
    items.forEach(([p, i]) => {
      const isForecast = p.nam >= 2026;
      const cell = el("button", {
        type: "button",
        class: "cell" + (isForecast ? " forecast" : ""),
        "data-i": String(i),
        "aria-label": `${MONTH_NAMES[p.thang - 1]}/${p.nam}, ${isForecast ? "dự báo" : "thực tế"}, TVDI ${fmt(p.tvdi_mean)}`,
        tabindex: "-1"
      });
      cell.style.background = colorFor(p.tvdi_mean);
      cell.title = `${periodText(p)} — ${isForecast ? "Dự báo AI" : "Thực tế"} — TVDI ${fmt(p.tvdi_mean)}`;
      cells.append(cell);
    });
    strip.append(el("div", { class: "year" }, [
      el("div", { class: "year-label", text: String(year) }),
      cells
    ]));
  });

  strip.setAttribute("aria-valuemax", String(state.periods.length - 1));
}

function markActiveCell() {
  document.querySelectorAll(".cell.active").forEach((c) => c.classList.remove("active"));
  const cell = document.querySelector(`.cell[data-i="${state.idx}"]`);
  if (cell) {
    cell.classList.add("active");
    cell.scrollIntoView({ block: "nearest", inline: "center" });
  }
  const p = state.periods[state.idx];
  if (p && $("strip")) {
    $("strip").setAttribute("aria-valuenow", String(state.idx));
    $("strip").setAttribute("aria-valuetext", `${periodText(p)}, ${p.nam >= 2026 ? "dự báo" : "thực tế"}`);
  }
}

function setupStripEvents() {
  if ($("strip")) {
    $("strip").addEventListener("click", (e) => {
      const cell = e.target.closest(".cell");
      if (cell) {
        stopAnimation();
        goTo(Number(cell.dataset.i));
      }
    });
  }
}

/* =========================================================
   6. TẢI DỮ LIỆU THEO THÁNG
   ========================================================= */

let loadToken = 0;

async function goTo(i) {
  const p = state.periods[i];
  if (!p) return;

  state.idx = i;
  markActiveCell();

  const token = ++loadToken;
  const q = `nam=${p.nam}&thang=${p.thang}&loai=${encodeURIComponent(p.loai || "thuc_te")}`;

  try {
    const [geo, sum] = await Promise.all([
      api(`/api/map?${q}`),
      api(`/api/summary?${q}`)
    ]);
    if (token !== loadToken) return;

    renderMap(geo);
    renderSummary(p, sum);
    if ($("empty")) $("empty").hidden = true;

    loadRanking().catch(() => {});
  } catch (err) {
    showNotice(err.message);
  }
}

function showNotice(msg) {
  const notice = $("empty");
  if (!notice) { console.error(msg); return; }
  notice.textContent = msg;
  notice.hidden = false;
}

/* =========================================================
   7. THỐNG KÊ TỔNG QUAN
   ========================================================= */

function renderSummary(p, sum) {
  if ($("period-title")) $("period-title").textContent = periodText(p);
  const isForecast = p.nam >= 2026;
  const badge = $("period-badge");
  if (badge) {
    badge.textContent = isForecast ? "Dự báo AI" : "Thực tế";
    badge.className = "badge" + (isForecast ? " forecast" : "");
  }
  if ($("strip-caption")) {
    $("strip-caption").textContent = `${periodText(p)} — ${isForecast ? "dự báo bằng AI" : "tính từ ảnh vệ tinh"}`;
  }

  if ($("mean-value")) $("mean-value").textContent = fmt(sum.mean);
  if ($("mean-label")) {
    $("mean-label").textContent = sum.level_label
      ? `TVDI trung bình, mức ${sum.level_label.toLowerCase()}`
      : "Chưa có dữ liệu";
  }

  const classes = sum.classes || [];
  const total = classes.reduce((a, c) => a + Number(c.count || 0), 0) || 1;

  const bar = $("class-bar");
  if (bar) bar.replaceChildren();
  const list = $("class-list");
  if (list) list.replaceChildren();

  classes.forEach((c) => {
    const level = LEVELS[c.level];
    const color = level ? colorFor(level.mid) : NODATA;
    if (bar) {
      const segment = el("span");
      segment.style.width = `${(Number(c.count || 0) / total) * 100}%`;
      segment.style.background = color;
      bar.append(segment);
    }
    if (list) {
      const swatch = el("i");
      swatch.style.background = color;
      list.append(el("li", {}, [
        swatch,
        el("span", { text: c.label }),
        el("b", { text: `${c.count} phường/xã` })
      ]));
    }
  });

  const driest = $("driest-list");
  if (driest) {
    driest.replaceChildren();
    (sum.driest || []).forEach((d, k) => {
      const btn = el("button", { type: "button" }, [
        el("span", { class: "rank", text: String(k + 1) }),
        el("span", { class: "w-name", text: d.ward_name }),
        el("span", { class: "w-val", text: fmt(d.tvdi_mean) })
      ]);
      btn.addEventListener("click", () => selectWard(d.ward_code, true));
      driest.append(el("li", {}, [btn]));
    });
  }
}

/* =========================================================
   8. CHI TIẾT PHƯỜNG/XÃ
   ========================================================= */

async function selectWard(code, zoom = false) {
  if (!code) return;

  state.wardCode = code;
  state.live = [];
  if ($("predict-result")) $("predict-result").replaceChildren();

  if (state.layer) {
    state.layer.eachLayer((layer) => {
      layer.setStyle(wardStyle(layer.feature));
      if (zoom && layer.feature.properties.ward_code === code) {
        state.map.fitBounds(layer.getBounds(), { maxZoom: 13 });
      }
    });
  }

  try {
    const data = await api(`/api/ward/${encodeURIComponent(code)}/series`);
    if (state.wardCode !== code) return;

    state.wardSeries = data;
    if ($("ward-block")) $("ward-block").hidden = false;
    if ($("ward-name")) $("ward-name").textContent = data.ward.name;
    if ($("ward-meta")) {
      $("ward-meta").textContent = data.ward.area_km2
        ? `Diện tích ${fmt(data.ward.area_km2, 1)} km²`
        : "";
    }

    renderWardChart();

    // Hiện nút bấm CHẠY AI nếu là Admin
    const predictBtn = $("predict-btn");
    if (predictBtn) predictBtn.hidden = !isAdmin();

    // Tự động hiển thị bảng dự báo (nếu có sẵn trong CSDL) cho MỌI NGƯỜI
    loadExistingForecast();
  } catch (err) {
    showNotice(err.message);
  }
}

// Hàm tải bảng dự báo có sẵn cho tất cả người dùng
function loadExistingForecast() {
  const out = $("predict-result");
  if (!out) return;
  out.replaceChildren();

  // Lấy dữ liệu dự báo (năm >= 2026) từ state.wardSeries
  if (!state.wardSeries || !state.wardSeries.series) return;
  
  const forecasts = state.wardSeries.series.filter(s => s.nam >= 2026);

  if (forecasts.length > 0) {
    const tbody = el("tbody");
    forecasts.forEach((p) => {
      tbody.append(el("tr", {}, [
        el("td", { text: `${String(p.thang).padStart(2, "0")}/${p.nam}` }),
        el("td", { text: fmt(p.tvdi_mean) }),
        el("td", { text: getLevelLabel(p.tvdi_mean) })
      ]));
    });

    out.append(
      el("p", { text: "Kết quả dự báo 6 tháng tới (từ CSDL):" }),
      el("table", {}, [
        el("thead", {}, [el("tr", {}, [
          el("th", { text: "Tháng" }),
          el("th", { text: "TVDI" }),
          el("th", { text: "Mức độ" })
        ])]),
        tbody
      ])
    );
  }
}

/* =========================================================
   9. BIỂU ĐỒ TVDI CỦA PHƯỜNG/XÃ
   ========================================================= */

function renderWardChart() {
  if (!state.wardSeries) return;

  const series = state.wardSeries.series || [];
  const label = (nam, thang) => `${String(thang).padStart(2, "0")}/${nam}`;
  const key = (nam, thang) => nam * 12 + thang;

  const months = new Map();
  series.forEach((s) => months.set(key(s.nam, s.thang), { nam: s.nam, thang: s.thang }));
  state.live.forEach((s) => months.set(key(s.nam, s.thang), { nam: s.nam, thang: s.thang }));

  const order = [...months.keys()].sort((a, b) => a - b);

  const pick = (loai) =>
    order.map((k) => {
      const m = months.get(k);
      const found = series.find((s) =>
        ((loai === "thuc_te" && s.nam < 2026) || (loai === "du_bao" && s.nam >= 2026)) &&
        s.nam === m.nam && s.thang === m.thang
      );
      return found ? found.tvdi_mean : null;
    });

  const actual = pick("thuc_te");
  const forecast = order.map((k) => {
    const m = months.get(k);
    const fromPrediction = state.live.find((s) => s.nam === m.nam && s.thang === m.thang);
    if (fromPrediction) return fromPrediction.tvdi_du_bao ?? fromPrediction.tvdi_mean ?? null;
    const fromSeries = series.find((s) => s.nam >= 2026 && s.nam === m.nam && s.thang === m.thang);
    return fromSeries ? fromSeries.tvdi_mean : null;
  });

  if (state.wardChart) state.wardChart.destroy();

  const chartCanvas = $("ward-chart");
  if (!chartCanvas) return;

  state.wardChart = new Chart(chartCanvas, {
    type: "line",
    data: {
      labels: order.map((k) => { const m = months.get(k); return label(m.nam, m.thang); }),
      datasets: [
        {
          label: "Thực tế", data: actual,
          borderColor: "#1b2a38", borderWidth: 1.5,
          pointRadius: 0, tension: 0.25
        },
        {
          label: "Dự báo AI", data: forecast,
          borderColor: "#0e6b8c", borderDash: [5, 4],
          borderWidth: 2, pointRadius: 2, tension: 0.25
        }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        y: { min: 0, max: 1, title: { display: true, text: "TVDI" } },
        x: { ticks: { maxTicksLimit: 10 } }
      },
      plugins: { legend: { position: "bottom", labels: { boxWidth: 14 } } }
    }
  });
}

/* =========================================================
   10. DỰ BÁO (ADMIN ONLY)
   ========================================================= */

async function runPredict() {
  if (!state.wardCode) return;
  if (!isAdmin()) {
    showNotice("Chỉ admin mới được chạy dự báo AI.");
    return;
  }

  const btn = $("predict-btn");
  const out = $("predict-result");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Đang dự báo...";
  }
  if (out) out.replaceChildren();

  try {
    const res = await api("/api/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ward_code: state.wardCode, horizon: 6 })
    });

    state.live = res.predictions || [];
    renderWardChart();

    // Cập nhật lại bảng dự báo (gọi selectWard để reload dữ liệu mới)
    await selectWard(state.wardCode, false);
    
    if (out && out.children.length === 0) {
      // Nếu chưa có dữ liệu trong CSDL, hiển thị tạm kết quả vừa dự báo
      const tbody = el("tbody");
      state.live.forEach((p) => {
        tbody.append(el("tr", {}, [
          el("td", { text: `${String(p.thang).padStart(2, "0")}/${p.nam}` }),
          el("td", { text: fmt(p.tvdi_du_bao) }),
          el("td", { text: p.level_label || "Chưa phân loại" })
        ]));
      });

      out.append(
        el("p", { text: "AI đã hoàn thành dự báo cho 6 tháng tiếp theo." }),
        el("table", {}, [
          el("thead", {}, [el("tr", {}, [
            el("th", { text: "Tháng" }),
            el("th", { text: "TVDI" }),
            el("th", { text: "Mức độ" })
          ])]),
          tbody
        ])
      );
    }
  } catch (err) {
    if (out) out.append(el("p", { class: "error", text: err.message }));
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Dự báo 6 tháng tới bằng AI";
    }
  }
}

/* =========================================================
   11. XẾP HẠNG + LỌC NGƯỠNG
   ========================================================= */

async function loadRanking() {
  const rankingSelect = $("ranking-metric");
  if (!rankingSelect) return;
  const metric = rankingSelect.value;
  const p = state.periods[state.idx];
  if (!p) return;

  const q = `nam=${p.nam}&thang=${p.thang}&loai=${encodeURIComponent(p.loai || "thuc_te")}&metric=${metric}`;
  try {
    const data = await api(`/api/ward-ranking?${q}`);
    renderRankingTable(data.items, metric);
    if ($("ward-tools-status")) {
      $("ward-tools-status").textContent = `${data.count} phường/xã (xếp theo ${metric.toUpperCase()}).`;
    }
  } catch (err) {
    if ($("ward-tools-status")) {
      $("ward-tools-status").textContent = `Lỗi xếp hạng: ${err.message}`;
    }
  }
}

function renderRankingTable(items, metric) {
  const tbody = $("ward-ranking-body");
  if (!tbody) return;
  tbody.replaceChildren();

  if ($("ranking-value-heading")) {
    $("ranking-value-heading").textContent =
      metric === "lst" ? "LST (°C)" : metric === "ndvi" ? "NDVI" : "TVDI";
  }

  if (!items || !items.length) {
    tbody.append(el("tr", {}, [el("td", { colspan: "3", text: "Không có dữ liệu." })]));
    return;
  }

  items.forEach((it, i) => {
    const tr = el("tr", {}, [
      el("td", { text: String(i + 1) }),
      el("td", { text: it.ward_name }),
      el("td", { text: fmt(it.value), style: "text-align: right; font-weight: 600;" })
    ]);
    tr.style.cursor = "pointer";
    tr.addEventListener("click", () => selectWard(it.ward_code, true));
    tbody.append(tr);
  });
}

async function applyWardFilter() {
  const p = state.periods[state.idx];
  if (!p) return;

  const body = {
    metric: $("filter-metric").value,
    operator: $("filter-operator").value,
    value: Number($("filter-value").value),
    value_max: $("filter-max-wrap").hidden ? null : Number($("filter-max-value").value)
  };

  const status = $("ward-tools-status");

  if (!Number.isFinite(body.value)) {
    if (status) status.textContent = "Vui lòng nhập ngưỡng hợp lệ.";
    return;
  }

  const q = `nam=${p.nam}&thang=${p.thang}&loai=${encodeURIComponent(p.loai || "thuc_te")}`;
  try {
    const data = await api(`/api/ward-filter?${q}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    renderRankingTable(data.items, body.metric);
    if (status) {
      status.textContent = `Khớp ${data.count} phường/xã với điều kiện ${body.metric.toUpperCase()} ${body.operator} ${body.value}${body.value_max != null ? " – " + body.value_max : ""}.`;
    }
  } catch (err) {
    if (status) status.textContent = `Lỗi lọc: ${err.message}`;
  }
}

function setupWardTools() {
  $("apply-ward-filter-btn")?.addEventListener("click", applyWardFilter);
  $("reset-ward-filter-btn")?.addEventListener("click", () => {
    if ($("filter-value")) $("filter-value").value = "";
    if ($("filter-max-value")) $("filter-max-value").value = "";
    loadRanking();
  });
  $("refresh-ranking-btn")?.addEventListener("click", loadRanking);
  $("ranking-metric")?.addEventListener("change", loadRanking);
  $("filter-operator")?.addEventListener("change", () => {
    const maxWrap = $("filter-max-wrap");
    if (maxWrap) maxWrap.hidden = $("filter-operator").value !== "between";
  });
}

/* =========================================================
   12. ANIMATION + 2D/3D
   ========================================================= */

function startAnimation() {
  if (state.animationTimer) return;
  const speed = Number($("animation-speed").value) || 1000;
  if ($("animation-play-btn")) $("animation-play-btn").disabled = true;
  state.animationTimer = setInterval(() => {
    const next = (state.idx + 1) % state.periods.length;
    goTo(next);
  }, speed);
}

function stopAnimation() {
  if (state.animationTimer) {
    clearInterval(state.animationTimer);
    state.animationTimer = null;
  }
  if ($("animation-play-btn")) $("animation-play-btn").disabled = false;
}

function setupMapTools() {
  $("animation-play-btn")?.addEventListener("click", startAnimation);
  $("animation-stop-btn")?.addEventListener("click", stopAnimation);

  $("view-2d-btn")?.addEventListener("click", () => {
    $("map").classList.remove("view-3d");
    $("view-2d-btn").setAttribute("aria-pressed", "true");
    $("view-3d-btn").setAttribute("aria-pressed", "false");
  });
  $("view-3d-btn")?.addEventListener("click", () => {
    $("map").classList.add("view-3d");
    $("view-3d-btn").setAttribute("aria-pressed", "true");
    $("view-2d-btn").setAttribute("aria-pressed", "false");
  });
}

/* =========================================================
   13. ADMIN LOGIN (JWT Token)
   ========================================================= */

function refreshAuthUI() {
  const admin = isAdmin();
  if ($("auth-status")) {
    $("auth-status").textContent = admin
      ? "Chế độ: Quản trị viên (toàn quyền)"
      : "Chế độ: Người dùng (chỉ xem)";
  }
  const btn = $("admin-toggle-btn");
  if (btn) {
    btn.textContent = admin ? "🔓 Đăng xuất" : "🔑 Admin";
    btn.title = admin ? "Đăng xuất admin" : "Đăng nhập admin";
  }
  if ($("predict-btn")) $("predict-btn").hidden = !admin;
}

async function setupAdminLogin() {
  const adminBtn = $("admin-toggle-btn");
  const authStatus = $("auth-status");
  
  // Hàm xử lý chung khi bấm đăng nhập/đăng xuất
  const handleAuthClick = async () => {
    if (isAdmin()) {
      sessionStorage.removeItem("admin_token");
      refreshAuthUI();
      return;
    }
    
    const password = window.prompt("Nhập mật khẩu Admin:");
    if (!password) return;

    try {
      const res = await fetch("/api/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: password })
      });
      
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Mật khẩu sai");
      }
      
      const data = await res.json();
      sessionStorage.setItem("admin_token", data.token);
      refreshAuthUI();
      alert("Đăng nhập Admin thành công!");
      
    } catch (err) {
      alert("Lỗi đăng nhập: " + err.message);
    }
  };

  // Gán sự kiện cho nút Admin
  if (adminBtn) {
    adminBtn.addEventListener("click", handleAuthClick);
  }
  
  // FIX LỖI 1: Gán sự kiện click cho cả dòng chữ trạng thái
  if (authStatus) {
    authStatus.style.cursor = "pointer"; // Đổi con trỏ chuột
    authStatus.style.textDecoration = "underline"; // Gạch chân để giống link
    authStatus.title = "Bấm để đăng nhập/đăng xuất Admin";
    authStatus.addEventListener("click", handleAuthClick);
  }
}

/* =========================================================
   14. PANEL MÔ HÌNH
   ========================================================= */

function setupTabs() {
  const tabArea = $("tab-area");
  const tabModel = $("tab-model");
  const panelArea = $("panel-area");
  const panelModel = $("panel-model");

  if (tabArea && tabModel && panelArea && panelModel) {
    tabArea.addEventListener("click", () => {
      tabArea.setAttribute("aria-selected", "true");
      tabModel.setAttribute("aria-selected", "false");
      panelArea.hidden = false;
      panelModel.hidden = true;
    });
    tabModel.addEventListener("click", () => {
      tabModel.setAttribute("aria-selected", "true");
      tabArea.setAttribute("aria-selected", "false");
      panelModel.hidden = false;
      panelArea.hidden = true;
      loadModelData();
    });
  }
}

async function loadModelData() {
  try {
    const models = await api("/api/models");
    const tbody = $("model-table-body");
    if (tbody) {
      tbody.replaceChildren();
      models.forEach((m) => {
        tbody.append(el("tr", {}, [
          el("td", { text: m.mo_hinh }),
          el("td", { text: fmt(m.mae, 3) }),
          el("td", { text: fmt(m.rmse, 3) }),
          el("td", { text: fmt(m.r2, 3) }),
          el("td", { text: fmt(m.mape, 1) })
        ]));
      });
    }
  } catch (err) {
    console.error("Lỗi tải bảng mô hình:", err);
  }

  try {
    const edgeData = await api("/api/edge-r2");
    renderEdgeChart(edgeData);
  } catch (err) {
    console.error("Lỗi tải thông số đường cạnh:", err);
  }
}

function renderEdgeChart(edgeData) {
  const canvas = $("edge-chart");
  if (!canvas) return;

  if (state.edgeChart) state.edgeChart.destroy();

  state.edgeChart = new Chart(canvas, {
    type: "bar",
    data: {
      labels: edgeData.map((d) => `Tháng ${d.thang}`),
      datasets: [
        { label: "R² Cạnh khô", data: edgeData.map((d) => d.r2_dry), backgroundColor: "#ff6600" },
        { label: "R² Cạnh ướt", data: edgeData.map((d) => d.r2_wet), backgroundColor: "#0bc400" }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { y: { min: 0, max: 1 } }
    }
  });
}

/* =========================================================
   15. CHÚ THÍCH BẢN ĐỒ
   ========================================================= */

function drawLegend() {
  const bar = $("legend-bar");
  if (bar) {
    const stops = PALETTE.map((color, i) =>
      `${color} ${(i / (PALETTE.length - 1)) * 100}%`
    ).join(", ");
    bar.style.background = `linear-gradient(to right, ${stops})`;
  }
}

/* =========================================================
   16. KHỞI TẠO ỨNG DỤNG
   ========================================================= */

async function init() {
  drawLegend();
  initMap();
  setupTabs();
  setupStripEvents();
  setupMapTools();
  setupWardTools();
  setupAdminLogin();
  refreshAuthUI();

  if ($("predict-btn")) {
    $("predict-btn").addEventListener("click", runPredict);
  }

  try {
    state.periods = await api("/api/city-series");
  } catch (err) {
    showNotice(err.message);
    return;
  }

  buildStrip();
  if (state.periods.length > 0) {
    await goTo(state.periods.length - 1);
  }
}

init();