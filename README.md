# TransPraxis / 译践

<p align="center">
  <img src="transpraxis/resources/brand/transpraxis-logo.png" alt="TransPraxis / 译践" width="420">
</p>

<p align="center"><strong>AI-assisted Translation Practice Workspace</strong></p>

TransPraxis / 译践是一套面向长文档翻译实践的本地工作空间，覆盖文档解析、术语管理、上下文翻译、独立审校、交付资产以及翻译实践报告。

项目主要面向需要处理较长 PDF / DOCX 文档、保持术语和译文一致性、记录审校过程，并将翻译过程继续用于实践分析的场景。任务状态和中间结果保存在本地，可在中断后继续处理。

<p align="center">
  <img src="docs/assets/transpraxis-workspace-progress.jpg" alt="TransPraxis 长文翻译任务进度界面" width="960">
</p>
<p align="center"><sub>《The Midnight Library》样本任务的进度页。</sub></p>

## Quick Start

### 安装 v0.4.0

需要 Python 3.10 或更高版本。

从 [GitHub Releases](https://github.com/xueyang-dev/TransPraxis/releases) 下载
`transpraxis-0.4.0-py3-none-any.whl`，然后运行：

```bash
python -m pip install ./transpraxis-0.4.0-py3-none-any.whl
transpraxis
```

首次启动后，在设置中选择 provider、model 并填写 API key。如需检查启动参数：

```bash
transpraxis --help
```

### 从源码安装

```bash
git clone https://github.com/xueyang-dev/TransPraxis.git
cd TransPraxis
python -m pip install .
transpraxis
```

仓库同时提供启动器：Windows 双击 `start.bat`，macOS 双击
`start.command`，macOS/Linux 运行 `./start.sh`。如需仅启动本地服务而不自动打开窗口，使用
`transpraxis --no-browser`。桌面窗口需要安装 `requirements-desktop.txt` 中的可选依赖。

## 工作流程

<p align="center">
  <a href="docs/assets/transpraxis-workflow.html">
    <img src="docs/assets/transpraxis-workflow.svg" alt="TransPraxis 长文档翻译工作流程：文档解析、术语管理、上下文翻译、独立审校、交付资产和实践报告" width="1200">
  </a>
</p>

### 1. 文档解析与上下文

支持按版面重建 PDF/DOCX 段落，并处理页眉、页脚、页码和断词。长文翻译阶段使用章节、语义单元和相邻段落构建上下文；已确认的译文可用于后续批次的上下文参考。

### 2. 术语管理

支持从原文提取术语候选，并对候选进行编辑、锁定、拒绝和冻结。翻译阶段仅注入当前范围相关的术语，以减少无关术语对模型上下文的占用。术语资产可导出为 XLSX 或 TBX。

### 3. 翻译与审校

审校阶段检查漏译、占位符、URL、引用标记和术语使用，并可关联文档证据。修订候选采用独立评估流程，避免直接将既有译文或修订结果作为判断依据。审校与修订记录保存在任务中，便于追溯。

### 4. 交付与翻译记忆

任务可按需导出纯译文/双语 DOCX、PDF、重点标注版、XLSX/TBX 术语、TMX 翻译记忆、JSONL 双语段落、证据文件和 `delivery_manifest.json`。仅通过审校的段落会进入翻译记忆；人工确认后的资产会冻结为可追溯的交付快照。任务状态保存在本地，长文中断后可从已保存的配置和进度继续处理。

### 5. 翻译实践报告

“学术增强”将翻译过程、案例、证据、研究问题和提纲整合至同一学术工作区，并生成实践报告草稿。该功能适用于 MTI 作业和研究型翻译；生成的译文、事实说明、引文和理论解释仍需人工核查。

## 三种预设

- **快速**：适合试译和预览；保留 TM 和基础检查，不自动提取术语，也不启用独立审校。
- **标准**：默认选项；自动提取术语，保留 TM，完成常规翻译和基础检查。
- **学术增强**：适合需要过程材料的任务；在标准设置上增加严格术语准备、独立审校和实践报告工作区。

预设提供不同的默认配置，翻译前仍可按任务调整策略和输出内容。

## 输出

常用输出包括：

- 纯译文/双语 DOCX、PDF、重点标注版 DOCX；
- 术语表 XLSX、TBX；
- TMX 翻译记忆、JSONL 双语段落；
- `delivery_manifest.json`、证据文件、审校发现与审校报告；
- 学术工作区 ZIP 和翻译实践报告 DOCX/Markdown 草稿。

## Provider 与命令行

界面支持 OpenCode Go、DeepSeek、OpenAI、Gemini、OpenRouter、SiliconFlow、Moonshot/Kimi、Zhipu/GLM、Qwen/DashScope，以及自定义 OpenAI-compatible endpoint。Provider、模型、API Key 和可选 Base URL 均在设置中配置。

脚本化处理可在源码目录运行：

```bash
export TRANSPRAXIS_API_KEY="your-api-key"
python scripts/translate_pdf.py "文档.pdf" --target-lang 简体中文 --quality
```

完整参数见 `python scripts/translate_pdf.py --help`。

## 使用说明与限制

AI 生成的译文和实践报告仅作为工作稿，提交前应人工核对事实、术语、引文和理论判断。`--lan` 当前采用受信任局域网模式，不包含认证层；不应暴露到不受信任的网络。LAN 认证不在 v0.4.0 范围内。

## 文档

- [CHANGELOG.md](CHANGELOG.md)
- [学术写作架构](docs/academic-writing-architecture.md)
- [文献证据链](docs/literature-evidence-spine.md)
- [MIT License](LICENSE)

## 开发与发布验证

```bash
python -m pip install ".[test]" build
python -m pytest -q
python -m build
```
