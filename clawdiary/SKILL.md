---
name: clawdiary
description: Read AI conversation history, then generate a shareable ClawDiary report — a field report with structured claw taxonomy, showcase track record, and skills data. Use when the user asks to generate their report, run clawdiary, or create their AI portfolio.
allowed-tools: Bash, Read, Glob, Grep, Write, AskUserQuestion
---

<!-- version: 3.1.0 -->

# clawdiary

You are writing a ClawDiary report about your **owner** — a field report from an observer (curator × journalist × Michelin guide reviewer). Read conversation history, then generate a shareable report that proves who your owner is through concrete evidence and observer-perspective storytelling.

**Core principle: Curate evidence of what makes them impressive — and make it shareable.**

---

## Execution Mode

**AUTO-COMPLETE: Steps 1-4 run continuously without stopping.** No confirmation between steps. Only stop at Step 4.

Skip non-fatal errors (unparseable session, undetermined field). Only stop for fatal errors (no sessions, no credentials).

**⚠️ Subagent Execution:** If you are dispatched as a subagent (by OpenClaw or another orchestrator):
1. Read this entire SKILL.md first — it contains the output schema and hard constraints
2. Read `analysis-prompt.md` at Step 2 — it contains the analytical framework for quality generation
3. Do NOT skip these reads. Skipping them causes wrong field names, missing blocks, and validation failures

---

## Step 1: Prepare (CLI)

### 1a. Privacy Statement

Output before anything else:

```
🐾 ClawDiary 隐私说明

✓ 读取本地对话记录（不上传原文）
✓ AI 在本地分析，生成结构化报告
✓ 上传前你会看到完整预览
✓ 上传后可随时设为私密或删除

继续？ [Y/n]
```

### 1b. Auto-Update (mandatory)

```bash
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "$HOME/.openclaw/skills/clawdiary")"
REPO_BASE="https://raw.githubusercontent.com/billc8128/clawdiary-skills/main/clawdiary"
REMOTE_VER=$(curl -sf --max-time 5 "$REPO_BASE/SKILL.md" 2>/dev/null | grep -o 'version: [0-9.]*' | head -1 | cut -d' ' -f2)
LOCAL_VER=$(grep -o 'version: [0-9.]*' "$SKILL_DIR/SKILL.md" 2>/dev/null | head -1 | cut -d' ' -f2)
if [ -n "$REMOTE_VER" ] && [ "$REMOTE_VER" != "$LOCAL_VER" ]; then
  echo "⬆️  Updating ClawDiary: v$LOCAL_VER → v$REMOTE_VER"
  curl -sf "$REPO_BASE/SKILL.md" -o "$SKILL_DIR/SKILL.md"
  curl -sf "$REPO_BASE/analysis-prompt.md" -o "$SKILL_DIR/analysis-prompt.md"
  curl -sf "$REPO_BASE/clawdiary-cli.py" -o "$SKILL_DIR/clawdiary-cli.py"
  echo "✅ Updated. Re-read SKILL.md now."
else
  echo "✅ ClawDiary v${LOCAL_VER:-unknown} is up to date."
fi
```

After updating, re-read updated `SKILL.md` and `analysis-prompt.md` before proceeding.

### 1c. Run Prepare Script

```bash
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "$HOME/.openclaw/skills/clawdiary")"
python3 "$SKILL_DIR/clawdiary-cli.py" prepare
```

**Exit non-zero:** report error, stop. **`pending_claim`:** remind owner about claim link.

### 1d. Incremental Support

The CLI automatically fetches the existing report during prepare (no `--claw-id` needed). If `_cr_parts/existing-report.json` exists after prepare, incremental mode is active.

Print status: `[1/4] Prepare complete ({tier} tier): {sampled} sessions sampled.`

**>>> CONTINUE to Step 2 immediately. <<<**

---

## Step 2: Read & Absorb

### 2a. Read analysis guide

Read `analysis-prompt.md` (same directory as this file). Contains persona, tone, signal-reading framework, block writing guide, and quality checks. **Internalize before reading conversation data.**

### 2b. Read workspace context (highest signal)

Read `_cr_parts/workspace.json` — contains SOUL.md, USER.md, MEMORY.md, IDENTITY.md, AGENTS.md, TOOLS.md, HEARTBEAT.md. These are curated content, prioritize over raw sessions.

### 2c. Read memory logs + config + automations

- `_cr_parts/memory_logs.json` — daily logs with dates → stories and catchphrases
- `_cr_parts/config.json` → clawProfile.model, skills.tools
- `_cr_parts/cron.json` → skills.cron

### 2d. Read compressed sessions

Read all `_cr_parts/compressed/session_*.json`. Observe: characteristic phrases, memorable interactions, working patterns, what makes this owner unique.

### 2e. Read quantitative data

- `_cr_parts/activity.json`, `_cr_parts/tools.json`, `_cr_parts/routines.json`
- `_cr_parts/extensions.json` (if exists) → feeds skills.tools
- `_cr_parts/memory_search.json` (deep scan only, if exists)

### 2f. Read owner summary (cross-claw aggregation)

If `_cr_parts/owner-summary.json` exists, use it for `hero.stats`:
- `totalMessages` → hero.stats[0] (消息)
- `totalDays` → hero.stats[1] (天)
- `totalTokens` → hero.stats[2] (TOKENS)
- `clawCount` → hero.stats[3] (龙虾)

This file contains **owner-level aggregated data across ALL claws**, not just the current one. hero.stats must reflect the owner's total, not just this claw's numbers.

### 2g. Read existing report (incremental mode)

If `_cr_parts/existing-report.json` exists, note names, showcase items, stories, classification. See analysis-prompt.md § Incremental for merge rules.

**>>> CONTINUE to Step 3 immediately. <<<**

---

## Step 3: Generate Report

Generate ONE file: `_cr_parts/report.json` with all 7 blocks. **Write the complete JSON in a single write operation.**

### Strategy

For large inputs (>50K tokens): write skeleton first (all fields with placeholder content), then fill block by block.

Generation order: **clawProfile** → **hero + showcase** → **stories + catchphrases + skills + letter**

### Output Schema

```json
{
  "hero": {
    "ownerName": "string — infer from context, or [你的名字]",
    "headline": "string — <=20 chars, single statement, NO ×/+ joins",
    "tagline": "string — <=60 chars, MUST contain concrete numbers",
    "stats": [
      {"value": "3,847", "label": "消息"},
      {"value": "127", "label": "天"},
      {"value": "21.4M", "label": "TOKENS"},
      {"value": "3", "label": "龙虾"}
    ]
  },
  "clawProfile": {
    "clawName": "string — AI name from conversation",
    "level": "L1|L2|L3|L4|L5",
    "levelLabel": "虾苗|小钳|红壳|巨钳|虾皇",
    "oneLiner": "string — e.g. L4 毒舌严格的全栈编程龙虾",
    "function": "string — free text, e.g. 全栈开发搭子",
    "domain": "string — free text, e.g. 全栈编程",
    "persona": "string — free text, e.g. 毒舌但高效",
    "model": "string? — Claude Opus, GPT-4, etc",
    "functionLabel": "string — 2-4 chars for UI badge",
    "domainLabel": "string — 2-4 chars",
    "personaLabel": "string — 2-4 chars",
    "stats": [
      {"value": "1,247", "label": "消息"},
      {"value": "27", "label": "天"},
      {"value": "3.5M", "label": "TOKENS"},
      {"value": "8", "label": "SKILLS"}
    ],
    "dimensions": {
      "depth": {"code": "D1-D5", "label": "深度", "evidence": "<=100 chars, cite specific behavior"},
      "breadth": {"code": "B1-B5", "label": "广度", "evidence": "<=100 chars"},
      "orchestration": {"code": "O1-O5", "label": "驾驭", "evidence": "<=100 chars"}
    }
  },
  "showcase": [
    {"metric": "6 份报告", "domain": "产品调研", "fact": "27 天内完成 6 份深度竞品调研报告"}
  ],
  "stories": [
    {
      "title": "10-20 chars", "setup": "40-80 chars", "turningPoint": "60-120 chars",
      "ownerQuote": "<=80 chars", "resolution": "40-80 chars", "reflection": "40-60 chars"
    }
  ],
  "catchphrases": [
    {"phrase": "exact words", "frequency": 8, "vibe": "demanding|decisive|philosophical|pivot|praise|frustration", "clawInterpretation": "guess-perspective"}
  ],
  "skills": {
    "subtitle": "harness design summary",
    "tools": [{"icon": "emoji", "name": "string", "count": 0, "highlight": "string", "featured": true}],
    "cron": [{"schedule": "每日 09:00", "name": "string", "description": "string", "runs": 27}]
  },
  "letter": {"text": "100-200 字", "signoff": "signature + status", "mood": "reflective|grateful|wry|bittersweet"}
}
```

### Block Constraints (hard — CLI will reject violations)

| Block | Rules |
|-------|-------|
| `hero.headline` | <=20 chars. No ×/+ joins. Single coherent statement. |
| `hero.stats` | **Exactly 4**: 消息/天/TOKENS/龙虾. Values <=6 chars, no units. **Use `owner-summary.json` totals** (not this claw's numbers). |
| `clawProfile.level` | L1-L5 via round(mean(D,B,O)). See analysis-prompt.md § Classification. |
| `clawProfile.stats` | **Exactly 4**: 消息/天/TOKENS/SKILLS. Claw-level (this claw only). Values <=6 chars, no units. |
| `clawProfile.persona` | Must have personality contrast or tension ("毒舌但高效"). NOT bland labels ("严格辩证", "认真负责"). |
| `clawProfile.dimensions` | depth/breadth/orchestration each with code + evidence citing specific behavior. |
| `showcase` | 3-6 items. `metric` has number. `fact` <=50 chars. Different domains. |
| `stories` | 1-3 items. Must have turningPoint + ownerQuote. Self-contained. |
| `catchphrases` | 3-8 items. No single punctuation (？。!). No generic words (ok/好的/嗯). `frequency` = number. |
| `skills` | See § Skills Block Assembly below. |
| `letter.text` | 100-200 字. Must reference a specific showcase achievement. |

### Skills Block: Assembly Guide

The skills block has the most complex data pipeline. Three components, three data sources:

**`subtitle`** — Measures the human's investment in designing AI behavior, NOT technical infrastructure.
- Scan workspace.json: count lines in SOUL.md, USER.md, AGENTS.md, MEMORY.md, IDENTITY.md, TOOLS.md
- Count custom instructions, heartbeat definitions from HEARTBEAT.md
- Format: `"1200 行 SOUL.md · AGENTS.md · 12 条自定义指令"`
- Include file names + line counts or entry counts where available

**`tools[]`** — Merge TWO sources from `_cr_parts/tools.json`:

| Source | What | `name` field | Icon | Featured? |
|--------|------|-------------|------|-----------|
| `installedSkills` | OpenClaw skills (clawdiary, clawfeed, etc.) | Skill name as-is | 🛠️ | Yes, prioritize |
| `toolCounts` | Tool usage stats (web_fetch ×45) — top 5-8 | **Exact tool name from data** | Semantic emoji | Top 2-3 only |

- **Include ALL installed skills.** They represent the owner's capability investment.
- **`toolCounts` names must be the exact tool names from the data** (e.g. `web_fetch`, `memory_search`, `Task`, `Bash`). Do NOT rename them to creative Chinese names. `web_fetch` stays `web_fetch`, not "网页抓取". `Task` stays `Task`, not "sub-agent 调度".
- AI writes `highlight` for each: describe the tool's role in the owner's workflow (not generic tool description)
- Skills listed BEFORE raw tools
- Do NOT invent tools that don't exist in the data. Do NOT aggregate multiple tools into made-up categories like "cron 自动化" or "飞书文档".

**`cron[]`** — From `_cr_parts/cron.json`. Include ALL cron jobs.

For each job:
1. **`runs`**: Copy the `runs` count from cron.json if present (number of executions). Do NOT omit or fabricate this.
2. **`description`**: Construct from the job's `prompt` or `command` field in cron.json (primary source), cross-reference with conversation data, or infer from `name`.
3. **`schedule`**: Format as readable text: cron `0 9 * * *` → `"每日 09:00"`, `0 21 * * 0` → `"每周日 21:00"`, every 30 min → `"每30分钟"`

Cron automation demonstrates sophisticated AI orchestration — a user with 10+ cron jobs is almost certainly O4-O5.

### ⚠️ Common Field Name Errors

| Wrong | Correct | Where |
|-------|---------|-------|
| `title` | `metric` | showcase item |
| `what` / `soWhat` | `fact` | showcase item |
| `soWhat` | `clawInterpretation` | catchphrase |
| `"high"` | `8` (number) | catchphrases.frequency |

### Name Handling

Infer `ownerName` and `clawName` from context. Reuse from existing report if available. After generation, tell user the inferred names.

### Step 3b: Group Chat Intro (optional, >=10 sessions)

Generate `_cr_parts/share_intro.txt`. See analysis-prompt.md § Group Chat Intro for format.

**>>> CONTINUE to Step 4 immediately. <<<**

---

## Step 4: Finalize (CLI)

```bash
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "$HOME/.openclaw/skills/clawdiary")"
python3 "$SKILL_DIR/clawdiary-cli.py" finalize
```

**Exit 0:** Extract `PREVIEW_URL=` (draft) or `REPORT_URL=` (direct publish). Reports upload as drafts by default — public URL returns 404 until user clicks Publish. This is expected.

**Exit 1:** Validation failed. Read `_cr_parts/validation_errors.json`, fix `report.json`, re-run finalize.

**Exit 2:** Upload failed. Common cause: wrong field names (e.g. `title` instead of `metric` in showcase).

### Present to user

Terminal summary:
1. Hero headline + tagline
2. Claw profile + D/B/O
3. Top 2-3 showcase items
4. Best story title
5. Top 2-3 catchphrases
6. Skills: featured tools + cron count

If `pending_claim`:
> ⚠️ 你的龙虾还没认领！先认领再发布：**{CLAIM_URL}**

Then:
> Your ClawDiary is ready! **{PREVIEW_URL}**
>
> 我推断你的名字是「{ownerName}」，AI 名字是「{clawName}」。如需修改请告诉我。

If the user wants changes, apply to `report.json`, re-run finalize, ask again.

---

## Privacy

- No raw conversation text in report.json
- `evidence` fields <=100 chars
- Skip sensitive content (passwords, tokens, API keys)
- **Language:** Match user's primary language. Keep original-language quotes. JSON field names in English.
