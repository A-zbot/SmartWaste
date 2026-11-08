/* SmartWaste 2.0 front-end behaviour (no frameworks, progressive enhancement) */

/* ---------------- navigation ---------------- */
function toggleMenu() {
  const links = document.getElementById('navLinks');
  if (links) links.classList.toggle('open');
}
function toggleSidebar() {
  const side = document.querySelector('.sidebar');
  if (side) side.classList.toggle('open');
}
document.addEventListener('click', (e) => {
  const side = document.querySelector('.sidebar');
  if (side && side.classList.contains('open') &&
      !e.target.closest('.sidebar') && !e.target.closest('.admin-menu-btn')) {
    side.classList.remove('open');
  }
});

/* ---------------- flash messages ---------------- */
function autoDismissFlashes() {
  document.querySelectorAll('.flash').forEach((el) => {
    setTimeout(() => {
      el.style.transition = 'opacity .4s, transform .4s';
      el.style.opacity = '0';
      el.style.transform = 'translateX(16px)';
      setTimeout(() => el.remove(), 420);
    }, 7000);
  });
}

/* ---------------- geolocation with manual correction ---------------- */
function useMyLocation() {
  const status = document.getElementById('geoStatus');
  const locationField = document.getElementById('location');
  const latField = document.getElementById('latitude');
  const lonField = document.getElementById('longitude');
  if (!navigator.geolocation) {
    if (status) status.textContent = 'Geolocation is not supported - enter the location manually.';
    return;
  }
  if (status) status.textContent = 'Detecting location…';
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      const lat = pos.coords.latitude.toFixed(5);
      const lon = pos.coords.longitude.toFixed(5);
      if (latField) latField.value = lat;
      if (lonField) lonField.value = lon;
      if (locationField && !locationField.value.trim()) {
        locationField.value = `Near ${lat}, ${lon}`;
      }
      if (status) {
        status.textContent = `Coordinates captured: ${lat}, ${lon}. Adjust the text below if needed.`;
        status.className = 'field-help';
      }
      document.getElementById('dupPanel')?.removeAttribute('data-checked');
    },
    () => {
      if (status) {
        status.textContent = 'Location permission denied - enter the address manually.';
        status.className = 'field-help';
      }
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
  );
}
function clearLocation() {
  const latField = document.getElementById('latitude');
  const lonField = document.getElementById('longitude');
  const status = document.getElementById('geoStatus');
  if (latField) latField.value = '';
  if (lonField) lonField.value = '';
  if (status) status.textContent = 'Coordinates cleared - text location only.';
}

/* ---------------- image preview ---------------- */
function bindImagePreview() {
  const input = document.getElementById('image');
  if (!input) return;
  input.addEventListener('change', () => {
    const file = input.files[0];
    const preview = document.getElementById('preview');
    const hint = document.getElementById('uploadText');
    if (!file || !preview) return;
    preview.src = URL.createObjectURL(file);
    preview.style.display = 'block';
    if (hint) hint.style.display = 'none';
  });
}

/* ---------------- duplicate check (AJAX) ---------------- */
function checkDuplicates() {
  const panel = document.getElementById('dupPanel');
  const output = document.getElementById('dupResults');
  const textArea = document.getElementById('description');
  if (!panel || !output || !textArea) return;
  const payload = {
    text: textArea.value,
    latitude: (document.getElementById('latitude') || {}).value || null,
    longitude: (document.getElementById('longitude') || {}).value || null,
    category: (document.getElementById('waste_type') || {}).value || null
  };
  const meta = document.getElementById('dupMeta');
  if (meta) meta.innerHTML = '<span class="dup-loading">Analysing text similarity and distance…</span>';
  fetch('/report/duplicate-check', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
      'X-CSRFToken': (document.querySelector('meta[name="csrf-token"]') || {}).content || ''
    },
    body: JSON.stringify(payload)
  })
    .then((r) => r.json())
    .then((data) => {
      panel.setAttribute('data-checked', '1');
      if (!data.ok) {
        if (meta) meta.innerHTML = `<span class="dup-loading">${data.error || 'Check unavailable.'}</span>`;
        return;
      }
      let html = `<div class="dup-loading">Compared against ${data.checked} recent complaint(s) in the last ${data.window_days} days.</div>`;
      if (data.matches && data.matches.length) {
        html += '<div class="dup-list">';
        data.matches.forEach((m) => {
          const dist = m.distance_km === null ? 'distance unknown' : `${m.distance_km} km away`;
          html += `<div class="dup-item ${m.is_likely ? 'likely' : ''}">
            <b>${m.tracking_id}</b> &middot; ${m.category} &middot;
            <span class="badge status-${(m.status || '').toLowerCase().replace(/\s+/g, '-')}">${m.status}</span>
            <div class="dup-meta">
              <span>Similarity ${(m.similarity * 100).toFixed(0)}%</span>
              <span>${dist}</span>
              <span>Submitted ${m.created_at}</span>
              <span>${m.location}</span>
              ${m.is_likely ? '<span><b>Likely duplicate</b></span>' : ''}
            </div></div>`;
        });
        html += '</div><div class="dup-loading">These are <b>suggestions only</b> - you can still submit this complaint.</div>';
      } else {
        html += '<div class="dup-ok">No similar complaints found nearby. Your report looks unique.</div>';
      }
      if (data.warnings && data.warnings.length) {
        html += `<div class="dup-loading">${data.warnings.join(' ')}</div>`;
      }
      output.innerHTML = html;
    })
    .catch(() => {
      if (meta) meta.innerHTML = '<span class="dup-loading">Duplicate check could not reach the server.</span>';
    });
}

/* ---------------- generic table filtering ---------------- */
function filterTable() {
  const table = document.getElementById('reportTable');
  if (!table) return;
  const search = (document.getElementById('search')?.value || '').toLowerCase();
  const active = (document.querySelector('.tab.active')?.dataset.status || 'all').toLowerCase();
  let shown = 0;
  table.querySelectorAll('tbody tr[data-status]').forEach((row) => {
    const ok = (active === 'all' || row.dataset.status === active) &&
      row.innerText.toLowerCase().includes(search);
    row.style.display = ok ? '' : 'none';
    if (ok) shown += 1;
  });
  const noMatch = document.getElementById('noMatch');
  if (noMatch) noMatch.style.display = (table.querySelectorAll('tbody tr[data-status]').length && !shown) ? '' : 'none';
}
function setFilterTab(btn) {
  document.querySelectorAll('.tab[data-status]').forEach((b) => b.classList.toggle('active', b === btn));
  const statusField = document.getElementById('statusFilter');
  if (statusField) statusField.value = btn.dataset.value || btn.dataset.status || '';
  filterTable();
}

/* ---------------- charts ---------------- */
const SW_COLORS = {
  forest: '#0A3527', emerald: '#0E9F6E', mint: '#7BD8B4', sky: '#3B82F6',
  amber: '#F59E0B', red: '#EF4444', violet: '#8B5CF6', slate: '#94A3B8',
  teal: '#14B8A6', rose: '#F43F5E'
};
const SW_PALETTE = [SW_COLORS.emerald, SW_COLORS.forest, SW_COLORS.sky, SW_COLORS.amber,
  SW_COLORS.teal, SW_COLORS.violet, SW_COLORS.rose, SW_COLORS.slate, SW_COLORS.mint, SW_COLORS.red];
const STATUS_COLORS = {
  'Submitted': '#3B82F6', 'Under Review': '#8B5CF6', 'Assigned': '#0EA5E9',
  'In Progress': '#F59E0B', 'Resolved': '#16A34A', 'Rejected': '#EF4444', 'Pending': '#3B82F6'
};

function baseChartOptions(extra) {
  return Object.assign({
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { boxWidth: 12, boxHeight: 12, usePointStyle: true, font: { size: 12 } } },
      tooltip: { padding: 10, cornerRadius: 8 }
    },
    scales: {
      x: { grid: { display: false }, ticks: { font: { size: 11 }, color: '#6B7C74', maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
      y: { beginAtZero: true, grid: { color: '#EDF2EF' }, ticks: { font: { size: 11 }, color: '#6B7C74', precision: 0 } }
    }
  }, extra || {});
}

function destroyChart(key) {
  if (window.__swCharts && window.__swCharts[key]) {
    window.__swCharts[key].destroy();
  }
  window.__swCharts = window.__swCharts || {};
}
function registerChart(key, chart) {
  window.__swCharts = window.__swCharts || {};
  window.__swCharts[key] = chart;
}

function renderDashboardCharts(data) {
  if (!data || !data.charts) return;
  const c = data.charts;

  const daily = document.getElementById('chartDaily');
  if (daily) {
    destroyChart('daily');
    registerChart('daily', new Chart(daily, {
      type: 'line',
      data: {
        labels: c.daily.labels.map((d) => d.slice(5)),
        datasets: [{
          label: 'Complaints / day', data: c.daily.values,
          borderColor: SW_COLORS.emerald, backgroundColor: 'rgba(14,159,110,.10)',
          fill: true, tension: .35, borderWidth: 2, pointRadius: 0
        }]
      },
      options: baseChartOptions()
    }));
  }

  const area = document.getElementById('chartArea');
  if (area) {
    destroyChart('area');
    registerChart('area', new Chart(area, {
      type: 'bar',
      data: {
        labels: c.area.map((r) => r.label),
        datasets: [{ label: 'Complaints', data: c.area.map((r) => r.value),
          backgroundColor: SW_COLORS.forest, borderRadius: 6, barThickness: 18 }]
      },
      options: baseChartOptions({ indexAxis: 'y', plugins: { legend: { display: false } } })
    }));
  }

  const category = document.getElementById('chartCategory');
  if (category) {
    destroyChart('category');
    registerChart('category', new Chart(category, {
      type: 'doughnut',
      data: {
        labels: c.category.map((r) => r.label),
        datasets: [{ data: c.category.map((r) => r.value),
          backgroundColor: SW_PALETTE, borderWidth: 2, borderColor: '#fff' }]
      },
      options: { responsive: true, maintainAspectRatio: false, cutout: '62%',
        plugins: { legend: { position: 'right', labels: { boxWidth: 11, usePointStyle: true, font: { size: 11.5 } } } } }
    }));
  }

  const status = document.getElementById('chartStatus');
  if (status) {
    destroyChart('status');
    registerChart('status', new Chart(status, {
      type: 'bar',
      data: {
        labels: c.status.map((r) => r.label),
        datasets: [{ label: 'Complaints', data: c.status.map((r) => r.value),
          backgroundColor: c.status.map((r) => STATUS_COLORS[r.label] || SW_COLORS.slate),
          borderRadius: 6, barThickness: 26 }]
      },
      options: baseChartOptions({ plugins: { legend: { display: false } } })
    }));
  }

  const monthly = document.getElementById('chartMonthly');
  if (monthly) {
    destroyChart('monthly');
    registerChart('monthly', new Chart(monthly, {
      type: 'bar',
      data: {
        labels: c.monthly.map((r) => r.label),
        datasets: [{ label: 'Complaints / month', data: c.monthly.map((r) => r.value),
          backgroundColor: SW_COLORS.emerald, borderRadius: 6, barThickness: 22 }]
      },
      options: baseChartOptions()
    }));
  }

  const urgency = document.getElementById('chartUrgency');
  if (urgency) {
    destroyChart('urgency');
    registerChart('urgency', new Chart(urgency, {
      type: 'doughnut',
      data: {
        labels: c.urgency.map((r) => r.label),
        datasets: [{ data: c.urgency.map((r) => r.value),
          backgroundColor: c.urgency.map((r) => ({
            'Emergency': SW_COLORS.red, 'High': SW_COLORS.rose, 'Medium': SW_COLORS.amber,
            'Low': SW_COLORS.emerald
          }[r.label] || SW_COLORS.slate), borderWidth: 2, borderColor: '#fff' }]
      },
      options: { responsive: true, maintainAspectRatio: false, cutout: '62%',
        plugins: { legend: { position: 'right', labels: { boxWidth: 11, usePointStyle: true, font: { size: 11.5 } } } } }
    }));
  }
}

function refreshDashboard() {
  const form = document.getElementById('dashboardFilters');
  if (!form) return;
  const params = new URLSearchParams(new FormData(form)).toString();
  const target = document.getElementById('dashboardCharts');
  if (target) target.style.opacity = '.55';
  fetch('/admin/api/overview?' + params, { headers: { 'Accept': 'application/json' } })
    .then((r) => r.json())
    .then((payload) => {
      if (!payload.ok) return;
      renderDashboardCharts(payload);
      updateKpis(payload.kpis);
      renderRecommendations(payload.recommendations);
      history.replaceState(null, '', '/admin' + (params ? '?' + params : ''));
      if (target) target.style.opacity = '1';
    })
    .catch(() => { if (target) target.style.opacity = '1'; });
}

function updateKpis(k) {
  const map = {
    kpiTotal: k.total, kpiOpen: k.open, kpiUrgent: k.urgent_open, kpiResolved: k.resolved,
    kpiReview: k.needs_review, kpiResolution: k.resolution_pct + '%',
    kpiHotspots: k.hotspots, kpiRecurring: k.recurring_locations
  };
  Object.keys(map).forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.textContent = map[id];
  });
  const sub = document.getElementById('kpiAvgRes');
  if (sub) sub.textContent = k.avg_resolution_hours === null
    ? 'no resolved complaints with timestamps yet'
    : `avg ${k.avg_resolution_hours} h across ${k.resolved_with_timestamp} resolved`;
}

function renderRecommendations(items) {
  const host = document.getElementById('recList');
  if (!host || !items) return;
  if (!items.length) {
    host.innerHTML = '<div class="mini-note">No recommendations right now - the backlog is clear for the active filters.</div>';
    return;
  }
  host.innerHTML = items.map((r) => `
    <div class="rec-item">
      <div class="rec-severity ${r.severity}"></div>
      <div class="rec-body">
        <b>${escapeHtml(r.title)}</b>
        <p>${escapeHtml(r.detail)}</p>
        <div class="rec-action">${escapeHtml(r.action)}</div>
      </div>
      <div class="rec-side"><b>${r.count}</b><small>items</small></div>
    </div>`).join('');
}

function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/* ---------------- forecast chart ---------------- */
function renderForecastChart(payload) {
  const canvas = document.getElementById('chartForecast');
  if (!canvas || !payload) return;
  const history = payload.history || { dates: [], counts: [] };
  const fc = payload.forecast || { dates: [], values: [], lower: [], upper: [] };
  const labels = history.dates.concat(fc.dates || []);
  const nulls = history.dates.map(() => null);
  const observed = history.counts.concat((fc.dates || []).map(() => null));
  const forecastSeries = nulls.concat(fc.values || []);
  const upper = nulls.concat(fc.upper && fc.upper.length ? fc.upper : (fc.dates || []).map(() => null));
  const lower = nulls.concat(fc.lower && fc.lower.length ? fc.lower : (fc.dates || []).map(() => null));

  const datasets = [];
  if (fc.upper && fc.upper.length && fc.lower && fc.lower.length) {
    datasets.push({
      label: 'Uncertainty band (upper)', data: upper, borderWidth: 0,
      pointRadius: 0, backgroundColor: 'rgba(14,159,110,.14)', fill: '+1'
    });
    datasets.push({
      label: 'Uncertainty band (lower)', data: lower, borderWidth: 0,
      pointRadius: 0, backgroundColor: 'rgba(14,159,110,.14)', fill: false
    });
  }
  datasets.push({
    label: 'Observed complaints', data: observed, borderColor: SW_COLORS.forest,
    backgroundColor: 'rgba(10,53,39,.08)', borderWidth: 2, tension: .3, pointRadius: 0, fill: false
  });
  if (fc.values && fc.values.length) {
    datasets.push({
      label: payload.status === 'ok' ? 'Random Forest forecast' : 'Baseline forecast',
      data: forecastSeries, borderColor: SW_COLORS.emerald, borderDash: [6, 4],
      borderWidth: 2, tension: .3, pointRadius: 2, pointBackgroundColor: SW_COLORS.emerald, fill: false
    });
  }
  destroyChart('forecast');
  registerChart('forecast', new Chart(canvas, {
    type: 'line',
    data: { labels: labels.map((d) => d.slice(5)), datasets },
    options: baseChartOptions({
      plugins: {
        legend: { labels: { boxWidth: 12, usePointStyle: true, filter: (i) => !i.text.includes('band') } },
        tooltip: { mode: 'index', intersect: false }
      }
    })
  }));
}

function renderBacktestChart(payload) {
  const canvas = document.getElementById('chartBacktest');
  if (!canvas || !payload || !payload.models || !payload.models.length) return;
  const first = payload.models[0];
  const labels = (first.test_days || []).map((d) => d.slice(5));
  const datasets = payload.models.map((m, idx) => ({
    label: m.name,
    data: m.predictions,
    borderColor: [SW_COLORS.forest, SW_COLORS.sky, SW_COLORS.emerald][idx % 3],
    borderDash: m.kind === 'baseline' ? [4, 3] : [],
    borderWidth: 2, tension: .25, pointRadius: 2, fill: false
  }));
  const actualIdx = payload.models.length;
  if (window.SW_ACTUALS && window.SW_ACTUALS.length === labels.length) {
    datasets.push({
      label: 'Actual', data: window.SW_ACTUALS,
      borderColor: SW_COLORS.amber, borderWidth: 2, pointRadius: 3, tension: .25, fill: false
    });
  }
  destroyChart('backtest');
  registerChart('backtest', new Chart(canvas, {
    type: 'line',
    data: { labels, datasets },
    options: baseChartOptions({ plugins: { legend: { labels: { boxWidth: 12, usePointStyle: true, font: { size: 11 } } } } })
  }));
}

/* ---------------- hotspot map ---------------- */
function initMap() {
  const host = document.getElementById('map');
  if (!host || typeof L === 'undefined' || !window.MAP_DATA) return;
  const { markers, clusters } = window.MAP_DATA;
  const map = L.map('map', { scrollWheelZoom: false });
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(map);

  const complaintLayer = L.layerGroup().addTo(map);
  const clusterLayer = L.layerGroup().addTo(map);
  const bounds = [];

  const statusColor = (s) => STATUS_COLORS[s] || '#94A3B8';

  (markers || []).forEach((m) => {
    if (m.lat == null || m.lng == null) return;
    const urgent = m.urgency === 'High' || m.urgency === 'Emergency' ||
      m.priority === 'High' || m.priority === 'Emergency';
    const marker = L.circleMarker([m.lat, m.lng], {
      radius: urgent ? 8 : 6,
      color: '#fff', weight: 1.5,
      fillColor: statusColor(m.status), fillOpacity: .9
    });
    marker.bindPopup(`
      <div style="font-family:Inter,Arial;min-width:210px">
        <b>${escapeHtml(m.tracking_id || ('#' + m.id))}</b>
        <span class="badge status-${(m.status || '').toLowerCase().replace(/\s+/g, '-')}">${escapeHtml(m.status)}</span>
        <p style="margin:6px 0 2px;font-size:13px">${escapeHtml(m.location)}</p>
        <p style="margin:0;font-size:12px;color:#6B7C74">
          ${escapeHtml(m.category)} &middot; priority ${escapeHtml(m.priority)}
          ${m.urgency ? ' &middot; AI ' + escapeHtml(m.urgency) : ''}
        </p>
        ${m.confidence != null ? `<p style="margin:4px 0 0;font-size:12px;color:#6B7C74">AI confidence ${(m.confidence * 100).toFixed(0)}%</p>` : ''}
        <a style="display:inline-block;margin-top:8px;color:#0E9F6E;font-weight:600" href="/admin/complaint/${m.id}">Open complaint →</a>
      </div>`);
    complaintLayer.addLayer(marker);
    bounds.push([m.lat, m.lng]);
  });

  (clusters || []).forEach((c) => {
    if (c.lat == null || c.lng == null) return;
    const radius = c.radius_km ? Math.max(c.radius_km * 1000, 120) : 300;
    L.circle([c.lat, c.lng], {
      radius, color: '#0E9F6E', weight: 1.5, dashArray: '5 5',
      fillColor: '#0E9F6E', fillOpacity: .10
    }).bindTooltip(`${c.label}: ${c.count} complaints (${c.unresolved} open)`, { sticky: true })
      .addTo(clusterLayer);
    const icon = L.divIcon({
      className: '',
      html: `<div class="cluster-badge">${c.label} · ${c.count}</div>`,
      iconSize: [70, 22], iconAnchor: [35, 11]
    });
    L.marker([c.lat, c.lng], { icon, interactive: false }).addTo(clusterLayer);
    bounds.push([c.lat, c.lng]);
  });

  L.control.layers(null, {
    'Complaints': complaintLayer,
    'Hotspot clusters': clusterLayer
  }, { collapsed: false }).addTo(map);

  if (bounds.length) map.fitBounds(bounds, { padding: [36, 36], maxZoom: 15 });
  else map.setView([20.5937, 78.9629], 5); // neutral India view when no coordinates exist
  setTimeout(() => map.invalidateSize(), 200);
}

/* ---------------- init ---------------- */
document.addEventListener('DOMContentLoaded', () => {
  autoDismissFlashes();
  bindImagePreview();

  const dash = document.getElementById('dashboardData');
  if (dash) {
    try { renderDashboardCharts(JSON.parse(dash.textContent)); } catch (e) { /* noop */ }
  }
  const fc = document.getElementById('forecastData');
  if (fc) {
    try {
      const payload = JSON.parse(fc.textContent);
      renderForecastChart(payload);
      renderBacktestChart(payload);
    } catch (e) { /* noop */ }
  }
  initMap();

  const dupButton = document.getElementById('dupCheckBtn');
  if (dupButton) dupButton.addEventListener('click', checkDuplicates);

  const dashForm = document.getElementById('dashboardFilters');
  if (dashForm) {
    dashForm.addEventListener('change', (e) => {
      if (e.target.tagName === 'SELECT' || e.target.type === 'date') refreshDashboard();
    });
    dashForm.addEventListener('submit', (e) => { e.preventDefault(); refreshDashboard(); });
  }

  filterTable();
});
