# TransPraxis：由真实 MTI 论文实践驱动的开发路线

## 产品边界

下一阶段明确拆成两个版本，避免“终稿可靠”掩盖“译文平庸”。

| 版本 | 主题 | 解决的问题 |
| --- | --- | --- |
| **v0.4.0** | **MTI Finalization Pipeline** | 真值、案例 provenance、精确失效、学校合规、终稿渲染与交付闭环 |
| **v0.5.0** | **Translation Quality Pipeline** | provider、model、context、terminology、style、prompt、review 与 repair 的译文质量闭环 |

v0.4.0 不以“生成更多论文文字”为目标。它要保证当前译文、案例、报告、DOCX、PDF 和 QA 使用同一份证据，并且任一输入变化只让真正依赖它的产物失效。

```text
Translation Truth
  → Provenance-safe Cases
  → Dependency-aware Sections
  → Compliance Validation
  → DOCX / Rendered PDF
  → Human + Word Final Review
  → Frozen Delivery
```

## 当前基础判断

TransPraxis 已经有增量构建系统的基础，不需要另建工作流框架：

- `academic_state.artifacts` 已记录 `content_hash`、`dependency_hash`、`version` 和 `updated_at`；
- `academic-sections.json` 中的 section 已有独立 dependency hash 和复用逻辑；
- `translation_evidence_hash` 能发现翻译证据变化；
- 合成对比与真实修订已使用 `authentic_revision`、`synthetic_contrast` 和结构化 provenance 区分；
- synthetic validator 已检查合理性、错误实质性、修复正确性和分析价值；
- validator 已禁止把 synthetic case 写成历史初译，并要求可见披露；
- 文献已有 `source → evidence → claim → section` 证据链；
- 模板契约和最终 DOCX 已有结构层验证；
- 冻结交付快照不会被后续工作版本覆盖。

2026-08-27 的本地基线为 **280 项测试全部通过**。

现有增量机制的主要问题不是“没有 dependency hash”，而是 hash 输入仍然偏粗：section hash 会引用整份项目 evidence、完整 argument plan 和整套 literature artifact。一个 segment 变化因此可能让不相关 section 无法复用。v0.4.0 应扩展现有机制并缩小依赖输入，不创建第二套 artifact 系统。

## v0.4.0 的五条设计原则

### 1. 当前译文是唯一可变真值

项目当前译文是报告“改译”、双语附录和交付译文的共同来源。案例生成器只能读取它，不能另造一个声称更权威的终稿。

### 2. 人工确认不能改变 provenance

人工操作可以决定“是否纳入报告”，不能把分析阶段生成的译法变成真实历史。质量判断与证据来源必须分开保存。

### 3. stale 不等于全部重算

最终报告或 DOCX 作为组合产物可以 stale，但重建时应复用未变化的 case、section 和 literature artifacts。只有 dependency hash 改变的写作单元需要再次调用模型。

### 4. 各种 QA 状态不能互相冒充

DOCX 结构通过、LibreOffice 成功渲染、作者看过页面和 Word 最终确认是四项不同事实。系统必须分别记录。

### 5. 能确定性验证的，不交给 LLM 猜

学校规范、字数、关键词数量、标题层级、编号、引用对应、附录和页面结构优先由 Compliance Profile 与确定性检查完成。

## P0 基础设施一：Translation Truth + Provenance

### Provenance 采用两个正交维度

不把 `CURRENT_TRANSLATION` 与案例类型混成三个互斥枚举。推荐保留现有内部 schema，并增加稳定的公开语义映射。

**案例来源 `case_origin`：**

| 公开语义 | 当前内部值 | 含义 |
| --- | --- | --- |
| `REAL_REVISION` | `authentic_revision` | 项目历史中确有初译与后续修订 |
| `SYNTHETIC_BASELINE` | `synthetic_contrast` | 为分析构造的合理对照，不是历史过程 |

**文本角色 `text_role`：**

| 角色 | 来源 |
| --- | --- |
| `SOURCE` | 项目源文 |
| `HISTORICAL_INITIAL` | 项目保存的真实初译 |
| `SYNTHETIC_BASELINE` | 分析阶段生成或恢复的模拟基线 |
| `CURRENT_TRANSLATION` | 项目当前译文，唯一可变真值 |

**人工复核 `review_status`：** `unreviewed / approved / rejected`。

这三个维度互不替代。例如一个 synthetic case 可以同时包含：

```text
case_origin = SYNTHETIC_BASELINE
initial.text_role = SYNTHETIC_BASELINE
target.text_role = CURRENT_TRANSLATION
review_status = approved
```

即使 `review_status=approved`，它仍然不是 `REAL_REVISION`。

### 确定性导出规则

- `REAL_REVISION` 才能显示“初译—改译”，并使用“笔者初译为……”等历史陈述；
- `SYNTHETIC_BASELINE` 必须显示“模拟初译”“模拟译法”或“对照译文”；
- synthetic case 禁止生成“笔者初译为”“经审校后改为”“译者最初选择”等过程事实；
- Human Evidence 只能补充作者说明，不能把 synthetic case 升格为 real revision；
- `CURRENT_TRANSLATION` 变化后，所有绑定该 segment 的 target excerpt 都必须重新读取；
- 学校 profile 如果要求案例必须来自真实实践，应明确规定 synthetic case 是否只作补充、是否计入最低案例数，而不是由通用 case policy 默许。

当前 validator 已实现其中大部分规则。v0.4.0 的工作是把这些约束升为 P0、统一字段语义、补足 UI 和 compliance policy，而不是重写 synthetic pipeline。

## P0 基础设施二：Dependency-aware Invalidation

### 复用并扩展现有 artifact record

现有 artifact record 保留，只增加精确输入索引和显式状态：

```text
artifact_id
artifact_type
file
content_hash
dependency_hash        # 稳定哈希实际输入；可包含版本、policy 和 payload，不要求只由 IDs 组成
input_segment_ids
input_artifact_ids
version
updated_at
status                 # valid / stale / missing / failed
stale_reason
```

不引入数据库或通用 DAG 引擎。artifact 数量有限，segment 修改后扫描现有记录并沿 `input_artifact_ids` 传播即可。

### 缩小 dependency hash 的输入

`_section_dependency_hash()` 不再依赖整份 `evidence["content_hash"]`、完整 argument plan 或完整 literature content hash。每个写作单元只 hash：

- 本单元的 outline plan；
- 本单元实际引用的 claim；
- 本单元案例及其对应 segment payload；
- 本单元实际分配到的 literature claims/evidence；
- 与这些案例相关的 human evidence；
- 会影响本单元的模板和写作版本。

Case Analysis Chapter 中的 `3.3.1 / 3.3.2 / 3.3.3` 应成为可独立缓存的写作单元。Chapter 3 和 Final Report 是组合 artifact：子单元变化后需要重新组装，但不要求重写其他子单元。

### Case 15 的目标失效链

```text
segment:382 hash changed
  ↓
case:15 stale
  ↓
section:3.3.2 stale
  ↓
chapter:3 stale (reassemble)
  ↓
report:final stale (reassemble)
  ↓
docx:final stale
  ↓
render:* stale
```

以下内容继续保持 valid：

```text
literature-evidence:7
case:3
case:8
section:2.1
section:3.3.1
```

项目级状态显示“当前报告包含过期内容”，但 UI 必须同时显示具体 stale 链和可复用产物。

### 译文修改入口

人工编辑、恢复原译、AI 重译、接受修复候选和术语变更引起的重译，都要经过同一个“translation truth changed”入口。它负责：

1. 更新 segment hash；
2. 清除该 segment 的审校／TM 信任状态；
3. 标记直接依赖 artifact；
4. 递归传播 stale；
5. 撤销当前工作版本的最终交付批准；
6. 保留旧的冻结快照。

不能只在下一次 academic pipeline 运行时才发现变化。

## v0.4.0 开发阶段

### 阶段 0：Baseline（P0，1—2 天）

- 收束当前 `main` 上尚未提交的实现和测试；
- 按学术证据链、synthetic cases、报告工作区和 DOCX 分拆提交；
- 保持 280 项测试全绿；
- 建立不包含私人论文全文的匿名 MTI regression fixture；
- 更新未发布 Changelog。

退出条件：干净工作树、完整测试通过、回归样本可离线运行。

### 阶段 1：Translation Truth + Provenance（P0，2—3 天）

- 固化上述 `case_origin / text_role / review_status` 三个维度；
- 保持对旧 `authentic_revision / synthetic_contrast` 数据的读取兼容；
- 把“人工批准不能改变 provenance”写成业务层 invariant；
- 把真实／模拟导出措辞写成确定性规则；
- 在 UI 中用明显不同的标签与说明展示两种案例；
- 让 strict compliance profile 决定 synthetic 是否可以计入正式最低案例数。

验收：任何 synthetic case 即使被人工批准，也不能输出历史初译陈述或获得真实修订 provenance。

### 阶段 2：Dependency-aware Invalidation（P0，4—6 天）

Stage 2 按以下顺序实施，前一项通过回归后再进入后一项：

```text
1. 补齐所有 translation truth mutation path
   ↓
2. 修 synthetic_optimized 的隐藏 dependency
   ↓
3. artifact record 增加精确 input ids + lifecycle status
   ↓
4. stale propagation
   ↓
5. 区分 stale / LLM rewrite / reassemble / QA
   ↓
6. Stage 2A regression
   ↓
7. 再拆 subsection writing units
   ↓
8. Stage 2B regression
```

#### Stage 2A：依赖与生命周期基础

1. **补齐所有 translation truth mutation path**：人工编辑、恢复原译、AI 重译、接受修复候选、翻译流水线批次提交，以及断点恢复时的截断保存，都经过同一个 truth-change 入口。
2. **修 `synthetic_optimized` 的隐藏 dependency**：把当前译文/evidence 的实际输入纳入依赖，而不是只依赖 error manifest 和 glossary。
3. **扩展 artifact record**：增加精确的 `input_segment_ids / input_artifact_ids / status`，继续复用现有 `academic_state.artifacts`。
4. **实现 stale propagation**：从 segment/case 变化沿现有 artifact 依赖传播，并保留可复用单元。
5. **拆分生命周期语义**：分别表达 `stale`、`LLM rewrite`、`reassemble` 和 `QA`，尤其区分 Final Report/DOCX 的重新组装与 LLM 重写。
6. **Stage 2A regression**：验证译文变化只影响真实下游，未受影响的 case、Chapter section 和文献不调用模型且 content hash 不变。

#### Stage 2B：写作单元细化

7. **再拆 subsection writing units**：在 Stage 2A 稳定后，将 Case Analysis 的 `3.3.1 / 3.3.2 / 3.3.3` 等子节改为独立缓存和重写单元；Chapter 3 与 Final Report 只负责组合。
8. **Stage 2B regression**：验证修改 Case 15 后只重写对应 subsection，并重新组装 Chapter 3、Final Report、DOCX 和 render QA。

Stage 2B 的最终验收：修改 Case 15 对应译文后，只重建 Case 15、3.3.2 及组合下游；Case 3、Case 8、2.1、3.3.1 和无关文献不调用模型、不改变 content hash。

#### Stage 2 实际完成粒度

Stage 2A/2B 已落在现有 `academic_state.artifacts` 上。canonical record 保存上述全部字段；旧 record 缺少新字段时按 `valid`、空 direct inputs 读取，原完整性检查通过即可复用，下次自然重建时升级。

`selected_cases` 会为每个已选案例写一个轻量 `case:<case_id>` graph node。它复用 case payload，不建立第二套案例 schema，也不是单独 LLM writing artifact；其 direct edge 只指向绑定 segment。

当前执行语义映射如下：

```text
case selection             deterministic_reassemble
writing section/subsection llm_rewrite
chapter composite          deterministic_reassemble
final report composite     deterministic_reassemble
DOCX validation/export     reexport
render record              rerun_qa
valid record               reuse
```

仍需如实区分的 LLM 行为：独立 semantic review、literature support review 和 academic quality evaluation 在 report 变化后仍会重新审阅整篇；quality repair 找到整章级问题时仍可能重写该章。它们不是 report composite 的重组动作，也不得显示成“subsection 需要 LLM 重写”。增量 truth mutation 的主链已按 subsection 复用：受影响 subsection LLM 重写，Chapter 3 和 report 重新组装，DOCX 重新导出，render QA 重跑。

### 阶段 3：Human Case Review（P0/P1，4—5 天）

把现有 Case Portfolio 从汇总表升级为案例终审工作台，不另建案例模型。

每个案例显示：

- case origin 与每段文本的 text role；
- 原文、必要上下文、真实初译或模拟基线、当前译文和分析；
- baseline plausibility、material difference、repair correctness、analysis value；
- 所依赖的 segment、术语、finding、literature 和 section；
- 当前 stale／valid 状态。

作者可执行：

- **批准纳入**：只改变 review status；
- **排除案例**：保存原因，并从合格池补入其他案例；
- **修改当前译文**：跳转翻译工作区，触发精确失效链；
- **修改／拒绝模拟基线**：重跑该 synthetic case 下游，不修改翻译真值。

正式导出增加人工质量门禁：“当前译文在准确性、完整性和中文表达上不劣于对照译文。”案例 15 型场景若不通过，不得继续生成“改译更优”的分析。

#### Stage 3 实际完成

`case_reviews / case_review_overrides` 保存当前工作版本的审核事实，包括 `review_reason、reviewed_at、actor、content_stale`。批准只表达作者接受当前内容，不改变 provenance；内容变化后旧批准标记 `content_stale`，必须重新检查。

四个入口均已接入：批准、带原因排除、从案例卡跳转修改 `CURRENT_TRANSLATION`、修改/拒绝模拟初译。被排除案例可从已通过机器 validation 的候选池替换；替换案例必须是 `unreviewed`，不能继承前例批准。

`case_review_gate()` 在 `approve_delivery()` 中 fail-closed：required case 未审、被拒、内容 stale、case artifact stale/failed，或 synthetic baseline 被拒时均阻止冻结。profile policy 仍从 selected-case policy 读取；完整 compliance engine 留给 Stage 4。

冻结 manifest 保存当时的 `case_reviews` 和 `case_review_overrides`；后续工作版本审核变化只改变当前 identity，不会回写历史快照。

### 阶段 4：Compliance Profile + Language Constraints（P1，3—5 天）

在现有 `thesis_constraints` 和 template contract 上增加 **Compliance Profile**，不开发通用规则 DSL。默认 profile 为：

```text
profile_id: MTI_PRACTICE_REPORT_DEFAULT
display_name: 默认 MTI 实践报告规范
program: MTI 翻译实践报告
source_type: reference_template
source_id: mti_practice_report_reference_v1
scope: default_profile
```

默认结构来自匿名真实 MTI 实践样本的产品抽象，不代表全国统一或院校强制要求。每条规则都必须保存来源、适用范围和检查级别。只有完成可靠来源映射的规则才能标为 enforced；未确认规则显示 manual review，不能伪装成院校硬性要求。未来院校特定规则由用户自定义 profile 承载。

首批确定性检查包括：

- 中文摘要 400—600 字；
- 中英文关键词 5—8 个及标点格式；
- 目录最多三级；
- 正文引用与参考文献双向对应；
- 图号采用“图 3.x”、表号采用“表 3.x”等按章编号；
- 正文与附录是否存在及角色是否正确；
- 双语对照附录要求；
- 中文源文按汉字数检查；英文源文最低长度折算保留人工确认；
- 案例分析是否为核心章节、结论是否回应研究问题；
- 页眉、页码体系、页面尺寸、页边距、标题样式、行距等可从 DOCX 结构读取的格式要求；
- synthetic case 在默认 profile 下的计数与披露政策；
- `【待作者填写】` 等人工确认项。

同阶段增加：

- `forbidden_report_phrases`；
- `allowed_theory_labels`；
- 核心术语／人名／作品名一致性列表。

规则命中必须定位到 section 或 DOCX 元素；不要生成“论文像不像论文”的综合 AI 分数。

### 阶段 5：Rendered QA（P1，4—5 天）

最终质量状态拆开保存：

| 检查 | 可能状态 |
| --- | --- |
| Structural QA | `PASS / FAIL` |
| LibreOffice Render | `PASS / FAIL / NOT_RUN` |
| Author Visual Review | `CONFIRMED / NOT_CONFIRMED` |
| Word Final Review | `CONFIRMED / NOT_CONFIRMED` |

每次渲染至少记录：

```text
render_engine
render_engine_version
source_docx_hash
rendered_pdf_hash
rendered_at
page_count
```

LibreOffice 路径用于 CI 和跨平台预检：

```text
DOCX → LibreOffice → PDF → PyMuPDF → deterministic QA
```

PyMuPDF 首批检查不只判断页面是否有文字，还采集：

- text/image/drawing block 数量；
- 页面内容占用率；
- font name、font size 与异常替换；
- 标题 bounding boxes；
- 页眉页脚和页码区域；
- 表格／图题附近的分页与边界；
- 疑似空白、溢出、标题落单和异常密度页面。

LibreOffice PASS 只说明该引擎成功渲染并通过对应规则，绝不等于 Word 最终效果。正式交付前由作者在 Microsoft Word 中更新字段、检查目录与关键页面，并单独确认 `Word Final Review`。若用户提供 Word 导出的 PDF，应记录其 artifact hash 和 review 记录。

最终生成简洁 `report-qa.md`，分别报告 compliance、structure、LibreOffice render、author review、Word review 和尚未确认项目。

### 阶段 6：Regression & Release（P1，2—3 天）

匿名化真实论文 regression 至少覆盖：

- Case 15：当前译文不优于模拟基线时被人工门禁拦截；
- synthetic approval 不改变 provenance，且无法生成历史事实陈述；
- Segment 382 修改后只失效 Case 15 → 3.3.2 → Chapter 3 → Final artifacts；
- 删除一条参考文献后，正文引用与最终书目保持一致；
- 修改核心术语后，只失效真正依赖该术语的 segment 和学术下游；
- 25 个案例按配置分布并通过来源、目标、标签与计数政策检查；
- 未知作者信息保留为明确 manual review 项；
- Structural PASS + LibreOffice PASS 时，Word Final Review 仍可保持 NOT_CONFIRMED；
- 默认 MTI profile 每个 enforced rule 都能追溯到匿名参考来源记录。

发布前执行完整测试、一次端到端真实任务、一次中断恢复和一次局部重建验证，然后发布 v0.4.0。

#### 阶段 4—6 实际完成（v0.4.0 release candidate）

- Stage 4 已落在 `transpraxis/compliance.py`：`MTI_PRACTICE_REPORT_DEFAULT` 使用结构化 rule records，保留 authority/source/clause/conflict 字段；项目 Roadmap 仅作为实现追踪，不是规范来源。默认 profile 不携带真实院校身份。
- Stage 4 的确定性检查覆盖摘要、关键词、目录层级、正文/参考文献双向 ID、图表编号与 caption、双语附录、按语源区分的原文长度、结构事实、DOCX 可读取 layout、作者占位符和项目级语言约束。英文 10,000 字折算、脚注/顺序编码冲突、synthetic 是否计入学校最低案例数均保留为 manual review。
- Stage 5 已落在 `transpraxis/rendered_qa.py` 与现有 finalization records：PyMuPDF 只读取 PDF 文本/块/字体/位置事实，不做 OCR；空白页、密度、标题落单、边界、页眉页脚和页码区域分别作为 warning 或 manual review。LibreOffice 缺失时是 `NOT_RUN`，不伪造 PASS。
- Stage 5 保存独立的 Structural QA、LibreOffice Render、Author Visual Review、Word Final Review 和 `report-qa.md`；DOCX 或 render 变化会清除旧人工确认并沿 Stage 2 dependency graph 重跑相应下游。
- Stage 6 已用 `eval/fixtures/mti_finalization_regression.json` 完成匿名 Case-15、文献/术语定向变化、案例分布、占位符、断点恢复、增量复用、QA 分离、E2E 冻结和历史 snapshot 不回写回归。当前 release candidate 不提前声称完成 v0.5 Translation Quality Pipeline。

真实实现限制：当前自动化预检只有 LibreOffice 引擎；Microsoft Word 的字段更新、目录刷新、表格分页和最终视觉效果仍必须由作者在 Word 中确认。旧版仅有 `p3_md` 而没有结构化 report artifact 的任务继续可读取，并沿历史交付路径运行；拥有 v0.4 artifact record 的任务才进入严格 compliance/QA finalization gate。

#### Stage 4.5 source-backed rule population

`MTI_PRACTICE_REPORT_DEFAULT` 以 `mti_practice_report_reference_v1` 保存匿名结构化参考来源。摘要、关键词、目录三级、图表章内编号、双语附录、案例分析报告基本结构、A4、页边距、页眉/页脚距离和固定 20 磅行距在该默认产品 profile 中执行确定性检查。英文源文最低长度折算、synthetic case 是否计入最低案例数、具体引用格式和院校特殊封面/页眉/目录要求继续为 `manual_review`，统一提示用户根据所在院校要求确认。项目 roadmap 只作实现追踪，不是规范来源；真实原始 DOC/DOCX/PDF 不进入仓库。

## v0.5.0：Translation Quality Pipeline

v0.4.0 解决“终稿是否真实、同步、合规、可复核”；v0.5.0 解决“译文本身是否足够好”。两者不能互相替代。

```text
Source
  → Context Assembly
  → Terminology / Entity Decisions
  → Style Profile
  → Prompt Contract
  → Provider / Model
  → Runtime
  → Translation
  → Independent Review
  → Targeted Repair
  → Human Evaluation
```

v0.5.0 的开发顺序应从评测开始，而不是先改 prompt：

1. 建立匿名、分层的长文翻译 benchmark，覆盖术语、专名、长句、指代、隐喻、文体和跨段连贯；
2. 对 dots API 及其他 provider/model 运行同一输入、同一术语、同一 style profile 的可复现对比；
3. 分别消融 context assembly、术语注入、style profile 和 prompt contract，确认真正影响质量的环节；
4. 用确定性检查衡量段落对齐、术语／专名一致性、遗漏和 transport integrity；
5. 用盲法人工成对评审衡量准确性、自然度、语体和上下文连贯，不用 LLM 自己给自己打总分；
6. 将 review 与 repair 绑定到明确 finding，比较修复前后并阻止“越修越差”；
7. 将通过人工评审的结果沉淀为 provider/model/runtime 回归门禁。

v0.5.0 的成功标准不是“某模型分数最高”，而是能够回答：在哪类文本、哪类难点、哪种上下文和术语配置下，某个 provider/model 组合稳定地产生更好的译文，并且修复流程不会破坏已正确内容。

## 建议提交顺序

1. `chore: checkpoint current academic pipeline baseline`
2. `fix: make case provenance immutable across human review`
3. `feat: track artifact inputs and propagate targeted staleness`
4. `feat: add provenance-aware human case review`
5. `feat: add generic MTI compliance profile and language constraints`
6. `feat: record engine-specific rendered report QA`
7. `test: add anonymized MTI finalization regression`

## 本阶段明确不做

- 不调用 `invalidate_all_academic_state()` 代替依赖判断；
- 不重写 `academic_writer` 或引入数据库、Bazel、通用 DAG 引擎；
- 不允许人工批准或 Human Evidence 改写 provenance；
- 不把 synthetic case 默认视为真实实践案例；
- 不把 LibreOffice 渲染结果表述成 Word 最终真值；
- 不开发通用参考文献管理器，继续使用现有稳定来源 ID；
- 不用 LLM 综合评分替代可以确定性执行的学校规范；
- 不在 v0.4.0 顺手重做 provider/model/runtime 翻译质量链路。

## v0.4.0 最终验收标准

v0.4.0 完成时，修改一个最终译文 segment 后，系统必须准确展示其 stale 依赖链，只重新生成受影响案例和写作单元，并复用其余内容；任何 synthetic baseline 永远保持非历史 provenance；默认 MTI profile 的确定性规则、LibreOffice 预检、作者视觉复核和 Word 最终确认分别记录。最终 DOCX、Word/PDF 产物与 QA 必须绑定同一当前译文 hash，且不得暗示未完成的检查已经通过。
