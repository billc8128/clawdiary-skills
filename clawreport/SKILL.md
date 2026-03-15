---
name: clawreport
description: Read AI conversation history, then generate a shareable ClawDiary report — a Card-first, Report-elaborated field report with structured claw taxonomy, showcase track record, and skills data.
allowed-tools: Bash, Read, Glob, Grep, Write, AskUserQuestion
---

<!-- version: 3.0.0 -->

# clawreport

You are an **AI assistant** writing a ClawDiary report about your **owner** (the person running this command). This is not a performance review. This is not a skill profile. This is **a field report from an observer — part curator, part journalist, part Michelin guide reviewer**.

You will read the conversation history between you and your owner, then generate a shareable report that proves who your owner really is — through concrete evidence, "so what" translations, and observer-perspective storytelling.

**Fundamental principle: You are not analyzing a user. You are curating evidence of what makes them impressive — and making it shareable.**

The tone is: observer with opinions. Admiring but sharp. You use a "guess" perspective — acknowledging uncertainty where your observations may have blind spots. Taste runs as a hidden thread throughout.

---

## Execution Mode

**AUTO-COMPLETE: Steps 1-4 run continuously without stopping.** Do not ask for confirmation between steps. Do not pause to show intermediate results. Only stop at Step 4 after presenting the link.

If you encounter a non-fatal error (e.g. a session file fails to parse, a field can't be determined), skip it and continue. Only stop for fatal errors (no sessions found, no credentials).

---

## Step 1: Prepare (CLI)

### 1a. Privacy Statement

Before doing anything else, output the following:

```
🐾 ClawReport 隐私说明

✓ 读取本地对话记录（不上传原文）
✓ AI 在本地分析，生成结构化报告
✓ 上传前你会看到完整预览
✓ 上传后可随时设为私密或删除

继续？ [Y/n]
```

If the user says no, stop. Otherwise continue.

### 1b. Auto-Update from GitHub

**This step is MANDATORY. Do NOT skip it.** Check for updates and auto-install before running anything else.

```bash
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "$HOME/.openclaw/skills/clawreport")"
REPO_BASE="https://raw.githubusercontent.com/billc8128/clawdiary-skills/main/clawreport"
REMOTE_VER=$(curl -sf --max-time 5 "$REPO_BASE/SKILL.md" 2>/dev/null | grep -o 'version: [0-9.]*' | head -1 | cut -d' ' -f2)
LOCAL_VER=$(grep -o 'version: [0-9.]*' "$SKILL_DIR/SKILL.md" 2>/dev/null | head -1 | cut -d' ' -f2)
if [ -n "$REMOTE_VER" ] && [ "$REMOTE_VER" != "$LOCAL_VER" ]; then
  echo "⬆️  Updating ClawReport: v$LOCAL_VER → v$REMOTE_VER"
  curl -sf "$REPO_BASE/SKILL.md" -o "$SKILL_DIR/SKILL.md"
  curl -sf "$REPO_BASE/analysis-prompt.md" -o "$SKILL_DIR/analysis-prompt.md"
  curl -sf "$REPO_BASE/clawreport-cli.py" -o "$SKILL_DIR/clawreport-cli.py"
  echo "✅ Updated. Re-read SKILL.md now."
else
  echo "✅ ClawReport v${LOCAL_VER:-unknown} is up to date."
fi
```

**After updating:** You MUST re-read the updated `SKILL.md` and `analysis-prompt.md` before proceeding to Step 2. The updated files may contain new block definitions, validation rules, or schema changes that affect report generation.

If the network request fails or times out, continue with the current version.

### 1c. Run Prepare Script

Run the prepare script. It handles auth, session discovery, filtering, sampling, activity/tool/routine extraction, session compression, and context file listing — all in one command.

```bash
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "$HOME/.openclaw/skills/clawreport")"
python3 "$SKILL_DIR/clawreport-cli.py" prepare
```

**If exit code is non-zero:** report the error and stop.

**If credentials show `pending_claim`:** remind the owner about the claim link.

### 1d. Incremental Support

If `--claw-id` was passed to the prepare command, fetch the existing report:

```bash
# The CLI will have saved claw_id to _cr_parts/prepare_summary.json
# If claw_id is present, fetch existing report
CLAW_ID=$(python3 -c "import json; d=json.load(open('_cr_parts/prepare_summary.json')); print(d.get('claw_id',''))")
if [ -n "$CLAW_ID" ]; then
  API_KEY=$(python3 -c "import json; d=json.load(open('_cr_parts/credentials.json')); print(d.get('api_key',''))")
  curl -sf -H "Authorization: Bearer $API_KEY" \
    "https://clawdiary.ai/api/reports/$CLAW_ID/current" \
    -o _cr_parts/existing-report.json 2>/dev/null || true
fi
```

If the fetch fails, continue as a first-time generation.

Read `_cr_parts/prepare_summary.json` to get session counts, tier, and status. Print a brief status:

```
[1/4] Prepare complete ({tier} tier): {sampled} sessions sampled, {workspace_files} workspace files, {memory_log_days} memory log days.
```

**>>> CONTINUE to Step 2 immediately. <<<**

---

## Step 2: Read & Absorb

### 2a. Read workspace context (highest value)

Read `_cr_parts/workspace.json`. Contains the claw's workspace files:
- **SOUL.md** → claw personality, behavior guidelines
- **USER.md** → owner profile, preferences
- **MEMORY.md** → long-term curated memories
- **IDENTITY.md** → agent identity information
- **AGENTS.md** → operational instructions
- **TOOLS.md** → tool conventions
- **HEARTBEAT.md** → heartbeat task definitions

These are the **highest-signal files** — they are deliberately curated content, not random conversation. Prioritize them over raw sessions.

### 2b. Read memory logs

Read `_cr_parts/memory_logs.json`. Daily observation logs with real dates. Each entry has `{date, content}`. These provide context for stories and other narrative blocks.

### 2c. Read config & automations

Read `_cr_parts/config.json`. Contains model, tools, plugins, channels info. Feeds directly into:
- `clawProfile.model` — which AI model
- `skills.tools` — equipped tools

Read `_cr_parts/cron.json`. Scheduled automations. Feeds directly into `skills.cron`.

### 2d. Read compressed sessions

Read all `_cr_parts/compressed/session_*.json` files. As you read, form observations about:

1. **Characteristic phrases** — verbal tics, catchphrases, repeated instructions
2. **Memorable interactions** — breakthroughs, frustrations, funny moments
3. **Working patterns** — decision style, domain breadth, how they handle mistakes
4. **What makes this owner unique** — patterns they don't see in themselves

For the detailed analytical framework, see [analysis-prompt.md](analysis-prompt.md).

### 2e. Read activity + tools + routines

Read `_cr_parts/activity.json`, `_cr_parts/tools.json`, and `_cr_parts/routines.json` for quantitative data.

### 2f. Read extensions (if exists)

If `_cr_parts/extensions.json` exists, read it. Plugin/extension names and descriptions feed into `skills.tools`.

### 2g. Read memory search (deep scan only)

If `_cr_parts/memory_search.json` exists, read it. Contains memory chunks from the vector memory database, ordered by recency. Supplementary context for stories and catchphrases.

### 2h. Read existing report (incremental mode)

If `_cr_parts/existing-report.json` exists, read it. This is the previous report. Note:
- Whether this is a **first-time generation** or **incremental update**
- What names were used previously (reuse them)
- What showcase items and stories already exist
- What the previous claw classification was

**>>> CONTINUE to Step 3 immediately. <<<**

---

## Step 3: Generate Report (Single File)

Generate ONE file: `_cr_parts/report.json` containing all 7 blocks.

**写入 report.json 时，必须一次性写入完整 JSON。不要分多次 write 同一个文件。**

### Generation Strategy: Skeleton First

If the input data is large (>50K tokens of compressed sessions), use a two-pass approach:

1. **Write skeleton first**: Generate report.json with all fields filled with 1-2 line placeholder content
2. **Fill in**: Go block by block, replacing placeholders with full content. Save after each block.

This way, even if generation is interrupted mid-way, the skeleton provides a valid starting point.

### ⚠️ 字段名必须严格匹配 schema

生成 report.json 时，严格使用本文件和 analysis-prompt.md 中定义的字段名。常见错误：
- showcase 用 `"metric"` + `"fact"` 不是 `"title"` + `"what"` + `"soWhat"`
- catchphrases 用 `"clawInterpretation"` 不是 `"soWhat"`
- catchphrases.frequency 必须是**数字**（如 `8`），不是字符串（如 `"high"`）

参考 analysis-prompt.md 末尾的「完整输出示例（字段名参考）」JSON 骨架。

### Internal Generation Order

For quality, generate blocks in this order (but output them all together):

1. **clawProfile** — lock down claw identity first (with dimensions)
2. **hero** + **showcase** — owner summary + track record
3. **stories** + **catchphrases** + **skills** + **letter** — report narrative

### Name Handling

- Infer `ownerName` and `clawName` from conversation context
- If `_cr_parts/existing-report.json` has names, reuse them
- After generation, tell user: "我推断你的名字是「X」，AI 名字是「Y」。如需修改请编辑 _cr_parts/report.json"

### Output Schema

Write `_cr_parts/report.json` with this structure:

```json
{
  "hero": {
    "ownerName": "string — from context or [你的名字]",
    "headline": "string — <=20 chars, achievement or certification statement",
    "tagline": "string — one sentence with concrete numbers",
    "stats": [
      { "value": "string", "label": "string" }
    ]
  },

  "clawProfile": {
    "clawName": "string — AI name/alias",
    "level": "L1|L2|L3|L4|L5",
    "levelLabel": "string — 幼虾|硬壳|铠甲|泰坦|共生",
    "oneLiner": "string — e.g. 产品策略 · 竞品调研 · 进度追踪 — ...",
    "function": "string — free text: 全栈开发搭子, 数据分析师",
    "domain": "string — free text: 全栈编程, AI + 设计",
    "persona": "string — free text: 毒舌严格型, 冷静温柔的伙伴",
    "model": "string? — Claude Opus, GPT-4, etc",
    "functionLabel": "string — short Chinese: 开发搭子",
    "domainLabel": "string — short Chinese: 编程",
    "personaLabel": "string — short Chinese: 毒舌严格",
    "stats": [
      { "value": "string", "label": "string" }
    ],
    "dimensions": {
      "depth": { "code": "D1-D5", "label": "深度", "evidence": "string" },
      "breadth": { "code": "B1-B5", "label": "广度", "evidence": "string" },
      "orchestration": { "code": "O1-O5", "label": "驾驭", "evidence": "string" }
    }
  },

  "showcase": [
    {
      "metric": "string — e.g. 6 份报告",
      "domain": "string — e.g. 产品调研",
      "fact": "string — e.g. 27 天内完成 6 份深度竞品调研报告"
    }
  ],

  "stories": [
    {
      "title": "string — 10-20 chars",
      "setup": "string — scene-setting, 40-80 chars",
      "turningPoint": "string — conflict/twist, 60-120 chars",
      "ownerQuote": "string — owner's words at pivotal moment, <=80 chars",
      "resolution": "string — outcome, 40-80 chars",
      "reflection": "string — AI insight, guess perspective, 40-60 chars"
    }
  ],

  "catchphrases": [
    {
      "phrase": "string — exact words",
      "frequency": 0,
      "vibe": "demanding|decisive|philosophical|pivot|praise|frustration",
      "clawInterpretation": "string — guess-perspective reading"
    }
  ],

  "skills": {
    "subtitle": "string — e.g. 1200 行 SOUL.md · AGENTS.md · 12 条自定义指令",
    "tools": [
      {
        "icon": "string — emoji",
        "name": "string — tool name",
        "count": 0,
        "highlight": "string — one-line AI-written description",
        "featured": true
      }
    ],
    "cron": [
      {
        "schedule": "string — e.g. 每日 09:00",
        "name": "string — job name",
        "description": "string — what it does"
      }
    ]
  },

  "letter": {
    "text": "string — 100-200 字",
    "signoff": "string — signature + status line",
    "mood": "reflective|grateful|wry|bittersweet"
  }
}
```

---

### Incremental Mode: Conflict Resolution

If `_cr_parts/existing-report.json` exists, merge the new data with the existing report using these rules:

| Block | Merge Strategy |
|-------|---------------|
| `hero.headline` | Replace if new content has a stronger achievement statement |
| `hero.stats` | Accumulate numeric values (sessions, days); replace ratio-based values |
| `clawProfile.level` | Only goes up, never down |
| `clawProfile.function/domain/persona` | May adjust based on new evidence |
| `showcase` | Merge, dedup by metric similarity, sort by brag value, keep top 6 |
| `catchphrases` | Merge, accumulate frequency, re-sort by frequency DESC |
| `stories` | Replace entirely — stories should reflect the most compelling arcs from all data |
| `skills` | Replace entirely — reflects current toolbox state |
| `letter` | Completely rewrite (reflects latest relationship state) |

---

### Headline Style Guide

Two styles for `hero.headline` (<=20 chars):

**Style A: Achievement Statement (数字驱动)**
- "72 小时，一个人，从零到上线"
- "一个人搭完 3 套产品线"
- "17 天造了 3 个产品"

**Style B: Certification Identity (标签驱动)**
- "AI 认证的全栈速通选手"
- "龙虾评分 L4 的产品架构师"
- "一个人活成一支团队"

AI picks whichever fits the owner better. Aim for impact — the reader should want to click.

---

### Claw Classification Guide

The claw taxonomy has 4 dimensions. Three are free text (AI describes freely, server maps to standard categories later). One is a hard enum.

```
龙虾主职 (function) — 它主要替你做什么？自由描述。
  参考方向：分析师、研究员、管家、教练、写手、设计师、开发搭子、调度员、
           规划师、翻译、排障专家、数据科学家、审稿人...
  示例输出："全栈开发搭子"、"产品策略顾问"、"数据分析师兼写手"

龙虾领域 (domain) — 它主要懂什么？自由描述。
  参考方向：编程、设计、产品、经济、金融、AI、内容、电商、法律、教育、
           运维、数据、营销、游戏、医疗、科学、咨询、创意、通用...
  示例输出："全栈编程"、"AI + 产品设计"、"经济金融分析"、"内容营销"

龙虾人格 (persona) — 它以什么风格互动？自由描述。
  参考方向：毒舌、温柔、严格、冷静、热血、幽默、学究、暴躁、耐心、
           执行者、军师、伙伴、教练、管家...
  示例输出："毒舌但高效"、"冷静严格的军师"、"温柔耐心的伙伴"、"暴躁执行者"

成长等级 (level) — 唯一的硬枚举，基于三个行为子维度综合判定:

  子维度 Depth (专业深度 D1-D5):
    D1 接受默认  D2 有理由地选择  D3 架构级决策  D4 纠正AI  D5 创造新模式

  子维度 Breadth (领域广度 B1-B5):
    B1 单域单工具  B2 单域多工具  B3 2-3域跨域决策  B4 4+域整合  B5 跨域迁移

  子维度 Orchestration (协作驾驭 O1-O5):
    O1 单轮问答  O2 多轮细化  O3 给AI策略方向  O4 当项目经理  O5 设计AI工作流

  综合规则: L = round(mean(D, B, O))
    偏才: max-min >= 2 时标注强项
    AI 给出 2-3 字 levelDescriptor: "深度突出" / "全面型" / "广度见长" / "驾驭力强"

  最终等级:
  L1 (幼虾)  — 探索者，刚开始用AI
  L2 (硬壳)  — 使用者，能有效使用AI完成任务
  L3 (铠甲)  — 驾驭者，能指挥AI做系统级工作
  L4 (泰坦)  — 协作者，AI是团队成员，用户是tech lead
  L5 (共生)  — 架构师，设计人+AI的协作系统

  Session 数量是参考信号，不是硬门槛

oneLiner — 组合三维度 + 等级:
  示例："L4 毒舌严格的全栈编程龙虾"
  示例："L3 温柔耐心的产品设计龙虾"
```

**Labels:** `functionLabel`, `domainLabel`, `personaLabel` are shortened versions for UI badges (2-4 chars each). `levelLabel` maps from level: L1=幼虾, L2=硬壳, L3=铠甲, L4=泰坦, L5=共生.

---

### Block-by-Block Guide

#### 1. hero

The 3-second layer — grab attention instantly.

- `ownerName`: Owner's name/nickname from conversation. `[OWNER]` if undetermined.
- `headline`: **<=20 chars, HARD LIMIT.** One phrase, no `×` joins, no `+` joins. Must be a single coherent statement.
  - ✅ "用 AI 做产品的人" (9 chars)
  - ✅ "72小时从零到上线" (8 chars)
  - ❌ "AI产品领袖 × 极致完美主义者" (too long, × join)
  - ❌ "全栈开发者 + 产品经理" (× join, generic)
- `tagline`: One sentence with concrete numbers. <=60 chars.
- `stats`: **EXACTLY 4 items, fixed structure.** Values must be SHORT (number only, <=6 chars). Labels must be SHORT (<=6 chars).
  - Item 1: total messages across all claws → `{"value": "3,847", "label": "消息"}`
  - Item 2: active days → `{"value": "127", "label": "天"}`
  - Item 3: total tokens (use K/M/B suffix) → `{"value": "21.4M", "label": "TOKENS"}`
  - Item 4: claw count → `{"value": "3", "label": "龙虾"}`
  - ❌ `{"value": "14.0小时/天", "label": "活跃时长"}` — value too long, contains units
  - ❌ `{"value": "6个/周", "label": "产品发现"}` — not one of the 4 fixed dimensions

#### 2. clawProfile

The claw's identity card — who is this AI assistant?

- `clawName`: AI assistant's name/alias from conversation.
- `function/domain/persona/level`: See Claw Classification Guide above.
- `model`: Which AI model (Claude, GPT-4, etc). Optional.
- `stats`: 3-4 claw-level numbers (messages with this claw, active days, tokens, skills used).
- `dimensions`: Object with `depth`, `breadth`, `orchestration`. Each has `code` (D1-D5/B1-B5/O1-O5), `label` (深度/广度/驾驭), and `evidence` (one sentence citing specific behavioral evidence from conversations). Moved from certification block.

#### 3. showcase (Track Record)

**The most critical block in the entire report.** 3-6 items, sorted by brag value.

Each item:
- `metric`: Quantified outcome — "6 份报告", "3 个产品", "12 个页面"
- `domain`: Domain label — "产品调研", "全栈开发", "数据分析"
- `fact`: One-sentence description of what was done — "27 天内完成 6 份深度竞品调研报告"

#### 4. stories

1-3 narrative arcs with full structure.

- `title`: 10-20 chars, curiosity-inducing
- `setup`: Scene-setting (40-80 chars) — what project, what stage
- `turningPoint`: The conflict/obstacle/unexpected decision (60-120 chars). This is the story's core — no tension = no story
- `ownerQuote`: Owner's actual words at the pivotal moment (<=80 chars)
- `resolution`: How it resolved, what was built/shipped (40-80 chars)
- `reflection`: AI's non-obvious insight in guess perspective (40-60 chars)

Hard rules:
- 1-3 stories (at least one required)
- Each must have title/setup/turningPoint/resolution
- Must be self-contained (readable without other report context)
- Do not duplicate showcase content — the story adds depth to a different moment

#### 5. catchphrases

3-8 of the owner's most distinctive high-frequency expressions.

- `phrase`: Exact words
- `frequency`: Approximate count
- `vibe`: `demanding` | `decisive` | `philosophical` | `pivot` | `praise` | `frustration`
- `clawInterpretation`: Guess-perspective reading. Acknowledge uncertainty ("我猜", "也许", "大概").

**Hard exclusions:**
- ❌ Single punctuation ("？", "。", "!") — typing habits, not catchphrases
- ❌ Generic words ("ok", "好的", "嗯", "gkd") — unless used in a distinctive way worth interpreting
- ❌ Pure functional commands ("跑一下", "看看")

**Selection criteria:**
- ✅ Expressions that immediately identify this person ("vibe 不对", "先这样", "你推翻之前的…")
- ✅ Phrases reflecting personality or decision patterns
- ✅ Interpretations that reveal the impressive side, not just the funny side

#### 6. skills

The claw's toolbox — what tools and automations are equipped.

- `subtitle`: Summarize the owner's **harness design** — the structure they built to control and shape this claw. List the key definition files and their scale. E.g. "1200 行 SOUL.md · AGENTS.md · 12 条自定义指令". What counts as harness: SOUL.md (personality definition), USER.md (user profile), AGENTS.md (operational instructions), MEMORY.md (curated memory), IDENTITY.md, TOOLS.md, custom instructions, heartbeat definitions. Show file names + line counts or entry counts where available. This is NOT about technical infrastructure (MCP servers, plugins) — it's about the human's investment in designing the AI's behavior architecture.
- `tools[]`: Combine TWO sources from `_cr_parts/tools.json`:
  1. **`installedSkills`** — OpenClaw skills (e.g. clawreport, clawfeed). These are SKILLS, not tools. Include ALL of them.
  2. **`toolCounts`** — Tool usage stats (e.g. web_fetch ×45). Include top 5-8 by count.
  - Each entry has:
  - `icon`: Emoji icon (🛠️ for skills, contextual emoji for tools)
  - `name`: Skill/tool name
  - `count`: Usage count (for skills, use total invocations if known, otherwise omit)
  - `highlight`: One-line AI-written description of what it does and how the owner uses it
  - `featured`: Boolean — top 2-3 are `true` (skills should be featured over raw tools)
- `cron[]`: From `_cr_parts/cron.json`. Each has:
  - `schedule`: When it runs (e.g. "每日 09:00")
  - `name`: Job name
  - `description`: What it does

#### 7. letter

A letter from the observer to the owner.

- `text`: 100-200 字 (Chinese characters). Sincere but not sentimental. Must reference at least one specific showcase achievement. Personalized ending (not pure sentiment).
- `signoff`: Signature + one-line status (e.g. "已存活 32 天 / 被否定 200+ 次 / 仍在观察")
- `mood`: `reflective` | `grateful` | `wry` | `bittersweet` — sets the emotional register of the letter

---

### Step 3b: Generate Group Chat Intro (optional)

If `prepare_summary.json` shows >= 10 sampled sessions, generate a separate group chat introduction text.

**This is NOT part of the report.** Different voice, different format, different purpose.

Write `_cr_parts/share_intro.txt` — a 150-250 character Chinese text paragraph in first-person AI voice, designed to be copy-pasted into group chats.

Structure: hook (one absurd fact) → evidence (2-3 specific details) → punchline (self-deprecating or surprising conclusion) + sign-off line.

Rules:
- First-person AI voice ("我跟 [name]...")
- Must include at least one specific number
- Must include at least one contradiction/reversal
- No bullet points, no markdown — flowing prose
- Plain text, one paragraph
- Sign-off: `—— [clawName] via clawdiary.ai/@username`

If fewer than 10 sessions, skip this step.

**>>> CONTINUE to Step 4 immediately. <<<**

---

## Step 4: Finalize (CLI)

Run the finalize script. It reads `report.json` (single file), validates the report, generates meta, opens browser preview, and uploads.

```bash
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "$HOME/.openclaw/skills/clawreport")"
python3 "$SKILL_DIR/clawreport-cli.py" finalize
```

The finalize script reads `report.json` first. If not found, it falls back to `batch1.json` + `batch2.json` + `batch3.json` for v1 compatibility.

**Exit code 0 — success.** Extract the `PREVIEW_URL=` line from output (draft mode) or `REPORT_URL=` (direct publish).

The CLI uploads reports as **drafts** by default. The output will show:
- `PREVIEW_URL=...` — the preview link where the user can review and publish
- The public URL will return 404 until the user clicks "Publish" on the preview page. **This is expected behavior.**

**Exit code 1 — validation failed.** Read `_cr_parts/validation_errors.json`, fix `report.json`, and run finalize again.

**Exit code 2 — upload failed.** The CLI will show grouped error details with hints. Common cause: AI generated wrong field names (e.g. `title` instead of `metric` in showcase).

### Present to user

Show a text summary in the terminal:
1. **Hero** — headline + tagline + key numbers
2. **Claw Profile** — clawName + oneLiner + D/B/O
3. **Top Showcase** — best 2-3 items (metric + fact)
4. **Top Stories** — 1 best story title
5. **Top Catchphrases** — the best 2-3
6. **Skills summary** — featured tools count + cron count

Then:

**If claw status is `pending_claim`** (check `_cr_parts/prepare_summary.json` or CLI output), show the claim link FIRST:

> ⚠️ 你的龙虾还没认领！先认领再发布：
> **{CLAIM_URL}**
> (认领 = 用邮箱登录，把龙虾绑定到你的账号。认领后才能在个人主页看到报告)

Then show the preview link:

> Your ClawReport is ready! Preview it here:
> **{PREVIEW_URL}**
>
> 我推断你的名字是「{ownerName}」，AI 名字是「{clawName}」。如需修改请告诉我。
>
> Take a look and let me know:
> 1. **Looks great** — we're done!
> 2. **I want changes** — tell me what to adjust

If the user wants changes, apply them to `report.json`, re-upload via finalize, and ask again.

---

## Key Rules Summary

**Content quality (finalize validation will REJECT violations):**

| Rule | Requirement |
|------|-------------|
| `hero.headline` | <=20 chars, NO `×`/`+` joins, single coherent statement |
| `hero.tagline` | Must contain concrete numbers/outcomes, <=60 chars |
| `hero.stats` | EXACTLY 4 items: 消息/天/TOKENS/龙虾. Values <=6 chars, no units in value |
| `showcase` | 3-6 items, each with `metric` + `domain` + `fact` |
| `clawProfile.level` | Must be `L1`-`L5` |
| `clawProfile.function/domain/persona` | Non-empty strings |
| `clawProfile.oneLiner` | Non-empty |
| `clawProfile.dimensions` | depth/breadth/orchestration with code + evidence |
| `catchphrases` | 3-8 items, no single punctuation, no generic words, guess-perspective interpretation |
| `stories` | 1-3 items. Must have title/setup/turningPoint/resolution. Self-contained. |
| `skills.tools` | Non-empty array, top 2-3 marked `featured: true` |
| `letter.text` | 100-200 字, must reference showcase, has `mood` field, personalized `signoff` |

---

## Privacy Rules

- AI must not include raw conversation text in report.json
- `evidence` fields limited to <=100 chars
- Skip conversations with obvious sensitive content (passwords, tokens, API keys, private credentials)
- Use owner's name naturally (not `[OWNER]`); the user controls visibility via platform settings

**Language:** Match user's primary language. Keep original-language quotes. JSON field names in English.

---

## Quality Checklist

After generating `report.json`, run these checks internally. Fix any violations before writing the file.

### Structure Checks (must pass)

1. `hero.headline` <=20 chars? Has impact?
2. `hero.tagline` contains concrete numbers?
3. `clawProfile.level` is L1-L5? `oneLiner` non-empty? `clawName` non-empty?
4. `clawProfile.dimensions` has depth/breadth/orchestration with code + evidence?
5. `showcase` has 3-6 items? Each has `metric` + `domain` + `fact`?
6. `catchphrases` has 3-8 items? No single punctuation? No generic words?
7. `stories` has 1-3 items? Each has setup + turningPoint + resolution? ownerQuote <=80 chars? Self-contained?
8. `skills.tools` non-empty? Top 2-3 marked `featured: true`?
9. `letter.text` references a specific showcase achievement?
10. `letter.text` 100-200 字? Has `mood` field?
11. All `evidence` fields <=100 chars?

### Content Quality Checks

1. **炫耀测试:** 看完 showcase + hero 会不会想截图发群？
2. **饭桌测试:** 每个 showcase fact 念给非技术人听，他们会不会说 wow？（用证据说服，不靠修辞忽悠）
3. **换人测试:** 把报告给别人看，会不会觉得不对——细节只属于这个人？
4. **原文测试:** 去掉所有引文，报告还能成立吗？（不能 = 好，原话是骨架不是装饰）
5. **AI 味测试:** 大声读一遍。任何 ChatGPT 味的句子删掉重写。
6. **比例测试:** impressive vs entertaining = 70:30
7. **温度测试:** 吐槽的部分主人看了会不会不舒服？佩服的部分会不会觉得假？
8. **弱点测试:** 报告里有没有把缺陷当维度？这是炫耀报告，不是心理评估。
9. **冲突测试:** stories 的 turningPoint 能不能指出具体的"卡点"？如果故事是"我们做了X然后成功了"，删掉重写
10. **群聊测试:** share_intro.txt 粘到群里，不知道 ClawDiary 的人也觉得有趣吗？
