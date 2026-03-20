"""OpenClaw Dashboard API — read-only integration with OpenClaw data directory.

Provides:
  GET /openclaw/status    — gateway health + cron summary
  GET /openclaw/cron      — all cron jobs with state
  GET /openclaw/activity  — recent cron run history
  GET /openclaw/costs     — token usage aggregation
  GET /openclaw/usage     — usage limits & cost tracking
  GET /openclaw/sessions  — live session registry
  GET /openclaw/subagents — subagent run history
  GET /openclaw/agents    — combined agent view for pixel office
"""

import glob
import json
import os
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request

openclaw_bp = Blueprint("openclaw", __name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _resolve_openclaw_dir():
    """Return the OpenClaw data directory, honouring OPENCLAW_DIR env var."""
    env = os.environ.get("OPENCLAW_DIR", "").strip()
    if env and os.path.isdir(env):
        return env
    # Windows default
    home = os.path.expanduser("~")
    candidate = os.path.join(home, ".openclaw")
    if os.path.isdir(candidate):
        return candidate
    return candidate  # return anyway; endpoints will gracefully degrade


OPENCLAW_DIR = _resolve_openclaw_dir()
CRON_DIR = os.path.join(OPENCLAW_DIR, "cron")
JOBS_FILE = os.path.join(CRON_DIR, "jobs.json")
RUNS_DIR = os.path.join(CRON_DIR, "runs")
SESSIONS_FILE = os.path.join(OPENCLAW_DIR, "agents", "main", "sessions", "sessions.json")
SESSIONS_DIR = os.path.join(OPENCLAW_DIR, "agents", "main", "sessions")
SUBAGENT_RUNS_FILE = os.path.join(OPENCLAW_DIR, "subagents", "runs.json")
GATEWAY_HEALTH_URL = "http://127.0.0.1:18789/health"

# Dismissed agents persistence
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISMISSED_FILE = os.path.join(PROJECT_ROOT, "dismissed_agents.json")
USAGE_CONFIG_FILE = os.path.join(PROJECT_ROOT, "usage_config.json")
RATE_LIMITS_CONFIG_FILE = os.path.join(PROJECT_ROOT, "rate_limits_config.json")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_jobs():
    """Read jobs.json and return the list of jobs (empty list on error)."""
    if not os.path.isfile(JOBS_FILE):
        return []
    try:
        with open(JOBS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("jobs", []) if isinstance(data, dict) else []
    except Exception:
        return []


def _job_name_map():
    """Return {jobId: jobName} from jobs.json."""
    return {j.get("id", ""): j.get("name", j.get("id", "unknown")) for j in _read_jobs()}


def _read_all_runs():
    """Parse all .jsonl files in the runs directory. Returns list of dicts."""
    if not os.path.isdir(RUNS_DIR):
        return []
    entries = []
    for path in glob.glob(os.path.join(RUNS_DIR, "*.jsonl")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception:
            continue
    return entries


def _check_gateway():
    """Check gateway health endpoint. Returns {ok, status}."""
    try:
        req = urllib.request.Request(GATEWAY_HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {"ok": data.get("ok", True), "status": data.get("status", "live")}
    except Exception:
        return {"ok": False, "status": "unreachable"}


def _relative_time_label(ts_ms):
    """Convert epoch-ms to a human-friendly relative label."""
    if not ts_ms:
        return None
    now_ms = time.time() * 1000
    diff_s = (ts_ms - now_ms) / 1000
    abs_s = abs(diff_s)
    if abs_s < 60:
        label = f"{int(abs_s)}s"
    elif abs_s < 3600:
        label = f"{int(abs_s / 60)}m"
    elif abs_s < 86400:
        label = f"{abs_s / 3600:.1f}h"
    else:
        label = f"{abs_s / 86400:.1f}d"
    return f"in {label}" if diff_s > 0 else f"{label} ago"


def _read_dismissed():
    """Read dismissed_agents.json and return the dismissed dict."""
    if not os.path.isfile(DISMISSED_FILE):
        return {}
    try:
        with open(DISMISSED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("dismissed", {}) if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_dismissed(dismissed):
    """Write the dismissed dict back to dismissed_agents.json."""
    try:
        with open(DISMISSED_FILE, "w", encoding="utf-8") as f:
            json.dump({"dismissed": dismissed}, f, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@openclaw_bp.route("/openclaw/status", methods=["GET"])
def openclaw_status():
    """System overview: gateway health + cron job counts."""
    jobs = _read_jobs()
    enabled = [j for j in jobs if j.get("enabled")]
    disabled = [j for j in jobs if not j.get("enabled")]
    erroring = [j for j in enabled if (j.get("state", {}).get("consecutiveErrors", 0) or 0) > 0]

    return jsonify({
        "gateway": _check_gateway(),
        "cron": {
            "total": len(jobs),
            "enabled": len(enabled),
            "disabled": len(disabled),
            "erroring": len(erroring),
        },
        "lastUpdated": datetime.now().isoformat(),
    })


@openclaw_bp.route("/openclaw/cron", methods=["GET"])
def openclaw_cron():
    """All cron jobs sorted by next run time."""
    jobs = _read_jobs()
    result = []
    for j in jobs:
        state = j.get("state", {}) or {}
        schedule = j.get("schedule", {}) or {}
        payload = j.get("payload", {}) or {}
        result.append({
            "id": j.get("id"),
            "name": j.get("name"),
            "enabled": j.get("enabled", False),
            "schedule": schedule.get("expr", ""),
            "tz": schedule.get("tz", ""),
            "lastRun": {
                "at": state.get("lastRunAtMs"),
                "atRelative": _relative_time_label(state.get("lastRunAtMs")),
                "status": state.get("lastRunStatus") or state.get("lastStatus"),
                "durationMs": state.get("lastDurationMs"),
                "delivered": state.get("lastDelivered"),
            },
            "nextRunAt": state.get("nextRunAtMs"),
            "nextRunAtRelative": _relative_time_label(state.get("nextRunAtMs")),
            "consecutiveErrors": state.get("consecutiveErrors", 0),
            "model": payload.get("model", ""),
        })
    # Sort by nextRunAtMs ascending (None/0 last)
    result.sort(key=lambda x: x.get("nextRunAt") or float("inf"))
    return jsonify(result)


@openclaw_bp.route("/openclaw/activity", methods=["GET"])
def openclaw_activity():
    """Recent cron completions across all jobs."""
    limit = request.args.get("limit", 20, type=int)
    limit = max(1, min(limit, 200))
    job_name_filter = request.args.get("jobName", "", type=str).strip()

    name_map = _job_name_map()
    runs = _read_all_runs()

    # Filter by jobName if requested
    if job_name_filter:
        job_ids_for_name = [jid for jid, jname in name_map.items() if jname == job_name_filter]
        if job_ids_for_name:
            runs = [r for r in runs if r.get("jobId") in job_ids_for_name]
        else:
            runs = []

    # Sort by timestamp descending
    runs.sort(key=lambda r: r.get("ts", 0), reverse=True)
    runs = runs[:limit]

    result = []
    for r in runs:
        usage = r.get("usage") or {}
        summary = (r.get("summary") or "")[:200]
        result.append({
            "ts": r.get("ts"),
            "jobId": r.get("jobId"),
            "jobName": name_map.get(r.get("jobId", ""), r.get("jobId", "unknown")),
            "action": r.get("action"),
            "status": r.get("status"),
            "durationMs": r.get("durationMs"),
            "model": r.get("model"),
            "provider": r.get("provider"),
            "tokens": {
                "input": usage.get("input_tokens", 0),
                "output": usage.get("output_tokens", 0),
                "total": usage.get("total_tokens", 0),
            },
            "delivered": r.get("delivered"),
            "summary": summary,
        })
    return jsonify(result)


@openclaw_bp.route("/openclaw/costs", methods=["GET"])
def openclaw_costs():
    """Token usage aggregation over the past N days."""
    days = request.args.get("days", 7, type=int)
    days = max(1, min(days, 90))

    cutoff_ms = (time.time() - days * 86400) * 1000
    runs = _read_all_runs()

    by_model = {}
    by_day = {}
    totals = {"runs": 0, "totalTokens": 0}

    for r in runs:
        ts = r.get("ts", 0)
        if ts < cutoff_ms:
            continue

        usage = r.get("usage") or {}
        input_t = usage.get("input_tokens", 0) or 0
        output_t = usage.get("output_tokens", 0) or 0
        total_t = usage.get("total_tokens", 0) or 0

        model = r.get("model") or r.get("provider") or "unknown"

        # By model
        if model not in by_model:
            by_model[model] = {"runs": 0, "totalTokens": 0, "inputTokens": 0, "outputTokens": 0}
        by_model[model]["runs"] += 1
        by_model[model]["totalTokens"] += total_t
        by_model[model]["inputTokens"] += input_t
        by_model[model]["outputTokens"] += output_t

        # By day
        try:
            day_str = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
        except Exception:
            day_str = "unknown"
        if day_str not in by_day:
            by_day[day_str] = {"date": day_str, "runs": 0, "totalTokens": 0}
        by_day[day_str]["runs"] += 1
        by_day[day_str]["totalTokens"] += total_t

        totals["runs"] += 1
        totals["totalTokens"] += total_t

    # Sort by_day chronologically
    by_day_list = sorted(by_day.values(), key=lambda d: d["date"])

    return jsonify({
        "byModel": by_model,
        "byDay": by_day_list,
        "totals": totals,
        "days": days,
    })


# ---------------------------------------------------------------------------
# Usage & Cost Tracking
# ---------------------------------------------------------------------------

def _read_usage_config():
    """Read usage_config.json with defaults."""
    defaults = {
        "monthlyBudget": 200,
        "warningThreshold": 0.8,
        "anthropicMonthlyLimit": None,
        "openaiMonthlyLimit": None,
        "pricing": {
            "claude-opus-4-6": {"inputPer1M": 15, "outputPer1M": 75, "cacheReadPer1M": 1.5},
            "claude-sonnet-4-6": {"inputPer1M": 3, "outputPer1M": 15, "cacheReadPer1M": 0.3},
            "gpt-5.4": {"inputPer1M": 2, "outputPer1M": 8, "cacheReadPer1M": 0.2},
            "gpt-5.3-codex": {"inputPer1M": 2, "outputPer1M": 8, "cacheReadPer1M": 0.2},
            "gpt-5.3-codex-spark": {"inputPer1M": 2, "outputPer1M": 8, "cacheReadPer1M": 0.2},
            "default": {"inputPer1M": 3, "outputPer1M": 15, "cacheReadPer1M": 0.3},
        },
    }
    if not os.path.isfile(USAGE_CONFIG_FILE):
        return defaults
    try:
        with open(USAGE_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Merge with defaults
        for k, v in defaults.items():
            if k not in data:
                data[k] = v
        return data
    except Exception:
        return defaults


def _estimate_cost(model, input_tokens, output_tokens, cache_read_tokens, pricing):
    """Estimate USD cost for token counts given model pricing table."""
    model_short = (model or "").split("/")[-1] if model else ""
    rates = pricing.get(model_short, pricing.get("default", {}))
    input_cost = (input_tokens / 1_000_000) * rates.get("inputPer1M", 3)
    output_cost = (output_tokens / 1_000_000) * rates.get("outputPer1M", 15)
    cache_cost = (cache_read_tokens / 1_000_000) * rates.get("cacheReadPer1M", 0.3)
    return round(input_cost + output_cost + cache_cost, 4)


def _provider_from_model(model):
    """Infer provider from model name."""
    m = (model or "").lower()
    if "claude" in m or "anthropic" in m:
        return "anthropic"
    if "gpt" in m or "codex" in m or "openai" in m:
        return "openai"
    if "openrouter" in m:
        return "openrouter"
    return "other"


def _normalize_provider(provider):
    """Normalize provider string to canonical keys (anthropic, openai, etc.)."""
    p = (provider or "").lower().strip()
    if p in ("anthropic",):
        return "anthropic"
    if p in ("openai", "openai-codex", "openai-responses"):
        return "openai"
    if "openrouter" in p:
        return "openrouter"
    if "anthropic" in p:
        return "anthropic"
    if "openai" in p or "codex" in p:
        return "openai"
    return provider


def _get_month_start_ms():
    """Return epoch ms for the start of the current month."""
    now = datetime.now()
    month_start = datetime(now.year, now.month, 1)
    return int(month_start.timestamp() * 1000)


def _get_today_start_ms():
    """Return epoch ms for the start of today."""
    now = datetime.now()
    today_start = datetime(now.year, now.month, now.day)
    return int(today_start.timestamp() * 1000)


@openclaw_bp.route("/openclaw/usage", methods=["GET"])
def openclaw_usage():
    """Usage limits & cost tracking — aggregates sessions + cron runs."""
    period = request.args.get("period", "current_month", type=str)
    config = _read_usage_config()
    pricing = config.get("pricing", {})

    # Determine time cutoff
    now_ms = time.time() * 1000
    if period == "today":
        cutoff_ms = _get_today_start_ms()
    elif period == "this_week":
        cutoff_ms = now_ms - 7 * 86400 * 1000
    else:  # current_month
        cutoff_ms = _get_month_start_ms()

    # --- 1. Aggregate from sessions.json ---
    sessions = _read_sessions()
    provider_totals = {}  # provider -> {inputTokens, outputTokens, cacheRead, totalTokens, sessions, cost}
    model_totals = {}     # model -> {inputTokens, outputTokens, cacheRead, totalTokens, sessions, cost}
    by_day = {}           # date_str -> {date, totalTokens, cost, sessions}

    for session_key, s in sessions.items():
        updated_at = s.get("updatedAt", 0)
        if updated_at < cutoff_ms:
            continue

        model = s.get("model", "") or ""
        model_provider = s.get("modelProvider", "") or ""
        input_t = s.get("inputTokens", 0) or 0
        output_t = s.get("outputTokens", 0) or 0
        cache_r = s.get("cacheRead", 0) or 0
        total_t = s.get("totalTokens", 0) or 0

        # Infer provider if not set
        provider = model_provider if model_provider and model_provider != "unknown" else _provider_from_model(model)

        cost = _estimate_cost(model, input_t, output_t, cache_r, pricing)

        # Provider aggregation
        if provider not in provider_totals:
            provider_totals[provider] = {"inputTokens": 0, "outputTokens": 0, "cacheRead": 0,
                                          "totalTokens": 0, "sessions": 0, "estimatedCost": 0}
        pt = provider_totals[provider]
        pt["inputTokens"] += input_t
        pt["outputTokens"] += output_t
        pt["cacheRead"] += cache_r
        pt["totalTokens"] += total_t
        pt["sessions"] += 1
        pt["estimatedCost"] = round(pt["estimatedCost"] + cost, 4)

        # Model aggregation
        model_key = model.split("/")[-1] if model else "unknown"
        if model_key not in model_totals:
            model_totals[model_key] = {"inputTokens": 0, "outputTokens": 0, "cacheRead": 0,
                                        "totalTokens": 0, "sessions": 0, "estimatedCost": 0}
        mt = model_totals[model_key]
        mt["inputTokens"] += input_t
        mt["outputTokens"] += output_t
        mt["cacheRead"] += cache_r
        mt["totalTokens"] += total_t
        mt["sessions"] += 1
        mt["estimatedCost"] = round(mt["estimatedCost"] + cost, 4)

        # By day aggregation
        try:
            day_str = datetime.fromtimestamp(updated_at / 1000).strftime("%Y-%m-%d")
        except Exception:
            day_str = "unknown"
        if day_str not in by_day:
            by_day[day_str] = {"date": day_str, "totalTokens": 0, "estimatedCost": 0, "sessions": 0}
        by_day[day_str]["totalTokens"] += total_t
        by_day[day_str]["estimatedCost"] = round(by_day[day_str]["estimatedCost"] + cost, 4)
        by_day[day_str]["sessions"] += 1

    # --- 2. Aggregate from cron runs ---
    runs = _read_all_runs()
    for r in runs:
        ts = r.get("ts", 0)
        if ts < cutoff_ms:
            continue

        usage = r.get("usage") or {}
        input_t = usage.get("input_tokens", 0) or 0
        output_t = usage.get("output_tokens", 0) or 0
        cache_r = usage.get("cache_read_input_tokens", 0) or 0
        model = r.get("model", "") or ""
        provider_raw = r.get("provider", "") or ""
        provider = provider_raw if provider_raw and provider_raw != "unknown" else _provider_from_model(model)

        cost = _estimate_cost(model, input_t, output_t, cache_r, pricing)

        # Provider
        if provider not in provider_totals:
            provider_totals[provider] = {"inputTokens": 0, "outputTokens": 0, "cacheRead": 0,
                                          "totalTokens": 0, "sessions": 0, "estimatedCost": 0}
        pt = provider_totals[provider]
        pt["inputTokens"] += input_t
        pt["outputTokens"] += output_t
        pt["cacheRead"] += cache_r
        pt["totalTokens"] += input_t + output_t
        pt["sessions"] += 1
        pt["estimatedCost"] = round(pt["estimatedCost"] + cost, 4)

        # Model
        model_key = model.split("/")[-1] if model else "unknown"
        if model_key not in model_totals:
            model_totals[model_key] = {"inputTokens": 0, "outputTokens": 0, "cacheRead": 0,
                                        "totalTokens": 0, "sessions": 0, "estimatedCost": 0}
        mt = model_totals[model_key]
        mt["inputTokens"] += input_t
        mt["outputTokens"] += output_t
        mt["cacheRead"] += cache_r
        mt["totalTokens"] += input_t + output_t
        mt["sessions"] += 1
        mt["estimatedCost"] = round(mt["estimatedCost"] + cost, 4)

        # By day
        try:
            day_str = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
        except Exception:
            day_str = "unknown"
        if day_str not in by_day:
            by_day[day_str] = {"date": day_str, "totalTokens": 0, "estimatedCost": 0, "sessions": 0}
        by_day[day_str]["totalTokens"] += input_t + output_t
        by_day[day_str]["estimatedCost"] = round(by_day[day_str]["estimatedCost"] + cost, 4)
        by_day[day_str]["sessions"] += 1

    # --- 3. Compute totals and warnings ---
    total_cost = sum(pt["estimatedCost"] for pt in provider_totals.values())
    total_tokens = sum(pt["totalTokens"] for pt in provider_totals.values())
    monthly_budget = config.get("monthlyBudget")
    warning_threshold = config.get("warningThreshold", 0.8)

    warnings = []
    budget_percent = None
    if monthly_budget and monthly_budget > 0:
        budget_percent = round(total_cost / monthly_budget, 4)
        if budget_percent >= 1.0:
            warnings.append(f"🔴 Monthly budget exceeded! ${total_cost:.2f} / ${monthly_budget:.2f}")
        elif budget_percent >= warning_threshold:
            warnings.append(f"🟡 Approaching monthly budget: ${total_cost:.2f} / ${monthly_budget:.2f} ({budget_percent*100:.0f}%)")

    # Provider-specific limit warnings
    for pname, limit_key in [("anthropic", "anthropicMonthlyLimit"), ("openai", "openaiMonthlyLimit")]:
        limit_val = config.get(limit_key)
        if limit_val and limit_val > 0 and pname in provider_totals:
            pct = provider_totals[pname]["estimatedCost"] / limit_val
            provider_totals[pname]["limit"] = limit_val
            provider_totals[pname]["percentUsed"] = round(pct, 4)
            if pct >= 1.0:
                warnings.append(f"🔴 {pname.title()} limit exceeded!")
            elif pct >= warning_threshold:
                warnings.append(f"🟡 {pname.title()} approaching limit ({pct*100:.0f}%)")

    # Pro-rated daily budget info
    now = datetime.now()
    days_in_month = 30  # approximation
    day_of_month = now.day
    daily_budget = monthly_budget / days_in_month if monthly_budget else None

    # Today's spend
    today_str = now.strftime("%Y-%m-%d")
    today_data = by_day.get(today_str, {"totalTokens": 0, "estimatedCost": 0, "sessions": 0})
    today_cost = today_data["estimatedCost"]
    today_budget_pct = None
    if daily_budget and daily_budget > 0:
        today_budget_pct = round(today_cost / daily_budget, 4)

    by_day_list = sorted(by_day.values(), key=lambda d: d["date"])

    return jsonify({
        "period": period,
        "totalEstimatedCost": round(total_cost, 2),
        "totalTokens": total_tokens,
        "monthlyBudget": monthly_budget,
        "budgetPercent": budget_percent,
        "byProvider": provider_totals,
        "byModel": model_totals,
        "byDay": by_day_list,
        "today": {
            "date": today_str,
            "estimatedCost": round(today_cost, 2),
            "totalTokens": today_data["totalTokens"],
            "sessions": today_data["sessions"],
            "dailyBudget": round(daily_budget, 2) if daily_budget else None,
            "budgetPercent": today_budget_pct,
        },
        "warnings": warnings,
    })


@openclaw_bp.route("/openclaw/usage/config", methods=["GET"])
def openclaw_usage_config_get():
    """Get the current usage config."""
    return jsonify(_read_usage_config())


@openclaw_bp.route("/openclaw/usage/config", methods=["POST"])
def openclaw_usage_config_set():
    """Update usage config (partial merge)."""
    try:
        updates = request.get_json(force=True)
        config = _read_usage_config()
        for k, v in updates.items():
            if k == "pricing" and isinstance(v, dict):
                config.setdefault("pricing", {}).update(v)
            else:
                config[k] = v
        with open(USAGE_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return jsonify({"ok": True, "config": config})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ---------------------------------------------------------------------------
# Rate Limits — rolling token window tracking
# ---------------------------------------------------------------------------

def _read_rate_limits_config():
    """Read rate_limits_config.json with defaults."""
    defaults = {
        "anthropic": {
            "sessionWindowHours": 5,
            "fiveHourTokenLimit": 300000,
            "weeklyTokenLimit": 5000000,
            "tier": "tier-2",
            "label": "Anthropic (Claude)",
        },
        "openai": {
            "sessionWindowHours": 5,
            "fiveHourTokenLimit": 500000,
            "weeklyTokenLimit": 10000000,
            "tier": "plus",
            "label": "OpenAI (Codex)",
        },
    }
    if not os.path.isfile(RATE_LIMITS_CONFIG_FILE):
        return defaults
    try:
        with open(RATE_LIMITS_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Merge with defaults for any missing providers
        for provider, pdefaults in defaults.items():
            if provider not in data:
                data[provider] = pdefaults
            else:
                for k, v in pdefaults.items():
                    if k not in data[provider]:
                        data[provider][k] = v
        return data
    except Exception:
        return defaults


# ---------------------------------------------------------------------------
# Data source: Codex SQLite (OpenAI)
# ---------------------------------------------------------------------------

import sqlite3

def _codex_sqlite_path():
    """Return path to Codex state SQLite database."""
    return os.path.join(os.path.expanduser("~"), ".codex", "state_5.sqlite")


def _read_codex_usage(session_cutoff_s, week_cutoff_s):
    """Read token usage from Codex SQLite for rolling windows.

    Returns {
        "session": {"total_tokens": N, "by_model": {model: tokens}},
        "weekly":  {"total_tokens": N, "by_model": {model: tokens}},
        "available": bool,
        "error": str or None,
        "thread_count_session": int,
        "thread_count_weekly": int,
    }
    """
    db_path = _codex_sqlite_path()
    result = {
        "session": {"total_tokens": 0, "by_model": {}},
        "weekly": {"total_tokens": 0, "by_model": {}},
        "available": False,
        "error": None,
        "thread_count_session": 0,
        "thread_count_weekly": 0,
    }
    if not os.path.isfile(db_path):
        result["error"] = "Codex SQLite not found"
        return result
    try:
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        db.execute("PRAGMA query_only = ON")

        # Session window
        row = db.execute(
            "SELECT COALESCE(SUM(tokens_used), 0), COUNT(*) FROM threads WHERE updated_at > ?",
            (int(session_cutoff_s),),
        ).fetchone()
        result["session"]["total_tokens"] = row[0] or 0
        result["thread_count_session"] = row[1] or 0

        # Weekly window
        row = db.execute(
            "SELECT COALESCE(SUM(tokens_used), 0), COUNT(*) FROM threads WHERE updated_at > ?",
            (int(week_cutoff_s),),
        ).fetchone()
        result["weekly"]["total_tokens"] = row[0] or 0
        result["thread_count_weekly"] = row[1] or 0

        # Per-model breakdown (use source field as proxy; Codex tracks model_provider not model name)
        # Group by source for session window
        for row in db.execute(
            "SELECT source, COALESCE(SUM(tokens_used), 0) FROM threads WHERE updated_at > ? GROUP BY source",
            (int(session_cutoff_s),),
        ).fetchall():
            src = row[0] or "unknown"
            result["session"]["by_model"][src] = row[1] or 0

        for row in db.execute(
            "SELECT source, COALESCE(SUM(tokens_used), 0) FROM threads WHERE updated_at > ? GROUP BY source",
            (int(week_cutoff_s),),
        ).fetchall():
            src = row[0] or "unknown"
            result["weekly"]["by_model"][src] = row[1] or 0

        db.close()
        result["available"] = True
    except Exception as e:
        result["error"] = str(e)
    return result


# ---------------------------------------------------------------------------
# Data source: Claude Code session JSONLs (Anthropic)
# ---------------------------------------------------------------------------

def _claude_code_sessions_dir():
    """Return path to Claude Code project sessions directory."""
    return os.path.join(os.path.expanduser("~"), ".claude", "projects")


def _parse_claude_code_jsonl(file_path, cutoff_s):
    """Parse a Claude Code session JSONL file for assistant message usage after cutoff.

    Returns list of {ts_s, model, input_tokens, output_tokens, cache_read, cache_write, total_tokens}.
    """
    entries = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Only care about assistant messages with usage
                if obj.get("type") != "assistant":
                    continue

                msg = obj.get("message", {})
                if not msg:
                    continue
                usage = msg.get("usage", {})
                if not usage:
                    continue

                # Parse timestamp from obj.timestamp (ISO format)
                ts_str = obj.get("timestamp", "")
                if not ts_str:
                    continue
                try:
                    ts_s = datetime.fromisoformat(
                        ts_str.replace("Z", "+00:00")
                    ).timestamp()
                except Exception:
                    continue

                if ts_s < cutoff_s:
                    continue

                input_t = usage.get("input_tokens", 0) or 0
                output_t = usage.get("output_tokens", 0) or 0
                cache_read = usage.get("cache_read_input_tokens", 0) or 0
                cache_write = usage.get("cache_creation_input_tokens", 0) or 0

                model = msg.get("model", "") or ""

                entries.append({
                    "ts_s": ts_s,
                    "model": model,
                    "input_tokens": input_t,
                    "output_tokens": output_t,
                    "cache_read": cache_read,
                    "cache_write": cache_write,
                    "total_tokens": input_t + output_t + cache_read + cache_write,
                })
    except Exception:
        pass
    return entries


def _read_claude_code_usage(session_cutoff_s, week_cutoff_s):
    """Read token usage from Claude Code session files for rolling windows.

    Returns {
        "session": {"input_tokens": N, "output_tokens": N, "cache_read": N, "cache_write": N, "total_tokens": N, "by_model": {}},
        "weekly":  {"input_tokens": N, "output_tokens": N, "cache_read": N, "cache_write": N, "total_tokens": N, "by_model": {}},
        "available": bool,
        "error": str or None,
        "files_scanned": int,
        "entries_found": int,
    }
    """
    projects_dir = _claude_code_sessions_dir()
    result = {
        "session": {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_write": 0, "total_tokens": 0, "by_model": {}},
        "weekly": {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_write": 0, "total_tokens": 0, "by_model": {}},
        "available": False,
        "error": None,
        "files_scanned": 0,
        "entries_found": 0,
    }
    if not os.path.isdir(projects_dir):
        result["error"] = "Claude Code projects dir not found"
        return result

    min_cutoff_s = min(session_cutoff_s, week_cutoff_s)
    files_scanned = 0
    total_entries = 0

    try:
        for jsonl_path in glob.glob(os.path.join(projects_dir, "**", "*.jsonl"), recursive=True):
            # Skip files not modified since the wider cutoff window
            try:
                mtime_s = os.path.getmtime(jsonl_path)
                if mtime_s < min_cutoff_s:
                    continue
            except Exception:
                continue

            files_scanned += 1
            entries = _parse_claude_code_jsonl(jsonl_path, min_cutoff_s)
            total_entries += len(entries)

            for e in entries:
                # Weekly window
                if e["ts_s"] >= week_cutoff_s:
                    w = result["weekly"]
                    w["input_tokens"] += e["input_tokens"]
                    w["output_tokens"] += e["output_tokens"]
                    w["cache_read"] += e["cache_read"]
                    w["cache_write"] += e["cache_write"]
                    w["total_tokens"] += e["total_tokens"]
                    model = e["model"] or "unknown"
                    w["by_model"][model] = w["by_model"].get(model, 0) + e["total_tokens"]

                # Session window
                if e["ts_s"] >= session_cutoff_s:
                    s = result["session"]
                    s["input_tokens"] += e["input_tokens"]
                    s["output_tokens"] += e["output_tokens"]
                    s["cache_read"] += e["cache_read"]
                    s["cache_write"] += e["cache_write"]
                    s["total_tokens"] += e["total_tokens"]
                    model = e["model"] or "unknown"
                    s["by_model"][model] = s["by_model"].get(model, 0) + e["total_tokens"]

        result["available"] = True
        result["files_scanned"] = files_scanned
        result["entries_found"] = total_entries
    except Exception as e:
        result["error"] = str(e)
    return result


# ---------------------------------------------------------------------------
# Data source: OpenClaw sessions + cron (existing)
# ---------------------------------------------------------------------------

def _parse_openclaw_session_jsonl_usage(session_path, cutoff_ms):
    """Parse an OpenClaw session JSONL file and extract per-message token usage entries after cutoff.

    Returns list of {ts_ms, provider, model, input_tokens, output_tokens, total_tokens}.
    """
    entries = []
    if not os.path.isfile(session_path):
        return entries
    try:
        with open(session_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "message":
                    continue
                msg = obj.get("message", {})
                usage = msg.get("usage", {})
                total = usage.get("totalTokens", 0) or 0
                if total <= 0:
                    continue

                # Get timestamp — prefer message.timestamp (epoch ms) then obj.timestamp (ISO)
                ts_ms = msg.get("timestamp", 0)
                if not ts_ms and obj.get("timestamp"):
                    try:
                        ts_ms = int(datetime.fromisoformat(
                            obj["timestamp"].replace("Z", "+00:00")
                        ).timestamp() * 1000)
                    except Exception:
                        continue
                if ts_ms < cutoff_ms:
                    continue

                model = msg.get("model", "") or ""
                provider_raw = msg.get("provider", "") or ""
                provider = provider_raw if provider_raw and provider_raw not in ("", "openclaw") else _provider_from_model(model)
                provider = _normalize_provider(provider)

                entries.append({
                    "ts_ms": ts_ms,
                    "provider": provider,
                    "model": model,
                    "input_tokens": usage.get("input", 0) or 0,
                    "output_tokens": usage.get("output", 0) or 0,
                    "total_tokens": total,
                })
    except Exception:
        pass
    return entries


def _collect_openclaw_rolling_usage(session_cutoff_ms, week_cutoff_ms):
    """Collect token usage from OpenClaw cron runs and session JSONL files.

    Returns {provider: {"session": {input, output, total}, "7d": {input, output, total}}}.
    """
    min_cutoff = min(session_cutoff_ms, week_cutoff_ms)
    result = {}

    def _init_provider(p):
        if p not in result:
            result[p] = {
                "session": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "7d": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            }

    def _add_entry(provider, ts_ms, input_t, output_t, total_t):
        _init_provider(provider)
        if ts_ms >= week_cutoff_ms:
            result[provider]["7d"]["input_tokens"] += input_t
            result[provider]["7d"]["output_tokens"] += output_t
            result[provider]["7d"]["total_tokens"] += total_t
        if ts_ms >= session_cutoff_ms:
            result[provider]["session"]["input_tokens"] += input_t
            result[provider]["session"]["output_tokens"] += output_t
            result[provider]["session"]["total_tokens"] += total_t

    # 1. Cron runs
    if os.path.isdir(RUNS_DIR):
        for path in glob.glob(os.path.join(RUNS_DIR, "*.jsonl")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            r = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        ts = r.get("ts", 0)
                        if ts < min_cutoff:
                            continue
                        usage = r.get("usage") or {}
                        input_t = usage.get("input_tokens", 0) or 0
                        output_t = usage.get("output_tokens", 0) or 0
                        total_t = usage.get("total_tokens", 0) or 0
                        if total_t <= 0:
                            continue
                        provider_raw = r.get("provider", "") or ""
                        model = r.get("model", "") or ""
                        provider = provider_raw if provider_raw and provider_raw != "unknown" else _provider_from_model(model)
                        provider = _normalize_provider(provider)
                        _add_entry(provider, ts, input_t, output_t, total_t)
            except Exception:
                continue

    # 2. OpenClaw session JSONL files
    if os.path.isdir(SESSIONS_DIR):
        for path in glob.glob(os.path.join(SESSIONS_DIR, "*.jsonl")):
            try:
                mtime_ms = os.path.getmtime(path) * 1000
                if mtime_ms < min_cutoff:
                    continue
            except Exception:
                continue
            entries = _parse_openclaw_session_jsonl_usage(path, min_cutoff)
            for e in entries:
                _add_entry(e["provider"], e["ts_ms"], e["input_tokens"], e["output_tokens"], e["total_tokens"])

    return result


@openclaw_bp.route("/openclaw/rate-limits", methods=["GET"])
def openclaw_rate_limits():
    """Rolling token usage windows for rate limit tracking.

    Aggregates from three data sources:
    1. Codex SQLite (OpenAI actual usage)
    2. Claude Code session JSONLs (Anthropic actual usage)
    3. OpenClaw sessions + cron runs (supplementary — adds to Anthropic totals)
    """
    now_s = time.time()
    now_ms = now_s * 1000
    config = _read_rate_limits_config()

    # Per-provider session windows (configurable)
    anthropic_session_hours = config.get("anthropic", {}).get("sessionWindowHours", 5)
    openai_session_hours = config.get("openai", {}).get("sessionWindowHours", 5)

    week_cutoff_s = now_s - 7 * 86400
    week_cutoff_ms = now_ms - 7 * 86400 * 1000

    # --- 1. Codex SQLite (OpenAI) ---
    openai_session_cutoff_s = now_s - openai_session_hours * 3600
    codex_data = _read_codex_usage(openai_session_cutoff_s, week_cutoff_s)

    # --- 2. Claude Code sessions (Anthropic) ---
    anthropic_session_cutoff_s = now_s - anthropic_session_hours * 3600
    claude_data = _read_claude_code_usage(anthropic_session_cutoff_s, week_cutoff_s)

    # --- 3. OpenClaw sessions + cron (supplementary) ---
    # Use the wider of the two session windows for OpenClaw data collection
    max_session_hours = max(anthropic_session_hours, openai_session_hours)
    openclaw_session_cutoff_ms = now_ms - max_session_hours * 3600 * 1000
    openclaw_data = _collect_openclaw_rolling_usage(openclaw_session_cutoff_ms, week_cutoff_ms)

    # --- Build response ---
    response = {}
    warnings = []
    worst_percent = 0

    # === ANTHROPIC ===
    anthropic_config = config.get("anthropic", {})
    session_limit = anthropic_config.get("fiveHourTokenLimit", 0)
    weekly_limit = anthropic_config.get("weeklyTokenLimit", 0)
    label = anthropic_config.get("label", "Anthropic (Claude)")

    # Claude Code is the primary source; OpenClaw Anthropic sessions are additive
    oc_anthropic = openclaw_data.get("anthropic", {
        "session": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "7d": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    })

    anthropic_session_total = (
        claude_data["session"]["total_tokens"] + oc_anthropic["session"]["total_tokens"]
    )
    anthropic_weekly_total = (
        claude_data["weekly"]["total_tokens"] + oc_anthropic["7d"]["total_tokens"]
    )
    anthropic_session_input = (
        claude_data["session"]["input_tokens"] + oc_anthropic["session"]["input_tokens"]
    )
    anthropic_session_output = (
        claude_data["session"]["output_tokens"] + oc_anthropic["session"]["output_tokens"]
    )
    anthropic_weekly_input = (
        claude_data["weekly"]["input_tokens"] + oc_anthropic["7d"]["input_tokens"]
    )
    anthropic_weekly_output = (
        claude_data["weekly"]["output_tokens"] + oc_anthropic["7d"]["output_tokens"]
    )

    session_pct = round(anthropic_session_total / session_limit * 100, 1) if session_limit > 0 else 0
    weekly_pct = round(anthropic_weekly_total / weekly_limit * 100, 1) if weekly_limit > 0 else 0
    worst_percent = max(worst_percent, session_pct, weekly_pct)

    anthropic_session_cutoff_ms = anthropic_session_cutoff_s * 1000
    response["anthropic"] = {
        "label": label,
        "tier": anthropic_config.get("tier", ""),
        "sessionWindowHours": anthropic_session_hours,
        "rolling5h": {
            "inputTokens": anthropic_session_input,
            "outputTokens": anthropic_session_output,
            "cacheRead": claude_data["session"].get("cache_read", 0),
            "cacheWrite": claude_data["session"].get("cache_write", 0),
            "totalTokens": anthropic_session_total,
            "windowStart": datetime.fromtimestamp(anthropic_session_cutoff_s).isoformat(),
            "windowHours": anthropic_session_hours,
            "estimatedLimit": session_limit,
            "percentUsed": session_pct,
            "remainingTokens": max(0, session_limit - anthropic_session_total) if session_limit > 0 else None,
        },
        "rollingWeek": {
            "inputTokens": anthropic_weekly_input,
            "outputTokens": anthropic_weekly_output,
            "cacheRead": claude_data["weekly"].get("cache_read", 0),
            "cacheWrite": claude_data["weekly"].get("cache_write", 0),
            "totalTokens": anthropic_weekly_total,
            "windowStart": datetime.fromtimestamp(week_cutoff_s).isoformat(),
            "estimatedLimit": weekly_limit,
            "percentUsed": weekly_pct,
            "remainingTokens": max(0, weekly_limit - anthropic_weekly_total) if weekly_limit > 0 else None,
        },
        "dataSources": {
            "claudeCode": {
                "available": claude_data["available"],
                "sessionTokens": claude_data["session"]["total_tokens"],
                "weeklyTokens": claude_data["weekly"]["total_tokens"],
                "filesScanned": claude_data.get("files_scanned", 0),
                "entriesFound": claude_data.get("entries_found", 0),
                "error": claude_data.get("error"),
                "byModel": claude_data["session"].get("by_model", {}),
            },
            "openclaw": {
                "sessionTokens": oc_anthropic["session"]["total_tokens"],
                "weeklyTokens": oc_anthropic["7d"]["total_tokens"],
            },
        },
    }

    # Anthropic warnings
    if session_pct >= 90:
        warnings.append(f"\U0001f534 {label} {anthropic_session_hours}h window at {session_pct}% — STOP or slow down!")
    elif session_pct >= 80:
        warnings.append(f"\U0001f7e1 {label} {anthropic_session_hours}h window at {session_pct}% — approaching limit")
    elif session_pct >= 60:
        warnings.append(f"\U0001f7e1 {label} {anthropic_session_hours}h window at {session_pct}%")

    if weekly_pct >= 90:
        warnings.append(f"\U0001f534 {label} weekly at {weekly_pct}% — budget critically low!")
    elif weekly_pct >= 80:
        warnings.append(f"\U0001f7e1 {label} weekly at {weekly_pct}% — approaching limit")
    elif weekly_pct >= 60:
        warnings.append(f"\U0001f7e1 {label} weekly at {weekly_pct}%")

    # === OPENAI ===
    openai_config = config.get("openai", {})
    session_limit = openai_config.get("fiveHourTokenLimit", 0)
    weekly_limit = openai_config.get("weeklyTokenLimit", 0)
    label = openai_config.get("label", "OpenAI (Codex)")

    # Codex SQLite is the primary source; OpenClaw OpenAI sessions are additive
    oc_openai = openclaw_data.get("openai", {
        "session": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "7d": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    })

    openai_session_total = (
        codex_data["session"]["total_tokens"] + oc_openai["session"]["total_tokens"]
    )
    openai_weekly_total = (
        codex_data["weekly"]["total_tokens"] + oc_openai["7d"]["total_tokens"]
    )

    session_pct = round(openai_session_total / session_limit * 100, 1) if session_limit > 0 else 0
    weekly_pct = round(openai_weekly_total / weekly_limit * 100, 1) if weekly_limit > 0 else 0
    worst_percent = max(worst_percent, session_pct, weekly_pct)

    response["openai"] = {
        "label": label,
        "tier": openai_config.get("tier", ""),
        "sessionWindowHours": openai_session_hours,
        "rolling5h": {
            "inputTokens": 0,  # Codex SQLite only tracks total, not input/output split
            "outputTokens": 0,
            "totalTokens": openai_session_total,
            "windowStart": datetime.fromtimestamp(openai_session_cutoff_s).isoformat(),
            "windowHours": openai_session_hours,
            "estimatedLimit": session_limit,
            "percentUsed": session_pct,
            "remainingTokens": max(0, session_limit - openai_session_total) if session_limit > 0 else None,
        },
        "rollingWeek": {
            "inputTokens": 0,
            "outputTokens": 0,
            "totalTokens": openai_weekly_total,
            "windowStart": datetime.fromtimestamp(week_cutoff_s).isoformat(),
            "estimatedLimit": weekly_limit,
            "percentUsed": weekly_pct,
            "remainingTokens": max(0, weekly_limit - openai_weekly_total) if weekly_limit > 0 else None,
        },
        "dataSources": {
            "codexSqlite": {
                "available": codex_data["available"],
                "sessionTokens": codex_data["session"]["total_tokens"],
                "weeklyTokens": codex_data["weekly"]["total_tokens"],
                "threadCountSession": codex_data.get("thread_count_session", 0),
                "threadCountWeekly": codex_data.get("thread_count_weekly", 0),
                "bySource": codex_data["session"].get("by_model", {}),
                "error": codex_data.get("error"),
            },
            "openclaw": {
                "sessionTokens": oc_openai["session"]["total_tokens"],
                "weeklyTokens": oc_openai["7d"]["total_tokens"],
            },
        },
    }

    # OpenAI warnings
    if session_pct >= 90:
        warnings.append(f"\U0001f534 {label} {openai_session_hours}h window at {session_pct}% — STOP or slow down!")
    elif session_pct >= 80:
        warnings.append(f"\U0001f7e1 {label} {openai_session_hours}h window at {session_pct}% — approaching limit")
    elif session_pct >= 60:
        warnings.append(f"\U0001f7e1 {label} {openai_session_hours}h window at {session_pct}%")

    if weekly_pct >= 90:
        warnings.append(f"\U0001f534 {label} weekly at {weekly_pct}% — budget critically low!")
    elif weekly_pct >= 80:
        warnings.append(f"\U0001f7e1 {label} weekly at {weekly_pct}% — approaching limit")
    elif weekly_pct >= 60:
        warnings.append(f"\U0001f7e1 {label} weekly at {weekly_pct}%")

    # Overall traffic light
    if worst_percent >= 80:
        traffic_light = "red"
    elif worst_percent >= 60:
        traffic_light = "yellow"
    else:
        traffic_light = "green"

    response["_meta"] = {
        "warnings": warnings,
        "trafficLight": traffic_light,
        "worstPercent": worst_percent,
        "calculatedAt": datetime.now().isoformat(),
        "dataSourceStatus": {
            "codexSqlite": codex_data["available"],
            "claudeCode": claude_data["available"],
            "openclawSessions": True,  # always available (may just be empty)
        },
    }

    return jsonify(response)


@openclaw_bp.route("/openclaw/rate-limits/config", methods=["GET"])
def openclaw_rate_limits_config_get():
    """Get the current rate limits config."""
    return jsonify(_read_rate_limits_config())


@openclaw_bp.route("/openclaw/rate-limits/config", methods=["POST"])
def openclaw_rate_limits_config_set():
    """Update rate limits config (partial merge)."""
    try:
        updates = request.get_json(force=True)
        config = _read_rate_limits_config()
        for provider_key, pval in updates.items():
            if isinstance(pval, dict):
                if provider_key not in config:
                    config[provider_key] = {}
                config[provider_key].update(pval)
        with open(RATE_LIMITS_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return jsonify({"ok": True, "config": config})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ---------------------------------------------------------------------------
# Sessions & Subagents
# ---------------------------------------------------------------------------

def _read_sessions():
    """Read sessions.json and return the dict of sessions."""
    if not os.path.isfile(SESSIONS_FILE):
        return {}
    try:
        with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _read_subagent_runs():
    """Read subagents/runs.json and return the runs dict."""
    if not os.path.isfile(SUBAGENT_RUNS_FILE):
        return {}
    try:
        with open(SUBAGENT_RUNS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("runs", {}) if isinstance(data, dict) else {}
    except Exception:
        return {}


def _session_status(updated_at_ms):
    """Classify session freshness: active/recent/idle."""
    if not updated_at_ms:
        return "idle"
    now_ms = time.time() * 1000
    age_ms = now_ms - updated_at_ms
    if age_ms < 30 * 60 * 1000:    # 30 min
        return "active"
    elif age_ms < 2 * 3600 * 1000:  # 2 hours
        return "recent"
    return "idle"


def _stat_session_file(session_id):
    """Try to stat a session JSONL file, return {size, mtime} or None."""
    if not session_id or not os.path.isdir(SESSIONS_DIR):
        return None
    # Session files may have various naming patterns
    for path in glob.glob(os.path.join(SESSIONS_DIR, f"*{session_id}*.jsonl")):
        try:
            st = os.stat(path)
            return {"size": st.st_size, "mtime": st.st_mtime}
        except Exception:
            continue
    return None


@openclaw_bp.route("/openclaw/sessions", methods=["GET"])
def openclaw_sessions():
    """Live session registry with freshness classification."""
    limit = request.args.get("limit", 30, type=int)
    limit = max(1, min(limit, 200))

    sessions = _read_sessions()
    result = []

    for session_key, s in sessions.items():
        updated_at = s.get("updatedAt", 0)
        session_id = s.get("sessionId", "")
        file_stat = _stat_session_file(session_id)

        result.append({
            "sessionKey": session_key,
            "sessionId": session_id,
            "displayName": s.get("displayName", session_key),
            "channel": s.get("channel", ""),
            "groupChannel": s.get("groupChannel", ""),
            "chatType": s.get("chatType", ""),
            "model": s.get("model", ""),
            "modelProvider": s.get("modelProvider", ""),
            "updatedAt": updated_at,
            "updatedAtRelative": _relative_time_label(updated_at),
            "totalTokens": s.get("totalTokens", 0),
            "inputTokens": s.get("inputTokens", 0),
            "outputTokens": s.get("outputTokens", 0),
            "cacheRead": s.get("cacheRead", 0),
            "compactionCount": s.get("compactionCount", 0),
            "status": _session_status(updated_at),
            "fileSize": file_stat["size"] if file_stat else 0,
        })

    # Sort by updatedAt descending
    result.sort(key=lambda x: x.get("updatedAt", 0), reverse=True)
    return jsonify(result[:limit])


@openclaw_bp.route("/openclaw/subagents", methods=["GET"])
def openclaw_subagents():
    """Subagent run history."""
    runs = _read_subagent_runs()
    dismissed = _read_dismissed()
    result = []

    for run_id, r in runs.items():
        created_at = r.get("createdAt", 0)
        task = r.get("task", "")
        result_text = r.get("frozenResultText", "")
        ended_at = r.get("endedAt", 0)
        duration_ms = (ended_at - created_at) if ended_at and created_at else None
        agent_label = r.get("label", "")
        result.append({
            "runId": run_id,
            "label": agent_label,
            "model": r.get("model", ""),
            "createdAt": created_at,
            "createdAtRelative": _relative_time_label(created_at),
            "task": task[:200] if task else "",
            "status": r.get("outcome", {}).get("status", "") if r.get("outcome") else (r.get("status", "running")),
            "runtime": r.get("runtime", ""),
            "endedAt": ended_at,
            "endedReason": r.get("endedReason", ""),
            "result": result_text[:500] if result_text else "",
            "durationMs": duration_ms,
            "dismissed": agent_label in dismissed,
        })

    # Sort by createdAt descending
    result.sort(key=lambda x: x.get("createdAt", 0), reverse=True)
    return jsonify(result)


@openclaw_bp.route("/openclaw/agents", methods=["GET"])
def openclaw_agents_combined():
    """Combined agent view for the pixel office — who's in the office right now."""
    now_ms = time.time() * 1000
    agents = []
    dismissed = _read_dismissed()

    # 1. Main agent "Cali" — derive state from the most recent active session
    sessions = _read_sessions()
    most_recent = None
    for sk, s in sessions.items():
        updated = s.get("updatedAt", 0)
        if most_recent is None or updated > most_recent.get("updatedAt", 0):
            most_recent = s

    if most_recent:
        age_ms = now_ms - most_recent.get("updatedAt", 0)
        if age_ms < 5 * 60 * 1000:
            main_state = "executing"
        elif age_ms < 30 * 60 * 1000:
            main_state = "writing"
        else:
            main_state = "idle"
        main_detail = most_recent.get("displayName", "")
    else:
        main_state = "idle"
        main_detail = ""

    agents.append({
        "name": "Cali",
        "type": "main",
        "state": main_state,
        "detail": main_detail,
        "model": most_recent.get("model", "") if most_recent else "",
        "startedAt": most_recent.get("updatedAt", 0) if most_recent else 0,
        "tokens": most_recent.get("totalTokens", 0) if most_recent else 0,
    })

    # 2. Active subagent runs (only REAL subagents with meaningful labels)
    runs = _read_subagent_runs()
    # UUID/hash detection regex
    _uuid_like_re = re.compile(r'^[0-9a-f]{8,}(?:-[0-9a-f]{4,}){0,4}$', re.IGNORECASE)

    for run_id, r in runs.items():
        created_at = r.get("createdAt", 0)
        ended_at = r.get("endedAt", 0)
        age_ms = now_ms - created_at

        # Only show subagents from the last 2 hours
        if age_ms > 2 * 3600 * 1000:
            continue

        # Skip dismissed agents
        label = r.get("label", run_id[:8])
        if label in dismissed:
            continue

        # Skip agents with UUID-like or hash-like names (not meaningful labels)
        if _uuid_like_re.match(label.strip()):
            continue

        # Determine state
        outcome = r.get("outcome", {})
        outcome_status = outcome.get("status", "") if outcome else ""

        if ended_at and ended_at > 0:
            # Finished
            if outcome_status == "error":
                sa_state = "error"
            else:
                # Recently finished — show briefly then they'll age out
                if now_ms - ended_at < 30 * 60 * 1000:
                    sa_state = "idle"
                else:
                    continue  # Don't show old finished agents
        else:
            # Still running
            if age_ms < 5 * 60 * 1000:
                sa_state = "executing"
            elif age_ms < 30 * 60 * 1000:
                sa_state = "researching"
            else:
                sa_state = "writing"

        task = r.get("task", "")
        result_text = r.get("frozenResultText", "")
        # Result snippet: first 100 chars for dashboard preview
        result_snippet = (result_text[:100] + "…") if result_text and len(result_text) > 100 else (result_text or "")
        agents.append({
            "name": r.get("label", run_id[:8]),
            "type": "subagent",
            "state": sa_state,
            "detail": task[:120] if task else "",
            "model": r.get("model", ""),
            "startedAt": created_at,
            "tokens": 0,
            "runId": run_id,
            "endedAt": ended_at,
            "result": result_text[:300] if result_text else "",
            "resultSnippet": result_snippet,
            "endedReason": r.get("endedReason", ""),
        })

    # 2b. Active sessions not covered by runs.json
    #     Surfaces orphaned subagents (NOT cron sessions — handled in section 3).
    #     Thread sessions are NOT included as separate agents — they are
    #     folded into the main Cali entry as activeThreads.
    five_min_ms = 5 * 60 * 1000

    # Build a set of session keys already represented by subagent runs
    covered_session_keys = set()
    for run_id, r in runs.items():
        child_key = r.get("childSessionKey", "")
        if child_key:
            covered_session_keys.add(child_key)

    # Collect active threads for the main Cali entry
    active_threads = []

    # UUID/hash detection regex — names that look like raw IDs, not labels
    _uuid_like_re = re.compile(r'^[0-9a-f]{8,}(?:-[0-9a-f]{4,}){0,4}$', re.IGNORECASE)

    for session_key, s in sessions.items():
        updated_at = s.get("updatedAt", 0)
        age_ms = now_ms - updated_at
        # Tightened freshness window: 5 minutes (was 30)
        if age_ms > five_min_ms:
            continue

        # Skip the main heartbeat session
        if session_key == "agent:main:main":
            continue

        # Skip sessions already covered by a subagent run
        if session_key in covered_session_keys:
            continue
        # Also check if any covered key is a substring match
        skip = False
        for ck in covered_session_keys:
            if ck and ck in session_key:
                skip = True
                break
        if skip:
            continue

        # Determine session type from key
        if "subagent:" in session_key:
            sess_type = "subagent"
        elif "discord:channel:" in session_key:
            sess_type = "thread"
        elif "cron:" in session_key:
            # Cron sessions are handled by section 3 — skip here entirely
            continue
        else:
            sess_type = "thread"  # default for other active sessions

        # Extract display name
        display_name = s.get("displayName", "") or ""
        clean_name = ""
        if display_name:
            channel_match = re.search(r"#([\w-]+)", display_name)
            if channel_match:
                clean_name = "#" + channel_match.group(1)
            else:
                clean_name = display_name
        if not clean_name:
            if "discord:channel:" in session_key:
                clean_name = "Discord thread"
            elif "subagent:" in session_key:
                parts = session_key.split("subagent:")
                clean_name = parts[-1][:30] if len(parts) > 1 else "Subagent"
            elif "cron:" in session_key:
                parts = session_key.split("cron:")
                clean_name = parts[-1][:30] if len(parts) > 1 else "Cron job"
            else:
                clean_name = session_key[:30]

        # --- Thread sessions go into activeThreads, NOT as separate agents ---
        if sess_type == "thread":
            if age_ms < five_min_ms:
                thread_state = "executing"
            else:
                thread_state = "writing"
            active_threads.append({
                "name": clean_name,
                "state": thread_state,
                "displayName": display_name or session_key,
                "updatedAt": updated_at,
                "sessionKey": session_key,
                "totalTokens": s.get("totalTokens", 0) or 0,
                "model": s.get("model", "") or "",
                "sessionAge": _relative_time_label(s.get("createdAt", updated_at) or updated_at),
                "lastActivityAge": _relative_time_label(updated_at),
            })
            continue

        # For subagent sessions from sessions.json (not runs.json),
        # skip if the name looks like a UUID/hash
        if sess_type == "subagent":
            # Extract the actual label portion
            label_part = clean_name.strip()
            if _uuid_like_re.match(label_part):
                continue

        # Only subagent and cron types reach here
        if sess_type == "subagent":
            agent_name = clean_name
        elif sess_type == "cron":
            agent_name = clean_name
        else:
            agent_name = clean_name

        # Check dismissed
        if agent_name in dismissed or session_key in dismissed:
            continue

        # Determine state from freshness
        if age_ms < five_min_ms:
            sess_state = "executing"
        else:
            sess_state = "writing"

        agents.append({
            "name": agent_name,
            "type": sess_type,
            "state": sess_state,
            "detail": display_name or session_key,
            "model": s.get("model", ""),
            "startedAt": updated_at,
            "tokens": s.get("totalTokens", 0) or 0,
            "sessionKey": session_key,
            "updatedAt": updated_at,
        })

    # Attach activeThreads to the main Cali agent entry
    main_entry = next((a for a in agents if a.get("type") == "main"), None)
    if main_entry is not None:
        main_entry["activeThreads"] = active_threads

    # 3. Cron jobs — ephemeral workers, short linger
    #    - Running: show at desk
    #    - Finished: show for 60 seconds max, then leave
    #    - Cron run sub-sessions (cron:*:run:*) are NOT shown as separate characters
    jobs = _read_jobs()
    # Regex to detect cron run sub-sessions (e.g. "cron:weekend-activities:run:1f412cb")
    _cron_run_re = re.compile(r'cron:.*:run:', re.IGNORECASE)

    for j in jobs:
        if not j.get("enabled"):
            continue
        state = j.get("state", {}) or {}
        last_run_ms = state.get("lastRunAtMs", 0)
        last_duration = state.get("lastDurationMs", 0)
        last_status = state.get("lastRunStatus") or state.get("lastStatus", "")
        job_name = j.get("name", j.get("id", "cron"))

        # Skip if dismissed
        if job_name in dismissed:
            continue

        if not last_run_ms:
            continue

        age_since_run_ms = now_ms - last_run_ms

        # Only show cron jobs active in the last 2 minutes
        if age_since_run_ms > 2 * 60 * 1000:
            continue

        # Determine cron state
        if last_status not in ("ok", "error", "skipped", ""):
            # Still running
            cron_state = "executing"
        else:
            # Finished — show for 60 seconds max, then they leave
            estimated_end_ms = last_run_ms + (last_duration or 0)
            time_since_end = now_ms - estimated_end_ms
            if time_since_end < 60 * 1000:  # 60 second linger
                cron_state = "idle"
            else:
                continue  # Don't show — finished and linger expired

        agents.append({
            "name": job_name,
            "type": "cron",
            "state": cron_state,
            "detail": f"cron: {j.get('schedule', {}).get('expr', '')}",
            "model": j.get("payload", {}).get("model", ""),
            "startedAt": last_run_ms,
            "tokens": 0,
        })

    # --- Write main agent state to state.json (server-side sync) ---
    # Only write if state or detail actually changed to prevent flickering
    main_entry = next((a for a in agents if a.get("type") == "main"), None)
    if main_entry:
        state_map = {
            "executing": "writing",
            "writing": "writing",
            "researching": "researching",
            "idle": "idle",
            "error": "error",
            "syncing": "syncing",
        }
        mapped = state_map.get(main_entry.get("state", "idle"), "idle")
        new_detail = main_entry.get("detail", "")
        state_json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state.json")
        try:
            # Read current state.json and compare before writing
            current_state = None
            current_detail = None
            if os.path.isfile(state_json_path):
                try:
                    with open(state_json_path, "r", encoding="utf-8") as sf:
                        existing = json.load(sf)
                    current_state = existing.get("state")
                    current_detail = existing.get("detail")
                except Exception:
                    pass  # file corrupt or missing, write fresh

            # Only write if state or detail actually changed
            if current_state != mapped or current_detail != new_detail:
                state_payload = {
                    "state": mapped,
                    "detail": new_detail,
                    "progress": 0,
                    "updated_at": datetime.now().isoformat(),
                }
                with open(state_json_path, "w", encoding="utf-8") as sf:
                    json.dump(state_payload, sf)
        except Exception:
            pass  # non-fatal; don't break the API response

    return jsonify(agents)


# ---------------------------------------------------------------------------
# Dismiss endpoint
# ---------------------------------------------------------------------------

@openclaw_bp.route("/openclaw/agent/<name>/dismiss", methods=["POST"])
def openclaw_dismiss_agent(name):
    """Mark a subagent as dismissed so it no longer appears in the office."""
    dismissed = _read_dismissed()
    dismissed[name] = int(time.time() * 1000)
    _write_dismissed(dismissed)
    return jsonify({"ok": True, "dismissed": name})


# ---------------------------------------------------------------------------
# Detail endpoints
# ---------------------------------------------------------------------------

@openclaw_bp.route("/openclaw/agent/<name>", methods=["GET"])
def openclaw_agent_detail(name):
    """Full detail for a single agent by name."""
    now_ms = time.time() * 1000

    # Check if it's the main agent
    if name.lower() in ("cali", "main"):
        sessions = _read_sessions()
        most_recent = None
        for sk, s in sessions.items():
            updated = s.get("updatedAt", 0)
            if most_recent is None or updated > most_recent.get("updatedAt", 0):
                most_recent = s

        if most_recent:
            age_ms = now_ms - most_recent.get("updatedAt", 0)
            if age_ms < 5 * 60 * 1000:
                main_state = "executing"
            elif age_ms < 30 * 60 * 1000:
                main_state = "writing"
            else:
                main_state = "idle"
        else:
            main_state = "idle"

        # Collect recent sessions
        recent_sessions = []
        for sk, s in sessions.items():
            recent_sessions.append({
                "sessionKey": sk,
                "displayName": s.get("displayName", sk),
                "channel": s.get("channel", ""),
                "chatType": s.get("chatType", ""),
                "model": s.get("model", ""),
                "modelProvider": s.get("modelProvider", ""),
                "updatedAt": s.get("updatedAt", 0),
                "updatedAtRelative": _relative_time_label(s.get("updatedAt", 0)),
                "totalTokens": s.get("totalTokens", 0),
                "inputTokens": s.get("inputTokens", 0),
                "outputTokens": s.get("outputTokens", 0),
                "cacheRead": s.get("cacheRead", 0),
                "cacheWrite": s.get("cacheWrite", 0),
                "compactionCount": s.get("compactionCount", 0),
                "status": _session_status(s.get("updatedAt", 0)),
            })
        recent_sessions.sort(key=lambda x: x.get("updatedAt", 0), reverse=True)

        return jsonify({
            "name": "Cali",
            "type": "main",
            "state": main_state,
            "detail": most_recent.get("displayName", "") if most_recent else "",
            "model": most_recent.get("model", "") if most_recent else "",
            "modelProvider": most_recent.get("modelProvider", "") if most_recent else "",
            "startedAt": most_recent.get("updatedAt", 0) if most_recent else 0,
            "startedAtRelative": _relative_time_label(most_recent.get("updatedAt", 0)) if most_recent else None,
            "totalTokens": most_recent.get("totalTokens", 0) if most_recent else 0,
            "inputTokens": most_recent.get("inputTokens", 0) if most_recent else 0,
            "outputTokens": most_recent.get("outputTokens", 0) if most_recent else 0,
            "recentSessions": recent_sessions[:10],
        })

    # Check subagent runs
    runs = _read_subagent_runs()
    for run_id, r in runs.items():
        label = r.get("label", run_id[:8])
        if label == name or run_id.startswith(name):
            task = r.get("task", "")
            outcome = r.get("outcome", {}) or {}
            created_at = r.get("createdAt", 0)
            ended_at = r.get("endedAt", 0)

            if ended_at and ended_at > 0:
                outcome_status = outcome.get("status", "completed")
                sa_state = "error" if outcome_status == "error" else "idle"
            else:
                age_ms = now_ms - created_at
                if age_ms < 5 * 60 * 1000:
                    sa_state = "executing"
                elif age_ms < 30 * 60 * 1000:
                    sa_state = "researching"
                else:
                    sa_state = "writing"

            # Duration
            duration_ms = None
            if ended_at and created_at:
                duration_ms = ended_at - created_at

            return jsonify({
                "name": label,
                "type": "subagent",
                "state": sa_state,
                "detail": task,
                "model": r.get("model", ""),
                "runtime": r.get("runtime", ""),
                "startedAt": created_at,
                "startedAtRelative": _relative_time_label(created_at),
                "endedAt": ended_at,
                "endedAtRelative": _relative_time_label(ended_at) if ended_at else None,
                "durationMs": duration_ms,
                "endedReason": r.get("endedReason", ""),
                "outcome": outcome,
                "runId": run_id,
                "result": r.get("frozenResultText", ""),
                "controllerSession": r.get("controllerSessionKey", ""),
                "requesterDisplay": r.get("requesterDisplayKey", ""),
            })

    # Check cron jobs
    jobs = _read_jobs()
    for j in jobs:
        if j.get("name") == name or j.get("id") == name:
            state = j.get("state", {}) or {}
            schedule = j.get("schedule", {}) or {}
            payload = j.get("payload", {}) or {}

            # Get recent runs for this job
            job_id = j.get("id", "")
            all_runs = _read_all_runs()
            job_runs = [r for r in all_runs if r.get("jobId") == job_id]
            job_runs.sort(key=lambda r: r.get("ts", 0), reverse=True)
            recent_runs = []
            for r in job_runs[:10]:
                usage = r.get("usage") or {}
                recent_runs.append({
                    "ts": r.get("ts"),
                    "status": r.get("status"),
                    "durationMs": r.get("durationMs"),
                    "model": r.get("model"),
                    "tokens": {
                        "input": usage.get("input_tokens", 0),
                        "output": usage.get("output_tokens", 0),
                        "total": usage.get("total_tokens", 0),
                    },
                    "delivered": r.get("delivered"),
                    "summary": (r.get("summary") or "")[:500],
                })

            return jsonify({
                "name": j.get("name"),
                "type": "cron",
                "state": "executing" if state.get("lastRunStatus") not in ("ok", "error", "skipped", None, "") else "idle",
                "detail": f"cron: {schedule.get('expr', '')}",
                "model": payload.get("model", ""),
                "jobId": job_id,
                "enabled": j.get("enabled", False),
                "schedule": schedule.get("expr", ""),
                "tz": schedule.get("tz", ""),
                "lastRun": {
                    "at": state.get("lastRunAtMs"),
                    "atRelative": _relative_time_label(state.get("lastRunAtMs")),
                    "status": state.get("lastRunStatus") or state.get("lastStatus"),
                    "durationMs": state.get("lastDurationMs"),
                },
                "nextRunAt": state.get("nextRunAtMs"),
                "nextRunAtRelative": _relative_time_label(state.get("nextRunAtMs")),
                "consecutiveErrors": state.get("consecutiveErrors", 0),
                "recentRuns": recent_runs,
            })

    # Check active sessions (thread/subagent/cron sessions not in runs.json)
    sessions = _read_sessions()
    # Strip emoji prefixes for matching (💬, ⚡, ⏰ etc.)
    clean_name = re.sub(r'^[\U0001f4ac\u26a1\u23f0\U0001f525\s]+', '', name).strip()
    for session_key, s in sessions.items():
        display_name = s.get("displayName", "") or ""
        # Match by session key or by cleaned display name containing the search name
        if clean_name in session_key or clean_name in display_name or session_key == name or clean_name == name:
            updated_at = s.get("updatedAt", 0)
            age_ms = now_ms - updated_at

            if "subagent:" in session_key:
                sess_type = "subagent"
            elif "discord:channel:" in session_key:
                sess_type = "thread"
            elif "cron:" in session_key:
                sess_type = "cron"
            else:
                sess_type = "thread"

            if age_ms < 5 * 60 * 1000:
                sess_state = "executing"
            elif age_ms < 30 * 60 * 1000:
                sess_state = "writing"
            else:
                sess_state = "idle"

            return jsonify({
                "name": name,
                "type": sess_type,
                "state": sess_state,
                "detail": display_name or session_key,
                "model": s.get("model", ""),
                "modelProvider": s.get("modelProvider", ""),
                "startedAt": updated_at,
                "startedAtRelative": _relative_time_label(updated_at),
                "totalTokens": s.get("totalTokens", 0) or 0,
                "inputTokens": s.get("inputTokens", 0) or 0,
                "outputTokens": s.get("outputTokens", 0) or 0,
                "cacheRead": s.get("cacheRead", 0) or 0,
                "sessionKey": session_key,
                "channel": s.get("channel", ""),
                "chatType": s.get("chatType", ""),
            })

    return jsonify({"error": "Agent not found"}), 404


@openclaw_bp.route("/openclaw/cron/<job_id>/runs", methods=["GET"])
def openclaw_cron_runs(job_id):
    """Recent run history for a specific cron job."""
    limit = request.args.get("limit", 5, type=int)
    limit = max(1, min(limit, 50))

    all_runs = _read_all_runs()
    job_runs = [r for r in all_runs if r.get("jobId") == job_id]
    job_runs.sort(key=lambda r: r.get("ts", 0), reverse=True)

    result = []
    for r in job_runs[:limit]:
        usage = r.get("usage") or {}
        result.append({
            "ts": r.get("ts"),
            "tsRelative": _relative_time_label(r.get("ts")),
            "status": r.get("status"),
            "durationMs": r.get("durationMs"),
            "model": r.get("model"),
            "provider": r.get("provider"),
            "tokens": {
                "input": usage.get("input_tokens", 0),
                "output": usage.get("output_tokens", 0),
                "total": usage.get("total_tokens", 0),
            },
            "delivered": r.get("delivered"),
            "summary": (r.get("summary") or "")[:500],
        })

    return jsonify(result)
