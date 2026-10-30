"use strict";

/* =========================================================
   1. HẰNG SỐ VÀ MÀU SẮC TVDI
   ========================================================= */

const PALETTE = [
  "#066b00",
  "#0bc400",
  "#0ce100",
  "#00ff00",
  "#ffff00",
  "#ffcc00",
  "#ff6600",
  "#ff0000"
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
  "T1", "T2", "T3", "T4", "T5", "T6",
  "T7", "T8", "T9", "T10", "T11", "T12"
];

/* =========================================================
   2. TIỆN ÍCH
   ========================================================= */

const $ = (id) => document.getElementById(id);

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [
    (n >> 16) & 255,
    (n >> 8) & 255,
    n & 255
  ];
}

function colorFor(v) {
  if (
    v === null ||
    v === undefined ||
    v === "" ||
    !Number.isFinite(Number(v))
  ) {
    return NODATA;
  }

  const val = Math.min(Math.max(Number(v), 0), 1);
  const t = val * (PALETTE.length - 1);

  const i = Math.min(
    Math.floor(t),
    PALETTE.length - 2
  );

  const f = t - i;
  const a = hexToRgb(PALETTE[i]);
  const b = hexToRgb(PALETTE[i + 1]);

  const c = a.map((x, k) =>
    Math.round(x + (b[k] - x) * f)
  );

  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

function fmt(v, d = 2) {
  if (
    v === null ||
    v === undefined ||
    v === "" ||
    !Number.isFinite(Number(v))
  ) {
    return "-";
  }

  return Number(v).toLocaleString("vi-VN", {
    minimumFractionDigits: d,
    maximumFractionDigits: d
  });
}

function periodText(p) {
  return `Tháng ${p.thang}/${p.nam}`;
}

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);

  Object.entries(props).forEach(([k, v]) => {
    if (k === "text") {
      node.textContent = v;
    } else if (k === "class") {
      node.className = v;
    } else {
      node.setAttribute(k, v);
    }
  });

  children.forEach((child) => node.append(child));

  return node;
}

async function api(path, options) {
  let res;

  try {
    res = await fetch(path, options);
  } catch (e) {
    throw new Error(
      "Không kết nối được máy chủ. Hãy kiểm tra backend đã chạy chưa."
    );
  }

  if (!res.ok) {
    let detail = `Lỗi ${res.status}`;

    try {
      detail = (await res.json()).detail || detail;
    } catch (_) {
      // Giữ thông báo lỗi mặc định.
    }

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
  edgeChart: null
};

/* =========================================================
   4. BẢN ĐỒ LEAFLET
   ========================================================= */

function initMap() {
  state.map = L.map("map", {
    zoomControl: true
  }).setView([10.85, 106.75], 9);

  L.tileLayer(
    "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19
    }
  ).addTo(state.map);
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
  if (state.layer) {
    state.layer.remove();
  }

  state.layer = L.geoJSON(geojson, {
    style: wardStyle,

    onEachFeature(feature, layer) {
      const p = feature.properties || {};

      const name =
        p.ward_name ||
        p.fullname ||
        p.name ||
        "Chưa xác định";

      const value = p.tvdi_mean;

      const noData =
        value === null ||
        value === undefined ||
        value === "" ||
        !Number.isFinite(Number(value));

      const tip = el("div", {}, [
        el("b", { text: name }),

        el("div", {
          text: noData
            ? "Không có dữ liệu"
            : `TVDI ${fmt(value)} - ${p.level_label || ""}`
        })
      ]);

      layer.bindTooltip(tip, {
        sticky: true,
        className: "ward-tip"
      });

      layer.on("click", () => {
        selectWard(p.ward_code);
      });
    }
  }).addTo(state.map);

  if (!state.fitted && geojson.features.length) {
    state.map.fitBounds(
      state.layer.getBounds(),
      { padding: [20, 20] }
    );

    state.fitted = true;
  }
}

/* =========================================================
   5. THANH THỜI GIAN TIMELINE
   ========================================================= */

function buildStrip() {
  const strip = $("strip");

  strip.replaceChildren();

  const byYear = new Map();

  state.periods.forEach((p, i) => {
    if (!byYear.has(p.nam)) {
      byYear.set(p.nam, []);
    }

    byYear.get(p.nam).push([p, i]);
  });

  byYear.forEach((items, year) => {
    const cells = el("div", {
      class: "cells"
    });

    items.forEach(([p, i]) => {
      // ĐÃ FIX: CHỈ NĂM >= 2026 MỚI LÀ DỰ BÁO (SỌC CARO), NĂM 2016-2025 LUÔN LÀ THỰC TẾ
      const isForecast = p.nam >= 2026;

      const cell = el("button", {
        type: "button",
        class: "cell" + (isForecast ? " forecast" : ""),
        "data-i": String(i),
        "aria-label":
          `${MONTH_NAMES[p.thang - 1]}/${p.nam}, ` +
          `${isForecast ? "dự báo" : "thực tế"}, ` +
          `TVDI ${fmt(p.tvdi_mean)}`,
        tabindex: "-1"
      });

      cell.style.background = colorFor(p.tvdi_mean);

      cell.title =
        `${periodText(p)} - ` +
        `${isForecast ? "Dự báo AI" : "Thực tế"} - ` +
        `TVDI ${fmt(p.tvdi_mean)}`;

      cells.append(cell);
    });

    strip.append(
      el("div", {
        class: "year"
      }, [
        el("div", {
          class: "year-label",
          text: String(year)
        }),
        cells
      ])
    );
  });

  strip.setAttribute(
    "aria-valuemax",
    String(state.periods.length - 1)
  );
}

function markActiveCell() {
  document
    .querySelectorAll(".cell.active")
    .forEach((cell) => cell.classList.remove("active"));

  const cell = document.querySelector(
    `.cell[data-i="${state.idx}"]`
  );

  if (cell) {
    cell.classList.add("active");

    cell.scrollIntoView({
      block: "nearest",
      inline: "center"
    });
  }

  const p = state.periods[state.idx];

  if (p) {
    const isForecast = p.nam >= 2026;

    $("strip").setAttribute(
      "aria-valuenow",
      String(state.idx)
    );

    $("strip").setAttribute(
      "aria-valuetext",
      `${periodText(p)}, ${
        isForecast ? "dự báo" : "thực tế"
      }`
    );
  }
}

function setupStripEvents() {
  const strip = $("strip");

  strip.addEventListener("click", (e) => {
    const cell = e.target.closest(".cell");

    if (cell) {
      goTo(Number(cell.dataset.i));
    }
  });
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

  const q =
    `nam=${p.nam}&thang=${p.thang}` +
    `&loai=${encodeURIComponent(p.loai || "thuc_te")}`;

  try {
    const [geo, sum] = await Promise.all([
      api(`/api/map?${q}`),
      api(`/api/summary?${q}`)
    ]);

    if (token !== loadToken) return;

    renderMap(geo);
    renderSummary(p, sum);

    $("empty").hidden = true;
  } catch (err) {
    showNotice(err.message);
  }
}

function showNotice(msg) {
  const notice = $("empty");

  if (!notice) {
    console.error(msg);
    return;
  }

  notice.textContent = msg;
  notice.hidden = false;
}

/* =========================================================
   7. THỐNG KÊ TỔNG QUAN
   ========================================================= */

function renderSummary(p, sum) {
  $("period-title").textContent = periodText(p);

  // ĐÃ FIX: CHỈ NĂM >= 2026 MỚI HIỂN THỊ BADGE DỰ BÁO AI
  const isForecast = p.nam >= 2026;

  const badge = $("period-badge");

  badge.textContent = isForecast ? "Dự báo AI" : "Thực tế";

  badge.className =
    "badge" + (isForecast ? " forecast" : "");

  $("strip-caption").textContent =
    `${periodText(p)} - ${
      isForecast
        ? "dự báo bằng AI"
        : "tính từ ảnh vệ tinh"
    }`;

  $("mean-value").textContent = fmt(sum.mean);

  $("mean-label").textContent = sum.level_label
    ? `TVDI trung bình, mức ${sum.level_label.toLowerCase()}`
    : "Chưa có dữ liệu";

  const classes = sum.classes || [];
  const total =
    classes.reduce((a, c) => a + Number(c.count || 0), 0) || 1;

  const bar = $("class-bar");
  bar.replaceChildren();

  const list = $("class-list");
  list.replaceChildren();

  classes.forEach((c) => {
    const level = LEVELS[c.level];
    const color = level ? colorFor(level.mid) : NODATA;

    const segment = el("span");

    segment.style.width =
      `${(Number(c.count || 0) / total) * 100}%`;

    segment.style.background = color;

    bar.append(segment);

    const swatch = el("i");
    swatch.style.background = color;

    list.append(
      el("li", {}, [
        swatch,
        el("span", {
          text: c.label
        }),
        el("b", {
          text: `${c.count} phường/xã`
        })
      ])
    );
  });

  const driest = $("driest-list");
  driest.replaceChildren();

  (sum.driest || []).forEach((d, k) => {
    const btn = el("button", {
      type: "button"
    }, [
      el("span", {
        class: "rank",
        text: String(k + 1)
      }),

      el("span", {
        class: "w-name",
        text: d.ward_name
      }),

      el("span", {
        class: "w-val",
        text: fmt(d.tvdi_mean)
      })
    ]);

    btn.addEventListener("click", () => {
      selectWard(d.ward_code, true);
    });

    driest.append(el("li", {}, [btn]));
  });
}

/* =========================================================
   8. CHI TIẾT PHƯỜNG/XÃ
   ========================================================= */

async function selectWard(code, zoom = false) {
  if (!code) return;

  state.wardCode = code;
  state.live = [];

  $("predict-result").replaceChildren();

  if (state.layer) {
    state.layer.eachLayer((layer) => {
      layer.setStyle(wardStyle(layer.feature));

      if (
        zoom &&
        layer.feature.properties.ward_code === code
      ) {
        state.map.fitBounds(
          layer.getBounds(),
          { maxZoom: 13 }
        );
      }
    });
  }

  try {
    const data = await api(
      `/api/ward/${encodeURIComponent(code)}/series`
    );

    if (state.wardCode !== code) return;

    state.wardSeries = data;

    $("ward-block").hidden = false;
    $("ward-name").textContent = data.ward.name;

    $("ward-meta").textContent = data.ward.area_km2
      ? `Diện tích ${fmt(data.ward.area_km2, 1)} km²`
      : "";

    renderWardChart();
  } catch (err) {
    showNotice(err.message);
  }
}

/* =========================================================
   9. BIỂU ĐỒ TVDI CỦA PHƯỜNG/XÃ
   ========================================================= */

function renderWardChart() {
  if (!state.wardSeries) return;

  const series = state.wardSeries.series || [];

  const label = (nam, thang) =>
    `${String(thang).padStart(2, "0")}/${nam}`;

  const key = (nam, thang) => nam * 12 + thang;

  const months = new Map();

  series.forEach((s) => {
    months.set(
      key(s.nam, s.thang),
      { nam: s.nam, thang: s.thang }
    );
  });

  state.live.forEach((s) => {
    months.set(
      key(s.nam, s.thang),
      { nam: s.nam, thang: s.thang }
    );
  });

  const order = [...months.keys()].sort((a, b) => a - b);

  const pick = (loai) =>
    order.map((k) => {
      const m = months.get(k);

      const found = series.find((s) =>
        (
          (loai === "thuc_te" && s.nam < 2026) ||
          (loai === "du_bao" && s.nam >= 2026)
        ) &&
        s.nam === m.nam &&
        s.thang === m.thang
      );

      return found ? found.tvdi_mean : null;
    });

  const actual = pick("thuc_te");

  const forecast = order.map((k) => {
    const m = months.get(k);

    const fromPrediction = state.live.find((s) =>
      s.nam === m.nam && s.thang === m.thang
    );

    if (fromPrediction) {
      return fromPrediction.tvdi_du_bao ??
        fromPrediction.tvdi_mean ??
        null;
    }

    const fromSeries = series.find((s) =>
      s.nam >= 2026 &&
      s.nam === m.nam &&
      s.thang === m.thang
    );

    return fromSeries ? fromSeries.tvdi_mean : null;
  });

  if (state.wardChart) {
    state.wardChart.destroy();
  }

  state.wardChart = new Chart($("ward-chart"), {
    type: "line",

    data: {
      labels: order.map((k) => {
        const m = months.get(k);
        return label(m.nam, m.thang);
      }),

      datasets: [
        {
          label: "Thực tế",
          data: actual,
          borderColor: "#1b2a38",
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.25
        },

        {
          label: "Dự báo AI",
          data: forecast,
          borderColor: "#0e6b8c",
          borderDash: [5, 4],
          borderWidth: 2,
          pointRadius: 2,
          tension: 0.25
        }
      ]
    },

    options: {
      responsive: true,
      maintainAspectRatio: false,

      scales: {
        y: {
          min: 0,
          max: 1,
          title: {
            display: true,
            text: "TVDI"
          }
        },

        x: {
          ticks: {
            maxTicksLimit: 10
          }
        }
      },

      plugins: {
        legend: {
          position: "bottom",
          labels: {
            boxWidth: 14
          }
        }
      }
    }
  });
}

/* =========================================================
   10. DỰ BÁO 6 THÁNG
   ========================================================= */

async function runPredict() {
  if (!state.wardCode) {
    return;
  }

  const btn = $("predict-btn");
  const out = $("predict-result");

  btn.disabled = true;
  btn.textContent = "Đang dự báo...";

  out.replaceChildren();

  try {
    const res = await api("/api/predict", {
      method: "POST",

      headers: {
        "Content-Type": "application/json"
      },

      body: JSON.stringify({
        ward_code: state.wardCode,
        horizon: 6
      })
    });

    state.live = res.predictions || [];

    renderWardChart();

    const tbody = el("tbody");

    state.live.forEach((p) => {
      tbody.append(
        el("tr", {}, [
          el("td", {
            text:
              `${String(p.thang).padStart(2, "0")}/${p.nam}`
          }),

          el("td", {
            text: fmt(p.tvdi_du_bao)
          }),

          el("td", {
            text: p.level_label || "Chưa phân loại"
          })
        ])
      );
    });

    out.append(
      el("p", {
        text: "AI đã hoàn thành dự báo cho 6 tháng tiếp theo."
      }),

      el("table", {}, [
        el("thead", {}, [
          el("tr", {}, [
            el("th", { text: "Tháng" }),
            el("th", { text: "TVDI" }),
            el("th", { text: "Mức độ" })
          ])
        ]),

        tbody
      ])
    );
  } catch (err) {
    out.append(
      el("p", {
        class: "error",
        text: err.message
      })
    );
  } finally {
    btn.disabled = false;
    btn.textContent = "Dự báo 6 tháng tới bằng AI";
  }
}

/* =========================================================
   11. ẨN TAB MÔ HÌNH
   ========================================================= */

function setupTabs() {
  const tabModel =
    $("tab-model") ||
    document.querySelector(
      "button[aria-controls='panel-model']"
    ) ||
    document.querySelectorAll(".tabs button")[1];

  const panelModel = $("panel-model");

  const tabsContainer = document.querySelector(".tabs");

  if (tabModel) {
    tabModel.style.display = "none";
  }

  if (panelModel) {
    panelModel.style.display = "none";
  }

  if (tabsContainer) {
    tabsContainer.style.display = "none";
  }
}

/* =========================================================
   12. CHÚ THÍCH BẢN ĐỒ
   ========================================================= */

function drawLegend() {
  const bar = $("legend-bar");

  if (bar) {
    const stops = PALETTE
      .map(
        (color, i) =>
          `${color} ${(i / (PALETTE.length - 1)) * 100}%`
      )
      .join(", ");

    bar.style.background =
      `linear-gradient(to right, ${stops})`;
  }

  const legendBox = document.querySelector(".legend");

  if (!legendBox) {
    console.warn("Không tìm thấy phần tử .legend trong HTML.");
    return;
  }

  let nodataDiv = legendBox.querySelector(".legend-nodata");

  if (!nodataDiv) {
    nodataDiv = document.createElement("div");
    nodataDiv.className = "legend-nodata";
    legendBox.appendChild(nodataDiv);
  }

  nodataDiv.replaceChildren();

  Object.assign(nodataDiv.style, {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    marginTop: "8px",
    fontSize: "12.5px",
    color: "#5b6b7a",
    lineHeight: "18px"
  });

  const swatch = document.createElement("span");

  Object.assign(swatch.style, {
    display: "inline-block",
    width: "14px",
    height: "14px",
    minWidth: "14px",
    backgroundColor: NODATA,
    border: "1px solid #66727d",
    borderRadius: "2px",
    boxSizing: "border-box",
    flexShrink: "0"
  });

  const label = document.createElement("span");
  label.textContent = "Không có dữ liệu";

  nodataDiv.append(swatch, label);
}

/* =========================================================
   13. KHỞI TẠO ỨNG DỤNG
   ========================================================= */

async function init() {
  drawLegend();
  initMap();
  setupTabs();
  setupStripEvents();

  const predictBtn = $("predict-btn");

  if (predictBtn) {
    predictBtn.addEventListener("click", runPredict);
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

/* =========================================================
   14. TRỢ LÝ CHAT AI TVDI
   ========================================================= */

(function setupTVDIChat() {
  const chatStyle = document.createElement("style");

  chatStyle.textContent = `
    #tvdi-chat-launcher {
      position: fixed;
      z-index: 2000;
      left: 20px;
      bottom: 115px;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
      min-width: 112px;
      height: 52px;
      padding: 0 15px;
      border: 2px solid #ffffff;
      border-radius: 28px;
      background: linear-gradient(135deg, #ffb347, #ff7043);
      color: #ffffff;
      font-family: Arial, sans-serif;
      font-size: 14px;
      font-weight: 700;
      cursor: pointer;
      box-shadow: 0 4px 14px rgba(255, 112, 67, 0.4);
      transition: transform 0.2s ease, box-shadow 0.2s ease;
    }

    #tvdi-chat-launcher:hover {
      transform: translateY(-3px);
      box-shadow: 0 6px 18px rgba(255, 112, 67, 0.5);
    }

    #tvdi-chat-launcher:active {
      transform: scale(0.96);
    }

    #tvdi-chat-launcher .tvdi-fire-icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 25px;
      line-height: 1;
    }

    #tvdi-chat-launcher .tvdi-fire-label {
      white-space: nowrap;
      letter-spacing: 0.3px;
    }

    #tvdi-chat-panel {
      position: fixed;
      z-index: 2001;
      left: 20px;
      bottom: 177px;
      width: min(360px, calc(100vw - 40px));
      max-height: min(470px, calc(100vh - 210px));
      display: none;
      flex-direction: column;
      overflow: hidden;
      background: #ffffff;
      border: 1px solid #dbe3ec;
      border-radius: 16px;
      box-shadow: 0 8px 30px rgba(0, 0, 0, 0.18);
      font-family: Arial, sans-serif;
    }

    #tvdi-chat-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      padding: 13px 15px;
      color: #ffffff;
      background: linear-gradient(135deg, #ff9f43, #ff7043);
      font-weight: 700;
    }

    .tvdi-chat-brand {
      display: flex;
      align-items: center;
      gap: 9px;
    }

    .tvdi-chat-brand-icon {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 35px;
      height: 35px;
      background: rgba(255, 255, 255, 0.2);
      border-radius: 50%;
      font-size: 23px;
    }

    .tvdi-chat-brand-title {
      font-size: 14px;
      font-weight: 700;
    }

    .tvdi-chat-brand-subtitle {
      margin-top: 3px;
      font-size: 11px;
      font-weight: 400;
      opacity: 0.9;
    }

    #tvdi-chat-close {
      width: 30px;
      height: 30px;
      border: none;
      border-radius: 50%;
      background: rgba(255, 255, 255, 0.18);
      color: #ffffff;
      font-size: 22px;
      line-height: 1;
      cursor: pointer;
    }

    #tvdi-chat-close:hover {
      background: rgba(255, 255, 255, 0.3);
    }

    #tvdi-chat-messages {
      min-height: 100px;
      max-height: 310px;
      overflow-y: auto;
      padding: 13px;
      display: flex;
      flex-direction: column;
      gap: 11px;
      background: #ffffff;
    }

    .tvdi-chat-message {
      max-width: 92%;
      padding: 11px 13px;
      border-radius: 13px;
      font-size: 13px;
      line-height: 1.65;
      overflow-wrap: anywhere;
      white-space: pre-line;
    }

    .tvdi-chat-bot {
      align-self: flex-start;
      background: #f1f5f9;
      color: #1b2a38;
      border-bottom-left-radius: 4px;
    }

    .tvdi-chat-user {
      align-self: flex-end;
      background: #1769aa;
      color: #ffffff;
      border-bottom-right-radius: 4px;
    }

    .tvdi-chat-result-title {
      display: block;
      margin-bottom: 7px;
      font-size: 14px;
      font-weight: 700;
      color: #1769aa;
    }

    .tvdi-chat-result-row {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin: 5px 0;
    }

    .tvdi-chat-result-row strong {
      text-align: right;
    }

    .tvdi-chat-result-note {
      margin-top: 9px;
      padding-top: 8px;
      border-top: 1px solid #dbe3ec;
      color: #526579;
      font-size: 12px;
    }

    .tvdi-chat-typing {
      align-self: flex-start;
      padding: 9px 12px;
      border-radius: 12px;
      background: #f1f5f9;
      color: #64748b;
      font-size: 12px;
    }

    #tvdi-chat-form {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px;
      border-top: 1px solid #e5e7eb;
      background: #ffffff;
    }

    #tvdi-chat-input {
      min-width: 0;
      flex: 1;
      padding: 11px 12px;
      border: 1px solid #ccd5df;
      border-radius: 10px;
      outline: none;
      font-family: Arial, sans-serif;
      font-size: 13px;
    }

    #tvdi-chat-input:focus {
      border-color: #1769aa;
      box-shadow: 0 0 0 2px rgba(23, 105, 170, 0.1);
    }

    #tvdi-chat-send {
      min-width: 48px;
      padding: 11px 13px;
      border: none;
      border-radius: 10px;
      background: #1769aa;
      color: #ffffff;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
    }

    #tvdi-chat-send:hover {
      background: #12588f;
    }

    #tvdi-chat-send:disabled {
      opacity: 0.55;
      cursor: wait;
    }

    @media (max-width: 600px) {
      #tvdi-chat-launcher {
        left: 12px;
        bottom: 105px;
        min-width: 108px;
        height: 49px;
        padding: 0 13px;
      }

      #tvdi-chat-panel {
        left: 12px;
        bottom: 163px;
        width: min(360px, calc(100vw - 24px));
        max-height: min(430px, calc(100dvh - 185px));
      }

      #tvdi-chat-messages {
        max-height: 270px;
      }
    }

    @media (max-height: 500px) {
      #tvdi-chat-launcher {
        bottom: 80px;
      }

      #tvdi-chat-panel {
        bottom: 138px;
        max-height: calc(100dvh - 155px);
      }

      #tvdi-chat-messages {
        max-height: 180px;
      }
    }
  `;

  document.head.appendChild(chatStyle);

  const launcher = document.createElement("button");
  launcher.id = "tvdi-chat-launcher";
  launcher.type = "button";
  launcher.innerHTML = `
    <span class="tvdi-fire-icon">🔥</span>
    <span class="tvdi-fire-label">AI TVDI</span>
  `;
  launcher.title = "Trợ lý AI TVDI - Tra cứu hạn hán";
  launcher.setAttribute("aria-label", "Mở trợ lý AI TVDI");

  const panel = document.createElement("section");
  panel.id = "tvdi-chat-panel";
  panel.setAttribute("aria-label", "Trợ lý AI TVDI");
  panel.innerHTML = `
    <div id="tvdi-chat-header">
      <div class="tvdi-chat-brand">
        <div class="tvdi-chat-brand-icon">🔥</div>
        <div>
          <div class="tvdi-chat-brand-title">AI TVDI</div>
          <div class="tvdi-chat-brand-subtitle">Trợ lý tra cứu hạn hán</div>
        </div>
      </div>
      <button id="tvdi-chat-close" type="button" aria-label="Đóng khung chat">×</button>
    </div>

    <div id="tvdi-chat-messages" aria-live="polite"></div>

    <form id="tvdi-chat-form">
      <input
        id="tvdi-chat-input"
        type="text"
        placeholder="Nhập xã/phường và tháng/năm..."
        autocomplete="off"
        required
      />
      <button id="tvdi-chat-send" type="submit">Gửi</button>
    </form>
  `;

  document.body.append(launcher, panel);

  const messages = $("tvdi-chat-messages");
  const form = $("tvdi-chat-form");
  const input = $("tvdi-chat-input");
  const send = $("tvdi-chat-send");

  function addMessage(text, type = "bot") {
    const div = document.createElement("div");
    div.className =
      "tvdi-chat-message " +
      (type === "user" ? "tvdi-chat-user" : "tvdi-chat-bot");
    div.textContent = text;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
  }

  function addResultMessage(wardName, period, value, level, noData) {
    const div = document.createElement("div");
    div.className = "tvdi-chat-message tvdi-chat-bot";

    const title = document.createElement("span");
    title.className = "tvdi-chat-result-title";
    title.textContent = "🔥 KẾT QUẢ TRA CỨU TVDI";
    div.appendChild(title);

    const rows = [
      ["Phường/xã", wardName],
      ["Thời gian", `${String(period.thang).padStart(2, "0")}/${period.nam}`],
      ["Chỉ số TVDI", noData ? "Không có dữ liệu" : fmt(value)],
      ["Mức độ", noData ? "Chưa xác định" : level]
    ];

    rows.forEach(([label, valueText]) => {
      const row = document.createElement("div");
      row.className = "tvdi-chat-result-row";

      const labelNode = document.createElement("span");
      labelNode.textContent = label;

      const valueNode = document.createElement("strong");
      valueNode.textContent = valueText;

      row.append(labelNode, valueNode);
      div.appendChild(row);
    });

    const note = document.createElement("div");
    note.className = "tvdi-chat-result-note";
    note.textContent = noData
      ? "Bản đồ đã chuyển sang thời gian tra cứu và làm nổi bật khu vực nếu có ranh giới tương ứng."
      : "Bản đồ đã chuyển sang đúng tháng/năm và làm nổi bật khu vực này.";

    div.appendChild(note);

    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  function addTyping() {
    const div = document.createElement("div");
    div.className = "tvdi-chat-typing";
    div.textContent = "AI TVDI đang tra cứu...";
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
  }

  addMessage(
    "Xin chào! Mình là AI TVDI 🔥\n\n" +
    "Bạn có thể tra cứu chỉ số hạn hán của một phường/xã theo tháng và năm.\n\n" +
    "Ví dụ: Phường Thủ Đức tháng 5/2020."
  );

  launcher.addEventListener("click", () => {
    const isOpen = panel.style.display === "flex";
    panel.style.display = isOpen ? "none" : "flex";
    if (!isOpen) {
      input.focus();
    }
  });

  $("tvdi-chat-close").addEventListener("click", () => {
    panel.style.display = "none";
  });

  function normalize(text) {
    return String(text || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/đ/g, "d")
      .replace(/Đ/g, "D")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  function parsePeriod(text) {
    const s = normalize(text);

    let match = s.match(
      /thang\s*(\d{1,2})\s*(?:nam\s*)?(\d{4})/
    );

    if (match) {
      return {
        thang: Number(match[1]),
        nam: Number(match[2])
      };
    }

    match = s.match(
      /(?:^|\s)(\d{1,2})\s*[\/.-]\s*(\d{4})(?:\s|$)/
    );

    if (match) {
      return {
        thang: Number(match[1]),
        nam: Number(match[2])
      };
    }

    match = s.match(
      /(?:^|\s)(\d{4})\s*[\/.-]\s*(\d{1,2})(?:\s|$)/
    );

    if (match) {
      return {
        nam: Number(match[1]),
        thang: Number(match[2])
      };
    }

    return null;
  }

  function findWard(query) {
    if (!state.layer) {
      return null;
    }

    const q = normalize(query);

    const features =
      state.layer.toGeoJSON().features || [];

    const candidates = features
      .map((feature) => {
        const p = feature.properties || {};

        const name =
          p.ward_name ||
          p.fullname ||
          p.name ||
          "";

        return {
          code: p.ward_code,
          name,
          normalizedName: normalize(name),
          properties: p
        };
      })
      .filter((ward) =>
        ward.code &&
        ward.normalizedName &&
        q.includes(ward.normalizedName)
      )
      .sort(
        (a, b) =>
          b.normalizedName.length - a.normalizedName.length
      );

    return candidates[0] || null;
  }

  async function searchTVDI(query) {
    if (!state.periods.length) {
      addMessage(
        "Dữ liệu thời gian chưa tải xong. Vui lòng thử lại."
      );
      return;
    }

    const period = parsePeriod(query);

    if (!period) {
      addMessage(
        "Bạn hãy nhập rõ tháng và năm nhé.\n\n" +
        "Ví dụ: Xã Đất Đỏ tháng 8/2024."
      );
      return;
    }

    if (period.thang < 1 || period.thang > 12) {
      addMessage(
        "Tháng không hợp lệ. Vui lòng nhập từ tháng 1 đến tháng 12."
      );
      return;
    }

    const index = state.periods.findIndex((p) =>
      Number(p.nam) === period.nam &&
      Number(p.thang) === period.thang
    );

    if (index < 0) {
      addMessage(
        `Không tìm thấy dữ liệu tháng ${period.thang}/${period.nam}.`
      );
      return;
    }

    await goTo(index);

    if (state.idx !== index || !state.layer) {
      addMessage(
        "Chưa tải được bản đồ của thời gian này. Vui lòng thử lại."
      );
      return;
    }

    const ward = findWard(query);

    if (!ward) {
      addMessage(
        "Mình chưa nhận diện được tên phường/xã trong câu hỏi.\n\n" +
        "Bạn hãy kiểm tra tên và thử nhập lại, ví dụ: " +
        "Phường Thủ Đức tháng 5/2020."
      );
      return;
    }

    await selectWard(ward.code, true);

    const currentFeature = state.layer
      .toGeoJSON()
      .features
      .find((feature) =>
        feature.properties.ward_code === ward.code
      );

    const p = currentFeature
      ? currentFeature.properties
      : ward.properties;

    const value = p.tvdi_mean;

    const noData =
      value === null ||
      value === undefined ||
      value === "" ||
      !Number.isFinite(Number(value));

    addResultMessage(
      ward.name,
      period,
      value,
      p.level_label || "Chưa phân loại",
      noData
    );
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const query = input.value.trim();

    if (!query) return;

    addMessage(query, "user");

    input.value = "";
    send.disabled = true;

    const typing = addTyping();

    try {
      await searchTVDI(query);
    } catch (error) {
      addMessage(
        `Không thể tra cứu dữ liệu: ${
          error.message || "Lỗi không xác định"
        }`
      );
    } finally {
      typing.remove();

      send.disabled = false;
      input.focus();
    }
  });
})();