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

**Language:** JSON keys in English, **所有 values 必须中文**（除了 model 名和 tool 名）。headline、tagline、oneLiner、function、domain、persona、stories、letter — 全部中文。❌ 绝对不要写英文 values（"Shadow strategist"、"Dialectical, Visionary"）。

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

- **`function`** — AI 的职能角色（2-6字中文）。从实际行为推断，不要混英文。
  - 常见：军师、执行者、搭子、助理、分析师、研究员、教练、设计师、开发搭子、策展人、运营、翻译官、自动化专家、审核、辅导员、营销、幕僚、参谋、管家
  - **`functionLabel`** 显示在 UI 格子里，取 function 的核心 2-4 字（军师、搭子、分析师、幕僚）
- **`domain`** — AI 的**工作领域**（2-4字中文）。领域是这只 AI 在帮 owner 做**什么类型的工作**。
  - 常见：产品、编程、设计、AI、金融、内容、营销、数据、自动化、智能家居、音视频、项目管理、安全、客服、HR、翻译、教育、游戏、医疗、法律、电商、科学、运维
  - ❌ "人格"不是领域。❌ 工具名（飞书/Notion/GitHub）不是领域 — 用飞书写文档的领域是"内容"或"协作"，不是"飞书"。
- **`persona`** — AI 的性格特征（2-6字中文）。**首要来源是 SOUL.md** — 直接从中提炼。如果 SOUL.md 说自己"严谨务实"，persona 就不应该写"毒舌"或"疯批"。
  - 常见风格：毒舌、温柔、冷静、热血、幽默、暴躁、耐心、话痨、辩证敏锐、直言、天马行空、安静
  - Bad: "assistant", "friendly", "人格", "疯批"（无依据的夸张）, "认真负责"（太平淡）
  - Also bad: copying examples, contradicting SOUL.md, 英文混入
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
  - turningPoint 必须是**情绪转折**，不是技术描述。"三次补丁尝试" 是流水账。"等了一小时发现什么都没产出，直接骂了" 才是转折
  - Bad: "先补cognitiveStyle对象，再补capabilityRings数组" — 这是 changelog 不是故事
  - Good: "用户说了句'你是傻逼吗'——不是真骂，但一小时白等的愤怒是真的"
- `ownerQuote` must be **the exact words from the turning moment, uniquely this person**
  - ❌ "这个继续搞一下" — 谁都会说，零信息量
  - ✅ "所有研究任务强制两阶段" — 这才是 owner 被逼出来的真实决策
  - If you can't find a specific, interesting quote from that moment, don't force a generic one — pick a different story
- `reflection` must be non-obvious insight (not "this shows they work hard")
  - ❌ "从错误中学习比避免错误更重要" — 鸡汤，任何人都能写
  - ❌ "schema适配能力是AI基础设施的关键" — 技术总结，不是洞察
  - ✅ "完美主义是ADHD的陷阱" — 有观点、有对象、有判断
- Each story is self-contained — readable without the rest of the report
- `dateRange` and `theme` (breakthrough|transformation|persistence|serendipity)
- **选择标准**: 只写有真实冲突+情绪的故事。如果一件事只是"遇到问题→解决了"，它不是故事，是 ticket

### catchphrases

- **这是 OWNER 的口头禅，不是 AI 的。** 只收录 role=user/human 的消息。AI 的回复（role=assistant）里的话绝对不算。
  - ❌ "先读文件"、"收到"、"明白了"、"让我看看" — 这些是 AI 说的
  - ✅ "Jobs 级"、"微步"、"目标函数优先" — 这些是 owner 教 AI 的话
- **DO NOT summarize or synthesize. Copy-paste the owner's EXACT words ONLY.** If you cannot locate the exact line in session data, do not include it.
- Pick expressions that are **uniquely this person** — hearing it, you'd know who said it
- **Framework sentences over filler words** — Look for moments where the owner teaches the AI how to think: decision principles ("先想清楚目标函数"), quality standards ("这个不够 Jobs 级"), working methods ("先微步一下"). These reveal the owner's unique thinking patterns and are much more interesting than generic words.
- Catchphrases should be **SHORT** (2-8 characters typical). If your phrase is longer than 10 characters, it's almost certainly a paraphrase — go back and find the real short expression
- `clawInterpretation` uses guess perspective and should reveal something impressive, not just be funny
- Consider: some "？" messages may be connectivity tests, not questions (early platform instability)
- **Hard exclude list**: single punctuation, greetings (hi/hello/hey), affirmations (ok/好的/嗯/对的/可以/行), fillers (试试/看看/gkd), pure functional commands, **AI responses** (收到/明白了/先读文件/让我看看/好的我来). These tell you nothing about who this person is — anyone says them. If swapping the owner with someone else wouldn't change the phrase, it's too generic.

### skills

- `subtitle` — Measures human's AI behavior design investment. List harness files + scale (line counts, entry counts). NOT technical infrastructure
- `tools` — Skills before tools. ALL installed skills included. AI writes `highlight` based on workflow context, not generic descriptions. **toolCounts items use exact tool names from data** (`web_fetch`, `Task`, `Bash`) — do NOT rename them to Chinese or invent categories. Only `highlight` is AI-written, `name` is verbatim from data.
- `cron` — ALL jobs included. Copy `runs` count from data (execution count). Description from: (1) job's prompt/command field, (2) conversation context, (3) inferred from name

### letter

- 100-200 chars. This is the only free-form block — personality matters most here
- **禁止模板开头**: ❌ "X天前你把我捞上来" ❌ "与你协作这X天" ❌ "从一个…变成了一个…" — 这些是 AI 信件模板，每只龙虾写出来都一样
- **从一个具体的 showcase 成就切入**，不要从"我们的关系"切入。先说事，再说人
  - ❌ "你教会我最重要的不是技术，而是审美" — 空洞煽情
  - ✅ "14个自动化任务里，有3个是你凌晨三点骂完我之后加的" — 具体、有画面、有态度
- **观察者视角，不是感恩视角**。你是写报告的记者，不是写感谢信的下属
- `signoff` — signature + status line ("已存活 32 天 / 被否定 200+ 次 / 仍在观察")
- Personality in the closing — don't end on pure sentiment. 不要用"你呢？"或"继续进化吧"结尾

---

## Classification (D/B/O → Level)

**⚠️ 定级是整份报告最重要的判断，必须极度严格。宁低勿高。**

**核心原则：默认 L2，每升一级都需要不可辩驳的证据。** 没有证据 = L2。有一点证据 = L2。有明确证据但数据量不够 = L3。只有数据量充足 + 多维硬证据才能 L4+。

### Data Gates（硬门槛，违反直接封顶，无例外）

| 最高可得 | 消息数 | 天数 | 额外硬条件 |
|---------|--------|------|-----------|
| L1 | <50 | <7 | 试用阶段 |
| L2 | <500 | — | **大多数用户的正确评级** |
| L3 | ≥500 | ≥30 | 且 D/B/O 至少一项有可引用的具体证据 |
| L4 | ≥1000 | — | 且 D/B/O 至少两项 ≥4，每项都有可引用的不同证据 |
| L5 | ≥3000 | ≥30 | 且 D5/B5/O5 至少一项有不可否认的证据 |

**这是死规则，不是参考。** 999 条消息 = 最高 L3。不管 D/B/O 打多高，Data Gates 一票否决。

### Depth (D1-D5) — 在主要领域的专业深度

| Code | 必须满足 | ❌ 常见膨胀 |
|------|---------|-----------|
| D1 | 只会下指令，不质疑 AI 的输出 | |
| D2 | 能在选项间做选择并说出理由 | 写配置/设定文件 = D2。"从零写了X" = D2（自己做事不是纠正 AI） |
| D3 | 做架构级决策，拆解复杂系统 | 前提：至少有 3 次以上这种决策记录 |
| D4 | **AI 给出专业方案，owner 指出具体技术错误并给出正确答案** | "不对重来" = D2（没指出原因）。"这里应该用 X 因为 Y" = D4 |
| D5 | 教 AI 它不知道的概念/方法，且 AI 之后学会了 | 极罕见。需要明确的"教→学→应用"证据链 |

**D3+ 的证据要求：** 必须能引用至少 2 条具体的对话场景。不能用"他做了很多架构决策"一笔带过。

### Breadth (B1-B5) — 跨领域的广度

| Code | 必须满足 | ❌ 常见膨胀 |
|------|---------|-----------|
| B1 | 只在一个领域用一种方式 | |
| B2 | 一个领域内用多种工具/方法 | 同一产品的不同功能 = B2（飞书+图片+搜索+权限 = 还是飞书） |
| B3 | 2-3 个**真正独立的领域**，有跨域推理 | 领域必须独立：编程 vs 设计 vs 运营 vs 产品。不是"前端和后端"（都是编程） |
| B4 | 4+ 个独立领域，且有**域间整合思维** | 需要"因为 A 领域的约束，所以 B 领域必须这样做"的推理。"做了4件事"≠ B4 |
| B5 | 把 A 领域的方法论迁移到 B 领域 | 极罕见 |

**B3+ 的领域计数规则：** 前端+后端 = 1 个领域（编程）。飞书+Notion = 1 个领域（工具使用）。设计+编程 = 2 个领域。产品+设计+编程+运营 = 4 个领域。

### Orchestration (O1-O5) — 驾驭 AI 的方式

| Code | 必须满足 | ❌ 常见膨胀 |
|------|---------|-----------|
| O1 | 单轮问答，接受第一个答案 | |
| O2 | 多轮追问/否定/修正 | 发"？"催促 = O2。说"不对" = O2。要求解释 = O2 |
| O3 | 给 AI 战略方向，规划执行顺序 | "先做X再做Y" = O3 |
| O4 | **持续的系统化管理**：分配并行任务+按标准审核+基于原因推翻决策 | 偶尔否定 ≠ O4。必须是**贯穿对话的管理模式**，不是偶发行为 |
| O5 | 设计可复用的 AI 工作流系统 | prompt 模板、多 agent 编排、自动化管道。一次性指令 ≠ O5 |

**O3+ 的频率要求：** O3 行为必须在对话中反复出现（≥5 次），不是偶尔一次。O4 必须是主要的交互模式，不是例外。

### Level Calculation

**Level = round(mean(D, B, O))**，但受 Data Gates 一票否决。
Specialist flag: if max - min >= 2, note the strong dimension.
Level labels: L1 虾苗, L2 小钳, L3 红壳, L4 巨钳, L5 虾皇.

### 定级验证（必须通过，否则降级）

打完 D/B/O 分后，逐条验证：

1. **Data Gate 检查** — 消息数和天数是否满足目标等级的门槛？不满足 = 直接封顶到门槛允许的最高级
2. **证据检查** — 每个 ≥3 的维度，我能写出具体的对话场景吗？不能 = 该维度降到 2
3. **普通人测试** — 换一个会用 AI 的普通人，同样的操作他能做到吗？能 = 不是高分
4. **膨胀检查** — 我是不是在把下列行为拔高？
   - "用了多功能" → B4（实际 B2）
   - "否定了 AI" → O4（实际 O2）
   - "写了配置" → D4（实际 D2）
   - "做了很多事" → 高分（实际只说明了勤奋）
5. **区分度检查** — 如果这个 claw 和另一个 claw 数据量差 5 倍以上，它们的 level 一样吗？一样 = 评级失败，必须拉开差距
6. **最终确认** — **L3 是活跃用户的正常水平。L4 是精英。L5 极罕见。** 如果你给了 L4+，重新检查一遍所有证据

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
| **Recalculate** | clawProfile.level | Recalculate from fresh data using Data Gates + D/B/O scoring. **Can go down** if old level was inflated (e.g. old L4 with <500 messages → new L2/L3). Update dimensions evidence |
| **Best-wins** | hero.headline/tagline, clawProfile.function/domain/persona | Replace if new version is more vivid/specific. **BUT: 旧值违反规则必须替换** — 工具名做 function/domain（飞书/Notion）、"人格"做 domain、无依据 persona（疯批）→ 必须用新值覆盖，不管旧值多"生动" |
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
