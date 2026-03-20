// OpenClaw Dashboard — pixel-art ops panel
// Vanilla JS, no dependencies. Auto-refreshes every 30s.

(function () {
  'use strict';

  const REFRESH_INTERVAL = 30000;
  const ACTIVITY_LIMIT = 20;
  let dashboardVisible = false;
  let refreshTimer = null;

  // ── Helpers ──────────────────────────────────────────────

  function relTime(ms) {
    if (!ms) return '—';
    const now = Date.now();
    const diff = ms - now;
    const abs = Math.abs(diff);
    let label;
    if (abs < 60000) label = Math.round(abs / 1000) + 's';
    else if (abs < 3600000) label = Math.round(abs / 60000) + 'm';
    else if (abs < 86400000) label = (abs / 3600000).toFixed(1) + 'h';
    else label = (abs / 86400000).toFixed(1) + 'd';
    return diff > 0 ? 'in ' + label : label + ' ago';
  }

  function fmtTokens(n) {
    if (!n) return '0';
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
    return String(n);
  }

  function fmtDuration(ms) {
    if (!ms) return '—';
    if (ms < 1000) return ms + 'ms';
    if (ms < 60000) return (ms / 1000).toFixed(1) + 's';
    return (ms / 60000).toFixed(1) + 'm';
  }

  function escHtml(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

  function statusDot(ok) {
    return '<span class="oc-dot ' + (ok ? 'oc-dot-green' : 'oc-dot-red') + '"></span>';
  }

  function jobStatusClass(job) {
    if (!job.enabled) return 'oc-job-disabled';
    if (job.consecutiveErrors > 0) return 'oc-job-error';
    return 'oc-job-ok';
  }

  function statusBadge(status) {
    const cls = status === 'ok' ? 'oc-badge-ok' : (status === 'error' ? 'oc-badge-err' : 'oc-badge-warn');
    return '<span class="oc-badge ' + cls + '">' + escHtml(status || '?') + '</span>';
  }

  // ── Data fetch ──────────────────────────────────────────

  async function fetchJSON(url) {
    try {
      const r = await fetch(url);
      if (!r.ok) return null;
      return await r.json();
    } catch (e) {
      return null;
    }
  }

  // ── Render functions ────────────────────────────────────

  function renderStatusBar(data) {
    const el = document.getElementById('oc-status-bar');
    if (!el || !data) return;
    const gw = data.gateway || {};
    const cr = data.cron || {};
    el.innerHTML =
      '<div class="oc-status-item">' + statusDot(gw.ok) + ' Gateway: ' + escHtml(gw.status || 'unknown') + '</div>' +
      '<div class="oc-status-item">⚙ Jobs: ' + (cr.enabled || 0) + '/' + (cr.total || 0) + ' enabled</div>' +
      (cr.erroring > 0 ? '<div class="oc-status-item oc-text-red">⚠ ' + cr.erroring + ' erroring</div>' : '<div class="oc-status-item oc-text-green">✓ all clear</div>');
  }

  function renderCronGrid(jobs) {
    const el = document.getElementById('oc-cron-grid');
    if (!el) return;
    if (!jobs || !jobs.length) { el.innerHTML = '<div class="oc-empty">No cron jobs found</div>'; return; }

    el.innerHTML = jobs.map(function (j) {
      const lr = j.lastRun || {};
      const cls = jobStatusClass(j);
      const indicatorIcon = !j.enabled ? '○' : (j.consecutiveErrors > 0 ? '✗' : '●');
      return '<div class="oc-job-card ' + cls + '">' +
        '<div class="oc-job-header">' +
          '<span class="oc-job-indicator">' + indicatorIcon + '</span>' +
          '<span class="oc-job-name">' + escHtml(j.name) + '</span>' +
        '</div>' +
        '<div class="oc-job-detail">' +
          '<span>Last: ' + relTime(lr.at) + (lr.durationMs ? ' (' + fmtDuration(lr.durationMs) + ')' : '') + '</span>' +
          '<span>Next: ' + relTime(j.nextRunAt) + '</span>' +
        '</div>' +
        '<div class="oc-job-meta">' +
          '<span>' + escHtml(j.schedule) + '</span>' +
          (j.model ? '<span class="oc-model-tag">' + escHtml(j.model.split('/').pop()) + '</span>' : '') +
          (j.consecutiveErrors > 0 ? '<span class="oc-err-count">err×' + j.consecutiveErrors + '</span>' : '') +
        '</div>' +
      '</div>';
    }).join('');
  }

  function renderActivity(runs) {
    const el = document.getElementById('oc-activity-feed');
    if (!el) return;
    if (!runs || !runs.length) { el.innerHTML = '<div class="oc-empty">No recent activity</div>'; return; }

    el.innerHTML = runs.map(function (r) {
      const ts = r.ts ? new Date(r.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '??:??';
      const day = r.ts ? new Date(r.ts).toLocaleDateString([], { month: 'short', day: 'numeric' }) : '';
      const tok = r.tokens || {};
      return '<div class="oc-activity-row" title="' + escHtml(r.summary || '') + '">' +
        '<span class="oc-act-time">' + day + ' ' + ts + '</span>' +
        statusBadge(r.status) +
        '<span class="oc-act-name">' + escHtml(r.jobName) + '</span>' +
        '<span class="oc-act-dur">' + fmtDuration(r.durationMs) + '</span>' +
        '<span class="oc-act-tok">' + fmtTokens(tok.total) + ' tok</span>' +
      '</div>';
    }).join('');
  }

  function renderCosts(data) {
    const el = document.getElementById('oc-costs-panel');
    if (!el || !data) return;

    const totals = data.totals || {};
    const byModel = data.byModel || {};
    const models = Object.keys(byModel);

    // Find max tokens for bar scaling
    let maxTok = 0;
    models.forEach(function (m) { if (byModel[m].totalTokens > maxTok) maxTok = byModel[m].totalTokens; });

    let html = '<div class="oc-costs-header">' +
      '<span>Last ' + (data.days || 7) + ' days</span>' +
      '<span class="oc-costs-total">' + fmtTokens(totals.totalTokens) + ' tokens · ' + (totals.runs || 0) + ' runs</span>' +
    '</div>';

    if (models.length) {
      html += '<div class="oc-costs-models">';
      // Sort by total tokens descending
      models.sort(function (a, b) { return (byModel[b].totalTokens || 0) - (byModel[a].totalTokens || 0); });
      models.forEach(function (m) {
        const d = byModel[m];
        const pct = maxTok > 0 ? Math.max(2, Math.round((d.totalTokens / maxTok) * 100)) : 2;
        html += '<div class="oc-cost-row">' +
          '<span class="oc-cost-model">' + escHtml(m.split('/').pop()) + '</span>' +
          '<div class="oc-cost-bar-wrap"><div class="oc-cost-bar" style="width:' + pct + '%"></div></div>' +
          '<span class="oc-cost-val">' + fmtTokens(d.totalTokens) + ' (' + d.runs + ')</span>' +
        '</div>';
      });
      html += '</div>';
    }

    el.innerHTML = html;
  }

  // ── Sessions & Agents ────────────────────────────────────

  function sessionStatusDot(status) {
    if (status === 'active') return '<span class="oc-dot oc-dot-green"></span>';
    if (status === 'recent') return '<span class="oc-dot oc-dot-yellow"></span>';
    return '<span class="oc-dot oc-dot-dim"></span>';
  }

  function agentStateBadge(state) {
    var colors = {
      executing: 'oc-badge-ok',
      writing: 'oc-badge-warn',
      researching: 'oc-badge-info',
      idle: 'oc-badge-dim',
      error: 'oc-badge-err',
      syncing: 'oc-badge-warn',
    };
    var cls = colors[state] || 'oc-badge-dim';
    return '<span class="oc-badge ' + cls + '">' + escHtml(state || 'idle') + '</span>';
  }

  function renderSessions(sessions) {
    var el = document.getElementById('oc-sessions-list');
    if (!el) return;
    if (!sessions || !sessions.length) {
      el.innerHTML = '<div class="oc-empty">No sessions found</div>';
      return;
    }

    // Show only active and recent by default
    var shown = sessions.filter(function (s) { return s.status === 'active' || s.status === 'recent'; });
    if (!shown.length) shown = sessions.slice(0, 5);

    el.innerHTML = shown.map(function (s) {
      var name = s.displayName || s.sessionKey || '?';
      // Clean up display name
      if (name.length > 50) name = name.substring(0, 47) + '…';
      var model = (s.model || '').split('/').pop();
      return '<div class="oc-session-row">' +
        sessionStatusDot(s.status) +
        '<span class="oc-session-name" title="' + escHtml(s.sessionKey) + '">' + escHtml(name) + '</span>' +
        (model ? '<span class="oc-model-tag">' + escHtml(model) + '</span>' : '') +
        '<span class="oc-session-time">' + escHtml(s.updatedAtRelative || '—') + '</span>' +
        '<span class="oc-session-tok">' + fmtTokens(s.totalTokens) + '</span>' +
      '</div>';
    }).join('');

    if (sessions.length > shown.length) {
      el.innerHTML += '<div class="oc-session-more">+ ' + (sessions.length - shown.length) + ' idle sessions</div>';
    }
  }

  function renderSubagents(subagents) {
    var el = document.getElementById('oc-subagents-list');
    if (!el) return;
    if (!subagents || !subagents.length) {
      el.innerHTML = '<div class="oc-empty">No subagent runs</div>';
      return;
    }

    // Show the most recent 10
    var shown = subagents.slice(0, 10);

    el.innerHTML = shown.map(function (r) {
      var statusCls = r.status === 'ok' ? 'oc-sa-ok' : (r.status === 'error' ? 'oc-sa-err' : 'oc-sa-running');
      var statusIcon = r.status === 'ok' ? '✓' : (r.status === 'error' ? '✗' : '◉');
      var model = (r.model || '').split('/').pop();
      var task = r.task || '';
      if (task.length > 100) task = task.substring(0, 97) + '…';
      return '<div class="oc-sa-card ' + statusCls + '">' +
        '<div class="oc-sa-header">' +
          '<span class="oc-sa-icon">' + statusIcon + '</span>' +
          '<span class="oc-sa-label">' + escHtml(r.label || r.runId || '?') + '</span>' +
          (model ? '<span class="oc-model-tag">' + escHtml(model) + '</span>' : '') +
        '</div>' +
        '<div class="oc-sa-time">' + escHtml(r.createdAtRelative || '—') + '</div>' +
        (task ? '<div class="oc-sa-task" title="' + escHtml(r.task || '') + '">' + escHtml(task) + '</div>' : '') +
      '</div>';
    }).join('');
  }

  function renderAgentsRoster(agents) {
    var el = document.getElementById('oc-agents-roster');
    if (!el) return;
    if (!agents || !agents.length) {
      el.innerHTML = '<div class="oc-empty">No agents active</div>';
      return;
    }

    el.innerHTML = agents.map(function (a) {
      var icon = a.type === 'main' ? '🔥' : (a.type === 'subagent' ? '⚡' : '⏰');
      var model = (a.model || '').split('/').pop();
      var detail = a.detail || '';
      if (detail.length > 60) detail = detail.substring(0, 57) + '…';
      return '<div class="oc-agent-row">' +
        '<span class="oc-agent-icon">' + icon + '</span>' +
        '<span class="oc-agent-name">' + escHtml(a.name) + '</span>' +
        agentStateBadge(a.state) +
        (model ? '<span class="oc-model-tag">' + escHtml(model) + '</span>' : '') +
        '<span class="oc-agent-detail" title="' + escHtml(a.detail || '') + '">' + escHtml(detail) + '</span>' +
      '</div>';
    }).join('');
  }

  // ── Data refresh ────────────────────────────────────────

  async function refreshAll() {
    const [status, cron, activity, costs, sessions, subagents, agentsCombined] = await Promise.all([
      fetchJSON('/openclaw/status'),
      fetchJSON('/openclaw/cron'),
      fetchJSON('/openclaw/activity?limit=' + ACTIVITY_LIMIT),
      fetchJSON('/openclaw/costs?days=7'),
      fetchJSON('/openclaw/sessions?limit=50'),
      fetchJSON('/openclaw/subagents'),
      fetchJSON('/openclaw/agents'),
    ]);
    renderStatusBar(status);
    renderCronGrid(cron);
    renderActivity(activity);
    renderCosts(costs);
    renderSessions(sessions);
    renderSubagents(subagents);
    renderAgentsRoster(agentsCombined);

    // Update last-refresh timestamp
    const ts = document.getElementById('oc-last-refresh');
    if (ts) ts.textContent = 'Updated ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  // ── Toggle logic ────────────────────────────────────────

  function toggleDashboard(forceState) {
    const panel = document.getElementById('oc-dashboard');
    const btn = document.getElementById('oc-dashboard-toggle');
    if (!panel) return;

    dashboardVisible = typeof forceState === 'boolean' ? forceState : !dashboardVisible;
    panel.style.display = dashboardVisible ? 'block' : 'none';
    if (btn) btn.textContent = dashboardVisible ? '▼ Dashboard' : '▲ Dashboard';

    if (dashboardVisible) {
      refreshAll();
      if (!refreshTimer) refreshTimer = setInterval(refreshAll, REFRESH_INTERVAL);
    } else {
      if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null; }
    }
  }

  // ── Build DOM ───────────────────────────────────────────

  function buildDashboard() {
    // Toggle button — placed after bottom-panels
    const toggle = document.createElement('button');
    toggle.id = 'oc-dashboard-toggle';
    toggle.textContent = '▲ Dashboard';
    toggle.className = 'oc-toggle-btn';
    toggle.addEventListener('click', function () { toggleDashboard(); });

    // Dashboard panel
    const panel = document.createElement('div');
    panel.id = 'oc-dashboard';
    panel.style.display = 'none';
    panel.innerHTML =
      '<div class="oc-panel-header">' +
        '<span class="oc-panel-title">≡ OPENCLAW OPS</span>' +
        '<span id="oc-last-refresh" class="oc-refresh-ts"></span>' +
        '<button class="oc-refresh-btn" onclick="document.dispatchEvent(new Event(\'oc-refresh\'))">↻</button>' +
      '</div>' +
      '<div id="oc-status-bar" class="oc-status-bar">Loading…</div>' +
      '<div class="oc-section-label">WHO\'S IN THE OFFICE</div>' +
      '<div id="oc-agents-roster" class="oc-agents-roster"></div>' +
      '<div class="oc-two-col">' +
        '<div class="oc-col">' +
          '<div class="oc-section-label">ACTIVE SESSIONS</div>' +
          '<div id="oc-sessions-list" class="oc-sessions-list"></div>' +
        '</div>' +
        '<div class="oc-col">' +
          '<div class="oc-section-label">SUBAGENT RUNS</div>' +
          '<div id="oc-subagents-list" class="oc-subagents-list"></div>' +
        '</div>' +
      '</div>' +
      '<div class="oc-section-label">CRON JOBS</div>' +
      '<div id="oc-cron-grid" class="oc-cron-grid"></div>' +
      '<div class="oc-two-col">' +
        '<div class="oc-col">' +
          '<div class="oc-section-label">RECENT ACTIVITY</div>' +
          '<div id="oc-activity-feed" class="oc-activity-feed"></div>' +
        '</div>' +
        '<div class="oc-col">' +
          '<div class="oc-section-label">TOKEN USAGE (7d)</div>' +
          '<div id="oc-costs-panel" class="oc-costs-panel"></div>' +
        '</div>' +
      '</div>';

    // Find insertion point: after #bottom-panels inside #main-stage
    const mainStage = document.getElementById('main-stage');
    if (mainStage) {
      const bottomPanels = document.getElementById('bottom-panels');
      if (bottomPanels && bottomPanels.nextSibling) {
        mainStage.insertBefore(toggle, bottomPanels.nextSibling);
        mainStage.insertBefore(panel, toggle.nextSibling);
      } else {
        mainStage.appendChild(toggle);
        mainStage.appendChild(panel);
      }
    } else {
      document.body.appendChild(toggle);
      document.body.appendChild(panel);
    }

    // Listen for manual refresh
    document.addEventListener('oc-refresh', function () { refreshAll(); });

    // Keyboard shortcut: Ctrl+D to toggle
    document.addEventListener('keydown', function (e) {
      if (e.ctrlKey && e.key === 'd') {
        e.preventDefault();
        toggleDashboard();
      }
    });
  }

  // ── Init ────────────────────────────────────────────────

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', buildDashboard);
  } else {
    buildDashboard();
  }

})();
