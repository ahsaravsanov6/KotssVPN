// analytics/static/dashboard.js
// Логика дашборда: подставляет ?token=... ко всем запросам API (тот же
// токен, что в URL страницы), тянет JSON, рисует графики Chart.js.
// Никакого build-шага — обычный браузерный JS.

const params = new URLSearchParams(window.location.search);
const TOKEN = params.get('token') || '';

let currentRange = '7d';
let charts = {};

function withToken(url) {
  const u = new URL(url, window.location.origin);
  u.searchParams.set('token', TOKEN);
  return u.toString();
}

async function fetchJSON(path) {
  const res = await fetch(withToken(path));
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
  return res.json();
}

// ── Форматирование ───────────────────────────────────────────────────────

function fmtBytes(bytes) {
  if (bytes === null || bytes === undefined) return '—';
  const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
  let v = Math.abs(bytes);
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(1)} ${units[i]}`;
}

function fmtBytesPerSec(bytes) {
  if (bytes === null || bytes === undefined) return '—';
  return fmtBytes(bytes) + '/с';
}

function fmtGB(bytes) {
  if (!bytes) return 0;
  return +(bytes / (1024 ** 3)).toFixed(3);
}

function fmtTime(iso) {
  const d = new Date(iso + 'Z');
  return d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function fmtTimeShort(iso) {
  const d = new Date(iso + 'Z');
  return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}

// ── Chart.js общие настройки темы ────────────────────────────────────────

Chart.defaults.font.family = "'JetBrains Mono', monospace";
Chart.defaults.font.size = 11;
Chart.defaults.color = '#8B92A4';

const GRID_COLOR = 'rgba(255,255,255,0.05)';
const ACCENT = '#5EEAD4';
const GOOD = '#34D399';
const WARN = '#F5A524';
const BAD = '#F25555';
const TEXT_DIM = '#565D70';

function baseScales(xLabel = '') {
  return {
    x: {
      grid: { color: GRID_COLOR, drawTicks: false },
      ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8 },
      border: { color: GRID_COLOR },
    },
    y: {
      grid: { color: GRID_COLOR, drawTicks: false },
      border: { display: false },
      beginAtZero: true,
    },
  };
}

function lineDataset(label, data, color, fill = true) {
  return {
    label,
    data,
    borderColor: color,
    backgroundColor: fill ? color + '1a' : 'transparent',
    fill,
    tension: 0.3,
    pointRadius: 0,
    borderWidth: 2,
  };
}

function makeOrUpdate(key, canvasId, config) {
  if (charts[key]) {
    charts[key].data = config.data;
    if (config.options) charts[key].options = config.options;
    charts[key].update();
    return charts[key];
  }
  const ctx = document.getElementById(canvasId);
  charts[key] = new Chart(ctx, config);
  return charts[key];
}

// ── KPI ──────────────────────────────────────────────────────────────────

async function loadOverview(range) {
  const data = await fetchJSON('/api/overview');
  const u = data.users;
  const s = data.server;

  document.getElementById('kpi-total-users').textContent = u ? u.total_users : '—';
  document.getElementById('kpi-total-users-sub').textContent = u
    ? `обновлено ${fmtTimeShort(u.ts)}` : '';

  document.getElementById('kpi-active-subs').textContent = u ? u.active_subscriptions : '—';
  document.getElementById('kpi-active-subs-sub').textContent = u
    ? `${u.no_subscription} без подписки` : '';

  document.getElementById('kpi-expired-subs').textContent = u ? u.expired_subscriptions : '—';
  document.getElementById('kpi-devices').textContent = u ? u.total_devices : '—';
  document.getElementById('kpi-online').textContent = data.online_now ?? '—';
  document.getElementById('kpi-referrals').textContent = u ? u.total_referrals : '—';

  document.getElementById('server-meta').textContent = s
    ? `${s.cpu_percent?.toFixed(1) ?? '—'}% · ${s.cpu_cores ?? '?'} ядер`
    : 'нет данных';
  document.getElementById('mem-meta').textContent = s
    ? `${fmtBytes(s.mem_current)} / ${fmtBytes(s.mem_total)}`
    : 'нет данных';

  // Индикатор "live": если последний снапшот старше 25 минут — считаем стейл.
  const dot = document.getElementById('live-dot');
  if (u) {
    const ageMin = (Date.now() - new Date(u.ts + 'Z').getTime()) / 60000;
    dot.classList.toggle('stale', ageMin > 25);
  }
}

// ── Сервер: CPU / память / сеть / онлайн ─────────────────────────────────

async function loadServerCharts(range) {
  const rows = await fetchJSON(`/api/server-timeseries?range=${range}`);
  const labels = rows.map(r => fmtTimeShort(r.ts));

  makeOrUpdate('cpu', 'chart-cpu', {
    type: 'line',
    data: {
      labels,
      datasets: [lineDataset('CPU %', rows.map(r => r.cpu_percent), ACCENT)],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { ...baseScales(), y: { ...baseScales().y, suggestedMax: 100 } },
    },
  });

  makeOrUpdate('mem', 'chart-mem', {
    type: 'line',
    data: {
      labels,
      datasets: [
        lineDataset('Использовано, ГБ', rows.map(r => r.mem_current ? +(r.mem_current / 1024 ** 3).toFixed(2) : null), GOOD),
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: baseScales(),
    },
  });

  makeOrUpdate('net', 'chart-net', {
    type: 'line',
    data: {
      labels,
      datasets: [
        lineDataset('Вход', rows.map(r => r.net_io_down), ACCENT, false),
        lineDataset('Выход', rows.map(r => r.net_io_up), WARN, false),
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: true, labels: { boxWidth: 10, boxHeight: 10 } } },
      scales: baseScales(),
    },
  });

  makeOrUpdate('online', 'chart-online', {
    type: 'line',
    data: {
      labels,
      datasets: [lineDataset('Онлайн', rows.map(r => r.online_clients), ACCENT)],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: baseScales(),
    },
  });
}

// ── Пользователи / подписки ──────────────────────────────────────────────

async function loadUsersChart(range) {
  const rows = await fetchJSON(`/api/users-timeseries?range=${range}`);
  const labels = rows.map(r => fmtTimeShort(r.ts));

  makeOrUpdate('users', 'chart-users', {
    type: 'line',
    data: {
      labels,
      datasets: [
        lineDataset('Всего пользователей', rows.map(r => r.total_users), TEXT_DIM, false),
        lineDataset('Активные подписки', rows.map(r => r.active_subscriptions), GOOD),
        lineDataset('Истекшие', rows.map(r => r.expired_subscriptions), WARN, false),
        lineDataset('Устройства', rows.map(r => r.total_devices), ACCENT, false),
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: true, labels: { boxWidth: 10, boxHeight: 10 } } },
      scales: baseScales(),
    },
  });
}

async function loadReferralsChart() {
  const rows = await fetchJSON('/api/referrals');
  const labels = rows.map(r => fmtTimeShort(r.ts));

  makeOrUpdate('referrals', 'chart-referrals', {
    type: 'line',
    data: {
      labels,
      datasets: [
        lineDataset('Приглашено', rows.map(r => r.total_referrals), ACCENT),
        lineDataset('С бонусом', rows.map(r => r.bonus_granted_referrals), GOOD, false),
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: true, labels: { boxWidth: 10, boxHeight: 10 } } },
      scales: baseScales(),
    },
  });
}

// ── Трафик: суммарный + топ клиентов ─────────────────────────────────────

async function loadTrafficCharts(range) {
  const totalRows = await fetchJSON(`/api/traffic-total-timeseries?range=${range}`);
  const labels = totalRows.map(r => fmtTimeShort(r.ts));

  makeOrUpdate('traffic_total', 'chart-traffic-total', {
    type: 'line',
    data: {
      labels,
      datasets: [
        lineDataset('Скачано (вниз)', totalRows.map(r => fmtGB(r.total_down)), ACCENT),
        lineDataset('Отправлено (вверх)', totalRows.map(r => fmtGB(r.total_up)), WARN, false),
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: true, labels: { boxWidth: 10, boxHeight: 10 } } },
      scales: {
        ...baseScales(),
        y: { ...baseScales().y, title: { display: true, text: 'ГБ накопительно' } },
      },
    },
  });

  const topRows = await fetchJSON(`/api/traffic-top-clients?range=${range}&limit=8`);
  const listEl = document.getElementById('top-clients-list');
  document.getElementById('top-clients-meta').textContent = `за ${rangeLabel(range)}`;

  if (!topRows.length) {
    listEl.innerHTML = '<div class="empty-state">Нет данных за этот период</div>';
    return;
  }

  const maxTotal = Math.max(...topRows.map(r => (r.delta_up || 0) + (r.delta_down || 0)), 1);

  listEl.innerHTML = topRows.map(r => {
    const total = (r.delta_up || 0) + (r.delta_down || 0);
    const pct = Math.max(2, Math.round((total / maxTotal) * 100));
    const tgPart = r.telegram_id ? `<span class="tg-id">#${r.telegram_id}</span>` : '';
    return `
      <div class="top-row">
        <span class="name">${escapeHtml(r.email)}${tgPart}</span>
        <span class="value">${fmtBytes(total)}</span>
        <div class="top-bar-track"><div class="top-bar-fill" style="width:${pct}%"></div></div>
      </div>
    `;
  }).join('');
}

function rangeLabel(range) {
  return { '24h': '24 часа', '7d': '7 дней', '30d': '30 дней', '90d': '90 дней' }[range] || range;
}

// ── Оплаты ────────────────────────────────────────────────────────────────

const METHOD_LABELS = {
  yookassa: '💳 YooKassa',
  cryptobot: '🤖 CryptoBot',
  heleket: '🌐 Heleket',
  unknown: '❓ Неизвестно',
};

function fmtRub(value) {
  if (!value) return '0 ₽';
  return Math.round(value).toLocaleString('ru-RU') + ' ₽';
}

async function loadPaymentsCharts(range) {
  const data = await fetchJSON(`/api/payments?range=${range}`);

  document.getElementById('kpi-revenue').textContent = fmtRub(data.total_price);
  document.getElementById('kpi-revenue-sub').textContent = `${data.total_count} оплат`;
  document.getElementById('payments-meta').textContent = `за ${rangeLabel(range)}`;

  const labels = data.by_day.map(r => {
    const d = new Date(r.day + 'T00:00:00Z');
    return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' });
  });

  makeOrUpdate('payments', 'chart-payments', {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          label: 'Выручка, ₽',
          data: data.by_day.map(r => r.total_price || 0),
          backgroundColor: ACCENT + '55',
          borderColor: ACCENT,
          borderWidth: 1.5,
          borderRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: baseScales(),
    },
  });

  const listEl = document.getElementById('payments-by-method-list');
  if (!data.by_method.length) {
    listEl.innerHTML = '<div class="empty-state">Нет оплат за этот период</div>';
    return;
  }

  const maxTotal = Math.max(...data.by_method.map(r => r.total_price || 0), 1);

  listEl.innerHTML = data.by_method.map(r => {
    const pct = Math.max(2, Math.round(((r.total_price || 0) / maxTotal) * 100));
    const label = METHOD_LABELS[r.method] || `❓ ${r.method}`;
    return `
      <div class="top-row">
        <span class="name">${label}<span class="tg-id">${r.count} оплат</span></span>
        <span class="value">${fmtRub(r.total_price)}</span>
        <div class="top-bar-track"><div class="top-bar-fill" style="width:${pct}%"></div></div>
      </div>
    `;
  }).join('');
}

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

// ── Оркестрация ───────────────────────────────────────────────────────────

async function loadAll(range) {
  try {
    await Promise.all([
      loadOverview(),
      loadServerCharts(range === '24h' ? '24h' : range),
      loadUsersChart(range),
      loadReferralsChart(),
      loadTrafficCharts(range),
      loadPaymentsCharts(range),
    ]);
  } catch (err) {
    console.error('Ошибка загрузки дашборда:', err);
  }
}

function updateClock() {
  document.getElementById('clock').textContent = new Date().toLocaleString('ru-RU');
}

document.getElementById('range-switch').addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-range]');
  if (!btn) return;
  document.querySelectorAll('.range-switch button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  currentRange = btn.dataset.range;
  loadAll(currentRange);
});

updateClock();
setInterval(updateClock, 1000);

loadAll(currentRange);
setInterval(() => loadAll(currentRange), 60000);
