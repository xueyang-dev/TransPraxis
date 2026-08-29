# Changelog

本文件记录 TransPraxis / 译践 的用户可见变更。`v0.4.0` 已达到发布候选状态；本轮 UX closure 已完成并冻结，发布仍以人工签发为准。

## [Unreleased]

### MTI 终稿基线

- 增加不含私人论文全文的匿名 MTI finalization fixture 与离线回归入口，覆盖真实修订和合成对照案例的基本边界。
- v0.4.0 release candidate 当前全套自动化测试为 352 项通过；匿名 MTI finalization fixture 可离线运行。

### v0.4.0 UX closure / release hardening

- Final Delivery 生命周期统一为“暂不满足交付条件 / 可以冻结交付 / 已冻结交付 vN / 工作版本已偏离冻结交付 vN”；历史与恢复入口不再显示泛化的 `可交付`。
- 默认 MTI profile 使用匿名结构化参考记录；缺少可靠来源映射的自定义规则不能标为 `enforced`。`docs/mti-practice-driven-roadmap.md` 仅作实现追踪，不是规范来源。
- release gate 增加 `academic_writer.py` 及关键模块的 `py_compile` / import 检查；编译、导入、Streamlit 冷启动、完整测试（352 passed）、匿名回归夹具和真实 23-case 项目 smoke test 均通过。
- v0.4.0 UX 现已冻结；除非发现 correctness bug，不再进行新的 v0.4.0 UX 重构。

### Translation Truth + Provenance

- 固化 `case_origin`、`text_role`、`review_status` 三维语义；旧 `authentic_revision` / `synthetic_contrast` 案例仍可读取并自动补齐公开字段。
- 人工批准只改变 `review_status`，不会把合成对照升格为真实修订；真实与模拟案例在报告、DOCX 和案例工作区使用确定性标签与说明。
- 增加 strict compliance profile 的 synthetic 计数策略：严格 profile 下合成案例只能作为补充，不能满足正式最低案例数。

### v0.4.0 MTI Finalization Pipeline

- 将 `CURRENT_TRANSLATION`、案例 provenance、人工案例终审和冻结交付绑定到同一可追溯工作版本；合成对照即使获批仍保持 `SYNTHETIC_BASELINE`。
- 为学术 artifact 保存精确输入 ID 与生命周期状态，支持按案例/小节的定向 stale propagation、未受影响单元复用，以及报告组合、DOCX 导出和 QA 重跑的独立语义。
- 增加 `MTI_PRACTICE_REPORT_DEFAULT` source-backed compliance profile、项目级语言/术语约束、可配置引文格式和可定位的 manual review 结果；没有可靠来源的要求不会被标记为 enforced。
- 默认 profile 以匿名真实实践样本抽象常见 MTI 报告结构；英文源文换算、synthetic 案例计数、具体引用格式和院校特殊版式继续显式保留为 manual review。
- 将 Structural QA、LibreOffice render、Author Visual Review 和 Word Final Review 分开保存；LibreOffice 只作为自动预检引擎，`report-qa.md` 绑定当前译文、报告、DOCX、PDF 和 QA 状态。
- 扩展匿名 MTI 回归，覆盖 Case-15 人工拒绝、文献/术语定向失效、断点恢复、增量重建、QA 分离和 frozen snapshot 不可回写。

### v0.4.0 已知边界

- 默认 profile 不携带真实院校、学院、网页或规范文件身份；未来院校特定要求只能作为用户自定义 profile 扩展。缺少可靠映射的规则不会冒充 `enforced`。
- 英文源文的 10,000 字折算规则未确认，因此只给出 manual review；不会自行换算为 10,000 English words。
- LibreOffice 不可用时状态为 `NOT_RUN`；Word 字段更新、目录刷新和最终视觉确认仍必须在 Microsoft Word 中完成。

## [0.3.0] - 2026-08-24

### 工作区与任务恢复

- 将翻译、上下文、审校、报告和交付整合为可操作的任务工作区；问题提示中的“查看案例选择”“定位章节”“查看补充问题”等入口现在会打开对应明细和处理动作。
- 长任务改由后台 worker 执行，并持久化运行阶段、心跳、进度和技术事件；刷新或重启后可继续任务、重试失败步骤或放弃失效运行，而不会丢失已完成的翻译和学术写作检查点。
- 任务首次运行时保存 provider 之外的处理策略和交付格式；恢复任务沿用原目标语言、术语、审校、报告和输出配置，避免被当前界面默认值覆盖。

### 学术报告与模板约束

- 报告页面增加案例、模板、章节和人工补充问题的分类明细，可定点重生成受影响章节并重新验证。
- DOCX 模板现在形成可验证的结构契约，包括封面、前置部分、章节层级、固定文本和案例数量要求；报告渲染会保留模板样式并填充正文结构。
- 强化翻译决策案例、文献支持、可见引文和人工证据的验证与修复；报告只有在最终校验完成后才能进入最终交付。

### 交付与可追溯性

- 最终交付改为不可变快照，保存确认人、说明、风险接受记录和对应资产；任务继续修改后会明确提示当前状态与冻结版本不一致。
- 交付格式可按任务选择，包括纯译文/双语 DOCX、PDF、重点标注版、XLSX/TBX 术语、TMX、JSONL、证据、案例、学术工作区 ZIP、审校报告和报告 DOCX/Markdown。
- 交付页面与冻结快照共用同一资产生成路径，避免界面选择与实际下载内容不一致。

### 发布验证

- 210 项自动化测试通过，覆盖运行状态恢复、按钮交互、报告模板、质量门禁、交付快照和各输出格式。
- sdist 与 wheel 已完成内容检查、依赖审计、隔离安装、CLI 以及真实 Streamlit 服务健康验证。
- Python 3.10、3.11 和 3.12 继续由 GitHub Release gate 验证。

### 已知限制

- 翻译、审校和学术写作仍需要用户自行配置 LLM provider；生成内容属于工作稿，正式交付或学术提交前必须人工核查。
- `--lan` 仍是无认证的受信任局域网模式，不应暴露到不受信任的网络。

## [0.2.1] - 2026-08-22

`v0.2.1` supersedes the earlier public builds and is published from the
scrubbed repository baseline. Earlier tags, releases, and downloadable build
artifacts were withdrawn during the repository-history cleanup.

### Runtime hardening

- Review failures remain non-acceptance and cannot promote reviewed state, translation memory, or knowledge feedback.
- Review, evidence, repair, findings, and persisted state now use unambiguous batch-local ordinals and document-global segment identity; repair review is tied to the exact candidate/input being evaluated.
- Blind review stays independent of formal targets, repair provenance, and prior repair decisions; delivery approval remains document-level human authority rather than fabricated segment acceptance.
- Knowledge observations are bound to verified source/target segments, semantic batching preserves context boundaries, and long-document digest/resume reduction remains bounded and restartable.
- Malformed ranges degrade safely, while checkpoint and Translation Memory recovery remain idempotent across interruption points.
- Uploaded XML rejects entity declarations, and user-controlled labels are escaped before entering custom HTML.

### Packaging and release validation

- Project metadata is versioned as `0.2.1`; the `transpraxis` package, console entrypoint, package resources, and cross-platform launchers are validated from an installed wheel.
- Python 3.10 or newer is required. GitHub Actions validates Python 3.10, 3.11, and 3.12, pytest, sdist/wheel contents, isolated wheel installation, and CLI smoke.
- Runtime dependency floors exclude the vulnerable Starlette 0.x line; dependency auditing reports no known vulnerabilities in the resolved release environment.

### Installation and known limitations

- Use `python -m pip install .` from source or install the `transpraxis-0.2.1` wheel, then run `transpraxis` (or `python gui.py` from source).
- Translation, review, and academic writing require a configured LLM provider. AI-generated translation and reports remain drafts that require appropriate human review for high-stakes or academic submission use.
- `--lan` remains trusted-LAN-only with no authentication; saved provider credentials and local task state remain on the host machine.

## [0.2.0] - 2026-08-22

> Superseded by `v0.2.1`; its public tag and release were withdrawn during repository-history cleanup.

### Highlights

- 统一 TransPraxis / 译践 品牌、Python 包名 `transpraxis` 与 `transpraxis` console entrypoint；补齐 Windows、macOS、Linux 启动器及 package resources。
- 强化确定性文档解析、语义批次与上下文边界，支持长文档的可恢复处理。
- 增加术语治理、范围化术语注入、翻译证据、独立审校、定点修复与 delivery gate，明确区分草稿、审校与最终交付。
- 将 Translation Memory、checkpoint、任务状态、文献证据和学术写作 artifact 绑定到可恢复的本地工作流。
- 完善本地 Streamlit 工作区、provider/model 配置、标准 TBX/TMX/JSONL/manifest 资产导出，以及学术报告的证据约束流程。

### Packaging and support

- 支持 Python 3.9+；源码可通过 `python -m pip install .` 安装，wheel 可直接交给 pip 安装，安装后使用 `transpraxis` 启动。
- 发布验证包括 sdist/wheel 构建、隔离 wheel 安装、console help 和已安装 Streamlit app/resource 定位。

### Known limitations

- 翻译、审校和学术写作需要用户配置相应的远程 LLM provider；生成的实践报告仍是 AI 初稿，理论判断和最终提交必须人工核查。
- `--lan` 是受信任局域网模式，当前没有认证层；它会让其它局域网设备访问共享的本地任务状态与已保存 provider 配置，不应暴露到不受信任网络。
- 本地测试可能产生 PyMuPDF/SwigPy 兼容性告警。
