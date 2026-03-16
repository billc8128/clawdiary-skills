#!/usr/bin/env python3
"""
ClawDiary CLI — deterministic session processing and report upload.

Two subcommands:
  prepare   — auth, data discovery, tier selection, scanning, compression
  finalize  — validate, upload, return URL

Zero external dependencies (stdlib only).
"""


import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _parse_iso(s: str) -> datetime:
    """Parse ISO 8601 timestamp, compatible with Python 3.6+."""
    s = s.replace("Z", "").replace("+00:00", "")
    if "." in s:
        base, frac = s.split(".", 1)
        s = base + "." + frac[:6]
        try:
            return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_URL = "https://clawdiary.ai"
CRED_FILE = Path.home() / ".clawdiary" / "credentials.json"
PARTS_DIR = Path("_cr_parts")
COMPRESSED_DIR = PARTS_DIR / "compressed"

# OpenClaw paths
OPENCLAW_HOME = Path.home() / ".openclaw"
WORKSPACE_DIR = OPENCLAW_HOME / "workspace"
SESSIONS_DIR = OPENCLAW_HOME / "agents" / "main" / "sessions"
MEMORY_LOGS_DIR = WORKSPACE_DIR / "memory"
MEMORY_DB_PATH = OPENCLAW_HOME / "memory" / "main.sqlite"
CONFIG_PATH = OPENCLAW_HOME / "openclaw.json"
CRON_DIR = OPENCLAW_HOME / "cron"
EXTENSIONS_DIR = OPENCLAW_HOME / "extensions"

# Workspace files by priority
WORKSPACE_PRIORITY_FILES = [
    "SOUL.md", "USER.md", "MEMORY.md", "IDENTITY.md",
    "AGENTS.md", "TOOLS.md", "HEARTBEAT.md",
]

# Skill directories (OpenClaw only)
SKILL_DIRS = [
    OPENCLAW_HOME / "skills",
    WORKSPACE_DIR / "skills",
]

TOKEN_CACHE_PATH = Path.home() / ".clawdiary" / "token-cache.json"
TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)

# Tier parameters
TIER_PARAMS = {
    "quick": {
        "session_recent": 5,
        "session_largest": 0,
        "max_msg_len": 2000,
        "tool_result_len": 0,
        "memory_logs_days": 0,
        "workspace_files": 4,
        "memory_db_limit": 0,
        "cron_runs_days": 0,
        "scan_extensions": False,
    },
    "standard": {
        "session_recent": 15,
        "session_largest": 5,
        "max_msg_len": 2000,
        "tool_result_len": 200,
        "memory_logs_days": 14,
        "workspace_files": 99,
        "memory_db_limit": 0,
        "cron_runs_days": 7,
        "scan_extensions": True,
    },
    "deep": {
        "session_recent": 30,
        "session_largest": 10,
        "max_msg_len": 5000,
        "tool_result_len": 500,
        "memory_logs_days": 999,
        "workspace_files": 99,
        "memory_db_limit": 50,
        "cron_runs_days": 999,
        "scan_extensions": True,
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str, code: int = 1) -> None:
    print(f"FATAL: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data, indent: Optional[int] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent, default=str)
    tmp.replace(path)


def fingerprint(path: str, size: int, mtime: int) -> str:
    return hashlib.sha256(f"{path}|{size}|{mtime}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def ensure_auth() -> dict:
    """Return credentials dict; register if needed."""
    if CRED_FILE.is_file():
        creds = load_json(CRED_FILE)
        try:
            req = urllib.request.Request(
                f"{creds['api_url']}/api/claw/status",
                headers={"Authorization": f"Bearer {creds['api_key']}"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = json.loads(resp.read())
            log(f"Authenticated. Status: {status.get('status', 'ok')}")
            if status.get("status") == "pending_claim":
                log(f"  Claim link: {creds.get('claim_url', '(unknown)')}")
            return creds
        except Exception as e:
            log(f"  Status check failed ({e}), continuing with cached creds")
            return creds

    log("No credentials found. Registering...")
    payload = json.dumps({
        "name": "OpenClaw",
        "description": "A loyal and opinionated AI assistant",
    }).encode()
    req = urllib.request.Request(
        f"{API_URL}/api/claw/register",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        die(f"Registration failed: {e}")

    creds = {
        "api_url": API_URL,
        "api_key": data["api_key"],
        "claw_id": data["claw_id"],
        "slug": data["slug"],
        "claim_url": data["claim_url"],
    }
    save_json(CRED_FILE, creds, indent=2)
    log(f"Registered! Claim link: {creds['claim_url']}")
    return creds


# ---------------------------------------------------------------------------
# Data Discovery
# ---------------------------------------------------------------------------

def discover_data() -> dict:
    """Scan OpenClaw home, return data inventory without reading content."""
    inventory = {
        "openclaw_home": str(OPENCLAW_HOME),
        "exists": OPENCLAW_HOME.is_dir(),
        "sessions": {"count": 0, "total_bytes": 0, "recent_30d": 0},
        "workspace": {"files": [], "memory_log_days": 0},
        "config": {"exists": False, "model": "", "plugins_count": 0},
        "cron": {"jobs_count": 0, "runs_count": 0},
        "extensions": [],
        "memory_db": {"exists": False, "size_bytes": 0},
        "skills": [],
    }

    if not OPENCLAW_HOME.is_dir():
        return inventory

    # Sessions
    now = datetime.now(timezone.utc).timestamp()
    cutoff_30d = now - 30 * 86400

    for sessions_dir in [SESSIONS_DIR, OPENCLAW_HOME / "sessions"]:
        if not sessions_dir.is_dir():
            continue
        glob_pattern = "*.jsonl" if sessions_dir == SESSIONS_DIR else "**/*.jsonl"
        for f in sessions_dir.glob(glob_pattern):
            try:
                stat = f.stat()
                inventory["sessions"]["count"] += 1
                inventory["sessions"]["total_bytes"] += stat.st_size
                if stat.st_mtime >= cutoff_30d:
                    inventory["sessions"]["recent_30d"] += 1
            except OSError:
                pass

    # Workspace files
    if WORKSPACE_DIR.is_dir():
        for name in WORKSPACE_PRIORITY_FILES:
            if (WORKSPACE_DIR / name).is_file():
                inventory["workspace"]["files"].append(name)
        for fpath in WORKSPACE_DIR.glob("*.md"):
            if fpath.name not in inventory["workspace"]["files"]:
                inventory["workspace"]["files"].append(fpath.name)

    # Memory logs
    if MEMORY_LOGS_DIR.is_dir():
        inventory["workspace"]["memory_log_days"] = sum(
            1 for _ in MEMORY_LOGS_DIR.glob("*.md")
        )

    # Config
    if CONFIG_PATH.is_file():
        inventory["config"]["exists"] = True
        try:
            config = load_json(CONFIG_PATH)
            model = config.get("model", {})
            if isinstance(model, dict):
                inventory["config"]["model"] = model.get("name", "") or model.get("model", "")
            elif isinstance(model, str):
                inventory["config"]["model"] = model
            plugins = config.get("plugins", [])
            inventory["config"]["plugins_count"] = len(plugins) if isinstance(plugins, list) else 0
        except (OSError, json.JSONDecodeError):
            pass

    # Cron
    jobs_path = CRON_DIR / "jobs.json"
    if jobs_path.is_file():
        try:
            jobs_data = load_json(jobs_path)
            if isinstance(jobs_data, list):
                inventory["cron"]["jobs_count"] = len(jobs_data)
            elif isinstance(jobs_data, dict):
                inventory["cron"]["jobs_count"] = len(jobs_data.get("jobs", []))
        except (OSError, json.JSONDecodeError):
            pass
    runs_dir = CRON_DIR / "runs"
    if runs_dir.is_dir():
        try:
            inventory["cron"]["runs_count"] = sum(1 for _ in runs_dir.iterdir())
        except OSError:
            pass

    # Extensions
    if EXTENSIONS_DIR.is_dir():
        try:
            inventory["extensions"] = [
                e.name for e in sorted(EXTENSIONS_DIR.iterdir()) if e.is_dir()
            ]
        except OSError:
            pass

    # Memory DB
    if MEMORY_DB_PATH.is_file():
        try:
            inventory["memory_db"]["exists"] = True
            inventory["memory_db"]["size_bytes"] = MEMORY_DB_PATH.stat().st_size
        except OSError:
            pass

    # Skills
    for sd in SKILL_DIRS:
        if sd.is_dir():
            try:
                for entry in sd.iterdir():
                    if entry.is_dir():
                        inventory["skills"].append(entry.name)
            except OSError:
                pass

    return inventory


def estimate_resources(tier: str, inventory: dict) -> dict:
    """Estimate token count and time for a given tier."""
    params = TIER_PARAMS[tier]
    est_tokens = 0

    # Sessions
    session_limit = params["session_recent"] + params["session_largest"]
    session_count = min(inventory["sessions"]["count"], session_limit)
    if inventory["sessions"]["count"] > 0:
        avg_bytes = inventory["sessions"]["total_bytes"] / inventory["sessions"]["count"]
    else:
        avg_bytes = 0
    # After compression: ~30% content survives, tokens ≈ bytes / 3
    est_tokens += int(session_count * avg_bytes * 0.3 / 3)

    # Workspace files
    ws_count = min(len(inventory["workspace"]["files"]), params["workspace_files"])
    est_tokens += ws_count * 2000

    # Memory logs
    if params["memory_logs_days"] > 0:
        log_days = min(inventory["workspace"]["memory_log_days"], params["memory_logs_days"])
        est_tokens += log_days * 1500

    # Config
    if inventory["config"]["exists"]:
        est_tokens += 500

    # Cron
    if inventory["cron"]["jobs_count"] > 0:
        runs_cap = min(inventory["cron"]["runs_count"], params["cron_runs_days"] * 5) if params["cron_runs_days"] > 0 else 0
        est_tokens += 300 + runs_cap * 200

    # Extensions
    if params["scan_extensions"] and inventory["extensions"]:
        est_tokens += len(inventory["extensions"]) * 300

    # Memory DB
    if params["memory_db_limit"] > 0 and inventory["memory_db"]["exists"]:
        est_tokens += params["memory_db_limit"] * 200

    est_time = max(30, int(est_tokens / 50000 * 60))

    return {"tokens": est_tokens, "time_seconds": est_time}


def select_tier(inventory: dict) -> str:
    """Display inventory + tier options, return user's choice."""
    total_mb = inventory["sessions"]["total_bytes"] / (1024 * 1024)

    log("")
    log("[scan] 数据发现:")
    log(f"  {inventory['sessions']['count']} 个 Session ({total_mb:.1f} MB, 最近 30 天 {inventory['sessions']['recent_30d']} 个)")

    ws_files = inventory["workspace"]["files"]
    if ws_files:
        display = ws_files[:6]
        suffix = f" + {len(ws_files) - 6} more" if len(ws_files) > 6 else ""
        log(f"  工作空间: {', '.join(display)}{suffix}")

    if inventory["workspace"]["memory_log_days"] > 0:
        log(f"  记忆日志: {inventory['workspace']['memory_log_days']} 天")

    if inventory["cron"]["jobs_count"] > 0:
        log(f"  自动化: {inventory['cron']['jobs_count']} 个定时任务")

    if inventory["memory_db"]["exists"]:
        db_mb = inventory["memory_db"]["size_bytes"] / (1024 * 1024)
        log(f"  记忆库: main.sqlite ({db_mb:.1f} MB)")

    config_parts = []
    if inventory["config"]["model"]:
        config_parts.append(inventory["config"]["model"])
    if inventory["config"]["plugins_count"]:
        config_parts.append(f"{inventory['config']['plugins_count']} 个插件")
    if config_parts:
        log(f"  配置: {', '.join(config_parts)}")

    log("")
    log("[scan] 扫描档位:")

    tier_info = [
        ("quick", "快速", "最近 5 个对话 + 核心身份文件"),
        ("standard", "标准", "推荐。对话+工作空间+记忆日志+自动化"),
        ("deep", "深度", "全量分析，低压缩对话+记忆数据库"),
    ]
    for i, (tier_name, label, desc) in enumerate(tier_info, 1):
        est = estimate_resources(tier_name, inventory)
        tokens_k = est["tokens"] / 1000
        if est["time_seconds"] < 120:
            time_str = f"~{est['time_seconds']}s"
        else:
            time_str = f"~{est['time_seconds'] // 60}min"
        log(f"  [{i}] {label}  (~{tokens_k:.0f}K tokens, {time_str})  — {desc}")

    log("")
    try:
        choice = input("  选择 [1/2/3] (默认 2): ").strip()
    except EOFError:
        choice = ""

    tier_map = {"1": "quick", "2": "standard", "3": "deep", "": "standard"}
    return tier_map.get(choice, "standard")


# ---------------------------------------------------------------------------
# Session Discovery
# ---------------------------------------------------------------------------

def discover_sessions() -> List[Path]:
    """Find all .jsonl session files from OpenClaw agents.

    Includes .deleted*, .bak*, .old files — JSONL is append-only,
    these still contain valid usage data for accurate token counting.
    """
    files: List[Path] = []

    # Primary: ~/.openclaw/agents/main/sessions/
    if SESSIONS_DIR.is_dir():
        for f in SESSIONS_DIR.iterdir():
            if f.is_symlink() or f.is_dir():
                continue
            if ".jsonl" in f.name:
                files.append(f)

    # Legacy path for backward compat
    legacy = OPENCLAW_HOME / "sessions"
    if legacy.is_dir():
        for f in legacy.rglob("*"):
            if f.is_symlink() or f.is_dir():
                continue
            if ".jsonl" in f.name:
                files.append(f)

    return sorted(set(files))


def filter_recent(files: List[Path], days: int = 30) -> List[Path]:
    """Keep only files modified within the last N days."""
    try:
        now = datetime.now(timezone.utc).timestamp()
    except Exception:
        now = datetime.utcnow().timestamp()
    cutoff = now - days * 86400
    result = []
    for f in files:
        try:
            if f.stat().st_mtime >= cutoff:
                result.append(f)
        except OSError:
            pass
    return result


def sample_sessions(files: List[Path], tier: str) -> List[Path]:
    """Select top N recent + top M largest based on tier, deduplicated."""
    params = TIER_PARAMS[tier]
    # Filter out symlinks to prevent directory escape
    safe_files = [f for f in files if not f.is_symlink()]
    # Cache stat results to avoid redundant syscalls
    stats = {f: f.stat() for f in safe_files}
    by_mtime = sorted(safe_files, key=lambda f: stats[f].st_mtime, reverse=True)
    by_size = sorted(safe_files, key=lambda f: stats[f].st_size, reverse=True)
    recent = set(by_mtime[:params["session_recent"]])
    largest = set(by_size[:params["session_largest"]]) if params["session_largest"] > 0 else set()
    combined = recent | largest
    return sorted(combined, key=lambda f: stats[f].st_mtime, reverse=True)


# ---------------------------------------------------------------------------
# Activity Extraction
# ---------------------------------------------------------------------------

def extract_timestamps(path: Path) -> List[datetime]:
    """Extract timestamps from a JSONL session file."""
    timestamps = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = obj.get("timestamp") or obj.get("ts")
                if ts:
                    if isinstance(ts, str):
                        try:
                            dt = _parse_iso(ts)
                            timestamps.append(dt)
                        except (ValueError, TypeError):
                            pass
                    elif isinstance(ts, (int, float)):
                        try:
                            if ts > 1e12:
                                ts = ts / 1000
                            timestamps.append(datetime.fromtimestamp(ts, tz=timezone.utc))
                        except (ValueError, OSError):
                            pass
    except OSError:
        pass
    if not timestamps:
        try:
            mtime = path.stat().st_mtime
            timestamps.append(datetime.fromtimestamp(mtime, tz=timezone.utc))
        except OSError:
            pass
    return timestamps


def extract_usage_from_jsonl(path: Path) -> dict:
    """Extract real token usage from JSONL session file.

    Supports two JSONL formats (both store usage inside entry.message.usage):
      - Claude Code: {"type":"assistant","message":{"role":"assistant","usage":{input_tokens,...}}}
      - OpenClaw:    {"type":"message","message":{"role":"assistant","usage":{input,...}}}

    Token calculation (aligned with token-stats):
      - "input" field can be NEGATIVE (provider double-subtraction via New-API proxy)
      - "totalTokens" is UNRELIABLE (arithmetic sum including negative input)
      - Correct formula: prompt = cacheRead + max(input, 0), total = prompt + output

    Returns {input, cacheRead, cacheWrite, output, total}.
    """
    usage = {"input": 0, "cacheRead": 0, "cacheWrite": 0, "output": 0}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                obj_type = obj.get("type", "")
                if obj_type not in ("assistant", "message"):
                    continue

                # Both formats: usage is inside entry.message.usage
                msg = obj.get("message", {})
                if msg.get("role") not in ("assistant", None):
                    continue
                u = msg.get("usage")
                if not u:
                    continue

                # Skip error responses
                if msg.get("stopReason") == "error":
                    continue

                # Anthropic API format keys → OpenClaw format keys
                inp = u.get("input_tokens", u.get("input", 0))
                cache_read = u.get("cache_read_input_tokens", u.get("cacheRead", u.get("cache_read", 0)))
                cache_write = u.get("cache_creation_input_tokens", u.get("cacheWrite", u.get("cache_write", 0)))
                output = u.get("output_tokens", u.get("output", 0))

                # input can be negative (New-API proxy double-subtraction bug)
                usage["input"] += max(0, inp)
                usage["cacheRead"] += cache_read
                usage["cacheWrite"] += cache_write
                usage["output"] += output
    except OSError:
        pass

    # total = prompt + output, where prompt = cacheRead + max(input, 0)
    # Do NOT use totalTokens field — it's tainted by negative input values
    usage["total"] = usage["cacheRead"] + usage["input"] + usage["output"]
    return usage


def extract_activity(all_sessions: List[Path]) -> dict:
    """Build per-day activity data from ALL sessions."""
    cache = {}
    try:
        cache = load_json(TOKEN_CACHE_PATH)
    except (OSError, json.JSONDecodeError):
        pass

    try:
        local_tz = datetime.now().astimezone().tzinfo
    except Exception:
        local_tz = timezone.utc

    next_cache = {}
    days: Dict[str, dict] = defaultdict(lambda: {"sessions": 0, "tokens": 0, "timestamps": []})
    total_tokens = 0
    total_usage = {"input": 0, "cacheRead": 0, "cacheWrite": 0, "output": 0}

    for path in all_sessions:
        spath = str(path)
        try:
            size = path.stat().st_size
            mtime = int(path.stat().st_mtime)
        except OSError:
            continue

        fp = fingerprint(spath, size, mtime)
        cached = cache.get(spath)
        if isinstance(cached, dict) and cached.get("fp") == fp and isinstance(cached.get("tokens"), int):
            tokens = cached["tokens"]
            # Also restore cached usage breakdown
            for k in ("input", "cacheRead", "cacheWrite", "output"):
                total_usage[k] += cached.get(k, 0)
        else:
            u = extract_usage_from_jsonl(path)
            tokens = u["total"]
            if tokens == 0:
                # Fallback: word count for non-JSONL or empty usage
                try:
                    data = path.read_bytes()[:8 * 1024 * 1024]
                    tokens = len(TOKEN_RE.findall(data.decode("utf-8", errors="replace")))
                except OSError:
                    tokens = size // 3
            else:
                for k in ("input", "cacheRead", "cacheWrite", "output"):
                    total_usage[k] += u[k]
            next_cache[spath] = {"fp": fp, "tokens": tokens,
                                 "input": u["input"], "cacheRead": u["cacheRead"],
                                 "cacheWrite": u["cacheWrite"], "output": u["output"]}
        total_tokens += tokens
        if spath not in next_cache:
            next_cache[spath] = {"fp": fp, "tokens": tokens}

        timestamps = extract_timestamps(path)
        if not timestamps:
            continue
        local_ts = [ts.astimezone(local_tz) for ts in timestamps]
        day_key = min(local_ts).strftime("%Y-%m-%d")
        day = days[day_key]
        day["sessions"] += 1
        day["tokens"] += tokens
        day["timestamps"].extend(local_ts)

    save_json(TOKEN_CACHE_PATH, next_cache)

    result: dict = {"days": [], "summary": {}}
    most_active_day, most_active_sessions = None, 0
    latest_night_date, latest_night_time, latest_night_score = None, None, -1
    longest_day, longest_hours = None, 0.0

    for day_key in sorted(days.keys()):
        d = days[day_key]
        all_ts = d["timestamps"]
        if not all_ts:
            continue
        earliest, latest = min(all_ts), max(all_ts)
        active_hours = round((latest - earliest).total_seconds() / 3600, 1)
        latest_time = latest.strftime("%H:%M")
        result["days"].append({
            "date": day_key,
            "sessions": d["sessions"],
            "tokens": d["tokens"],
            "activeHours": active_hours,
            "latestTime": latest_time,
        })
        if d["sessions"] > most_active_sessions:
            most_active_sessions = d["sessions"]
            most_active_day = day_key
        hour = latest.hour
        late_score = hour if hour >= 18 else (hour + 24 if hour < 6 else 0)
        if late_score > latest_night_score:
            latest_night_score = late_score
            latest_night_date = day_key
            latest_night_time = latest_time
        if active_hours > longest_hours:
            longest_hours = active_hours
            longest_day = day_key

    # Cost calculation (Opus pricing per M tokens)
    cost_usd = (
        total_usage["input"] * 15.00 / 1e6
        + total_usage["cacheRead"] * 0.30 / 1e6
        + total_usage["cacheWrite"] * 3.75 / 1e6
        + total_usage["output"] * 75.00 / 1e6
    )

    result["summary"] = {
        "totalDays": len(result["days"]),
        "totalSessions": len(all_sessions),
        "totalTokens": total_tokens,
        "usage": {
            "input": total_usage["input"],
            "cacheRead": total_usage["cacheRead"],
            "cacheWrite": total_usage["cacheWrite"],
            "output": total_usage["output"],
        },
        "costUsd": round(cost_usd, 2),
        "mostActiveDay": {"date": most_active_day, "sessions": most_active_sessions} if most_active_day else None,
        "latestNight": {"date": latest_night_date, "time": latest_night_time} if latest_night_date else None,
        "longestDay": {"date": longest_day, "hours": longest_hours} if longest_day else None,
    }
    return result


# ---------------------------------------------------------------------------
# Workspace & Config Scanning
# ---------------------------------------------------------------------------

def scan_workspace(tier: str) -> dict:
    """Read workspace .md files based on tier."""
    params = TIER_PARAMS[tier]
    result = {}

    if not WORKSPACE_DIR.is_dir():
        return result

    # Priority files first
    files_to_read = WORKSPACE_PRIORITY_FILES[:params["workspace_files"]]
    for name in files_to_read:
        fpath = WORKSPACE_DIR / name
        if fpath.is_file():
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                if len(content) > 50000:
                    content = content[:50000] + "\n... [truncated]"
                result[name] = content
            except OSError:
                pass

    # For standard/deep, also read any other .md files in workspace root
    if params["workspace_files"] > len(WORKSPACE_PRIORITY_FILES):
        for fpath in sorted(WORKSPACE_DIR.glob("*.md")):
            if fpath.name not in result:
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    if len(content) > 50000:
                        content = content[:50000] + "\n... [truncated]"
                    result[fpath.name] = content
                except OSError:
                    pass

    return result


def scan_memory_logs(tier: str) -> List[dict]:
    """Read daily memory logs based on tier."""
    params = TIER_PARAMS[tier]
    if params["memory_logs_days"] == 0:
        return []

    if not MEMORY_LOGS_DIR.is_dir():
        return []

    log_files = sorted(MEMORY_LOGS_DIR.glob("*.md"), reverse=True)

    if params["memory_logs_days"] < 999:
        cutoff = (datetime.now() - timedelta(days=params["memory_logs_days"])).strftime("%Y-%m-%d")
        log_files = [f for f in log_files if f.stem >= cutoff]

    logs = []
    for fpath in log_files:
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
            if len(content) > 30000:
                content = content[:30000] + "\n... [truncated]"
            logs.append({"date": fpath.stem, "content": content})
        except OSError:
            pass

    return sorted(logs, key=lambda x: x["date"])


def scan_config() -> dict:
    """Parse openclaw.json, extract non-sensitive info."""
    if not CONFIG_PATH.is_file():
        return {}

    try:
        raw = load_json(CONFIG_PATH)
    except (OSError, json.JSONDecodeError):
        return {}

    result = {}

    # Model
    model = raw.get("model", {})
    if isinstance(model, dict):
        result["model"] = model.get("name", "") or model.get("model", "")
    elif isinstance(model, str):
        result["model"] = model

    # Tools (names only, no secrets — skip non-dict entries to avoid leaking config strings)
    tools = raw.get("tools", [])
    if isinstance(tools, list):
        result["tools"] = [
            t.get("name", "unknown") for t in tools
            if isinstance(t, dict) and t.get("name")
        ]

    # Plugins (names only)
    plugins = raw.get("plugins", [])
    if isinstance(plugins, list):
        result["plugins"] = [
            p.get("name", "unknown") for p in plugins
            if isinstance(p, dict) and p.get("name")
        ]

    # Channels (names only)
    channels = raw.get("channels", [])
    if isinstance(channels, list):
        result["channels"] = [
            c.get("name", "unknown") for c in channels
            if isinstance(c, dict) and c.get("name")
        ]

    # Compaction mode
    compaction = raw.get("compaction", {})
    if isinstance(compaction, dict) and compaction.get("mode"):
        result["compaction"] = compaction["mode"]

    return result


def scan_cron(tier: str) -> dict:
    """Read cron jobs and run history based on tier."""
    params = TIER_PARAMS[tier]
    result = {"jobs": [], "runs": []}

    jobs_path = CRON_DIR / "jobs.json"
    if jobs_path.is_file():
        try:
            jobs_data = load_json(jobs_path)
            if isinstance(jobs_data, list):
                raw_jobs = [j for j in jobs_data if isinstance(j, dict)]
            elif isinstance(jobs_data, dict):
                raw_jobs = [j for j in jobs_data.get("jobs", []) if isinstance(j, dict)]
            else:
                raw_jobs = []
            for j in raw_jobs:
                job = {
                    "name": j.get("name", "unnamed"),
                    "schedule": j.get("schedule", ""),
                }
                # Preserve prompt/command for AI description generation
                if j.get("prompt"):
                    job["prompt"] = j["prompt"][:500]
                if j.get("command"):
                    job["command"] = j["command"][:500]
                if j.get("description"):
                    job["description"] = j["description"]
                result["jobs"].append(job)
        except (OSError, json.JSONDecodeError):
            pass

    # Count runs per job
    run_counts = Counter()
    if params["cron_runs_days"] > 0:
        runs_dir = CRON_DIR / "runs"
        if runs_dir.is_dir():
            try:
                run_files = sorted(runs_dir.iterdir(), reverse=True)
                if params["cron_runs_days"] < 999:
                    cutoff = (datetime.now() - timedelta(days=params["cron_runs_days"])).strftime("%Y-%m-%d")
                    run_files = [f for f in run_files if f.stem >= cutoff]
                for fpath in run_files[:500]:
                    try:
                        data = load_json(fpath)
                        job_name = data.get("job") or data.get("name") or data.get("job_name") or "unknown"
                        run_counts[job_name] += 1
                        if len(result["runs"]) < 50:
                            result["runs"].append(data)
                    except (OSError, json.JSONDecodeError):
                        pass
            except OSError:
                pass

    # Attach run counts to jobs
    for job in result["jobs"]:
        count = run_counts.get(job["name"], 0)
        if count > 0:
            job["runs"] = count
    result["total_runs"] = sum(run_counts.values())

    return result


def scan_extensions() -> List[dict]:
    """Scan extensions directory for plugin info."""
    if not EXTENSIONS_DIR.is_dir():
        return []

    extensions = []
    try:
        for entry in sorted(EXTENSIONS_DIR.iterdir()):
            if not entry.is_dir():
                continue
            ext = {"name": entry.name, "description": ""}
            for meta_name in ("plugin.json", "package.json"):
                meta_path = entry / meta_name
                if meta_path.is_file():
                    try:
                        meta = load_json(meta_path)
                        ext["description"] = meta.get("description", "")
                        break
                    except (OSError, json.JSONDecodeError):
                        pass
            extensions.append(ext)
    except OSError:
        pass

    return extensions


def query_memory_db(limit: int) -> List[dict]:
    """Query SQLite memory DB for recent memory chunks (deep tier only)."""
    if limit <= 0 or not MEMORY_DB_PATH.is_file():
        return []

    limit = max(0, min(int(limit), 1000))
    try:
        query = f"SELECT content, source, created_at FROM chunks ORDER BY created_at DESC LIMIT {limit}"
        result = subprocess.check_output(
            ["sqlite3", "-json", str(MEMORY_DB_PATH), query],
            stderr=subprocess.DEVNULL,
            timeout=10,
            text=True,
        )
        if result.strip():
            return json.loads(result)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass

    return []


# ---------------------------------------------------------------------------
# Tool & Skill Extraction
# ---------------------------------------------------------------------------

def extract_tools(sampled_sessions: List[Path]) -> dict:
    """Extract tool usage counts and installed skills."""
    tool_counts: Counter = Counter()

    for path in sampled_sessions:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    content = obj.get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict):
                                if block.get("type") in ("tool_use", "function_call"):
                                    tool_counts[block.get("name", "unknown")] += 1
                    for tc in obj.get("tool_calls", []):
                        if isinstance(tc, dict):
                            name = tc.get("function", {}).get("name") or tc.get("name", "unknown")
                            tool_counts[name] += 1
        except OSError:
            continue

    skills_found = []
    for sd in SKILL_DIRS:
        if sd.is_dir():
            try:
                for entry in sd.iterdir():
                    if entry.is_dir():
                        skill_md = entry / "SKILL.md"
                        desc = ""
                        if skill_md.is_file():
                            try:
                                for sline in skill_md.read_text(errors="replace").splitlines():
                                    if sline.startswith("description:"):
                                        desc = sline.split(":", 1)[1].strip()
                                        break
                            except OSError:
                                pass
                        skills_found.append({"name": entry.name, "description": desc})
            except OSError:
                continue

    return {
        "toolCounts": dict(tool_counts.most_common(20)),
        "installedSkills": skills_found,
    }


# ---------------------------------------------------------------------------
# Routine Detection
# ---------------------------------------------------------------------------

def detect_routines() -> List[dict]:
    """Detect crontab, launchd, and OpenClaw scheduled tasks."""
    routines = []

    # crontab — only openclaw/claw keywords
    try:
        cron = subprocess.check_output(["crontab", "-l"], stderr=subprocess.DEVNULL, text=True)
        for line in cron.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                if any(kw in line.lower() for kw in ("openclaw", "claw")):
                    routines.append({"raw": line, "source": "crontab"})
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # launchd agents (macOS) — only openclaw/claw keywords
    launch_dir = Path.home() / "Library" / "LaunchAgents"
    if launch_dir.is_dir():
        for name in os.listdir(launch_dir):
            if any(kw in name.lower() for kw in ("openclaw", "claw")):
                routines.append({"raw": name, "source": "launchd"})

    # OpenClaw cron jobs
    jobs_path = CRON_DIR / "jobs.json"
    if jobs_path.is_file():
        try:
            jobs_data = load_json(jobs_path)
            jobs = jobs_data if isinstance(jobs_data, list) else jobs_data.get("jobs", [])
            for task in jobs:
                if isinstance(task, dict):
                    routines.append({
                        "name": task.get("name", "unnamed"),
                        "schedule": task.get("schedule", "unknown"),
                        "description": task.get("description", ""),
                        "source": "openclaw_cron",
                    })
        except (OSError, json.JSONDecodeError):
            pass

    return routines


# ---------------------------------------------------------------------------
# Session Compression
# ---------------------------------------------------------------------------

def compress_sessions(sampled: List[Path], tier: str) -> None:
    """Compress sampled sessions based on tier parameters."""
    params = TIER_PARAMS[tier]
    max_msg_len = params["max_msg_len"]
    tool_result_len = params["tool_result_len"]
    COMPRESSED_DIR.mkdir(parents=True, exist_ok=True)

    for i, path in enumerate(sampled):
        messages: List[dict] = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    role = obj.get("role")
                    if not role:
                        msg = obj.get("message")
                        if isinstance(msg, dict):
                            role = msg.get("role")
                    if role not in ("user", "human", "assistant", "model", "ai"):
                        continue

                    content = obj.get("content")
                    if not content:
                        msg = obj.get("message")
                        if isinstance(msg, dict):
                            content = msg.get("content")

                    text = ""
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        parts = []
                        for block in content:
                            if isinstance(block, dict):
                                if block.get("type") == "text":
                                    parts.append(block.get("text", ""))
                                elif block.get("type") == "tool_use":
                                    tool_name = block.get("name", "?")
                                    if tier == "deep":
                                        inp = block.get("input", {})
                                        inp_summary = json.dumps(inp, ensure_ascii=False)[:300] if inp else ""
                                        parts.append(f"[tool: {tool_name} | input: {inp_summary}]")
                                    else:
                                        parts.append(f"[tool: {tool_name}]")
                                elif block.get("type") == "tool_result":
                                    if tool_result_len > 0:
                                        result_text = str(block.get("content", ""))[:tool_result_len]
                                        parts.append(f"[tool_result: {result_text}...]")
                        text = "\n".join(parts)

                    if not text or len(text.strip()) < 5:
                        continue

                    if len(text) > max_msg_len:
                        text = text[:max_msg_len] + "... [truncated]"

                    norm_role = "user" if role in ("human", "user") else "assistant"

                    if messages and messages[-1]["role"] == norm_role:
                        messages[-1]["text"] += "\n" + text
                    else:
                        messages.append({"role": norm_role, "text": text})

                    ts = obj.get("timestamp") or obj.get("ts")
                    if ts and messages:
                        messages[-1]["ts"] = str(ts) if not isinstance(ts, str) else ts

        except OSError:
            continue

        out_path = COMPRESSED_DIR / f"session_{i:03d}.json"
        save_json(out_path, {"source": path.name, "messages": messages})
        log(f"  Session {i + 1}/{len(sampled)}: {len(messages)} messages from {path.name}")

    log(f"Compressed {len(sampled)} sessions to {COMPRESSED_DIR}/")


# ---------------------------------------------------------------------------
# prepare subcommand
# ---------------------------------------------------------------------------

def cmd_prepare(args: argparse.Namespace) -> None:
    """Run all deterministic preprocessing steps."""
    PARTS_DIR.mkdir(parents=True, exist_ok=True)

    # Privacy statement
    log("")
    log("  ClawReport 隐私说明")
    log("")
    log("  * 读取本地 OpenClaw 数据（对话记录、工作空间、记忆日志）")
    log("  * AI 在本地分析，生成结构化报告")
    log("  * 上传前你会看到完整预览")
    log("  * 上传后可随时设为私密或删除")
    log("")
    try:
        confirm = input("  继续？ [Y/n] ").strip().lower()
        if confirm == 'n':
            log("已取消")
            sys.exit(0)
    except EOFError:
        pass

    # Version check
    try:
        skill_dir = Path(__file__).parent
        skill_md = skill_dir / "SKILL.md"
        local_version = None
        if skill_md.is_file():
            first_lines = skill_md.read_text().split('\n')
            for line in first_lines[:10]:
                m = re.match(r'<!--\s*version:\s*([\d.]+)\s*-->', line)
                if m:
                    local_version = m.group(1)
                    break

        if local_version:
            req = urllib.request.Request(f"{API_URL}/skill-version", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                remote = json.loads(resp.read())
            remote_version = remote.get("version", "")
            if remote_version and remote_version != local_version:
                try:
                    from packaging.version import Version
                    if Version(remote_version) > Version(local_version):
                        log(f"  ClawReport skill 有新版本 ({local_version} -> {remote_version})")
                        try:
                            update = input("  是否更新？ [Y/n] ").strip().lower()
                            if update != 'n':
                                log("  请运行: curl -sSL https://clawdiary.ai/install | bash")
                        except EOFError:
                            pass
                except Exception:
                    rv = tuple(int(x) for x in remote_version.split(".") if x.isdigit())
                    lv = tuple(int(x) for x in local_version.split(".") if x.isdigit())
                    if rv > lv:
                        log(f"  ClawReport skill 有新版本 ({local_version} -> {remote_version})")
    except Exception:
        pass

    # 1. Auth
    log("[1/8] Checking credentials...")
    creds = ensure_auth()

    # 2. Data discovery
    log("[2/8] Discovering data...")
    inventory = discover_data()

    if not inventory["exists"]:
        die("OpenClaw home (~/.openclaw/) not found. Is OpenClaw installed?")

    if inventory["sessions"]["count"] == 0:
        die("No session files found in ~/.openclaw/agents/main/sessions/. Nothing to analyze.")

    # 3. Tier selection
    tier = select_tier(inventory)
    params = TIER_PARAMS[tier]
    log(f"\n[3/8] 选择档位: {tier}")

    # 4. Discover & sample sessions (no date filter — use ALL history)
    log("[4/8] Scanning sessions...")
    all_sessions = discover_sessions()
    log(f"  Found {len(all_sessions)} session files")

    if not all_sessions:
        die("No session files found.")

    sampled = sample_sessions(all_sessions, tier)
    log(f"  Sampled {len(sampled)} sessions")

    # 5. Activity extraction
    log("[5/8] Extracting activity data...")
    activity = extract_activity(all_sessions)
    save_json(PARTS_DIR / "activity.json", activity)
    summary = activity["summary"]
    def fmt_tokens(n: int) -> str:
        if n >= 1e9:
            return f"{n / 1e9:.1f}B"
        if n >= 1e6:
            return f"{n / 1e6:.1f}M"
        if n >= 1e3:
            return f"{n / 1e3:.1f}K"
        return str(n)

    log(f"  {summary['totalDays']} days, {summary['totalSessions']} sessions, {fmt_tokens(summary['totalTokens'])} tokens")
    usage = summary.get("usage", {})
    if usage.get("output", 0) > 0:
        log(f"  Token breakdown: input={fmt_tokens(usage['input'])}, cache_read={fmt_tokens(usage['cacheRead'])}, cache_write={fmt_tokens(usage['cacheWrite'])}, output={fmt_tokens(usage['output'])}")
        log(f"  Estimated cost: ${summary.get('costUsd', 0):.2f}")

    # 6. Workspace + config + memory + cron + extensions
    log("[6/8] Scanning workspace & config...")

    workspace = scan_workspace(tier)
    save_json(PARTS_DIR / "workspace.json", workspace, indent=2)
    log(f"  Workspace: {len(workspace)} files ({', '.join(workspace.keys())})")

    memory_logs = scan_memory_logs(tier)
    save_json(PARTS_DIR / "memory_logs.json", memory_logs, indent=2)
    if memory_logs:
        log(f"  Memory logs: {len(memory_logs)} days ({memory_logs[0]['date']} ~ {memory_logs[-1]['date']})")
    else:
        log("  Memory logs: none")

    config = scan_config()
    save_json(PARTS_DIR / "config.json", config, indent=2)
    if config:
        log(f"  Config: model={config.get('model', '?')}, {len(config.get('tools', []))} tools, {len(config.get('plugins', []))} plugins")

    cron_data = scan_cron(tier)
    save_json(PARTS_DIR / "cron.json", cron_data, indent=2)
    if cron_data["jobs"]:
        log(f"  Cron: {len(cron_data['jobs'])} jobs, {len(cron_data['runs'])} runs")

    if params["scan_extensions"]:
        extensions = scan_extensions()
        save_json(PARTS_DIR / "extensions.json", extensions, indent=2)
        if extensions:
            log(f"  Extensions: {len(extensions)} ({', '.join(e['name'] for e in extensions)})")

    # 7. Tool/skill extraction + routine detection
    log("[7/8] Extracting tools & routines...")
    tools = extract_tools(sampled)
    save_json(PARTS_DIR / "tools.json", tools)
    log(f"  {len(tools['toolCounts'])} unique tools, {len(tools['installedSkills'])} installed skills")

    routines = detect_routines()
    save_json(PARTS_DIR / "routines.json", routines)
    log(f"  {len(routines)} routines found")

    # 8. Session compression + memory DB
    log("[8/8] Compressing sessions...")
    compress_sessions(sampled, tier)

    if params["memory_db_limit"] > 0:
        log("  Querying memory database...")
        memories = query_memory_db(params["memory_db_limit"])
        save_json(PARTS_DIR / "memory_search.json", memories, indent=2)
        log(f"  Memory DB: {len(memories)} entries")

    # Prepare summary
    resources = estimate_resources(tier, inventory)
    prepare_summary = {
        "status": "ok",
        "tier": tier,
        "credentials": {
            "slug": creds.get("slug"),
            "claim_url": creds.get("claim_url"),
            "status": "authenticated",
        },
        "inventory": {
            "sessions_total": inventory["sessions"]["count"],
            "sessions_recent_30d": inventory["sessions"]["recent_30d"],
            "workspace_files": inventory["workspace"]["files"],
            "memory_log_days": inventory["workspace"]["memory_log_days"],
            "has_memory_db": inventory["memory_db"]["exists"],
            "cron_jobs": inventory["cron"]["jobs_count"],
            "extensions": len(inventory["extensions"]),
        },
        "sessions": {
            "total": len(all_sessions),
            "sampled": len(sampled),
        },
        "activity_summary": summary,
        "tools_count": len(tools["toolCounts"]),
        "skills_count": len(tools["installedSkills"]),
        "routines_count": len(routines),
        "resources": resources,
    }
    save_json(PARTS_DIR / "prepare_summary.json", prepare_summary, indent=2)

    # Incremental: auto-download existing report using credentials
    log("[+] Checking for existing report (incremental mode)...")
    try:
        creds = load_json(CRED_FILE)
        req = urllib.request.Request(
            f"{creds['api_url']}/api/report/mine/current",
            headers={"Authorization": f"Bearer {creds['api_key']}"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            existing = json.loads(resp.read())
        # Extract the reportJson from the response
        report_json = existing.get("reportJson", existing)
        save_json(PARTS_DIR / "existing-report.json", report_json, indent=2)
        log("  Existing report downloaded → _cr_parts/existing-report.json (incremental mode ON)")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            log("  No existing report found (first-time generation)")
        else:
            log(f"  Could not fetch existing report: HTTP {e.code}")
    except Exception as e:
        log(f"  Could not fetch existing report: {e}")

    log("")
    log(f"Prepare complete ({tier} tier).")
    log(f"  Workspace data:      {PARTS_DIR / 'workspace.json'}")
    if memory_logs:
        log(f"  Memory logs:         {PARTS_DIR / 'memory_logs.json'}")
    log(f"  Config:              {PARTS_DIR / 'config.json'}")
    log(f"  Compressed sessions: {COMPRESSED_DIR}/session_*.json")
    log(f"  Activity data:       {PARTS_DIR / 'activity.json'}")


# ---------------------------------------------------------------------------
# finalize subcommand
# ---------------------------------------------------------------------------

REQUIRED_KEYS_V3 = ["hero", "clawProfile", "showcase", "stories", "catchphrases", "skills", "letter"]
REQUIRED_KEYS_V2 = ["hero", "clawProfile", "showcase", "certification", "portrait", "catchphrases", "diary", "achievements", "letter"]
REQUIRED_KEYS_V1 = ["heroStats", "effortMap", "showcase", "ownerPortrait", "catchphrases", "diary", "achievements", "letterToOwner"]
TIER_ORDER = {"legendary": 0, "epic": 1, "rare": 2, "common": 3}
VALID_DEPTHS = {"surface", "working", "deep", "symbiotic"}
VALID_LEVELS = {"L1", "L2", "L3", "L4", "L5"}


def auto_fix_report(report: dict) -> List[str]:
    """Fix common AI generation errors before validation. Returns list of fixes applied."""
    fixes: List[str] = []

    # diary: description → entry
    for i, d in enumerate(report.get("diary") or []):
        if isinstance(d, dict) and "description" in d and "entry" not in d:
            d["entry"] = d.pop("description")
            fixes.append(f"diary[{i}]: renamed 'description' → 'entry'")

    # showcase: headline → title (if title missing)
    for i, s in enumerate(report.get("showcase") or []):
        if isinstance(s, dict):
            if "headline" in s and "title" not in s:
                s["title"] = s.pop("headline")
                fixes.append(f"showcase[{i}]: renamed 'headline' → 'title'")
            if "description" in s and "what" not in s:
                s["what"] = s.pop("description")
                fixes.append(f"showcase[{i}]: renamed 'description' → 'what'")

    # portrait.observations: theme → label, details → observation
    for i, obs in enumerate((report.get("portrait") or {}).get("observations") or []):
        if isinstance(obs, dict):
            if "theme" in obs and "label" not in obs:
                obs["label"] = obs.pop("theme")
                fixes.append(f"portrait.observations[{i}]: renamed 'theme' → 'label'")
            if "details" in obs and "observation" not in obs:
                obs["observation"] = obs.pop("details")
                fixes.append(f"portrait.observations[{i}]: renamed 'details' → 'observation'")

    # catchphrases: soWhat → clawInterpretation
    for i, c in enumerate(report.get("catchphrases") or []):
        if isinstance(c, dict) and "soWhat" in c and "clawInterpretation" not in c:
            c["clawInterpretation"] = c.pop("soWhat")
            fixes.append(f"catchphrases[{i}]: renamed 'soWhat' → 'clawInterpretation'")

    # catchphrases.frequency: string → number (with type guard)
    for i, c in enumerate(report.get("catchphrases") or []):
        if isinstance(c, dict):
            freq = c.get("frequency")
            if isinstance(freq, str):
                freq_map = {"high": 10, "medium": 5, "low": 2, "very high": 15}
                c["frequency"] = freq_map.get(freq.lower(), 5)
                fixes.append(f"catchphrases[{i}]: converted frequency '{freq}' → {c['frequency']}")
            elif freq is None:
                c["frequency"] = 5
                fixes.append(f"catchphrases[{i}]: missing frequency → 5")

    # collaborationStyle: string → object
    portrait = report.get("portrait", {})
    if isinstance(portrait, dict):
        cs = portrait.get("collaborationStyle")
        if isinstance(cs, str):
            portrait["collaborationStyle"] = {"label": cs, "description": cs}
            fixes.append("portrait.collaborationStyle: converted string → object")

    # v1 field names → v2 (if AI mixed them up)
    renames = {"heroStats": "hero", "ownerPortrait": "portrait", "letterToOwner": "letter"}
    for old, new in renames.items():
        if old in report and new not in report:
            report[new] = report.pop(old)
            fixes.append(f"renamed top-level '{old}' → '{new}'")
            # letterToOwner v1 can be string, v2 letter requires object
            if new == "letter" and isinstance(report[new], str):
                report[new] = {"text": report[new]}
                fixes.append("letter: converted string → object")

    # v2→v3 migration: move clawProfile.tools → skills.tools, clawProfile.automations → skills.cron
    cp = report.get("clawProfile", {})
    if isinstance(cp, dict) and "skills" not in report:
        tools_data = cp.pop("tools", None)
        auto_data = cp.pop("automations", None)
        if tools_data or auto_data:
            skills_block = {}
            if tools_data:
                skills_block["tools"] = tools_data
            if auto_data:
                skills_block["cron"] = auto_data
            report["skills"] = skills_block
            fixes.append("v2→v3: moved clawProfile.tools/automations → skills block")

    # v2→v3 migration: move certification D/B/O → clawProfile.dimensions
    cert = report.get("certification", {})
    if isinstance(cert, dict) and isinstance(cp, dict):
        if cert.get("dimensionDepth") and not cp.get("dimensions"):
            signal_ev = cert.get("signalEvidence", {})
            cp["dimensions"] = {
                "depth": {"code": cert.get("dimensionDepth", ""), "label": "深度", "evidence": signal_ev.get("depth", "")},
                "breadth": {"code": cert.get("dimensionBreadth", ""), "label": "广度", "evidence": signal_ev.get("breadth", "")},
                "orchestration": {"code": cert.get("dimensionOrchestration", ""), "label": "驾驭", "evidence": signal_ev.get("orchestration", "")},
            }
            fixes.append("v2→v3: moved certification D/B/O → clawProfile.dimensions")

    # v2→v3 showcase migration: title+what → metric+fact
    for i, s in enumerate(report.get("showcase") or []):
        if isinstance(s, dict) and "what" in s and "metric" not in s and "fact" not in s:
            s["metric"] = s.pop("title", "")
            s["fact"] = s.pop("what", "")
            s.pop("soWhat", None)
            s.pop("evidence", None)
            s.pop("impactLevel", None)
            fixes.append(f"showcase[{i}]: v2→v3 converted title/what → metric/fact")

    return fixes


def format_server_errors(error_body: str) -> str:
    """Parse and group server validation errors for human readability."""
    try:
        data = json.loads(error_body)
    except (json.JSONDecodeError, TypeError):
        return error_body

    if "details" not in data:
        return data.get("error", error_body)

    groups: Dict[str, List[str]] = {}
    for detail in data["details"]:
        path = detail.get("path", "")
        field = ".".join(path.split(".")[:2]) if "." in path else (path or "(root)")
        msg = detail.get("message", "")
        key = f"{field}: {msg}"
        groups.setdefault(key, []).append(path or "(root)")

    lines = [f"  验证失败 ({len(data['details'])} 个问题):"]
    for desc, paths in groups.items():
        if len(paths) > 3:
            lines.append(f"    {desc} ({len(paths)} 处)")
        else:
            for p in paths:
                lines.append(f"    {p}: {desc.split(': ', 1)[-1]}")

    if data.get("hint"):
        lines.append(f"\n  提示: {data['hint']}")
    if data.get("summary"):
        lines.append(f"  摘要: {data['summary']}")

    return "\n".join(lines)


def is_v3_report(report: dict) -> bool:
    """Detect v3 report by presence of skills block or v3 showcase format."""
    if "skills" in report:
        return True
    showcase = report.get("showcase", [])
    if showcase and isinstance(showcase[0], dict) and "metric" in showcase[0]:
        return True
    return False


def is_v2_report(report: dict) -> bool:
    """Detect v2 report by presence of v2-only keys."""
    return "hero" in report or "clawProfile" in report


def validate_report(report: dict) -> Tuple[List[str], List[str]]:
    """Validate report structure. Returns (errors, warnings)."""
    if is_v3_report(report):
        return validate_v3(report)
    if is_v2_report(report):
        return validate_v2(report)
    return validate_v1(report)


def validate_v3(report: dict) -> Tuple[List[str], List[str]]:
    """Validate v3 report structure. Returns (errors, warnings)."""
    errors: List[str] = []
    warnings: List[str] = []

    missing = [k for k in REQUIRED_KEYS_V3 if k not in report]
    if missing:
        errors.append(f"Missing required keys: {missing}")

    # hero
    hero = report.get("hero", {})
    if not hero.get("ownerName"):
        warnings.append("hero.ownerName is empty")
    if not hero.get("tagline"):
        errors.append("hero.tagline is required")
    headline = hero.get("headline", "")
    if len(headline) > 20:
        errors.append(f"hero.headline is {len(headline)} chars, must be <= 20")
    if "×" in headline or "✕" in headline or " x " in headline.lower():
        errors.append(f"hero.headline must not use × joins: {headline!r}")
    hero_stats = hero.get("stats", [])
    if len(hero_stats) != 4:
        errors.append(f"hero.stats must have exactly 4 items, got {len(hero_stats)}")
    VALID_STAT_LABELS = {"消息", "天", "TOKENS", "tokens", "龙虾"}
    for i, st in enumerate(hero_stats):
        if not isinstance(st, dict):
            continue
        val = st.get("value", "")
        if len(val) > 6:
            errors.append(f"hero.stats[{i}].value too long ({len(val)} chars): {val!r}. Must be <=6 chars (e.g. '3,847', '21.4M')")
        lbl = st.get("label", "")
        if lbl not in VALID_STAT_LABELS:
            warnings.append(f"hero.stats[{i}].label={lbl!r} is not standard (expected: 消息/天/TOKENS/龙虾)")

    # clawProfile
    cp = report.get("clawProfile", {})
    level = cp.get("level", "")
    if level not in VALID_LEVELS:
        errors.append(f"clawProfile.level must be L1-L5, got: {level!r}")
    for field in ("function", "domain", "persona"):
        val = cp.get(field, "")
        if not isinstance(val, str) or not val.strip():
            errors.append(f"clawProfile.{field} must be non-empty string, got: {val!r}")
    one_liner = cp.get("oneLiner", "")
    if not isinstance(one_liner, str) or not one_liner.strip():
        errors.append("clawProfile.oneLiner must be non-empty string")

    # clawProfile.stats (exactly 4: 消息/天/TOKENS/SKILLS)
    cp_stats = cp.get("stats", [])
    if not isinstance(cp_stats, list) or len(cp_stats) != 4:
        errors.append(f"clawProfile.stats must have exactly 4 items, got {len(cp_stats) if isinstance(cp_stats, list) else 'non-list'}")
    else:
        expected_labels = {"消息", "天", "TOKENS", "SKILLS"}
        actual_labels = {s.get("label", "") for s in cp_stats if isinstance(s, dict)}
        if actual_labels != expected_labels:
            errors.append(f"clawProfile.stats labels must be 消息/天/TOKENS/SKILLS, got: {actual_labels}")

    # clawProfile.dimensions (D/B/O)
    dims = cp.get("dimensions", {})
    if not dims:
        warnings.append("clawProfile.dimensions is empty (expected D/B/O)")
    else:
        valid_dim_codes = {"D1", "D2", "D3", "D4", "D5", "B1", "B2", "B3", "B4", "B5", "O1", "O2", "O3", "O4", "O5"}
        for dim_key in ("depth", "breadth", "orchestration"):
            dim = dims.get(dim_key, {})
            if isinstance(dim, dict):
                code = dim.get("code", "")
                if code and code not in valid_dim_codes:
                    errors.append(f"clawProfile.dimensions.{dim_key}.code invalid: {code!r}")
            else:
                warnings.append(f"clawProfile.dimensions.{dim_key} is not an object")

    # showcase (v3 format: metric + domain + fact)
    showcase = report.get("showcase", [])
    if len(showcase) < 3:
        errors.append(f"showcase has {len(showcase)} items, need at least 3")
    elif len(showcase) > 6:
        warnings.append(f"showcase has {len(showcase)} items, recommend at most 6")
    for i, item in enumerate(showcase):
        if not isinstance(item, dict):
            errors.append(f"showcase[{i}] must be object")
            continue
        if not item.get("metric"):
            errors.append(f"showcase[{i}] missing metric")
        if not item.get("fact"):
            errors.append(f"showcase[{i}] missing fact")

    # stories (1-3)
    stories = report.get("stories", [])
    if len(stories) < 1:
        errors.append("stories must have at least 1 item")
    elif len(stories) > 3:
        warnings.append(f"stories has {len(stories)} items, recommend at most 3")
    for i, story in enumerate(stories):
        if not story.get("setup"):
            errors.append(f"stories[{i}] missing setup")
        if not story.get("turningPoint"):
            errors.append(f"stories[{i}] missing turningPoint")
        if not story.get("resolution"):
            errors.append(f"stories[{i}] missing resolution")
        owner_quote = story.get("ownerQuote", "")
        if owner_quote and len(owner_quote) > 80:
            warnings.append(f"stories[{i}].ownerQuote is {len(owner_quote)} chars, target <= 80")

    # catchphrases
    catchphrases = report.get("catchphrases", [])
    if len(catchphrases) < 3:
        errors.append(f"catchphrases has {len(catchphrases)} items, need at least 3")
    elif len(catchphrases) > 8:
        warnings.append(f"catchphrases has {len(catchphrases)} items, recommend at most 8")
    for i, cp_item in enumerate(catchphrases):
        if not isinstance(cp_item, dict):
            errors.append(f"catchphrases[{i}] must be object")
            continue
        phrase = cp_item.get("phrase", "")
        if len(phrase) <= 1:
            errors.append(f"catchphrases[{i}] is single char: {phrase!r}")

    # skills block
    skills = report.get("skills", {})
    tools_list = skills.get("tools", [])
    if not tools_list:
        warnings.append("skills.tools is empty")
    cron_list = skills.get("cron", [])

    # letter
    letter = report.get("letter", {})
    letter_text = letter.get("text", "")
    if not letter_text:
        errors.append("letter.text is required")
    if not letter.get("signoff"):
        warnings.append("letter.signoff is empty")

    # NO checks for portrait, diary, achievements, certification (v3 removed blocks)

    return errors, warnings


def validate_v2(report: dict) -> Tuple[List[str], List[str]]:
    """Validate v2 report structure. Returns (errors, warnings)."""
    errors: List[str] = []
    warnings: List[str] = []

    missing = [k for k in REQUIRED_KEYS_V2 if k not in report]
    if missing:
        errors.append(f"Missing required keys: {missing}")

    cp = report.get("clawProfile", {})
    level = cp.get("level", "")
    if level not in VALID_LEVELS:
        errors.append(f"clawProfile.level must be L1-L5, got: {level!r}")
    for field in ("function", "domain", "persona"):
        val = cp.get(field, "")
        if not isinstance(val, str) or not val.strip():
            errors.append(f"clawProfile.{field} must be non-empty string, got: {val!r}")
    one_liner = cp.get("oneLiner", "")
    if not isinstance(one_liner, str) or not one_liner.strip():
        errors.append("clawProfile.oneLiner must be non-empty string")

    # hero field checks
    hero = report.get("hero", {})
    if not hero.get("ownerName"):
        warnings.append("hero.ownerName is empty")
    if not hero.get("tagline"):
        errors.append("hero.tagline is required")
    hero_stats = hero.get("stats", [])
    if len(hero_stats) < 3:
        errors.append(f"hero.stats has {len(hero_stats)} items, need at least 3")

    # showcase count + field checks
    showcase = report.get("showcase", [])
    if len(showcase) < 3:
        errors.append(f"showcase has {len(showcase)} items, need at least 3")
    elif len(showcase) > 5:
        warnings.append(f"showcase has {len(showcase)} items, recommend at most 5")
    for i, item in enumerate(showcase):
        if not isinstance(item, dict):
            errors.append(f"showcase[{i}] must be object, got {type(item).__name__}")
            continue
        if not item.get("soWhat"):
            errors.append(f"showcase[{i}] missing soWhat")

    cert = report.get("certification", {})
    depth = cert.get("depth", "")
    if depth not in VALID_DEPTHS:
        errors.append(f"certification.depth must be surface/working/deep/symbiotic, got: {depth!r}")

    # Behavioral sub-dimensions (new v2 fields, warn if missing)
    valid_depth_dims = {"D1", "D2", "D3", "D4", "D5"}
    valid_breadth_dims = {"B1", "B2", "B3", "B4", "B5"}
    valid_orch_dims = {"O1", "O2", "O3", "O4", "O5"}
    dim_depth = cert.get("dimensionDepth", "")
    dim_breadth = cert.get("dimensionBreadth", "")
    dim_orch = cert.get("dimensionOrchestration", "")
    if dim_depth and dim_depth not in valid_depth_dims:
        errors.append(f"certification.dimensionDepth must be D1-D5, got: {dim_depth!r}")
    if dim_breadth and dim_breadth not in valid_breadth_dims:
        errors.append(f"certification.dimensionBreadth must be B1-B5, got: {dim_breadth!r}")
    if dim_orch and dim_orch not in valid_orch_dims:
        errors.append(f"certification.dimensionOrchestration must be O1-O5, got: {dim_orch!r}")
    if not dim_depth or not dim_breadth or not dim_orch:
        warnings.append("certification missing dimensionDepth/Breadth/Orchestration sub-dimensions")
    signal_ev = cert.get("signalEvidence", {})
    if dim_depth and not signal_ev.get("depth"):
        warnings.append("certification.signalEvidence.depth is empty")
    if dim_breadth and not signal_ev.get("breadth"):
        warnings.append("certification.signalEvidence.breadth is empty")
    if dim_orch and not signal_ev.get("orchestration"):
        warnings.append("certification.signalEvidence.orchestration is empty")
    if not cert.get("levelDescriptor"):
        warnings.append("certification.levelDescriptor is empty")

    diary = report.get("diary", [])
    if len(diary) < 5:
        errors.append(f"diary has {len(diary)} entries, need at least 5")
    bt_count = sum(1 for d in diary if d.get("type") in ("breakthrough", "milestone"))
    if bt_count < 3:
        errors.append(f"diary has {bt_count} breakthrough/milestone entries, need at least 3")
    diary_dates = set(d.get("date", "") for d in diary)
    if len(diary_dates) < 3:
        warnings.append(f"diary covers {len(diary_dates)} dates, recommend at least 3")
    comedy_count = sum(1 for d in diary if d.get("type") == "comedy")
    if comedy_count > 2:
        warnings.append(f"diary has {comedy_count} comedy entries, recommend at most 2")

    achievements = report.get("achievements", [])
    if len(achievements) < 5:
        errors.append(f"achievements has {len(achievements)} items, need at least 5")
    tiers = [TIER_ORDER.get(a.get("tier", "common"), 3) for a in achievements]
    if tiers != sorted(tiers):
        errors.append("achievements not sorted by tier (legendary first)")
    top3_tiers = [a.get("tier") for a in achievements[:3]]
    if any(t not in ("legendary", "epic") for t in top3_tiers):
        errors.append(f"first 3 achievements must be legendary/epic, got: {top3_tiers}")

    # stories validation (optional block)
    stories = report.get("stories", [])
    if len(stories) > 1:
        warnings.append(f"stories has {len(stories)} items, recommend at most 1")
    for i, story in enumerate(stories):
        if not story.get("setup"):
            errors.append(f"stories[{i}] missing setup")
        if not story.get("turningPoint"):
            errors.append(f"stories[{i}] missing turningPoint")
        if not story.get("resolution"):
            errors.append(f"stories[{i}] missing resolution")
        owner_quote = story.get("ownerQuote", "")
        if owner_quote and len(owner_quote) > 80:
            warnings.append(f"stories[{i}].ownerQuote is {len(owner_quote)} chars, target <= 80")
        valid_themes = {"breakthrough", "transformation", "persistence", "serendipity"}
        theme = story.get("theme", "")
        if theme and theme not in valid_themes:
            warnings.append(f"stories[{i}].theme '{theme}' not in {valid_themes}")

    portrait = report.get("portrait", {})
    observations = portrait.get("observations", [])
    if len(observations) < 2:
        errors.append(f"portrait.observations has {len(observations)} items, need at least 2")

    catchphrases = report.get("catchphrases", [])
    if len(catchphrases) < 3:
        errors.append(f"catchphrases has {len(catchphrases)} items, need at least 3")
    elif len(catchphrases) > 8:
        warnings.append(f"catchphrases has {len(catchphrases)} items, recommend at most 8")
    for i, cp_item in enumerate(catchphrases):
        if not isinstance(cp_item, dict):
            errors.append(f"catchphrases[{i}] must be object, got {type(cp_item).__name__}: {str(cp_item)[:50]}")
            continue
        phrase = cp_item.get("phrase", "")
        if len(phrase) <= 1:
            errors.append(f"catchphrases[{i}] is single char: {phrase!r}")

    # portrait.collaborationStyle checks
    collab = portrait.get("collaborationStyle", {})
    if isinstance(collab, str):
        errors.append(f"portrait.collaborationStyle must be object, got string: {collab[:50]!r}")
    elif isinstance(collab, dict):
        collab_level = collab.get("level", "")
        if collab_level and collab_level not in VALID_LEVELS:
            errors.append(f"portrait.collaborationStyle.level must be L1-L5, got: {collab_level!r}")
        collab_evidence = collab.get("evidence", [])
        if isinstance(collab_evidence, list) and len(collab_evidence) < 2:
            warnings.append(f"portrait.collaborationStyle.evidence has {len(collab_evidence)} quotes, recommend at least 2")

    # letter checks
    letter = report.get("letter", {})
    letter_text = letter.get("text", "")
    letter_words = len(letter_text.split())
    if letter_words > 200:
        warnings.append(f"letter.text is {letter_words} words, target <= 200")
    if not letter.get("signoff"):
        warnings.append("letter.signoff is empty")

    headline = hero.get("headline", "")
    if len(headline) > 20:
        errors.append(f"hero.headline is {len(headline)} chars, must be <= 20")

    cert_sessions = cert.get("sessions", 0)
    if level and cert_sessions:
        # Session counts are reference signals, not hard thresholds
        session_signals = {"L1": 0, "L2": 5, "L3": 15, "L4": 30, "L5": 50}
        min_signal = session_signals.get(level, 0)
        if isinstance(cert_sessions, (int, float)) and cert_sessions < min_signal:
            warnings.append(f"clawProfile.level={level} but certification.sessions={cert_sessions} (unusually low, expected ~{min_signal}+ as reference signal)")

    return errors, warnings


def validate_v1(report: dict) -> Tuple[List[str], List[str]]:
    """Validate v1 report structure. Returns (errors, warnings)."""
    errors: List[str] = []
    warnings: List[str] = []

    missing = [k for k in REQUIRED_KEYS_V1 if k not in report]
    if missing:
        errors.append(f"Missing required keys: {missing}")

    for i, item in enumerate(report.get("showcase", [])):
        if not item.get("soWhat"):
            errors.append(f"showcase[{i}] missing soWhat")

    diary = report.get("diary", [])
    if len(diary) < 5:
        errors.append(f"diary has {len(diary)} entries, need at least 5")
    bt_count = sum(1 for d in diary if d.get("type") in ("breakthrough", "milestone"))
    if bt_count < 3:
        errors.append(f"diary has {bt_count} breakthrough/milestone entries, need at least 3")
    diary_dates = set(d.get("date", "") for d in diary)
    if len(diary_dates) < 3:
        warnings.append(f"diary covers {len(diary_dates)} dates, recommend at least 3")

    achievements = report.get("achievements", [])
    if len(achievements) < 6:
        errors.append(f"achievements has {len(achievements)} items, need at least 6")
    tiers = [TIER_ORDER.get(a.get("tier", "common"), 3) for a in achievements]
    if tiers != sorted(tiers):
        errors.append("achievements not sorted by tier (legendary first)")
    top3_tiers = [a.get("tier") for a in achievements[:3]]
    if any(t not in ("legendary", "epic") for t in top3_tiers):
        errors.append(f"first 3 achievements must be legendary/epic, got: {top3_tiers}")

    dims = report.get("ownerPortrait", {}).get("dimensions", [])
    if len(dims) < 4:
        errors.append(f"dimensions has {len(dims)} items, need at least 4")
    cap_count = sum(1 for d in dims if d.get("type") == "capability")
    sty_count = sum(1 for d in dims if d.get("type") == "style")
    if cap_count < 2:
        errors.append(f"dimensions has {cap_count} capability items, need at least 2")
    if sty_count < 2:
        errors.append(f"dimensions has {sty_count} style items, need at least 2")

    cl = report.get("ownerPortrait", {}).get("collaborationLevel", {})
    level = cl.get("level", "")
    if not isinstance(level, str) or not level.startswith("L"):
        errors.append(f"collaborationLevel.level must be string 'L1'-'L5', got: {level!r}")

    ta = report.get("ownerPortrait", {}).get("tasteAnchor", {})
    names = ta.get("names")
    if not isinstance(names, list):
        errors.append(f"tasteAnchor.names must be array, got: {type(names).__name__}")

    for i, cp_item in enumerate(report.get("catchphrases", [])):
        phrase = cp_item.get("phrase", "")
        if len(phrase) <= 1:
            errors.append(f"catchphrases[{i}] is single char: {phrase!r}")

    hs = report.get("heroStats", {})
    headline = hs.get("headline", "")
    if len(headline) > 15:
        warnings.append(f"heroStats.headline is {len(headline)} chars, target <= 10")

    return errors, warnings


def cmd_finalize(_args: argparse.Namespace) -> None:
    """Merge batch JSONs, validate, upload."""
    report_path = PARTS_DIR / "report.json"
    if report_path.is_file():
        try:
            merged = load_json(report_path)
        except (json.JSONDecodeError, OSError) as e:
            die(f"Failed to read {report_path}: {e}")
        log(f"Read report.json: {len(merged)} top-level keys ({', '.join(merged.keys())})")
    else:
        log("Merging batch files...")
        merged = {}
        for batch_file in ["batch1.json", "batch2.json", "batch3.json"]:
            path = PARTS_DIR / batch_file
            if not path.is_file():
                die(f"Missing {path}. AI must generate report.json or all 3 batch files first.")
            try:
                data = load_json(path)
                merged.update(data)
            except (json.JSONDecodeError, OSError) as e:
                die(f"Failed to read {path}: {e}")
        save_json(PARTS_DIR / "report.json", merged, indent=2)
        log(f"Merged batches: {len(merged)} top-level keys ({', '.join(merged.keys())})")

    log("Auto-fixing common AI errors...")
    fixes = auto_fix_report(merged)
    if fixes:
        for f in fixes:
            log(f"  FIXED: {f}")
        save_json(PARTS_DIR / "report.json", merged, indent=2)
        log(f"  Applied {len(fixes)} auto-fix(es)")
    else:
        log("  No fixes needed")

    log("Validating report...")
    errors, warnings = validate_report(merged)

    for w in warnings:
        log(f"  WARNING: {w}")

    if errors:
        log("VALIDATION FAILED:")
        for e in errors:
            log(f"  ERROR: {e}")
        save_json(PARTS_DIR / "validation_errors.json", {"errors": errors, "warnings": warnings}, indent=2)
        sys.exit(1)

    log("VALIDATION PASSED")

    # Inject share_intro.txt into report.shareContent.intro if present
    share_intro_path = PARTS_DIR / "share_intro.txt"
    if share_intro_path.is_file():
        try:
            intro_text = share_intro_path.read_text(encoding="utf-8").strip()
            if intro_text:
                if "shareContent" not in merged:
                    merged["shareContent"] = {}
                merged["shareContent"]["intro"] = intro_text
                save_json(PARTS_DIR / "report.json", merged, indent=2)
                log(f"Injected share_intro.txt ({len(intro_text)} chars) into report.shareContent.intro")
        except OSError as e:
            log(f"  WARNING: Could not read {share_intro_path}: {e}")

    preview_path = PARTS_DIR / "report.json"
    log(f"\nReport saved to {preview_path}")

    activity = {}
    try:
        activity = load_json(PARTS_DIR / "activity.json")
    except (OSError, json.JSONDecodeError):
        pass

    sampled_count = len(list(COMPRESSED_DIR.glob("session_*.json"))) if COMPRESSED_DIR.is_dir() else 0
    total_count = activity.get("summary", {}).get("totalSessions", sampled_count)

    meta = {
        "sessionsAnalyzed": sampled_count,
        "sessionsTotal": total_count,
        "totalTokens": activity.get("summary", {}).get("totalTokens", 0),
    }

    # Include tier info if available
    try:
        prep_summary = load_json(PARTS_DIR / "prepare_summary.json")
        meta["tier"] = prep_summary.get("tier", "standard")
    except (OSError, json.JSONDecodeError):
        pass

    save_json(PARTS_DIR / "meta.json", meta)

    log("Uploading to clawdiary.ai...")
    if not CRED_FILE.is_file():
        die("No credentials found. Run 'prepare' first.")

    creds = load_json(CRED_FILE)
    if not creds.get("api_key"):
        die("Credentials file has no api_key. Run 'prepare' again.")
    if not creds.get("api_url"):
        creds["api_url"] = API_URL
    payload = json.dumps({
        "report": merged,
        "activity": activity,
        "meta": meta,
        "visibility": "draft",
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{creds['api_url']}/api/report/sync",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {creds['api_key']}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        log(f"Upload response: {json.dumps(result, indent=2)}")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        log(f"Upload failed: HTTP {e.code} {e.reason}")
        if body:
            formatted = format_server_errors(body)
            log(formatted)
        sys.exit(2)
    except Exception as e:
        log(f"Upload failed: {e}")
        sys.exit(2)

    preview_url = result.get("preview_url", "")
    report_url = result.get("url", f"{creds['api_url']}/p/{creds['slug']}")
    claim_url = creds.get("claim_url", "")
    log("")
    if preview_url:
        log("报告已上传为草稿")
        log(f"  预览并发布: {preview_url}")
        log("  (发布前，公开链接不可访问)")
        log("")
        log(f"PREVIEW_URL={preview_url}")
    else:
        log("报告已发布")
        log(f"  查看: {report_url}")
        log("")
        log(f"REPORT_URL={report_url}")

    # Prominent claim reminder if claw is unclaimed
    if claim_url:
        try:
            req = urllib.request.Request(
                f"{creds['api_url']}/api/claw/status",
                headers={"Authorization": f"Bearer {creds['api_key']}"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = json.loads(resp.read())
            if status.get("status") == "pending_claim":
                log("")
                log("=" * 50)
                log("⚠️  龙虾还没认领！请先认领再分享：")
                log(f"  {claim_url}")
                log("  (认领 = 用邮箱登录，绑定到你的账号)")
                log("=" * 50)
                log(f"CLAIM_URL={claim_url}")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="ClawDiary CLI")
    sub = parser.add_subparsers(dest="command")
    prep = sub.add_parser("prepare", help="Auth + data discovery + tier selection + scanning")
    prep.add_argument("--claw-id", help="(deprecated, now auto-detected) Claw ID for incremental update")
    sub.add_parser("finalize", help="Validate + upload")

    args = parser.parse_args()
    if args.command == "prepare":
        cmd_prepare(args)
    elif args.command == "finalize":
        cmd_finalize(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
