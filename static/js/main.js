/* ═══════════════════════════════════════════════════════
   Van Sales V3 ERP — Main JavaScript
   ═══════════════════════════════════════════════════════ */

'use strict';

// ── Theme ──────────────────────────────────────────────
const ThemeManager = {
  init() {
    // Fall back to the server-rendered data-theme (the account's saved
    // preference) rather than always 'light', so a fresh device/session
    // opens in the theme the user picked on their profile page.
    const saved = localStorage.getItem('vs3-theme') || document.documentElement.getAttribute('data-theme') || 'light';
    this.apply(saved);
    document.getElementById('themeToggle')?.addEventListener('click', () => this.toggle());
  },
  apply(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    const icon = document.getElementById('themeIcon');
    if (icon) {
      icon.className = theme === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
    }
    localStorage.setItem('vs3-theme', theme);
  },
  toggle() {
    const current = document.documentElement.getAttribute('data-theme');
    this.apply(current === 'dark' ? 'light' : 'dark');
  }
};

// ── Sidebar ────────────────────────────────────────────
const SidebarManager = {
  init() {
    const toggle = document.getElementById('sidebarToggle');
    const close  = document.getElementById('sidebarClose');
    const overlay = document.getElementById('sidebarOverlay');
    const sidebar = document.getElementById('sidebar');

    toggle?.addEventListener('click', () => {
      if (window.innerWidth >= 992) {
        document.body.classList.toggle('sidebar-collapsed');
        localStorage.setItem('vs3-sidebar-collapsed',
          document.body.classList.contains('sidebar-collapsed'));
      } else {
        sidebar.classList.toggle('open');
        overlay.classList.toggle('active');
      }
    });

    close?.addEventListener('click',   () => this.closeMobile());
    overlay?.addEventListener('click', () => this.closeMobile());

    // Restore collapsed state on desktop
    if (window.innerWidth >= 992 &&
        localStorage.getItem('vs3-sidebar-collapsed') === 'true') {
      document.body.classList.add('sidebar-collapsed');
    }

    // Menu search
    document.getElementById('menuSearch')?.addEventListener('input', function () {
      const q = this.value.toLowerCase();
      document.querySelectorAll('.menu-item').forEach(item => {
        const txt = item.textContent.toLowerCase();
        item.style.display = (!q || txt.includes(q)) ? '' : 'none';
      });
      document.querySelectorAll('.menu-section').forEach(sec => {
        const visible = [...sec.querySelectorAll('.menu-item')]
          .some(i => i.style.display !== 'none');
        sec.style.display = visible ? '' : 'none';
      });
    });
  },
  closeMobile() {
    document.getElementById('sidebar')?.classList.remove('open');
    document.getElementById('sidebarOverlay')?.classList.remove('active');
  }
};

// ── Toast notifications ────────────────────────────────
const Toast = {
  show(message, type = 'success', duration = 3500) {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const icons = { success: 'check-circle', danger: 'times-circle',
                    warning: 'exclamation-triangle', info: 'info-circle' };
    const id = 'toast-' + Date.now();
    const html = `
      <div id="${id}" class="toast align-items-center text-bg-${type} border-0 mb-2" role="alert">
        <div class="d-flex">
          <div class="toast-body d-flex align-items-center gap-2">
            <i class="fas fa-${icons[type] || 'bell'}"></i> ${message}
          </div>
          <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
      </div>`;
    container.insertAdjacentHTML('beforeend', html);
    const el = document.getElementById(id);
    const t = new bootstrap.Toast(el, { delay: duration });
    t.show();
    el.addEventListener('hidden.bs.toast', () => el.remove());
  }
};

// ── DataTables defaults ────────────────────────────────
// DataTables reports internal errors (e.g. a malformed row) via a blocking
// native alert() by default — that freezes the whole page for a real user
// over what's usually a harmless warning. Log it instead.
if (window.jQuery && $.fn.dataTable) {
  $.fn.dataTable.ext.errMode = 'console';
}

function initDataTable(selector, options = {}) {
  const defaults = {
    pageLength: 25,
    responsive: true,
    dom: '<"row align-items-center mb-3"<"col-sm-6"l><"col-sm-6"f>>rtip',
    language: {
      search: '',
      searchPlaceholder: 'Search...',
      lengthMenu: 'Show _MENU_ entries',
      info: 'Showing _START_ to _END_ of _TOTAL_ records',
      emptyTable: 'No records found',
      zeroRecords: 'No matching records found'
    }
  };
  return $(selector).DataTable({ ...defaults, ...options });
}

// ── CSRF helper (form submissions) ────────────────────
function getCsrfToken() {
  return document.querySelector('meta[name="csrf-token"]')?.content || '';
}

// ── AJAX with JSON ─────────────────────────────────────
// Routes here return JSON bodies like {success:true,...} or {error:"..."}
// even on 4xx/5xx status codes — read the body first so callers checking
// res.error / res.success get the real reason instead of a generic
// "HTTP 400". Only throw when the response isn't valid JSON at all (a true
// network failure or an unhandled server error page).
async function apiCall(url, method = 'GET', data = null) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
  };
  if (data) opts.body = JSON.stringify(data);
  const res = await fetch(url, opts);
  let body;
  try {
    body = await res.json();
  } catch {
    throw new Error(`HTTP ${res.status}`);
  }
  if (!res.ok && !('error' in body) && !('success' in body)) {
    throw new Error(`HTTP ${res.status}`);
  }
  return body;
}

// ── Confirm dialog ─────────────────────────────────────
function confirmAction(message = 'Are you sure?') {
  return confirm(message);
}

// ── Currency formatter ─────────────────────────────────
function formatGHS(amount) {
  return 'GHS ' + parseFloat(amount || 0).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

// ── Number formatter ───────────────────────────────────
function formatNumber(n) {
  return parseFloat(n || 0).toLocaleString();
}

// ── Auto-dismiss flash messages ─────────────────────────
function initFlashAutoDismiss() {
  setTimeout(() => {
    document.querySelectorAll('.flash-alert').forEach(el => {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(el);
      bsAlert?.close();
    });
  }, 5000);
}

// ── Chart.js global defaults ───────────────────────────
function initChartDefaults() {
  if (typeof Chart === 'undefined') return;
  Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.color = getComputedStyle(document.documentElement)
    .getPropertyValue('--text-muted').trim() || '#64748b';
  Chart.defaults.plugins.legend.labels.boxWidth = 12;
  Chart.defaults.plugins.legend.labels.padding = 16;
}

// ── Brand colors palette for charts ───────────────────
const CHART_COLORS = [
  '#2563EB','#10b981','#f59e0b','#ef4444','#8b5cf6',
  '#14b8a6','#f97316','#ec4899','#06b6d4','#84cc16'
];

// ── Load & render a chart ──────────────────────────────
async function loadChart(canvasId, url, type, label, options = {}) {
  try {
    const data = await apiCall(url);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const gridColor = isDark ? 'rgba(255,255,255,.07)' : 'rgba(0,0,0,.06)';

    const chartData = {
      labels: data.labels,
      datasets: [{
        label,
        data: data.values,
        backgroundColor: type === 'line'
          ? 'rgba(37,99,235,.12)'
          : CHART_COLORS.slice(0, data.labels.length),
        borderColor: type === 'line' ? '#2563EB' : CHART_COLORS[0],
        borderWidth: type === 'line' ? 2 : 0,
        tension: 0.4,
        fill: type === 'line',
        pointRadius: 3,
        pointHoverRadius: 5,
        borderRadius: type === 'bar' ? 6 : 0,
        ...options.dataset
      }]
    };

    return new Chart(ctx, {
      type,
      data: chartData,
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: { display: type !== 'line' && type !== 'bar' },
          tooltip: { callbacks: {
            label: ctx => type === 'pie' || type === 'doughnut'
              ? `${ctx.label}: GHS ${ctx.raw.toLocaleString()}`
              : `GHS ${ctx.raw.toLocaleString()}`
          }}
        },
        scales: type !== 'pie' && type !== 'doughnut' ? {
          x: { grid: { color: gridColor }, ticks: { maxRotation: 45 } },
          y: { grid: { color: gridColor }, ticks: {
            callback: v => 'GHS ' + v.toLocaleString()
          }}
        } : undefined,
        ...options.chart
      }
    });
  } catch (err) {
    console.warn(`Chart ${canvasId} failed:`, err);
  }
}

// ── Search with debounce ───────────────────────────────
function debounce(fn, wait = 300) {
  let t;
  return function (...args) {
    const context = this;
    clearTimeout(t);
    t = setTimeout(() => fn.apply(context, args), wait);
  };
}

// ── Delete confirmation via POST form ──────────────────
document.addEventListener('click', e => {
  const btn = e.target.closest('[data-delete-url]');
  if (!btn) return;
  e.preventDefault();
  if (!confirmAction('Delete this record? This cannot be undone.')) return;
  const form = document.createElement('form');
  form.method = 'POST';
  form.action = btn.dataset.deleteUrl;
  document.body.appendChild(form);
  form.submit();
});

// ── Approve / Reject via AJAX ──────────────────────────
document.addEventListener('click', async e => {
  const btn = e.target.closest('[data-action-url]');
  if (!btn) return;
  e.preventDefault();
  const msg = btn.dataset.confirm || 'Confirm action?';
  if (!confirmAction(msg)) return;
  try {
    btn.disabled = true;
    const res = await apiCall(btn.dataset.actionUrl, 'POST');
    if (res.success) {
      Toast.show(btn.dataset.successMsg || 'Action completed.', 'success');
      setTimeout(() => location.reload(), 800);
    } else {
      Toast.show(res.error || 'Action failed.', 'danger');
      btn.disabled = false;
    }
  } catch {
    Toast.show('Network error.', 'danger');
    btn.disabled = false;
  }
});

// ── Init on DOM ready ──────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  ThemeManager.init();
  SidebarManager.init();
  initFlashAutoDismiss();
  initChartDefaults();

  // Tooltips
  document.querySelectorAll('[data-bs-toggle="tooltip"]')
    .forEach(el => new bootstrap.Tooltip(el));

  // Popovers
  document.querySelectorAll('[data-bs-toggle="popover"]')
    .forEach(el => new bootstrap.Popover(el));
});
