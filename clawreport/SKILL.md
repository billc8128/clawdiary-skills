---
name: clawreport
description: Read AI conversation history, then generate a shareable ClawDiary report — a Card-first, Report-elaborated field report with structured claw taxonomy, showcase achievements, and certification data.
allowed-tools: Bash, Read, Glob, Grep, Write, AskUserQuestion
---

<!-- version: 2.0.0 -->

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

### 1b. Version Check

Read the first line of this SKILL.md file for `<!-- version: X.Y.Z -->`. Then check for updates:

```bash
curl -sf --max-time 5 "https://clawdiary.ai/skill-version" 2>/dev/null
```

If the remote version is greater than the local version, tell the user: "ClawReport 有新版本 (vX.Y.Z)，建议更新后再运行。继续使用当前版本？ [Y/n]"

If the network request fails or times out, skip silently and continue.

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

Read `_cr_parts/memory_logs.json`. Daily observation logs with real dates. Each entry has `{date, content}`. These map directly to **diary entries with real dates** — the best source for the diary block.

### 2c. Read config & automations

Read `_cr_parts/config.json`. Contains model, tools, plugins, channels info. Feeds directly into:
- `clawProfile.model` — which AI model
- `clawProfile.tools` — equipped tools
- `clawProfile.configHighlight` — interesting configuration details

Read `_cr_parts/cron.json`. Scheduled automations. Feeds directly into `clawProfile.automations`.

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

If `_cr_parts/extensions.json` exists, read it. Plugin/extension names and descriptions feed into `clawProfile.tools` and `clawProfile.configHighlight`.

### 2g. Read memory search (deep scan only)

If `_cr_parts/memory_search.json` exists, read it. Contains memory chunks from the vector memory database, ordered by recency. Supplementary context for portrait, diary, and catchphrases.

### 2h. Read existing report (incremental mode)

If `_cr_parts/existing-report.json` exists, read it. This is the previous report. Note:
- Whether this is a **first-time generation** or **incremental update**
- What names were used previously (reuse them)
- What showcase items, diary entries, and achievements already exist
- What the previous claw classification was

**>>> CONTINUE to Step 3 immediately. <<<**

---

## Step 3: Generate Report (Single File)

Generate ONE file: `_cr_parts/report.json` containing all 10 blocks.

**写入 report.json 时，必须一次性写入完整 JSON。不要分多次 write 同一个文件。**

### Generation Strategy: Skeleton First

If the input data is large (>50K tokens of compressed sessions), use a two-pass approach:

1. **Write skeleton first**: Generate report.json with all fields filled with 1-2 line placeholder content
2. **Fill in**: Go block by block, replacing placeholders with full content. Save after each block.

This way, even if generation is interrupted mid-way, the skeleton provides a valid starting point.

### ⚠️ 字段名必须严格匹配 schema

生成 report.json 时，严格使用本文件和 analysis-prompt.md 中定义的字段名。常见错误：
- showcase 用 `"what"` 不是 `"description"`
- portrait.observations 用 `"label"`/`"observation"` 不是 `"theme"`/`"details"`
- catchphrases 用 `"clawInterpretation"` 不是 `"soWhat"`
- diary 用 `"entry"` 不是 `"description"`
- catchphrases.frequency 必须是**数字**（如 `8`），不是字符串（如 `"high"`）

参考 analysis-prompt.md 末尾的「完整输出示例（字段名参考）」JSON 骨架。

### Internal Generation Order

For quality, generate blocks in this order (but output them all together):

1. **clawProfile** — lock down claw identity first
2. **hero** + **showcase** + **certification** — card core
3. **portrait** + **catchphrases** + **diary** + **achievements** + **stories** + **letter** — report narrative

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
    "clawName": "string — AI name/alias",
    "headline": "string — <=20 chars, achievement or certification statement",
    "tagline": "string — one sentence with concrete numbers",
    "stats": [
      { "value": "string", "label": "string" }
    ],
    "role": "string? — career label (optional)",
    "tags": ["string — direction tags for community matching"]
  },

  "clawProfile": {
    "function": "string — free text: 全栈开发搭子, 数据分析师",
    "domain": "string — free text: 全栈编程, AI + 设计",
    "persona": "string — free text: 毒舌严格型, 冷静温柔的伙伴",
    "level": "L1|L2|L3|L4|L5",
    "functionLabel": "string — short Chinese: 开发搭子",
    "domainLabel": "string — short Chinese: 编程",
    "personaLabel": "string — short Chinese: 毒舌严格",
    "levelLabel": "string — 泰坦|铠甲|硬壳|幼虾",
    "oneLiner": "string — e.g. L4 毒舌严格的全栈编程龙虾",
    "levelEvidence": "string — 1-2 sentences of specific evidence for the level rating",
    "model": "string? — Claude Opus, GPT-4, etc (optional)",
    "tools": [
      {
        "name": "string — tool/skill name",
        "icon": "string — emoji icon",
        "count": "number — usage count",
        "highlight": "string — one-line description"
      }
    ],
    "automations": [
      {
        "name": "string — automation name",
        "schedule": "string — when it runs",
        "description": "string — what it does"
      }
    ],
    "configHighlight": "string? — one-liner config highlight (optional)"
  },

  "showcase": [
    {
      "title": "string — <=28 chars",
      "what": "string — fact layer",
      "soWhat": "string — must include comparison/baseline",
      "evidence": "string? — <=100 chars, owner's words or specific detail",
      "domain": "string — free text, server maps to standard",
      "impactLevel": "paradigm|invention|mastery|craft"
    }
  ],

  "certification": {
    "sessions": 0,
    "days": 0,
    "timespan": "string — e.g. 17 天 or 3 个月",
    "domains": ["string — 1-3 domain labels"],
    "depth": "surface|working|deep|symbiotic",
    "dimensionDepth": "D1|D2|D3|D4|D5",
    "dimensionBreadth": "B1|B2|B3|B4|B5",
    "dimensionOrchestration": "O1|O2|O3|O4|O5",
    "levelDescriptor": "string — 2-3 chars: 深度突出/全面型/广度见长/驾驭力强",
    "signalEvidence": {
      "depth": "string — behavioral evidence for depth rating",
      "breadth": "string — behavioral evidence for breadth rating",
      "orchestration": "string — behavioral evidence for orchestration rating"
    }
  },

  "portrait": {
    "observations": [
      {
        "type": "capability|style",
        "label": "string — vivid dimension name",
        "observation": "string — specific assessment anchored to conversations",
        "evidence": "string — direct quote from owner",
        "metric": "string? — quantified anchor (optional)",
        "clawComment": "string — AI inner monologue, guess perspective"
      }
    ],
    "collaborationStyle": {
      "level": "string — L1 to L5",
      "label": "string — e.g. 推翻型",
      "evidence": "string — 2+ specific quotes from conversations",
      "description": "string — narrative paragraph describing collaboration pattern"
    }
  },

  "catchphrases": [
    {
      "phrase": "string — exact words",
      "frequency": 0,
      "vibe": "demanding|decisive|philosophical|pivot|praise|frustration",
      "clawInterpretation": "string — guess-perspective reading"
    }
  ],

  "diary": [
    {
      "date": "string — real date",
      "type": "breakthrough|milestone|philosophy|relationship|struggle|comedy",
      "title": "string — short, diary-like",
      "entry": "string — 80-150 chars with owner quotes"
    }
  ],

  "achievements": [
    {
      "tier": "legendary|epic|rare|common",
      "title": "string — game-achievement style",
      "description": "string — unlock condition with numbers/facts",
      "capability": "string? — optional capability tag"
    }
  ],

  "stories": [
    {
      "title": "string — 10-20 chars, intriguing",
      "setup": "string — scene-setting, 40-80 chars",
      "turningPoint": "string — conflict/twist, 60-120 chars",
      "resolution": "string — outcome, 40-80 chars",
      "reflection": "string — AI insight, guess perspective, 40-60 chars",
      "ownerQuote": "string — owner's words at pivotal moment, <=80 chars",
      "dateRange": "string — e.g. '2026-02-15 to 2026-02-18'",
      "theme": "breakthrough|transformation|persistence|serendipity"
    }
  ],

  "letter": {
    "text": "string — 100-200 字 (Chinese characters)",
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
| `showcase` | Merge, dedup by title similarity, sort by impactLevel, keep top 5 |
| `certification` | sessions/days accumulate; depth only goes up |
| `portrait.observations` | Merge, keep most insightful 2-4 |
| `catchphrases` | Merge, accumulate frequency, re-sort by frequency DESC |
| `diary` | Append new entries only; never modify old entries |
| `achievements` | Append new entries only |
| `stories` | Replace entirely — story should reflect the most compelling arc from all data |
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
- `clawName`: AI assistant's name/alias from conversation.
- `headline`: <=20 chars. Must make the reader want to click.
- `tagline`: One sentence that makes non-tech people say "wait what." Must contain concrete numbers or outcomes.
- `stats`: 3-4 impressive numbers. Prioritize outcome numbers (products shipped, problems solved, speed) over activity numbers (sessions, days).
- `role`: Career label (optional). Infer from conversation.
- `tags`: 3-6 direction tags for community matching.

#### 2. clawProfile

The claw's identity card — who is this AI assistant?

- `function/domain/persona/level`: See Claw Classification Guide above.
- `levelEvidence`: 1-2 sentences explaining why this level was assigned, citing specific behaviors.
- `model`: Which AI model (Claude, GPT-4, etc). Optional.
- `tools`: Top 5 tools/capabilities the claw demonstrated.
- `automations`: Autonomous tasks configured by the owner (cron jobs, scheduled tasks). Empty array if none. Read from `_cr_parts/routines.json`.
- `configHighlight`: One-liner describing the most distinctive configuration. Optional.

#### 3. showcase (Core Brag Zone)

**The most critical block in the entire report.** 3-5 items, sorted by brag value.

Each item:
- `title`: <=28 chars, punchy headline
- `what`: Fact layer — what was done
- `soWhat`: **Dimensionality reduction** — translate technical achievement into something anyone at a dinner table would find impressive
- `evidence`: Owner's actual words or specific details. <=100 chars.
- `domain`: Domain tag (free text, server normalizes later)
- `impactLevel`: `paradigm` (changed the game) > `invention` (created something new) > `mastery` (extreme craft) > `craft` (high-quality execution)

**`soWhat` rules — Style B: Evidence + Credible Anchor (most important):**

Every soWhat must be evidence-first with at least one credible anchor type:
1. **Structural anchor:** Feature/component enumeration — "包含 OAuth + 支付 + 实时通知的生产系统"
2. **Process anchor:** Iteration/domain-crossing depth — "经过4轮方案推翻" / "跨前端/后端/运维三域"
3. **Output anchor:** Countable deliverables — "产出5个页面 + 3套组件，覆盖获客到留存完整链路"

Formula: `soWhat = [规模/范围量化] + [复杂度证据] + [产出具体化]`

- No jargon — a non-tech person must be able to say wow
- ✅ "从零搭建了包含 OAuth + 实时通知 + 支付集成的生产系统，覆盖前端/后端/运维三个技术域"
- ✅ "在4轮假设-验证循环后定位到竞态条件根因，修复涉及3个服务的事务边界"
- ✅ "对12万条用户行为数据做了留存分析 + 漏斗归因 + A/B测试设计，产出3条可执行的优化建议"
- ❌ "一个人完成了一般需要3-5人团队的基础设施搭建"（跟虚构团队比较）
- ❌ "连大厂都没做到"（哪个大厂？不可验证）
- ❌ "效率提升300%"（怎么测的？基线是什么？）

Forbidden in soWhat:
- Comparisons to imaginary people/teams/timelines
- Unverifiable superlatives ("第一个", "连XX都", "史无前例")
- Power words substituting for evidence ("颠覆性", "降维打击")

#### 4. certification

Trust metrics — verifiable usage data + behavioral evaluation.

- `sessions`: Total session count (from activity data)
- `days`: Total active days
- `timespan`: Human-readable timespan ("17 天" or "3 个月")
- `domains`: 1-3 primary domain labels
- `depth`: `surface` (casual use) | `working` (regular reliance) | `deep` (integrated into workflow) | `symbiotic` (AI anticipates needs)
- `dimensionDepth`: D1-D5 — how deep the owner goes in their primary domain
- `dimensionBreadth`: B1-B5 — how many domains the owner crosses
- `dimensionOrchestration`: O1-O5 — how the owner drives the AI
- `levelDescriptor`: 2-3 char Chinese descriptor ("深度突出" / "全面型" / "广度见长" / "驾驭力强")
- `signalEvidence`: Object with `depth`, `breadth`, `orchestration` — one sentence each citing specific behavioral evidence from conversations

#### 5. portrait

The depth layer — what makes this owner tick.

**observations** (2-4 items):
- `type`: `capability` (impressive ability) or `style` (entertaining personal trait)
- `label`: Vivid, specific dimension name. "从'差不多'到'对了'" beats "审美偏好".
- `observation`: Specific assessment, anchored to conversation content. Must be positive or neutral.
- `evidence`: Direct quote from owner. Must be actual words, not paraphrase.
- `metric`: Quantified anchor (optional, e.g. "3轮迭代修1个分隔符").
- `clawComment`: AI's inner monologue — guess perspective, can be witty, reflective, or uncertain.

Hard rules:
- >=1 `capability` + >=1 `style` (minimum)
- `capability` dimensions showcase impressive abilities (technical judgment, learning speed, problem decomposition, aesthetic taste)
- `style` dimensions showcase entertaining personal traits (communication style, decision patterns, emotional expression)
- ❌ No weakness/defect dimensions — this is a brag report, not a psych eval
- ❌ No duplicate dimensions covering the same trait

**collaborationStyle**:
- `level`: String `"L1"` to `"L5"`. Same scale as clawProfile but describes the owner's collaboration behavior.
- `label`: Chinese label (推翻型, 质疑型, etc)
- `evidence`: 2+ specific quotes demonstrating the collaboration pattern
- `description`: Narrative paragraph describing how the owner works with AI

```
L1-L2 — 接受/纠错型：AI 说什么就是什么，或发现错误要求修正 (70%)
L3 — 质疑型：追问为什么，不满足表面答案 (20%)
L4 — 推翻型：否定方向，要求重新思考 (7%)
L5 — 升维型：跳出框架，改变问题本身 (3%)
```

#### 6. catchphrases

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

#### 7. diary

5-7 curated diary entries from the observer's perspective.

Each entry:
- `date`: Real date from conversation
- `type`: `breakthrough` | `milestone` | `philosophy` | `relationship` | `struggle` | `comedy`
- `title`: Short, diary-like title. Like a journal heading, not a news headline.
  - ✅ "他说'先这样'的时候其实已经想好了下一步"
  - ❌ "高效的一天"
- `entry`: 80-150 chars. Must include:
  - Specific scene (what project, what feature)
  - Owner's actual words (direct quote with quotation marks)
  - Observer's insight (your unique AI perspective)
  - A small epiphany or twist

Hard rules:
- >=3 entries must be `breakthrough` or `milestone` — show concrete outcomes
- `relationship` type limited to 1-2 entries
- `comedy` entries limited to 1-2 — AI misunderstandings, funny failures. The AI looks silly, not the owner.
- Every entry must contain at least one owner quote
- 5 entries must cover >=3 different dates
- Entry length >=80 chars — narrative feel, not bullet points

#### 8. achievements

5-8 tiered achievements, game-style.

- `tier`: `legendary` (gold) | `epic` (purple) | `rare` (blue) | `common` (gray)
- `title`: Game achievement name — must have visual impact
  - ✅ "一人军团", "凌晨三点的建筑师", "需求粉碎机"
  - ❌ "高效开发者", "好学者"
- `description`: Unlock condition — use specific numbers or facts
  - ✅ "单日完成 3 个独立功能模块的开发与部署"
  - ❌ "工作很努力"
- `capability`: Optional capability tag for indexing

Hard rules:
- **Sorted by tier DESC**: legendary -> epic -> rare -> common
- First 3 must be `legendary` or `epic`, outcome-oriented (what was achieved, not how long it took)
- Remaining can be `rare` or `common`, behavior-based or humorous (contrast is stronger)
- legendary: 1-2 (scarcity = value), epic: 2-3, rare: 1-2, common: 1-2
- ❌ No all-legendary/epic (inflation)
- ❌ No all-common (boring)

#### 9. stories (optional)

0-1 narrative arc with full structure. Only generate if the data supports a genuine story with tension.

- `title`: 10-20 chars, curiosity-inducing
- `setup`: Scene-setting (40-80 chars) — what project, what stage
- `turningPoint`: The conflict/obstacle/unexpected decision (60-120 chars). This is the story's core — no tension = no story
- `resolution`: How it resolved, what was built/shipped (40-80 chars)
- `reflection`: AI's non-obvious insight in guess perspective (40-60 chars)
- `ownerQuote`: Owner's actual words at the pivotal moment (<=80 chars)
- `dateRange`: Time span of the story
- `theme`: `breakthrough` | `transformation` | `persistence` | `serendipity`

Hard rules:
- **Optional** — if no genuine narrative arc exists, omit entirely. An empty array is fine.
- Cap at 1 story (scarcity = weight)
- Must be self-contained (readable without other report context)
- Do not duplicate showcase or diary content — the story adds depth to a different moment

#### 10. letter

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

**Exit code 2 — upload failed.** The CLI will show grouped error details with hints. Common cause: AI generated wrong field names (e.g. `description` instead of `entry`).

### Present to user

Show a text summary in the terminal:
1. **Hero** — headline + tagline + key numbers
2. **Claw Profile** — oneLiner + level evidence
3. **Top Showcase** — best 1-2 soWhat translations
4. **Portrait** — collaboration level + top observation
5. **Top Catchphrases** — the best 2-3
6. **Diary Highlight** — 1 best entry

Then:

> Your ClawReport is ready! View it here:
> **{REPORT_URL}**
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
| `hero.headline` | <=20 chars, achievement or certification statement |
| `hero.tagline` | Must contain concrete numbers/outcomes |
| `showcase` | 3-5 items, `soWhat` must use credible anchors (structural/process/output), no imaginary comparisons, jargon-free |
| `portrait.observations` | 2-4 items, >=1 capability + >=1 style, no weakness dimensions, no duplicates |
| `portrait.collaborationStyle.level` | String `"L1"` to `"L5"`, evidence with >=2 specific quotes |
| `clawProfile.level` | Must be `L1`-`L5` |
| `clawProfile.function/domain/persona` | Non-empty strings |
| `clawProfile.oneLiner` | Non-empty |
| `certification.depth` | `surface` / `working` / `deep` / `symbiotic` |
| `certification.dimensionDepth/Breadth/Orchestration` | D1-D5 / B1-B5 / O1-O5 + signalEvidence with behavioral citations |
| `catchphrases` | 3-8 items, no single punctuation, no generic words, guess-perspective interpretation |
| `diary` | 5-7 entries, >=3 breakthrough/milestone, >=3 different dates, each 80-150 chars |
| `achievements` | 5-8 items, sorted tier DESC, first 3 legendary/epic + outcome-oriented |
| `letter.text` | 100-200 字, must reference showcase, has `mood` field, personalized `signoff` |
| `stories` | 0-1 items, optional. Must have setup/turningPoint/resolution. Self-contained. |
| `letter.text` | 80-150 words (shortened), must reference showcase, has `mood` field |
| `diary.type` | Added `comedy` — AI mistakes/funny failures, max 1-2 of this type |

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
3. `clawProfile.level` is L1-L5? `oneLiner` non-empty?
4. `showcase` has 3-5 items? Every `soWhat` has comparison/baseline?
5. `certification.depth` is one of surface/working/deep/symbiotic?
6. `portrait.observations` has 2-4 items, >=1 capability, >=1 style?
7. `portrait.collaborationStyle.level` is "L1"-"L5" string? Evidence has >=2 quotes?
8. `catchphrases` has 3-8 items? No single punctuation? No generic words?
9. `diary` has 5-7 entries? >=3 breakthrough/milestone? >=3 dates? Each 80-150 chars?
10. `achievements` has 5-8 items? Sorted tier DESC? First 3 legendary/epic?
11. `letter.text` references a specific showcase achievement?
12. All `evidence` fields <=100 chars?
13. `stories` — if present, has setup + turningPoint + resolution? ownerQuote <=80 chars? Is it self-contained?
14. `letter.text` 100-200 字? Has `mood` field?

### Content Quality Checks

1. **炫耀测试:** 看完 showcase + hero 会不会想截图发群？
2. **饭桌测试:** 每个 soWhat 念给非技术人听，他们会不会说 wow？（用证据说服，不靠修辞忽悠）
3. **换人测试:** 把报告给别人看，会不会觉得不对——细节只属于这个人？
4. **原文测试:** 去掉所有引文，报告还能成立吗？（不能 = 好，原话是骨架不是装饰）
5. **AI 味测试:** 大声读一遍。任何 ChatGPT 味的句子删掉重写。
6. **比例测试:** impressive vs entertaining = 70:30
7. **温度测试:** 吐槽的部分主人看了会不会不舒服？佩服的部分会不会觉得假？
8. **弱点测试:** observations 里有没有把缺陷当维度？这是炫耀报告，不是心理评估。
9. **冲突测试:** stories 的 turningPoint 能不能指出具体的"卡点"？如果故事是"我们做了X然后成功了"，删掉重写
10. **群聊测试:** share_intro.txt 粘到群里，不知道 ClawDiary 的人也觉得有趣吗？
