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
      var jobId = j.id || '';
      return '<div class="oc-job-card ' + cls + ' oc-clickable" data-job-id="' + escHtml(jobId) + '" data-job-name="' + escHtml(j.name) + '">' +
        '<div class="oc-job-header">' +
          '<span class="oc-job-indicator">' + indicatorIcon + '</span>' +
          '<span class="oc-job-name">' + escHtml(j.name) + '</span>' +
          '<span class="oc-expand-icon">▸</span>' +
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
        '<div class="oc-job-expanded" style="display:none;"></div>' +
      '</div>';
    }).join('');

    // Bind click handlers for expansion
    el.querySelectorAll('.oc-job-card.oc-clickable').forEach(function(card) {
      card.addEventListener('click', function() {
        var expanded = card.querySelector('.oc-job-expanded');
        var icon = card.querySelector('.oc-expand-icon');
        if (!expanded) return;
        var isOpen = expanded.style.display !== 'none';
        if (isOpen) {
          expanded.style.display = 'none';
          card.classList.remove('oc-expanded');
          if (icon) icon.textContent = '▸';
          return;
        }
        // Close other expanded cards
        el.querySelectorAll('.oc-job-expanded').forEach(function(e) { e.style.display = 'none'; });
        el.querySelectorAll('.oc-expand-icon').forEach(function(e) { e.textContent = '▸'; });
        el.querySelectorAll('.oc-job-card').forEach(function(e) { e.classList.remove('oc-expanded'); });

        expanded.innerHTML = '<div style="color:#484f58;padding:8px;font-style:italic;">Loading...</div>';
        expanded.style.display = 'block';
        card.classList.add('oc-expanded');
        if (icon) icon.textContent = '▾';

        var jobId = card.getAttribute('data-job-id');
        var jobName = card.getAttribute('data-job-name');

        // Fetch detail
        fetchJSON('/openclaw/agent/' + encodeURIComponent(jobName)).then(function(data) {
          if (!data || data.error) {
            expanded.innerHTML = '<div style="color:#484f58;padding:8px;">Data unavailable</div>';
            return;
          }
          var html = '<div style="padding:6px 0;border-top:1px dashed #2d2218;margin-top:6px;">';
          html += '<div style="font-size:11px;color:#8b949e;margin-bottom:4px;">';
          if (data.schedule) html += '📅 ' + escHtml(data.schedule);
          if (data.tz) html += ' (' + escHtml(data.tz) + ')';
          html += '</div>';
          if (data.nextRunAtRelative) {
            html += '<div style="font-size:11px;color:#e8a849;margin-bottom:6px;">Next: ' + escHtml(data.nextRunAtRelative) + '</div>';
          }

          if (data.recentRuns && data.recentRuns.length > 0) {
            html += '<div style="font-size:10px;color:#484f58;margin-bottom:4px;letter-spacing:1px;">RECENT RUNS</div>';
            data.recentRuns.slice(0, 5).forEach(function(run) {
              var ts = run.ts ? new Date(run.ts).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '?';
              var dur = run.durationMs ? fmtDuration(run.durationMs) : '—';
              var tok = run.tokens ? fmtTokens(run.tokens.total || 0) : '0';
              var status = run.status || '?';
              var statusColor = status === 'ok' ? '#3fb950' : (status === 'error' ? '#f85149' : '#d29922');
              html += '<div style="font-size:10px;padding:2px 0;display:flex;gap:4px;align-items:center;border-bottom:1px solid rgba(45,34,24,0.5);">';
              html += '<span style="color:#484f58;min-width:80px;">' + ts + '</span>';
              html += '<span style="color:' + statusColor + ';">' + status + '</span>';
              html += '<span style="color:#8b949e;">' + dur + '</span>';
              html += '<span style="color:#e8a849;margin-left:auto;">' + tok + '</span>';
              html += '</div>';
              if (run.summary) {
                html += '<div style="font-size:9px;color:#484f58;padding:1px 0 3px;white-space:pre-wrap;max-height:40px;overflow:hidden;">' + escHtml(run.summary.substring(0, 150)) + '</div>';
              }
            });
          }
          html += '</div>';
          expanded.innerHTML = html;
        });
      });
    });
  }

  function renderActivity(runs) {
    const el = document.getElementById('oc-activity-feed');
    if (!el) return;
    if (!runs || !runs.length) { el.innerHTML = '<div class="oc-empty">No recent activity</div>'; return; }

    el.innerHTML = runs.map(function (r, i) {
      const ts = r.ts ? new Date(r.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '??:??';
      const day = r.ts ? new Date(r.ts).toLocaleDateString([], { month: 'short', day: 'numeric' }) : '';
      const tok = r.tokens || {};
      var summaryFull = r.summary || '';
      var modelStr = r.model ? (r.model.split('/').pop()) : '';
      var providerStr = r.provider || '';
      var deliveredStr = r.delivered != null ? String(r.delivered) : '';
      return '<div class="oc-activity-row oc-clickable" data-idx="' + i + '">' +
        '<span class="oc-act-time">' + day + ' ' + ts + '</span>' +
        statusBadge(r.status) +
        '<span class="oc-act-name">' + escHtml(r.jobName) + '</span>' +
        '<span class="oc-act-dur">' + fmtDuration(r.durationMs) + '</span>' +
        '<span class="oc-act-tok">' + fmtTokens(tok.total) + ' tok</span>' +
        '<div class="oc-act-expanded" style="display:none;" data-summary="' + escHtml(summaryFull) + '" data-model="' + escHtml(modelStr) + '" data-provider="' + escHtml(providerStr) + '" data-delivered="' + escHtml(deliveredStr) + '" data-tok-in="' + (tok.input || 0) + '" data-tok-out="' + (tok.output || 0) + '" data-tok-total="' + (tok.total || 0) + '"></div>' +
      '</div>';
    }).join('');

    // Bind click handlers
    el.querySelectorAll('.oc-activity-row.oc-clickable').forEach(function(row) {
      row.addEventListener('click', function() {
        var expanded = row.querySelector('.oc-act-expanded');
        if (!expanded) return;
        var isOpen = expanded.style.display !== 'none';
        // Close all
        el.querySelectorAll('.oc-act-expanded').forEach(function(e) { e.style.display = 'none'; });
        el.querySelectorAll('.oc-activity-row').forEach(function(e) { e.classList.remove('oc-expanded'); });
        if (isOpen) return;

        var summary = expanded.getAttribute('data-summary') || '';
        var model = expanded.getAttribute('data-model') || '';
        var provider = expanded.getAttribute('data-provider') || '';
        var delivered = expanded.getAttribute('data-delivered') || '';
        var tokIn = expanded.getAttribute('data-tok-in') || '0';
        var tokOut = expanded.getAttribute('data-tok-out') || '0';
        var tokTotal = expanded.getAttribute('data-tok-total') || '0';

        var html = '<div style="padding:6px 4px;border-top:1px dashed #2d2218;margin-top:4px;font-size:10px;">';
        if (model) html += '<div style="color:#8b949e;">Model: <span style="color:#e8a849;">' + model + '</span></div>';
        if (provider) html += '<div style="color:#8b949e;">Provider: ' + provider + '</div>';
        html += '<div style="color:#8b949e;">Tokens: In ' + fmtTokens(parseInt(tokIn)) + ' / Out ' + fmtTokens(parseInt(tokOut)) + ' / Total ' + fmtTokens(parseInt(tokTotal)) + '</div>';
        if (delivered) html += '<div style="color:#8b949e;">Delivered: ' + delivered + '</div>';
        if (summary) html += '<div style="color:#c9d1d9;margin-top:4px;white-space:pre-wrap;max-height:100px;overflow-y:auto;border:1px solid #2d2218;padding:4px;background:#120e0a;">' + escHtml(summary) + '</div>';
        html += '</div>';
        expanded.innerHTML = html;
        expanded.style.display = 'block';
        row.classList.add('oc-expanded');
      });
    });
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

  // ── Usage & Limits ───────────────────────────────────────

  function fmtCost(n) {
    if (n == null) return '$0.00';
    return '$' + n.toFixed(2);
  }

  function budgetBarClass(pct) {
    if (pct == null) return 'oc-bar-green';
    if (pct >= 0.8) return 'oc-bar-red';
    if (pct >= 0.5) return 'oc-bar-yellow';
    return 'oc-bar-green';
  }

  function todayDotClass(pct) {
    if (pct == null) return 'oc-today-green';
    if (pct >= 0.8) return 'oc-today-red';
    if (pct >= 0.5) return 'oc-today-yellow';
    return 'oc-today-green';
  }

  function renderUsagePanel(data) {
    var el = document.getElementById('oc-usage-panel');
    if (!el || !data) { if (el) el.innerHTML = '<div class="oc-empty">Usage data unavailable</div>'; return; }

    var html = '';

    // Warnings
    if (data.warnings && data.warnings.length) {
      html += '<div class="oc-usage-warnings">';
      data.warnings.forEach(function (w) {
        var isRed = w.indexOf('🔴') > -1;
        html += '<div class="oc-usage-warning' + (isRed ? ' oc-usage-warning-red' : '') + '">' + escHtml(w) + '</div>';
      });
      html += '</div>';
    }

    // Budget meter
    var budget = data.monthlyBudget;
    var totalCost = data.totalEstimatedCost || 0;
    var budgetPct = data.budgetPercent;
    var barPct = budgetPct != null ? Math.min(budgetPct * 100, 100) : 0;
    var barCls = budgetBarClass(budgetPct);

    html += '<div class="oc-usage-budget-wrap">';
    html += '<div class="oc-usage-budget-header">';
    html += '<span class="oc-usage-budget-label">Monthly Budget</span>';
    html += '<span class="oc-usage-budget-amount">' + fmtCost(totalCost) + (budget ? ' / ' + fmtCost(budget) : '') + '</span>';
    html += '</div>';
    html += '<div class="oc-usage-bar-track">';
    html += '<div class="oc-usage-bar-fill ' + barCls + '" style="width:' + barPct + '%"></div>';
    if (budgetPct != null) {
      html += '<span class="oc-usage-bar-pct">' + Math.round(budgetPct * 100) + '%</span>';
    }
    html += '</div>';
    html += '</div>';

    // Provider cards
    var providers = data.byProvider || {};
    var providerKeys = Object.keys(providers).filter(function (k) { return k !== 'unknown' && k !== 'other'; });
    providerKeys.sort(function (a, b) { return (providers[b].estimatedCost || 0) - (providers[a].estimatedCost || 0); });

    if (providerKeys.length) {
      html += '<div class="oc-usage-providers">';
      providerKeys.forEach(function (pname) {
        var p = providers[pname];
        html += '<div class="oc-usage-provider-card">';
        html += '<div class="oc-usage-provider-name">' + escHtml(pname) + '</div>';
        html += '<div class="oc-usage-provider-cost">' + fmtCost(p.estimatedCost) + '</div>';
        html += '<div class="oc-usage-provider-tokens">' + fmtTokens(p.totalTokens) + ' tokens · ' + (p.sessions || 0) + ' sessions</div>';
        if (p.cacheRead) {
          html += '<div class="oc-usage-provider-tokens">Cache: ' + fmtTokens(p.cacheRead) + '</div>';
        }
        if (p.limit) {
          html += '<div class="oc-usage-provider-tokens">Limit: ' + fmtCost(p.limit) + ' (' + Math.round((p.percentUsed || 0) * 100) + '%)</div>';
        }
        html += '</div>';
      });
      html += '</div>';
    }

    // Model breakdown
    var models = data.byModel || {};
    var modelKeys = Object.keys(models).filter(function (k) { return k !== 'unknown'; });
    modelKeys.sort(function (a, b) { return (models[b].estimatedCost || 0) - (models[a].estimatedCost || 0); });

    if (modelKeys.length) {
      var maxModelCost = 0;
      modelKeys.forEach(function (m) { if (models[m].estimatedCost > maxModelCost) maxModelCost = models[m].estimatedCost; });

      html += '<div class="oc-usage-models">';
      html += '<div style="font-size:10px;color:#484f58;letter-spacing:1px;margin-bottom:4px;">BY MODEL</div>';
      modelKeys.forEach(function (m) {
        var d = models[m];
        var pct = maxModelCost > 0 ? Math.max(3, Math.round((d.estimatedCost / maxModelCost) * 100)) : 3;
        html += '<div class="oc-usage-model-row">';
        html += '<span class="oc-usage-model-name">' + escHtml(m) + '</span>';
        html += '<div class="oc-usage-model-bar-wrap"><div class="oc-usage-model-bar" style="width:' + pct + '%"></div></div>';
        html += '<span class="oc-usage-model-cost">' + fmtCost(d.estimatedCost) + '</span>';
        html += '</div>';
      });
      html += '</div>';
    }

    // Daily trend sparkline
    var byDay = data.byDay || [];
    if (byDay.length > 1) {
      var maxDayCost = 0;
      byDay.forEach(function (d) { if (d.estimatedCost > maxDayCost) maxDayCost = d.estimatedCost; });

      html += '<div style="font-size:10px;color:#484f58;letter-spacing:1px;margin-bottom:4px;">DAILY SPEND</div>';
      html += '<div class="oc-usage-sparkline">';
      byDay.forEach(function (d) {
        var h = maxDayCost > 0 ? Math.max(2, Math.round((d.estimatedCost / maxDayCost) * 36)) : 2;
        var shortDate = d.date.substring(5); // MM-DD
        html += '<div class="oc-usage-spark-bar" style="height:' + h + 'px" data-tip="' + shortDate + ': ' + fmtCost(d.estimatedCost) + '"></div>';
      });
      html += '</div>';
      if (byDay.length >= 2) {
        html += '<div class="oc-usage-spark-label">';
        html += '<span>' + byDay[0].date.substring(5) + '</span>';
        html += '<span>' + byDay[byDay.length - 1].date.substring(5) + '</span>';
        html += '</div>';
      }
    }

    // Today's badge
    var today = data.today;
    if (today) {
      var todayCls = todayDotClass(today.budgetPercent);
      html += '<div style="margin-top:8px;display:flex;align-items:center;gap:8px;">';
      html += '<div class="oc-usage-today-badge">';
      html += '<span class="oc-usage-today-dot ' + todayCls + '"></span>';
      html += 'Today: ' + fmtCost(today.estimatedCost);
      if (today.dailyBudget) html += ' / ' + fmtCost(today.dailyBudget);
      html += ' · ' + (today.sessions || 0) + ' sessions';
      html += '</div>';
      html += '</div>';
    }

    el.innerHTML = html;

    // Update the usage indicator badge in the main UI
    updateUsageIndicator(data);
  }

  function updateUsageIndicator(data) {
    // Create or update a small usage badge in the top-right of main-stage
    var badge = document.getElementById('oc-usage-indicator');
    if (!badge) {
      badge = document.createElement('div');
      badge.id = 'oc-usage-indicator';
      badge.style.cssText = 'position:fixed;top:8px;right:8px;z-index:9999;padding:3px 8px;font-family:ArkPixel,monospace;font-size:10px;border:1px solid #2d2218;background:#1e1710;cursor:pointer;opacity:0.85;transition:opacity 0.2s;';
      badge.addEventListener('mouseenter', function () { badge.style.opacity = '1'; });
      badge.addEventListener('mouseleave', function () { badge.style.opacity = '0.85'; });
      badge.addEventListener('click', function () { toggleDashboard(true); });
      document.body.appendChild(badge);
    }

    var today = data && data.today;
    if (!today) { badge.style.display = 'none'; return; }

    badge.style.display = 'block';
    var pct = today.budgetPercent;
    var dotColor = '#3fb950'; // green
    if (pct != null && pct >= 0.8) dotColor = '#f85149';
    else if (pct != null && pct >= 0.5) dotColor = '#d29922';

    badge.innerHTML = '<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:' + dotColor + ';margin-right:4px;"></span>' +
      fmtCost(today.estimatedCost) + '/day';
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

  function cleanSessionKey(key) {
    // Clean up raw session keys like "agent:main:subagent:3e73235b-..." to something readable
    if (!key) return '?';
    // Remove common prefixes
    var cleaned = key.replace(/^agent:main:/, '').replace(/^agent:/, '');
    // Shorten UUIDs
    cleaned = cleaned.replace(/([0-9a-f]{8})-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, '$1…');
    return cleaned;
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

    el.innerHTML = shown.map(function (s, i) {
      var name = s.displayName || cleanSessionKey(s.sessionKey);
      var truncName = name.length > 50 ? name.substring(0, 47) + '…' : name;
      var model = (s.model || '').split('/').pop();
      var provider = s.modelProvider || '';
      return '<div class="oc-session-row oc-clickable" data-idx="' + i + '">' +
        sessionStatusDot(s.status) +
        '<span class="oc-session-name" title="' + escHtml(s.sessionKey) + '">' + escHtml(truncName) + '</span>' +
        (model ? '<span class="oc-model-tag">' + escHtml(model) + '</span>' : '') +
        '<span class="oc-session-time">' + escHtml(s.updatedAtRelative || '—') + '</span>' +
        '<span class="oc-session-tok">' + fmtTokens(s.totalTokens) + '</span>' +
        '<div class="oc-session-expanded" style="display:none;"' +
          ' data-key="' + escHtml(s.sessionKey || '') + '"' +
          ' data-channel="' + escHtml(s.channel || '') + '"' +
          ' data-chat-type="' + escHtml(s.chatType || '') + '"' +
          ' data-model="' + escHtml(s.model || '') + '"' +
          ' data-provider="' + escHtml(provider) + '"' +
          ' data-compaction="' + (s.compactionCount || 0) + '"' +
          ' data-display-name="' + escHtml(s.displayName || '') + '"' +
          ' data-cache-read="' + (s.cacheRead || 0) + '"' +
          ' data-in-tok="' + (s.inputTokens || 0) + '"' +
          ' data-out-tok="' + (s.outputTokens || 0) + '"' +
        '></div>' +
      '</div>';
    }).join('');

    if (sessions.length > shown.length) {
      el.innerHTML += '<div class="oc-session-more">+ ' + (sessions.length - shown.length) + ' idle sessions</div>';
    }

    // Bind click handlers
    el.querySelectorAll('.oc-session-row.oc-clickable').forEach(function(row) {
      row.addEventListener('click', function() {
        var expanded = row.querySelector('.oc-session-expanded');
        if (!expanded) return;
        var isOpen = expanded.style.display !== 'none';
        // Close all
        el.querySelectorAll('.oc-session-expanded').forEach(function(e) { e.style.display = 'none'; });
        el.querySelectorAll('.oc-session-row').forEach(function(e) { e.classList.remove('oc-expanded'); });
        if (isOpen) return;

        var html = '<div style="padding:6px 4px;border-top:1px dashed #2d2218;margin-top:4px;font-size:10px;">';
        var key = expanded.getAttribute('data-key');
        var channel = expanded.getAttribute('data-channel');
        var chatType = expanded.getAttribute('data-chat-type');
        var model = expanded.getAttribute('data-model');
        var provider = expanded.getAttribute('data-provider');
        var compaction = expanded.getAttribute('data-compaction');
        var displayName = expanded.getAttribute('data-display-name');
        var cacheRead = expanded.getAttribute('data-cache-read');
        var inTok = expanded.getAttribute('data-in-tok');
        var outTok = expanded.getAttribute('data-out-tok');

        if (displayName) html += '<div style="color:#e6edf3;">Name: ' + displayName + '</div>';
        if (key) html += '<div style="color:#8b949e;word-break:break-all;">Key: ' + key + '</div>';
        if (channel) html += '<div style="color:#8b949e;">Channel: ' + channel + (chatType ? ' (' + chatType + ')' : '') + '</div>';
        if (model) html += '<div style="color:#8b949e;">Model: <span style="color:#e8a849;">' + model + '</span></div>';
        if (provider) html += '<div style="color:#8b949e;">Provider: ' + provider + '</div>';
        html += '<div style="color:#8b949e;">Tokens: In ' + fmtTokens(parseInt(inTok)) + ' / Out ' + fmtTokens(parseInt(outTok)) + '</div>';
        if (parseInt(compaction) > 0) html += '<div style="color:#8b949e;">Compactions: ' + compaction + '</div>';
        if (parseInt(cacheRead) > 0) html += '<div style="color:#8b949e;">Cache read: ' + fmtTokens(parseInt(cacheRead)) + '</div>';
        html += '</div>';
        expanded.innerHTML = html;
        expanded.style.display = 'block';
        row.classList.add('oc-expanded');
      });
    });
  }

  function renderSubagents(subagents) {
    var el = document.getElementById('oc-subagents-list');
    if (!el) return;
    if (!subagents || !subagents.length) {
      el.innerHTML = '<div class="oc-empty">No subagent runs</div>';
      return;
    }

    // Filter out dismissed subagents from display
    subagents = subagents.filter(function(r) { return !r.dismissed; });
    if (!subagents.length) {
      el.innerHTML = '<div class="oc-empty">No subagent runs</div>';
      return;
    }

    // Show the most recent 10
    var shown = subagents.slice(0, 10);

    el.innerHTML = shown.map(function (r) {
      var statusCls = r.status === 'ok' ? 'oc-sa-ok' : (r.status === 'error' ? 'oc-sa-err' : 'oc-sa-running');
      var statusIcon = r.status === 'ok' ? '✓' : (r.status === 'error' ? '✗' : '◉');
      var model = (r.model || '').split('/').pop();
      var fullTask = r.task || '';
      var truncTask = fullTask.length > 300 ? fullTask.substring(0, 297) + '…' : fullTask;
      var dismissBtn = '';
      var isCompleted = r.status === 'ok' || r.status === 'completed';
      var isDismissed = r.dismissed === true;
      if (isCompleted && !isDismissed) {
        dismissBtn = '<button class="oc-sa-dismiss" data-label="' + escHtml(r.label || r.runId || '') + '" title="Dismiss" style="' +
          'position:absolute;top:4px;right:4px;background:none;border:1px solid #5c3d1a;' +
          'color:#e8a849;font-size:12px;width:20px;height:20px;line-height:18px;' +
          'cursor:pointer;border-radius:3px;padding:0;font-family:ArkPixel,monospace;' +
          'opacity:0;transition:opacity 0.2s;' +
        '">✕</button>';
      }
      return '<div class="oc-sa-card ' + statusCls + ' oc-expandable' + (isDismissed ? ' oc-sa-dismissed' : '') + '" onclick="this.classList.toggle(\'expanded\')" style="position:relative;">' +
        dismissBtn +
        '<div class="oc-sa-header">' +
          '<span class="oc-sa-icon">' + statusIcon + '</span>' +
          '<span class="oc-sa-label">' + escHtml(r.label || r.runId || '?') + '</span>' +
          (model ? '<span class="oc-model-tag">' + escHtml(model) + '</span>' : '') +
        '</div>' +
        '<div class="oc-sa-time">' + escHtml(r.createdAtRelative || '—') + '</div>' +
        (fullTask ? '<div class="oc-sa-task oc-truncatable" data-full="' + escHtml(fullTask) + '" data-short="' + escHtml(truncTask) + '">' + escHtml(truncTask) + '</div>' : '') +
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
      var fullDetail = a.detail || '';
      var truncDetail = fullDetail.length > 200 ? fullDetail.substring(0, 197) + '…' : fullDetail;
      return '<div class="oc-agent-row oc-expandable" onclick="this.classList.toggle(\'expanded\')">' +
        '<span class="oc-agent-icon">' + icon + '</span>' +
        '<span class="oc-agent-name">' + escHtml(a.name) + '</span>' +
        agentStateBadge(a.state) +
        (model ? '<span class="oc-model-tag">' + escHtml(model) + '</span>' : '') +
        '<span class="oc-agent-detail oc-truncatable" data-full="' + escHtml(fullDetail) + '" data-short="' + escHtml(truncDetail) + '">' + escHtml(truncDetail) + '</span>' +
      '</div>';
    }).join('');
  }

  // ── Data refresh ────────────────────────────────────────

  async function refreshAll() {
    const [status, cron, activity, costs, sessions, subagents, agentsCombined, usage] = await Promise.all([
      fetchJSON('/openclaw/status'),
      fetchJSON('/openclaw/cron'),
      fetchJSON('/openclaw/activity?limit=' + ACTIVITY_LIMIT),
      fetchJSON('/openclaw/costs?days=7'),
      fetchJSON('/openclaw/sessions?limit=50'),
      fetchJSON('/openclaw/subagents'),
      fetchJSON('/openclaw/agents'),
      fetchJSON('/openclaw/usage?period=current_month'),
    ]);
    renderStatusBar(status);
    renderUsagePanel(usage);
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
        '<span class="oc-panel-title">🔥 THE HEARTH OPS</span>' +
        '<span id="oc-last-refresh" class="oc-refresh-ts"></span>' +
        '<button class="oc-refresh-btn" onclick="document.dispatchEvent(new Event(\'oc-refresh\'))">↻</button>' +
      '</div>' +
      '<div id="oc-status-bar" class="oc-status-bar">Loading…</div>' +
      '<div class="oc-section-label">USAGE &amp; LIMITS</div>' +
      '<div id="oc-usage-panel" class="oc-usage-panel">Loading…</div>' +
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

    // Click-to-expand: toggle truncated text in expandable rows
    panel.addEventListener('click', function (e) {
      var expandable = e.target.closest('.oc-expandable');
      if (!expandable) return;
      var truncatables = expandable.querySelectorAll('.oc-truncatable');
      var isExpanded = expandable.classList.contains('expanded');
      truncatables.forEach(function (el) {
        if (isExpanded) {
          el.textContent = el.getAttribute('data-full') || el.textContent;
        } else {
          el.textContent = el.getAttribute('data-short') || el.textContent;
        }
      });
    });

    // Add expand/collapse styles
    var expandStyle = document.createElement('style');
    expandStyle.textContent =
      '.oc-expandable { cursor: pointer; transition: background 0.2s; }' +
      '.oc-expandable:hover { background: rgba(88,166,255,0.08); }' +
      '.oc-agent-detail, .oc-sa-task { word-wrap: break-word; white-space: normal; }' +
      '.oc-expandable.expanded .oc-agent-detail,' +
      '.oc-expandable.expanded .oc-sa-task,' +
      '.oc-expandable.expanded .oc-session-name { white-space: normal !important; word-break: break-all; overflow: visible !important; text-overflow: unset !important; max-height: none !important; }' +
      /* Clickable elements */
      '.oc-clickable { cursor: pointer; transition: background 0.15s, filter 0.15s; }' +
      '.oc-clickable:hover { background: rgba(232,168,73,0.06); filter: brightness(1.05); }' +
      '.oc-expanded { background: rgba(232,168,73,0.08) !important; }' +
      /* Expand icon in job cards */
      '.oc-expand-icon { color: #484f58; font-size: 10px; margin-left: auto; transition: transform 0.2s; }' +
      /* Smooth expand for activity and session inner panels */
      '.oc-act-expanded, .oc-session-expanded, .oc-job-expanded { animation: oc-slide-down 0.2s ease; }' +
      '@keyframes oc-slide-down { from { opacity: 0; max-height: 0; } to { opacity: 1; max-height: 500px; } }' +
      /* Activity rows need flex-wrap for expanded content */
      '.oc-activity-row.oc-clickable { flex-wrap: wrap; }' +
      '.oc-act-expanded { width: 100%; }' +
      '.oc-session-row.oc-clickable { flex-wrap: wrap; }' +
      '.oc-session-expanded { width: 100%; }' +
      /* Dismiss button hover reveal */
      '.oc-sa-card:hover .oc-sa-dismiss { opacity: 1 !important; }' +
      '.oc-sa-dismiss:hover { background: #5c3d1a !important; color: #fff !important; }' +
      /* Fade-out animation for dismissed cards */
      '.oc-sa-fade-out { transition: opacity 0.4s ease, max-height 0.4s ease, padding 0.4s ease, margin 0.4s ease; opacity: 0; max-height: 0; padding: 0 !important; margin: 0 !important; overflow: hidden; }';
    document.head.appendChild(expandStyle);

    // Dismiss button handler (delegated)
    panel.addEventListener('click', function (e) {
      var btn = e.target.closest('.oc-sa-dismiss');
      if (!btn) return;
      e.stopPropagation(); // Don't trigger expand
      var label = btn.getAttribute('data-label');
      if (!label) return;
      btn.disabled = true;
      btn.textContent = '…';
      fetch('/openclaw/agent/' + encodeURIComponent(label) + '/dismiss', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok) {
          var card = btn.closest('.oc-sa-card');
          if (card) {
            card.classList.add('oc-sa-fade-out');
            setTimeout(function () { card.remove(); }, 450);
          }
        } else {
          btn.disabled = false;
          btn.textContent = '✕';
        }
      })
      .catch(function () {
        btn.disabled = false;
        btn.textContent = '✕';
      });
    });

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
