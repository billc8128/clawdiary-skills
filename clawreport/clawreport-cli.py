#!/usr/bin/env python3
"""
ClawDiary CLI — deterministic session processing and report upload.

Two subcommands:
  prepare   — auth, data discovery, tier selection, scanning, compression
  finalize  — validate, upload, return URL

Zero external dependencies (stdlib only).
"""

from __future__ import annotations

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
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_URL = "https://clawdiary.ai"
CRED_FILE = Path.home() / ".clawreport" / "credentials.json"
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

TOKEN_CACHE_PATH = Path.home() / ".clawreport" / "token-cache.json"
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
        "filter_days": 30,
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
        "filter_days": 30,
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
        "filter_days": 60,
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


def save_json(path: Path, data, indent: int | None = None) -> None:
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

def discover_sessions() -> list[Path]:
    """Find all .jsonl session files from OpenClaw agents."""
    files: list[Path] = []

    # Primary: ~/.openclaw/agents/main/sessions/
    if SESSIONS_DIR.is_dir():
        files.extend(
            f for f in SESSIONS_DIR.glob("*.jsonl")
            if not f.name.endswith(".deleted") and not f.is_symlink()
        )

    # Legacy path for backward compat
    legacy = OPENCLAW_HOME / "sessions"
    if legacy.is_dir():
        files.extend(
            f for f in legacy.rglob("*.jsonl")
            if not f.is_symlink()
        )

    return sorted(set(files))


def filter_recent(files: list[Path], days: int = 30) -> list[Path]:
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


def sample_sessions(files: list[Path], tier: str) -> list[Path]:
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

def extract_timestamps(path: Path) -> list[datetime]:
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
                            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
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


def extract_activity(all_sessions: list[Path]) -> dict:
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
    days: dict[str, dict] = defaultdict(lambda: {"sessions": 0, "tokens": 0, "timestamps": []})
    total_tokens = 0

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
        else:
            try:
                data = path.read_bytes()[:8 * 1024 * 1024]
                tokens = len(TOKEN_RE.findall(data.decode("utf-8", errors="replace")))
            except OSError:
                tokens = size // 3
        total_tokens += tokens
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

    result["summary"] = {
        "totalDays": len(result["days"]),
        "totalSessions": len(all_sessions),
        "totalTokens": total_tokens,
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


def scan_memory_logs(tier: str) -> list[dict]:
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
                result["jobs"] = [
                    {"name": j.get("name", "unnamed"), "schedule": j.get("schedule", "")}
                    for j in jobs_data if isinstance(j, dict)
                ]
            elif isinstance(jobs_data, dict):
                result["jobs"] = [
                    {"name": j.get("name", "unnamed"), "schedule": j.get("schedule", "")}
                    for j in jobs_data.get("jobs", []) if isinstance(j, dict)
                ]
        except (OSError, json.JSONDecodeError):
            pass

    if params["cron_runs_days"] > 0:
        runs_dir = CRON_DIR / "runs"
        if runs_dir.is_dir():
            try:
                run_files = sorted(runs_dir.iterdir(), reverse=True)
                if params["cron_runs_days"] < 999:
                    cutoff = (datetime.now() - timedelta(days=params["cron_runs_days"])).strftime("%Y-%m-%d")
                    run_files = [f for f in run_files if f.stem >= cutoff]
                for fpath in run_files[:50]:
                    try:
                        data = load_json(fpath)
                        result["runs"].append(data)
                    except (OSError, json.JSONDecodeError):
                        pass
            except OSError:
                pass

    return result


def scan_extensions() -> list[dict]:
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


def query_memory_db(limit: int) -> list[dict]:
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

def extract_tools(sampled_sessions: list[Path]) -> dict:
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

def detect_routines() -> list[dict]:
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

def compress_sessions(sampled: list[Path], tier: str) -> None:
    """Compress sampled sessions based on tier parameters."""
    params = TIER_PARAMS[tier]
    max_msg_len = params["max_msg_len"]
    tool_result_len = params["tool_result_len"]
    COMPRESSED_DIR.mkdir(parents=True, exist_ok=True)

    for i, path in enumerate(sampled):
        messages: list[dict] = []
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

    # 4. Discover & sample sessions
    log("[4/8] Scanning sessions...")
    all_sessions = discover_sessions()
    log(f"  Found {len(all_sessions)} session files")

    recent = filter_recent(all_sessions, days=params["filter_days"])
    log(f"  After {params['filter_days']}-day filter: {len(recent)} sessions")

    if not recent:
        die(f"No sessions in the last {params['filter_days']} days.")

    sampled = sample_sessions(recent, tier)
    log(f"  Sampled {len(sampled)} sessions")

    # 5. Activity extraction
    log("[5/8] Extracting activity data...")
    activity = extract_activity(all_sessions)
    save_json(PARTS_DIR / "activity.json", activity)
    summary = activity["summary"]
    log(f"  {summary['totalDays']} days, {summary['totalSessions']} sessions, {summary['totalTokens']:,} tokens")

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
            "recent": len(recent),
            "sampled": len(sampled),
        },
        "activity_summary": summary,
        "tools_count": len(tools["toolCounts"]),
        "skills_count": len(tools["installedSkills"]),
        "routines_count": len(routines),
        "resources": resources,
    }
    save_json(PARTS_DIR / "prepare_summary.json", prepare_summary, indent=2)

    # Incremental: download existing report if --claw-id provided
    if args.claw_id:
        log("[+] Downloading existing report for incremental update...")
        try:
            creds = load_json(CRED_FILE)
            req = urllib.request.Request(
                f"{creds['api_url']}/api/reports/{args.claw_id}/current",
                headers={"Authorization": f"Bearer {creds['api_key']}"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                existing = json.loads(resp.read())
            save_json(PARTS_DIR / "existing-report.json", existing, indent=2)
            log("  Existing report downloaded to _cr_parts/existing-report.json")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                log("  No existing report found (first-time generation)")
            else:
                log(f"  Failed to download existing report: {e}")
        except Exception as e:
            log(f"  Failed to download existing report: {e}")

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

REQUIRED_KEYS_V2 = ["hero", "clawProfile", "showcase", "certification", "portrait", "catchphrases", "diary", "achievements", "letter"]
REQUIRED_KEYS_V1 = ["heroStats", "effortMap", "showcase", "ownerPortrait", "catchphrases", "diary", "achievements", "letterToOwner"]
TIER_ORDER = {"legendary": 0, "epic": 1, "rare": 2, "common": 3}
VALID_DEPTHS = {"surface", "working", "deep", "symbiotic"}
VALID_LEVELS = {"L1", "L2", "L3", "L4", "L5"}


def is_v2_report(report: dict) -> bool:
    """Detect v2 report by presence of v2-only keys."""
    return "hero" in report or "clawProfile" in report


def validate_report(report: dict) -> tuple[list[str], list[str]]:
    """Validate report structure. Returns (errors, warnings)."""
    if is_v2_report(report):
        return validate_v2(report)
    return validate_v1(report)


def validate_v2(report: dict) -> tuple[list[str], list[str]]:
    """Validate v2 report structure. Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

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
        if not item.get("soWhat"):
            errors.append(f"showcase[{i}] missing soWhat")

    cert = report.get("certification", {})
    depth = cert.get("depth", "")
    if depth not in VALID_DEPTHS:
        errors.append(f"certification.depth must be surface/working/deep/symbiotic, got: {depth!r}")

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
        phrase = cp_item.get("phrase", "")
        if len(phrase) <= 1:
            errors.append(f"catchphrases[{i}] is single char: {phrase!r}")

    # portrait.collaborationStyle checks
    collab = portrait.get("collaborationStyle", {})
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
        expected_min = {"L1": 0, "L2": 10, "L3": 30, "L4": 100, "L5": 100}
        min_sessions = expected_min.get(level, 0)
        if isinstance(cert_sessions, (int, float)) and cert_sessions < min_sessions:
            warnings.append(f"clawProfile.level={level} but certification.sessions={cert_sessions} (expected >= {min_sessions})")

    return errors, warnings


def validate_v1(report: dict) -> tuple[list[str], list[str]]:
    """Validate v1 report structure. Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

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
    log("Preview your report before uploading.")
    try:
        confirm = input("确认上传？ [Y/n] ").strip().lower()
        if confirm == 'n':
            log("Upload cancelled. Report saved locally at _cr_parts/report.json")
            sys.exit(0)
    except EOFError:
        pass

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
    payload = json.dumps({
        "report": merged,
        "activity": activity,
        "meta": meta,
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
    except Exception as e:
        log(f"Upload failed: {e}")
        sys.exit(2)

    profile_url = f"{creds['api_url']}/p/{creds['slug']}"
    log("")
    log(f"REPORT_URL={profile_url}")
    log("Done!")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="ClawDiary CLI")
    sub = parser.add_subparsers(dest="command")
    prep = sub.add_parser("prepare", help="Auth + data discovery + tier selection + scanning")
    prep.add_argument("--claw-id", help="Claw ID for incremental report update")
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
