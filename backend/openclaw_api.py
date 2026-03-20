"""OpenClaw Dashboard API — read-only integration with OpenClaw data directory.

Provides:
  GET /openclaw/status    — gateway health + cron summary
  GET /openclaw/cron      — all cron jobs with state
  GET /openclaw/activity  — recent cron run history
  GET /openclaw/costs     — token usage aggregation
  GET /openclaw/sessions  — live session registry
  GET /openclaw/subagents — subagent run history
  GET /openclaw/agents    — combined agent view for pixel office
"""

import glob
import json
import os
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
    result = []

    for run_id, r in runs.items():
        created_at = r.get("createdAt", 0)
        task = r.get("task", "")
        result_text = r.get("frozenResultText", "")
        ended_at = r.get("endedAt", 0)
        duration_ms = (ended_at - created_at) if ended_at and created_at else None
        result.append({
            "runId": run_id,
            "label": r.get("label", ""),
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
        })

    # Sort by createdAt descending
    result.sort(key=lambda x: x.get("createdAt", 0), reverse=True)
    return jsonify(result)


@openclaw_bp.route("/openclaw/agents", methods=["GET"])
def openclaw_agents_combined():
    """Combined agent view for the pixel office — who's in the office right now."""
    now_ms = time.time() * 1000
    agents = []

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

    # 2. Active subagent runs
    runs = _read_subagent_runs()
    for run_id, r in runs.items():
        created_at = r.get("createdAt", 0)
        ended_at = r.get("endedAt", 0)
        age_ms = now_ms - created_at

        # Only show subagents from the last 2 hours
        if age_ms > 2 * 3600 * 1000:
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
            "endedReason": r.get("endedReason", ""),
        })

    # 3. Currently-running cron jobs
    jobs = _read_jobs()
    for j in jobs:
        if not j.get("enabled"):
            continue
        state = j.get("state", {}) or {}
        last_run_ms = state.get("lastRunAtMs", 0)
        last_duration = state.get("lastDurationMs", 0)
        last_status = state.get("lastRunStatus") or state.get("lastStatus", "")

        # Consider a cron job "running" if it ran recently and hasn't finished
        # Heuristic: last run was within 5 minutes and status isn't a terminal state
        if last_run_ms and (now_ms - last_run_ms) < 5 * 60 * 1000:
            if last_status not in ("ok", "error", "skipped"):
                agents.append({
                    "name": j.get("name", j.get("id", "cron")),
                    "type": "cron",
                    "state": "executing",
                    "detail": f"cron: {j.get('schedule', {}).get('expr', '')}",
                    "model": j.get("payload", {}).get("model", ""),
                    "startedAt": last_run_ms,
                    "tokens": 0,
                })

    # --- Write main agent state to state.json (server-side sync) ---
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
        state_json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state.json")
        try:
            state_payload = {
                "state": mapped,
                "detail": main_entry.get("detail", ""),
                "progress": 0,
                "updated_at": datetime.now().isoformat(),
            }
            with open(state_json_path, "w", encoding="utf-8") as sf:
                json.dump(state_payload, sf)
        except Exception:
            pass  # non-fatal; don't break the API response

    return jsonify(agents)


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
