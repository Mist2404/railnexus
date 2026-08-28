/* RailNexus 地图组件 (Leaflet + OSM, 方案 A+ 两级显示)
 *
 * 一级 (全国视野): 城市点 marker, 点击弹出该城站点列表
 * 二级 (放大到城市级): 展开具体站点 marker, 可直接点选
 * 铁路线: 按车次类型着色, 低缩放只画干线
 */
(function () {
  "use strict";

  let map = null;
  let mapData = null;
  let cityLayer = null;      // 城市点 marker 层
  let stationLayer = null;   // 站点 marker 层
  let railLayer = null;      // 铁路线 polyline 层
  let selectedFrom = null;   // {tc, name}
  let selectedTo = null;

  const CITY_ZOOM = 8;       // 放大到城市级的缩放阈值
  const TYPE_COLOR = {
    G: "#d62728", D: "#1f77b4", C: "#9467bd",
    Z: "#2ca02c", T: "#17becf", K: "#ff7f0e",
    default: "#7f7f7f",
  };

  function init(containerId) {
    map = L.map(containerId, {
      center: [35.86, 104.20], zoom: 4,
      zoomControl: true,
    });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map);

    cityLayer = L.layerGroup().addTo(map);
    stationLayer = L.layerGroup().addTo(map);
    railLayer = L.layerGroup().addTo(map);

    loadData();
    map.on("zoomend", onZoomEnd);
  }

  async function loadData() {
    try {
      const resp = await fetch("/api/map");
      mapData = await resp.json();
      renderRails();
      renderCities();
      renderStations();
      onZoomEnd();
    } catch (e) {
      console.error("load map data failed", e);
    }
  }

  /* 铁路线: 只画 level<=maxLevel 站点之间相连的边 */
  function renderRails() {
    railLayer.clearLayers();
    if (!mapData) return;
    const stByTc = {};
    mapData.stations.forEach((s) => { stByTc[s.tc] = s; });

    const paths = [];
    mapData.edges.forEach((e) => {
      const a = stByTc[e.f], b = stByTc[e.t];
      if (!a || !b) return;
      const type = pickType(e.types);
      paths.push({
        latlng: [[a.lat, a.lng], [b.lat, b.lng]],
        type: type,
        color: TYPE_COLOR[type] || TYPE_COLOR.default,
      });
    });

    // 按类型分组添加到图层, 供按缩放级别控制
    railLayer.clearLayers();
    paths.forEach((p) => {
      L.polyline(p.latlng, {
        color: p.color, weight: 1.2, opacity: 0.55,
      }).addTo(railLayer);
    });
  }

  function pickType(types) {
    const order = ["G", "D", "C", "Z", "T", "K"];
    for (const t of order) {
      if (types.includes(t)) return t;
    }
    return types[0] || "default";
  }

  /* 一级: 城市点 */
  function renderCities() {
    cityLayer.clearLayers();
    mapData.cities.forEach((city) => {
      const m = L.circleMarker([city.lat, city.lng], {
        radius: 7, color: "#fff", weight: 1.5,
        fillColor: "#1976d2", fillOpacity: 0.9,
      }).addTo(cityLayer);

      const stationNames = city.station_tcs
        .map((tc) => {
          const s = mapData.stations.find((x) => x.tc === tc);
          return s ? s.name : null;
        })
        .filter(Boolean);

      const listHtml = stationNames
        .map((n, i) =>
          `<button class="map-sta-btn" data-city="${city.name}" data-idx="${i}">${n}</button>`
        )
        .join("");

      m.bindPopup(
        `<div class="map-city-pop">
          <b>${city.name}</b> (${stationNames.length}站)
          <div class="map-sta-list">${listHtml}</div>
         </div>`
      );
    });
  }

  /* 二级: 站点 marker */
  function renderStations() {
    stationLayer.clearLayers();
    mapData.stations.forEach((s) => {
      const color = s.level === 1 ? "#d62728" : (s.level === 2 ? "#ff7f0e" : "#1976d2");
      const m = L.circleMarker([s.lat, s.lng], {
        radius: s.level === 1 ? 5 : (s.level === 2 ? 3.5 : 2),
        color: "#fff", weight: 1, fillColor: color, fillOpacity: 0.9,
      }).addTo(stationLayer);
      m.bindTooltip(s.name);
      m.on("click", () => onStationClick(s));
    });
  }

  /* 缩放级别控制两级显示 */
  function onZoomEnd() {
    const z = map.getZoom();
    if (z >= CITY_ZOOM) {
      stationLayer.addTo(map);
    } else {
      map.removeLayer(stationLayer);
    }
  }

  /* 点击站点处理: 未选出发 → 设出发; 已选出发 → 设到达 */
  function onStationClick(s) {
    if (!selectedFrom) {
      setSelection("from", s);
    } else if (!selectedTo) {
      setSelection("to", s);
    } else {
      setSelection("from", s);
      setSelection("to", null);
    }
  }

  function setSelection(role, s) {
    if (role === "from") {
      selectedFrom = s;
      document.getElementById("fromInput").value = s ? s.name : "";
      if (s) highlightMarker(s, "from");
    } else {
      selectedTo = s;
      document.getElementById("toInput").value = s ? s.name : "";
      if (s) highlightMarker(s, "to");
    }
    // 同步文本输入框
    if (selectedFrom && selectedTo) {
      document.getElementById("searchBtn").disabled = false;
    }
  }

  /* 简单高亮: 重新渲染站点层太贵, 用 popup 提示 */
  function highlightMarker(s, role) {
    if (!map) return;
    const stByTc = {};
    mapData.stations.forEach((x) => { stByTc[x.tc] = x; });
    const st = stByTc[s.tc];
    if (st) {
      const m = L.circleMarker([st.lat, st.lng], {
        radius: 7, color: "#fff", weight: 2,
        fillColor: role === "from" ? "#2ca02c" : "#d62728", fillOpacity: 1,
      }).addTo(map);
      m.bindPopup((role === "from" ? "出发站: " : "到达站: ") + s.name).openPopup();
      setTimeout(() => { map.removeLayer(m); }, 2500);
    }
  }

  /* 暴露给全局: 供外部按钮/输入框联动 */
  window.RailMap = {
    init,
    setFrom(s) { setSelection("from", s); },
    setTo(s) { setSelection("to", s); },
    clearSelections() {
      selectedFrom = null;
      selectedTo = null;
    },
    /* 按电报码选择: 未选出发→出发; 已选出发→到达 */
    selectByTc(tc) {
      const s = mapData.stations.find((x) => x.tc === tc);
      if (s) onStationClick(s);
    },
  };
})();
