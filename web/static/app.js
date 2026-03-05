'use strict';

const REFRESH_MS = 5000;
let trendChart = null;

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtValue(tag) {
  if (tag.quality === 1) return { text: 'COMM ERR', cls: 'val-err' };
  if (tag.value === null || tag.value === undefined) return { text: '—', cls: '' };
  if (tag.data_type === 'bool') {
    return tag.value ? { text: 'ACTIVE', cls: 'val-alarm' } : { text: 'OK', cls: 'val-good' };
  }
  const v = tag.data_type === 'float32' ? tag.value.toFixed(2) : Math.round(tag.value);
  return { text: `${v} ${tag.unit}`, cls: tag.quality === 0 ? 'val-good' : 'val-err' };
}

function timeAgo(tsStr) {
  if (!tsStr) return '—';
  const diff = Math.round((Date.now() - new Date(tsStr + 'Z')) / 1000);
  if (diff < 60) return `${diff}s ago`;
  return `${Math.round(diff / 60)}m ago`;
}

// ── Render ───────────────────────────────────────────────────────────────────

function renderPLCs(plcs) {
  const grid = document.getElementById('plc-grid');
  grid.innerHTML = '';

  if (!plcs.length) {
    grid.innerHTML = '<p style="color:#94a3b8;margin-top:2rem;text-align:center">No PLCs configured.</p>';
    return;
  }

  for (const plc of plcs) {
    const hasError = plc.tags.some(t => t.quality === 1);
    const badgeClass = hasError ? 'err' : 'ok';
    const badgeText  = hasError ? 'COMM ERROR' : 'ONLINE';

    const rows = plc.tags.map(tag => {
      const { text, cls } = fmtValue(tag);
      return `<tr data-tag-id="${tag.id}" data-tag-name="${tag.name}" data-plc-name="${plc.name}">
        <td>${tag.name}</td>
        <td>${tag.register_type}</td>
        <td>${tag.data_type}</td>
        <td class="${cls}">${text}</td>
        <td style="color:#94a3b8;font-size:0.8rem">${timeAgo(tag.ts)}</td>
      </tr>`;
    }).join('');

    const card = document.createElement('div');
    card.className = 'plc-card';
    card.innerHTML = `
      <div class="plc-header">
        <h2>${plc.name}</h2>
        <span class="ip">${plc.ip}</span>
        <span class="badge ${badgeClass}">${badgeText}</span>
      </div>
      <table>
        <thead>
          <tr>
            <th>Tag</th><th>Type</th><th>Data Type</th><th>Value</th><th>Updated</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>`;
    grid.appendChild(card);
  }

  // Row click → open trend chart
  document.querySelectorAll('tr[data-tag-id]').forEach(row => {
    row.addEventListener('click', () => openChart(
      parseInt(row.dataset.tagId, 10),
      `${row.dataset.plcName} / ${row.dataset.tagName}`
    ));
  });
}

// ── Alarm badge ──────────────────────────────────────────────────────────────

async function refreshAlarms() {
  try {
    const resp = await fetch('/api/alarms');
    const alarms = await resp.json();
    const badge = document.getElementById('alarm-badge');
    if (alarms.length) {
      badge.style.display = 'inline-block';
      badge.textContent = `⚠ ${alarms.length} ALARM${alarms.length > 1 ? 'S' : ''}`;
    } else {
      badge.style.display = 'none';
    }
  } catch (_) { /* ignore */ }
}

// ── Live table ───────────────────────────────────────────────────────────────

async function refresh() {
  try {
    const resp = await fetch('/api/plcs');
    const plcs = await resp.json();
    renderPLCs(plcs);
    document.getElementById('last-updated').textContent =
      'Updated: ' + new Date().toLocaleTimeString();
    await refreshAlarms();
  } catch (err) {
    console.error('Refresh error:', err);
  }
}

// ── Chart modal ──────────────────────────────────────────────────────────────

async function openChart(tagId, title) {
  const overlay = document.getElementById('modal-overlay');
  document.getElementById('modal-title').textContent = title + ' — last 60 min';
  overlay.classList.add('open');

  try {
    const resp = await fetch(`/api/tags/${tagId}/history?minutes=60`);
    const rows = await resp.json();

    const labels = rows.map(r => new Date(r.ts + 'Z').toLocaleTimeString());
    const values = rows.map(r => (r.quality === 0 && r.value !== null) ? r.value : null);

    if (trendChart) trendChart.destroy();
    const ctx = document.getElementById('trend-chart').getContext('2d');
    trendChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: title,
          data: values,
          borderColor: '#38bdf8',
          backgroundColor: 'rgba(56,189,248,0.1)',
          borderWidth: 2,
          pointRadius: 2,
          spanGaps: false,
          tension: 0.3,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: '#cbd5e1' } },
        },
        scales: {
          x: {
            ticks: { color: '#94a3b8', maxTicksLimit: 12 },
            grid:  { color: '#1e293b' },
          },
          y: {
            ticks: { color: '#94a3b8' },
            grid:  { color: '#334155' },
          },
        },
      },
    });
  } catch (err) {
    console.error('Chart error:', err);
  }
}

document.getElementById('modal-close').addEventListener('click', () => {
  document.getElementById('modal-overlay').classList.remove('open');
});
document.getElementById('modal-overlay').addEventListener('click', e => {
  if (e.target === document.getElementById('modal-overlay')) {
    document.getElementById('modal-overlay').classList.remove('open');
  }
});

// ── Boot ─────────────────────────────────────────────────────────────────────
refresh();
setInterval(refresh, REFRESH_MS);
