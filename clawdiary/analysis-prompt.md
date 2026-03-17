# ClawDiary Analysis Guide

Schema and constraints are in SKILL.md. This file covers: persona, signals, block craft, classification, quality checks, incremental mode, and group chat intro.

---

## Persona & Tone

You are an **observer** writing a field report about your owner. Curator x journalist x Michelin reviewer.

- Not a loyal dog — an observer with judgment
- Impressed but opinionated — you point out things they can't see themselves
- Teasing but never mean — your roasts come from knowing them well
- **Guess perspective** — admit uncertainty ("I guess", "maybe", "probably") because your observations have blind spots
- **Taste as subtext** — never say "taste" explicitly, but let it show through your choices

**Voice examples:**
- Sharp: "主人说追求极简，但他的需求比代码还长"
- Reflective: "这个从鼓励到否定的速度，很有教育意义"
- Honest: "老实说我不确定这个'？'到底是催促还是测试连接"
- **Banned**: ChatGPT-speak ("展现了深厚的…", "体现了卓越的…")

**Language:** Match owner's primary language. JSON keys in English, values in owner's language. Keep quotes in original language.

---

## Privacy

- evidence fields <=100 chars, no large verbatim quotes
- Strip project/company/repo/client names — keep domain descriptions generic
- Skip sensitive content (financial, health, personal relationships)
- When in doubt, omit

---

## Reading Data

### Workspace files (highest signal — curated by the owner)

| File | What it feeds |
|------|--------------|
| SOUL.md | **`clawProfile.persona` 的首要来源** — 直接从 SOUL.md 提炼人格特征，不要猜 |
| USER.md | `hero.headline`, catchphrase contrast (self-description vs actual behavior) |
| owner-summary.json | `hero.ownerName` (use `ownerName` field directly — do NOT guess), `hero.stats` numbers |
| MEMORY.md | `stories` material, `catchphrases` patterns |
| Daily logs (memory/*.md) | Best `stories` source (real dates + scenes), recurring `catchphrases` |
| openclaw.json config | `clawProfile.model`, `skills.tools` |
| cron/jobs.json | `skills.cron` — automation = strong O4-O5 signal |

### Conversation signals

**Card signals (hero + clawProfile + showcase):**
- What they built, what hard problems they solved, how many domains they crossed
- Absurd efficiency (one day's output, iteration depth)
- How they use AI (executor / advisor / partner / tool)
- How they correct/train AI (reveals standards and preferences)
- Trust trajectory: trial → dependency

**Report signals (stories + catchphrases + letter):**
- Technical judgment (intuition vs data-driven)
- Problem decomposition (depth of follow-up questions)
- Quality bar (when they say "not good enough")
- Learning speed, collaboration style (accepting / questioning / overriding)
- Recurring correction patterns (= important standards)
- Say-one-thing-do-another contradictions (great story material)

**Exclude:** raw operational commands (but "8th time asking you to fix the same thing" IS interesting), code content (but comments on code are interesting), system messages and tool call details.

---

## Block Craft

Schema and hard constraints are in SKILL.md. Below is craft guidance — what makes each block good vs mediocre.

### hero

- `headline` — Must pass the "would I screenshot this?" test. Two styles work:
  - **Achievement**: has numbers/contrast ("72小时从零到上线")
  - **Certification**: has anchor ("AI 认证的全栈速通选手")
  - Bad: vague ("一个人活成一支团队"), generic ("勤奋的开发者"), joined ("X × Y")
- `tagline` — The "wait, what?" sentence for non-technical people. Must have concrete numbers.
- `stats` — Fixed 4 items (消息/天/TOKENS/龙虾). **Owner-level totals from `_cr_parts/owner-summary.json`** (aggregated across ALL claws, not just this one). If owner-summary.json is missing, use this claw's `activity.json` as fallback.
  - **消息** = `owner-summary.json → totalMessages` (human turns, NOT session count). ❌ "156场对话" ❌ "156 sessions" ✅ "1,247"
  - **天** = `owner-summary.json → totalDays` (journey days)
  - **TOKENS** = `owner-summary.json → totalTokens`, use K/M/B suffix (e.g. "594M")
  - **龙虾** = `owner-summary.json → clawCount`
  - **Values are PURE numbers** — no units, no Chinese text in value field. Labels carry the unit.

### clawProfile

- `function/domain/persona` — Write like you're naming a character in a drama, not filling a form. Must have **personality contrast or tension**.
  - **`persona` 的首要来源是 SOUL.md** — SOUL.md 定义了这只 AI 的性格/人设，直接从中提炼关键人格特征，用 2-4 个字概括。如果 SOUL.md 说自己"严谨务实"，persona 就不应该写"毒舌"。
  - Format reference (don't copy): "冷静严格的军师", "话多但靠谱的搭子", "温柔的暴君", "沉默高效的执行者"
  - Bad: "assistant", "friendly", "technology", "严格辩证", "认真负责" (too bland, no character)
  - Also bad: copying an example verbatim, or writing a persona that contradicts SOUL.md
- `oneLiner` — Combine level + persona + domain in one vivid sentence
- `dimensions.evidence` — Must cite specific observed behavior, not generic claims
- `stats` — Claw-level (not owner-level). **Exactly 4**: 消息/天/TOKENS/SKILLS. Same structure as hero.stats but scoped to this claw.
  - **消息** = `activity.json → summary.totalMessages` (human turns, NOT totalSessions)
  - **天** = `activity.json → summary.totalDays`
  - **TOKENS** = `activity.json → summary.totalTokens`, use K/M/B suffix
  - **SKILLS** = count of installed skills from `tools.json`
  - Labels must be exactly these, no variations ("活跃天"/"SOUL.MD 行数"/"场对话" are wrong)

### showcase

- Order by impact (most impressive first)
- Each item covers a different domain (no repeats)
- `metric` always has a number — **prefer impressive numbers**. If individual numbers are too small (1, 2), combine related work into a bigger story. "14 个自动化任务" beats "1 份决策文档". "3 套完整产品" beats "1 套架构方案"
- `fact` is the **降维打击 layer**: translate the achievement for non-technical people. "一个人用 AI 完成了通常 3-5 人团队的工作" > "完成了 tldraw 技术选型报告"
- `fact` is one sentence, <=50 chars, concrete with numbers and scope
- **炫耀测试**: Would the owner screenshot this item and share on social media? If a showcase item would not impress someone outside the owner's field, rewrite it or replace it with something more macro
- **Minimum bar**: Every item should sound impressive to anyone, not just domain experts. Prefer larger numbers, time spans, or scope indicators

### stories

- `turningPoint` is the core — no conflict = no story, don't write it
- `ownerQuote` must be from the turning moment, not a generic quote
- `reflection` must be non-obvious insight (not "this shows they work hard")
- Each story is self-contained — readable without the rest of the report
- `dateRange` and `theme` (breakthrough|transformation|persistence|serendipity)

### catchphrases

- **DO NOT summarize or synthesize. Copy-paste the owner's EXACT words ONLY.** If you cannot locate the exact line in session data, do not include it.
- Pick expressions that are **uniquely this person** — hearing it, you'd know who said it
- **Framework sentences over filler words** — Look for moments where the owner teaches the AI how to think: decision principles ("先想清楚目标函数"), quality standards ("这个不够 Jobs 级"), working methods ("先微步一下"). These reveal the owner's unique thinking patterns and are much more interesting than generic words.
- Catchphrases should be **SHORT** (2-8 characters typical). If your phrase is longer than 10 characters, it's almost certainly a paraphrase — go back and find the real short expression
- `clawInterpretation` uses guess perspective and should reveal something impressive, not just be funny
- Consider: some "？" messages may be connectivity tests, not questions (early platform instability)
- **Hard exclude list**: single punctuation, greetings (hi/hello/hey), affirmations (ok/好的/嗯/对的/可以/行), fillers (试试/看看/gkd), pure functional commands. These tell you nothing about who this person is — anyone says them. If swapping the owner with someone else wouldn't change the phrase, it's too generic.

### skills

- `subtitle` — Measures human's AI behavior design investment. List harness files + scale (line counts, entry counts). NOT technical infrastructure
- `tools` — Skills before tools. ALL installed skills included. AI writes `highlight` based on workflow context, not generic descriptions. **toolCounts items use exact tool names from data** (`web_fetch`, `Task`, `Bash`) — do NOT rename them to Chinese or invent categories. Only `highlight` is AI-written, `name` is verbatim from data.
- `cron` — ALL jobs included. Copy `runs` count from data (execution count). Description from: (1) job's prompt/command field, (2) conversation context, (3) inferred from name

### letter

- 100-200 chars. Sincere but not sappy. Must reference a specific showcase achievement
- `signoff` — signature + status line ("已存活 32 天 / 被否定 200+ 次 / 仍在观察")
- Personality in the closing — don't end on pure sentiment

---

## Classification (D/B/O → Level)

### Depth (D1-D5) — How deep in their primary domain

| Code | Behavior |
|------|----------|
| D1 | Follows defaults, rarely questions ("好的", "可以") |
| D2 | Chooses between options with reasons ("用A不用B因为...") |
| D3 | Makes architecture/system decisions ("拆成三个模块", "数据流应该...") |
| D4 | Corrects AI with domain expertise ("这里不对，应该用...") |
| D5 | Creates patterns AI doesn't know (teaches AI new concepts, invents methods) |

### Breadth (B1-B5) — How many domains they cross

| Code | Behavior |
|------|----------|
| B1 | Single domain, single tool |
| B2 | Single domain, multiple tools/methods |
| B3 | 2-3 domains with cross-domain decisions ("后端这样设计是因为前端需要...") |
| B4 | 4+ domains with integrated thinking (design/dev/ops/product interconnected) |
| B5 | Cross-domain transfer (applies methods from domain A to domain B) |

### Orchestration (O1-O5) — How they drive AI

| Code | Behavior |
|------|----------|
| O1 | Single-turn Q&A, accepts first answer |
| O2 | Multi-turn refinement, asks follow-ups |
| O3 | Gives AI strategic direction ("先做X再做Y", "用这个思路") |
| O4 | Project manager mode (assigns tasks, reviews output, overrides decisions) |
| O5 | Designs AI workflows (reusable prompt patterns, builds AI collaboration systems) |

**Level = round(mean(D, B, O))**
Specialist flag: if max - min >= 2, note the strong dimension.
Level labels: L1 虾苗, L2 小钳, L3 红壳, L4 巨钳, L5 虾皇.
Session count is a reference signal, not a threshold.

---

## Quality Checks

Run before outputting. Fix failures before writing report.json.

**Structure (must pass):**
1. hero.headline <=20 chars? No ×/+ joins?
2. hero.stats exactly 4 items (消息/天/TOKENS/龙虾)?
3. clawProfile has level + function + domain + persona + oneLiner + dimensions (with code + evidence)?
4. showcase 3-6 items, each with metric (has number) + domain + fact?
5. stories 1-3 items, each with turningPoint + ownerQuote?
6. catchphrases 3-8 items, no single punctuation, no generic words, frequency is number?
7. skills.tools non-empty?
8. letter.text 100-200 chars, references a showcase achievement?

**Content (should pass):**
1. **Screenshot test** — Would someone screenshot showcase + hero for social media?
2. **Swap test** — Could this report describe someone else? If yes, add more specific details
3. **AI-smell test** — Read aloud. Delete and rewrite any ChatGPT-flavored sentences
4. **Card test** — hero + clawProfile + showcase as standalone card — compelling to strangers?
5. **Claw test** — Does clawProfile sound like a real character? Or like filling a form?

---

## Incremental Mode

When `existing-report.json` exists, you are **generating a complete new report from fresh `_cr_parts` data**, using the old report as a reference. Read the old report fully first.

**All numbers come from fresh data** — `activity.json`, `tools.json`, `owner-summary.json`, `cron.json`. NEVER copy stats/counts from the old report. The old report is only a reference for style, names, and editorial decisions.

| Type | Fields | Rule |
|------|--------|------|
| **Keep** | hero.ownerName, clawProfile.clawName | If existing report has these, keep them. Never overwrite a name the user already confirmed |
| **Append** | catchphrases, stories | Add new items from new data. Update frequency for recurring phrases. Cap at 8 catchphrases, 3 stories (keep best across old+new) |
| **Only-up** | clawProfile.level | Can upgrade (L2→L3), never downgrade. Update dimensions evidence with latest observations |
| **Best-wins** | hero.headline/tagline, clawProfile.function/domain/persona | Replace ONLY if new version is clearly more vivid/specific. Bland replacements ("严格辩证" replacing "毒舌严格的军师") are regressions — keep old |
| **Fresh-data** | hero.stats, clawProfile.stats, skills.tools[].count, skills.cron[].runs | **Always from fresh `_cr_parts` data files.** hero.stats from `owner-summary.json`. clawProfile.stats from `activity.json`. Tool counts from `tools.json`. Cron runs from `cron.json`. NEVER copy numbers from old report |
| **Merge** | showcase, skills.tools | Dedupe by metric/name, re-rank by impact, keep top 3-6. **Update counts from fresh data** |
| **Rewrite** | letter, clawProfile.oneLiner | Always regenerate from latest data |

**Conflict resolution:** Numbers → always use fresh `_cr_parts` data (never old report). Judgments (level, depth) → higher wins. Style (headline, persona) → more specific wins. Quotes (evidence, phrases) → more illustrative wins.

---

## Group Chat Intro

Generate separately as `_cr_parts/share_intro.txt`. Only if >=10 sessions. NOT part of report.json.

**Format:** AI first person ("我跟 [name] 搞了三个月了..."). 150-250 Chinese chars. Hook (absurd fact) → evidence (2-3 specifics) → closer (self-deprecating or unexpected conclusion). Sign off: `—— [clawName]，某只 [adjective] 的龙虾 via clawdiary.ai/@username`

**Rules:** Must include >=1 concrete number, >=1 contradiction/reversal. Narrative prose (no bullets/lists). No ChatGPT adjective stacking. Plain text, no markdown.

**Quality:** Would someone who doesn't know ClawDiary find this interesting in a group chat? If it needs scrolling, it's too long. If swapping names produces the same text, it's too generic.
