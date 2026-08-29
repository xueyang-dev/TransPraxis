"""TransPraxis / 译践 Streamlit 界面层。

信息架构：左侧产品导航 + 四步任务创建 + 运行后任务工作台。AI Provider
与翻译记忆属于全局设置；学术报告属于翻译后的下游工作流，不占据文档首屏。
"""
import base64
import inspect
import json
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

import core
from transpraxis import assets as _assets
from transpraxis import academic_validator as _academic_validator
from transpraxis import case_provenance as _case_provenance
from transpraxis import context as _context
from transpraxis import delivery as _delivery
from transpraxis import finalization as _finalization
from transpraxis import knowledge as _knowledge
from transpraxis import literature_evidence as _literature_evidence
from transpraxis import report_evidence as _report_evidence
from transpraxis import report_template as _report_template
from transpraxis import compliance as _compliance
from transpraxis import thesis_constraints as _thesis_constraints

# Older Streamlit versions (including the Python 3.9-compatible line) do not
# expose persist_state; widget keys provide the fallback there.
_PERSIST_STATE = (
    {"persist_state": "session"}
    if "persist_state" in inspect.signature(st.selectbox).parameters
    else {}
)

# ================= 页面全局设置 =================
_APP_ROOT = Path(__file__).resolve().parent
_BRAND_DIR = Path(_assets.__file__).resolve().parent / "resources" / "brand"
_BRAND_MARK = _BRAND_DIR / "transpraxis-mark.png"
_BRAND_FAVICON = _BRAND_DIR / "transpraxis-favicon.png"
_BRAND_MARK_URI = "data:image/png;base64," + base64.b64encode(
    _BRAND_MARK.read_bytes()).decode("ascii")

st.set_page_config(page_title="TransPraxis / 译践", page_icon=_BRAND_FAVICON, layout="wide",
                   initial_sidebar_state="expanded")

if "doc_states" not in st.session_state:
    st.session_state.doc_states = {}
if "active_job_id" not in st.session_state:
    st.session_state.active_job_id = None
if "task_step" not in st.session_state:
    st.session_state.task_step = 1
if "app_view" not in st.session_state:
    st.session_state.app_view = "new"
if "workspace_mode" not in st.session_state:
    st.session_state.workspace_mode = False
if "provider_configured" not in st.session_state:
    st.session_state.provider_configured = False
if "provider_connection_status" not in st.session_state:
    st.session_state.provider_connection_status = "unverified"
# 从本地配置恢复 AI 引擎（保存过之后，重启应用无需重新填写）
_saved_provider_cfg = core.load_provider_config()
if _saved_provider_cfg:
    _saved_provider = _saved_provider_cfg["provider"]
    if _saved_provider in core.PROVIDERS \
            and "provider_choice" not in st.session_state:
        st.session_state.provider_choice = _saved_provider
    if _saved_provider_cfg.get("api_key") \
            and f"api_key_{_saved_provider}" not in st.session_state:
        st.session_state[f"api_key_{_saved_provider}"] = \
            _saved_provider_cfg["api_key"]
    _saved_model = _saved_provider_cfg.get("model")
    _saved_models = core.PROVIDERS.get(_saved_provider, {}).get("models") or []
    if _saved_model and (not _saved_models or _saved_model in _saved_models) \
            and f"model_choice_{_saved_provider}" not in st.session_state:
        st.session_state[f"model_choice_{_saved_provider}"] = \
            _saved_model
    if _saved_provider_cfg.get("base_url") \
            and "custom_base_url" not in st.session_state:
        st.session_state.custom_base_url = _saved_provider_cfg["base_url"]
    _saved_reviewer = _saved_provider_cfg.get("reviewer") or {}
    if _saved_reviewer.get("provider") and "reviewer_mode" not in st.session_state:
        st.session_state.reviewer_mode = "separate"
        st.session_state.reviewer_provider_choice = _saved_reviewer["provider"]
        st.session_state.reviewer_model = _saved_reviewer.get("model", "")
        st.session_state.reviewer_api_key = _saved_reviewer.get("api_key", "")
        st.session_state.reviewer_base_url = _saved_reviewer.get("base_url", "")
# ================= 设计系统（TransPraxis Research IDE） =================
_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');

:root {
 --tp-sidebar-width: 236px;
 --tp-main-gutter: 80px;
 --tp-navy: #001471;
 --tp-brand-ink: #15379a;
 --tp-logo-blue: #057afe;
 --tp-primary: #1267e8;
 --tp-primary-hover: #0d57ce;
 --tp-primary-active: #0a49b4;
 --tp-cyan: #09a7fd;
 --tp-primary-soft: #eef5ff;
 --tp-primary-soft-hover: #e5f0ff;
 --tp-border: #bed7ff;
 --tp-focus-ring: rgba(18,103,232,.22);
 --tp-canvas: #f7f8fa;
 --tp-surface: #ffffff;
 --tp-ink: #131c2e;
 --tp-sub: #667085;
 --tp-faint: #8a94a6;
 --tp-line: #dee3ea;
 --tp-line-subtle: #ebeef3;
 --tp-sidebar-line: #e7eaf0;
 --tp-success: #22a06b;
 --tp-danger: #dc2626;
 --tp-radius-sm: 6px;
 --tp-radius-md: 8px;
 --tp-radius-lg: 12px;
 --action-bar-height: 80px;
}

html, body, [class*="css"], .stApp, button, input, textarea, select {
 font-family: 'Manrope', ui-sans-serif, system-ui, -apple-system,
 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Noto Sans SC',
 sans-serif !important;
}

.stApp {
 background: var(--tp-canvas);
}
[data-testid="stHeader"] { display: none; }
[data-testid="stDecoration"] { display: none; }
footer { visibility: hidden; }
[data-testid="stMainBlockContainer"] {
 width: min(100%, 1152px); max-width: 1152px; margin-left: 0; margin-right: auto;
 padding: 72px var(--tp-main-gutter) 40px;
}

/* ---------- Typography ---------- */
h1, h2, h3, h4, [data-testid="stHeadingWithActionElements"] {
 color: var(--tp-ink) !important;
 letter-spacing: -.02em; font-weight: 650;
}
h1 { font-size: 34px !important; line-height: 1.2 !important; font-weight: 700 !important; }
h2 { font-size: 23px !important; }
h3 { font-size: 16px !important; }
p, label, input, textarea, [data-baseweb="select"] { font-size: 14px !important; }
label, [data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] label {
 color: var(--tp-ink) !important; opacity: 1 !important;
}
[data-testid="stCaptionContainer"], .stCaption {
 color: var(--tp-sub) !important; opacity: 1 !important;
}
[data-testid="stRadio"] [data-testid="stRadioOption"],
[data-testid="stRadio"] [data-testid="stRadioOption"] [data-testid="stMarkdownContainer"],
[data-testid="stRadio"] [data-testid="stRadioOption"] [data-testid="stMarkdownContainer"] *,
[data-testid="stSlider"] [data-testid="stSliderThumbValue"],
[data-testid="stSlider"] [data-testid="stSliderThumbValue"] * {
 color: var(--tp-ink) !important; opacity: 1 !important;
}
[data-testid="stRadio"] [data-testid="stRadioOption"] > div > div > div:first-child {
 background: var(--tp-surface) !important; border: 2px solid #98a2b3 !important;
}
[data-testid="stRadio"] [data-testid="stRadioOption"][data-selected="true"] > div > div > div:first-child {
 background: var(--tp-primary) !important; border-color: var(--tp-primary) !important;
}
[data-testid="stRadio"] [data-testid="stRadioOption"][data-selected="true"]
 > div > div > div:first-child > div {
 background: #fff !important;
}
[data-testid="stRadio"] [data-testid="stRadioOption"]:hover > div > div > div:first-child {
 border-color: var(--tp-primary) !important;
}
[data-testid="stSlider"] div:has(> [data-testid="stSliderThumbValue"]) {
 background: var(--tp-primary) !important;
}
a { color: var(--tp-primary); text-decoration-color: var(--tp-border); text-underline-offset: 2px; }
a:hover { color: var(--tp-primary-hover); text-decoration-color: var(--tp-logo-blue); }
hr { border-color: var(--tp-line); }
::selection { background: var(--tp-focus-ring); }

/* ---------- Product shell ---------- */
[data-testid="stSidebar"] {
 background: var(--tp-surface); border-right: 1px solid var(--tp-sidebar-line);
 width: var(--tp-sidebar-width) !important; min-width: var(--tp-sidebar-width) !important;
 overflow-x: clip;
 transform: none !important;
}
[data-testid="stSidebarContent"] {
 padding: 20px 24px 82px; position: relative;
}
[data-testid="stSidebarHeader"] { display: none !important; }
[data-testid="stSidebarUserContent"] { padding-top: 0; }
[data-testid="stSidebarContent"] [data-testid="stVerticalBlock"] { gap: .5rem; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { line-height: 1.5; }
/* Streamlit 会给 markdown 容器默认注入 -16px 下边距（补偿段落默认边距），
   品牌块没有段落默认边距，会被压缩导致副标题与下方按钮重叠，这里抵消掉。 */
[data-testid="stSidebarContent"] [data-testid="stMarkdownContainer"]:has(.tp-brand) {
 margin-bottom: 0;
}
[data-testid="stSidebar"] .stButton > button {
 min-height: 44px; justify-content: flex-start; border-color: transparent;
 background: transparent; color: #536176; font-size: 14px; font-weight: 400;
}
[data-testid="stSidebar"] .stButton > button:hover {
 background: #f6f8fb; border-color: transparent; color: #202a3a;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
 background: var(--tp-primary-soft); border-color: transparent;
 color: var(--tp-brand-ink); font-weight: 500;
}
.tp-brand {
 display: flex; flex-direction: column; align-items: center;
 padding: 8px 0 0; margin-bottom: 14px; text-align: center;
}
.tp-brand-mark {
 display: block; width: 116px; height: auto; object-fit: contain;
 margin: 0 auto 4px;
}
.tp-brand-copy strong {
 display: block; overflow: hidden; color: var(--tp-navy); font-size: 18px;
 font-weight: 700; letter-spacing: -.025em; line-height: 1.12; text-overflow: ellipsis;
 white-space: nowrap;
}
.tp-brand-copy b {
 display: block; margin-top: 3px; color: var(--tp-brand-ink); font-size: 12px;
 font-weight: 600; letter-spacing: .04em; line-height: 1.3;
}
.tp-brand > span {
 display: block; margin-top: 8px; color: #7c8799; font-size: 10px;
 font-weight: 400; line-height: 1.4; white-space: nowrap;
}
.tp-nav-label {
 margin: 18px 0 6px; color: #7c8799; font-size: 12px;
 font-weight: 500; letter-spacing: 0; line-height: 1.4;
}
.tp-nav-divider { height: 1px; margin: 24px 0; background: var(--tp-sidebar-line); }
.st-key-new_task_action .stButton > button {
 min-height: 44px; border: 1px solid #dce2ea; border-radius: 9px;
 background: #fff; color: #202a3a; font-size: 14px; font-weight: 500;
}
.st-key-new_task_action .stButton > button:hover { background: #f8fafc; border-color: #c9d2df; }
.st-key-new_task_action .stButton > button:active { background: #f1f5f9; }
.st-key-task_steps { position: relative; gap: 0 !important; margin: 0 0 6px; }
.st-key-task_steps::before {
 content: ""; position: absolute; left: 17px; top: 28px; height: calc(100% - 56px);
 width: 1px; background: #dce2ea;
}
.st-key-task_steps .stButton { position: relative; z-index: 1; margin: 0; }
.st-key-task_steps .stButton > button {
 min-height: 56px; height: 56px; padding: 0 8px; background: transparent;
 border-color: transparent; border-radius: var(--tp-radius-md); font-size: 14px;
}
.st-key-task_steps .stButton > button > div { width: 100%; }
.st-key-task_steps .stButton > button > div > span {
 display: grid !important; grid-template-columns: 18px minmax(0,1fr);
 column-gap: 6px; align-items: center; width: 100%;
}
.st-key-task_steps .stButton > button[kind="primary"] {
 background: transparent; border-color: transparent; color: var(--tp-brand-ink); font-weight: 600;
}
.st-key-task_steps button[data-testid="stBaseButton-primary"] {
 background: transparent !important; border-color: transparent !important;
 color: var(--tp-brand-ink) !important;
}
.st-key-task_steps [data-testid="stIconMaterial"] {
 position: relative; z-index: 2; background: var(--tp-surface); border-radius: 50%;
 font-size: 18px;
}
[class*="st-key-task_step_done_"] [data-testid="stIconMaterial"] { color: var(--tp-success); }
[class*="st-key-task_step_current_"] [data-testid="stIconMaterial"] { color: var(--tp-logo-blue); }
[class*="st-key-task_step_pending_"] [data-testid="stIconMaterial"] { color: #a8b2c1; }
[class*="st-key-task_step_done_"] .stButton > button { color: #344054; font-weight: 500; }
[class*="st-key-task_step_current_"] .stButton > button { color: var(--tp-brand-ink); font-weight: 600; }
[class*="st-key-task_step_pending_"] .stButton > button { color: #536176; font-weight: 400; }
.tp-engine-row, .tp-summary, .tp-pipeline, .tp-confirm-card {
 border: 1px solid var(--tp-line); border-radius: 10px; background: var(--tp-surface);
}
.tp-engine-row { padding: 12px 14px; margin: 6px 0 18px; }
.tp-engine-row strong { font-size: 13px; color: var(--tp-ink); }
.tp-engine-row span { display: block; margin-top: 3px; font-size: 12px; color: var(--tp-sub); }
.st-key-provider_status {
 position: fixed; left: 24px; bottom: 12px; z-index: 30;
 width: calc(var(--tp-sidebar-width) - 48px);
 margin: 0; padding: 20px 0 0; border-top: 1px solid var(--tp-sidebar-line);
 background: var(--tp-surface);
}
.st-key-provider_status [data-testid="stHorizontalBlock"] { align-items: center; gap: 6px; }
.st-key-provider_status .stButton > button {
 min-height: 30px; padding: 2px 0; justify-content: flex-end;
 color: var(--tp-primary); font-size: 13px; font-weight: 500;
}
.st-key-provider_status .stButton > button:hover { color: var(--tp-primary-hover); background: transparent; }
.tp-provider { position: relative; padding-left: 17px; }
.tp-provider::before {
 content: ""; position: absolute; left: 2px; top: 5px; width: 8px; height: 8px;
 border-radius: 50%; background: var(--tp-surface); border: 1px solid #98a2b3;
}
.tp-provider.is-connected::before { background: var(--tp-success); border-color: var(--tp-success); }
.tp-provider.is-error::before { background: var(--tp-danger); border-color: var(--tp-danger); }
.tp-provider strong { display: block; color: #202a3a; font-size: 13px; font-weight: 600; }
.tp-provider span {
 display: block; margin-top: 3px; color: #7c8799; font-size: 11px; overflow-wrap: anywhere;
}
.tp-title { margin: 3px 0 24px; }
.tp-title h1 {
 margin: 0; color: var(--tp-ink); font-size: 34px; font-weight: 700;
 line-height: 1.2; letter-spacing: -.025em;
}
.tp-title p {
 margin: 16px 0 0; color: #707b8d; font-size: 15px !important; font-weight: 400;
}
.tp-history-copy { min-width: 0; padding: 2px 0; }
.tp-history-copy strong {
 display: block; overflow: hidden; color: var(--tp-ink) !important;
 font-size: 14px; font-weight: 600; line-height: 1.45;
 text-overflow: ellipsis; white-space: nowrap;
}
.tp-history-copy span {
 display: block; margin-top: 4px; color: var(--tp-sub) !important;
 font-size: 12px; line-height: 1.4;
}
[class*="st-key-history_item_"] {
 margin-bottom: 12px; padding: 10px 12px 10px 16px;
 border: 1px solid var(--tp-line); border-radius: 10px;
 background: var(--tp-surface);
}
[class*="st-key-history_item_"] [data-testid="stHorizontalBlock"] {
 align-items: center; gap: 16px;
}
[class*="st-key-history_item_"] [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
.tp-section-title {
 margin: 0 0 8px; color: #172033; font-size: 23px;
 font-weight: 650; line-height: 1.3;
}
.tp-section-sub { margin: 0 0 16px; color: #718096; font-size: 14px; }
.tp-summary { padding: 18px 20px; }
.tp-summary-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 12px 28px; }
.tp-confirm-card .tp-summary-grid { grid-template-columns: repeat(3,minmax(0,1fr)); }
.tp-summary-item span { display: block; font-size: 12px; color: var(--tp-sub); }
.tp-summary-item strong { display: block; margin-top: 4px; font-size: 14px; color: var(--tp-ink); font-weight: 600; }
.tp-summary-item.is-wide { grid-column: 1 / -1; }
.tp-confirm-stack { display: grid; grid-template-columns: 1.55fr 1fr; gap: 12px; }
.tp-confirm-card { padding: 14px 16px; }
.tp-confirm-head {
 display: flex; align-items: center; gap: 8px; margin-bottom: 12px;
 color: var(--tp-ink); font-size: 14px;
}
.tp-confirm-head .material-symbols-rounded {
 color: var(--tp-primary); font-size: 18px; font-family: "Material Symbols Rounded" !important;
 font-weight: normal; font-style: normal; line-height: 1; font-feature-settings: "liga";
}
.tp-artifact-list { display: grid; grid-template-columns: 1fr; gap: 7px; }
.tp-artifact-row {
 display: grid; grid-template-columns: 28px minmax(0,1fr) auto; align-items: center; gap: 8px;
 min-height: 52px; padding: 7px 10px; border: 1px solid var(--tp-line);
 border-radius: 8px; background: #fbfcfe;
}
.tp-artifact-row > .material-symbols-rounded {
 color: var(--tp-primary); font-size: 19px; font-family: "Material Symbols Rounded" !important;
 font-weight: normal; font-style: normal; line-height: 1; font-feature-settings: "liga";
}
.tp-artifact-row strong { display: block; color: var(--tp-ink); font-size: 13px; }
.tp-artifact-row div span { display: block; margin-top: 2px; color: var(--tp-sub); font-size: 11px; }
.tp-artifact-row b { color: var(--tp-sub); font-size: 10px; font-weight: 650; }
.tp-runtime-card { margin-top: 10px; }
.tp-runtime-grid { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 12px; }
.tp-runtime-grid span { display: block; color: var(--tp-sub); font-size: 11px; }
.tp-runtime-grid strong { display: block; margin-top: 4px; color: var(--tp-ink); font-size: 13px; }
.tp-status { position: relative; padding-left: 13px; }
.tp-status::before {
 content: ""; position: absolute; left: 0; top: 5px; width: 7px; height: 7px;
 border-radius: 50%; background: #98a2b3;
}
.tp-status.is-success::before { background: var(--tp-success); }
.tp-status.is-warning::before { background: #d97706; }
.tp-status.is-error::before { background: var(--tp-danger); }
.tp-flow { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.tp-flow span { font-size: 12px; color: var(--tp-sub); }
.tp-flow b { color: #c4c7ce; font-weight: 500; }

/* ---------- Controls & cards ---------- */
div[data-testid="stVerticalBlockBorderWrapper"] {
 border: 1px solid var(--tp-line); border-radius: 10px;
 background: var(--tp-surface); box-shadow: none;
}
.stButton > button, [data-testid="stDownloadButton"] > button {
 min-height: 44px; border-radius: var(--tp-radius-md); font-weight: 500; cursor: pointer;
 border: 1px solid var(--tp-line); background: var(--tp-surface); color: var(--tp-ink);
 box-shadow: none; transition: border-color .15s ease, background .15s ease, color .15s ease;
}
.stButton > button:hover, [data-testid="stDownloadButton"] > button:hover {
 border-color: #c9d2df; color: #202a3a; background: #f7f9fc;
}
.stButton > button[kind="primary"],
button[data-testid="stBaseButton-primary"] {
 background: var(--tp-primary); border: 1px solid var(--tp-primary); color: #fff;
 border-radius: 9px; box-shadow: none;
}
.stButton > button[kind="primary"]:hover,
button[data-testid="stBaseButton-primary"]:hover {
 background: var(--tp-primary-hover); border-color: var(--tp-primary-hover); color: #fff;
}
.stButton > button[kind="primary"]:active,
button[data-testid="stBaseButton-primary"]:active {
 background: var(--tp-primary-active); border-color: var(--tp-primary-active); color: #fff;
}
.stButton > button:disabled,
button[data-testid="stBaseButton-primary"]:disabled {
 opacity: 1; cursor: not-allowed; box-shadow: none;
 background: #d9e5f6 !important; border-color: #d9e5f6 !important; color: #8ca2c0 !important;
}
.stButton > button:focus-visible, [data-testid="stDownloadButton"] > button:focus-visible,
button[data-baseweb="tab"]:focus-visible, summary:focus-visible {
 outline: 3px solid var(--tp-focus-ring) !important;
 outline-offset: 2px;
}

/* ---------- Tabs ---------- */
[data-testid="stTabs"] [role="tablist"] {
 background: transparent; border-bottom: 1px solid var(--tp-line); padding: 0; gap: 22px;
}
button[data-baseweb="tab"] {
 border-radius: 0 !important; padding: 7px 0 9px; font-weight: 550; color: var(--tp-sub); background: transparent;
}
button[data-baseweb="tab"]:hover { color: var(--tp-primary-hover); }
button[data-baseweb="tab"][aria-selected="true"] {
 background: transparent; color: var(--tp-primary-hover); box-shadow: inset 0 -2px var(--tp-primary);
}
div[data-baseweb="tab-highlight"], div[data-baseweb="tab-border"] { display: none !important; }
[data-testid="stButtonGroup"] [role="radio"][aria-checked="true"] {
 background:var(--tp-primary-soft) !important;
 border-color:#69a7f8 !important;
 color:var(--tp-brand-ink) !important;
}

/* ---------- 输入控件 ---------- */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea {
 border-radius: var(--tp-radius-md) !important; border-color: #dce2ea !important;
 background: var(--tp-surface) !important; color: var(--tp-ink) !important;
 caret-color: var(--tp-ink) !important;
}
[data-testid="stTextInput"] input::placeholder,
[data-testid="stNumberInput"] input::placeholder,
[data-testid="stTextArea"] textarea::placeholder {
 color: var(--tp-sub) !important; opacity: 1 !important;
}
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
[data-baseweb="select"] > div { min-height: 44px; }
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {
 border-color: #69a7f8 !important;
 box-shadow: 0 0 0 3px rgba(18,103,232,.14) !important;
}
.stSelectbox .react-aria-ComboBox > div {
 min-height: 44px; border-radius: var(--tp-radius-md) !important;
 border: 1px solid #dce2ea !important;
 background: var(--tp-surface) !important; color: var(--tp-ink) !important;
 box-shadow: none !important;
}
.stSelectbox [role="combobox"] {
 border: 0 !important; border-radius: 8px !important; background: transparent !important;
 color: var(--tp-ink) !important; box-shadow: none !important;
}
.stSelectbox [role="combobox"] *,
.stSelectbox [role="combobox"] svg { color: var(--tp-ink) !important; fill: currentColor !important; }
.stSelectbox .react-aria-ComboBox button {
 background: transparent !important; border: 0 !important; color: var(--tp-ink) !important;
 box-shadow: none !important;
}
.stSelectbox .react-aria-ComboBox button svg,
.stSelectbox .react-aria-ComboBox button [data-testid="stIconMaterial"] {
 color: var(--tp-ink) !important; fill: currentColor !important; visibility: visible !important;
}
[data-baseweb="select"] > div:focus-within {
 border-color: #69a7f8 !important;
 box-shadow: 0 0 0 3px rgba(18,103,232,.14) !important;
}
.stSelectbox .react-aria-ComboBox > div:focus-within {
 border-color: #69a7f8 !important;
 box-shadow: 0 0 0 3px rgba(18,103,232,.14) !important;
}
[role="listbox"] {
 background: var(--tp-surface) !important; color: var(--tp-ink) !important;
}
[role="listbox"] [role="option"] {
 background: var(--tp-surface) !important; color: var(--tp-ink) !important;
}
[role="listbox"] [role="option"][aria-selected="true"] {
 background: var(--tp-primary-soft) !important; color: var(--tp-brand-ink) !important;
}
[role="listbox"] [role="option"]:hover {
 background: #f6f8fb !important; color: var(--tp-ink) !important;
}
[data-testid="stFileUploaderDropzone"] {
 min-height: 148px; border-radius: var(--tp-radius-lg);
 border: 1px dashed #c8d6ea; background: #fff;
 transition: all .15s ease;
}
[data-testid="stFileUploaderDropzone"]:hover {
 border-color: #79b4ff; background: #f7fbff;
}
.st-key-source_documents { position: relative; }
.tp-source-label {
 margin: 0 0 8px; color: #202a3a; font-size: 15px; font-weight: 600; line-height: 20px;
}
.st-key-source_documents .tp-upload-copy {
 position: absolute; z-index: 2; pointer-events: none; top: 80px; left: 0; right: 0;
 display: flex; flex-direction: column; align-items: center; text-align: center;
}
.tp-upload-copy .material-symbols-rounded {
 margin-bottom: 5px; color: var(--tp-cyan); font-size: 24px;
 font-family: "Material Symbols Rounded" !important; font-weight: normal;
 font-style: normal; line-height: 1; letter-spacing: normal; text-transform: none;
 white-space: nowrap; word-wrap: normal; direction: ltr;
 -webkit-font-feature-settings: "liga"; -webkit-font-smoothing: antialiased;
 font-feature-settings: "liga";
}
.tp-upload-copy span { color: #202a3a; font-size: 14px; font-weight: 600; }
.tp-upload-copy small { margin-top: 7px; color: #8590a2; font-size: 12px; }
.st-key-source_documents [data-testid="stFileUploaderDropzone"] {
 position: relative; padding: 0; align-items: stretch; justify-content: stretch; cursor: pointer;
}
.st-key-source_documents [data-testid="stFileUploaderDropzone"] > div { width: 100%; }
.st-key-source_documents [data-testid="stFileUploaderDropzoneInstructions"] { display: none; }
.st-key-source_documents:not(:has([data-testid="stFileChip"]))
 [data-testid="stFileUploaderDropzone"] button[data-testid="stBaseButton-secondary"] {
 position: absolute; inset: 0; width: 100%; height: 100%; transform: none;
 border: 0 !important; background: transparent !important; color: transparent !important;
}
.st-key-source_documents:not(:has([data-testid="stFileChip"]))
 [data-testid="stFileUploaderDropzone"] button[data-testid="stBaseButton-secondary"] p,
.st-key-source_documents:not(:has([data-testid="stFileChip"]))
 [data-testid="stFileUploaderDropzone"] button[data-testid="stBaseButton-secondary"] svg,
.st-key-source_documents:not(:has([data-testid="stFileChip"]))
 [data-testid="stFileUploaderDropzone"] button[data-testid="stBaseButton-secondary"] [data-testid="stIconMaterial"] {
 visibility: hidden;
}
.st-key-source_documents [data-testid="stFileUploaderDropzone"]:focus-within {
 border-color: var(--tp-primary); background: var(--tp-primary-soft);
 box-shadow: inset 0 0 0 1px rgba(18,103,232,.08), 0 0 0 3px rgba(18,103,232,.14);
}
.st-key-source_documents:has([data-testid="stFileChip"]) .tp-upload-copy {
 display: none !important;
}
.st-key-source_documents:has([data-testid="stFileChip"])
 [data-testid="stFileUploaderDropzone"] {
 min-height: 116px; padding: 14px 16px; cursor: default;
 border-style: solid; border-color: var(--tp-line); background: var(--tp-surface);
}
.st-key-source_documents:has([data-testid="stFileChip"])
 [data-testid="stFileUploaderDropzone"]:hover {
 border-color: var(--tp-line); background: var(--tp-surface);
}
.st-key-source_documents [data-testid="stFileChips"] {
 display: block; width: 100%; max-height: none; overflow: visible;
}
.st-key-source_documents [data-testid="stFileChips"] > div,
.st-key-source_documents [data-testid="stFileChip"] {
 width: 100%; max-width: none;
}
.st-key-source_documents [data-testid="stFileChip"] {
 position: relative; display: flex !important; align-items: flex-start;
 min-height: 86px; padding: 2px 0 32px; gap: 12px;
 border-radius: 0; background: transparent !important; color: var(--tp-ink);
}
.st-key-source_documents [data-testid="stFileChip"] > div:first-child {
 width: 36px; height: 36px; flex: 0 0 36px;
 border-radius: 8px; background: var(--tp-primary-soft) !important;
 color: var(--tp-primary) !important;
}
.st-key-source_documents [data-testid="stFileChipIconSpinner"] {
 display: inline-flex !important; color: var(--tp-primary) !important;
}
.st-key-source_documents [data-testid="stFileChip"] > div:nth-child(2) {
 min-width: 0; padding-top: 1px;
}
.st-key-source_documents [data-testid="stFileChipName"] {
 display: block !important; overflow: hidden; color: var(--tp-ink) !important;
 font-size: 0 !important; font-weight: 600; line-height: 20px;
 text-overflow: ellipsis; white-space: nowrap;
}
.st-key-source_documents [data-testid="stFileChipName"]::before {
 content: attr(title); display: block; overflow: hidden;
 color: var(--tp-ink); font-size: 14px; line-height: 20px;
 text-overflow: ellipsis; white-space: nowrap;
}
.st-key-source_documents [data-testid="stFileChip"] > div:nth-child(2) > div:last-child {
 color: var(--tp-sub) !important; font-size: 12px !important;
}
.st-key-source_documents [data-testid="stFileChipDeleteBtn"] {
 display: flex !important; position: absolute; top: 0; right: 0;
}
.st-key-source_documents [data-testid="stFileChipDeleteBtn"] button {
 width: 30px !important; height: 30px !important; color: #7b8493 !important;
}
.st-key-source_documents [data-testid="stFileChipDeleteBtn"] button:hover {
 color: var(--tp-danger) !important; background: #fef2f2 !important;
}
.st-key-source_documents [data-testid="stFileChip"]::before {
 content: "上传中…"; position: absolute; left: 48px; bottom: 14px;
 color: var(--tp-primary); font-size: 12px; font-weight: 600;
}
.st-key-source_documents [data-testid="stFileChip"]::after {
 content: ""; position: absolute; left: 48px; right: 0; bottom: 2px;
 height: 3px; overflow: hidden; border-radius: 999px;
 background: linear-gradient(90deg, var(--tp-primary-soft) 0%, var(--tp-primary) 50%, var(--tp-primary-soft) 100%);
 background-repeat: no-repeat; background-size: 42% 100%;
 animation: tp-upload-bar 1.15s ease-in-out infinite;
}
.st-key-source_documents [data-testid="stFileUploaderDropzone"] [aria-label="Add files"] {
 display: none !important;
}
.tp-source-file {
 position: relative; display: flex; align-items: center; gap: 12px;
 min-height: 82px; padding: 13px 14px;
 border: 1px solid var(--tp-line); border-radius: 10px; background: var(--tp-surface);
}
.tp-source-file .material-symbols-rounded {
 color: var(--tp-primary); font-size: 22px; font-family: "Material Symbols Rounded" !important;
 font-weight: normal; font-style: normal; line-height: 1; letter-spacing: normal;
 text-transform: none; white-space: nowrap; font-feature-settings: "liga";
}
.tp-source-file .material-symbols-rounded.is-loading { animation: tp-spin .8s linear infinite; }
.tp-source-file-copy { min-width: 0; flex: 1; }
.tp-source-file-copy strong {
 display: -webkit-box; overflow: hidden; color: var(--tp-ink); font-size: 14px;
 line-height: 1.4; overflow-wrap: anywhere; -webkit-box-orient: vertical; -webkit-line-clamp: 2;
}
.tp-source-file-copy span { display: block; margin-top: 3px; color: var(--tp-sub); font-size: 12px; }
.tp-source-file-copy .tp-source-file-status {
 display: inline; margin: 0; color: var(--tp-primary-hover); font-size: 12px;
 font-weight: 600; white-space: nowrap;
}
.tp-source-file-status.is-uploaded, .tp-source-file-status.is-parsing { color: var(--tp-primary); }
.tp-source-file-status.is-parsed { color: var(--tp-success); }
.tp-source-file-status.is-error { color: var(--tp-danger); }
.tp-source-ready {
 position: absolute; right: 14px; bottom: 13px; color: var(--tp-success);
 font-size: 12px; font-weight: 650;
}
@keyframes tp-spin { to { transform: rotate(360deg); } }
@keyframes tp-upload-bar {
 from { background-position: -72% 0; }
 to { background-position: 172% 0; }
}
.st-key-source_file_summary { margin-bottom: 8px; }
.st-key-source_file_card { position: relative; min-height: 82px; }
.st-key-source_file_card .tp-source-file { padding-right: 82px; }
.st-key-source_file_card > [data-testid="stElementContainer"]:has(.tp-source-file) {
 position: relative; z-index: 1;
}
.st-key-source_file_card > [data-testid="stElementContainer"]:has(.stButton) {
 position: absolute !important; right: 8px; top: 8px; z-index: 3;
 width: 36px !important; height: 36px !important;
}
.st-key-source_file_card .stButton {
 width: 36px; height: 36px; margin: 0;
}
.st-key-source_file_card .stButton button {
 min-height: 36px !important; height: 36px !important; width: 36px; padding: 0;
 border-color: transparent !important; color: #7b8493 !important;
 background: transparent !important; box-shadow: none !important;
}
.st-key-source_file_card .stButton button:hover {
 border-color: #fecaca !important; background: #fef2f2 !important;
 color: var(--tp-danger) !important;
}
.st-key-source_file_card .stButton p {
 position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
 overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0;
}
.st-key-target_language_field { max-width: 340px; margin-top: 12px; }
.st-key-target_language_field label,
.st-key-target_language_field [data-testid="stWidgetLabel"] {
 color: #202a3a !important; opacity: 1 !important;
 font-size: 15px !important; font-weight: 600 !important;
}
.tp-field-head { margin-top: 14px; }
.tp-field-head strong { display: block; color: #202a3a; font-size: 15px; font-weight: 600; }
.tp-field-head span { display: block; margin-top: 4px; color: #7c8799; font-size: 13px; }
.st-key-termbase_attach { max-width: 340px; margin-top: 10px; }
.st-key-termbase_attach .stButton > button {
 background: var(--tp-surface) !important; border-color: var(--tp-line) !important;
 color: var(--tp-ink) !important;
}
.st-key-termbase_attach .stButton > button:hover {
 background: #f7f9fc !important; border-color: #c9d2df !important; color: #202a3a !important;
}
.st-key-termbase_picker { max-width: 620px; margin-top: 8px; }
.st-key-termbase_picker [data-testid="stFileUploaderDropzone"] { min-height: 96px; }
.tp-attachment {
 display: flex; align-items: center; min-height: 62px; padding: 11px 13px;
 border: 1px solid var(--tp-line); border-radius: 8px; background: #fff;
}
.tp-attachment strong { display: block; color: var(--tp-ink); font-size: 13px; overflow-wrap: anywhere; }
.tp-attachment span { display: block; margin-top: 3px; color: var(--tp-sub); font-size: 12px; }
.st-key-termbase_attached { max-width: 620px; margin-top: 10px; }
.st-key-termbase_attached [data-testid="stHorizontalBlock"] { align-items: center; }
.st-key-termbase_attached .stButton > button { color: var(--tp-danger); }
/* 操作栏参与正文流：sticky 固定在滚动区底部，滚动到底时停留在文档流末尾，
   不再悬浮覆盖正文。sticky 必须设在包含操作栏的流式 wrapper 上，否则操作栏
   会被自身的短包含块限制而无法吸附到滚动区底部。 */
[data-testid="stMainBlockContainer"] [data-testid="stLayoutWrapper"]:has(.st-key-task_action_bar) {
 position: sticky; bottom: 0; z-index: 20;
}
.st-key-task_action_bar {
 /* margin-top 保证最后一个控件与操作栏之间始终有间距 */
 margin: 48px 0 0; padding: 15px 0; min-height: var(--action-bar-height);
 border-top: 1px solid #e3e8ef; background: rgba(247,248,250,.96);
 -webkit-backdrop-filter: blur(8px); backdrop-filter: blur(8px);
}
.st-key-task_action_bar [data-testid="stHorizontalBlock"] { align-items: center; }
.tp-autosave { color: #667085; font-size: 12px; }
.tp-autosave.is-saved { color: var(--tp-success); }
.st-key-task_action_bar button[data-testid="stBaseButton-primary"] {
 min-width: 180px; min-height: 48px; height: 48px;
 border-radius: 9px; font-size: 15px; font-weight: 500;
 transition: background .18s ease, border-color .18s ease, color .18s ease;
}
.st-key-task_action_bar button[data-testid="stBaseButton-secondary"] {
 min-height: 48px; height: 48px; border-radius: 9px; font-size: 15px; font-weight: 500;
}
.st-key-library_nav .stButton > button {
 display: flex; align-items: center; justify-content: flex-start;
 min-height: 48px; height: 48px; gap: 14px; padding-inline: 10px;
 border-radius: var(--tp-radius-md); color: #536176; font-size: 14px;
 font-weight: 400; text-align: left;
}
.st-key-library_nav .stButton > button > div { width: 100%; }
.st-key-library_nav .stButton > button [data-testid="stIconMaterial"] { flex: 0 0 18px; }
.st-key-library_nav .stButton > button [data-testid="stMarkdownContainer"] { flex: 1 1 auto; min-width: 0; }
.st-key-library_nav .stButton > button > div > span {
 display: grid; grid-template-columns: 18px minmax(0,1fr); column-gap: 14px;
 align-items: center; width: 100%;
}
.st-key-library_nav .stButton > button [data-testid="stIconMaterial"] {
 width: 18px; margin: 0; color: #667085; font-size: 18px;
}
.st-key-library_nav .stButton > button:hover { background: #f6f8fb; color: #202a3a; }
.st-key-library_nav .stButton > button[kind="primary"] {
 background: var(--tp-primary-soft); color: var(--tp-brand-ink); font-weight: 500;
}
.st-key-library_nav .stButton > button p { margin: 0; }
/* ---------- Translation strategy ---------- */
.st-key-preset_cards { margin-top: 0; }
.st-key-preset_cards [data-testid="stHorizontalBlock"] { align-items: stretch; gap: 12px; }
/* 三张卡片等高：列容器已随行拉伸，这里让列内链撑满，避免窄屏下
   流程链换行导致卡片参差。 */
.st-key-preset_cards [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
 display: flex; flex-direction: column;
}
.st-key-preset_cards [data-testid="stHorizontalBlock"] [data-testid="stLayoutWrapper"] {
 flex: 1 1 auto;
}
[class*="st-key-preset_card_"] { position: relative; }
[class*="st-key-preset_card_"] > [data-testid="stElementContainer"] { flex: 1 1 auto; }
[class*="st-key-preset_card_"] [data-testid="stElementContainer"] > [data-testid="stMarkdown"],
[class*="st-key-preset_card_"] [data-testid="stMarkdown"] > div,
[class*="st-key-preset_card_"] [data-testid="stMarkdownContainer"] { height: 100%; }
.tp-preset-card {
 min-height: 182px; padding: 20px 20px 18px;
 display: grid; grid-template-rows: auto 44px 46px auto; row-gap: 8px;
 border: 1.5px solid #dce2ea; border-radius: 12px;
 background: #ffffff; transition: border-color .18s ease, background .18s ease;
}
[class*="st-key-preset_card_"]:hover .tp-preset-card {
 border-color: #c5d1e0; background: #fbfcfe;
}
[class*="st-key-preset_card_"][class*="_selected"] .tp-preset-card {
 border-color: #4e93f4; background: #f7fbff;
}
/* header 行固定 22px：推荐 badge 的行高约 22px，若不固定会让选中卡
   的头部行比其他卡高 2px，破坏三卡横向对齐。 */
.tp-preset-head { display: flex; align-items: center; gap: 10px; min-height: 22px; }
.tp-preset-head .material-symbols-rounded {
 color: #98a2b3; font-family: "Material Symbols Rounded" !important;
 font-size: 18px; font-weight: normal; line-height: 1; font-feature-settings: "liga";
}
[class*="st-key-preset_card_"][class*="_selected"] .tp-preset-head .material-symbols-rounded {
 color: var(--tp-primary);
}
.tp-preset-head strong {
 color: #172033; font-size: 16px; font-weight: 700; line-height: 1.25;
}
[class*="st-key-preset_card_"][class*="_selected"] .tp-preset-head strong {
 color: #15379a;
}
.tp-preset-badge {
 margin-left: auto; padding: 2px 8px; border-radius: 999px;
 background: #eaf2ff; color: #1267e8;
 font-size: 11px; font-weight: 600; line-height: 1.6;
}
/* 四个固定槽位：标题行 / 适用场景(两行) / 流程链(两行) / 标签行。
   grid row-gap 负责间距，p 的内外边距清零（Streamlit 自带 p 规则
   specificity 更高，这里用卡片内选择器覆盖）；flow 字号需要
   !important 才能压过全局 p 字号规则。 */
.tp-preset-card .tp-preset-purpose {
 margin: 0; color: #667085; font-size: 14px; font-weight: 400; line-height: 1.55;
}
.tp-preset-card .tp-preset-flow {
 margin: 0; color: #24324a; font-size: 15px !important;
 font-weight: 600; line-height: 1.5;
}
[class*="st-key-preset_card_"][class*="_selected"] .tp-preset-flow {
 color: #1e2f4d;
}
.tp-preset-tags {
 display: flex; align-items: center; gap: 6px; min-height: 22px;
}
.tp-preset-tag {
 padding: 4px 9px; border-radius: 6px;
 background: #eef1f5; color: #5f6b7a;
 font-size: 11px; font-weight: 500; line-height: 1.4;
}
[class*="st-key-preset_card_"][class*="_selected"] .tp-preset-tag {
 background: #eaf2ff; color: #3c67a8;
}
/* ---------- Step 01 Quick Profiling（风格画像与建议） ---------- */
.tp-style-card {
 border: 1px solid #dce2ea; border-radius: 12px; background: #ffffff;
 padding: 18px 20px 16px; margin: 18px 0 10px;
}
.tp-style-card.is-selected { border-color: #4e93f4; background: #f7fbff; }
.tp-style-card-head { display: flex; align-items: center; gap: 8px; }
.tp-style-card-head .material-symbols-rounded {
 color: var(--tp-primary); font-size: 18px; line-height: 1;
 font-family: "Material Symbols Rounded" !important;
}
.tp-style-card-head strong { font-size: 14px; font-weight: 600; color: #202a3a; }
.tp-style-card-head b {
 margin-left: auto; padding: 2px 8px; border-radius: 999px;
 background: #eaf2ff; color: #1267e8; font-size: 12px; font-weight: 600;
}
.tp-style-card p { margin: 10px 0 0; color: #667085; font-size: 13px; line-height: 1.55; }
.tp-style-name { margin-top: 12px; font-size: 20px; font-weight: 700; color: #172033; }
.tp-style-summary { margin-top: 4px; font-size: 13px; color: #667085; }
.tp-style-reasons { margin-top: 10px; }
.tp-style-reasons span { font-size: 11px; font-weight: 600; color: #8a94a6; }
.tp-style-reasons ul {
 margin: 4px 0 0; padding-left: 16px; color: #5f6b7a;
 font-size: 12.5px; line-height: 1.6;
}
.tp-style-source { margin-top: 10px; font-size: 12px; color: #1f8a57; }
.tp-style-adjust-head { margin: 14px 0 4px; }
.tp-style-adjust-head strong { font-size: 14px; font-weight: 600; color: #202a3a; }
.tp-style-adjust-head span {
 display: block; margin-top: 2px; font-size: 12px; color: #8a94a6;
}
/* “开始智能画像”入口：初始只保留按钮，点击后才出现风格建议卡。
   白色描边 + 品牌蓝文字/图标，与页面次级操作保持一致。 */
.st-key-run_quick_profile { max-width: 420px; }
.st-key-run_quick_profile .stButton > button {
 height: 44px; border: 1px solid var(--tp-border);
 color: var(--tp-brand-ink); font-weight: 600;
 background: var(--tp-surface);
}
.st-key-run_quick_profile .stButton > button:hover {
 border-color: var(--tp-primary); background: var(--tp-primary-soft);
 color: var(--tp-primary);
}
.st-key-run_quick_profile .stButton > button [data-testid="stIconMaterial"] {
 color: var(--tp-primary); font-size: 18px;
}
/* ---------- 首次使用引导 ---------- */
.tp-onboard-card {
 border: 1px solid #dce2ea; border-radius: 12px; background: #ffffff;
 padding: 16px 20px 14px; margin-bottom: 4px;
}
.tp-onboard-card .material-symbols-rounded {
 color: var(--tp-primary); font-size: 18px; line-height: 1;
 font-family: "Material Symbols Rounded" !important;
}
.tp-onboard-card p { margin: 10px 0 0; color: #667085; font-size: 13px; line-height: 1.6; }
.tp-onboard-card ol {
 margin: 6px 0 0; padding-left: 20px; color: #5f6b7a;
 font-size: 13px; line-height: 1.8;
}
[class*="st-key-preset_card_"] .stButton {
 position: absolute; inset: 0; z-index: 3; margin: 0;
}
/* Streamlit 给按钮的 stElementContainer 默认 position: relative，
   会让绝对定位的透明覆盖按钮以 16×22 的按钮容器为包含块，导致整卡
   只有左侧一条窄带可点击。恢复 static 后包含块回到卡片列，按钮才能
   覆盖整张卡片。 */
[class*="st-key-preset_card_"] > [data-testid="stElementContainer"]:has(.stButton) {
 position: static; flex: 0 1 auto;
}
[class*="st-key-preset_card_"] .stButton > button {
 width: 100%; height: 100%; min-height: 0; padding: 0; border: 0 !important;
 background: transparent !important; color: transparent !important; box-shadow: none !important;
}
[class*="st-key-preset_card_"] .stButton > button:focus-visible {
 outline: 3px solid var(--tp-focus-ring) !important; outline-offset: 2px;
}
.st-key-strategy_advanced { margin-top: 16px; }
.st-key-strategy_advanced {
 position: relative; border: 1px solid var(--tp-line); border-radius: 10px;
 background: var(--tp-surface); overflow: hidden;
}
.tp-advanced-trigger {
 display: grid; grid-template-columns: auto minmax(0,1fr); align-items: center; gap: 18px;
 height: 50px; min-height: 50px; padding: 0 14px;
}
.tp-advanced-title { display: inline-flex; align-items: center; gap: 8px; color: var(--tp-ink); }
.tp-advanced-title .material-symbols-rounded {
 color: #667085; font-family: "Material Symbols Rounded" !important; font-size: 18px;
 font-weight: normal; line-height: 1; font-feature-settings: "liga";
}
.tp-advanced-title strong { font-size: 14px; font-weight: 600; }
.st-key-strategy_advanced > [data-testid="stElementContainer"]:has(.stButton) {
 position: absolute; inset: 0 0 auto; z-index: 3; height: 50px;
}
.st-key-strategy_advanced > [data-testid="stElementContainer"]:has(.tp-advanced-trigger) {
 height: 50px;
}
.st-key-strategy_advanced .stButton, .st-key-strategy_advanced .stButton > button {
 width: 100%; height: 50px; min-height: 50px; margin: 0;
}
.st-key-strategy_advanced .stButton > button {
 padding: 0; border: 0 !important; border-radius: 0; background: transparent !important;
 color: transparent !important; box-shadow: none !important;
}
.st-key-strategy_advanced:has(.stButton > button:hover) .tp-advanced-trigger { background: #f8fafc; }
.st-key-strategy_advanced .stButton > button:focus-visible {
 outline: 3px solid var(--tp-focus-ring) !important; outline-offset: -3px;
}
.tp-strategy-state {
 padding: 0; margin: 0 0 22px;
 color: #7c8799; font-size: 12px; font-weight: 400; line-height: 1.5;
}
.tp-strategy-state strong { color: var(--tp-primary-hover); font-weight: 650; }
.st-key-advanced_body {
 gap: 0 !important; border-top: 1px solid var(--tp-line);
 padding: 20px 24px 24px;
}
/* 抵消 Streamlit 对 markdown 容器的 -16px 默认下边距，让上下文行与
   分组标题的间距按声明值精确渲染，不出现文字行重叠。 */
.st-key-advanced_body [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
/* 分组标题：上方 24px 与上一组分开，下方 10px 接本组第一个设置项；
   第一组紧随「当前使用…」上下文行，不再额外加 24px。 */
.tp-advanced-group {
 margin: 24px 0 10px; padding: 0;
 color: #6f7b8d; font-size: 12px; font-weight: 600; line-height: 1.4;
 letter-spacing: 0.01em;
}
.st-key-advanced_body > [data-testid="stElementContainer"]:nth-child(2) .tp-advanced-group {
 margin-top: 0;
}
/* 设置行：单个视觉单元，文本列最宽 640px，开关固定在右侧列。 */
[class*="st-key-strategy_"][class*="_row"] {
 min-height: 62px; margin: 0; justify-content: center;
}
/* 行间细分隔线：设置行各自包在 stLayoutWrapper 里，选择器作用于
   advanced_body 的直接子容器（行包装器 / 只读行容器）。 */
.st-key-advanced_body > [data-testid="stLayoutWrapper"] + [data-testid="stLayoutWrapper"],
.st-key-advanced_body > [data-testid="stElementContainer"]:has(.tp-readonly-setting) + [data-testid="stLayoutWrapper"] {
 border-top: 1px solid #f0f2f5; padding-top: 14px;
}
[class*="st-key-strategy_"][class*="_row"] [data-testid="stHorizontalBlock"] {
 display: grid; grid-template-columns: minmax(0, 640px) minmax(48px, auto);
 justify-content: space-between; align-items: center; column-gap: 32px;
}
[class*="st-key-strategy_"][class*="_row"] [data-testid="stColumn"]:last-child {
 display: flex; align-items: center; justify-content: flex-end; min-width: 48px;
}
[class*="st-key-strategy_"][class*="_row"] [data-testid="stColumn"]:last-child > [data-testid="stVerticalBlock"],
[class*="st-key-strategy_"][class*="_row"] [data-testid="stColumn"]:last-child [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"],
[class*="st-key-strategy_"][class*="_row"] [data-testid="stColumn"]:last-child [data-testid="stElementContainer"] > [data-testid="stCheckbox"] {
 width: 100%;
}
[class*="st-key-strategy_"][class*="_row"] [data-testid="stColumn"]:last-child [data-testid="stCheckbox"] {
 display: flex; justify-content: flex-end;
}
.tp-setting-copy { padding: 0; max-width: 640px; }
.tp-setting-copy strong {
 display: block; color: #202a3a; font-size: 14px; font-weight: 600; line-height: 1.35;
}
.tp-setting-copy span {
 display: block; margin-top: 4px; color: #7a8699; font-size: 12.5px; line-height: 1.55;
}
.st-key-strategy_advanced [data-testid="stToggle"],
.st-key-output_options [data-testid="stToggle"],
.st-key-academic_output_options [data-testid="stToggle"] { margin: 0; }
[class*="st-key-strategy_"][class*="_row"] [data-testid="stToggle"] {
 display: flex; justify-content: flex-end;
}
[class*="st-key-strategy_"][class*="_row"] [data-testid="stToggle"] label {
 min-height: 44px; padding: 0;
}
.st-key-strategy_advanced [data-testid="stToggle"] label,
.st-key-output_options [data-testid="stToggle"] label,
.st-key-academic_output_options [data-testid="stToggle"] label {
 min-height: 38px; padding: 6px 0; color: var(--tp-ink) !important;
}
.st-key-strategy_advanced [data-testid="stToggle"] [role="switch"],
.st-key-output_options [data-testid="stToggle"] [role="switch"],
.st-key-academic_output_options [data-testid="stToggle"] [role="switch"] {
 width: 36px !important; min-width: 36px !important; height: 20px !important;
 background: #c6ceda !important; border-color: #c6ceda !important;
}
label:has(input[role="switch"]) > div:first-of-type {
 width: 36px !important; min-width: 36px !important; height: 20px !important;
 background: #c6ceda !important; border-color: #c6ceda !important;
}
label:has(input[role="switch"]) > div:first-of-type > div {
 width: 16px !important; height: 16px !important;
}
label[data-selected="true"]:has(input[role="switch"]) > div:first-of-type {
 background: var(--tp-primary) !important; border-color: var(--tp-primary) !important;
}
label:has(input[type="checkbox"]:not([role="switch"])) > div:first-of-type {
 background: var(--tp-surface) !important; border-color: #98a2b3 !important;
}
label[data-selected="true"]:has(input[type="checkbox"]:not([role="switch"])) > div:first-of-type {
 background: var(--tp-primary) !important; border-color: var(--tp-primary) !important;
}
.st-key-strategy_advanced [data-testid="stToggle"] label[data-selected="true"] > div:first-of-type,
.st-key-output_options [data-testid="stToggle"] label[data-selected="true"] > div:first-of-type,
.st-key-academic_output_options [data-testid="stToggle"] label[data-selected="true"] > div:first-of-type,
.st-key-output_report label[data-selected="true"] > div:first-of-type,
.st-key-output_annotate label[data-selected="true"] > div:first-of-type,
.st-key-strategy_auto_term label[data-selected="true"] > div:first-of-type,
.st-key-strategy_use_tm label[data-selected="true"] > div:first-of-type,
.st-key-strategy_review label[data-selected="true"] > div:first-of-type,
.st-key-strategy_strict_terms label[data-selected="true"] > div:first-of-type {
 background: var(--tp-primary) !important; border-color: var(--tp-primary) !important;
}
.st-key-strategy_advanced [data-testid="stToggle"] label:has(input:focus-visible) > div:first-of-type,
.st-key-output_options [data-testid="stToggle"] label:has(input:focus-visible) > div:first-of-type,
.st-key-academic_output_options [data-testid="stToggle"] label:has(input:focus-visible) > div:first-of-type,
.st-key-strategy_advanced [data-testid="stCheckbox"] label:has(input:focus-visible) > div:first-of-type,
.st-key-output_options [data-testid="stCheckbox"] label:has(input:focus-visible) > div:first-of-type,
label:has(input[role="switch"]:focus-visible) > div:first-of-type,
label:has(input[type="checkbox"]:not([role="switch"]):focus-visible) > div:first-of-type {
 box-shadow: 0 0 0 3px var(--tp-focus-ring) !important;
}
.st-key-strategy_advanced [data-testid="stToggle"] p,
.st-key-output_options [data-testid="stToggle"] p,
.st-key-academic_output_options [data-testid="stToggle"] p { color: var(--tp-ink) !important; }
.st-key-strategy_advanced [data-testid="stCheckbox"] p,
.st-key-output_options [data-testid="stCheckbox"] p { color: var(--tp-ink) !important; }
.st-key-strategy_advanced [data-testid="stCheckbox"] label > div:first-of-type,
.st-key-output_options [data-testid="stCheckbox"] label > div:first-of-type {
 background: var(--tp-surface) !important; border-color: #98a2b3 !important;
}
.st-key-strategy_advanced [data-testid="stCheckbox"] label[data-selected="true"] > div:first-of-type,
.st-key-output_options [data-testid="stCheckbox"] label[data-selected="true"] > div:first-of-type {
 background: var(--tp-primary) !important; border-color: var(--tp-primary) !important;
}
.st-key-strategy_advanced [data-testid="stCheckbox"] label[data-selected="true"] svg,
.st-key-output_options [data-testid="stCheckbox"] label[data-selected="true"] svg {
 stroke: #fff !important;
}
.st-key-output_options [data-testid="stCaptionContainer"] {
 margin: -8px 0 0; color: var(--tp-sub); font-size: 12px;
}
.tp-readonly-setting {
 padding: 7px 0 7px;
}
.tp-readonly-head { display: flex; align-items: center; gap: 9px; }
.tp-readonly-setting strong { color: var(--tp-ink); font-size: 14px; font-weight: 550; }
.tp-readonly-setting span { display: block; margin-top: 3px; color: var(--tp-sub); font-size: 12px; }
.tp-readonly-setting b {
 flex: 0 0 auto; padding: 2px 7px; border-radius: 999px; background: #ecfdf3;
 color: #15803d; font-size: 11px; font-weight: 650;
}
/* 高级设置面板内的只读行（基础一致性检查）与开关行使用同一套行节奏；
   Step 03 输出页的只读行保持原样式。 */
.st-key-advanced_body .tp-readonly-setting {
 min-height: 62px; padding: 0;
}
.st-key-advanced_body .tp-readonly-head { display: flex; align-items: center; gap: 8px; }
.st-key-advanced_body .tp-readonly-setting strong {
 color: #202a3a; font-size: 14px; font-weight: 600; line-height: 1.35;
}
.st-key-advanced_body .tp-readonly-setting span {
 display: block; margin-top: 4px; color: #7a8699; font-size: 12.5px; line-height: 1.55;
}
.st-key-advanced_body .tp-readonly-setting b {
 flex: 0 0 auto; padding: 2px 7px; border-radius: 999px;
 background: #eaf8f0; color: #1f8a57;
 font-size: 10.5px; font-weight: 600; line-height: 1.5;
}
.st-key-output_options { max-width: 760px; margin-top: 14px; }
.tp-output-section { margin-top: 18px; }
.tp-output-section-head { margin-bottom: 8px; }
.tp-output-section-head strong { display: block; color: var(--tp-ink); font-size: 14px; }
.tp-output-section-head span { display: block; margin-top: 3px; color: var(--tp-sub); font-size: 12px; }
.st-key-style_output { max-width: 760px; }
.st-key-style_output .stSelectbox { max-width: 340px; }
.tp-style-note {
 margin-top: 8px; padding: 12px 14px; border: 1px solid var(--tp-line);
 border-radius: 8px; background: #fbfcfe;
}
.tp-style-note strong { display: block; margin-bottom: 6px; color: var(--tp-ink); font-size: 12px; }
.tp-style-note ul { margin: 0; padding-left: 18px; }
.tp-style-note li { margin: 3px 0; color: #475467; font-size: 12px; line-height: 1.5; }
.st-key-academic_output_options {
 max-width: 760px; margin-top: 16px; padding-top: 2px; border-top: 1px solid var(--tp-line);
}
.st-key-academic_output_options .stSelectbox { max-width: 520px; }
.st-key-engine_setup_banner [data-testid="stAlert"] {
 border: 1px solid #f6c66a !important; background: #fffbeb !important;
 color: #78350f !important;
}
.st-key-engine_setup_banner [data-testid="stAlert"] p,
.st-key-engine_setup_banner [data-testid="stAlert"] [data-testid="stMarkdownContainer"],
.st-key-engine_setup_banner [data-testid="stAlert"] [data-testid="stIconMaterial"] {
 color: #78350f !important; opacity: 1 !important; visibility: visible !important;
}
.st-key-engine_setup_banner [data-testid="stHorizontalBlock"] { align-items: center; gap: 12px; }
.st-key-engine_setup_banner .stButton > button {
 min-height: 36px; background: #fff; border-color: #f3c35c; color: #92400e;
}
.st-key-analysis_theory { max-width: 520px; margin-top: 8px; }
.tp-report-helper { margin: 0 0 4px; color: var(--tp-sub); font-size: 12px; }

/* ---------- 容器类组件 ---------- */
[data-testid="stExpander"] {
 border: 1px solid var(--tp-line) !important;
 border-radius: 10px !important; background: #fff; box-shadow: none; overflow: hidden;
}
[data-testid="stExpander"] summary { font-weight: 600; color: var(--tp-ink); }
[data-testid="stExpander"] summary:hover { color: var(--tp-primary-hover); }
[data-testid="stAlert"] { border-radius: 8px; }
[data-testid="stAlertContainer"] {
 border: 1px solid var(--tp-line) !important;
 border-radius: 8px !important;
}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) {
 background: #eff6ff !important; border-color: #bfdbfe !important;
}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) {
 background: #ecfdf3 !important; border-color: #b7e2c7 !important;
}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) {
 background: #fff7e6 !important; border-color: #f0cf8a !important;
}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) {
 background: #fff1f0 !important; border-color: #f2c3c0 !important;
}
[data-testid="stAlertContentInfo"],
[data-testid="stAlertContentInfo"] [data-testid="stMarkdownContainer"],
[data-testid="stAlertContentInfo"] p {
 color: #1e40af !important; opacity: 1 !important;
}
[data-testid="stAlertContentSuccess"],
[data-testid="stAlertContentSuccess"] [data-testid="stMarkdownContainer"],
[data-testid="stAlertContentSuccess"] p {
 color: #147a4a !important; opacity: 1 !important;
}
[data-testid="stAlertContentWarning"],
[data-testid="stAlertContentWarning"] [data-testid="stMarkdownContainer"],
[data-testid="stAlertContentWarning"] p {
 color: #8a5a00 !important; opacity: 1 !important;
}
[data-testid="stAlertContentError"],
[data-testid="stAlertContentError"] [data-testid="stMarkdownContainer"],
[data-testid="stAlertContentError"] p {
 color: #b42318 !important; opacity: 1 !important;
}
[data-testid="stAlertContentInfo"] p,
[data-testid="stAlertContentSuccess"] p,
[data-testid="stAlertContentWarning"] p,
[data-testid="stAlertContentError"] p { margin: 0; }
[data-testid="stDataFrame"] {
 border: 1px solid var(--tp-line); border-radius: 12px; overflow: hidden;
}
[data-testid="stProgress"] [role="progressbar"] > div { background: var(--tp-primary); }
[data-testid="stStatusWidget"] {
 border-radius: 14px; border-color: var(--tp-line) !important;
}
.st-key-task_action_bar .stButton button > div > span {
 display: flex; align-items: center; justify-content: center; gap: 8px;
}
.st-key-task_action_bar .stButton button [data-testid="stMarkdownContainer"] { order: 1; }
.st-key-task_action_bar .stButton button [data-testid="stIconMaterial"] { order: 2; }
.st-key-task_action_bar [class*="st-key-back_to_"] button [data-testid="stMarkdownContainer"] { order: 2; }
.st-key-task_action_bar [class*="st-key-back_to_"] button [data-testid="stIconMaterial"] { order: 1; }

/* ---------- 响应式与减少动态效果 ---------- */
@media (max-width: 1439px) {
 :root { --tp-main-gutter: 48px; }
}

@media (max-width: 1279px) {
 :root { --tp-main-gutter: 32px; }
}

@media (max-width: 767px) {
 :root { --tp-main-gutter: 14px; }
 [data-testid="stSidebar"] {
  width: var(--tp-sidebar-width); min-width: var(--tp-sidebar-width);
 }
 [data-testid="stMainBlockContainer"] { width: 100%; padding: 1rem .875rem 3rem; }
 .tp-title h1 { font-size: 26px; }
 .tp-summary-grid { grid-template-columns: 1fr; gap: 14px; }
 .tp-confirm-card .tp-summary-grid { grid-template-columns: 1fr; }
 .tp-summary-item.is-wide { grid-column: auto; }
 .tp-confirm-stack { grid-template-columns: 1fr; }
 .tp-artifact-list, .tp-runtime-grid { grid-template-columns: 1fr; }
 .st-key-preset_cards [data-testid="stHorizontalBlock"] { flex-direction: column; }
 .tp-advanced-trigger { grid-template-columns: 1fr; gap: 0; }
 [data-testid="stTabs"] [role="tablist"] { overflow-x: auto; scrollbar-width: none; }
 [data-testid="stTabs"] [role="tablist"]::-webkit-scrollbar { display: none; }
 button[data-baseweb="tab"] { min-height: 40px; white-space: nowrap; }
 .st-key-target_language_field, .st-key-termbase_attach, .st-key-termbase_picker,
 .st-key-termbase_attached { max-width: none; }
 .st-key-provider_status { position: static; width: auto; }
}

@media (prefers-reduced-motion: reduce) {
 *, *::before, *::after {
 scroll-behavior: auto !important;
 transition-duration: .01ms !important;
 animation-duration: .01ms !important;
 animation-iteration-count: 1 !important;
 }
}
"""

# Workspace-specific shell.  The setup flow keeps the existing product shell;
# once a task is open this replaces it with a focused project workspace.
_WORKSPACE_CSS = """
.stApp:has(.tp-workspace-shell) [data-testid="stSidebar"] { display: none !important; }
[data-testid="stMainBlockContainer"]:has(.tp-workspace-shell) {
 width: min(100%, 1440px); max-width: 1440px; margin: 0 auto;
 padding: 10px 32px 44px;
}
.tp-workspace-shell { min-height: 2px; }
.st-key-workspace_exit_actions { margin-bottom:0; }
.st-key-workspace_exit_actions .stButton > button {
 min-height:28px; height:28px; padding:0 8px; border-color:transparent; background:transparent;
 color:var(--tp-sub); font-size:12px; justify-content:flex-start;
}
.st-key-workspace_exit_actions .stButton > button:hover {
 border-color:var(--tp-line); background:#fff; color:var(--tp-ink);
}
.tp-workspace-topbar {
 display:flex; align-items:flex-start; justify-content:space-between; gap:24px;
 padding: 0 0 6px; border-bottom:1px solid var(--tp-line);
}
.tp-workspace-topbar h1 { margin:0; padding:0 !important; font-size:20px !important; line-height:1.2 !important; }
.tp-workspace-eyebrow { margin-bottom:3px; color:var(--tp-sub); font-size:10px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; }
.tp-workspace-meta { margin-top:4px; color:var(--tp-sub); font-size:11px; }
.tp-workspace-status { display:flex; align-items:center; gap:8px; padding-top:4px; color:var(--tp-sub); font-size:12px; white-space:nowrap; }
.tp-status-dot { width:9px; height:9px; border-radius:50%; background:#f59e0b; }
.tp-status-dot.is-success { background:var(--tp-success); }
.tp-status-dot.is-danger { background:var(--tp-danger); }
.tp-status-dot.is-neutral { background:#94a3b8; }
.tp-workspace-layout { margin-top:10px; }
.st-key-workspace_nav_col, .st-key-workspace_context_col, .st-key-workspace_main_col { min-width:0; }
.st-key-workspace_nav_col {
 position:sticky; top:18px; align-self:flex-start; z-index:10;
 padding-right:18px; border-right:1px solid var(--tp-line-subtle);
 min-height:calc(100vh - 112px);
}
.tp-workspace-nav-title { margin:2px 0 8px; color:var(--tp-ink); font-size:11px; font-weight:750; letter-spacing:.04em; text-transform:uppercase; }
.tp-workspace-nav-caption { margin:0 0 10px; color:var(--tp-sub); font-size:11px; line-height:1.45; }
.st-key-workspace_nav .stButton > button {
 min-height:36px; margin:1px 0; justify-content:flex-start; padding:0 10px;
 border-color:transparent; background:transparent; color:#536176; font-size:13px;
}
.st-key-workspace_nav .stButton > button:hover { background:#f4f7fb; border-color:transparent; color:var(--tp-ink); }
.st-key-workspace_nav .stButton > button[kind="primary"] {
 background:var(--tp-primary-soft); border-color:transparent; color:var(--tp-brand-ink); font-weight:650;
}
.st-key-workspace_nav [class*="st-key-workspace_nav_item_"] {
 margin:2px 0; border-radius:9px;
}
.st-key-workspace_nav [class*="st-key-workspace_nav_item_"] [data-testid="stHorizontalBlock"] {
 align-items:center; gap:4px;
}
.tp-nav-state {
 display:block; min-width:48px; color:var(--tp-faint); font-size:10px; font-weight:750;
 line-height:1.2; text-align:right; white-space:nowrap;
}
.tp-nav-state.is-done { color:#147a4a; }
.tp-nav-state.is-attention { color:#b42318; }
.tp-nav-state.is-stale { color:#8a5a00; }
.tp-nav-state.is-pending { color:#8a5a00; }
.tp-nav-state.is-neutral { color:var(--tp-faint); }
.tp-nav-state.is-empty { color:transparent; }
.tp-nav-state[title] { cursor:help; }
.tp-workspace-nav-item { display:flex; align-items:center; gap:10px; }
.tp-workspace-nav-item i { width:7px; height:7px; border:1.5px solid currentColor; border-radius:50%; }
.tp-workspace-nav-item.is-active i { background:currentColor; }
.st-key-workspace_main_col { padding:0 22px; }
.tp-workspace-main h2 { margin:2px 0 5px; font-size:21px !important; }
.tp-workspace-main h3 { margin:0; font-size:15px !important; }
.tp-section-kicker { color:var(--tp-sub); font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.06em; }
.tp-section-lead { margin:5px 0 18px; color:var(--tp-sub); font-size:13px; }
.tp-overview-hero { padding:22px 24px; border:1px solid #d8e5fa; border-radius:14px; background:linear-gradient(135deg,#f8fbff,#fff); }
.tp-overview-hero strong { display:block; color:var(--tp-ink); font-size:19px; }
.tp-overview-hero p { margin:8px 0 16px; color:var(--tp-sub); font-size:13px; }
.tp-runtime-panel { margin:0 0 18px; padding:20px 22px; border:1px solid #c9dcfb; border-radius:14px; background:linear-gradient(135deg,#f8fbff,#fff); }
.tp-runtime-kicker { color:var(--tp-primary); font-size:12px; font-weight:750; letter-spacing:.04em; }
.tp-runtime-head { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; margin-top:7px; }
.tp-runtime-head h3 { margin:0; color:var(--tp-ink); font-size:19px !important; }
.tp-runtime-head p { margin:5px 0 0; color:var(--tp-sub); font-size:13px; line-height:1.5; }
.tp-runtime-phase { display:flex; align-items:center; gap:8px; margin-top:17px; color:var(--tp-ink); font-size:14px; font-weight:700; }
.tp-runtime-phase .dot { width:9px; height:9px; border-radius:50%; background:var(--tp-primary); box-shadow:0 0 0 4px #e3efff; }
.tp-runtime-phase.is-warning .dot { background:#c47b00; box-shadow:0 0 0 4px #fff1cf; }
.tp-runtime-phase.is-danger .dot { background:var(--tp-danger); box-shadow:0 0 0 4px #ffe3e3; }
.tp-runtime-meta { display:flex; flex-wrap:wrap; gap:6px 18px; margin-top:8px; color:var(--tp-sub); font-size:12px; font-variant-numeric:tabular-nums; }
.tp-runtime-progress-head { display:flex; justify-content:space-between; gap:12px; margin-top:18px; color:var(--tp-sub); font-size:12px; }
.tp-runtime-progress-head strong { color:var(--tp-ink); font-variant-numeric:tabular-nums; }
.tp-runtime-bar { height:8px; margin-top:7px; overflow:hidden; border-radius:999px; background:#e7eef9; }
.tp-runtime-bar i { display:block; height:100%; border-radius:inherit; background:var(--tp-primary); transition:width .2s ease; }
.tp-runtime-step-title { margin-top:18px; color:var(--tp-ink); font-size:13px; font-weight:750; }
.tp-runtime-steps { margin-top:7px; padding-left:0; list-style:none; }
.tp-runtime-steps li { position:relative; padding:5px 0 5px 24px; color:var(--tp-sub); font-size:12px; }
.tp-runtime-steps li::before { content:"○"; position:absolute; left:0; color:#9aa7b8; font-size:16px; line-height:1; }
.tp-runtime-steps li.is-current { color:var(--tp-ink); font-weight:650; }
.tp-runtime-steps li.is-current::before { content:"●"; color:var(--tp-primary); }
.tp-runtime-steps li.is-done { color:var(--tp-sub); }
.tp-runtime-steps li.is-done::before { content:"✓"; color:var(--tp-success); font-weight:750; }
.tp-runtime-alert { margin-top:13px; padding:9px 11px; border-radius:8px; background:#fff5e6; color:#8a5a00; font-size:12px; line-height:1.5; }
.tp-runtime-alert.is-danger { background:#fff0f0; color:#a12222; }
.tp-runtime-event { display:flex; gap:12px; padding:6px 0; color:var(--tp-sub); font-size:12px; line-height:1.45; }
.tp-runtime-event time { flex:0 0 62px; color:var(--tp-faint); font-variant-numeric:tabular-nums; }
.tp-runtime-event span { color:var(--tp-ink); }
.tp-status-badge { display:inline-flex; align-items:center; gap:6px; padding:5px 10px; border-radius:999px; background:#fff7e6; color:#9a6700; font-size:12px; font-weight:700; }
.tp-status-badge.is-success { background:#eaf8f1; color:#147a4a; }
.tp-status-badge.is-danger { background:#fff0f0; color:#b42318; }
.tp-status-badge.is-neutral { background:#f1f4f8; color:#536176; }
.tp-card-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin:18px 0 26px; }
.tp-summary-card { min-height:142px; padding:17px 17px 14px; border:1px solid var(--tp-line); border-radius:12px; background:#fff; }
.tp-summary-card strong { display:block; color:var(--tp-ink); font-size:14px; }
.tp-summary-card b { display:block; margin-top:15px; color:var(--tp-ink); font-size:23px; line-height:1; }
.tp-summary-card span { display:block; margin-top:7px; color:var(--tp-sub); font-size:12px; }
.tp-stage-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin:18px 0 28px; }
.tp-stage-card { min-height:142px; padding:17px; border:1px solid var(--tp-line); border-radius:12px; background:#fff; }
.tp-stage-card strong { display:block; color:var(--tp-ink); font-size:14px; }
.tp-stage-card b { display:block; margin-top:14px; color:var(--tp-ink); font-size:21px; line-height:1; font-variant-numeric:tabular-nums; }
.tp-stage-card span { display:block; margin-top:8px; color:var(--tp-sub); font-size:12px; }
.tp-stage-card.is-active { border-color:#b9d3f8; background:#f8fbff; }
.tp-stage-card.is-done strong::before { content:"✓"; margin-right:7px; color:var(--tp-success); }
.tp-stage-card.is-active strong::before { content:"●"; margin-right:7px; color:var(--tp-primary); font-size:11px; vertical-align:1px; }
[class*="st-key-overview_stage_card_"] {
 min-height:178px; padding:0 17px 14px; border:1px solid var(--tp-line);
 border-radius:12px; background:#fff;
}
[class*="st-key-overview_stage_card_"]:has(.tp-stage-card-content.is-active) {
 border-color:#b9d3f8; background:#f8fbff;
}
[class*="st-key-overview_stage_card_"] .stButton > button { margin-top:12px; }
.tp-stage-card-content { padding-top:17px; }
.tp-stage-card-content strong { display:block; color:var(--tp-ink); font-size:14px; }
.tp-stage-card-content b { display:block; margin-top:14px; color:var(--tp-ink); font-size:21px; line-height:1; font-variant-numeric:tabular-nums; }
.tp-stage-card-content span { display:block; margin-top:8px; color:var(--tp-sub); font-size:12px; }
.tp-stage-card-content.is-done strong::before { content:"✓"; margin-right:7px; color:var(--tp-success); }
.tp-stage-card-content.is-active strong::before { content:"●"; margin-right:7px; color:var(--tp-primary); font-size:11px; vertical-align:1px; }
.tp-overview-progress { display:flex; align-items:center; flex-wrap:wrap; gap:8px; margin:0 0 28px; padding:10px 0; border-top:1px solid var(--tp-line-subtle); border-bottom:1px solid var(--tp-line-subtle); }
.tp-progress-step { display:inline-flex; align-items:center; gap:6px; color:var(--tp-ink); font-size:12px; white-space:nowrap; }
.tp-progress-step i { font-style:normal; color:var(--tp-success); font-size:14px; }
.tp-progress-step.is-active i { color:var(--tp-primary); }
.tp-progress-step.is-pending i { color:#94a3b8; }
.tp-step-connector { color:#b6c0ce; font-size:13px; }
.tp-section-label { margin:0 0 10px; color:var(--tp-ink); font-size:14px; font-weight:700; }
.tp-activity { position:relative; margin-left:5px; padding:5px 0 2px 20px; border-left:1px solid #dbe3ee; }
.tp-activity-date { margin:0 0 5px; color:var(--tp-faint); font-size:12px; font-variant-numeric:tabular-nums; }
.tp-activity-row { position:relative; display:block; padding:8px 0; color:var(--tp-ink); font-size:13px; }
.tp-activity-row::before { content:""; position:absolute; left:-25px; top:14px; width:8px; height:8px; border:2px solid #fff; border-radius:50%; background:#9bbdf0; box-shadow:0 0 0 1px #9bbdf0; }
.tp-activity-row time { display:none; }
.st-key-workspace_context_col {
 position:sticky; top:18px; align-self:flex-start; padding-left:14px;
}
.tp-info-card { padding:14px; border:1px solid var(--tp-line); border-radius:10px; background:#fff; }
.tp-info-card + .tp-info-card { margin-top:10px; }
.tp-info-card h3 { margin:0 0 10px; }
.tp-info-stat { display:flex; align-items:baseline; justify-content:space-between; gap:8px; padding:7px 0; border-bottom:1px solid var(--tp-line-subtle); }
.tp-info-stat:last-child { border-bottom:0; }
.tp-info-stat span { color:var(--tp-sub); font-size:11px; }
.tp-info-stat b { color:var(--tp-ink); font-size:13px; font-variant-numeric:tabular-nums; }
.tp-version-compare { padding:14px; border:1px solid var(--tp-line); border-radius:10px; background:#fff; }
.tp-version-compare h3 { margin:0 0 10px; color:var(--tp-ink); font-size:15px !important; }
.tp-version-row { display:flex; align-items:baseline; justify-content:space-between; gap:10px; padding:8px 0; border-bottom:1px solid var(--tp-line-subtle); }
.tp-version-row:last-of-type { border-bottom:0; }
.tp-version-row span { color:var(--tp-sub); font-size:11px; }
.tp-version-row strong { color:var(--tp-ink); font-size:12px; text-align:right; }
.tp-version-compare-status { margin-top:10px; padding:8px 9px; border-radius:7px; background:#f1f4f8; color:var(--tp-sub); font-size:11px; line-height:1.45; }
.tp-version-compare-status.is-warning { background:#fff7e6; color:#8a5a00; }
.tp-version-compare-status.is-success { background:#eaf8f1; color:#147a4a; }
.tp-version-technical { margin-top:8px; color:var(--tp-faint); font-size:10px; line-height:1.45; }
.tp-truth-banner { margin:0 0 18px; padding:14px 16px; border:1px solid #bdd5fb; border-left:4px solid var(--tp-primary); border-radius:10px; background:#f5f9ff; }
.tp-truth-banner strong { display:block; color:var(--tp-brand-ink); font-size:14px; }
.tp-truth-banner p { margin:5px 0 0; color:var(--tp-sub); font-size:12px; line-height:1.55; }
.tp-truth-banner small { display:block; margin-top:7px; color:#536176; font-size:11px; line-height:1.45; }
.tp-truth-kicker { display:block; margin-bottom:5px; color:var(--tp-primary); font-size:10px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
.tp-transport-alert { margin:12px 0; padding:12px 14px; border:1px solid #efc1bd; border-left:4px solid var(--tp-danger); border-radius:9px; background:#fff7f6; color:#7f1d1d; }
.tp-transport-alert strong { display:block; font-size:12px; }
.tp-transport-alert p { margin:5px 0; color:#7f1d1d; font-size:12px; line-height:1.5; }
.tp-transport-alert span { color:#9f3d37; font-size:11px; line-height:1.45; }
.tp-dependency-panel { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; margin:0 0 16px; padding:14px 16px; border:1px solid #f0d5a1; border-radius:10px; background:#fffaf0; }
.tp-dependency-panel strong { color:#714c00; font-size:13px; }
.tp-dependency-panel p { margin:4px 0 0; color:#8a5a00; font-size:12px; line-height:1.45; }
.tp-dependency-panel span { align-self:center; color:#714c00; font-size:11px; font-weight:650; line-height:1.45; text-align:right; }
.tp-dependency-panel small { align-self:center; color:#8a6a24; font-size:11px; line-height:1.45; }
.tp-case-head { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; margin-bottom:12px; }
.tp-case-head h3 { margin:2px 0 4px; font-size:18px !important; }
.tp-case-head p { margin:0; color:var(--tp-sub); font-size:12px; line-height:1.5; }
.tp-case-validity { flex:0 0 auto; padding:5px 8px; border-radius:999px; font-size:10px; font-weight:800; letter-spacing:.02em; white-space:nowrap; }
.tp-case-validity.is-valid { background:#eaf8f1; color:#147a4a; }
.tp-case-validity.is-stale { background:#fff7e6; color:#8a5a00; }
.tp-case-validity.is-pending { background:#fff8e8; color:#8a5a00; }
.tp-case-role-grid { display:grid; grid-template-columns:90px minmax(0,1fr); gap:5px 10px; margin:0 0 14px; padding:10px 12px; border:1px solid var(--tp-line-subtle); border-radius:8px; background:#fbfcfe; }
.tp-case-role-grid { grid-template-columns:minmax(110px,.42fr) minmax(0,1fr); }
.tp-case-role-grid span { color:var(--tp-sub); font-size:11px; white-space:nowrap; }
.tp-case-role-grid b { color:var(--tp-ink); font-size:11px; font-weight:700; }
.tp-case-text { min-height:110px; margin-bottom:12px; padding:12px; border:1px solid var(--tp-line); border-radius:9px; background:#fff; }
.tp-case-text label { display:block; margin-bottom:7px; color:var(--tp-sub); font-size:10px !important; font-weight:800; letter-spacing:.06em; text-transform:uppercase; }
.tp-case-text p { margin:0; color:var(--tp-ink); font-size:12px; line-height:1.7; white-space:pre-wrap; }
.tp-case-detail-label { margin:16px 0 8px; color:var(--tp-sub); font-size:11px; font-weight:800; letter-spacing:.04em; text-transform:uppercase; }
.tp-case-evidence-grid { display:grid; grid-template-columns:1fr 1fr; gap:0 12px; padding:10px 12px; border:1px solid var(--tp-line); border-radius:9px; background:#fbfcfe; }
.tp-case-evidence-grid span, .tp-case-evidence-grid b { padding:6px 0; border-bottom:1px solid var(--tp-line-subtle); font-size:11px; }
.tp-case-evidence-grid span { color:var(--tp-sub); }
.tp-case-evidence-grid b { color:var(--tp-ink); text-align:right; }
.tp-qa-profile { display:flex; align-items:baseline; flex-wrap:wrap; gap:8px 16px; margin-bottom:18px; padding:14px 16px; border:1px solid #c9dcfb; border-radius:10px; background:#f8fbff; }
.tp-qa-profile strong { color:var(--tp-brand-ink); font-size:14px; }
.tp-qa-profile span { color:var(--tp-sub); font-size:12px; }
.tp-qa-profile b { margin-left:auto; color:var(--tp-ink); font-size:11px; }
.tp-qa-profile small { flex-basis:100%; color:var(--tp-faint); font-size:10px; line-height:1.4; }
.tp-qa-heading { margin:20px 0 9px; font-size:15px !important; }
.tp-qa-rule { display:flex; align-items:flex-start; justify-content:space-between; gap:10px; margin:0 0 6px; padding:9px 12px; border:1px solid var(--tp-line); border-radius:9px; background:#fff; }
.tp-qa-rule > div { min-width:0; }
.tp-qa-rule strong { color:var(--tp-ink); font-size:12px; }
.tp-qa-rule p { margin:3px 0; color:var(--tp-sub); font-size:11px; line-height:1.4; }
.tp-qa-rule small { display:block; color:var(--tp-faint); font-size:10px; line-height:1.45; }
.tp-qa-rule > span { flex:0 0 auto; padding:4px 7px; border-radius:999px; font-size:10px; font-weight:750; white-space:nowrap; }
.tp-qa-rule.is-pass > span { background:#eaf8f1; color:#147a4a; }
.tp-qa-rule.is-fail { border-color:#efc1bd; background:#fffafa; }
.tp-qa-rule.is-fail > span { background:#fff0f0; color:#b42318; }
.tp-qa-rule.is-manual_review > span { background:#fff7e6; color:#8a5a00; }
.tp-qa-rule.is-not_checked > span { background:#f1f4f8; color:#536176; }
.tp-qa-fact { display:flex; flex-direction:column; gap:4px; padding:10px 0; }
.tp-qa-fact strong { color:var(--tp-ink); font-size:13px; }
.tp-qa-fact span { color:var(--tp-sub); font-size:11px; }
.tp-qa-status { margin-top:8px; padding:7px 8px; border-radius:8px; font-size:11px; font-weight:750; text-align:center; }
.tp-qa-status.is-pass, .tp-qa-status.is-confirmed { background:#eaf8f1; color:#147a4a; }
.tp-qa-status.is-fail { background:#fff0f0; color:#b42318; }
.tp-qa-status.is-stale { background:#fff7e6; color:#8a5a00; }
.tp-qa-status.is-not_run, .tp-qa-status.is-not_confirmed { background:#f1f4f8; color:#536176; }
.st-key-translation_inspector {
 padding-left:6px; color:var(--tp-ink);
}
.tp-translation-inspector-head {
 display:flex; align-items:flex-start; justify-content:space-between; gap:12px;
 padding:2px 0 14px; border-bottom:1px solid var(--tp-line);
}
.tp-translation-inspector-head h3 { margin:0; font-size:16px !important; }
.tp-translation-inspector-position { color:var(--tp-sub); font-size:12px; white-space:nowrap; }
.tp-inspector-section { padding:15px 0; border-bottom:1px solid var(--tp-line-subtle); }
.tp-inspector-section:last-child { border-bottom:0; }
.tp-inspector-section h4 {
 margin:0 0 10px; color:var(--tp-ink); font-size:12px; font-weight:750;
 letter-spacing:.02em;
}
.tp-inspector-status { display:flex; align-items:center; gap:7px; color:var(--tp-sub); font-size:12px; }
.tp-inspector-status strong { color:var(--tp-ink); font-weight:650; }
.tp-inspector-term { display:flex; justify-content:space-between; gap:12px; padding:7px 0; font-size:12px; }
.tp-inspector-term span { color:var(--tp-sub); }
.tp-inspector-term b { color:var(--tp-ink); font-weight:650; text-align:right; }
.tp-inspector-empty { color:var(--tp-sub); font-size:12px; }
.tp-inspector-preview { margin:0; color:var(--tp-sub); font-size:12px; line-height:1.55; }
.tp-inspector-preview + .tp-inspector-preview { margin-top:10px; }
.tp-inspector-preview strong { display:block; margin-bottom:3px; color:var(--tp-faint); font-size:11px; font-weight:650; }
.st-key-translation_inspector .stTextArea textarea { min-height:150px; font-size:13px; line-height:1.65; }
.st-key-translation_inspector [data-testid="stExpander"] { border:0; border-top:1px solid var(--tp-line-subtle); border-radius:0; }
.st-key-translation_inspector [data-testid="stExpander"] summary { padding:12px 0; }
.st-key-translation_inspector .stButton > button { min-height:36px; }
.tp-translation-table-note { margin:8px 0 10px; color:var(--tp-faint); font-size:11px; }
.tp-review-head { display:flex; align-items:flex-end; justify-content:space-between; gap:16px; margin-bottom:16px; }
.tp-review-count { color:var(--tp-sub); font-size:13px; }
.tp-focus-head { display:flex; justify-content:space-between; gap:12px; margin:8px 0 14px; color:var(--tp-sub); font-size:13px; font-weight:650; }
.tp-focus-text { min-height:300px; padding:18px; border:1px solid var(--tp-line); border-radius:12px; background:#fff; }
.tp-focus-text label { display:block; margin-bottom:12px; color:var(--tp-sub); font-size:11px !important; font-weight:700; letter-spacing:.06em; text-transform:uppercase; }
.tp-focus-text p { margin:0; color:var(--tp-ink); font-size:15px; line-height:1.85; white-space:pre-wrap; }
.tp-filter-strip { display:flex; align-items:center; gap:8px; padding:9px 0 13px; border-top:1px solid var(--tp-line-subtle); border-bottom:1px solid var(--tp-line); }
.tp-filter-chip { padding:5px 10px; border:1px solid var(--tp-line); border-radius:999px; color:var(--tp-sub); font-size:12px; }
.tp-filter-chip.is-blocking { border-color:#f3c0bd; color:#b42318; background:#fff8f7; }
.tp-review-pane { min-height:530px; padding:16px; border:1px solid var(--tp-line); border-radius:12px; background:#fff; }
.tp-review-pane + .tp-review-pane { margin-left:-1px; border-radius:0 12px 12px 0; }
.tp-review-pane.is-queue { border-radius:12px 0 0 12px; background:#fbfcfe; }
.tp-review-pane.is-evidence { border-radius:0 12px 12px 0; background:#fbfcfe; }
.tp-review-queue-count { color:var(--tp-sub); font-size:13px; font-weight:500; }
.tp-review-section-label { margin:18px 0 7px; color:var(--tp-sub); font-size:12px; font-weight:700; }
.tp-review-long-text {
 padding:12px 0 16px; border-bottom:1px solid var(--tp-line-subtle);
 color:var(--tp-ink); font-size:14px; line-height:1.75; white-space:pre-wrap;
}
.tp-review-diagnostic-label { margin-top:18px; color:var(--tp-sub); font-size:11px; font-weight:750; letter-spacing:.02em; }
.tp-review-diagnostic-copy { margin:6px 0 0; color:var(--tp-ink); font-size:14px; line-height:1.7; white-space:pre-wrap; }
.tp-review-summary { padding:12px 14px; border-left:3px solid #f59e0b; border-radius:0 8px 8px 0; background:#fff9eb; color:#5f4600; }
.tp-review-span { padding:1px 3px; border-radius:3px; background:#fff0bd; box-shadow:inset 0 -1px 0 #e5b93f; }
.tp-review-location-note { margin:6px 0 0; color:var(--tp-faint); font-size:11px; line-height:1.5; }
.tp-review-legacy { margin:14px 0; padding:10px 12px; border:1px solid #d9e2ef; border-radius:8px; background:#f8fafc; color:var(--tp-sub); font-size:12px; line-height:1.55; }
.tp-review-evidence-detail { color:var(--tp-sub); font-size:12px; line-height:1.55; }
.tp-review-evidence-title { margin:0 0 14px; font-size:16px !important; }
.tp-review-evidence-row {
 display:flex; align-items:baseline; justify-content:space-between; gap:12px;
 padding:9px 0; border-bottom:1px solid var(--tp-line-subtle); font-size:12px;
}
.tp-review-evidence-row span { color:var(--tp-sub); }
.tp-review-evidence-row b { color:var(--tp-ink); text-align:right; }
.tp-review-evidence-label { margin-top:16px; color:var(--tp-sub); font-size:11px; font-weight:750; }
.tp-review-evidence-copy { margin:5px 0 0; color:var(--tp-ink); font-size:12px; line-height:1.65; white-space:pre-wrap; }
.tp-queue-item { padding:11px 10px; border-bottom:1px solid var(--tp-line-subtle); }
.tp-queue-item strong { display:block; color:var(--tp-ink); font-size:13px; line-height:1.4; }
.tp-queue-item span { display:block; margin-top:4px; color:var(--tp-sub); font-size:11px; line-height:1.35; }
.tp-queue-item.is-selected { margin:0 -10px; padding-left:20px; border-left:3px solid var(--tp-primary); background:#eef5ff; }
.tp-segment-label { color:var(--tp-sub); font-size:12px; font-weight:650; }
.tp-finding-reason { margin:14px 0; padding:13px 15px; border-left:3px solid #f59e0b; border-radius:0 8px 8px 0; background:#fff9eb; color:#6c4d00; font-size:13px; line-height:1.6; }
.tp-text-card { min-height:130px; padding:14px; border:1px solid var(--tp-line); border-radius:10px; background:#fbfcfe; }
.tp-text-card label { display:block; margin-bottom:9px; color:var(--tp-sub); font-size:11px !important; font-weight:700; text-transform:uppercase; letter-spacing:.05em; }
.tp-text-card p { margin:0; color:var(--tp-ink); font-size:14px; line-height:1.7; white-space:pre-wrap; }
.tp-evidence-card { padding:13px; border:1px solid var(--tp-line); border-radius:10px; background:#fff; }
.tp-evidence-card p { margin:0; color:var(--tp-sub); font-size:12px; line-height:1.6; }
.tp-delivery-header { padding:20px 22px; border:1px solid var(--tp-line); border-radius:14px; background:#fff; }
.tp-report-page-head { margin-bottom:18px; }
.tp-report-page-head h2 { margin:2px 0 5px; }
.tp-report-page-lead { margin:0; color:var(--tp-sub); font-size:13px; line-height:1.6; }
.tp-report-meta-chips { display:flex; flex-wrap:wrap; gap:7px; margin-top:14px; }
.tp-report-meta-chip { display:inline-flex; align-items:center; gap:5px; padding:5px 9px; border:1px solid var(--tp-line); border-radius:999px; background:#fff; color:var(--tp-sub); font-size:11px; line-height:1.2; }
.tp-report-meta-chip strong { color:var(--tp-ink); font-weight:700; }
.tp-report-overall { margin-bottom:14px; padding:18px 20px; border:1px solid #c9dcfb; border-left:4px solid var(--tp-primary); border-radius:12px; background:#f8fbff; }
.tp-report-overall.is-danger { border-color:#f1c2bf; border-left-color:var(--tp-danger); background:#fff7f6; }
.tp-report-overall.is-warning { border-color:#edd39d; border-left-color:#c47b00; background:#fffaf0; }
.tp-report-overall.is-success { border-color:#b8dfcc; border-left-color:var(--tp-success); background:#f3fbf7; }
.tp-report-overall-head { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }
.tp-report-overall-head h3 { margin:0; color:var(--tp-ink); font-size:21px !important; }
.tp-report-overall-grid { display:grid; grid-template-columns:minmax(0,1.6fr) .8fr 1fr; gap:18px; margin-top:16px; padding-top:14px; border-top:1px solid var(--tp-line-subtle); }
.tp-report-overall-grid span { display:block; color:var(--tp-sub); font-size:11px; }
.tp-report-overall-grid strong { display:block; margin-top:5px; color:var(--tp-ink); font-size:13px; line-height:1.45; font-variant-numeric:tabular-nums; }
.tp-report-status-progress { height:6px; margin-top:14px; overflow:hidden; border-radius:999px; background:#e1ebfa; }
.tp-report-status-progress i { display:block; height:100%; border-radius:inherit; background:var(--tp-primary); }
.tp-report-overall-detail { margin:13px 0 0; color:var(--tp-sub); font-size:12px; line-height:1.55; }
.tp-delivery-header h3 { margin:0; font-size:19px !important; }
.tp-report-toolbar-kicker { margin-bottom:7px; color:var(--tp-sub); font-size:11px; font-weight:750; letter-spacing:.08em; text-transform:uppercase; }
.tp-report-outline { margin:16px 0 0; padding:14px 16px; border:1px solid var(--tp-line); border-radius:10px; background:#fbfcfe; }
.tp-report-outline-title { margin-bottom:8px; color:var(--tp-ink); font-size:12px; font-weight:750; }
.tp-report-outline a { display:block; padding:4px 0; color:var(--tp-sub); font-size:12px; line-height:1.45; text-decoration:none; }
.tp-report-outline a:hover, .tp-report-outline a:focus, .tp-report-outline a:focus-visible {
 margin:0 -7px; padding-left:7px; padding-right:7px; border-radius:5px;
 background:var(--tp-primary-soft); color:var(--tp-primary); text-decoration:none;
}
.tp-report-outline a.is-chapter { color:var(--tp-ink); font-weight:650; }
.tp-report-outline a.is-subsection { padding-left:16px; }
.tp-report-body a:target + h1, .tp-report-body a:target + h2,
.tp-report-body a:target + h3, .tp-report-body a:target + h4 {
 margin-left:-10px; padding-left:8px; border-left:2px solid var(--tp-primary);
}
.tp-report-issues { margin-top:4px; }
.tp-report-issues-head { display:flex; align-items:baseline; justify-content:space-between; gap:16px; }
.tp-report-issues-head h3 { margin:0; font-size:17px !important; }
.tp-report-issues-summary { display:flex; flex-wrap:wrap; gap:6px; color:var(--tp-sub); font-size:11px; }
.tp-report-issues-summary span { padding:3px 7px; border-radius:999px; background:#f1f4f8; }
.tp-report-issues-summary .is-blocker { background:#fff0f0; color:#b42318; }
.tp-report-issues-summary .is-warning { background:#fff7e6; color:#8a5a00; }
.tp-report-issues-summary .is-human-review { background:#edf4ff; color:var(--tp-brand-ink); }
.tp-report-issues-group { margin-top:18px; }
.tp-report-issues-group-title { display:flex; align-items:center; gap:8px; margin-bottom:2px; color:var(--tp-ink); }
.tp-report-issues-group-title h4 { margin:0; font-size:13px !important; font-weight:750; }
.tp-report-issues-group-title span { color:var(--tp-faint); font-size:11px; }
.tp-report-issue { display:block; margin:0; padding:0; border:0; background:transparent; }
.tp-report-issue-badge { display:inline-flex; padding:3px 8px; border-radius:999px; background:#f1f4f8; color:var(--tp-sub); font-size:11px; font-weight:750; }
.tp-report-issue.is-blocker .tp-report-issue-badge { background:#fff0f0; color:#b42318; }
.tp-report-issue.is-warning .tp-report-issue-badge { background:#fff7e6; color:#8a5a00; }
.tp-report-issue.is-human-review .tp-report-issue-badge { background:#edf4ff; color:var(--tp-brand-ink); }
.tp-report-issue h4 { margin:8px 0 0; color:var(--tp-ink); font-size:15px; }
.tp-report-issue p { margin:5px 0 10px; color:var(--tp-sub); font-size:13px; line-height:1.6; }
.tp-report-issue-meta { display:grid; grid-template-columns:72px minmax(0,1fr); gap:5px 10px; }
.tp-report-issue-meta span { color:var(--tp-faint); font-size:11px; }
.tp-report-issue-meta strong { color:var(--tp-ink); font-size:12px; font-weight:600; line-height:1.55; }
.tp-report-issue-next { display:inline-flex; align-items:center; min-height:32px; padding:0 8px; color:var(--tp-primary); font-size:11px; font-weight:750; white-space:nowrap; }
[class*="st-key-report_issue_row_action_"] .stButton > button { min-height:36px; white-space:nowrap; }
[class*="st-key-report_issue_row_"]:not([class*="st-key-report_issue_row_action_"]) { margin:0; padding:15px 0 15px 14px; border-bottom:1px solid var(--tp-line-subtle); border-left:3px solid #d5a12c; }
[class*="st-key-report_issue_row_"]:not([class*="st-key-report_issue_row_action_"]) .stHorizontalBlock { align-items:flex-start; }
[class*="st-key-report_issue_row_blocker_"] { border-left-color:var(--tp-danger); }
[class*="st-key-report_issue_row_human_review_"] { border-left-color:var(--tp-primary); }
.tp-report-issues-empty { margin-top:14px; padding:15px 0; color:var(--tp-sub); font-size:13px; }
[class*="st-key-report_recommended_"] { margin-top:24px; padding:17px 19px; border:1px solid #b9d3f8; border-left:4px solid var(--tp-primary); border-radius:12px; background:#f8fbff; }
[class*="st-key-report_recommended_"] .stHorizontalBlock { align-items:center; }
.tp-report-recommended-copy { min-width:0; }
.tp-report-recommended-kicker { color:var(--tp-primary); font-size:11px; font-weight:800; letter-spacing:.07em; text-transform:uppercase; }
.tp-report-recommended-copy h3 { margin:5px 0 0; color:var(--tp-ink); font-size:16px !important; }
.tp-report-recommended-copy p { margin:4px 0 0; color:var(--tp-sub); font-size:12px; line-height:1.55; }
[class*="st-key-report_recommended_"] .stButton > button { min-width:150px; }
.tp-report-focus { margin-top:24px; padding:18px 19px 20px; border:1px solid var(--tp-line); border-radius:12px; background:#fff; }
.tp-report-focus-head { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:12px; }
.tp-report-focus-head h3 { margin:0; font-size:17px !important; }
.tp-report-body { margin-top:16px; padding:30px 34px 36px; border:1px solid var(--tp-line); border-radius:12px; background:#fff; }
.tp-report-body h1, .tp-report-body h2, .tp-report-body h3, .tp-report-body h4 { color:var(--tp-ink); }
.tp-report-body h1 { margin:0 0 1.1em; font-size:25px !important; line-height:1.35 !important; }
.tp-report-body h2 { margin:1.55em 0 .55em; font-size:21px !important; line-height:1.45 !important; }
.tp-report-body h3 { margin:1.25em 0 .45em; font-size:17px !important; line-height:1.5 !important; }
.tp-report-body h4 { margin:1.15em 0 .4em; font-size:15px !important; }
.tp-report-body p, .tp-report-body li { max-width:72ch; color:#283548; font-size:15px; line-height:1.9; }
.tp-report-body p { margin:0 0 1em; }
.tp-report-body ul, .tp-report-body ol { margin:0 0 1em; padding-left:1.5em; }
.tp-report-body blockquote { max-width:72ch; margin:18px 0; padding:12px 18px; border-left:3px solid #b7cdf0; border-radius:0 8px 8px 0; background:#f7faff; color:#43536b; }
.tp-report-body blockquote p { color:#43536b; font-size:14px; line-height:1.75; }
.tp-report-body table { display:block; max-width:100%; overflow-x:auto; margin:18px 0 22px; border-collapse:collapse; }
.tp-report-body th, .tp-report-body td { min-width:110px; padding:8px 10px; border:1px solid var(--tp-line); font-size:13px; line-height:1.6; text-align:left; }
.tp-report-body th { background:#f7f9fc; color:var(--tp-ink); font-weight:700; }
.tp-report-body hr { margin:24px 0; border:0; border-top:1px solid var(--tp-line-subtle); }
.tp-report-body a { color:var(--tp-primary); }
.tp-checklist { margin:16px 0 22px; border-top:1px solid var(--tp-line-subtle); }
.tp-check-row { display:flex; gap:11px; align-items:center; padding:12px 0; border-bottom:1px solid var(--tp-line-subtle); color:var(--tp-ink); font-size:13px; }
.tp-check-row i { font-style:normal; width:20px; text-align:center; color:var(--tp-success); font-size:16px; }
.tp-check-row.is-warning i { color:#d97706; }
.tp-version-list { display:grid; gap:8px; margin-top:14px; }
.tp-version { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:12px 14px; border:1px solid var(--tp-line); border-radius:9px; background:#fff; }
.tp-version strong { color:var(--tp-ink); font-size:13px; }
.tp-version span { color:var(--tp-sub); font-size:12px; }
.tp-asset-list { display:grid; gap:8px; margin-top:16px; }
.tp-asset-row { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:13px 14px; border:1px solid var(--tp-line); border-radius:10px; background:#fff; }
.tp-asset-copy { min-width:0; }
.tp-asset-copy strong { display:block; color:var(--tp-ink); font-size:13px; }
.tp-asset-copy span { display:block; margin-top:4px; color:var(--tp-sub); font-size:11px; }
.tp-empty { padding:34px 20px; border:1px dashed #cbd5e1; border-radius:12px; background:#fbfcfe; color:var(--tp-sub); text-align:center; }
.tp-tech-detail { color:var(--tp-sub); font-size:12px; }
.tp-readiness-card { margin:0 0 14px; padding:17px 18px 15px; border:1px solid #edd39d; border-left:4px solid #c47b00; border-radius:12px; background:#fffaf0; }
.tp-readiness-card.is-success { border-color:#b8dfcc; border-left-color:var(--tp-success); background:#f3fbf7; }
.tp-readiness-card.is-danger { border-color:#efc1bd; border-left-color:var(--tp-danger); background:#fff8f7; }
.tp-readiness-card.is-warning .tp-readiness-kicker { color:#8a5a00; }
.tp-readiness-card.is-success .tp-readiness-kicker { color:#147a4a; }
.tp-readiness-card.is-danger .tp-readiness-kicker { color:#b42318; }
.tp-readiness-kicker { color:#8a5a00; font-size:10px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
.tp-readiness-head { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; margin-top:5px; }
.tp-readiness-head h3 { margin:0; color:var(--tp-ink); font-size:22px !important; line-height:1.25; }
.tp-readiness-head p { max-width:58ch; margin:6px 0 0; color:#6f4d13; font-size:13px; line-height:1.55; }
.tp-readiness-card.is-success .tp-readiness-head p { color:#315f48; }
.tp-readiness-card.is-danger .tp-readiness-head p { color:#6f3130; }
.tp-readiness-flag { flex:0 0 auto; padding:5px 8px; border-radius:999px; background:#fff0cf; color:#8a5a00; font-size:10px; font-weight:800; white-space:nowrap; }
.tp-readiness-card.is-success .tp-readiness-flag { background:#dff4e8; color:#147a4a; }
.tp-readiness-card.is-danger .tp-readiness-flag { background:#fff0f0; color:#b42318; }
.tp-readiness-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:0 12px; margin-top:15px; padding-top:8px; border-top:1px solid #f0dfbd; }
.tp-readiness-card.is-success .tp-readiness-grid { border-top-color:#d5ebdf; }
.tp-readiness-card.is-danger .tp-readiness-grid { border-top-color:#f1d8d5; }
.tp-readiness-item { min-width:0; padding:10px 0 9px; border-bottom:1px solid #f1e5cb; }
.tp-readiness-card.is-success .tp-readiness-item { border-bottom-color:#e1f0e7; }
.tp-readiness-card.is-danger .tp-readiness-item { border-bottom-color:#f4e1df; }
.tp-readiness-item-head { display:flex; align-items:center; gap:7px; min-width:0; }
.tp-readiness-icon { display:inline-grid; flex:0 0 auto; place-items:center; width:18px; height:18px; border-radius:50%; font-size:11px; font-weight:850; line-height:1; }
.tp-readiness-item.is-pass .tp-readiness-icon { background:#dff4e8; color:#147a4a; }
.tp-readiness-item.is-warning .tp-readiness-icon { background:#fff0cf; color:#8a5a00; }
.tp-readiness-item.is-pending .tp-readiness-icon { background:#e9edf3; color:#536176; }
.tp-readiness-label { min-width:0; color:var(--tp-ink); font-size:12px; font-weight:750; line-height:1.35; }
.tp-readiness-detail { margin:5px 0 0 25px; color:var(--tp-sub); font-size:11px; line-height:1.45; }
.tp-readiness-status { margin:4px 0 0 25px; color:var(--tp-faint); font-size:10px; font-weight:750; }
.tp-readiness-item.is-pass .tp-readiness-status { color:#147a4a; }
.tp-readiness-item.is-warning .tp-readiness-status { color:#8a5a00; }
.tp-readiness-item.is-pending .tp-readiness-status { color:#536176; }
.tp-next-action-copy { min-width:0; }
.tp-next-action-kicker { color:var(--tp-primary); font-size:10px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
.tp-next-action-copy strong { display:block; margin-top:4px; color:var(--tp-ink); font-size:14px; }
.tp-next-action-copy p { margin:4px 0 0; color:var(--tp-sub); font-size:12px; line-height:1.45; }
[class*="st-key-delivery_next_action_"] { margin:0 0 14px; padding:13px 15px; border:1px solid #c9dcfb; border-left:3px solid var(--tp-primary); border-radius:10px; background:#f7faff; }
[class*="st-key-delivery_next_action_"] [data-testid="stHorizontalBlock"] { align-items:center; gap:16px; }
[class*="st-key-delivery_next_action_"] .stButton > button { min-height:34px; white-space:normal; }
.tp-impact-panel { margin:0 0 14px; padding:15px 16px 13px; border:1px solid #edd39d; border-left:3px solid #c47b00; border-radius:10px; background:#fffaf0; }
.tp-impact-panel > strong { display:block; color:#714c00; font-size:14px; }
.tp-impact-panel > p { margin:4px 0 0; color:#8a5a00; font-size:12px; line-height:1.45; }
.tp-impact-summary { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin-top:12px; }
.tp-impact-summary div { min-width:0; padding-top:9px; border-top:1px solid #f0dfbd; }
.tp-impact-summary span { display:block; color:#8a6a24; font-size:10px; font-weight:700; }
.tp-impact-summary strong { display:block; margin-top:4px; color:#5f4600; font-size:12px; line-height:1.4; }
.tp-impact-chain { display:grid; gap:7px; margin-top:8px; }
.tp-impact-chain-row { display:flex; align-items:baseline; gap:8px; color:var(--tp-ink); font-size:12px; line-height:1.45; }
.tp-impact-chain-row i { flex:0 0 auto; color:#c47b00; font-style:normal; font-weight:800; }
.tp-impact-chain-row strong { flex:0 0 52px; color:var(--tp-ink); font-weight:750; white-space:nowrap; }
.tp-impact-chain-row span { flex:1 1 auto; min-width:0; color:var(--tp-sub); }
.tp-technical-note { margin:0 0 14px; padding:10px 12px; border:1px solid var(--tp-line-subtle); border-radius:8px; background:#fbfcfe; }
.tp-technical-note strong { display:block; color:var(--tp-ink); font-size:12px; }
.tp-technical-note small { display:block; margin-top:4px; color:var(--tp-faint); font-size:10px; line-height:1.45; }
.tp-qa-profile { margin-bottom:12px; padding:11px 13px; }
.tp-qa-rule { border-radius:8px; }
.tp-qa-source { margin-top:6px; color:var(--tp-faint); font-size:10px; line-height:1.45; }
.tp-qa-rule .stExpander { margin-top:4px; }
[class*="st-key-translation_search_"] input:focus:not([aria-invalid="true"]),
[class*="st-key-translation_search_"] input:focus-visible:not([aria-invalid="true"]),
[class*="st-key-case_search_"] input:focus:not([aria-invalid="true"]),
[class*="st-key-case_search_"] input:focus-visible:not([aria-invalid="true"]) {
 border-color:#69a7f8 !important;
 box-shadow:0 0 0 3px rgba(18,103,232,.14) !important;
}
[class*="st-key-translation_search_"] [data-testid="stTextInputRootElement"]:focus-within {
 border-color:#69a7f8 !important;
 box-shadow:0 0 0 3px rgba(18,103,232,.14) !important;
}
[class*="st-key-case_search_"] [data-testid="stTextInputRootElement"]:focus-within {
 border-color:#69a7f8 !important;
 box-shadow:0 0 0 3px rgba(18,103,232,.14) !important;
}
@media (max-width: 1050px) {
 [data-testid="stMainBlockContainer"]:has(.tp-workspace-shell) { padding:22px 24px 48px; }
 .st-key-workspace_main_col { padding:0 18px; }
 .st-key-workspace_context_col { padding-left:0; margin-top:20px; }
 .st-key-translation_inspector { padding-left:0; }
 .st-key-workspace_nav_col { position:static; min-height:auto; padding-right:0; padding-bottom:14px; border-right:0; border-bottom:1px solid var(--tp-line-subtle); }
 .tp-card-grid, .tp-stage-grid { grid-template-columns:1fr; }
 .tp-readiness-grid, .tp-impact-summary { grid-template-columns:repeat(2,minmax(0,1fr)); }
 .tp-dependency-panel { display:block; }
 .tp-dependency-panel span, .tp-dependency-panel small { display:block; margin-top:7px; text-align:left; }
 .tp-qa-profile b { margin-left:0; width:100%; }
}
@media (max-width: 760px) {
 [data-testid="stMainBlockContainer"]:has(.tp-workspace-shell) { padding:16px 14px 40px; }
 .tp-workspace-topbar { display:block; }
 .tp-workspace-status { padding-top:12px; }
 .st-key-workspace_main_col { padding:0; }
 .tp-readiness-grid, .tp-impact-summary { grid-template-columns:1fr; }
 .tp-readiness-head { display:block; }
 .tp-readiness-flag { display:inline-block; margin-top:10px; }
 [class*="st-key-delivery_next_action_"] [data-testid="stHorizontalBlock"] { flex-direction:column; align-items:stretch; }
 [class*="st-key-delivery_next_action_"] .stButton > button { width:100%; margin-top:12px; }
 .tp-review-pane, .tp-review-pane + .tp-review-pane { min-height:auto; margin:0; border-radius:12px; }
 .tp-report-overall-grid { grid-template-columns:1fr; gap:10px; }
 .tp-report-issues-head { display:block; }
 .tp-report-issues-summary { margin-top:9px; }
 [class*="st-key-report_issue_row_"]:not([class*="st-key-report_issue_row_action_"]) { padding-left:11px; }
 [class*="st-key-report_issue_row_"]:not([class*="st-key-report_issue_row_action_"]) .stHorizontalBlock,
 [class*="st-key-report_recommended_"] .stHorizontalBlock { flex-direction:column; }
 [class*="st-key-report_issue_row_action_"] .stButton > button { width:100%; }
 [class*="st-key-report_recommended_"] .stButton > button { width:100%; margin-top:13px; }
 .tp-report-focus { padding:16px 14px 18px; }
 .tp-report-body { padding:20px 17px; }
}
"""
st.markdown("<style>" + _CSS + _WORKSPACE_CSS + "</style>", unsafe_allow_html=True)

# ================= 术语审核面板工具函数 =================
_EVIDENCE_LABELS = {
    "user": "用户提供", "local_termbase": "本地术语库",
    "project_override": "项目覆盖", "model_knowledge": "模型知识",
    "external": "外部来源",
}


def _evidence_label(e):
    evs = e.get("evidence") or []
    parts = []
    for ev in evs[:2]:
        label = _EVIDENCE_LABELS.get(ev.get("evidence_type"), ev.get("evidence_type"))
        note = (ev.get("note") or "").strip()
        parts.append(f"{label}：{note}" if note else label)
    return "；".join(parts)


def _conflict(e, entries):
    src = (e.get("source") or "").casefold()
    pref = e.get("preferred") or e.get("target")
    for other in entries:
        if other is e:
            continue
        if (other.get("source") or "").casefold() == src \
                and (other.get("preferred") or other.get("target")) != pref:
            return "冲突"
    return ""


def _first_context(e, paras, width=60):
    occ = e.get("occurrences") or []
    if not occ or not paras:
        return ""
    first = occ[0]
    if not (0 <= first < len(paras)):
        return ""
    text = paras[first]
    return text[:width] + ("…" if len(text) > width else "")


def _glossary_dataframe(entries, paras):
    rows = []
    for e in entries:
        rows.append({
            "选择": False,
            "id": e.get("id", ""),
            "source": e.get("source", ""),
            "proposed_target": e.get("proposed_target") or e.get("target", ""),
            "target": e.get("target", ""),
            "preferred": e.get("preferred", ""),
            "forbidden": "；".join(e.get("forbidden") or []),
            "behavior": e.get("behavior", "translate"),
            "status": e.get("status", "provisional"),
            "domain": e.get("domain", ""),
            "scope": e.get("scope", ""),
            "note": e.get("note", ""),
            "confidence": float(e.get("confidence") or 0.5),
            "出现次数": len(e.get("occurrences") or []),
            "上下文": _first_context(e, paras),
            "证据": _evidence_label(e),
            "冲突": _conflict(e, entries),
            "payload": json.dumps(e, ensure_ascii=False),
        })
    return pd.DataFrame(rows)


def _df_to_entries(df):
    entries = []
    for _, row in df.iterrows():
        base = {}
        payload = row.get("payload")
        if isinstance(payload, str) and payload.strip():
            try:
                base = json.loads(payload)
            except Exception:
                base = {}
        if not isinstance(base, dict):
            base = {}
        base = dict(base)

        def _s(key):
            v = row.get(key)
            return "" if pd.isna(v) else str(v).strip()

        base.update({
            "source": _s("source"),
            "proposed_target": _s("proposed_target"),
            "target": _s("target") or _s("proposed_target"),
            "preferred": _s("preferred") or _s("target") or _s("proposed_target"),
            "forbidden": [x.strip() for x in re.split(r"[;；]", _s("forbidden"))
                          if x.strip()],
            "behavior": (_s("behavior") or "translate").lower(),
            "status": (_s("status") or "provisional").lower(),
            "domain": _s("domain"),
            "scope": _s("scope"),
            "note": _s("note"),
        })
        try:
            base["confidence"] = float(row.get("confidence") or 0.5)
        except (TypeError, ValueError):
            base["confidence"] = 0.5
        entries.append(base)
    return entries


def _page_title(title, sub):
    st.markdown(
        f'<div class="tp-title"><h1>{title}</h1><p>{sub}</p></div>',
 unsafe_allow_html=True)


def _step_title(number, title, sub):
    st.markdown(
        f'<div class="tp-section-title">{title}</div>'
        f'<div class="tp-section-sub">{sub}</div>', unsafe_allow_html=True)


def _go_to_step(step):
    st.session_state.task_step = step


def _request_step(step):
    if step > 1 and not st.session_state.get("task_files"):
        st.session_state.step_gate_message = "请先上传原文。"
        st.session_state.task_step = 1
        return
    st.session_state.pop("step_gate_message", None)
    st.session_state.task_step = step


def _reset_provider_connection(preserve_models=False):
    st.session_state.provider_configured = False
    st.session_state.provider_connection_status = "unverified"
    st.session_state.pop("provider_test_feedback", None)
    if not preserve_models:
        provider = st.session_state.get("provider_choice")
        if provider:
            st.session_state.pop(f"fetched_models_{provider}", None)
            st.session_state.pop(f"preferred_fetched_model_{provider}", None)
        st.session_state.pop("model_fetch_feedback", None)


def _open_provider_settings():
    st.session_state.app_view = "settings"


_PRESET_CONFIGS = {
    "快速": {
        "auto_term": False, "use_tm": True,
        "enable_understanding": False,
        "enable_review": False, "strict_terminology_governance": False,
    },
    "标准": {
        "auto_term": True, "use_tm": True,
        "enable_understanding": True,
        "enable_review": False, "strict_terminology_governance": False,
    },
    "学术增强": {
        "auto_term": True, "use_tm": True,
        "enable_understanding": True,
        "enable_review": True, "strict_terminology_governance": True,
    },
}

def _default_output_config():
    return core.default_delivery_config()


_PRESET_OUTPUTS = {
    "快速": {**_default_output_config()},
    "标准": {**_default_output_config()},
    "学术增强": {**_default_output_config(), "enable_report": True},
}


def _apply_preset(label):
    for key in ("strategy_auto_term", "strategy_use_tm", "strategy_review",
                "strategy_understanding", "strategy_strict_terms",
                "output_annotate", "output_report"):
        st.session_state.pop(key, None)
    st.session_state.translation_preset = label
    st.session_state.strategy_config = dict(_PRESET_CONFIGS[label])
    st.session_state.output_config = dict(_PRESET_OUTPUTS[label])


def _strategy_is_adjusted(label, config):
    return any(config.get(key) != value
               for key, value in _PRESET_CONFIGS[label].items())


def _output_is_adjusted(label, config):
    return any(config.get(key) != value
               for key, value in _PRESET_OUTPUTS[label].items())


def _toggle_advanced_strategy():
    st.session_state.strategy_advanced_open = not st.session_state.get(
        "strategy_advanced_open", False)


def _set_strategy_option(option, widget_key):
    config = dict(st.session_state.strategy_config)
    config[option] = bool(st.session_state[widget_key])
    st.session_state.strategy_config = config


def _set_output_option(option, widget_key):
    config = dict(st.session_state.output_config)
    config[option] = bool(st.session_state[widget_key])
    st.session_state.output_config = config


# ---------------- 智能风格建议（Step 01 Quick Profiling） ----------------

def _apply_style_selection(selection):
    """把选中的 Style Profile 落成 style_rules / style_template。"""
    from transpraxis.style_profile import STYLE_PROFILES, profile_to_rules
    selection = selection or {}
    rules = profile_to_rules(selection)
    custom = (selection.get("custom_rules") or "").strip()
    if custom:
        rules = rules.rstrip("。") + "。" + custom + "。"
    st.session_state.style_rules = rules
    base = selection.get("selected") or "general"
    st.session_state.style_template = STYLE_PROFILES.get(
        base, STYLE_PROFILES["general"])["name"]
    st.session_state.style_selection = selection


def _accept_style_recommendation():
    rec = st.session_state.get("style_recommendation") or {}
    selection = {
        "selected": rec.get("recommended_style", "general"),
        "source": "accepted",
        "adjustments": {},
    }
    _apply_style_selection(selection)


def _run_quick_profile_with_progress():
    """在脚本运行内执行 Quick Profiling，用 st.status 分步显示进度。

    不放在按钮回调里：回调期间前端收不到任何更新会显得卡死/白屏。
    改为点击后置 running 状态，在本轮运行内逐步渲染状态并执行，
    完成后同一轮直接渲染结果卡片。
    """
    from transpraxis import models as _models
    from transpraxis.style_profile import _fallback_recommendation, quick_profile
    task_files = st.session_state.get("task_files") or []
    if not task_files:
        st.session_state.style_profiling_state = "idle"
        return
    source = task_files[0]
    warnings = []
    with st.status("正在生成智能风格建议…", expanded=True) as status:
        status.update(label="正在提取文档文本…", state="running")
        paragraphs, extract_warnings = core.extract_document_paragraphs(
            source.get("name", ""), source.get("bytes", b""))
        warnings.extend(extract_warnings)
        provider = st.session_state.get("provider_choice",
                                        next(iter(core.PROVIDERS)))
        api_key = st.session_state.get(f"api_key_{provider}", "")
        model = st.session_state.get(f"model_choice_{provider}", "")
        target_lang = st.session_state.get("target_lang", "简体中文")
        if not api_key or not model:
            status.update(label="未配置 AI 引擎，请手动选择风格",
                          state="complete")
            warnings.append("未配置 AI 引擎，无法自动画像；可直接手动选择风格")
            doc_profile = _models.default_document_profile()
            style_rec = _fallback_recommendation()
            st.session_state.style_profiling_needs_api = True
        else:
            status.update(label="正在抽取首/中/尾样本并分析文体…",
                          state="running")
            doc_profile, style_rec, llm_warnings = quick_profile(
                paragraphs, provider, api_key, model, target_lang)
            warnings.extend(llm_warnings)
            status.update(label="风格建议已生成", state="complete")
            st.session_state.style_profiling_needs_api = False
    st.session_state.style_profiling_state = "done"
    st.session_state.doc_profile = doc_profile
    st.session_state.style_recommendation = style_rec
    st.session_state.style_profile_warnings = warnings


def _render_style_adjust_panel():
    """基础风格 radio + 4 个微调滑块 + 高级规则；应用后覆盖系统建议。"""
    from transpraxis.style_profile import STYLE_PROFILES
    names = list(STYLE_PROFILES)
    current = st.session_state.get("style_selection") or {}
    rec = st.session_state.get("style_recommendation") or {}
    base_id = current.get("selected") or rec.get("recommended_style") or "general"
    if base_id not in names:
        base_id = "general"
    st.markdown(
        '<div class="tp-style-adjust-head"><strong>调整风格</strong>'
        '<span>修改后将覆盖系统建议，并记录为 user_override</span></div>',
        unsafe_allow_html=True)
    base = st.radio(
        "基础风格", names, index=names.index(base_id),
        format_func=lambda pid: STYLE_PROFILES[pid]["name"],
        key="style_adjust_base", label_visibility="collapsed",
        **_PERSIST_STATE)
    col_a, col_b = st.columns(2)
    with col_a:
        formality = st.slider("表达正式度", 0, 100, 60, key="adj_formality",
                              **_PERSIST_STATE)
        restructuring = st.slider("句法重构幅度", 0, 100, 40,
                                  key="adj_restructuring",
                                  **_PERSIST_STATE)
    with col_b:
        terminology = st.slider("术语保守程度", 0, 100, 60, key="adj_terminology",
                                **_PERSIST_STATE)
        form_preservation = st.slider("原文形式保留", 0, 100, 70,
                                      key="adj_form_preservation",
                                      **_PERSIST_STATE)
    custom_rules = st.text_area(
        "高级规则（可选）", key="style_adjust_custom",
        placeholder="补充风格约束，例如：保留访谈口吻；飞机型号与引用标注保留原文。",
        **_PERSIST_STATE)
    if st.button("应用风格", key="apply_style_adjust"):
        selection = {
            "selected": base,
            "source": "user_override",
            "adjustments": {
                "formality": formality,
                "terminology": terminology,
                "restructuring": restructuring,
                "form_preservation": form_preservation,
            },
            "custom_rules": custom_rules.strip(),
        }
        _apply_style_selection(selection)
        st.session_state.style_adjust_open = False
        st.rerun()


def _render_style_profile_section():
    """Step 01 的智能风格建议卡片：推荐 -> 接受 / 调整 / 查看分析。"""
    from transpraxis.style_profile import STYLE_PROFILES
    state = st.session_state.get("style_profiling_state", "idle")
    rec = st.session_state.get("style_recommendation")
    selection = st.session_state.get("style_selection")
    with st.container(key="style_profile_section"):
        if state == "idle":
            if not st.button("开始智能画像",
                             icon=":material/auto_awesome:",
                             key="run_quick_profile"):
                return
            st.session_state.style_profiling_state = "running"
            state = "running"
        if state == "running":
            _run_quick_profile_with_progress()
            rec = st.session_state.get("style_recommendation")
        if rec is None:
            return
        style_id = (selection or {}).get("selected") or rec.get("recommended_style") \
            or "general"
        meta = STYLE_PROFILES.get(style_id, STYLE_PROFILES["general"])
        confidence = rec.get("confidence", 0.0)
        reasons = rec.get("reasons") or []
        source_text = ""
        if selection:
            source_text = "已接受系统推荐" if selection.get("source") == "accepted" \
                else "已使用用户选择覆盖系统建议"
        st.markdown(
            f'<div class="tp-style-card{" is-selected" if selection else ""}">'
            '<div class="tp-style-card-head">'
            '<span class="material-symbols-rounded" aria-hidden="true">auto_awesome</span>'
            '<strong>智能风格建议</strong>'
            f'<b>{round(confidence * 100)}%</b></div>'
            f'<div class="tp-style-name">{meta["name"]}</div>'
            f'<div class="tp-style-summary">{meta["summary"]}</div>'
            '<div class="tp-style-reasons"><span>检测依据</span><ul>'
            + "".join(f"<li>{escape(r)}</li>" for r in reasons)
            + '</ul></div>'
            + (f'<div class="tp-style-source">{source_text}</div>'
               if source_text else "")
            + '</div>', unsafe_allow_html=True)
        for warn in st.session_state.get("style_profile_warnings", []):
            st.warning(warn)
        if st.session_state.get("style_profiling_needs_api"):
            goto_col, retry_col, adjust_col = st.columns(3)
            with goto_col:
                if st.button("前往配置 API Key", key="goto_api_settings",
                             type="primary", width="stretch"):
                    st.session_state.app_view = "settings"
                    st.rerun()
            with retry_col:
                if st.button("重试", key="retry_quick_profile",
                             width="stretch"):
                    st.session_state.style_profiling_state = "running"
                    st.rerun()
            with adjust_col:
                if st.button("调整", key="open_style_adjust_api",
                             width="stretch"):
                    st.session_state.style_adjust_open = not st.session_state.get(
                        "style_adjust_open", False)
                    st.session_state.style_analysis_open = False
                    st.rerun()
        else:
            accept_col, adjust_col, analyze_col = st.columns(3)
            with accept_col:
                if st.button("接受推荐", key="accept_style_rec",
                             width="stretch"):
                    _accept_style_recommendation()
                    st.session_state.style_adjust_open = False
                    st.session_state.style_analysis_open = False
                    st.rerun()
            with adjust_col:
                if st.button("调整", key="open_style_adjust",
                             width="stretch"):
                    st.session_state.style_adjust_open = not st.session_state.get(
                        "style_adjust_open", False)
                    st.session_state.style_analysis_open = False
                    st.rerun()
            with analyze_col:
                if st.button("查看分析", key="show_style_analysis",
                             width="stretch"):
                    st.session_state.style_analysis_open = not st.session_state.get(
                        "style_analysis_open", False)
                    st.session_state.style_adjust_open = False
                    st.rerun()
        if st.session_state.get("style_analysis_open"):
            with st.expander("文档画像分析", expanded=True):
                doc = st.session_state.get("doc_profile") or {}
                rows = [
                    ("领域", doc.get("domain") or "—"),
                    ("细分领域", doc.get("subdomain") or "—"),
                    ("文本类型", doc.get("genre") or "—"),
                    ("目标读者", doc.get("audience") or "—"),
                    ("语域", doc.get("register") or "—"),
                    ("文体约束", doc.get("style_constraints") or "—"),
                ]
                st.markdown("<br>".join(
                    f"<b>{k}</b>：{escape(str(v))}" for k, v in rows),
                    unsafe_allow_html=True)
                if rec.get("domain"):
                    st.caption("领域标签：" + " · ".join(rec.get("domain", [])))
                st.caption("样本策略：首 / 中 / 尾分布式采样，约 3000–6000 字符")
        if st.session_state.get("style_adjust_open"):
            _render_style_adjust_panel()


def _render_task_actions(*, back_step=None, next_step=None, next_label="下一步",
                         next_disabled=False, run=False):
    with st.container(key="task_action_bar"):
        status_col, back_col, next_col = st.columns([2.6, .8, .8])
        has_inputs = bool(st.session_state.get("task_files"))
        save_text = "已保存" if has_inputs else "更改会自动保存"
        save_class = "tp-autosave is-saved" if has_inputs else "tp-autosave"
        status_col.markdown(f'<span class="{save_class}">{save_text}</span>',
                            unsafe_allow_html=True)
        if back_step is not None:
            back_col.button("上一步", icon=":material/arrow_back:", width="stretch",
                            on_click=_go_to_step,
                            args=(back_step,), key=f"back_to_{back_step}")
        if run:
            return next_col.button(next_label, type="primary", width="stretch",
                                   disabled=next_disabled, key="run_task")
        next_col.button(next_label, type="primary", icon=":material/arrow_forward:",
                        width="stretch", on_click=_request_step, args=(next_step,),
                        disabled=next_disabled, key=f"next_to_{next_step}")
    return False


def _remove_task_termbase():
    for key in ("task_glossary", "task_glossary_name", "task_glossary_count"):
        st.session_state.pop(key, None)
    st.session_state.show_termbase_picker = False


def _remove_literature_uploads():
    for key in ("literature_uploads", "literature_upload_sources",
                "literature_upload_warnings"):
        st.session_state.pop(key, None)
    st.session_state.literature_uploader_generation = \
        st.session_state.get("literature_uploader_generation", 0) + 1


def _remove_literature_registry():
    for key in ("literature_registry_sources", "literature_registry_name",
                "literature_registry_signature", "literature_registry_warning"):
        st.session_state.pop(key, None)
    st.session_state.literature_registry_generation = \
        st.session_state.get("literature_registry_generation", 0) + 1


def _remove_report_template():
    for key in ("report_template_input", "report_template_error",
                "report_template_signature"):
        st.session_state.pop(key, None)
    st.session_state.report_template_removed = True
    st.session_state.report_template_uploader_generation = \
        st.session_state.get("report_template_uploader_generation", 0) + 1


def _render_report_template_input():
    """Capture the DOCX template separately from reference-material uploads."""
    template = st.session_state.get("report_template_input")
    if template:
        summary = _report_template.contract_summary(template.get("contract"))
        st.markdown(
            f'<div class="tp-attachment"><div><strong>{escape(str(template.get("name") or "模板.docx"))}</strong>'
            f'<span>已解析 · {summary.get("chapter_count", 0)} 个章节 · '
            f'{summary.get("subsection_count", 0)} 个小节</span></div></div>',
            unsafe_allow_html=True)
        st.button("移除报告模板", key="remove_report_template",
                  on_click=_remove_report_template, width="stretch")
        with st.expander("查看模板结构与格式契约", expanded=False):
            st.caption(
                f"模板哈希：{str(summary.get('template_hash') or '')[:16]} · "
                "模板章节、标题层级、前后置部分与 DOCX 样式将作为报告约束。")
            structure = template["contract"].get("document_structure") or {}
            for chapter in structure.get("chapters") or []:
                subs = "、".join(str(x.get("title")) for x in
                                  chapter.get("required_subsections") or [])
                st.markdown(
                    f"- **{chapter.get('section_id')} {chapter.get('title')}**"
                    f"（{chapter.get('role')}）"
                    + (f"：{subs}" if subs else ""))
            if structure.get("front_matter"):
                st.caption("前置部分：" + "、".join(
                    str(x.get("title")) for x in structure["front_matter"]))
            if structure.get("back_matter"):
                st.caption("后置部分：" + "、".join(
                    str(x.get("title")) for x in structure["back_matter"]))
        return

    uploaded = st.file_uploader(
        "论文 / 翻译实践报告模板（DOCX，可选但推荐）",
        type=["docx"],
        key=f"report_template_uploader_"
            f"{st.session_state.get('report_template_uploader_generation', 0)}",
        help="模板会固定报告章节、标题层级、前后置部分和 Word 样式；未上传时使用通用 DOCX。",
    )
    if uploaded:
        raw = uploaded.getvalue()
        signature = (uploaded.name, len(raw), raw[:32])
        if signature != st.session_state.get("report_template_signature"):
            try:
                contract = _report_template.parse_docx_template(uploaded.name, raw)
                st.session_state.report_template_input = {
                    "name": uploaded.name, "bytes": raw, "contract": contract,
                }
                st.session_state.report_template_error = None
                st.session_state.report_template_signature = signature
                st.session_state.report_template_removed = False
                st.rerun()
            except _report_template.TemplateParseError as exc:
                st.session_state.report_template_error = str(exc)
                st.session_state.report_template_signature = signature
    if st.session_state.get("report_template_error"):
        st.error("报告模板无法使用：" + str(st.session_state.report_template_error))


def _render_literature_inputs():
    """Show user-facing reference uploads; registry JSON stays an advanced escape hatch."""
    uploads = st.session_state.get("literature_uploads") or []
    if uploads:
        names = [escape(str(item.get("name") or "未命名资料")) for item in uploads]
        label = names[0] if len(names) == 1 else f"{names[0]} 等 {len(names)} 个文件"
        st.markdown(
            f'<div class="tp-attachment"><div><strong>{label}</strong>'
            f'<span>已添加参考资料 · 系统将在运行时解析并记录来源位置</span></div></div>',
            unsafe_allow_html=True)
        st.button("移除参考资料", key="remove_literature_uploads",
                  on_click=_remove_literature_uploads, width="stretch")
    else:
        uploaded = st.file_uploader(
            "上传参考资料",
            type=["pdf", "docx", "md", "markdown", "txt", "bib", "ris"],
            accept_multiple_files=True,
            key=f"literature_uploads_"
                f"{st.session_state.get('literature_uploader_generation', 0)}",
            help="支持 PDF、DOCX、Markdown、TXT、BibTeX / RIS（含 Zotero 导出）",
        )
        if uploaded:
            files = [{"name": item.name, "bytes": item.getvalue()} for item in uploaded]
            sources, warnings = _literature_evidence.build_sources_from_uploads(
                files, core.OUTPUT_DIR)
            st.session_state.literature_uploads = files
            st.session_state.literature_upload_sources = sources
            st.session_state.literature_upload_warnings = warnings
            st.rerun()
    for warning in st.session_state.get("literature_upload_warnings") or []:
        st.warning(warning)

    with st.expander("高级选项", expanded=False):
        st.caption("用于恢复已有工作流；普通用户无需准备 JSON。")
        registry_file = st.file_uploader(
            "导入已有文献证据注册表（.json）",
            type=["json"],
            key=f"literature_registry_"
                f"{st.session_state.get('literature_registry_generation', 0)}",
            help="仅支持已有 Literature Evidence Registry JSON",
        )
        if registry_file:
            raw = registry_file.getvalue()
            signature = (registry_file.name, len(raw))
            if signature != st.session_state.get("literature_registry_signature"):
                try:
                    loaded = json.loads(raw.decode("utf-8-sig"))
                    if isinstance(loaded, dict):
                        loaded = loaded.get("sources") or []
                    if not isinstance(loaded, list) \
                            or not all(isinstance(item, dict) for item in loaded):
                        raise ValueError("JSON 中没有可用的 sources 列表")
                    st.session_state.literature_registry_sources = loaded
                    st.session_state.literature_registry_name = registry_file.name
                    st.session_state.literature_registry_warning = None
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                    st.session_state.literature_registry_warning = f"注册表无法导入：{exc}"
                st.session_state.literature_registry_signature = signature
        if st.session_state.get("literature_registry_warning"):
            st.warning(st.session_state.literature_registry_warning)
        if st.session_state.get("literature_registry_sources") is not None:
            registry_name = escape(str(
                st.session_state.get("literature_registry_name") or "已有注册表"))
            registry_count = len(st.session_state.get("literature_registry_sources") or [])
            st.caption(f"已导入 {registry_name} · {registry_count} 条来源")
            st.button("移除已有注册表", key="remove_literature_registry",
                      on_click=_remove_literature_registry, width="stretch")


def _remove_source_documents():
    st.session_state.pop("task_files", None)
    st.session_state.pop("source_parse_state", None)
    st.session_state.pop("step_gate_message", None)
    for key in ("style_profiling_state", "doc_profile", "style_recommendation",
                "style_selection", "style_profile_warnings",
                "style_adjust_open", "style_analysis_open",
                "style_profiling_needs_api"):
        st.session_state.pop(key, None)
    st.session_state.source_uploader_generation = \
        st.session_state.get("source_uploader_generation", 0) + 1


def _source_file_html(task_files):
    total_size = sum(len(item.get("bytes") or b"") for item in task_files)
    count = len(task_files)
    raw_name = task_files[0].get("name") or "未命名文档"
    first_name = escape(raw_name)
    name = first_name if count == 1 else f"{first_name} 等 {count} 个文件"
    parse_state = st.session_state.get("source_parse_state", "uploaded")
    page_total = sum(int(item.get("pages") or 0) for item in task_files)
    parsed_detail = f"{_format_size(total_size)}" \
        f'{f" · {page_total:,} 页" if page_total else ""}'
    meta = {
        "uploaded": (_format_size(total_size), "已上传，等待解析"),
        "parsing": (_format_size(total_size), "正在解析…"),
        "parsed": (parsed_detail, "文件已就绪"),
        "error": (_format_size(total_size), "解析失败"),
    }
    detail, status = meta.get(parse_state, meta["uploaded"])
    icon = "progress_activity" if parse_state == "parsing" else "description"
    icon_class = "material-symbols-rounded is-loading" if parse_state == "parsing" \
        else "material-symbols-rounded"
    ready_badge = '<span class="tp-source-ready">已就绪</span>' \
        if parse_state == "parsed" else ""
    return (
        '<div class="tp-source-file">'
        f'<span class="{icon_class}" aria-hidden="true">{icon}</span>'
        f'<div class="tp-source-file-copy"><strong title="{escape(raw_name, quote=True)}">'
        f'{name}</strong>'
        f'<span>{detail} · <b class="tp-source-file-status is-{parse_state}">'
        f'{status}</b></span></div>{ready_badge}</div>'
    )


def _preset_card_html(label):
    cards = {
        "快速": ("快速生成可读初稿", "翻译 → 基础检查", ("最快", "成本最低")),
        "标准": ("兼顾质量与效率", "全文理解 → 术语增强 → 翻译 → 基础检查",
                 ("术语更一致", "成本适中")),
        "学术增强": ("适合需要完整过程证据的任务",
                 "全文理解 → 术语治理 → 翻译 → 独立审校 → 学术证据",
                 ("证据最完整", "耗时较长")),
    }
    purpose, workflow, tags = cards[label]
    badge = '<span class="tp-preset-badge">推荐</span>' if label == "标准" else ""
    icon = "radio_button_checked" if label == st.session_state.get(
        "translation_preset", "标准") else "radio_button_unchecked"
    tag_html = "".join(
        f'<span class="tp-preset-tag">{tag}</span>' for tag in tags)
    return (
        '<div class="tp-preset-card">'
        '<div class="tp-preset-head">'
        f'<span class="material-symbols-rounded" aria-hidden="true">{icon}</span>'
        f'<strong>{label}</strong>{badge}</div>'
        f'<p class="tp-preset-purpose">{purpose}</p>'
        f'<p class="tp-preset-flow">{workflow}</p>'
        f'<div class="tp-preset-tags">{tag_html}</div></div>'
    )


def _render_strategy_toggle(label, description, option, key, config):
    with st.container(key=f"{key}_row"):
        copy_col, switch_col = st.columns([9, 1], vertical_alignment="center")
        copy_col.markdown(
            f'<div class="tp-setting-copy"><strong>{label}</strong>'
            f'<span>{description}</span></div>', unsafe_allow_html=True)
        switch_col.toggle(label, value=config[option], key=key,
                          label_visibility="collapsed",
                          on_change=_set_strategy_option, args=(option, key),
                          help=description, **_PERSIST_STATE)


def _format_size(size):
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{max(1, round(size / 1024))} KB"


def _summary_html(filename, target_lang, preset_label, glossary_name,
                  strategy_config, output_config, style_template,
                  style_source=""):
    filename = escape(str(filename))
    target_lang = escape(str(target_lang))
    preset_label = escape(str(preset_label))
    glossary_name = escape(str(glossary_name))
    workflow = []
    if strategy_config.get("enable_understanding"):
        workflow.append("全文理解")
    if strategy_config["strict_terminology_governance"]:
        workflow.append("术语治理")
    elif strategy_config["auto_term"]:
        workflow.append("术语增强")
    workflow.extend(["翻译", "基础检查"])
    if strategy_config["enable_review"]:
        workflow.append("独立审校")
    if output_config["enable_annotate"]:
        workflow.append("重点标注")
    if output_config["enable_report"]:
        workflow.extend(["学术证据", "实践报告"])
    mode_label = preset_label
    if _strategy_is_adjusted(preset_label, strategy_config) \
            or _output_is_adjusted(preset_label, output_config):
        mode_label += " · 已调整"
    artifacts = []
    if output_config.get("deliver_plain_docx"):
        artifacts.append(("description", "纯译文", "仅含译文文本", "DOCX"))
    if output_config.get("deliver_bilingual_docx"):
        artifacts.append(("description", "双语译文", "原文与译文对照", "DOCX"))
    if output_config.get("deliver_pdf"):
        artifacts.append(("picture_as_pdf", "PDF 译文", "便携格式译文", "PDF"))
    if output_config.get("deliver_terms_xlsx"):
        artifacts.append(("table", "术语表", "自动抽取与锁定术语", "XLSX"))
    for key, name in (("deliver_tbx", "TBX 术语库"),
                      ("deliver_tmx", "TMX 翻译记忆"),
                      ("deliver_jsonl", "JSONL 双语段落")):
        if output_config.get(key):
            artifacts.append(("code", name, "语言资产导出", "交换格式"))
    if output_config["enable_annotate"]:
        artifacts.append(("ink_highlighter", "重点标注版",
                          "标出生僻词、专业术语和翻译难点句", "DOCX"))
    if output_config["enable_report"]:
        artifacts.append(("article", "翻译实践报告",
                          "基于翻译过程证据生成", "DOCX / MD"))
        if output_config.get("deliver_review_report"):
            artifacts.append(("fact_check", "审校报告",
                              "审校发现与处理记录", "MD"))
    style_value = escape(str(
        style_template + (f"（{style_source}）" if style_source else "")))
    artifact_rows = "".join(
        '<div class="tp-artifact-row">'
        f'<span class="material-symbols-rounded" aria-hidden="true">{icon}</span>'
        f'<div><strong>{name}</strong><span>{detail}</span></div><b>{kind}</b></div>'
        for icon, name, detail, kind in artifacts)
    return (
        '<div class="tp-confirm-stack">'
        '<section class="tp-confirm-card"><div class="tp-confirm-head">'
        '<span class="material-symbols-rounded" aria-hidden="true">tune</span>'
        '<strong>任务配置</strong></div><div class="tp-summary-grid">'
        f'<div class="tp-summary-item"><span>原文</span><strong>{filename}</strong></div>'
        f'<div class="tp-summary-item"><span>目标语言</span><strong>{target_lang}</strong></div>'
        f'<div class="tp-summary-item"><span>翻译模式</span><strong>{mode_label}</strong></div>'
        f'<div class="tp-summary-item"><span>译文风格</span><strong>{style_value}</strong></div>'
        f'<div class="tp-summary-item"><span>术语库</span><strong>{glossary_name}</strong></div>'
        '<div class="tp-summary-item is-wide"><span>工作流</span>'
        f'<strong>{" → ".join(workflow)}</strong></div></div></section>'
        '<section class="tp-confirm-card"><div class="tp-confirm-head">'
        '<span class="material-symbols-rounded" aria-hidden="true">inventory_2</span>'
        '<strong>将生成</strong></div><div class="tp-artifact-list">'
        f'{artifact_rows}</div></section></div>')


def _runtime_html(provider, model, connection_status, can_start):
    provider = escape(str(provider))
    model = escape(str(model or "未配置"))
    connection = {
        "connected": ("已连接", "is-success"),
        "error": ("连接失败", "is-error"),
        "unverified": ("未验证", "is-neutral"),
    }.get(connection_status, ("未验证", "is-neutral"))
    if not can_start:
        readiness = ("需要配置", "is-warning")
    elif connection_status == "connected":
        readiness = ("可启动", "is-success")
    elif connection_status == "error":
        readiness = ("需检查连接", "is-error")
    else:
        readiness = ("待验证", "is-warning")
    return (
        '<section class="tp-confirm-card tp-runtime-card">'
        '<div class="tp-confirm-head"><span class="material-symbols-rounded" '
        'aria-hidden="true">memory</span><strong>运行环境</strong></div>'
        '<div class="tp-runtime-grid">'
        f'<div><span>AI 引擎</span><strong>{provider}</strong></div>'
        f'<div><span>模型</span><strong>{model}</strong></div>'
        f'<div><span>连接状态</span><strong class="tp-status {connection[1]}">'
        f'{connection[0]}</strong></div>'
        f'<div><span>启动状态</span><strong class="tp-status {readiness[1]}">'
        f'{readiness[0]}</strong></div></div></section>')


def _render_profile_editor(job_id, state, box=None):
    box = box or st
    profile = state.get("document_profile") or {}
    with box.expander("文档画像（AI 生成，可修改后保存）", expanded=False):
        c1, c2, c3 = box.columns(3)
        domain = c1.text_input("领域 domain", value=profile.get("domain") or "",
                               key=f"pf_d_{job_id}")
        subdomain = c2.text_input("细分领域 subdomain",
                                  value=profile.get("subdomain") or "",
                                  key=f"pf_sd_{job_id}")
        genre = c3.text_input("文本类型 genre", value=profile.get("genre") or "",
                              key=f"pf_g_{job_id}")
        audience = c1.text_input("读者 audience", value=profile.get("audience") or "",
                                 key=f"pf_a_{job_id}")
        register = c2.text_input("语域 register", value=profile.get("register") or "",
                                 key=f"pf_r_{job_id}")
        confidence = c3.slider("置信度", 0.0, 1.0,
                               float(profile.get("confidence") or 0.0),
                               key=f"pf_c_{job_id}")
        style_constraints = box.text_area(
            "风格约束 style_constraints",
            value=profile.get("style_constraints") or "", key=f"pf_sc_{job_id}")
        if box.button("保存文档画像", key=f"pf_save_{job_id}"):
            core.save_document_profile(job_id, {
                "domain": domain, "subdomain": subdomain, "genre": genre,
                "audience": audience, "register": register,
                "style_constraints": style_constraints, "confidence": confidence,
                "sections": profile.get("sections") or [],
            })
            st.rerun()
        secs = profile.get("sections") or []
        if secs:
            box.caption("分节：" + "；".join(
                f"{x.get('section_id')}（段落 {x.get('start_segment')}-{x.get('end_segment')}"
                f"，{x.get('topic') or x.get('domain') or '?'}）" for x in secs))
        elif not state.get("profile_done"):
            box.caption("画像未生成（AI 失败或已跳过），可在此人工填写后保存。")

def _asset_prefix(state, snapshot_current=False):
    """Only a currently matching frozen snapshot may use the final prefix."""
    return "final_" if snapshot_current and state.get("delivery_status") == "final" else "draft_"


def _render_snapshot_versions(job_id, state, location):
    snapshots = core.list_delivery_snapshots(job_id)
    if not snapshots:
        return
    filename = Path(str(state.get("filename") or "document")).stem or "document"
    with st.expander("最终交付版本", expanded=False):
        st.caption("历史版本来自已冻结文件，不会随当前工作版本变化。")
        for snapshot in reversed(snapshots):
            version = snapshot["snapshot_version"]
            approval = snapshot.get("approval") or {}
            st.markdown(f"**最终交付版本 v{version}** · 已冻结")
            st.caption(
                f"确认时间：{approval.get('timestamp') or snapshot.get('created_at') or '—'} · "
                f"交付说明：{approval.get('note') or '—'} · "
                f"资产：{len(snapshot.get('assets') or [])} 项")
            archive = core.delivery_snapshot_archive(job_id, version)
            if archive is not None:
                st.download_button(
                    f"下载最终交付版本 v{version}", archive,
                    file_name=f"final_delivery_v{version}_{filename}.zip",
                    mime="application/zip",
                    key=f"snapshot_download_{location}_{job_id}_v{version}",
                    width="stretch")


def _review_sort_key(context):
    return (
        _delivery.SEVERITY_ORDER.get(context.get("severity"), 99),
        context.get("segment_index") if context.get("segment_index") is not None else 10**9,
        context.get("finding_id") or "",
    )


def _review_phase_label(phase):
    return {
        "formal_review": "正式审校",
        "shadow_repair": "自动修订复核",
        "suggested_shadow_review": "建议译文复核",
    }.get(phase, phase or "审校记录")


def _render_finding_evidence(context):
    refs = context.get("evidence_refs") or []
    traces = context.get("review_evidence") or []
    if refs:
        st.caption("该问题引用的证据：" + "、".join(refs))
    if not traces:
        st.caption("暂无额外证据请求；以上原文与译文来自任务本地记录。")
        return
    with st.expander("审校 / 证据详情", expanded=False):
        for trace in traces[-3:]:
            status = (trace.get("completion_receipt") or {}).get("status") or "-"
            evidence_ids = "、".join(trace.get("evidence_ids") or []) or "无"
            st.caption(
                f"{_review_phase_label(trace.get('phase'))} · "
                f"结论 {trace.get('decision') or '-'} · 状态 {status} · "
                f"证据 {evidence_ids}")
            for request in (trace.get("requests") or [])[:4]:
                tool = request.get("tool") or "evidence"
                evidence_id = request.get("evidence_id") or "-"
                arguments = request.get("arguments") or {}
                st.caption(f"{evidence_id} · {tool} · {arguments}")


def _format_saved_at(value):
    if not value:
        return "尚无保存记录"
    return str(value).replace("T", " ")[:19]


def _render_recovery_panel(job_id, state):
    summary = core.recovery_summary(job_id, state)
    status = core.task_status_label(state, job_id)
    with st.container(border=True):
        st.subheader("任务状态与自动保存")
        c1, c2, c3 = st.columns(3)
        c1.metric("当前状态", status)
        batch_count = (f"{summary['completed_batch_count']}/{summary['total_batches']}"
                       if summary["total_batches"] else "—")
        c2.metric("已完成处理批次", batch_count)
        c3.metric("自动保存", "已开启")
        st.caption(f"最近保存进度：{_format_saved_at(summary['last_saved_at'])} · "
                   f"最近完成阶段：{summary['last_completed_stage']}")
        current = summary.get("current_batch")
        if current:
            st.warning(
                f"第 {current['number']} 个处理批次中断：已保存本批次 "
                f"{current['completed_segments']}/{current['segment_count']} 段。"
                f"继续时会重新执行本批次剩余内容（最多重新执行 "
                f"{current['regenerate_segments']} 段），此前已保存的批次不会重做。")
        if summary["recovered_tm_entries"]:
            st.info(f"已从上次中断中恢复 {summary['recovered_tm_entries']} 条翻译记忆同步记录。")
        if summary["can_resume"] and st.button(
                "继续处理", type="primary", key=f"resume_workspace_{job_id}",
                width="stretch"):
            st.session_state.update(
                active_job_id=job_id, app_view="workspace", workspace_mode=True)
            _resume_job(job_id, state)
            st.rerun()


def _context_status_label(status):
    return {
        "model": "模型生成",
        "deterministic_fallback": "临时摘要",
        "pending": "生成中",
        "unavailable": "不可用",
    }.get(str(status or ""), "未记录")


def _target_context_level_label(level):
    return {
        "human_accepted": "人工确认",
        "reviewed": "独立审校",
        "tm_approved": "翻译记忆",
        "generated": "自动译文（未确认）",
    }.get(level, "未标注")


def _render_context_surface(job_id, state):
    st.header("文档上下文")
    st.caption("查看系统对全文、当前内容单元和前文译文连续性的理解。")
    artifacts = core.load_context_artifacts(job_id, state)
    units = artifacts["semantic_units"]
    digests = artifacts["section_digests"]
    synopsis = artifacts["document_synopsis"]
    recovery = core.recovery_summary(job_id, state)
    pairs = state.get("pairs") or []
    current_batch = recovery.get("current_batch")
    if current_batch:
        current_index = current_batch.get("start_segment", len(pairs)) \
            + current_batch.get("completed_segments", 0)
        st.info(
            f"当前处理批次：第 {current_batch['number']} 批 · "
            f"本批已保存 {current_batch['completed_segments']}/{current_batch['segment_count']} 段。")
    else:
        current_index = len(pairs)
        if state.get("p2_done"):
            st.success("翻译批次已完成；以下显示最近使用的上下文。")
        else:
            st.caption("翻译尚未形成批次记录；以下可查看已经生成的全文理解。")
    current_index = max(0, min(current_index, len(state.get("paras") or pairs)))

    synopsis_status = _context_status_label(synopsis.get("status"))
    accepted_context = _context.select_target_context(
        pairs, current_index, limit=4)
    metric_cols = st.columns(3)
    metric_cols[0].metric("内容单元", len(units))
    metric_cols[1].metric("章节摘要", len(digests))
    metric_cols[2].metric("前文连续性", f"{len(accepted_context)} 条")

    with st.container(border=True):
        st.subheader("全文概要")
        if synopsis.get("summary"):
            st.write(synopsis["summary"])
            if synopsis.get("document_arc"):
                st.markdown(f"**全文发展/论证**：{synopsis['document_arc']}")
            for label, key in (("主题", "themes"), ("关键实体", "entities"),
                               ("关键概念", "terms"), ("翻译连续性提示", "translation_notes")):
                values = synopsis.get(key) or []
                if values:
                    st.caption(f"{label}：" + "、".join(values))
            st.caption(f"概要状态：{synopsis_status}")
        else:
            st.info(
                "当前任务没有可用的全文概要。可能是快速模式运行，或全文理解尚未完成；"
                "这不会阻止翻译继续。")

    if units:
        digest_by_unit = {str(item.get("unit_id")): item for item in digests
                          if isinstance(item, dict)}
        def unit_label(index):
            unit = units[index]
            label = unit.get("label") or f"内容单元 {index + 1}"
            return f"{label} · 第 {unit.get('start_segment', 0) + 1}-{unit.get('end_segment', 0) + 1} 段"

        default_unit = 0
        for index, unit in enumerate(units):
            if unit.get("start_segment", 0) <= current_index <= unit.get("end_segment", -1):
                default_unit = index
                break
            if unit.get("start_segment", 0) <= max(0, current_index - 1) \
                    <= unit.get("end_segment", -1):
                default_unit = index
        selected_unit = st.selectbox(
            "当前章节/内容单元", range(len(units)), index=default_unit,
            format_func=unit_label, key=f"context_unit_{job_id}")
        unit = units[selected_unit]
        digest = digest_by_unit.get(str(unit.get("unit_id")))
        with st.container(border=True):
            st.subheader("章节摘要")
            st.caption(unit_label(selected_unit))
            if digest and digest.get("summary"):
                st.write(digest["summary"])
                for label, key in (("关键实体", "key_entities"), ("关键概念", "key_terms"),
                                   ("待确认线索", "open_threads"),
                                   ("翻译提示", "translation_notes")):
                    values = digest.get(key) or []
                    if values:
                        st.caption(f"{label}：" + "、".join(values))
            else:
                st.info("该内容单元暂无章节摘要。")
    elif not synopsis.get("summary"):
        st.info("当前任务没有可展示的内容单元或章节摘要。")

    with st.container(border=True):
        st.subheader("上下文连续性")
        if accepted_context:
            st.caption("最近批次/最近译文参考的前文内容如下；标签表示译文的确认程度。")
            for item in accepted_context:
                with st.expander(
                        f"第 {item['segment_index'] + 1} 段 · "
                        f"{_target_context_level_label(item['level'])}", expanded=False):
                    st.markdown("**前文原文**")
                    st.code(item["source"] or "（无原文记录）")
                    st.markdown("**前文译文**")
                    st.code(item["target"])
        else:
            st.info("当前没有可用的前文译文连续性记录。")

        packet_log = state.get("context_packet_log") or []
        if packet_log:
            latest = packet_log[-1]
            previous_count = len(latest.get("previous_target_segments") or [])
            st.caption(
                f"最近一次处理参考了全文概要、当前章节摘要、前文原文，"
                f"以及 {previous_count} 条前文译文连续性记录。")
        else:
            st.caption("当前任务尚无已保存的批次上下文参考记录。")

    warnings = artifacts.get("warnings") or []
    if warnings:
        with st.expander("上下文生成提示", expanded=False):
            for warning in warnings:
                st.warning(warning)
    if state.get("context_packet_log"):
        with st.expander("高级诊断", expanded=False):
            st.caption("仅供排查使用；正常工作不需要查看内部记录。")
            st.json(state["context_packet_log"][-5:])


def _render_terminology_version(state):
    entries = state.get("glossary") or []
    frozen = state.get("glossary_frozen") or {}
    versions = state.get("glossary_versions") or []
    status = "已冻结" if frozen else "草稿，尚未冻结"
    version = frozen.get("version") if frozen else "—"
    recent = frozen.get("frozen_at") if frozen else "暂无冻结版本"
    st.caption(
        f"当前术语版本：v{version} · 状态：{status} · 条目数量：{len(entries)} · "
        f"最近变更：{str(recent or '暂无记录').replace('T', ' ')[:19]}")
    if versions:
        st.caption(f"历史版本 {len(versions)} 个；旧版本保留，不在普通界面显示哈希。")


def _render_knowledge_library(saved_jobs):
    st.subheader("待确认词条")
    st.caption("这些词条来自翻译过程中的知识观察，默认不会成为锁定术语。")
    pending = []
    for job in saved_jobs:
        state = job["state"]
        candidates = [item for item in state.get("knowledge_candidates") or []
                      if isinstance(item, dict) and not item.get("decision")]
        for candidate in candidates:
            pending.append((job, state, _knowledge.candidate_context(candidate, state)))
    if not pending:
        st.info("当前没有待确认词条。通过审校的译文会在后续批次产生新的知识观察。")
        return

    query = st.text_input(
        "搜索待确认词条", key="knowledge_library_search",
        placeholder="输入源语、译名或文档名…",
        help="按源语、建议译名、文档名或上下文筛选待确认词条")
    normalized_query = query.strip().casefold()
    if normalized_query:
        pending = [item for item in pending if normalized_query in " ".join(
            str(value or "") for value in (
                item[0]["state"].get("filename"), item[2].get("source"),
                item[2].get("proposed_target"), item[2].get("source_context"),
                item[2].get("target_context"))).casefold()]

    limit_key = "knowledge_library_visible_count"
    query_key = "knowledge_library_last_query"
    if st.session_state.get(query_key) != normalized_query:
        st.session_state[limit_key] = 20
        st.session_state[query_key] = normalized_query
    visible_count = max(20, int(st.session_state.get(limit_key, 20)))
    visible = pending[:visible_count]
    st.caption(f"显示 {len(visible)} / {len(pending)} 条待确认词条")

    for job in saved_jobs:
        job_items = [item for item in visible if item[0]["job_id"] == job["job_id"]]
        if not job_items:
            continue
        filename = job["state"].get("filename", "?")
        total_for_job = sum(1 for item in pending if item[0]["job_id"] == job["job_id"])
        with st.expander(
                f"{filename} · {len(job_items)} / {total_for_job} 条待确认词条",
                expanded=True):
            for _, state, context in job_items:
                cid = context["candidate_id"]
                with st.container(key=f"knowledge_candidate_{job['job_id']}_{cid}"):
                    st.markdown(
                        f"**{context['source']}** → **{context['proposed_target']}**")
                    segment = context["first_observed_segment"]
                    segment_label = f"第 {segment + 1} 段" if segment is not None else "段落未知"
                    try:
                        confidence = float(context["confidence"] or 0)
                    except (TypeError, ValueError):
                        confidence = 0.0
                    st.caption(
                        f"首次出现：{segment_label} · 出现 {len(context['occurrences'])} 次 · "
                        f"类型：{'术语' if context['kind'] == 'term' else '专名' if context['kind'] == 'name' else '固定表达'} · "
                        f"来源：翻译流观察 · 观察置信度：{confidence:.2f}")
                    if context["source_context"] or context["target_context"]:
                        source_col, target_col = st.columns(2)
                        with source_col:
                            st.markdown("**所在原文**")
                            st.code(context["source_context"] or "（未找到原文段落）")
                        with target_col:
                            st.markdown("**所在译文**")
                            st.code(context["target_context"] or "（未找到译文段落）")
                    if context["conflicts"]:
                        st.warning(
                            "与现有项目术语存在译名冲突：" + "；".join(
                                f"{item['target']}（{item['status']}）"
                                for item in context["conflicts"]))
                    else:
                        st.caption("未发现与当前项目术语的译名冲突。")
                    c1, c2, c3 = st.columns(3)
                    if c1.button(
                            "加入项目术语", disabled=bool(context["conflicts"]),
                            key=f"knowledge_project_{job['job_id']}_{cid}", width="stretch"):
                        _, ok, message = core.review_knowledge_candidate(
                            job["job_id"], cid, "project_term")
                        if ok:
                            st.success(message)
                            st.rerun()
                        st.error(message)
                    if c2.button(
                            "仅本任务采用", key=f"knowledge_task_{job['job_id']}_{cid}",
                            width="stretch"):
                        _, ok, message = core.review_knowledge_candidate(
                            job["job_id"], cid, "task_only")
                        if ok:
                            st.rerun()
                        st.error(message)
                    if c3.button(
                            "拒绝", key=f"knowledge_reject_{job['job_id']}_{cid}",
                            width="stretch"):
                        _, ok, message = core.review_knowledge_candidate(
                            job["job_id"], cid, "rejected")
                        if ok:
                            st.rerun()
                        st.error(message)
                    st.caption(
                        "可复用术语库：当前运行时没有全局术语库存储，因此不提供此操作。"
                        "项目术语会保存在本任务的术语版本中。")
    if len(pending) > visible_count:
        if st.button(
                f"显示更多（还剩 {len(pending) - visible_count} 条）",
                key="knowledge_library_more", width="stretch"):
            st.session_state[limit_key] = visible_count + 20
            st.rerun()


def _render_delivery_review_queue(
    job_id, state, target_lang, ai_provider, ai_model, api_key, style_rules,
):
    """Render the human review queue; delivery state changes stay in core.py."""
    findings = _delivery.review_queue_findings(state)
    contexts = sorted(
        [_delivery.finding_context(state, finding) for finding in findings],
        key=_review_sort_key)
    st.divider()
    st.subheader("人工审查队列")
    if not contexts:
        st.success("当前没有待处理发现；可以继续准备交付资产。")
        return

    counts = {severity: sum(1 for x in contexts if x["severity"] == severity)
              for severity in _delivery.SEVERITY_LABELS}
    st.caption(
        f"共 {len(contexts)} 个待审问题 · "
        f"必须处理 {counts['blocking']} · 建议检查 {counts['actionable']} · "
        f"仅供参考 {counts['informational']}。先处理必须处理项；相同审校事件的重复记录已合并，"
        "不同审校事件会分别保留。")
    metric_cols = st.columns(4)
    metric_cols[0].metric("待审", len(contexts))
    metric_cols[1].metric("必须处理", counts["blocking"])
    metric_cols[2].metric("建议检查", counts["actionable"])
    metric_cols[3].metric("仅供参考", counts["informational"])

    filter_options = ["必须处理", "全部", "建议检查", "仅供参考"]
    default_filter = "必须处理" if counts["blocking"] else "全部"
    filter_label = st.radio(
        "筛选发现", filter_options,
        index=filter_options.index(default_filter), horizontal=True,
        key=f"fd_filter_{job_id}")
    selected_severity = {
        "必须处理": "blocking", "建议检查": "actionable", "仅供参考": "informational",
    }.get(filter_label)
    visible = [x for x in contexts
               if selected_severity is None or x["severity"] == selected_severity]
    st.caption(f"当前显示 {len(visible)} 项；展开单项可查看原文、译文和审校证据。")

    selectable = [x for x in contexts if x["severity"] in ("blocking", "actionable")
                  or x["proper_noun_candidate"]]
    for ordinal, context in enumerate(visible):
        fid = context["finding_id"]
        interactive = context in selectable
        if interactive:
            st.checkbox(
                "选择此问题",
                key=f"fd_select_{job_id}_{fid}",
                help="选择后可在队列底部批量标记或重新翻译。")
        title = (
            f"第 {context['segment_number']} 段 · {context['severity_label']} · "
            f"{context['reason'][:100]}")
        if context["duplicate_count"] > 1:
            title += f" · 已合并 {context['duplicate_count']} 条重复记录"
        with st.expander(title, expanded=(ordinal == 0 and context["severity"] == "blocking")):
            st.caption(f"问题编号（调试/证据追踪）：{fid}")
            if context["detected_text"]:
                st.markdown("**检测到的文本**")
                st.code(context["detected_text"])
            source_col, target_col = st.columns(2)
            with source_col:
                st.markdown("**原文**")
                st.code(context["source"] or "（未找到对应段落）")
            with target_col:
                st.markdown("**当前译文**")
                st.code(context["target"] or "（未找到当前译文）")
            if context["initial_target"] and context["initial_target"] != context["target"]:
                st.caption("初译（当前译文之前）：")
                st.code(context["initial_target"])
            st.markdown(f"**问题说明**：{context['reason']}")
            if context["proper_noun_candidate"]:
                st.info(
                    "检测到的源语片段可能是人名、机构名或作品名。若确认这是有意保留，"
                    "可选择该问题并使用“确认保留专名”，不会强制重新翻译。")
            _render_finding_evidence(context)

    selected = [
        context for context in selectable
        if st.session_state.get(f"fd_select_{job_id}_{context['finding_id']}", False)
    ]
    selected_ids = [context["finding_id"] for context in selected]
    selected_segments = sorted({
        context["segment_index"] for context in selected
        if context["severity"] in ("blocking", "actionable")
        and isinstance(context["segment_index"], int)
    })
    preserve_ids = [
        context["finding_id"] for context in selected
        if context["proper_noun_candidate"]
    ]
    st.divider()
    st.caption(
        f"已选择 {len(selected)} 个问题 / {len(selected_segments)} 个段落。"
        "批量重新翻译按段落执行，同一段的多个问题会一起复验。")
    note = st.text_input("处理说明（可选）", key=f"fd_note_{job_id}")
    action_cols = st.columns(4)
    if action_cols[0].button(
            "标记选中为人工已处理", disabled=not selected_ids,
            key=f"fd_fix_{job_id}", width="stretch"):
        core.mark_findings_resolved(
            job_id, selected_ids, "human_fixed", note or "人工核对后确认已处理")
        st.rerun()
    if action_cols[1].button(
            "重新翻译选中段落", disabled=not selected_segments or not api_key,
            key=f"fd_retranslate_{job_id}", width="stretch"):
        core.retranslate_segments(
            job_id, selected_segments, ai_provider, api_key, ai_model,
            target_lang, style_rules=style_rules,
            on_caption=lambda text: st.caption(text))
        st.rerun()
    if action_cols[2].button(
            "确认保留选中专名", disabled=not preserve_ids,
            key=f"fd_preserve_{job_id}", width="stretch"):
        core.mark_findings_resolved(
            job_id, preserve_ids, "preserved",
            note or "用户确认该源语片段为有意保留的专名")
        st.rerun()
    if action_cols[3].button(
            "清除选择", disabled=not selected,
            key=f"fd_clear_{job_id}", width="stretch"):
        for context in selectable:
            st.session_state.pop(f"fd_select_{job_id}_{context['finding_id']}", None)
        st.rerun()
    if selected_segments and not api_key:
        st.warning("重新翻译需要先在设置中配置 API Key；人工处理和确认保留仍可使用。")


def _render_delivery_gate(job_id, state, dstatus, target_lang="", provider="", model=""):
    st.divider()
    st.subheader("最终交付")
    blockers = _delivery.unresolved_blocking(state)
    actions = _delivery.unresolved_findings(state)
    if blockers:
        hard_gate_reasons = _workspace_hard_gate_reasons(job_id, state)
        if hard_gate_reasons:
            st.error("当前版本存在不可通过‘接受风险’跳过的交付门禁：" +
                     "、".join(hard_gate_reasons) + "。请先完成这些门禁。")
            return
        st.warning(f"仍有 {len(blockers)} 个必须处理问题；未处理或未明确接受风险前不能最终交付。")
        confirm = st.checkbox(
            "我已检查这些必须处理问题，并确认接受剩余风险",
            key=f"fd_accept_confirm_{job_id}")
        note = st.text_input("接受风险说明", key=f"fd_accept_note_{job_id}")
        if st.button(
                "接受必须处理风险并进入最终交付",
                disabled=not confirm, key=f"fd_accept_{job_id}", width="stretch"):
            _, ok, errors = core.approve_delivery(
                job_id, note or "人工确认并接受剩余 blocking 风险", accept_blocking=True,
                target_lang=target_lang, provider=provider, model=model)
            if ok:
                st.rerun()
            for error in errors:
                st.error(error)
    elif dstatus == "final":
        snapshot = core.delivery_snapshot_status(job_id, state)
        if snapshot["current"]:
            latest = snapshot["latest"]
            st.success(
                f"最终交付版本 v{latest['snapshot_version']} 已冻结；"
                "后续工作版本变更不会修改该版本。")
        else:
            st.warning(
                "当前任务虽有最终状态，但没有可用的冻结交付版本，或工作版本已有变更；"
                "请重新确认以生成新的最终交付版本。")
            note = st.text_input("交付说明（可选）", key=f"fd_reapprove_note_{job_id}")
            if st.button("重新确认并冻结最终交付", key=f"fd_reapprove_{job_id}", width="stretch"):
                _, ok, errors = core.approve_delivery(
                    job_id, note or "重新确认最终交付", target_lang=target_lang,
                    provider=provider, model=model)
                if ok:
                    st.rerun()
                for error in errors:
                    st.error(error)
        return
    else:
        if actions:
            st.info(f"还有 {len(actions)} 个建议检查/参考项；它们不阻止最终交付。")
        note = st.text_input("最终交付说明（可选）", key=f"fd_final_note_{job_id}")
        if st.button("确认进入最终交付", key=f"fd_final_{job_id}", width="stretch"):
            _, ok, errors = core.approve_delivery(
                job_id, note or "人工确认交付", target_lang=target_lang,
                provider=provider, model=model)
            if ok:
                st.rerun()
            for error in errors:
                st.error(error)


# ================= 可视化辅助（证据链流程 / 术语状态） =================
def _chain_flow(stages):
    """横向流程卡片。"""
    boxes = []
    for i, (label, value, sub, color) in enumerate(stages):
        boxes.append(
            f'<div style="flex:1 1 130px;min-width:110px;padding:8px 12px;'
            f'border:1px solid {color}44;border-left:4px solid {color};'
            f'border-radius:8px;text-align:center;background:{color}10;">'
            f'<div style="font-size:12px;color:{color};font-weight:600;">{label}</div>'
            f'<div style="font-size:20px;font-weight:700;margin-top:1px;">{value}</div>'
            + (f'<div style="font-size:11px;opacity:.75;">{sub}</div>' if sub else "")
            + "</div>")
        if i < len(stages) - 1:
            boxes.append('<div style="align-self:center;color:#94a3b8;padding:0 2px;">→</div>')
    return ('<div style="display:flex;align-items:stretch;gap:2px;flex-wrap:wrap;'
            'margin:2px 0 8px;">' + "".join(boxes) + "</div>")


def _glossary_status_chips(entries):
    counts = {}
    for entry in entries:
        status = str(entry.get("status") or "provisional")
        counts[status] = counts.get(status, 0) + 1
    conflicts = sum(1 for entry in entries if _conflict(entry, entries))
    meta = [("候选", "candidate", "#64748b"), ("建议", "provisional", "#d97706"),
            ("已锁定", "locked", "#16a34a"), ("已拒绝", "rejected", "#dc2626")]
    chips = []
    for label, status, color in meta:
        chips.append(f'<span style="display:inline-block;padding:2px 12px;margin:0 6px 4px 0;'
                     f'border-radius:999px;border:1px solid {color};color:{color};'
                     f'font-size:13px;font-weight:600;">{label} {counts.get(status, 0)}</span>')
    conflict_label = f"冲突 {conflicts}" if conflicts else "无冲突"
    chips.append(f'<span style="display:inline-block;padding:2px 12px;border-radius:999px;'
                 f'border:1px solid #94a3b8;color:#64748b;font-size:13px;">{conflict_label}</span>')
    return '<div>' + "".join(chips) + "</div>"


def _merge_edited_entries(entries, edited_rows):
    """把编辑器可见行的修改合并回完整术语表。"""
    edited_by_id = {}
    new_rows = []
    for entry in edited_rows:
        entry_id = entry.get("id")
        if entry_id:
            edited_by_id[str(entry_id)] = entry
        else:
            new_rows.append(entry)
    merged = [edited_by_id.get(str(entry.get("id")), entry) for entry in entries]
    merged.extend(new_rows)
    return merged


# ================= Task workspace =================
def _workspace_review_contexts(state):
    findings = _delivery.review_queue_findings(state)
    return sorted([_delivery.finding_context(state, finding) for finding in findings],
                  key=_review_sort_key)


def _workspace_status(state, job_id=""):
    runtime_view = core.build_job_runtime_view(job_id, state) if job_id else {}
    runtime_status = runtime_view.get("runtime_status")
    if runtime_status in {"resume_requested", "queued", "starting", "running",
                          "waiting_external", "cancelling",
                          "stalled", "interrupted", "failed", "cancelled",
                          "idle_incomplete", "waiting_manual"}:
        tone = "danger" if runtime_status in {"failed", "interrupted"} else \
            "warning" if runtime_status in {"stalled", "cancelling", "waiting_manual"} else "neutral"
        return runtime_view.get("headline_status") or "未完成", tone
    if runtime_status == "completed" and state.get("report_enabled") \
            and not state.get("p3_done"):
        return "暂不满足交付条件", "warning"
    if job_id:
        return _workspace_delivery_state(job_id, state)
    if _delivery.unresolved_blocking(state):
        return "暂不满足交付条件", "warning"
    if state.get("p1_done"):
        return "处理中", "neutral"
    return "未开始", "neutral"


def _workspace_status_badge(label, tone="neutral"):
    return f'<span class="tp-status-badge is-{tone}"><span class="tp-status-dot is-{tone}"></span>{escape(label)}</span>'


def _workspace_findings_counts(state):
    contexts = _workspace_review_contexts(state)
    return contexts, {
        severity: sum(1 for item in contexts if item.get("severity") == severity)
        for severity in _delivery.SEVERITY_LABELS
    }


def _workspace_compliance_view(job_id, state):
    """Return the anonymous default-profile checks for this task."""
    return core.compliance_profile_view(job_id, state)


def _workspace_structural_qa(job_id, state):
    """Expose a stale DOCX check as a distinct user-facing state."""
    qa = _finalization.normalize_final_qa(state.get("final_qa"))
    final_docx = core.load_academic_artifact(job_id, "final_docx_validation") or {}
    structural = ("PASS" if final_docx.get("status") in {"pass", "pass_with_warnings"}
                  else "FAIL" if final_docx.get("status") == "fail"
                  else qa.get("structural_qa", "NOT_RUN"))
    artifact_status = _finalization._artifact_status_value(
        state.get("academic_state") or {}, "final_docx_validation")
    if artifact_status in {"stale", "missing"}:
        return "STALE"
    if artifact_status == "failed":
        return "FAIL"
    return structural


def _workspace_delivery_state(job_id, state):
    """Return one human-facing delivery state without changing gate semantics."""
    snapshot = core.delivery_snapshot_status(job_id, state) if job_id else {}
    if snapshot.get("current"):
        version = (snapshot.get("latest") or {}).get("snapshot_version")
        return (f"已冻结交付 v{version}" if version is not None else "已冻结交付", "success")
    if snapshot.get("diverged"):
        version = (snapshot.get("latest") or {}).get("snapshot_version")
        return (f"工作版本已偏离冻结交付 v{version}" if version is not None
                else "工作版本已偏离冻结交付", "warning")

    blockers = _delivery.unresolved_blocking(state)
    impact = core.dependency_impact_view(job_id, state) if job_id else {}
    compliance = _workspace_compliance_view(job_id, state) if job_id else {}
    compliance_counts = compliance.get("counts") or {}
    qa = _finalization.normalize_final_qa(state.get("final_qa"))
    academic = state.get("academic_state") or {}
    report_required = bool(state.get("report_enabled"))
    report_ready = _delivery.report_ready(state)
    stale_artifacts = any(
        _finalization._artifact_status_value(academic, name) in {"stale", "missing", "failed"}
        for name in ("report", "final_docx_validation", "libreoffice_render")
    )
    structural = _workspace_structural_qa(job_id, state) if job_id else qa.get("structural_qa")
    case_gate = _finalization.case_review_gate(
        state, core.load_academic_artifact(job_id, "selected_cases") if job_id else None)
    translation_ready = (bool(state.get("p2_done")) and not blockers and
                         (state.get("delivery_validation") or {}).get("blocking") is not True)
    technical_blocker = (
        not translation_ready or impact.get("status") == "stale" or
        (report_required and (not report_ready or stale_artifacts)) or
        case_gate.get("status") == "blocked" or compliance_counts.get("fail") or
        compliance.get("status") == "fail" or structural in {"FAIL", "STALE"} or
        (report_required and qa.get("libreoffice_render") == "FAIL")
    )
    manual_pending = (
        case_gate.get("blocked_count", 0) or compliance_counts.get("manual_review") or
        compliance_counts.get("not_checked") or
        (report_required and qa.get("author_visual_review") != "CONFIRMED") or
        (report_required and qa.get("word_final_review") != "CONFIRMED") or
        (report_required and structural == "NOT_RUN") or
        (report_required and qa.get("libreoffice_render") == "NOT_RUN")
    )
    if technical_blocker:
        tone = "danger" if blockers or compliance_counts.get("fail") or structural == "FAIL" else "warning"
        return "暂不满足交付条件", tone
    if manual_pending:
        return "暂不满足交付条件", "warning"
    return "可以冻结交付", "success"


def _workspace_hard_gate_reasons(job_id, state):
    """Return delivery gates that cannot be waived as ordinary review risk."""
    impact = core.dependency_impact_view(job_id, state) if job_id else {}
    compliance = _workspace_compliance_view(job_id, state) if job_id else {}
    compliance_counts = compliance.get("counts") or {}
    qa = _finalization.normalize_final_qa(state.get("final_qa"))
    finalization_qa_required = bool(state.get("report_enabled"))
    academic = state.get("academic_state") or {}
    report_ready = _delivery.report_ready(state)
    report_stale = _finalization._artifact_status_value(academic, "report") in {
        "stale", "missing", "failed"}
    final_export_stale = _finalization._artifact_status_value(
        academic, "final_docx_validation") in {"stale", "missing", "failed"}
    render_stale = _finalization._artifact_status_value(
        academic, "libreoffice_render") in {"stale", "missing", "failed"}
    structural = _workspace_structural_qa(job_id, state) if job_id else qa.get("structural_qa")
    case_gate = _finalization.case_review_gate(
        state, core.load_academic_artifact(job_id, "selected_cases") if job_id else None)
    translation_truth_gate_pass = (bool(state.get("p2_done")) and
                                   (state.get("delivery_validation") or {}).get("blocking") is not True)
    reasons = []
    if not translation_truth_gate_pass:
        reasons.append("当前译文交付门禁")
    if impact.get("status") == "stale":
        reasons.append("受影响产物需要重建")
    if finalization_qa_required and not report_ready:
        reasons.append("报告尚未通过交付门禁")
    if finalization_qa_required and (report_stale or final_export_stale or render_stale):
        reasons.append("交付产物仍是旧版本")
    if case_gate.get("status") == "blocked":
        reasons.append("案例来源或终审条件未满足")
    if compliance_counts.get("fail") or compliance_counts.get("manual_review") or compliance_counts.get("not_checked"):
        reasons.append("合规门禁尚未完成")
    if finalization_qa_required and structural != "PASS":
        reasons.append("DOCX 结构检查尚未通过")
    if finalization_qa_required and qa.get("libreoffice_render") != "PASS":
        reasons.append("页面渲染尚未通过")
    if finalization_qa_required and qa.get("author_visual_review") != "CONFIRMED":
        reasons.append("作者视觉复核尚未确认")
    if finalization_qa_required and qa.get("word_final_review") != "CONFIRMED":
        reasons.append("Word 最终复核尚未确认")
    return list(dict.fromkeys(reasons))


def _workspace_impact_change_label(impact):
    indexes = impact.get("changed_segment_indexes") or []
    if len(indexes) == 1:
        try:
            return f"第 {int(indexes[0]) + 1} 段已编辑"
        except (TypeError, ValueError):
            pass
    if indexes:
        return f"{len(indexes)} 个段落已编辑"
    return "下游内容发生变化"


def _workspace_impact_reason(impact):
    reason = str(impact.get("reason") or "")
    if "CURRENT_TRANSLATION" in reason or "工作译文" in reason:
        return "工作译文发生变化，相关案例与报告产物需要更新。"
    if reason:
        return reason.replace("stale", "需要更新")
    return "相关下游内容需要更新。"


def _workspace_impact_label(item):
    labels = {
        "literature_sources": "文献来源",
        "literature_evidence": "文献证据",
        "literature_claims": "文献主张",
        "literature_support_review": "文献支持复核",
        "human_evidence": "人工证据",
        "human_evidence_needs": "人工证据需求",
        "human_evidence_questions": "人工证据问题",
        "final_contrast_portfolio": "案例对照组合",
        "legacy_inventory": "历史资料清单",
        "legacy_recovery": "历史资料恢复",
        "legacy_recovery_report": "历史资料恢复报告",
        "quality_repair_history": "质量修复记录",
        "repair_history": "修复记录",
    }
    raw_id = str(item.get("id") or "")
    raw_label = str(item.get("label") or "")
    if raw_label and raw_label != raw_id:
        return raw_label
    mapped = labels.get(raw_id) or _finalization.artifact_label(raw_id)
    return mapped if mapped != raw_id else "相关产物"


def _workspace_impact_action(item):
    action = item.get("action")
    if action:
        return _finalization.execution_action_label(action)
    return {
        "stale": "需要重建",
        "missing": "需要生成",
        "failed": "检查失败",
        "valid": "已同步",
        "reusable": "可复用",
    }.get(str(item.get("status") or ""), "需要确认")


def _render_workspace_impact_expander(impact):
    affected = impact.get("affected") or []
    reusable = impact.get("reusable") or []
    with st.expander("查看影响", expanded=False):
        st.markdown('<div class="tp-impact-chain">'
                    f'<div class="tp-impact-chain-row"><i>1</i><strong>发生变化</strong>'
                    f'<span>{escape(_workspace_impact_change_label(impact))}</span></div>'
                    f'<div class="tp-impact-chain-row"><i>2</i><strong>需要更新</strong>'
                    f'<span>{len(affected)} 项下游产物：{escape("、".join(_workspace_impact_label(item) + " · " + _workspace_impact_action(item) for item in affected) or "相关学术下游")}</span></div>'
                    f'<div class="tp-impact-chain-row"><i>3</i><strong>可以复用</strong>'
                    f'<span>{len(reusable)} 个未受影响单元/资产；案例、写作单元和支持资料保留。</span></div>'
                    '</div>', unsafe_allow_html=True)


def _workspace_case_views(job_id, state):
    selected = core.load_academic_artifact(job_id, "selected_cases") or {}
    project_evidence = core.load_academic_artifact(job_id, "evidence") or {}
    argument_plan = core.load_academic_artifact(job_id, "argument_plan") or {}
    case_analysis_plans = core.load_academic_artifact(
        job_id, "case_analysis_plans") or {}
    outline = core.load_academic_artifact(job_id, "outline") or {}
    literature = core.load_academic_artifact(job_id, "literature_sources") or {}
    cases = selected.get("cases") or []
    evidence_segments = ((project_evidence.get("project_evidence") or {}).get("segments")
                         or [])
    source_records = {str(item.get("source_id")): item
                      for item in literature.get("sources") or []
                      if isinstance(item, dict) and item.get("source_id")}
    glossary = [item for item in state.get("glossary") or []
                if isinstance(item, dict)]
    findings = [item for item in state.get("findings") or []
                if isinstance(item, dict)]
    plan_index = {
        str(item.get("case_id")): item
        for item in case_analysis_plans.get("plans") or [] if item.get("case_id")
    }
    human_by_case = {}
    for entry in state.get("human_evidence") or []:
        human_by_case.setdefault(str(entry.get("case_id")), []).append(entry)
    views = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        view = _finalization.case_review_view(case, state, job_id)
        case_id = str(view.get("case_id") or "")
        segment_index = view.get("segment_index")
        segment_id = str(view.get("segment_id") or "")
        evidence_segment = next((item for item in evidence_segments
                                 if str(item.get("segment_id") or "") == segment_id
                                 or item.get("segment_index") == segment_index), {})
        process = evidence_segment.get("process_evidence") or {}
        related_terms = list(process.get("terminology_decisions") or [])
        if not related_terms:
            haystack = f'{view.get("source_text") or ""}\n{view.get("current_text") or ""}'.casefold()
            related_terms = [item for item in glossary
                             if str(item.get("source") or "").casefold() in haystack]
        case_findings = [item for item in findings
                         if item.get("segment_index") == segment_index]
        for item in process.get("findings") or []:
            if item not in case_findings:
                case_findings.append(item)
        related_claims = []
        for claim in argument_plan.get("claims") or []:
            if (case_id in {str(item) for item in claim.get("core_case_ids") or []}
                    or case_id in {str(item) for item in claim.get("supports_cases") or []}
                    or segment_id in {str(item) for item in claim.get("project_evidence") or []}):
                related_claims.append(claim)
        literature_ids = set()
        for claim in related_claims:
            for key in ("literature_evidence", "literature_claims", "literature_sources"):
                literature_ids.update(str(item) for item in claim.get(key) or [])
        commentary = []
        for label, value in (
                ("针对问题", view.get("targeted_issue")),
                ("选择理由", view.get("selection_rationale")),
                ("差异说明", view.get("contrast_rationale")),
                ("分析理由", (view.get("synthetic_evidence") or {}).get("academic_analysis_reason")),
                ("分析种子", view.get("legacy_analysis_seed")),
                ("限制", "；".join(str(item) for item in view.get("limitations") or [])),
        ):
            if value:
                commentary.append({"label": label, "value": value})
        target_subsection = str(view.get("target_subsection") or "").strip()
        section_title = ""
        for section in outline.get("sections") or []:
            section_id = str(section.get("section_id") or "")
            if section_id == str(view.get("section_id") or "") or (
                    target_subsection and target_subsection.startswith(section_id + ".")):
                section_title = str(section.get("title") or "")
                break
        context = view.get("focus") or {}
        before = str(context.get("context_before") or "").strip()
        after = str(context.get("context_after") or "").strip()
        if not before and isinstance(segment_index, int) and segment_index > 0:
            before = str((state.get("pairs") or [])[segment_index - 1].get("target") or "")
        if not after and isinstance(segment_index, int) and segment_index + 1 < len(state.get("pairs") or []):
            after = str((state.get("pairs") or [])[segment_index + 1].get("target") or "")
        view.update({
            "case_plan": plan_index.get(case_id) or {},
            "human_evidence": human_by_case.get(case_id) or [],
            "related_terms": related_terms[:12],
            "case_findings": case_findings[:12],
            "related_claims": related_claims[:8],
            "literature_evidence": [source_records[item] for item in sorted(literature_ids)
                                     if item in source_records],
            "analytical_commentary": commentary[:8],
            "target_subsection": target_subsection,
            "section_title": section_title,
            "context_before": before,
            "context_after": after,
        })
        views.append(view)
    return views


def _workspace_activity(job_id, state):
    try:
        saved_at = _workspace_saved_label(job_id, state)
    except Exception:
        saved_at = "最近"
    rows = []
    if state.get("p3_done"):
        rows.append((saved_at, "生成实践报告"))
    if state.get("findings") is not None and state.get("p2_done"):
        rows.append((saved_at, "完成审校"))
    if state.get("auto_terms"):
        rows.append((saved_at, "完成术语抽取"))
    if state.get("p2_done"):
        rows.append((saved_at, "完成翻译"))
    elif state.get("p1_done"):
        rows.append((saved_at, "完成文档解析"))
    return rows[:4]


def _runtime_age(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
    except (TypeError, ValueError):
        return None


def _runtime_clock(value):
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone().strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return str(value)[:19]


def _runtime_duration(seconds):
    seconds = max(0, int(seconds or 0))
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}小时{minutes:02d}分"
    if minutes:
        return f"{minutes}分{remainder:02d}秒"
    return f"{remainder}秒"


def _render_runtime_panel(job_id, state):
    view = core.build_job_runtime_view(job_id, state)
    runtime = view["runtime"]
    status = view["status"]
    if status == "idle":
        return
    label = view["status_label"]
    tone = "danger" if status in {"failed", "interrupted"} else \
        "warning" if status in {"stalled", "cancelling", "waiting_manual"} else "neutral"
    headline, detail = view["headline"], view["detail"]
    heartbeat_age = _runtime_age(runtime.get("last_heartbeat_at"))
    tone_class = "is-warning" if tone == "warning" else "is-danger" if tone == "danger" else ""
    completed, total = view["progress_completed"], view["progress_total"]
    progress_html = ""
    if total:
        progress_pct = round(min(1.0, completed / total) * 100)
        progress_html = (
            f'<div class="tp-runtime-progress-head"><span>报告工作流</span>'
            f'<strong>{completed} / {total}</strong></div>'
            f'<div class="tp-runtime-bar" aria-label="报告工作流 {completed} / {total}">'
            f'<i style="width:{progress_pct}%"></i></div>')
    timing_html = ""
    if status in {"running", "waiting_external", "cancelling"}:
        timing_html = (
            f'<div class="tp-runtime-meta"><span>本步骤已运行 '
            f'{_runtime_duration(_runtime_age(runtime.get("operation_started_at")) or 0)}</span>'
            f'<span>最后运行信号 {_runtime_duration(heartbeat_age or 0)}前</span></div>')
    st.markdown(
        '<div class="tp-runtime-panel">'
        f'<div class="tp-runtime-kicker">{escape(view["surface_label"])}</div>'
        f'<div class="tp-runtime-phase {tone_class}"><span class="dot"></span>'
        f'<span>{escape(label)}</span></div>'
        f'<div class="tp-runtime-head"><div><h3>{escape(headline)}</h3>'
        f'<p>{escape(detail)}</p></div></div>'
        f'{timing_html}{progress_html}'
        '</div>', unsafe_allow_html=True)
    recent_events = view["user_events"]
    if recent_events:
        st.caption("最近活动")
        for event in reversed(recent_events):
            st.markdown(
                f'<div class="tp-runtime-event"><time>{escape(_runtime_clock(event.get("timestamp") or event.get("at")))}</time>'
                f'<span>{escape(event.get("message") or "")}</span></div>',
                unsafe_allow_html=True)
    action_col, detail_col = st.columns([1, 1.2], gap="small")
    with action_col:
        if status in {"resume_requested", "queued", "starting"}:
            st.button("正在恢复…", key=f"runtime_resuming_{job_id}",
                      disabled=True, width="stretch")
        elif status in {"running", "waiting_external", "cancelling"} and st.button(
                "取消任务", key=f"runtime_cancel_{job_id}", width="stretch"):
            core.request_job_cancel(job_id)
            st.rerun()
        elif status in {"interrupted", "idle_incomplete", "cancelled"}:
            if st.button("继续处理", type="primary", key=f"runtime_resume_{job_id}",
                         width="stretch"):
                _resume_job(job_id, state)
                st.rerun()
        elif status == "stalled" and core.is_job_worker_alive(job_id):
            if st.button("放弃当前运行", type="primary", key=f"runtime_abandon_{job_id}",
                         width="stretch"):
                core.request_job_cancel(job_id)
                st.rerun()
        elif status in {"failed", "stalled"}:
            if st.button("重试当前步骤", type="primary", key=f"runtime_retry_{job_id}",
                         width="stretch"):
                core.retry_job_step(job_id)
                _resume_job(job_id, core.load_job_state(job_id) or state)
                st.rerun()
    with detail_col:
        with st.expander("运行详情", expanded=False):
            st.caption(f"worker：{'运行中' if core.is_job_worker_alive(job_id) else '未连接'}")
            worker = runtime.get("worker") or {}
            st.caption(f"worker id：{worker.get('worker_id') or '—'} · "
                       f"PID：{worker.get('owner_pid') or '—'}")
            st.caption(f"lease：{worker.get('lease_expires_at') or '—'}")
            st.caption(f"runtime status：{status} · phase：{runtime.get('phase') or '—'}")
            st.caption(f"stage：{runtime.get('stage_id') or runtime.get('stage') or '—'} · "
                       f"operation：{runtime.get('operation_id') or runtime.get('operation') or '—'}")
            st.caption(f"checkpoint：{view['progress_completed']} / "
                       f"{view['progress_total'] or '—'}")
            st.caption(f"最后进展：{_runtime_clock(runtime.get('last_progress_at'))}")
            st.caption(f"最后心跳：{_runtime_clock(runtime.get('last_heartbeat_at'))}")
            if isinstance(runtime.get("error"), dict):
                error = runtime["error"]
                st.caption(f"失败类型：{error.get('type') or '—'} · "
                           f"技术日志：{error.get('technical_log') or '—'}")
            if runtime.get("last_event"):
                st.caption(f"最后事件：{runtime['last_event']}")
            st.caption("技术日志")
            for event in reversed(core.read_runtime_events(
                    job_id, 12, visibility="technical")):
                st.markdown(
                    f'<div class="tp-runtime-event"><time>{escape(_runtime_clock(event.get("timestamp") or event.get("at")))}</time>'
                    f'<span>{escape(event.get("event") or "")} · '
                    f'{escape(event.get("message") or "")}</span></div>',
                    unsafe_allow_html=True)


def _workspace_saved_label(job_id, state):
    if not job_id:
        return "最近"
    value = (core.recovery_summary(job_id, state) or {}).get("last_saved_at")
    if not value:
        return "最近"
    match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})[ T](\d{1,2}):(\d{2})", str(value))
    if match:
        return f"{int(match.group(2))} 月 {int(match.group(3))} 日 {int(match.group(4)):02d}:{match.group(5)}"
    return _format_saved_at(value)[:16]


def _workspace_project_title(filename):
    stem = Path(str(filename or "")).stem.strip()
    candidate = re.split(r"提取自", stem, maxsplit=1)[-1].strip()
    candidate = re.sub(r"^\d+\s*", "", candidate)
    candidate = re.sub(r"\s*\([^)]*\)\s*$", "", candidate).strip()
    candidate = re.sub(r"\s+", " ", candidate)
    if not candidate:
        return stem or "未命名项目"
    words = candidate.split(" ")
    small_words = {"a", "an", "and", "as", "at", "by", "for", "in",
                   "of", "on", "or", "the", "to", "via"}
    if len(words) > 1:
        words = [words[0]] + [word.lower() if word.lower() in small_words else word
                              for word in words[1:]]
    return " ".join(words)


def _workspace_report_stage(job_id, state):
    if not state.get("p3_done"):
        return "处理中"
    report_status = state.get("report_status") or \
        (state.get("academic_state") or {}).get("report_status")
    if report_status == "failed_template_validation":
        return "模板校验失败"
    if report_status in {"incomplete", "review_required"}:
        return "报告不完整"
    quality = (state.get("academic_state") or {}).get("quality_status") \
        or (state.get("academic_state") or {}).get("status")
    if quality in ("fail", "failed", "review_required"):
        return "需要复核"
    snapshot = core.delivery_snapshot_status(job_id, state) if job_id else {"current": False}
    return "已冻结" if snapshot.get("current") else "草稿已生成"


def _render_workspace_topbar(job_id, state):
    filename = str(state.get("filename") or "未命名项目")
    part_match = re.search(r"\bPart\s*([A-Za-z0-9IVX]+)", filename, re.IGNORECASE)
    part_label = f"Part {part_match.group(1)}" if part_match else "当前项目"
    project_title = _workspace_project_title(filename)
    term_count = len(state.get("glossary") or state.get("auto_terms") or [])
    status, tone = _workspace_status(state, job_id)
    try:
        saved_at = _workspace_saved_label(job_id, state)
    except Exception:
        saved_at = "最近"
    status_html = "" if st.session_state.get("workspace_section") == "report" else (
        f'<div class="tp-workspace-status"><span class="tp-status-dot is-{tone}"></span>'
        f'<strong>{escape(status)}</strong></div>')
    with st.container(key="workspace_exit_actions"):
        back_col, home_col, _ = st.columns([1.35, 1.15, 5.5], gap="small")
        with back_col:
            if st.button("返回任务列表", icon=":material/arrow_back:",
                         key=f"workspace_back_{job_id}", width="stretch"):
                st.session_state.update(app_view="history", workspace_mode=False)
                st.rerun()
        with home_col:
            if st.button("回到主页", icon=":material/home:",
                         key=f"workspace_home_{job_id}", width="stretch"):
                st.session_state.update(app_view="new", workspace_mode=False, task_step=1)
                st.rerun()
    st.markdown(
        '<div class="tp-workspace-shell"></div>'
        '<div class="tp-workspace-topbar">'
        '<div><div class="tp-workspace-eyebrow">TransPraxis · Translation Practice Workspace</div>'
        f'<h1>{escape(project_title)}</h1>'
        f'<div class="tp-workspace-meta">{escape(part_label)} · '
        f'{len(state.get("paras") or []):,} 段 · {term_count:,} 个术语 · 最近保存 {escape(saved_at)}</div></div>'
        f'{status_html}</div>', unsafe_allow_html=True)


def _render_workspace_nav(section, state, job_id=""):
    st.markdown('<div class="tp-workspace-nav-title">项目导航</div>'
                '<div class="tp-workspace-nav-caption">从这里进入每个工作阶段。</div>',
                unsafe_allow_html=True)
    contexts, _ = _workspace_findings_counts(state)
    case_views = _workspace_case_views(job_id, state) if job_id else []
    case_pending = sum(1 for item in case_views
                       if item.get("review_status") == "unreviewed"
                       or (item.get("case_origin") == _case_provenance.SYNTHETIC_BASELINE
                           and item.get("baseline_status") == "rejected"))
    compliance = _workspace_compliance_view(job_id, state) if job_id else {}
    qa = _finalization.normalize_final_qa(state.get("final_qa"))
    terms_done = bool(state.get("glossary_frozen") or state.get("quality_bypass")
                      or (state.get("auto_terms") and not state.get("quality_mode")))
    compliance_counts = compliance.get("counts") or {}
    qa_required = bool(state.get("report_enabled"))
    delivery_label, _delivery_tone = _workspace_delivery_state(job_id, state) \
        if job_id else ("未开始", "neutral")
    qa_attention_count = sum(int(compliance_counts.get(key, 0) or 0)
                             for key in ("fail", "manual_review", "not_checked"))
    if qa_required:
        structural = _workspace_structural_qa(job_id, state) if job_id else qa.get("structural_qa")
        qa_attention_count += int(structural != "PASS")
        qa_attention_count += int(qa.get("libreoffice_render") != "PASS")
        qa_attention_count += int(qa.get("author_visual_review") != "CONFIRMED")
        qa_attention_count += int(qa.get("word_final_review") != "CONFIRMED")
    if delivery_label.startswith("已冻结交付"):
        delivery_nav = ("", "done", "当前工作版本与冻结交付一致")
    elif delivery_label.startswith("工作版本已偏离冻结交付"):
        delivery_nav = ("1 项", "attention", delivery_label)
    elif delivery_label == "可以冻结交付":
        delivery_nav = ("", "pending", "所有前置事实已满足，可生成不可变交付")
    else:
        delivery_nav = ("1 项", "attention", "仍有交付门禁未完成")
    nav_meta = {
        "overview": (("", "neutral", "当前任务全貌") if section == "overview" else
                     ("", "neutral", "回到任务概览")),
        "translation": (("", "done", "翻译门禁已通过")
                         if state.get("p2_done") else ("1 项", "pending", "翻译尚未完成")),
        "terms": (("", "done", "术语已冻结") if terms_done else
                  ("1 项", "pending", "术语仍需确认")),
        "review": ((f"{len(contexts)} 项", "attention", f"审校队列还有 {len(contexts)} 项") if contexts else
                   ("", "done", "没有未关闭的审校发现") if state.get("p2_done") else
                   ("", "pending", "翻译完成后开始审校")),
        "cases": ((f"{case_pending} 项", "attention", f"还有 {case_pending} 个案例未完成人工确认") if case_pending else
                  ("", "done", "案例均已完成人工确认") if case_views else
                  ("", "pending", "案例选择产物尚未生成")),
        "report": (("", "done", "报告稿已生成") if state.get("p3_done") else
                   ("1 项", "attention", "报告仍需完成") if state.get("report_enabled") else
                   ("", "neutral", "当前任务未启用实践报告")),
        "qa": ((f"{qa_attention_count} 项", "attention", f"合规与最终 QA 还有 {qa_attention_count} 项需要处理")
               if qa_attention_count else
               ("", "done", "合规与最终 QA 已完成") if qa_required else
               ("", "neutral", "当前任务未启用最终 QA")),
        "delivery": delivery_nav,
    }
    labels = [("overview", "概览"), ("translation", "翻译"),
              ("terms", "术语"), ("review", "审校"), ("cases", "案例"),
              ("report", "报告"), ("qa", "合规与 QA"), ("delivery", "交付")]
    with st.container(key="workspace_nav"):
        for value, label in labels:
            active = value == section
            nav_status, nav_tone, nav_title = nav_meta[value]
            icon = (":material/radio_button_checked:" if active
                    else ":material/check_circle:" if nav_tone == "done"
                    else ":material/error_outline:" if nav_tone == "attention"
                    else ":material/schedule:" if nav_tone == "pending"
                    else ":material/info:")
            with st.container(key=f"workspace_nav_item_{value}"):
                label_col, state_col = st.columns([5, 1.65], gap="small")
                with label_col:
                    if st.button(label, icon=icon, key=f"workspace_nav_{value}", width="stretch",
                                 type="primary" if active else "secondary"):
                        st.session_state.workspace_section = value
                        st.rerun()
                with state_col:
                    state_class = f"is-{nav_tone}" if nav_status else "is-empty"
                    st.markdown(f'<span class="tp-nav-state {state_class}" title="{escape(nav_title)}">'
                                f'{escape(nav_status)}</span>', unsafe_allow_html=True)


def _render_workspace_project_details(state):
    with st.expander("项目详情", expanded=False):
        st.caption(f"源文件：{state.get('filename') or '—'}")
        st.caption(f"段落：{len(state.get('paras') or []):,} · 目标语言：{state.get('target_lang') or '简体中文'}")


def _translation_pair_status(pair):
    return _translation_pair_status_label(pair)


def _translation_pair_status_label(pair):
    if pair.get("human_edited"):
        return "已修改"
    if pair.get("reviewed"):
        return "已审校"
    return "待审"


def _translation_pair_flags(state, pair):
    flags = []
    if pair.get("from_tm"):
        flags.append("M")
    if _translation_terms_for_pair(state, pair):
        flags.append("T")
    return " · ".join(flags) or "—"


def _translation_terms_for_pair(state, pair):
    return core.translation_terms_for_pair(state, pair)


def _translation_preview(value, limit=170):
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _translation_segment_id(job_id, index, pair):
    for key in ("segment_id", "segment_uid", "seg_id"):
        if pair.get(key) is not None:
            return str(pair[key])
    # Reuse the identity already used by exported translation assets.
    return _assets.segment_id(job_id, index)


def _translation_segment_records(job_id, state):
    return [{
        "segment_id": _translation_segment_id(job_id, index, pair),
        "index": index,
        "pair": pair,
    } for index, pair in enumerate(state.get("pairs") or [])]


def _translation_selected_segment(job_id, state, visible_records=None):
    records = _translation_segment_records(job_id, state)
    by_id = {record["segment_id"]: record for record in records}
    selected_id = st.session_state.get("selected_segment_id")
    if selected_id is not None:
        selected_id = str(selected_id)
    if selected_id in by_id and (visible_records is None or
                                selected_id in {item["segment_id"] for item in visible_records}):
        st.session_state["selected_segment_id"] = selected_id
        return by_id[selected_id]
    if selected_id is None and visible_records is None:
        return None
    candidates = visible_records or records
    if not candidates:
        st.session_state["selected_segment_id"] = None
        return None
    selected = candidates[0]
    st.session_state["selected_segment_id"] = selected["segment_id"]
    return selected


def _translation_segment_findings(state, index):
    return [
        _delivery.finding_context(state, finding)
        for finding in _delivery.review_queue_findings(state)
        if finding.get("segment_index") == index
    ]


def _save_translation_edit(job_id, index, text):
    core.save_translation_edit(job_id, index, text)


def _restore_translation_pair(job_id, index):
    core.restore_translation_edit(job_id, index)


def _explain_translation_segment(job_id, index, state):
    if not api_key:
        return "请先配置 API Key。"
    pair = state["pairs"][index]
    terms = _translation_terms_for_pair(state, pair)
    term_text = "；".join(f"{source} → {target}" for source, target, _ in terms) or "无锁定术语"
    system = "你是严谨的翻译实践导师。用简体中文解释当前译法，聚焦语义、术语和上下文，不改写译文。"
    prompt = (f"原文：{pair.get('source', '')}\n当前译文：{pair.get('target', '')}\n"
              f"相关术语：{term_text}\n"
              "请用 2-4 句话说明当前译法的主要决策和可能的注意点。")
    try:
        return core.call_llm(ai_provider, api_key, ai_model, system, prompt, temperature=0.2)
    except Exception as exc:
        return f"解释失败：{str(exc)[:160]}"


def _render_workspace_translation_context(job_id, state):
    selected_segment = _translation_selected_segment(job_id, state)
    if selected_segment is None:
        st.markdown('<div class="tp-empty">翻译开始后，这里会显示选中段落。</div>',
                    unsafe_allow_html=True)
        return
    pairs = state.get("pairs") or []
    index = selected_segment["index"]
    pair = selected_segment["pair"]
    selected_id = selected_segment["segment_id"]
    terms = _translation_terms_for_pair(state, pair)
    findings = _translation_segment_findings(state, index)
    transport_issue = next(
        (issue for issue in (state.get("delivery_validation") or {}).get("issues") or []
         if issue.get("code") == "transport_wrapper"
         and issue.get("segment_index") == index), None)
    status_symbol = _translation_pair_status(pair)
    status_label = _translation_pair_status_label(pair)

    st.markdown(
        f'<div class="tp-translation-inspector-head"><div><h3>当前段落 · #{index + 1}</h3>'
        f'<div class="tp-inspector-status"><span>{status_symbol}</span><strong>{escape(status_label)}</strong></div>'
        f'</div><span class="tp-translation-inspector-position">{index + 1} / {len(pairs)}</span></div>',
        unsafe_allow_html=True)
    if findings:
        issue_label = f"⚠ {len(findings)} 个审校问题"
        st.markdown(f'<div class="tp-inspector-section"><div class="tp-inspector-status">'
                    f'<span>{escape(issue_label)}</span></div></div>', unsafe_allow_html=True)
        if st.button("查看对应审校", key=f"translation_open_review_{job_id}_{selected_id}",
                     width="stretch", type="secondary"):
            st.session_state.workspace_section = "review"
            st.rerun()
    if transport_issue:
        st.markdown(
            '<div class="tp-transport-alert">'
            '<strong>译文结构异常</strong>'
            '<p>检测到 JSON / Markdown transport wrapper。原文仍安全保留；当前译文不能作为普通正文交付。</p>'
            '<span>修复路径：编辑当前译文，或重新翻译当前段；修复后再运行交付检查。</span>'
            '</div>', unsafe_allow_html=True)

    st.markdown('<div class="tp-inspector-section"><h4>原文</h4>'
                f'<p class="tp-inspector-preview">{escape(pair.get("source") or "—")}</p></div>',
                unsafe_allow_html=True)

    edited_key = f"translation_editor_{selected_id}"
    st.markdown('<div class="tp-inspector-section"><h4>当前译文</h4>', unsafe_allow_html=True)
    st.text_area("当前译文", value=pair.get("target") or "", key=edited_key,
                 height=160, label_visibility="collapsed")
    save_col, retranslate_col = st.columns([1.35, 1])
    with save_col:
        if st.button("保存修改", type="primary", key=f"translation_save_{selected_id}",
                     width="stretch"):
            _save_translation_edit(job_id, index, st.session_state.get(edited_key, ""))
            st.session_state.pop(edited_key, None)
            st.rerun()
    with retranslate_col:
        if st.button("重新生成译文", icon=":material/auto_awesome:",
                     key=f"translation_retranslate_{selected_id}",
                     disabled=not api_key, width="stretch"):
            with st.spinner("正在重新翻译当前段落…"):
                core.retranslate_segments(job_id, [index], ai_provider, api_key, ai_model,
                                           target_lang, style_rules=style_rules,
                                           on_caption=lambda text: st.caption(text))
            st.session_state.pop(edited_key, None)
            st.rerun()
    if pair.get("human_edited") and st.button("恢复原译", key=f"translation_restore_{selected_id}",
                                                width="stretch"):
        _restore_translation_pair(job_id, index)
        st.session_state.pop(edited_key, None)
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="tp-inspector-section"><h4>相关术语</h4>', unsafe_allow_html=True)
    if terms:
        for source, target, provenance in terms:
            st.markdown(f'<div class="tp-inspector-term"><span>{escape(source)}<br/>'
                        f'<small>{escape(provenance)}</small></span><b>→ {escape(target)}</b></div>',
                        unsafe_allow_html=True)
    else:
        st.markdown('<div class="tp-inspector-empty">本段无项目术语</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="tp-inspector-section"><h4>翻译记忆</h4>', unsafe_allow_html=True)
    if pair.get("from_tm"):
        st.markdown('<div class="tp-inspector-status"><span>✓</span><strong>已匹配并复用</strong></div>'
                    f'<p class="tp-inspector-preview" style="margin-top:8px">源：{escape(_translation_preview(pair.get("source"), 100))}</p>'
                    f'<p class="tp-inspector-preview">译：{escape(_translation_preview(pair.get("target"), 100))}</p>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<div class="tp-inspector-empty">暂无匹配</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    with st.expander("上下文", expanded=False):
        if index:
            previous = pairs[index - 1].get("source") or "—"
            st.markdown(f'<p class="tp-inspector-preview"><strong>上一段</strong>{escape(_translation_preview(previous, 180))}</p>',
                        unsafe_allow_html=True)
        if index + 1 < len(pairs):
            following = pairs[index + 1].get("source") or "—"
            st.markdown(f'<p class="tp-inspector-preview"><strong>下一段</strong>{escape(_translation_preview(following, 180))}</p>',
                        unsafe_allow_html=True)
        if not index and index + 1 >= len(pairs):
            st.caption("没有相邻段落。")

    with st.expander("当前译法依据", expanded=False):
        explanation_key = f"translation_explanation_{selected_id}"
        if st.session_state.get(explanation_key):
            st.write(st.session_state[explanation_key])
        else:
            st.caption("可让 AI 解释当前译法的语义、术语与上下文决策。")
        if st.button("解释当前译法", key=f"translation_explain_{selected_id}",
                     disabled=not api_key, width="stretch"):
            with st.spinner("正在分析当前译法…"):
                st.session_state[explanation_key] = _explain_translation_segment(job_id, index, state)
            st.rerun()

    with st.expander("翻译设置", expanded=False):
        profile = state.get("document_profile") or {}
        st.caption(f"风格：{profile.get('register') or '正式书面语'}")
        st.caption(f"文档画像：{profile.get('domain') or '未标注领域'} · {profile.get('genre') or '未标注文本类型'}")
        st.caption("源文件：" + str(state.get("filename") or "—"))


def _render_workspace_terms_context(state):
    entries = state.get("glossary") or []
    term_count = len(entries) if isinstance(entries, list) else len(state.get("auto_terms") or {})
    status = "已冻结" if state.get("glossary_frozen") else "已采用建议" if state.get("quality_bypass") else "待确认"
    st.markdown('<div class="tp-info-card"><h3>术语详情</h3>'
                f'<div class="tp-info-stat"><span>当前状态</span><b>{status}</b></div>'
                f'<div class="tp-info-stat"><span>项目术语</span><b>{term_count:,}</b></div>'
                '<p class="tp-tech-detail" style="margin-top:12px">锁定后的术语会注入后续翻译批次。</p>'
                '</div>', unsafe_allow_html=True)
    _render_workspace_project_details(state)


def _review_highlight(text, span):
    text = str(text or "")
    span = str(span or "").strip()
    if not text or not span:
        return escape(text or "—"), False
    start = text.find(span)
    if start < 0:
        return escape(text), False
    end = start + len(span)
    return (escape(text[:start]) + '<mark class="tp-review-span">'
            + escape(text[start:end]) + '</mark>' + escape(text[end:])), True


def _review_confidence_label(value):
    if value is None or value == "":
        return "未提供"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return escape(str(value))


def _render_workspace_review_context(job_id, state):
    contexts, _ = _workspace_findings_counts(state)
    selected_id = str(st.session_state.get("selected_finding_id") or "")
    selected = next((item for item in contexts if item.get("finding_id") == selected_id), None)
    if not selected:
        st.markdown('<div class="tp-empty">当前没有选中的审校发现。</div>',
                    unsafe_allow_html=True)
        return
    raw_selected = next(
        (finding for finding in state.get("findings") or []
         if _delivery.finding_id(finding) == selected_id), {})
    traces = selected.get("review_evidence") or []
    evidence_ids = selected.get("evidence_ids") or []
    stages = list(dict.fromkeys(_review_phase_label(trace.get("phase"))
                                for trace in traces if trace.get("phase")))
    evidence_count = len(evidence_ids)
    evidence_rows = [
        ("检测器", selected.get("detector") or "未提供"),
        ("问题类型", selected.get("category_label") or "未分类"),
        ("严重性", selected.get("severity_label") or "未提供"),
        ("置信度", _review_confidence_label(selected.get("confidence"))),
        ("证据记录", f"{evidence_count} 条" if evidence_count else "未提供"),
    ]
    if stages:
        evidence_rows.append(("QA 阶段", "、".join(stages)))
    if raw_selected.get("created_at"):
        evidence_rows.append(("创建时间", str(raw_selected["created_at"])))
    st.markdown('<h3 class="tp-review-evidence-title">审校依据</h3>',
                unsafe_allow_html=True)
    for label, value in evidence_rows:
        st.markdown(f'<div class="tp-review-evidence-row"><span>{escape(str(label))}</span>'
                    f'<b>{escape(str(value))}</b></div>', unsafe_allow_html=True)
    if selected.get("detected_text"):
        st.markdown('<div class="tp-review-evidence-label">检测到的片段</div>'
                    f'<p class="tp-review-evidence-copy">{escape(selected["detected_text"])}</p>',
                    unsafe_allow_html=True)
    if not evidence_ids and not traces:
        st.markdown('<p class="tp-review-evidence-detail">该 finding 未附带证据记录；置信度也未提供。</p>',
                    unsafe_allow_html=True)
    with st.expander("查看证据详情", expanded=False):
        if selected.get("evidence_refs"):
            st.markdown('<div class="tp-review-evidence-detail">Finding 引用：'
                        f'{escape("、".join(selected["evidence_refs"]))}</div>',
                        unsafe_allow_html=True)
        if evidence_ids:
            st.markdown('<div class="tp-review-evidence-detail">关联证据：'
                        f'{escape("、".join(evidence_ids))}</div>',
                        unsafe_allow_html=True)
        if not traces:
            st.caption("没有可展开的审校证据记录。")
        for trace in traces[-3:]:
            receipt = trace.get("completion_receipt") or {}
            st.markdown(f'**{escape(_review_phase_label(trace.get("phase")))}** · '
                        f'结论 {escape(str(trace.get("decision") or "—"))} · '
                        f'状态 {escape(str(receipt.get("status") or "—"))}')
            if trace.get("requests"):
                st.json(trace["requests"])


def _render_workspace_delivery_context(job_id, state):
    snapshot = core.delivery_snapshot_status(job_id, state)
    latest = snapshot.get("latest") or {}
    approval = latest.get("approval") or {}
    truth = core.translation_truth_view(job_id, state)
    working_label = f'v{truth.get("version", 0)} · 当前'
    frozen_label = (f'v{latest.get("snapshot_version")} · 已冻结交付'
                    if latest else "尚未生成")
    if snapshot.get("diverged"):
        status_label = (f'工作版本已偏离冻结交付 v{latest.get("snapshot_version")}；'
                        "原冻结版本仍可下载")
        status_tone = "warning"
    elif latest:
        status_label = f'已冻结交付 v{latest.get("snapshot_version")}'
        status_tone = "success"
    else:
        status_label = "尚未生成冻结交付"
        status_tone = "warning"
    st.markdown('<div class="tp-version-compare"><h3>版本对比</h3>'
                f'<div class="tp-version-row"><span>工作版本</span><strong>{escape(working_label)}</strong></div>'
                f'<div class="tp-version-row"><span>冻结交付</span><strong>{escape(frozen_label)}</strong></div>'
                f'<div class="tp-version-compare-status is-{status_tone}">{escape(status_label)}</div>'
                f'<div class="tp-version-technical">确认人：{escape(str(approval.get("actor") or "—"))}</div>'
                '</div>', unsafe_allow_html=True)
    if latest:
        st.caption(f"确认时间：{str(approval.get('timestamp') or latest.get('created_at') or '—')[:16]}")
    _render_workspace_project_details(state)


def _render_workspace_context(job_id, state, section):
    if section == "translation":
        with st.container(key="translation_inspector"):
            _render_workspace_translation_context(job_id, state)
    elif section == "terms":
        _render_workspace_terms_context(state)
    elif section == "review":
        _render_workspace_review_context(job_id, state)
    elif section == "cases":
        _render_workspace_cases_context(job_id, state)
    elif section == "qa":
        _render_workspace_qa_context(job_id, state)
    elif section == "delivery":
        _render_workspace_delivery_context(job_id, state)


def _render_workspace_overview(job_id, state):
    contexts, counts = _workspace_findings_counts(state)
    status, tone = _workspace_status(state, job_id)
    blockers = counts["blocking"]
    st.markdown('<h2>概览</h2>'
                '<div class="tp-section-lead">当前任务与项目进度</div>',
                unsafe_allow_html=True)
    _render_runtime_panel(job_id, state)
    impact = core.dependency_impact_view(job_id, state)
    compliance = _workspace_compliance_view(job_id, state)
    compliance_counts = compliance.get("counts") or {}
    if blockers:
        action_text = f"{blockers} 个必须处理问题阻止最终交付。"
    elif impact.get("status") == "stale":
        action_text = "当前译文已通过，但受影响的报告产物仍需重建。"
    elif state.get("report_enabled") and not _delivery.report_ready(state):
        action_text = "报告尚未完成，暂不满足交付条件。"
    elif compliance_counts.get("fail") or compliance_counts.get("manual_review"):
        action_text = "合规检查或人工复核尚未完成，暂不满足交付条件。"
    else:
        action_text = "当前没有交付阻塞，可以准备最终版本。"
    st.markdown('<div class="tp-overview-hero">'
                f'{_workspace_status_badge(status, tone)}'
                f'<strong>{escape(action_text)}</strong>'
                f'<p>已完成翻译 {len(state.get("pairs") or []):,} 段；审校队列还有 {len(contexts):,} 个未关闭发现。</p>'
                '</div>', unsafe_allow_html=True)

    total_segments = len(state.get("paras") or state.get("pairs") or [])
    translated_segments = len(state.get("pairs") or []) if state.get("p2_done") else 0
    reviewed_segments = (state.get("review_stats") or {}).get("reviewed_segments", 0)
    case_count = len((core.load_academic_artifact(job_id, "selected_cases") or {}).get("cases") or [])
    cards = [
        ("翻译", f"{translated_segments:,} / {total_segments:,} 段",
         "完成" if state.get("p2_done") else "处理中", "查看翻译", "translation",
         "is-done" if state.get("p2_done") else "is-active"),
        ("审校", f"{reviewed_segments:,} / {total_segments:,} 段",
         f"{blockers} 阻塞 · {counts['actionable']} 建议", "继续审校", "review",
         "is-done" if not contexts and state.get("p2_done") else "is-active"),
        ("报告", f"{case_count:,} 个案例",
         _workspace_report_stage(job_id, state), "查看报告", "report",
         "is-done" if state.get("p3_done") else "is-active"),
    ]
    card_cols = st.columns(3)
    for col, (title, value, sub, action, destination, tone) in zip(card_cols, cards):
        with col:
            with st.container(key=f"overview_stage_card_{destination}"):
                st.markdown(f'<div class="tp-stage-card-content {tone}"><strong>{escape(title)}</strong>'
                            f'<b>{escape(value)}</b><span>{escape(sub)}</span></div>',
                            unsafe_allow_html=True)
                if st.button(action + " →", key=f"overview_go_{destination}_{job_id}", width="stretch",
                             type="primary" if destination == "review" and blockers else "secondary"):
                    st.session_state.workspace_section = destination
                    st.rerun()

    progress = [
        ("原文处理", bool(state.get("p1_done")), False),
        ("术语提取", bool(state.get("auto_terms")), False),
        ("翻译", bool(state.get("p2_done")), False),
        ("人工审校", bool(state.get("p2_done") and not contexts), bool(contexts)),
        ("报告草稿", bool(state.get("p3_done")), False),
        ("最终交付", _workspace_status(state, job_id)[0].startswith("已冻结交付"), False),
    ]
    progress_rows = []
    for label, done, active in progress:
        icon = "●" if active else "✓" if done else "○"
        row_class = "is-active" if active else "is-done" if done else "is-pending"
        if progress_rows:
            progress_rows.append('<span class="tp-step-connector">→</span>')
        progress_rows.append(f'<span class="tp-progress-step {row_class}"><i>{icon}</i>{label}</span>')
    st.markdown('<div class="tp-section-label">项目进度</div>'
                '<div class="tp-overview-progress">' + "".join(progress_rows) + '</div>',
                unsafe_allow_html=True)
    if not core.build_job_runtime_view(job_id, state).get("user_events"):
        st.markdown('<div class="tp-section-label">最近活动</div><div class="tp-activity">',
                    unsafe_allow_html=True)
        activities = _workspace_activity(job_id, state)
        if activities:
            st.markdown(f'<div class="tp-activity-date">{escape(activities[0][0])}</div>',
                        unsafe_allow_html=True)
            for _, text_value in activities[:3]:
                st.markdown(f'<div class="tp-activity-row">{escape(text_value)}</div>',
                            unsafe_allow_html=True)
        else:
            st.markdown('<div class="tp-activity-row">暂无活动记录</div>',
                        unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    _render_workspace_project_details(state)


def _render_workspace_translation(job_id, state):
    pairs = state.get("pairs") or []
    st.markdown('<h2>翻译</h2>'
                '<div class="tp-section-lead">浏览、检查和编辑双语段落。</div>',
                unsafe_allow_html=True)
    truth = core.translation_truth_view(job_id, state)
    last_change = truth.get("last_change") or {}
    changed_indexes = last_change.get("segment_indexes") or []
    raw_change_reason = str(last_change.get("reason") or "")
    change_reason = ("当前译文已更新，相关下游需要重新检查"
                     if "CURRENT_TRANSLATION" in raw_change_reason
                     else raw_change_reason or "工作版本已更新")
    change_note = (f"最近变更：第 {', '.join(str(int(x) + 1) for x in changed_indexes)} 段 · "
                   f"{change_reason}"
                   if changed_indexes else "尚未记录工作版本变更")
    st.markdown(
        '<div class="tp-truth-banner">'
        '<div><span class="tp-truth-kicker">交付与审校依据</span>'
        '<strong>当前译文 — 交付和审校的唯一来源</strong>'
        f'<p>版本 v{truth["version"]} · {truth["segment_count"]:,} 段。报告、案例、附录和交付文件都只能读取这里的当前译文。</p>'
        f'<small>{escape(change_note)}</small></div>'
        '</div>', unsafe_allow_html=True)
    reviewed = (state.get("review_stats") or {}).get("reviewed_segments", 0)
    total = len(pairs)
    st.caption(f"{total:,} 段 · {reviewed:,} 已审校 · {max(0, total - reviewed):,} 待审 · TM 复用 {state.get('tm_used_count', 0):,}")
    if not pairs:
        st.markdown('<div class="tp-empty">翻译尚未开始。</div>', unsafe_allow_html=True)
        return
    toolbar_search, toolbar_primary, toolbar_filter, toolbar_more = st.columns(
        [3.35, 2.35, 0.9, 0.9], gap="small")
    with toolbar_search:
        search = st.text_input("搜索段落", key=f"translation_search_{job_id}",
                               placeholder="搜索原文或译文，或输入段落号…",
                               label_visibility="collapsed")
    with toolbar_primary:
        filter_label = st.segmented_control(
            "一级筛选", ["全部", "待审", "已审校"], default="全部",
            key=f"translation_filter_{job_id}", label_visibility="collapsed",
            width="stretch") or "全部"
    with toolbar_filter:
        with st.popover("筛选 ▾", use_container_width=True):
            filter_terms = st.checkbox("含项目术语", key=f"translation_filter_terms_{job_id}")
            filter_edited = st.checkbox("已修改", key=f"translation_filter_edited_{job_id}")
            issue_only = st.checkbox("有审校问题", key=f"translation_filter_issue_{job_id}")
            filter_tm = st.checkbox("使用翻译记忆", key=f"translation_filter_tm_{job_id}")
    with toolbar_more:
        with st.popover("更多", use_container_width=True):
            mode = st.radio("显示模式", ["列表模式", "聚焦模式"],
                            key=f"translation_mode_{job_id}")

    issue_indexes = {item.get("segment_index") for item in _workspace_review_contexts(state)
                     if item.get("segment_index") is not None}
    visible_indexes = core.translation_visible_indexes(
        state, search=search, status_filter=filter_label,
        filter_terms=filter_terms, filter_edited=filter_edited,
        filter_issues=issue_only, filter_tm=filter_tm,
        issue_indexes=issue_indexes)
    records = _translation_segment_records(job_id, state)
    visible_records = [records[index] for index in visible_indexes]
    if not visible_indexes:
        st.session_state["selected_segment_id"] = None
        st.markdown('<div class="tp-empty">没有符合当前筛选条件的段落。</div>', unsafe_allow_html=True)
        return

    selected_segment = _translation_selected_segment(job_id, state, visible_records)
    selected_index = selected_segment["index"]
    if mode == "聚焦模式":
        pair = selected_segment["pair"]
        st.markdown(f'<div class="tp-focus-head"><span>第 {selected_index + 1} 段</span>'
                    f'<span>{escape(_translation_pair_status_label(pair))} · {selected_index + 1} / {total}</span></div>',
                    unsafe_allow_html=True)
        source_col, target_col = st.columns(2)
        with source_col:
            st.markdown(f'<div class="tp-focus-text"><label>原文</label><p>{escape(pair.get("source") or "—")}</p></div>',
                        unsafe_allow_html=True)
        with target_col:
            st.markdown(f'<div class="tp-focus-text"><label>当前译文</label><p>{escape(pair.get("target") or "—")}</p></div>',
                        unsafe_allow_html=True)
        prev_col, next_col = st.columns(2)
        if prev_col.button("← 上一段", key=f"translation_focus_prev_{job_id}", disabled=selected_index == visible_indexes[0], width="stretch"):
            current = visible_indexes.index(selected_index)
            next_index = visible_indexes[max(0, current - 1)]
            st.session_state["selected_segment_id"] = records[next_index]["segment_id"]
            st.rerun()
        if next_col.button("下一段 →", key=f"translation_focus_next_{job_id}", disabled=selected_index == visible_indexes[-1], width="stretch"):
            current = visible_indexes.index(selected_index)
            next_index = visible_indexes[min(len(visible_indexes) - 1, current + 1)]
            st.session_state["selected_segment_id"] = records[next_index]["segment_id"]
            st.rerun()
        return

    rows = [{
        "状态": _translation_pair_status(pair),
        "#": f"#{index + 1}",
        "原文": _translation_preview(pair.get("source")),
        "当前译文": _translation_preview(pair.get("target")),
    } for index in visible_indexes for pair in [pairs[index]]]
    st.markdown('<div class="tp-translation-table-note">点击一行，在右侧 Inspector 中查看完整段落并编辑译文。</div>',
                unsafe_allow_html=True)
    table_revision = abs(hash((search, filter_label, filter_terms,
                               filter_edited, issue_only, filter_tm,
                               tuple(visible_indexes))))
    table_key = f"translation_table_{job_id}_{table_revision}"
    event = st.dataframe(
        pd.DataFrame(rows), hide_index=True, width="stretch", height=610,
        row_height=58,
        on_select="rerun", selection_mode="single-row",
        key=table_key,
        column_config={
            "状态": st.column_config.TextColumn("状态", width="small",
                                                   help="已修改=人工改过；已审校=人工检查完成；待审=尚未确认"),
            "#": st.column_config.TextColumn("#", width="small"),
            "原文": st.column_config.TextColumn("原文", width="large"),
            "当前译文": st.column_config.TextColumn("当前译文", width="large"),
        })
    selection = getattr(event, "selection", None)
    selected_rows = list(getattr(selection, "rows", []) or [])
    if selected_rows:
        row_index = selected_rows[0]
        if 0 <= row_index < len(visible_records):
            st.session_state["selected_segment_id"] = visible_records[row_index]["segment_id"]


def _render_workspace_terms(job_id, state):
    entries = state.get("glossary") or []
    if not isinstance(entries, list):
        entries = []
    if not entries and isinstance(state.get("auto_terms"), dict):
        entries = [{"id": f"auto-{i}", "source": source,
                    "target": value if isinstance(value, str) else "",
                    "preferred": value if isinstance(value, str) else "",
                    "status": "provisional"}
                   for i, (source, value) in enumerate(state["auto_terms"].items())]
    st.markdown('<div class="tp-section-kicker">语言资产</div><h2>术语</h2>'
                '<div class="tp-section-lead">术语是项目记忆的一部分；锁定后会随翻译批次注入。</div>',
                unsafe_allow_html=True)
    frozen = state.get("glossary_frozen")
    bypassed = state.get("quality_bypass")
    if frozen:
        st.success(f"术语已冻结 · v{frozen.get('version')}")
    elif bypassed:
        st.info("本任务跳过了人工冻结，当前使用 provisional 术语。")
    elif not state.get("p2_done") and state.get("quality_mode"):
        st.warning("术语尚未冻结；完成审核后才能继续翻译。")
        _render_profile_editor(job_id, state)
    if not entries:
        st.markdown('<div class="tp-empty">暂无项目术语。</div>', unsafe_allow_html=True)
        return
    if not state.get("p2_done") and state.get("quality_mode") and state.get("glossary") is not None:
        df = _glossary_dataframe(entries, state.get("paras") or [])
        visible = ["选择", "source", "proposed_target", "preferred", "status", "domain", "note", "id", "payload"]
        edited = st.data_editor(
            df[[key for key in visible if key in df.columns]],
            key=f"workspace_glossary_editor_{job_id}", num_rows="dynamic",
            hide_index=True, width="stretch",
            column_config={
                "选择": st.column_config.CheckboxColumn("选择"),
                "id": st.column_config.TextColumn("ID", disabled=True),
                "source": st.column_config.TextColumn("源术语", required=True),
                "proposed_target": st.column_config.TextColumn("建议译名"),
                "preferred": st.column_config.TextColumn("首选译名"),
                "status": st.column_config.SelectboxColumn(
                    "状态", options=["candidate", "provisional", "locked", "rejected"]),
                "domain": st.column_config.TextColumn("领域"),
                "note": st.column_config.TextColumn("备注"),
                "payload": st.column_config.TextColumn("payload", disabled=True),
            })
        chosen = edited[edited["选择"].fillna(False)] if "选择" in edited.columns else edited.iloc[0:0]
        ids = [str(item) for item in chosen.get("id", []).tolist() if str(item)]
        a, b, c = st.columns(3)
        if a.button("保存草稿", key=f"workspace_terms_save_{job_id}", width="stretch"):
            core.save_glossary_draft(job_id, _merge_edited_entries(entries, _df_to_entries(edited)))
            st.rerun()
        if b.button("锁定选中", key=f"workspace_terms_lock_{job_id}", disabled=not ids, width="stretch"):
            core.set_glossary_entry_status(job_id, ids, "locked")
            st.rerun()
        if c.button("冻结并继续翻译", type="primary", key=f"workspace_terms_freeze_{job_id}", width="stretch"):
            core.freeze_glossary(job_id, entries=_merge_edited_entries(entries, _df_to_entries(edited)), frozen_by="用户")
            st.session_state.pending_continue_job = job_id
            st.rerun()
    else:
        rows = [{"源术语": e.get("source", ""), "首选译名": e.get("preferred") or e.get("target", ""),
                 "状态": e.get("status", "provisional"), "出现次数": len(e.get("occurrences") or [])}
                for e in entries]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=430)


def _render_workspace_review(job_id, state):
    contexts, counts = _workspace_findings_counts(state)
    st.markdown('<div class="tp-review-head"><div><div class="tp-section-kicker">人工工作区</div>'
                '<h2>审校</h2></div>'
                f'<div class="tp-review-count">{len(contexts):,} 个待审发现</div></div>',
                unsafe_allow_html=True)
    if not contexts:
        st.session_state["selected_finding_id"] = None
        st.markdown('<div class="tp-empty">所有审校发现都已处理，可以继续准备交付。</div>',
                    unsafe_allow_html=True)
        return
    filter_options = [
        f"必须处理 {counts['blocking']}",
        f"建议 {counts['actionable']}",
        f"参考 {counts['informational']}",
        f"全部 {len(contexts)}",
    ]
    filter_key = f"workspace_review_filter_chips_{job_id}"
    filter_default = filter_options[0] if counts["blocking"] else filter_options[-1]
    if st.session_state.get(filter_key) not in filter_options:
        st.session_state[filter_key] = filter_default
    filter_value = st.segmented_control(
        "筛选审校发现", filter_options,
        default=None if filter_key in st.session_state else filter_default,
        key=filter_key,
        label_visibility="collapsed", width="stretch") or filter_options[-1]
    filter_label = filter_value.rsplit(" ", 1)[0]
    severity = {"必须处理": "blocking", "建议": "actionable",
                "参考": "informational"}.get(filter_label)
    visible = [item for item in contexts if severity is None or item.get("severity") == severity]
    if not visible:
        st.session_state["selected_finding_id"] = None
        st.info("当前筛选下没有待处理发现。")
        return
    by_id = {item["finding_id"]: item for item in visible}
    selected_id = str(st.session_state.get("selected_finding_id") or "")
    if selected_id not in by_id:
        selected_id = visible[0]["finding_id"]
        st.session_state["selected_finding_id"] = selected_id
    queue_col, editor_col = st.columns([1.05, 2.35], gap="medium")
    with queue_col:
        st.markdown(f'<h3>审校队列 <span class="tp-review-queue-count">{len(contexts)}</span></h3>',
                    unsafe_allow_html=True)
        st.caption(f'必须处理 {counts["blocking"]} · 建议 {counts["actionable"]} · 参考 {counts["informational"]}')
        queue_labels = []
        queue_label_to_id = {}
        for item in visible:
            base_label = (f'第 {item["segment_number"]} 段 · {item["severity_label"]}\n'
                          f'{(item.get("summary") or item.get("reason") or "未提供问题摘要")[:56]}')
            label = base_label
            suffix = 1
            while label in queue_label_to_id:
                suffix += 1
                label = f'{base_label} · 另一个发现 {suffix}'
            queue_labels.append(label)
            queue_label_to_id[label] = item["finding_id"]
        queue_key = f"workspace_review_queue_{job_id}"
        if st.session_state.get(queue_key) not in queue_label_to_id:
            st.session_state[queue_key] = next(
                label for label, finding_id in queue_label_to_id.items()
                if finding_id == selected_id
            )
        selected_label = st.radio(
            "审校队列", queue_labels, key=queue_key,
            label_visibility="collapsed")
        selected_id = queue_label_to_id[selected_label]
        st.session_state["selected_finding_id"] = selected_id
    selected = by_id[selected_id]
    raw_selected = next(
        (finding for finding in state.get("findings") or []
         if _delivery.finding_id(finding) == selected_id),
        {},
    )
    suggested_target = str(raw_selected.get("suggested_target") or "").strip()
    with editor_col:
        st.markdown(f'<div class="tp-segment-label">第 {selected["segment_number"]} 段 · '
                    f'{escape(selected["severity_label"])} · '
                    f'{escape(selected.get("category_label") or "未分类")}</div>',
                    unsafe_allow_html=True)
        summary = selected.get("summary") or selected.get("reason") or "未提供问题摘要"
        st.markdown('<div class="tp-review-diagnostic-label">问题摘要</div>'
                    f'<div class="tp-review-diagnostic-copy tp-review-summary">{escape(summary)}</div>',
                    unsafe_allow_html=True)
        if selected.get("legacy_diagnostic"):
            st.markdown('<div class="tp-review-legacy">该审校记录来自旧版本，仅包含基础问题信息。'
                        '未保存可验证的完整诊断字段。</div>', unsafe_allow_html=True)
        st.markdown('<div class="tp-review-diagnostic-label">问题位置</div>',
                    unsafe_allow_html=True)
        source_markup, source_found = _review_highlight(
            selected.get("source"), selected.get("source_span"))
        target_markup, target_found = _review_highlight(
            selected.get("target"), selected.get("target_span"))
        st.markdown('<div class="tp-review-section-label">原文</div>'
                    f'<div class="tp-review-long-text">{source_markup}</div>',
                    unsafe_allow_html=True)
        if selected.get("source_span") and not source_found:
            st.markdown('<p class="tp-review-location-note">记录的原文片段无法在当前段落中可靠定位，未进行高亮。</p>',
                        unsafe_allow_html=True)
        elif not selected.get("source_span"):
            st.markdown('<p class="tp-review-location-note">触发原文片段：未提供。</p>',
                        unsafe_allow_html=True)
        st.markdown('<div class="tp-review-section-label">当前译文</div>'
                    f'<div class="tp-review-long-text">{target_markup}</div>',
                    unsafe_allow_html=True)
        if selected.get("target_span") and not target_found:
            st.markdown('<p class="tp-review-location-note">记录的译文片段无法在当前译文中可靠定位，未进行高亮。</p>',
                        unsafe_allow_html=True)
        elif not selected.get("target_span"):
            st.markdown('<p class="tp-review-location-note">触发译文片段：未提供。</p>',
                        unsafe_allow_html=True)
        st.markdown('<div class="tp-review-diagnostic-label">判断依据</div>'
                    f'<p class="tp-review-diagnostic-copy">{escape(selected.get("explanation") or "该旧记录未保存判断依据，请结合原文、译文和右侧证据人工核对。")}</p>',
                    unsafe_allow_html=True)
        st.markdown('<div class="tp-review-diagnostic-label">建议处理</div>'
                    f'<p class="tp-review-diagnostic-copy">{escape(selected.get("recommendation") or "请结合原文、译文和右侧证据人工核对后决定是否修改。")}</p>',
                    unsafe_allow_html=True)
        if suggested_target:
            st.markdown(f'<div class="tp-review-location-note">系统建议译文：{escape(suggested_target)}</div>', unsafe_allow_html=True)
        note_key = f"workspace_review_note_{selected_id}"
        with st.expander("处理说明（可选）", expanded=False):
            st.text_input("说明", key=note_key, label_visibility="collapsed",
                          placeholder="添加说明…")
        note = st.session_state.get(note_key, "")
        action_a, action_b, action_c = st.columns(3)
        if action_a.button("接受建议" if suggested_target else "标记已处理",
                          type="primary", key=f"workspace_review_fix_{selected_id}", width="stretch"):
            if suggested_target and selected.get("segment_index") is not None:
                latest = core.load_job_state(job_id) or state
                index = selected["segment_index"]
                pairs = latest.get("pairs") or []
                if 0 <= index < len(pairs):
                    # An accepted repair is still a mutation of the one
                    # authoritative CURRENT_TRANSLATION.  Route it through
                    # the same business entry as a manual edit so stale
                    # scope, TM trust and final approval are handled together.
                    core.save_translation_edit(
                        job_id, index, suggested_target, actor="reviewer")
            core.mark_findings_resolved(job_id, [selected_id], "human_fixed",
                                        note or ("接受审校建议" if suggested_target else "人工核对后确认已处理"))
            st.rerun()
        can_retranslate = bool(api_key and selected.get("segment_index") is not None)
        if action_b.button("重新翻译", disabled=not can_retranslate, key=f"workspace_review_retranslate_{selected_id}", width="stretch"):
            core.retranslate_segments(job_id, [selected["segment_index"]], ai_provider, api_key, ai_model,
                                       target_lang, style_rules=style_rules,
                                       on_caption=lambda text: st.caption(text))
            st.rerun()
        if action_c.button("保留当前译文", disabled=not selected.get("proper_noun_candidate"),
                          key=f"workspace_review_preserve_{selected_id}", width="stretch"):
            core.mark_findings_resolved(job_id, [selected_id], "preserved", note or "人工确认保留当前译文")
            st.rerun()
        if not can_retranslate:
            st.caption("重新翻译需要已配置 API Key。")


def _case_origin_label(case):
    return _case_provenance.display_contract(case).get("origin_label") or "未分类案例"


def _case_review_status_label(status):
    value = str(status or "")
    return {"unreviewed": "待人工确认", "approved": "已批准纳入", "rejected": "已排除"}.get(
        value, "需人工确认" if value else "待人工确认")


def _case_state_label(value):
    return {
        "pass": "已通过", "fail": "未通过", "manual_review": "待人工复核",
        "not_checked": "未检查", "not_applicable": "不适用",
        "not_available": "尚未生成", "unreviewed": "未处理",
        "approved": "已确认", "rejected": "已拒绝", "modified": "已修改",
        "other": "其他",
    }.get(str(value or ""), "需确认" if value else "—")


def _case_identity_label(case):
    raw = str(case.get("case_id") or "")
    if raw.startswith("seg-"):
        index = case.get("segment_index")
        return f"第 {int(index) + 1} 段" if isinstance(index, int) else "真实修订案例"
    if raw.startswith(("LSC-", "SC-")):
        index = case.get("segment_index")
        return f"第 {int(index) + 1} 段" if isinstance(index, int) else "案例"
    return "案例" if raw else "未命名案例"


def _case_review_is_stale(case, state):
    case_id = str(case.get("case_id") or "")
    if bool(case.get("content_stale")):
        return True
    academic = state.get("academic_state") or {}
    artifact = (academic.get("artifacts") or {}).get(f"case:{case_id}") or {}
    if artifact.get("status") == "stale":
        return True
    impact = state.get("dependency_impact") or {}
    if case_id in {str(value) for value in impact.get("affected_case_ids") or []}:
        return True
    return False


def _case_validity_label(case, state):
    if _case_review_is_stale(case, state):
        return "需要重新检查", "stale"
    if case.get("review_status") == "rejected" or case.get("baseline_status") == "rejected":
        return "已排除", "stale"
    if case.get("review_status") == "unreviewed":
        return "待人工确认", "pending"
    return "可复用", "valid"


def _render_workspace_cases(job_id, state):
    selected = core.load_academic_artifact(job_id, "selected_cases") or {}
    views = _workspace_case_views(job_id, state)
    st.markdown('<div class="tp-section-kicker">案例与人工确认</div><h2>案例终审</h2>'
                '<div class="tp-section-lead">逐例确认案例是否可纳入学术分析；批准不会把合成对照变成历史初译。</div>',
                unsafe_allow_html=True)
    truth = core.translation_truth_view(job_id, state)
    st.markdown(
        '<div class="tp-truth-banner">'
        '<div><span class="tp-truth-kicker">案例引用依据</span>'
        '<strong>当前译文 — 案例引用的交付真值</strong>'
        f'<p>所有案例的“当前译文”都来自工作译文 v{truth["version"]}；案例只保存来源与分析用途，不另造终稿。</p>'
        '</div></div>', unsafe_allow_html=True)
    if not views:
        st.markdown('<div class="tp-empty">尚未生成案例选择产物。</div>', unsafe_allow_html=True)
        return
    filter_origin, filter_status, filter_search = st.columns([1, 1, 1.6], gap="small")
    with filter_origin:
        origin_filter = st.selectbox(
            "案例来源", ["全部", "真实修订", "合成对照", "翻译决策"],
            key=f"case_origin_filter_{job_id}", label_visibility="collapsed")
    with filter_status:
        status_filter = st.selectbox(
            "审校状态", ["全部", "待人工确认", "已批准纳入", "已排除"],
            key=f"case_status_filter_{job_id}", label_visibility="collapsed")
    with filter_search:
        case_search = st.text_input(
            "搜索案例", key=f"case_search_{job_id}",
            placeholder="搜索段落、原文或译文…", label_visibility="collapsed")
    needle = str(case_search or "").strip().casefold()
    filtered = [item for item in views
                if (origin_filter == "全部" or _case_origin_label(item) == origin_filter)
                and (status_filter == "全部" or
                     _case_review_status_label(item.get("review_status")) == status_filter)
                and (not needle or needle in " ".join(
                    str(value or "") for value in (
                        _case_identity_label(item), _case_origin_label(item),
                        _case_review_status_label(item.get("review_status")),
                        item.get("source_text"), item.get("current_text"),
                        item.get("target_subsection"), item.get("section_title"),
                    )).casefold())]
    if not filtered:
        st.info("当前筛选下没有案例。")
        return
    ids = [str(item.get("case_id")) for item in filtered]
    selected_id = str(st.session_state.get(f"selected_case_id_{job_id}") or "")
    if selected_id not in ids:
        selected_id = ids[0]
        st.session_state[f"selected_case_id_{job_id}"] = selected_id
    queue_col, detail_col = st.columns([1.35, 2.3], gap="medium")
    with queue_col:
        st.markdown(f'<h3>案例队列 <span class="tp-review-queue-count">{len(filtered)}</span></h3>',
                    unsafe_allow_html=True)
        labels = []
        label_ids = {}
        for index, item in enumerate(filtered, start=1):
            label = (f'{_case_identity_label(item)} · {_case_origin_label(item)} · '
                     f'{_case_review_status_label(item.get("review_status"))}')
            if label in label_ids:
                label = f'{label} · 第 {index} 项'
            labels.append(label)
            label_ids[label] = str(item.get("case_id"))
        queue_key = f"case_queue_{job_id}"
        current_label = next(label for label in labels if label_ids[label] == selected_id)
        if st.session_state.get(queue_key) not in labels:
            st.session_state[queue_key] = current_label
        chosen_label = st.selectbox(
            "案例队列", labels, key=queue_key, label_visibility="collapsed",
            help="选择一个案例查看证据并记录人工终审。")
        selected_id = label_ids[chosen_label]
        st.session_state[f"selected_case_id_{job_id}"] = selected_id
        approved = sum(item.get("review_status") == "approved" for item in views)
        excluded = sum(item.get("review_status") == "rejected" for item in views)
        st.caption(f"显示 {len(filtered)} / 总计 {len(views)} · 总计状态：已批准 {approved} · 已排除 {excluded} · 待人工确认 {len(views) - approved - excluded}")
    item = next(item for item in filtered if str(item.get("case_id")) == selected_id)
    display = _case_provenance.display_contract(item)
    lifecycle = item.get("artifact_status") or "not_available"
    with detail_col:
        validity_label, tone = _case_validity_label(item, state)
        stale = tone == "stale"
        status = _case_review_status_label(item.get("review_status"))
        st.markdown(
            f'<div class="tp-case-head"><div><div class="tp-section-kicker">当前选中 · {escape(_case_identity_label(item))}</div>'
            f'<h3>{escape(display["origin_label"])} · {escape(status)}</h3>'
            f'<p>{escape(display["origin_description"])}</p></div>'
            f'<span class="tp-case-validity is-{tone}">{validity_label}</span></div>',
            unsafe_allow_html=True)
        has_initial = bool(item.get("initial_text"))
        initial_role_label = (
            "模拟初译" if item.get("case_origin") == _case_provenance.SYNTHETIC_BASELINE
            else "历史初译" if has_initial else "无真实初译（不伪造对照）")
        role_rows = ['<span>原文</span><b>原文段落</b>']
        if item.get("case_origin") == _case_provenance.SYNTHETIC_BASELINE or has_initial:
            role_rows.append(
                f'<span>{escape(initial_role_label)}</span><b>{escape(initial_role_label)}</b>')
        role_rows.append('<span>当前译文</span><b>当前译文</b>')
        st.markdown('<div class="tp-case-role-grid">' + "".join(role_rows) + '</div>',
                    unsafe_allow_html=True)
        text_col_a, text_col_b = st.columns(2)
        with text_col_a:
            st.markdown(f'<div class="tp-case-text"><label>原文</label><p>{escape(item.get("source_text") or "—")}</p></div>', unsafe_allow_html=True)
            if item.get("initial_text"):
                st.markdown(f'<div class="tp-case-text"><label>{escape(display.get("initial_label") or "初始文本")}</label><p>{escape(item.get("initial_text"))}</p></div>', unsafe_allow_html=True)
        with text_col_b:
            st.markdown(f'<div class="tp-case-text"><label>当前译文</label><p>{escape(item.get("current_text") or "—")}</p></div>', unsafe_allow_html=True)
            context = " ".join(str(item.get(key) or "") for key in ("context_before", "context_after")).strip()
            if context:
                st.markdown(f'<div class="tp-case-text"><label>必要上下文</label><p>{escape(context)}</p></div>', unsafe_allow_html=True)
        st.markdown('<div class="tp-case-detail-label">分析与证据</div>', unsafe_allow_html=True)
        evidence = item.get("synthetic_evidence") or {}
        analysis = item.get("analysis_fields") or {}
        evidence_rows = [
            ("基线合理性", _case_state_label(evidence.get("baseline_plausibility"))),
            ("实质差异", _case_state_label(evidence.get("material_difference"))),
            ("修复正确性", _case_state_label(evidence.get("repair_correctness"))),
            ("分析价值", _case_state_label(evidence.get("academic_analysis_value"))),
            ("基线状态", ({"modified": "已修改", "rejected": "已拒绝",
                           "approved": "已确认", "unreviewed": "未处理"}.get(
                               item.get("baseline_status"), "不适用")
                       if item.get("case_origin") == _case_provenance.SYNTHETIC_BASELINE
                       else "不适用")),
            ("分析状态", "已保存" if analysis else "未提供"),
        ]
        case_plan = item.get("case_plan") or {}
        if case_plan:
            evidence_rows.extend([
                ("问题类型", _case_state_label((case_plan.get("problem") or {}).get("type"))),
                ("决策理由", "已保存" if case_plan.get("decision_rationale") else "未提供"),
                ("理论映射", "已保存" if case_plan.get("theory_mapping") else "未提供"),
            ])
        st.markdown('<div class="tp-case-evidence-grid">' + "".join(
            f'<span>{escape(label)}</span><b>{escape(str(value))}</b>'
            for label, value in evidence_rows) + '</div>', unsafe_allow_html=True)
        segment_index = item.get("segment_index")
        finding_count = len(item.get("case_findings") or [])
        target_section = item.get("target_subsection") or item.get("section_id") or "—"
        section_suffix = f' · {item.get("section_title")}' if item.get("section_title") else ""
        st.caption(f'关联位置：第 {int(segment_index) + 1 if isinstance(segment_index, int) else "—"} 段 · '
                   f'目标报告位置 {target_section}{section_suffix} · 相关审校发现 {finding_count} 条')
        if item.get("segment_current_text") and item.get("current_text") != item.get("segment_current_text"):
            st.caption("当前译文已按案例片段定位；完整段落真值仍以翻译工作区中的当前译文为准。")
        with st.expander("查看依赖与技术依据", expanded=False):
            st.caption(f'依赖状态：{"需要重建" if stale else "可复用"} · '
                       f'内部生命周期：{lifecycle} · 技术标识：{item.get("segment_id") or "—"}')
        with st.expander("查看关联证据", expanded=True):
            commentary = item.get("analytical_commentary") or []
            if commentary:
                st.markdown("**分析评论**")
                for entry in commentary:
                    st.markdown(f'**{escape(str(entry.get("label") or "说明"))}**：{escape(str(entry.get("value") or "—"))}')
            else:
                st.caption("尚未保存可展示的案例分析评论。")
            terms = item.get("related_terms") or []
            if terms:
                st.markdown("**相关术语**")
                for term in terms:
                    source = term.get("source") or term.get("term") or "—"
                    target = term.get("target") or term.get("preferred") or term.get("proposed_target") or "—"
                    st.markdown(f'- {escape(str(source))} → {escape(str(target))}')
            else:
                st.caption("未登记与本案例直接绑定的术语记录。")
            if item.get("case_findings"):
                st.markdown("**相关审校发现**")
                for finding in item.get("case_findings") or []:
                    severity = {"blocking": "必须处理", "actionable": "建议",
                                "informational": "参考"}.get(
                                    str(finding.get("severity") or ""), "审校发现")
                    st.markdown(f'- {escape(severity)} · {escape(str(finding.get("reason") or "审校发现"))}')
            else:
                st.caption("当前段落没有已登记的 finding。")
            if item.get("literature_evidence"):
                st.markdown("**文献证据**")
                for source in item.get("literature_evidence") or []:
                    st.markdown(f'- {escape(str(source.get("title") or source.get("source_id") or "—"))}')
            else:
                st.caption("未登记案例专属文献证据；当前分析边界仍以项目证据为准。")
            human_entries = item.get("human_evidence") or []
            if human_entries:
                st.markdown("**作者补充证据**")
                for entry in human_entries:
                    st.markdown(f'- {escape(str(entry.get("question_type") or "说明"))}: '
                                f'{escape(str(entry.get("answer") or "—"))}')
            else:
                st.caption("没有已确认的作者事后解释。")
        if item.get("review_note"):
            st.caption(f'审核说明：{item["review_note"]}')
        if item.get("reviewed_at"):
            st.caption(f'审核记录：{item.get("reviewed_at")} · {item.get("review_actor") or "user"}')
        if stale:
            st.warning("当前译文或输入已变化，此案例需要重新检查；旧批准不能直接交付。")
        action_a, action_b, action_c, action_d = st.columns(4)
        if action_a.button("批准纳入" if item.get("review_status") != "approved" else "保持批准",
                          type="primary", key=f"case_approve_{job_id}_{selected_id}",
                          disabled=item.get("review_status") == "approved" and not stale,
                          width="stretch"):
            core.review_academic_case(job_id, selected_id, "approved", actor="user")
            st.rerun()
        exclude_key = f"case_exclude_note_{job_id}_{selected_id}"
        with action_b:
            with st.popover("排除案例", use_container_width=True):
                note = st.text_area("排除原因", key=exclude_key, height=90,
                                    placeholder="说明为什么不纳入本次分析…")
                if st.button("确认排除", key=f"case_exclude_go_{job_id}_{selected_id}",
                             type="primary", width="stretch"):
                    if not note.strip():
                        st.warning("请填写排除原因。")
                    else:
                        core.review_academic_case(job_id, selected_id, "rejected", note, actor="user")
                        st.rerun()
        with action_c:
            if st.button("修改当前译文", key=f"case_edit_target_{job_id}_{selected_id}", width="stretch"):
                if segment_index is not None:
                    pair = (state.get("pairs") or [])[int(segment_index)]
                    st.session_state["selected_segment_id"] = _translation_segment_id(
                        job_id, int(segment_index), pair)
                st.session_state.workspace_section = "translation"
                st.rerun()
        with action_d:
            if st.button("从合格池替换", key=f"case_replace_{job_id}_{selected_id}",
                         disabled=item.get("review_status") != "rejected", width="stretch"):
                _state, ok, result = core.replace_rejected_case(
                    job_id, selected_id, actor="user")
                if not ok:
                    st.error(result[0] if isinstance(result, list) and result else str(result))
                else:
                    st.rerun()
        if item.get("case_origin") == _case_provenance.SYNTHETIC_BASELINE:
            st.markdown('<div class="tp-case-detail-label">模拟初译（分析对照，不是历史初译）</div>', unsafe_allow_html=True)
            baseline_key = f"case_baseline_{job_id}_{selected_id}"
            if baseline_key not in st.session_state:
                st.session_state[baseline_key] = item.get("initial_text") or ""
            baseline = st.text_area("模拟初译", key=baseline_key, height=110,
                                    label_visibility="collapsed")
            base_a, base_b = st.columns(2)
            if base_a.button("保存修改模拟初译", key=f"case_baseline_save_{job_id}_{selected_id}", width="stretch"):
                _state, ok, message = core.update_synthetic_baseline(
                    job_id, selected_id, baseline, status="modified", actor="user")
                if not ok:
                    st.error(message)
                else:
                    st.rerun()
            if base_b.button("拒绝模拟初译", key=f"case_baseline_reject_{job_id}_{selected_id}", width="stretch"):
                core.update_synthetic_baseline(job_id, selected_id, baseline,
                                               status="rejected", actor="user")
                st.rerun()


def _render_workspace_cases_context(job_id, state):
    views = _workspace_case_views(job_id, state)
    pending = sum(item.get("review_status") == "unreviewed" for item in views)
    synthetic = sum(item.get("case_origin") == _case_provenance.SYNTHETIC_BASELINE for item in views)
    real = sum(item.get("case_origin") == _case_provenance.REAL_REVISION for item in views)
    st.markdown('<div class="tp-info-card"><h3>案例状态</h3>'
                f'<div class="tp-info-stat"><span>案例总数</span><b>{len(views)}</b></div>'
                f'<div class="tp-info-stat"><span>真实修订</span><b>{real}</b></div>'
                f'<div class="tp-info-stat"><span>合成对照</span><b>{synthetic}</b></div>'
                f'<div class="tp-info-stat"><span>尚未审校</span><b>{pending}</b></div>'
                '</div>', unsafe_allow_html=True)
    impact = core.dependency_impact_view(job_id, state)
    if impact.get("status") == "stale":
        st.markdown('<div class="tp-info-card"><h3>最近依赖变化</h3>'
                    f'<p class="tp-inspector-preview">{escape(_workspace_impact_reason(impact))}</p>'
                    f'<p class="tp-inspector-preview">{len(impact.get("affected") or [])} 项下游内容需要更新 · '
                    f'{len(impact.get("reusable") or [])} 个未受影响单元/资产可复用</p></div>',
                    unsafe_allow_html=True)


def _render_workspace_qa(job_id, state):
    """Compliance, independent QA facts, and the explicit finalization gate."""
    st.markdown('<div class="tp-section-kicker">交付检查</div><h2>合规与最终 QA</h2>'
                '<div class="tp-section-lead">每一项检查都独立决定一件事；结构检查和页面渲染通过，也不等于作者与 Word 最终复核已确认。</div>',
                unsafe_allow_html=True)
    compliance = _workspace_compliance_view(job_id, state)
    profile_id = str(state.get("compliance_profile_id") or
                     _compliance.DEFAULT_PROFILE_ID)
    profile = _compliance.compliance_profile(profile_id)
    counts = compliance.get("counts") or {}
    source_mapping_label = {
        "reference_template_mapped": "已登记匿名参考模板",
    }.get(profile.get("authority_mapping_status"), "院校特殊要求需人工确认")
    st.markdown(
        '<div class="tp-qa-profile"><strong>MTI 翻译实践报告</strong>'
        f'<span>{escape(str(profile.get("display_name") or "默认 MTI 实践报告规范"))} · {escape(source_mapping_label)}</span>'
        f'<b>通过 {counts.get("pass", 0)} · 失败 {counts.get("fail", 0)} · 人工复核 {counts.get("manual_review", 0)} · 未检查 {counts.get("not_checked", 0)}</b>'
        '</div>', unsafe_allow_html=True)
    with st.expander("查看规则集技术依据", expanded=False):
        st.markdown(
            f'**规则集内部标识**：`{escape(str(profile.get("profile_id") or "—"))}`')
        mapping_status = profile.get("authority_mapping_status")
        mapping_label = {
            "reference_template_mapped": "已登记匿名参考模板",
        }.get(mapping_status, "院校特殊要求需人工确认")
        st.caption(f'参考映射状态：{mapping_label}')
        for source in profile.get("sources") or profile.get("source_documents") or []:
            st.caption(f'参考来源记录：{source.get("document") or source.get("title") or source.get("file") or "—"} · '
                       f'{source.get("note") or source.get("authority") or ""}')
        for source in profile.get("implementation_sources") or []:
            st.caption(f'项目实现依据（非规范来源）：{source.get("document") or source.get("file") or "—"}')
    st.markdown('<h3 class="tp-qa-heading">合规检查清单</h3>', unsafe_allow_html=True)
    for index, rule in enumerate(compliance.get("rules") or []):
        status = str(rule.get("status") or "not_checked")
        label = {"pass": "通过", "fail": "失败", "manual_review": "手动复核",
                 "not_applicable": "不适用", "not_checked": "未检查"}.get(status, status)
        rule_label = (rule.get("description") or rule.get("label") or
                      rule.get("rule_id") or rule.get("id") or "合规规则")
        source = rule.get("source") or {}
        applicability = rule.get("scope") or rule.get("applicability") or "—"
        check_level = rule.get("check_type") or rule.get("check_level") or "—"
        check_level_label = {"deterministic": "自动检查", "manual": "人工检查",
                             "project_constraint": "项目约束"}.get(str(check_level), str(check_level))
        authority = rule.get("authority_level") or ""
        authority_label = {"project": "项目约束",
                           "reference_template": "默认参考模板",
                           "custom_profile": "用户自定义院校规则"}.get(
                               str(authority), "未映射的自定义规则" if not (
                                   rule.get("source_available") or
                                   rule.get("reliable_source_mapping") or
                                   source.get("available"))
                               else str(source.get("authority") or "—"))
        source_document = rule.get("source_document") or source.get("file")
        has_rule_source = (
            rule.get("source_kind") in {"reference_template", "custom_profile"} and
            rule.get("authority_level") != "project" and
            (rule.get("source_available") or
             rule.get("reliable_source_mapping") or source.get("available")))
        rule_source = (source_document if has_rule_source else
                       "院校特殊要求需根据实际模板确认")
        with st.container(key=f"qa_rule_{job_id}_{index}"):
            st.markdown(
                f'<div class="tp-qa-rule is-{status}"><div><strong>{escape(str(rule_label))}</strong>'
                f'<p>{escape(str(rule.get("message") or ""))}</p>'
                f'</div><span>{escape(label)}</span></div>', unsafe_allow_html=True)
            with st.expander("查看来源与技术细节", expanded=False):
                st.caption(f'规则来源：{rule_source} · 页码/条款：{rule.get("page_or_clause") or source.get("page") or "待提供"}')
                source_url = rule.get("source_url") or source.get("url") or ""
                if source_url and has_rule_source:
                    st.markdown(f'来源链接：[打开来源]({source_url})')
                st.caption(f'适用范围：{applicability} · 检查方式：{check_level_label} · 规则层级：{authority_label}')
                implementation_source = rule.get("implementation_source")
                implementation_clause = rule.get("implementation_clause") or rule.get("source_clause")
                if implementation_source:
                    st.caption(f'项目实现依据（非规范来源）：{implementation_source} · {implementation_clause or "—"}')
                st.caption(f'内部状态：{status} · 规则标识：{rule.get("rule_id") or rule.get("id") or "—"}')
    qa = _finalization.normalize_final_qa(state.get("final_qa"))
    structural = _workspace_structural_qa(job_id, state)
    if structural in {"PASS", "FAIL", "NOT_RUN"} and structural != qa.get("structural_qa"):
        qa["structural_qa"] = structural
        state["final_qa"] = qa
        core.save_job_state(job_id, state)
    st.markdown('<h3 class="tp-qa-heading">独立最终质量事实</h3>', unsafe_allow_html=True)
    qa_rows = [
        ("structural_qa", "DOCX 结构检查", structural, "文档结构、段落与确定性规则"),
        ("libreoffice_render", "LibreOffice 页面渲染", qa.get("libreoffice_render"), "DOCX 转 PDF 页面预检"),
        ("author_visual_review", "作者视觉复核", qa.get("author_visual_review"), "作者检查关键页面与版式"),
        ("word_final_review", "Word 最终复核", qa.get("word_final_review"), "Word 更新字段并确认最终页面"),
    ]
    for field, label, status, proof in qa_rows:
        with st.container(key=f"qa_fact_{job_id}_{field}"):
            left, right = st.columns([3.1, 1.1], gap="small")
            with left:
                st.markdown(f'<div class="tp-qa-fact"><strong>{escape(label)}</strong><span>{escape(proof)}</span></div>', unsafe_allow_html=True)
            with right:
                status_class = "stale" if status == "STALE" else str(status).lower()
                status_label = "需要重建" if status == "STALE" else _finalization.final_qa_label(
                    str(field), str(status))
                st.markdown(f'<div class="tp-qa-status is-{status_class}">{escape(status_label)}</div>', unsafe_allow_html=True)
            if field == "libreoffice_render":
                if st.button("运行 LibreOffice 页面预检", key=f"qa_run_lo_{job_id}",
                             disabled=not bool(state.get("p2_done")), width="stretch"):
                    try:
                        core.run_libreoffice_render_qa(job_id)
                        st.rerun()
                    except RuntimeError as exc:
                        st.error(str(exc))
            elif field in {"author_visual_review", "word_final_review"}:
                button_label = "确认已完成" if status != "CONFIRMED" else "撤销确认"
                next_status = "CONFIRMED" if status != "CONFIRMED" else "NOT_CONFIRMED"
                if st.button(button_label, key=f"qa_confirm_{job_id}_{field}", width="stretch"):
                    core.record_final_qa(job_id, field, next_status,
                                        "人工在最终 QA 工作区记录", actor="user")
                    st.rerun()
    if qa.get("libreoffice_render") == "PASS":
        st.caption(f'渲染记录：{qa.get("page_count") or "—"} 页 · 当前 DOCX 已渲染并保存 PDF 页面预检结果。')
        render_record = core.load_academic_artifact(job_id, "libreoffice_render") or {}
        from transpraxis import rendered_qa as _rendered_qa
        st.markdown("#### 关键页面定位（作者需在 Word 中复核）")
        st.dataframe(pd.DataFrame(_rendered_qa.key_page_references(render_record)),
                     hide_index=True, width="stretch")
    st.warning("只有以上四项独立质量事实和合规门禁都分别满足要求，才能把版本标为最终确认。")


def _render_workspace_qa_context(job_id, state):
    qa = _finalization.normalize_final_qa(state.get("final_qa"))
    compliance = _workspace_compliance_view(job_id, state)
    snapshot = core.delivery_snapshot_status(job_id, state)
    structural = _workspace_structural_qa(job_id, state)
    render_status = _finalization._artifact_status_value(
        state.get("academic_state") or {}, "libreoffice_render")
    structural_label = {"PASS": "已通过", "FAIL": "失败", "STALE": "需要重建",
                         "NOT_RUN": "尚未运行"}.get(structural, "尚未运行")
    render_label = ("需要重建" if render_status in {"stale", "missing"} else
                    "失败" if render_status == "failed" or qa.get("libreoffice_render") == "FAIL" else
                    "已通过" if qa.get("libreoffice_render") == "PASS" else "尚未运行")
    author_label = "已确认" if qa.get("author_visual_review") == "CONFIRMED" else "尚未确认"
    word_label = "已确认" if qa.get("word_final_review") == "CONFIRMED" else "尚未确认"
    delivery_label, _ = _workspace_delivery_state(job_id, state)
    st.markdown('<div class="tp-info-card"><h3>交付门禁</h3>'
                f'<div class="tp-info-stat"><span>合规失败</span><b>{(compliance.get("counts") or {}).get("fail", 0)}</b></div>'
                f'<div class="tp-info-stat"><span>DOCX 结构</span><b>{structural_label}</b></div>'
                f'<div class="tp-info-stat"><span>页面渲染</span><b>{render_label}</b></div>'
                f'<div class="tp-info-stat"><span>作者 / Word</span><b>{author_label} / {word_label}</b></div>'
                f'<div class="tp-info-stat"><span>交付判断</span><b>{delivery_label}</b></div>'
                f'<div class="tp-info-stat"><span>最近冻结</span><b>{"v" + str((snapshot.get("latest") or {}).get("snapshot_version")) if snapshot.get("latest") else "尚未生成"}</b></div>'
                '</div>', unsafe_allow_html=True)


_REPORT_CASE_ISSUES = {
    "case_count_status_mismatch", "insufficient_core_revision_cases",
    "invalid_selected_case", "non_revision_case_used_as_revision_analysis",
    "synthetic_pipeline_unavailable", "synthetic_only_without_eligible_cases",
    "ineligible_synthetic_case_selected", "synthetic_case_provenance_mismatch",
    "duplicate_selected_case_presentation",
    "case_presentation_count_mismatch",
    "case_minimum_not_met", "case_coverage_below_recommended",
    "duplicate_canonical_case", "missing_focus_span",
    "focus_span_outside_canonical", "focus_excerpt_excessively_long",
    "full_segment_rendered_as_case", "case_node_focus_mismatch",
    "case_numbering_not_continuous", "case_hierarchy_missing",
    "case_distribution_severely_unbalanced",
    "research_question_case_coverage_insufficient",
    "case_presentation_contract_violation",
}
_REPORT_SECTION_ISSUES = {
    "missing_required_section", "section_too_short", "missing_planned_claim",
    "missing_research_question_link", "missing_selected_case",
    "missing_planned_literature_claim", "missing_planned_literature_evidence",
    "section_literature_outside_plan", "section_literature_claim_outside_plan",
    "section_literature_evidence_outside_plan", "section_literature_source_outside_plan",
}
_REPORT_STATISTIC_ISSUES = {
    "unknown_project_statistic", "wrong_project_statistic",
    "unresolved_statistic_token", "unmarked_project_statistic",
}
_REPORT_TEMPLATE_ISSUES = {
    "template_chapter_count_mismatch", "template_missing_chapter",
    "template_chapter_order_mismatch", "template_chapter_title_mismatch",
    "template_missing_subsection", "template_subsection_level_mismatch",
    "template_subsection_order_mismatch", "template_extra_subsection",
    "template_extra_chapter", "template_hash_mismatch", "template_matter_mismatch",
    "template_case_role_missing", "template_case_role_mismatch",
    "template_case_mapping_mismatch", "template_case_minimum_not_met",
    "template_front_matter_content_missing", "template_internal_id_visible",
    "template_unresolved_marker", "template_duplicate_rendering",
    "template_duplicate_heading",
}


def _report_artifacts(job_id):
    return {
        name: core.load_academic_artifact(job_id, name)
        for name in (
            "evidence", "argument_plan", "selected_cases", "outline", "report", "validation", "review",
            "literature_sources", "literature_evidence", "literature_claims",
            "literature_support_review", "academic_quality",
            "human_evidence_questions",
            "final_docx_validation",
        )
    }


def _report_quality_label(status):
    return {
        "pass": "已验证", "pass_with_warnings": "已验证 · 有警告",
        "review_required": "需要复核", "fail": "需要复核",
        "literature_required": "需要补充文献",
        "failed": "生成失败", "not_started": "未生成",
        "stale": "需要更新（按影响范围）", "in_progress": "生成中",
    }.get(status, "—")


def _report_validation_label(status):
    return {
        "pass": "通过", "pass_with_warnings": "通过 · 有警告",
        "fail": "需要复核", "review_required": "需要复核",
        "not_configured": "未配置模板",
    }.get(status, "未生成")


def _report_literature_status(artifacts):
    sources = (artifacts.get("literature_sources") or {}).get("sources") or []
    evidence = (artifacts.get("literature_evidence") or {}).get("items") or []
    claims = (artifacts.get("literature_claims") or {}).get("items") or []
    if not sources:
        return "尚未建立"
    if not evidence or not claims:
        return "待补证据"
    if any(item.get("evidence_grounded_status") in {"needs_review", "review_required"}
           for item in claims):
        return "需要复核"
    return "已登记"


def _report_updated_label(job_id, state, academic):
    value = academic.get("updated_at") or \
        (core.recovery_summary(job_id, state) or {}).get("last_saved_at")
    return _format_saved_at(value) if value else "最近"


def _report_docx_bytes(state, frozen_assets=None):
    """Use the persisted template renderer for Report and Delivery surfaces."""
    job_id = st.session_state.get("active_job_id")
    if not job_id:
        return None
    return core.report_docx_bytes(job_id, state, frozen_assets=frozen_assets)


def _report_heading_title(value):
    value = re.sub(r"\s+#+\s*$", "", str(value or "")).strip()
    return value


def _report_heading_key(value):
    value = _report_heading_title(value).casefold()
    value = re.sub(r"^\d+(?:\.\d+)*[.、．]?\s*", "", value)
    return re.sub(r"\s+", "", value)


def _report_headings(report):
    headings = []
    for line_index, line in enumerate(str(report or "").splitlines()):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if not match:
            continue
        title = _report_heading_title(match.group(2))
        if not title:
            continue
        headings.append({
            "line_index": line_index,
            "level": len(match.group(1)),
            "title": title,
            "anchor": f"report-heading-{len(headings) + 1}",
        })
    return headings


def _report_markdown_with_anchors(report, headings):
    lines = str(report or "").splitlines()
    for item in reversed(headings):
        lines.insert(item["line_index"],
                     f'<a id="{escape(item["anchor"])}"></a>')
    return "\n".join(lines)


def _clean_report_for_display(report_md):
    """Hide provenance and collapse adjacent duplicate headings in the reader."""
    text = str(report_md or "")
    text = re.sub(r"\\?<!--.*?-->\\?", "", text, flags=re.DOTALL)
    text = re.sub(r"\\?\{\{TERM:[^}]+\}\}\\?", "", text)
    text = re.sub(r"\b(?:(?:seg|claim|rq|lit-claim|lit-evidence|human-ev)-"
                  r"[A-Za-z0-9_.:-]+|(?:AQ|AV|AR|LR)-\d+)\b",
                  "对应证据", text)
    # These two shapes are reachable in ordinary legacy/generated reports:
    # the analysis label can leak a quote marker, and a bold numbered
    # subsection can be glued to the preceding paragraph.  Repair only those
    # exact forms; ordinary blockquotes and bold prose remain untouched.
    text = re.sub(
        r"((?:\*{0,2}分析\*{0,2})\s*[：:]\s*)>\s*[。．]\s*",
        r"\1", text)
    text = re.sub(
        r"(?P<lead>[。！？])\s*(?P<title>\d+(?:\.\d+)+\s+[^。\n*]{2,100})"
        r"\*{2}\s*[。！？]",
        r"\g<lead>\n\n### \g<title>\n\n", text)
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            title = _report_heading_title(match.group(2))
            # The toolbar is the single report-title source.
            if not any(value.strip() for value in cleaned) and \
                    title.casefold().startswith("翻译实践报告"):
                continue
            previous = next((value for value in reversed(cleaned) if value.strip()), "")
            previous_match = re.match(r"^#{1,6}\s+(.+?)\s*$", previous)
            if previous_match and _report_heading_key(previous_match.group(1)) == \
                    _report_heading_key(title):
                continue
        cleaned.append(line.rstrip())
    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return _report_template.anonymize_sensitive_institutions(text.strip())


def _report_issue_category(issue):
    issue_type = str(issue.get("type") or "")
    if issue_type in _REPORT_CASE_ISSUES:
        return "案例不足"
    if issue_type in _REPORT_STATISTIC_ISSUES:
        return "统计验证失败"
    if issue_type in _REPORT_TEMPLATE_ISSUES:
        return "模板合规"
    if "citation" in issue_type or issue_type in {
            "unregistered_formal_citation", "uncitable_literature_source"}:
        return "引用需要确认"
    if "literature" in issue_type or "grounding" in issue_type:
        return "文献证据缺失"
    if issue_type in _REPORT_SECTION_ISSUES or issue.get("section_id"):
        return "章节需要重新生成"
    if "human" in issue_type:
        return "需要人工补充"
    return "需要人工补充"


def _report_issue_detail(category, issue):
    if category == "案例不足":
        return "项目中可追溯、符合资格的案例数量或案例选择状态需要确认。"
    if category == "文献证据缺失":
        return "文献来源、逐字证据与论点之间的支持链路尚未完整。"
    if category == "引用需要确认":
        return "存在需要核对的引用来源或作者—年份信息。"
    if category == "统计验证失败":
        return "报告中的项目统计与证据库不一致，或统计来源未能解析。"
    if category == "模板合规":
        return "报告与上传模板的章节、标题、层级或角色不一致。"
    if category == "章节需要重新生成":
        section_id = issue.get("section_id")
        return f"第 {section_id} 节存在结构或论证问题，建议定点重新生成。" \
            if section_id else "报告章节存在结构或论证问题，建议重新生成。"
    if "human" in str(issue.get("type") or ""):
        return "有需要作者确认或补充的项目过程信息。"
    return "报告质量结果仍需人工核对后再作为最终学术结论使用。"


def _report_issue_groups(artifacts, academic):
    groups = {}

    def add(category, detail, section_id=None):
        group = groups.setdefault(category, {"category": category, "details": [],
                                             "sections": set()})
        if detail and detail not in group["details"]:
            group["details"].append(detail)
        if section_id:
            group["sections"].add(str(section_id))

    selected = artifacts.get("selected_cases") or {}
    policy = selected.get("authentic_selection_status") or \
        (selected.get("case_count_policy") or {}).get("status")
    if policy == "insufficient_revision_cases":
        add("案例不足", "符合资格的真实修订案例少于当前研究要求。")

    validation = artifacts.get("validation") or {}
    review = artifacts.get("review") or {}
    literature_review = artifacts.get("literature_support_review") or {}
    quality = artifacts.get("academic_quality") or {}
    final_docx_validation = artifacts.get("final_docx_validation") or {}
    for issue in list(validation.get("issues") or []) \
            + list(review.get("issues") or []) \
            + list(literature_review.get("issues") or []) \
            + list(quality.get("findings") or []) \
            + list(final_docx_validation.get("issues") or []):
        category = _report_issue_category(issue)
        add(category, _report_issue_detail(category, issue), issue.get("section_id"))

    # A legacy/fixture report without a structured report artifact has no
    # literature contract to enforce.  Once the academic pipeline has emitted
    # the report artifact, its explicit literature status is authoritative.
    report_artifact = artifacts.get("report") or {}
    if report_artifact and not (artifacts.get("literature_sources") or {}).get("sources"):
        add("文献证据缺失", "正文结构与案例已完成，但学术文献支持尚未建立。")

    if _academic_validator.citation_validation_status(
            validation, artifacts.get("literature_sources"),
            artifacts.get("literature_evidence"), artifacts.get("literature_claims")) \
            == "evidence_missing" and \
            (artifacts.get("literature_sources") or {}).get("sources"):
        add("文献证据缺失", "已登记文献来源，但逐字证据或文献主张尚未完整。")

    dimensions = academic.get("quality_dimensions") or {}
    if dimensions.get("literature_grounding") in {"review_required", "fail"}:
        add("文献证据缺失", "文献证据的可核验性仍需处理。")
    if dimensions.get("citation_validation") in {"review_required", "fail"}:
        add("引用需要确认", "引用完整性检查未通过。")
    if dimensions.get("statistics_validation") in {"review_required", "fail"}:
        add("统计验证失败", "统计一致性检查未通过。")
    human_status = academic.get("human_evidence_status") or {}
    if human_status.get("unanswered") or human_status.get("critical_questions"):
        add("需要人工补充", "仍有未回答的人类证据问题。")
    if (academic.get("quality_status") or academic.get("status")) in {
            "review_required", "fail", "failed"} and not groups:
        add("需要人工补充", "报告质量状态仍要求人工复核。")

    ordered = []
    for category in ("模板合规", "案例不足", "文献证据缺失", "引用需要确认",
                     "统计验证失败", "章节需要重新生成", "需要人工补充"):
        if category not in groups:
            continue
        group = groups[category]
        sections = sorted(group["sections"], key=str)
        if category == "模板合规":
            action = "处理模板问题"
        elif category == "案例不足":
            action = "处理案例"
        elif category == "文献证据缺失":
            action = "处理文献证据"
        elif category == "引用需要确认":
            action = "检查引用"
        elif category == "统计验证失败":
            action = "检查统计"
        elif category == "章节需要重新生成":
            action = "重新生成章节"
        else:
            action = "回答人工问题"
        group["action"] = action
        group["target"] = "detail"
        ordered.append(group)
    return ordered


def _report_issue_level(category):
    if category == "需要人工补充":
        return "human_review"
    if category in {"章节需要重新生成", "引用需要确认"}:
        return "warning"
    return "blocker"


def _report_issue_impact(group):
    category = group["category"]
    sections = sorted(group.get("sections") or [], key=str)
    if group.get("target") == "review":
        return (f"涉及 {len(sections)} 个段落，完成处理后才能继续最终交付。"
                if sections else "翻译审校队列仍有未关闭发现。")
    if category == "案例不足":
        return "案例分析未满足数量或可追溯性要求，报告不能最终交付。"
    if category == "统计验证失败":
        return "项目统计与证据不一致，最终稿不能通过验证。"
    if category == "模板合规":
        return "章节或版式未满足模板约束，DOCX 交付可能被阻止。"
    if category == "文献证据缺失":
        return "论点缺少可核验支持，报告不能作为最终学术成果交付。"
    if category == "引用需要确认":
        return "引用信息仍需核对，可能影响稿件可信度。"
    if category == "章节需要重新生成":
        location = "、".join(f"第 {value} 节" for value in sections)
        return f"{location or '部分章节'}的结构或证据需要修正。"
    return "仍有内容依赖作者判断或项目经历补充。"


def _report_issue_recommendation(category):
    return {
        "模板合规": "查看验证结果，按模板约束修正报告。",
        "案例不足": "查看案例选择结果，补足合格案例。",
        "文献证据缺失": "检查来源与证据链，补齐文献支持。",
        "引用需要确认": "核对引用来源和作者—年份信息。",
        "统计验证失败": "查看不一致项，重新验证项目统计。",
        "章节需要重新生成": "定位受影响章节，仅重新生成问题部分。",
        "需要人工补充": "回答待补充问题，再继续生成受影响内容。",
    }[category]


def _report_review_issue_groups(state):
    """Bring translation delivery findings into the report Issues view."""
    groups = {}
    for context in _workspace_review_contexts(state):
        if context.get("severity") not in {"blocking", "actionable"}:
            continue
        category = context.get("category_label") or "翻译审校"
        severity = "blocker" if context.get("severity") == "blocking" else "warning"
        group = groups.setdefault(category, {
            "category": category,
            "details": [],
            "sections": set(),
            "severity": severity,
            "level": severity,
            "action": "处理审校",
            "target": "review",
            "finding_ids": [],
        })
        if severity == "blocker":
            group["severity"] = group["level"] = "blocker"
        reason = context.get("summary") or context.get("reason") or "存在待处理的翻译审校发现。"
        if reason not in group["details"]:
            group["details"].append(reason)
        if context.get("segment_number") not in {None, "?"}:
            group["sections"].add(f"段落 {context['segment_number']}")
        finding_id = context.get("finding_id")
        if finding_id and finding_id not in group["finding_ids"]:
            group["finding_ids"].append(finding_id)
    for group in groups.values():
        sections = sorted(group["sections"], key=str)
        group["impact"] = (f"涉及 {len(sections)} 个段落，完成处理后才能继续最终交付。"
                            if sections else "翻译审校队列仍有未关闭发现。")
        group["recommendation"] = "打开审校工作区，逐项处理并保留处理记录。"
    return list(groups.values())


def _report_page_view(job_id, state, artifacts=None):
    """Compose the report page's single status and decision hierarchy."""
    artifacts = artifacts or _report_artifacts(job_id)
    academic = state.get("academic_state") or {}
    runtime_view = core.build_job_runtime_view(job_id, state)
    runtime_status = runtime_view.get("runtime_status") or runtime_view.get("status")
    quality = academic.get("quality_status") or academic.get("status") or "not_started"
    final_qa = _finalization.normalize_final_qa(state.get("final_qa"))
    academic_records = academic.get("artifacts") or {}
    strict_finalization = bool(state.get("report_enabled")) and any(
        name in academic_records for name in (
            "report", "compliance", "final_docx_validation",
            "libreoffice_render", "report_qa"))
    final_review_pending = strict_finalization and (
        final_qa.get("author_visual_review") != "CONFIRMED" or
        final_qa.get("word_final_review") != "CONFIRMED")
    validation = artifacts.get("validation") or {}
    groups = _report_issue_groups(artifacts, academic) + _report_review_issue_groups(state)
    if runtime_status == "waiting_manual" and not any(
            group.get("severity") == "human_review" for group in groups):
        groups.append({
            "category": "运行需要人工确认",
            "details": ["当前阶段已暂停，等待人工输入后才能继续。"],
            "sections": set(),
            "severity": "human_review",
            "level": "human_review",
            "action": "查看运行详情",
            "target": "runtime",
            "impact": "报告生成流程尚未完成。",
            "recommendation": "查看运行详情，确认需要补充的输入。",
        })
    for group in groups:
        group.setdefault("severity", _report_issue_level(group["category"]))
        group["level"] = group["severity"]
        group["impact"] = _report_issue_impact(group)
        group.setdefault("recommendation", _report_issue_recommendation(group["category"])
                         if group["category"] in {
                             "模板合规", "案例不足", "文献证据缺失", "引用需要确认",
                             "统计验证失败", "章节需要重新生成", "需要人工补充",
                         } else "打开审校工作区，逐项处理并保留处理记录。")
    active_statuses = {"resume_requested", "queued", "starting", "running",
                       "waiting_external", "cancelling"}
    blocking = [group for group in groups if group["severity"] == "blocker"]
    if runtime_status in active_statuses:
        overall = "running"
    elif runtime_status == "waiting_manual":
        overall = "review_required"
    elif runtime_status in {"failed", "interrupted", "stalled"} or quality == "failed":
        overall = "failed"
    elif runtime_status in {"cancelled", "idle_incomplete"} and not state.get("p3_done"):
        overall = "blocked"
    elif blocking or quality == "fail" or validation.get("status") == "fail":
        overall = "blocked"
    elif groups or quality in {"review_required", "pass_with_warnings"}:
        overall = "review_required"
    elif state.get("p3_done") and quality == "pass" and validation.get("status") == "pass":
        overall = "ready_for_delivery"
    elif state.get("p3_md"):
        overall = "draft_preview"
    else:
        overall = "blocked"
    report_preview_available = bool(state.get("p3_md") or artifacts.get("report"))
    status_meta = {
        "running": ("正在运行", "查看运行详情", "运行详情", "neutral"),
        "failed": ("运行失败", "查看运行详情", "运行详情", "danger"),
        "blocked": ("可预览 · 尚不可交付" if report_preview_available else "尚不可交付",
                    "处理阻塞问题", "问题与修复", "danger"),
        "review_required": ("可预览 · 等待复核" if report_preview_available else "等待复核",
                            "查看待复核项", "问题与修复", "warning"),
        "ready_for_delivery": ("暂不满足交付条件" if final_review_pending else "可以冻结交付",
                                "完成最终确认" if final_review_pending else "进入交付",
                                None, "warning" if final_review_pending else "success"),
        "draft_preview": ("可预览 · 尚不可交付", "查看当前稿件", "当前稿件", "neutral"),
    }
    label, cta, target_tab, tone = status_meta[overall]
    severity_order = {"blocker": 0, "warning": 1, "human_review": 2}
    groups.sort(key=lambda group: (severity_order.get(group.get("severity"), 9),
                                   group.get("category", "")))
    recommended_issue = next((group for group in groups
                              if group.get("severity") == "blocker"), None)
    if recommended_issue is None:
        recommended_issue = next((group for group in groups
                                  if group.get("severity") in {"warning", "human_review"}), None)
    if recommended_issue and overall in {"blocked", "review_required"}:
        cta = recommended_issue["action"]
        target_tab = "问题与修复"
    if overall in {"failed", "running"}:
        target_tab = "运行详情"
    if overall == "blocked" and not groups:
        cta = "查看运行详情"
        target_tab = "运行详情"
    if overall == "blocked":
        if blocking:
            gate_note = f"仍有 {len(blocking)} 个报告阻塞项；下一步：{cta}。"
        elif validation.get("status") == "fail":
            gate_note = "当前问题列表没有报告阻塞项，但验证结果仍未通过；下一步：查看报告验证结果。"
        elif quality in {"fail", "failed"}:
            gate_note = "当前问题列表没有报告阻塞项，但报告质量检查未通过；下一步：查看质量检查结果。"
        else:
            gate_note = "报告门禁尚未完成；下一步：查看运行详情并完成报告流程。"
    elif overall == "review_required" and not groups:
        gate_note = "报告仍需人工复核；下一步：查看运行详情并记录复核结果。"
    elif overall == "ready_for_delivery" and final_review_pending:
        gate_note = "报告技术检查已完成，但作者视觉复核和 Word 最终复核仍未确认；下一步：进入交付检查。"
    else:
        gate_note = ""
    return {
        "overall": overall, "overall_label": label, "tone": tone,
        "primary_cta": cta, "target_tab": target_tab,
        "runtime": runtime_view, "quality": quality,
        "validation": validation, "groups": groups, "blocking": blocking,
        "recommended_issue": recommended_issue,
        "preview_only": overall != "ready_for_delivery" or final_review_pending,
        "delivery_label": ("暂不满足交付条件" if final_review_pending else "可以冻结交付")
        if overall == "ready_for_delivery" else
        "可预览 · 尚不可交付" if report_preview_available else "尚不可交付",
        "final_review_pending": final_review_pending,
        "gate_note": gate_note,
    }


def _select_report_tab(job_id, label):
    st.session_state[f"report_tabs_{job_id}"] = label


def _report_issues_for_category(category, artifacts):
    issues = []
    for artifact_name, field in (("validation", "issues"), ("review", "issues"),
                                 ("literature_support_review", "issues"),
                                 ("academic_quality", "findings")):
        for issue in (artifacts.get(artifact_name) or {}).get(field) or []:
            if _report_issue_category(issue) == category:
                issues.append(issue)
    return issues


def _queue_report_repair(job_id, state, category, sections):
    if category == "模板合规":
        scope = "writer"
    elif category == "案例不足":
        scope = "planning"
    elif category == "文献证据缺失":
        scope = "all"
    elif category in {"引用需要确认", "统计验证失败"}:
        scope = "validation"
    elif category == "章节需要重新生成" and sections:
        for section_id in sections:
            core.invalidate_academic_report(job_id, "section", section_id)
        scope = None
    else:
        scope = "case_analysis" if category == "需要人工补充" else "writer"
    if scope:
        core.invalidate_academic_report(job_id, scope)
    _resume_job(job_id, core.load_job_state(job_id) or state)


def _render_report_issue_detail(job_id, state, groups, artifacts):
    category = st.session_state.get(f"report_review_focus_{job_id}")
    group = next((item for item in groups if item["category"] == category), None)
    if not group:
        return

    with st.container(key=f"report_issue_detail_{job_id}"):
        back_col, _ = st.columns([1.2, 4], gap="small")
        with back_col:
            if st.button("← 返回当前问题", key=f"report_issue_back_{job_id}",
                         type="secondary", width="stretch"):
                st.session_state.pop(f"report_review_focus_{job_id}", None)
                st.rerun()
        st.markdown(
            f'<div class="tp-report-focus"><div class="tp-report-focus-head">'
            f'<h3>{escape(group["action"])}</h3>'
            f'<span class="tp-report-issue-badge">{escape(group["category"])}</span>'
            '</div>', unsafe_allow_html=True)
        if group.get("target") == "review":
            st.info("这类问题属于翻译审校队列；打开审校工作区后可查看原文、译文和证据，并留下处理记录。")
            if st.button("打开审校工作区", type="primary",
                         key=f"report_open_review_{job_id}", width="stretch"):
                _open_report_issue(job_id, group)
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
            return
        if category == "案例不足":
            selected = artifacts.get("selected_cases") or {}
            cases = selected.get("cases") or []
            st.caption(
                f"选择状态：{selected.get('authentic_selection_status') or '未记录'} · "
                f"当前案例 {len(cases)} 个")
            if cases:
                rows = [{
                    "案例": item.get("case_id") or "—",
                    "类型": _case_provenance.display_contract(item)["origin_label"],
                    "类型说明": _case_provenance.display_contract(item)[
                        "origin_description"],
                    "来源段": item.get("segment_id") or item.get("source_segment_id") or "—",
                    "聚焦问题": (item.get("focus") or {}).get("issue") or "—",
                    "难点": item.get("difficulty_group") or "—",
                    "策略": item.get("strategy_group") or "—",
                } for item in cases]
                with st.expander(f"查看 {len(cases)} 个已选案例", expanded=False):
                    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            else:
                st.info("当前没有符合报告要求的案例。重新规划会再次扫描现有翻译修订记录。")
            _render_case_portfolio(selected, artifacts.get("validation") or {})
        elif category == "文献证据缺失":
            sources = (artifacts.get("literature_sources") or {}).get("sources") or []
            evidence = (artifacts.get("literature_evidence") or {}).get("items") or []
            claims = (artifacts.get("literature_claims") or {}).get("items") or []
            st.caption(f"已登记来源 {len(sources)} · 可核验证据 {len(evidence)} · 文献主张 {len(claims)}")
            for source in sources:
                st.markdown(f"- {escape(str(source.get('title') or source.get('source_id') or '未命名来源'))}")
            if not sources:
                st.info("当前没有已登记的参考资料；请先在新建任务的报告设置中添加文献，再重新生成。")
        elif category == "需要人工补充":
            questions = [
                question for question in
                (artifacts.get("human_evidence_questions") or {}).get("questions") or []
                if question.get("status") == "open"
            ]
            if not questions:
                st.success("当前没有尚未回答的人类证据问题，可以继续生成受影响章节。")
            for question in questions:
                question_id = question.get("question_id")
                context = question.get("context") or {}
                st.markdown(f"**{escape(str(question.get('question') or '请补充项目过程信息'))}**")
                if context.get("source"):
                    st.caption(f"原文：{str(context['source'])[:180]}")
                answer_key = f"report_human_answer_{job_id}_{question_id}"
                answer = st.text_area(
                    "你的回答", key=answer_key, height=90,
                    placeholder="如无法回忆，可填写“不记得/没有相关记录”。")
                if st.button("提交回答", key=f"report_human_submit_{job_id}_{question_id}"):
                    if not answer.strip():
                        st.warning("请填写回答；无法回忆时可直接填写“不记得”。")
                    else:
                        core.record_human_evidence(job_id, question_id, answer)
                        st.session_state.pop(answer_key, None)
                        st.rerun()
        elif category == "章节需要重新生成":
            sections = group.get("sections") or []
            st.info("将只重新生成问题章节：" + "、".join(f"第 {value} 节" for value in sections))
        else:
            issues = _report_issues_for_category(category, artifacts)
            if not issues:
                st.info("已定位该复核项；重新执行对应检查后会刷新这里的结果。")
            for issue in issues:
                reason = issue.get("reason") or issue.get("message") or \
                    _report_issue_detail(category, issue)
                st.markdown(f"- {escape(str(reason))}")

        sections = sorted(group.get("sections") or [], key=str)
        action_labels = {
            "模板合规": "按模板重新生成",
            "案例不足": "重新选择案例并继续生成",
            "文献证据缺失": "重建文献证据并继续生成",
            "引用需要确认": "重新验证引用并继续生成",
            "统计验证失败": "重新验证统计并继续生成",
            "章节需要重新生成": "重新生成问题章节",
            "需要人工补充": "用已提交回答继续生成",
        }
        open_questions = category == "需要人工补充" and any(
            question.get("status") == "open" for question in
            (artifacts.get("human_evidence_questions") or {}).get("questions") or [])
        disabled = not api_key or open_questions
        if st.button(action_labels[category], type="secondary",
                     key=f"report_issue_repair_{job_id}_{category}",
                     disabled=disabled, width="stretch"):
            _queue_report_repair(job_id, state, category, sections)
            st.rerun()
        if not api_key:
            st.caption("继续生成需要先在“设置”中配置当前模型的 API Key。")
        elif open_questions:
            st.caption("请先提交上方所有待回答问题；无法回忆时可以如实说明。")
        st.markdown('</div>', unsafe_allow_html=True)


def _render_case_portfolio(selected_cases, validation):
    portfolio = (selected_cases or {}).get("case_portfolio") or {}
    cases = list(portfolio.get("cases") or [])
    if not cases:
        return
    case_validation = (validation or {}).get("case_validation") or {}
    st.markdown("### Case Portfolio")
    pool = int(portfolio.get("candidate_pool_count") or 0)
    selected_count = int(portfolio.get("selected_case_count") or len(cases))
    validated = case_validation.get("provenance_safe_case_count")
    cols = st.columns(3)
    cols[0].metric("总候选数", pool)
    cols[1].metric("最终选中", selected_count)
    cols[2].metric("已验证", "—" if validated is None else int(validated))
    distribution = (selected_cases or {}).get("difficulty_distribution") or {}
    if distribution:
        st.caption(" · ".join(f"{label} {count}" for label, count in distribution.items()))
    st.caption("真实修订：项目保存的历史初译与当前译文；合成对照：模拟初译仅用于分析，不是历史初译。")
    rows = []
    for item in cases:
        focus = item.get("focus") or {}
        source = (focus.get("source_span") or {}).get("text") or ""
        display = _case_provenance.display_contract(item)
        rows.append({
            "case_id": item.get("case_id") or "—",
            "类型": display["origin_label"],
            "类型说明": display["origin_description"],
            "focus": source,
            "难点": item.get("difficulty_group") or "—",
            "策略": item.get("strategy_group") or "—",
            "RQ": "、".join(item.get("research_question_ids") or []),
            "provenance": item.get("provenance_confidence") or "—",
        })
    with st.expander(f"查看 {selected_count} 个聚焦案例", expanded=False):
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _open_report_issue(job_id, group):
    if group.get("target") == "review":
        st.session_state.workspace_section = "review"
        finding_ids = group.get("finding_ids") or []
        if finding_ids:
            st.session_state.selected_finding_id = finding_ids[0]
        return
    if group.get("target") == "runtime":
        _select_report_tab(job_id, "运行详情")
        return
    st.session_state[f"report_review_focus_{job_id}"] = group["category"]


def _render_report_status_card(job_id, view):
    runtime = view["runtime"]
    progress = (f'{runtime["progress_completed"]} / {runtime["progress_total"]}'
                if runtime["progress_total"] else "—")
    signal = runtime.get("runtime", {}).get("last_heartbeat_at") or runtime.get("last_activity_at")
    current_step = runtime.get("current_operation") or runtime.get("headline") or "等待下一步"
    detail = runtime.get("detail") or "当前没有新的运行说明。"
    if view.get("gate_note") and view["gate_note"] not in detail:
        detail = f"{detail} {view['gate_note']}"
    progress_html = ""
    if runtime.get("progress_total"):
        progress_pct = round(min(1.0, runtime["progress_completed"] /
                                 runtime["progress_total"]) * 100)
        progress_html = (f'<div class="tp-report-status-progress" aria-label="报告进度 {escape(progress)}">'
                          f'<i style="width:{progress_pct}%"></i></div>')
    st.markdown(
        f'<div class="tp-report-overall is-{view["tone"]}">'
        '<div class="tp-report-overall-head"><div>'
        '<div class="tp-report-toolbar-kicker">报告状态</div>'
        f'<h3>{escape(view["overall_label"])}</h3></div>'
        f'{_workspace_status_badge(view["overall_label"], view["tone"])}</div>'
        '<div class="tp-report-overall-grid">'
        f'<div><span>当前阶段</span><strong>{escape(current_step)}</strong></div>'
        f'<div><span>当前进度</span><strong>{escape(progress)}</strong></div>'
        f'<div><span>最近运行信号</span><strong>{escape(_runtime_clock(signal))}</strong></div>'
        f'</div>{progress_html}<p class="tp-report-overall-detail">{escape(detail)}</p>'
        '</div>', unsafe_allow_html=True)
    if view["overall"] == "running":
        with st.popover("更多操作", use_container_width=False):
            if st.button("取消任务", type="secondary", width="stretch",
                         key=f"report_cancel_{job_id}"):
                core.request_job_cancel(job_id)
                st.rerun()


def _render_report_issue_workbench(job_id, state, view, artifacts):
    groups = view["groups"]
    counts = {
        severity: sum(1 for group in groups if group.get("severity") == severity)
        for severity in ("blocker", "warning", "human_review")
    }
    st.markdown(
        '<section class="tp-report-issues" aria-labelledby="report-issues-heading">'
        '<div class="tp-report-issues-head"><h3 id="report-issues-heading">当前问题</h3>'
        '<div class="tp-report-issues-summary">'
        f'<span class="is-blocker">阻塞项 {counts["blocker"]}</span>'
        f'<span class="is-warning">建议项 {counts["warning"]}</span>'
        f'<span class="is-human-review">人工判断 {counts["human_review"]}</span>'
        '</div></div></section>', unsafe_allow_html=True)
    focused_category = st.session_state.get(f"report_review_focus_{job_id}")
    if focused_category and any(
            group.get("category") == focused_category for group in groups):
        _render_report_issue_detail(job_id, state, groups, artifacts)
        return
    if not groups:
        st.markdown('<div class="tp-report-issues-empty">当前没有待处理的问题。</div>',
                    unsafe_allow_html=True)
        if view.get("gate_note"):
            st.warning(view["gate_note"])
        return
    if view["overall"] == "running":
        st.info("系统仍在运行。问题列表是最近一次检查结果，请等待当前步骤完成后再执行修复。")
    level_meta = {
        "blocker": ("阻塞项", "阻止交付"),
        "warning": ("建议项", "建议检查"),
        "human_review": ("人工判断", "需要人工判断"),
    }
    recommended = view.get("recommended_issue")
    for severity in ("blocker", "warning", "human_review"):
        level_groups = [group for group in groups if group.get("severity") == severity]
        if not level_groups:
            continue
        heading, note = level_meta[severity]
        st.markdown(
            f'<div class="tp-report-issues-group"><div class="tp-report-issues-group-title">'
            f'<h4>{heading}</h4><span>{note} · {len(level_groups)}</span></div></div>',
            unsafe_allow_html=True)
        for index, group in enumerate(level_groups):
            details = " ".join(group.get("details") or [])
            is_recommended = (group is recommended
                              and view["overall"] in {"blocked", "review_required"})
            recommended_marker = (
                '<span class="tp-report-issue-next">推荐下一步</span>'
                if is_recommended else "")
            with st.container(key=f"report_issue_row_{job_id}_{severity}_{index}"):
                issue_col, action_col = st.columns([4.8, 1.2], gap="small")
                with issue_col:
                    st.markdown(
                        f'<div class="tp-report-issue is-{severity}">'
                        f'<div class="tp-report-issue-badge">{heading}</div>'
                        f'<h4>{escape(group["category"])}</h4>'
                        f'<p>{escape(details)}</p>'
                        '<div class="tp-report-issue-meta">'
                        f'<span>影响范围</span><strong>{escape(group["impact"])}</strong>'
                        f'<span>下一步</span><strong>{escape(group["recommendation"])}</strong>'
                        '</div></div>', unsafe_allow_html=True)
                with action_col:
                    if is_recommended:
                        st.markdown(recommended_marker, unsafe_allow_html=True)
                    else:
                        with st.container(key=f"report_issue_row_action_{job_id}_{severity}_{index}"):
                            if st.button(group["action"], type="secondary", width="stretch",
                                         disabled=view["overall"] == "running",
                                         key=f"report_issue_button_{job_id}_{severity}_{index}"):
                                _open_report_issue(job_id, group)
                                st.rerun()
    _render_report_issue_detail(job_id, state, groups, artifacts)


def _render_report_recommended_action(job_id, view):
    issue = view.get("recommended_issue")
    if view["overall"] == "ready_for_delivery":
        title = "完成作者与 Word 最终复核" if view.get("final_review_pending") \
            else "进入交付并冻结最终版本"
        description = ("报告技术检查已完成，但两项人工终审仍需分别确认。"
                       if view.get("final_review_pending") else
                       "报告已通过当前验证，下一步是确认并生成不可变的最终交付版本。")
    elif view["overall"] in {"running", "failed"}:
        title = view["primary_cta"]
        description = ("查看当前阶段和运行日志，完成后再继续交付。"
                       if view["overall"] == "running"
                       else "查看失败原因并重试当前步骤，报告工作区会保留已完成产物。")
    elif issue:
        title = issue["action"]
        description = issue.get("recommendation") or "处理后会重新计算报告的交付状态。"
    else:
        title = view["primary_cta"]
        description = "查看运行详情，确认报告生成流程的下一步。"
    with st.container(key=f"report_recommended_{job_id}"):
        action_col, button_col = st.columns([3.2, 1], gap="small")
        with action_col:
            st.markdown(
                '<div class="tp-report-recommended-copy">'
                '<div class="tp-report-recommended-kicker">推荐下一步</div>'
                f'<h3>{escape(title)}</h3><p>{escape(description)}</p></div>',
                unsafe_allow_html=True)
        with button_col:
            if st.button(title, type="primary", width="stretch",
                         key=f"report_primary_{job_id}_{view['overall']}"):
                if issue and view["overall"] in {"blocked", "review_required"}:
                    _open_report_issue(job_id, issue)
                    if issue.get("target") in {"review", "runtime"}:
                        st.rerun()
                    _select_report_tab(job_id, "问题与修复")
                elif view["target_tab"] == "运行详情":
                    _select_report_tab(job_id, "运行详情")
                elif view["target_tab"] == "当前稿件":
                    _select_report_tab(job_id, "当前稿件")
                else:
                    st.session_state.workspace_section = "delivery"
                st.rerun()


def _render_report_draft(job_id, state, view, artifacts, report, headings):
    if not report:
        st.markdown('<div class="tp-empty">报告尚未生成。</div>', unsafe_allow_html=True)
        return
    template = core.load_report_template(job_id)
    template_summary = (template or {}).get("summary") or {}
    template_compliance = (view["validation"].get("template_compliance") or {}).get(
        "status", "not_configured")
    st.markdown("### 当前工作稿")
    if view["preview_only"]:
        st.warning("当前稿件仅供预览，尚不能用于最终交付。")
    else:
        st.success("当前稿件已通过验证，可以进入最终交付。")
    if not (artifacts.get("literature_sources") or {}).get("sources"):
        st.warning("正文结构与案例已完成，但学术文献支持尚未建立。")
    if template:
        st.caption(f"模板：{template_summary.get('filename') or '—'} · "
                   f"{template_summary.get('chapter_count', 0)} 章 / "
                   f"{template_summary.get('subsection_count', 0)} 节 · "
                   f"合规 {_report_validation_label(template_compliance)}")
    else:
        st.caption("未配置报告模板；当前 DOCX 使用通用排版。")
    st.caption("阅读模式 · 技术标记已隐藏")
    with st.container(key=f"report_actions_{job_id}"):
        action_a, action_b = st.columns([1.45, 1.2], gap="small")
        docx_data = _report_docx_bytes(state)
        filename = Path(str(state.get("filename") or "report")).stem or "report"
        draft_label = ("导出模板化 DOCX" if template else
                       "导出当前草稿 DOCX" if view["preview_only"] else "导出 DOCX")
        with action_a:
            if docx_data is None:
                blockers = "、".join(group["category"] for group in view["blocking"][:2])
                st.error(f"DOCX 暂不可导出：请先处理“问题与修复”中的{blockers or '阻塞项'}。")
            else:
                st.download_button(
                    draft_label, docx_data,
                    file_name=f"{filename}_翻译实践报告_草稿.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"report_docx_{job_id}", width="stretch")
        with action_b:
            st.download_button(
                "导出 Markdown", report.encode("utf-8"),
                file_name=f"{filename}_翻译实践报告_草稿.md", mime="text/markdown",
                key=f"report_markdown_{job_id}", width="stretch")
    if headings:
        outline_links = []
        for item in headings:
            css = "is-chapter" if item["level"] <= 2 else "is-subsection"
            outline_links.append(
                f'<a class="{css}" href="#{escape(item["anchor"])}">'
                f'{escape(item["title"])}</a>')
        st.markdown('<nav class="tp-report-outline" aria-label="报告目录">'
                    '<div class="tp-report-outline-title">报告目录</div>'
                    + "".join(outline_links) + '</nav>', unsafe_allow_html=True)
    st.markdown('<article class="tp-report-body">', unsafe_allow_html=True)
    st.markdown(_report_markdown_with_anchors(report, headings), unsafe_allow_html=True)
    st.markdown('</article>', unsafe_allow_html=True)


def _render_report_runtime_details(job_id, view, artifacts):
    runtime = view["runtime"]
    runtime_status = runtime.get("runtime_status") or runtime.get("status")
    if runtime_status in {"interrupted", "idle_incomplete", "cancelled"}:
        st.info("这次运行没有完成；已保存的报告产物仍然保留，可以从当前检查点继续。")
        if st.button("继续处理", type="primary", key=f"report_runtime_resume_{job_id}",
                     width="stretch"):
            _resume_job(job_id, core.load_job_state(job_id) or {})
            st.rerun()
    elif runtime_status in {"failed", "stalled"}:
        st.error("报告运行未完成。查看下方阶段和技术详情后，可以重试当前步骤。")
        if st.button("重试当前步骤", type="primary", key=f"report_runtime_retry_{job_id}",
                     width="stretch"):
            core.retry_job_step(job_id)
            _resume_job(job_id, core.load_job_state(job_id) or {})
            st.rerun()
    st.markdown("### 最近活动")
    events = runtime["user_events"]
    if events:
        for event in reversed(events):
            st.markdown(
                f'<div class="tp-runtime-event"><time>{escape(_runtime_clock(event.get("timestamp") or event.get("at")))}</time>'
                f'<span>{escape(event.get("message") or "")}</span></div>',
                unsafe_allow_html=True)
    else:
        st.caption("暂无运行活动。")
    st.markdown("### 运行阶段")
    completed, total = runtime["progress_completed"], runtime["progress_total"]
    if total:
        progress_pct = round(min(1.0, completed / total) * 100)
        st.markdown(
            f'<div class="tp-runtime-progress-head"><span>{escape(runtime["headline"])}</span>'
            f'<strong>{completed} / {total}</strong></div>'
            f'<div class="tp-runtime-bar"><i style="width:{progress_pct}%"></i></div>',
            unsafe_allow_html=True)
    else:
        st.caption(runtime["detail"] or "尚无可用的阶段进度。")
    with st.expander("技术详情与调试信息", expanded=False):
        raw = runtime["runtime"]
        worker = raw.get("worker") or {}
        st.caption(f"runtime status：{runtime['status']} · phase：{raw.get('phase') or '—'}")
        st.caption(f"worker id：{worker.get('worker_id') or '—'} · PID：{worker.get('owner_pid') or '—'}")
        st.caption(f"最后进展：{_runtime_clock(raw.get('last_progress_at'))} · "
                   f"最后心跳：{_runtime_clock(raw.get('last_heartbeat_at'))}")
        for label, artifact_name in (("验证产物", "validation"),
                                     ("语义复核", "review"),
                                     ("质量评估", "academic_quality"),
                                     ("最终 DOCX 验证", "final_docx_validation")):
            artifact = artifacts.get(artifact_name)
            if artifact:
                with st.expander(label, expanded=False):
                    st.json(artifact)
        technical_events = core.read_runtime_events(job_id, 12, visibility="technical")
        if technical_events:
            st.caption("技术日志")
            for event in reversed(technical_events):
                st.markdown(
                    f'<div class="tp-runtime-event"><time>{escape(_runtime_clock(event.get("timestamp") or event.get("at")))}</time>'
                    f'<span>{escape(event.get("event") or "")} · '
                    f'{escape(event.get("message") or "")}</span></div>',
                    unsafe_allow_html=True)


def _render_workspace_report(job_id, state):
    artifacts = _report_artifacts(job_id)
    view = _report_page_view(job_id, state, artifacts)
    report = _clean_report_for_display(state.get("p3_md"))
    headings = _report_headings(report)
    outline = artifacts.get("outline") or {}
    selected_cases = artifacts.get("selected_cases") or {}
    template = core.load_report_template(job_id)
    template_summary = (template or {}).get("summary") or {}
    compliance = (view["validation"].get("template_compliance") or {}).get(
        "status", "not_configured")
    chapter_count = template_summary.get("chapter_count") or sum(
        item["level"] == 2 for item in headings) or len(outline.get("sections") or [])
    subsection_count = template_summary.get("subsection_count") or sum(
        item["level"] > 2 for item in headings)
    if not report:
        chapter_count = subsection_count = 0
    case_portfolio = selected_cases.get("case_portfolio") or {}
    case_count = (len(selected_cases.get("cases") or [])
                  or int(case_portfolio.get("selected_case_count")
                         or len(case_portfolio.get("cases") or [])))
    issue_counts = {
        severity: sum(1 for group in view["groups"] if group.get("severity") == severity)
        for severity in ("blocker", "warning", "human_review")
    }
    chips = [
        ("章节", f"{chapter_count} 章 / {subsection_count} 节"),
        ("案例", f"{case_count} 个"),
        ("验证", _report_validation_label(view["validation"].get("status"))),
        ("阻塞项", str(issue_counts["blocker"])),
        ("交付", view["delivery_label"]),
    ]
    if template:
        chips.insert(2, ("模板", _report_validation_label(compliance)))
    chip_html = "".join(
        f'<span class="tp-report-meta-chip">{escape(label)} <strong>{escape(value)}</strong></span>'
        for label, value in chips)
    st.markdown(
        '<div class="tp-report-page-head"><div class="tp-section-kicker">报告工作区</div>'
        '<h2>报告</h2>'
        '<p class="tp-report-page-lead">先判断报告状态，再处理真正阻止交付的问题。</p>'
        f'<div class="tp-report-meta-chips">{chip_html}</div></div>',
        unsafe_allow_html=True)
    truth = core.translation_truth_view(job_id, state)
    st.markdown(
        '<div class="tp-truth-banner"><div><span class="tp-truth-kicker">报告输入依据</span>'
        '<strong>当前译文 — 报告证据的唯一来源</strong>'
        f'<p>报告中的译文证据来自工作译文 v{truth["version"]}；译文变更会使受影响的案例、写作单元和报告稿进入“需要更新”。</p>'
        '</div></div>', unsafe_allow_html=True)
    _render_report_status_card(job_id, view)
    impact = core.dependency_impact_view(job_id, state)
    if impact.get("status") == "stale":
        affected = impact.get("affected") or []
        reusable = impact.get("reusable") or []
        st.markdown(
            '<div class="tp-impact-panel"><strong>报告需要更新</strong>'
            f'<p>{escape(_workspace_impact_reason(impact))}</p>'
            '<div class="tp-impact-summary">'
            f'<div><span>发生了什么</span><strong>{escape(_workspace_impact_change_label(impact))}</strong></div>'
            f'<div><span>现在需要更新</span><strong>{len(affected)} 个下游产物</strong></div>'
            f'<div><span>仍可复用</span><strong>{len(reusable)} 个未受影响单元/资产</strong></div>'
            '</div></div>',
            unsafe_allow_html=True)
        _render_workspace_impact_expander(impact)
        if st.button("按影响范围继续重建", type="secondary",
                     key=f"report_targeted_rebuild_{job_id}",
                     disabled=not api_key, width="stretch"):
            _resume_job(job_id, state)
            st.rerun()
        if not api_key:
            st.caption("定点重建需要先在“设置”中配置当前模型 API Key；上方范围说明仍可用于人工核对。")
    tabs = st.tabs(["问题与修复", "当前稿件", "运行详情"],
                   default="问题与修复", key=f"report_tabs_{job_id}")
    with tabs[0]:
        _render_report_issue_workbench(job_id, state, view, artifacts)
        if not st.session_state.get(f"report_review_focus_{job_id}"):
            _render_report_recommended_action(job_id, view)
    with tabs[1]:
        _render_report_draft(job_id, state, view, artifacts, report, headings)
    with tabs[2]:
        _render_report_runtime_details(job_id, view, artifacts)


def _render_workspace_delivery(job_id, state):
    blockers = _delivery.unresolved_blocking(state)
    snapshot = core.delivery_snapshot_status(job_id, state)
    latest = snapshot.get("latest")
    report_ready = _delivery.report_ready(state)
    impact = core.dependency_impact_view(job_id, state)
    compliance = _workspace_compliance_view(job_id, state)
    compliance_counts = compliance.get("counts") or {}
    qa = _finalization.normalize_final_qa(state.get("final_qa"))
    finalization_qa_required = bool(state.get("report_enabled"))
    final_docx = core.load_academic_artifact(job_id, "final_docx_validation") or {}
    academic = state.get("academic_state") or {}
    final_export_status = _finalization._artifact_status_value(
        academic, "final_docx_validation")
    render_status = _finalization._artifact_status_value(
        academic, "libreoffice_render")
    report_status = _finalization._artifact_status_value(academic, "report")
    final_export_stale = final_export_status in {"stale", "missing", "failed"}
    render_stale = render_status in {"stale", "missing", "failed"}
    report_stale = report_status in {"stale", "missing", "failed"}
    structural = _workspace_structural_qa(job_id, state)
    qa_ready = (not finalization_qa_required or
                not report_stale and not final_export_stale and not render_stale and
                compliance.get("status") == "pass" and
                structural == "PASS" and
                qa.get("libreoffice_render") == "PASS" and
                qa.get("author_visual_review") == "CONFIRMED" and
                qa.get("word_final_review") == "CONFIRMED")
    case_views = _workspace_case_views(job_id, state)
    case_gate = _finalization.case_review_gate(
        state, core.load_academic_artifact(job_id, "selected_cases"))
    case_pending = case_gate.get("blocked_count", 0)
    case_stale = sum(1 for item in case_views if _case_review_is_stale(item, state))
    render_label = ("需要重建" if render_status == "stale" else
                    "失败" if render_status == "failed" else
                    "尚未运行" if render_status in {"missing", "not_available"} else
                    "已通过" if qa.get("libreoffice_render") == "PASS" else "尚未运行")
    render_detail = ("上一份页面预检通过；当前译文变化后需要重新运行" if render_status == "stale" else
                     "页面预检失败，需要查看失败原因" if render_status == "failed" else
                     "尚未生成页面预检结果" if render_status in {"missing", "not_available"} else
                     f"{qa.get('page_count') or '—'} 页 PDF 页面预检" if qa.get("libreoffice_render") == "PASS" else
                     "需要重新运行页面预检")
    translation_truth_gate_pass = (bool(state.get("p2_done")) and
                                   (state.get("delivery_validation") or {}).get("blocking") is not True)
    translation_gate_pass = translation_truth_gate_pass and not blockers
    report_draft_exists = bool(state.get("p3_md") or
                               core.load_academic_artifact(job_id, "report"))
    affected_count = len(impact.get("affected") or [])
    reusable_count = len(impact.get("reusable") or [])
    readiness = [
        ("当前译文真值", "通过" if translation_gate_pass else "需要处理",
         "交付门禁通过 · 0 个阻塞问题" if translation_gate_pass else
         f"还有 {len(blockers)} 个问题阻止继续交付",
         "pass" if translation_gate_pass else "warning"),
        ("学术产物同步", "需要更新" if (impact.get("status") == "stale" or
                                          report_stale or final_export_stale) else
         "已同步" if report_ready else "报告未完成",
         f"{affected_count} 项下游产物待重建" if impact.get("status") == "stale" else
         "报告或 DOCX 产物需要重新检查" if report_stale or final_export_stale else
         "报告与当前译文一致" if report_ready else
         "报告稿可预览，但尚未达到可交付状态" if report_draft_exists else
         "报告稿尚未生成",
         "warning" if impact.get("status") == "stale" or report_stale or
         final_export_stale or not report_ready else "pass"),
        ("案例复核", "需要重建" if case_stale else "待人工确认" if case_pending else
         "已确认" if case_views else "待生成",
         f"{case_stale} 个案例受译文变化影响" if case_stale else
         f"{case_pending} 个案例尚未完成终审" if case_pending else
         "案例均已完成终审" if case_views else "尚未生成案例选择产物",
         "warning" if case_stale or case_pending or not case_views else "pass"),
        ("合规检查", f"{compliance_counts.get('fail', 0)} 项失败" if compliance_counts.get("fail") else
         "需人工复核" if compliance_counts.get("manual_review") else "已通过",
         (f"{compliance_counts.get('manual_review', 0)} 项需要人工复核 · "
          f"{compliance_counts.get('not_checked', 0)} 项未检查")
         if compliance_counts.get("manual_review") or compliance_counts.get("not_checked") else
         "所有适用规则已通过" if compliance.get("status") == "pass" else "仍有规则需要确认",
         "warning" if compliance_counts.get("fail") or compliance_counts.get("manual_review") else "pass"),
        ("DOCX 结构检查", "已通过" if structural == "PASS" else
         "失败" if structural == "FAIL" else "需要重建" if structural == "STALE" else "尚未运行",
         "文档结构检查已保存" if structural == "PASS" else
         "上一份检查已通过；当前译文变化后需要重新检查" if structural == "STALE" else
         "需要先完成结构检查" if structural == "NOT_RUN" else "结构检查发现问题",
         "pass" if structural == "PASS" else "warning"),
        ("LibreOffice 页面渲染", render_label, render_detail,
         "warning" if render_status in {"stale", "missing", "failed", "not_available"} or
         qa.get("libreoffice_render") != "PASS" else "pass"),
        ("作者视觉复核", "已确认" if qa.get("author_visual_review") == "CONFIRMED" else "尚未确认",
         "作者已确认关键页面" if qa.get("author_visual_review") == "CONFIRMED" else "需要作者检查关键页面与版式",
         "pass" if qa.get("author_visual_review") == "CONFIRMED" else "warning"),
        ("Word 最终复核", "已确认" if qa.get("word_final_review") == "CONFIRMED" else "尚未确认",
         "Word 最终页面已确认" if qa.get("word_final_review") == "CONFIRMED" else "需要在 Word 更新字段并确认最终页面",
         "pass" if qa.get("word_final_review") == "CONFIRMED" else "warning"),
        ("冻结交付", f"已冻结交付 v{latest.get('snapshot_version')}"
         if snapshot.get("current") and latest else
         f"工作版本已偏离冻结交付 v{latest.get('snapshot_version')}"
         if snapshot.get("diverged") and latest else "尚未生成",
         f"冻结交付 v{latest.get('snapshot_version')} 可下载" if snapshot.get("current") and latest else
         f"v{latest.get('snapshot_version')} 保持不变；完成更新后可冻结新版本 v{int(latest.get('snapshot_version')) + 1}"
         if snapshot.get("diverged") and latest else
         "所有前置事实满足后再生成不可变版本",
         "pass" if snapshot.get("current") else "warning"),
    ]
    hard_gate_reasons = _workspace_hard_gate_reasons(job_id, state)
    delivery_state_label, delivery_state_tone = _workspace_delivery_state(job_id, state)
    if snapshot.get("current"):
        readiness_title = delivery_state_label
        readiness_summary = "当前冻结交付仍是可下载的不可变版本。"
    elif snapshot.get("diverged"):
        readiness_title = delivery_state_label
        readiness_summary = (f"冻结交付 v{latest.get('snapshot_version')} 保持不变；"
                             f"当前工作版本需要完成检查后，才能冻结为新版本 v{int(latest.get('snapshot_version')) + 1}。"
                             if latest else "当前工作版本与最近冻结交付不一致，需要重新检查后再冻结。")
    elif delivery_state_label == "可以冻结交付":
        readiness_title = "可以冻结交付"
        readiness_summary = "所有交付前置事实均已分别满足，可以生成冻结交付。"
    else:
        readiness_title = "暂不满足交付条件"
        summary_parts = []
        if translation_gate_pass:
            summary_parts.append("当前译文已通过交付门禁")
        if impact.get("status") == "stale":
            summary_parts.append("但受影响的报告产物仍需重建")
        if compliance_counts.get("fail"):
            summary_parts.append(f"{compliance_counts['fail']} 项合规检查失败")
        if compliance_counts.get("manual_review"):
            summary_parts.append(f"{compliance_counts['manual_review']} 项需要人工复核")
        if compliance_counts.get("not_checked"):
            summary_parts.append(f"{compliance_counts['not_checked']} 项尚未检查")
        if structural == "STALE":
            summary_parts.append("DOCX 结构检查需要重建")
        if render_stale:
            summary_parts.append("LibreOffice 页面预检需要重建")
        if qa.get("author_visual_review") != "CONFIRMED" and qa.get("word_final_review") != "CONFIRMED":
            summary_parts.append("作者视觉复核和 Word 最终复核尚未确认")
        elif qa.get("author_visual_review") != "CONFIRMED":
            summary_parts.append("作者视觉复核尚未确认")
        elif qa.get("word_final_review") != "CONFIRMED":
            summary_parts.append("Word 最终复核尚未确认")
        if case_pending and "案例" not in "".join(summary_parts):
            summary_parts.append(f"另有 {case_pending} 个案例待人工确认")
        readiness_summary = ("当前暂不满足交付条件；" + "；".join(summary_parts) + "。"
                             if summary_parts else "当前暂不满足交付条件；请查看各项准备状态。")
    st.markdown('<div class="tp-section-kicker">工作流最后一步</div><h2>最终交付</h2>'
                '<div class="tp-section-lead">先判断是否安全，再处理阻塞项；确认后才会生成不可变版本。</div>',
                unsafe_allow_html=True)
    flag_label = delivery_state_label
    st.markdown(
        f'<div class="tp-readiness-card is-{delivery_state_tone}"><div class="tp-readiness-kicker">交付判断</div>'
        f'<div class="tp-readiness-head"><div><h3>{escape(readiness_title)}</h3>'
        f'<p>{escape(readiness_summary)}</p></div><span class="tp-readiness-flag">{flag_label}</span></div>'
        '<div class="tp-readiness-grid">' + "".join(
            f'<div class="tp-readiness-item is-{tone}"><div class="tp-readiness-item-head">'
            f'<span class="tp-readiness-icon">{"✓" if tone == "pass" else "!"}</span>'
            f'<span class="tp-readiness-label">{escape(label)}</span></div>'
            f'<div class="tp-readiness-detail">{escape(detail)}</div>'
            f'<div class="tp-readiness-status">{escape(status)}</div></div>'
            for label, status, detail, tone in readiness) + '</div></div>',
        unsafe_allow_html=True)
    if impact.get("status") == "stale":
        next_title = "更新受影响的报告产物"
        next_detail = (f"先按影响范围重建 {affected_count} 项下游产物；"
                       f"{reusable_count} 个未受影响单元/资产仍可复用。")
        next_button = "按影响范围继续重建"
        next_target = "rebuild"
    elif compliance_counts.get("fail") or compliance_counts.get("manual_review"):
        next_title = "处理合规与人工复核"
        next_detail = "先在合规与 QA 中处理失败规则，再记录需要人工确认的项目。"
        next_button = "打开合规与 QA"
        next_target = "qa"
    elif not report_ready and state.get("report_enabled"):
        next_title = "完成报告"
        next_detail = "当前报告还不能作为最终学术产物交付。"
        next_button = "打开报告"
        next_target = "report"
    elif qa.get("author_visual_review") != "CONFIRMED" or qa.get("word_final_review") != "CONFIRMED":
        next_title = "完成最终人工复核"
        next_detail = "作者视觉复核和 Word 最终复核都必须分别记录。"
        next_button = "打开合规与 QA"
        next_target = "qa"
    elif snapshot.get("diverged") and latest:
        next_title = f"冻结为新版本 v{int(latest.get('snapshot_version')) + 1}"
        next_detail = (f"当前工作版本已偏离 v{latest.get('snapshot_version')}；"
                       "冻结会追加新版本，不会覆盖已有交付。")
        next_button = "回到冻结操作"
        next_target = "freeze"
    else:
        next_title = "生成冻结交付"
        next_detail = "前置检查已完成，确认后会生成不可变交付快照。"
        next_button = "回到冻结操作"
        next_target = "freeze"
    with st.container(key=f"delivery_next_action_{job_id}"):
        action_copy, action_button = st.columns([3.2, 1.15], gap="medium")
        with action_copy:
            st.markdown(f'<div class="tp-next-action-copy"><div class="tp-next-action-kicker">下一步</div>'
                        f'<strong>{escape(next_title)}</strong>'
                        f'<p>{escape(next_detail)}</p></div>', unsafe_allow_html=True)
        with action_button:
            if next_target == "rebuild":
                if st.button(next_button, type="primary", key=f"delivery_targeted_rebuild_{job_id}",
                             disabled=not api_key, width="stretch"):
                    _resume_job(job_id, state)
                    st.rerun()
            elif next_target == "qa":
                if st.button(next_button, type="primary", key=f"delivery_open_qa_{job_id}", width="stretch"):
                    st.session_state.workspace_section = "qa"
                    st.rerun()
            elif next_target == "report":
                if st.button(next_button, type="primary", key=f"delivery_open_report_{job_id}", width="stretch"):
                    st.session_state.workspace_section = "report"
                    st.rerun()
            else:
                st.caption("请使用下方冻结操作。")
    if next_target == "rebuild" and not api_key:
        st.caption("定点重建需要先在“设置”中配置当前模型 API Key；影响范围仍可用于人工核对。")
    with st.expander("查看技术依据", expanded=False):
        truth = core.translation_truth_view(job_id, state)
        st.caption(f'CURRENT_TRANSLATION · 当前工作译文 v{truth["version"]} · {truth["segment_count"]:,} 段')
        st.caption("交付文件和学术下游都以当前译文为输入；冻结交付另存为不可变快照。")
    if impact.get("status") == "stale":
        st.markdown(
            '<div class="tp-impact-panel"><strong>最近变更的影响</strong>'
            f'<p>{escape(_workspace_impact_reason(impact))}</p>'
            '<div class="tp-impact-summary">'
            f'<div><span>发生了什么</span><strong>{escape(_workspace_impact_change_label(impact))}</strong></div>'
            f'<div><span>现在需要更新</span><strong>{affected_count} 个下游产物</strong></div>'
            f'<div><span>仍可复用</span><strong>{reusable_count} 个未受影响单元/资产</strong></div>'
            '</div></div>', unsafe_allow_html=True)
        _render_workspace_impact_expander(impact)
    freeze_action = (f"冻结为新版本 v{int(latest.get('snapshot_version')) + 1}"
                     if latest else "确认并冻结最终版本")
    if blockers and hard_gate_reasons:
        st.error(f"还有 {len(blockers)} 个审校阻塞项；以下门禁不能通过“接受风险”跳过："
                 f"{'、'.join(dict.fromkeys(hard_gate_reasons))}。请先完成这些门禁。")
    elif blockers:
        st.warning(f"还有 {len(blockers)} 个审校阻塞项；这些项目可在人工检查后明确接受剩余风险。")
        accept = st.checkbox("我已检查这些审校问题，并确认接受剩余风险", key=f"workspace_delivery_accept_{job_id}")
        note = st.text_input("接受风险说明", key=f"workspace_delivery_note_{job_id}", placeholder="说明为什么可以接受…")
        risk_action = (f"接受风险并{freeze_action}" if latest
                       else "接受风险并冻结最终版本")
        if st.button(risk_action, type="primary",
                     disabled=not accept or not report_ready or not qa_ready,
                     key=f"workspace_delivery_accept_go_{job_id}", width="stretch"):
            _, ok, errors = core.approve_delivery(job_id, note or "人工确认并接受剩余风险",
                                                   accept_blocking=True, target_lang=target_lang,
                                                   provider=ai_provider, model=ai_model)
            if ok:
                st.rerun()
            for error in errors:
                st.error(error)
    elif not snapshot.get("current"):
        note = st.text_input("交付说明（可选）", key=f"workspace_delivery_final_note_{job_id}", placeholder="例如：已完成人工审校…")
        if st.button(freeze_action, type="primary",
                     disabled=not report_ready or not qa_ready,
                     key=f"workspace_delivery_final_{job_id}", width="stretch"):
            _, ok, errors = core.approve_delivery(job_id, note or "人工确认最终交付",
                                                   target_lang=target_lang, provider=ai_provider,
                                                   model=ai_model)
            if ok:
                st.rerun()
            for error in errors:
                st.error(error)
    else:
        st.success(f"最终交付版本 v{latest.get('snapshot_version')} 已冻结；后续工作版本变更不会修改它。")

    st.markdown('<div class="tp-section-label" style="margin-top:24px">版本历史</div>', unsafe_allow_html=True)
    snapshots = core.list_delivery_snapshots(job_id)
    if snapshots:
        st.markdown('<div class="tp-version-list">', unsafe_allow_html=True)
        filename = Path(str(state.get("filename") or "document")).stem or "document"
        for item in reversed(snapshots):
            approval = item.get("approval") or {}
            st.markdown(f'<div class="tp-version"><strong>v{item.get("snapshot_version")} · 已冻结</strong>'
                        f'<span>{escape(str(approval.get("timestamp") or item.get("created_at") or "—"))[:19]}</span></div>',
                        unsafe_allow_html=True)
            archive = core.delivery_snapshot_archive(job_id, item.get("snapshot_version"))
            if archive:
                st.download_button(f"下载最终交付版本 v{item.get('snapshot_version')}", archive,
                                   file_name=f"final_delivery_v{item.get('snapshot_version')}_{filename}.zip",
                                   mime="application/zip", key=f"workspace_snapshot_{job_id}_{item.get('snapshot_version')}",
                                   width="stretch")
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.caption("尚无冻结版本；确认后将从 v1 开始记录。")

    if not state.get("p2_done"):
        st.markdown('<div class="tp-empty">翻译完成后，交付文件会显示在这里。</div>', unsafe_allow_html=True)
        return
    frozen_assets = core.delivery_snapshot_assets(job_id, latest.get("snapshot_version")) \
        if snapshot.get("current") and latest else {}
    try:
        assets = frozen_assets or core.build_delivery_assets(job_id, state)
    except RuntimeError as exc:
        st.error(str(exc))
        for issue in (state.get("delivery_validation") or {}).get("issues") or []:
            st.warning(
                f"第 {int(issue.get('segment_index', -1)) + 1 if isinstance(issue.get('segment_index'), int) else '?'} 段："
                f"{issue.get('message', '译文未通过交付检查')}"
            )
        st.caption("当前工作稿已保留；修复问题后才能生成 DOCX、JSONL、TMX 和最终快照。")
        return
    labels = {
        "translation.docx": "纯译文", "bilingual.docx": "双语对照",
        "translation.pdf": "PDF 译文", "annotated_bilingual.docx": "重点标注版",
        "terms.xlsx": "术语表", "terms.tbx": "TBX 术语库",
        "memory.tmx": "TMX 翻译记忆", "bilingual.jsonl": "JSONL 双语段落",
        "segment_evidence.jsonl": "翻译过程证据",
        "selected_cases.json": "案例候选",
        "academic_workspace.zip": "学术写作工作区",
        "review_report.md": "审校报告", "report.docx": "实践报告 DOCX",
        "report.md": "实践报告 Markdown",
        "delivery_manifest.json": "Delivery Manifest",
        "stage1_cleaned.docx": "清洗后原文", "auto_terms.xlsx": "自动术语表",
        "stage2_bilingual.docx": "双语对照", "stage3_report.docx": "实践报告",
    }
    mime_by_suffix = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pdf": "application/pdf", ".tbx": "application/xml",
        ".tmx": "application/xml", ".json": "application/json",
        ".jsonl": "application/x-jsonlines", ".md": "text/markdown",
        ".zip": "application/zip",
    }
    st.markdown('<div class="tp-section-label" style="margin-top:24px">交付文件</div><div class="tp-asset-list">', unsafe_allow_html=True)
    for index, (key, data) in enumerate(assets.items()):
        label = labels.get(key, key)
        mime = mime_by_suffix.get(Path(key).suffix.lower(), "application/octet-stream")
        description = f"{key} · {_format_size(len(data))}"
        asset_col, action_col = st.columns([3, 1])
        with asset_col:
            st.markdown(f'<div class="tp-asset-row"><div class="tp-asset-copy"><strong>{escape(label)}</strong><span>{escape(description)}</span></div></div>', unsafe_allow_html=True)
        with action_col:
            if data is not None:
                st.download_button("下载" if key != "delivery_manifest.json" else "下载 manifest", data,
                                   file_name=key, mime=mime, key=f"workspace_asset_{job_id}_{index}", width="stretch")
            if key == "delivery_manifest.json" and data:
                with st.expander("查看 manifest", expanded=False):
                    try:
                        st.json(json.loads(data.decode("utf-8")))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        st.caption("manifest 当前不可预览。")
    st.markdown('</div>', unsafe_allow_html=True)


def _render_workspace_shell(job_id, state):
    if not state:
        _render_workspace_topbar(job_id or "", {"filename": "当前任务", "paras": [], "pairs": []})
        st.markdown('<div class="tp-empty">还没有打开的任务。请从历史任务或新建任务进入。</div>', unsafe_allow_html=True)
        return
    _render_workspace_topbar(job_id, state)
    section = st.session_state.get("workspace_section", "overview")
    if section not in {"overview", "translation", "terms", "review", "cases", "report", "qa", "delivery"}:
        section = "overview"
        st.session_state.workspace_section = section
    if section == "overview":
        nav_col, main_col = st.columns([0.82, 4.63], gap="small")
        with nav_col:
            with st.container(key="workspace_nav_col"):
                _render_workspace_nav(section, state, job_id)
        with main_col:
            with st.container(key="workspace_main_col"):
                _render_workspace_overview(job_id, state)
        return

    if section == "report":
        nav_col, main_col = st.columns([0.82, 4.63], gap="small")
        with nav_col:
            with st.container(key="workspace_nav_col"):
                _render_workspace_nav(section, state, job_id)
        with main_col:
            with st.container(key="workspace_main_col"):
                _render_workspace_report(job_id, state)
        return

    # Translation needs the widest center surface; the inspector stays a
    # compact, segment-driven utility column rather than a second dashboard.
    shell_ratios = [0.82, 3.35, 1.28] if section == "translation" else [0.82, 3.05, 1.58]
    nav_col, main_col, context_col = st.columns(shell_ratios, gap="small")
    with nav_col:
        with st.container(key="workspace_nav_col"):
            _render_workspace_nav(section, state, job_id)
    with main_col:
        with st.container(key="workspace_main_col"):
            if section == "translation":
                _render_workspace_translation(job_id, state)
            elif section == "terms":
                _render_workspace_terms(job_id, state)
            elif section == "review":
                _render_workspace_review(job_id, state)
            elif section == "cases":
                _render_workspace_cases(job_id, state)
            elif section == "report":
                _render_workspace_report(job_id, state)
            elif section == "qa":
                _render_workspace_qa(job_id, state)
            else:
                _render_workspace_delivery(job_id, state)
    with context_col:
        with st.container(key="workspace_context_col"):
            _render_workspace_context(job_id, state, section)


@st.fragment(run_every="3s")
def _render_live_workspace(job_id):
    """Poll the durable state without blocking the Streamlit render thread."""
    _render_workspace_shell(job_id, core.load_job_state(job_id) if job_id else None)

# ================= Product shell / state =================
providers = sorted(core.PROVIDERS, key=str.casefold)
default_provider = "DeepSeek" if "DeepSeek" in providers else providers[0]
ai_provider = st.session_state.get("provider_choice", default_provider)
if ai_provider not in core.PROVIDERS:
    ai_provider = default_provider
provider_cfg = core.PROVIDERS[ai_provider]
model_opts = sorted(provider_cfg.get("models") or [], key=str.casefold)
default_model = provider_cfg.get("default_model")
if default_model not in model_opts:
    default_model = model_opts[0] if model_opts else ""
ai_model = st.session_state.get(f"model_choice_{ai_provider}", default_model)
if model_opts and ai_model not in model_opts:
    ai_model = default_model
    st.session_state[f"model_choice_{ai_provider}"] = default_model
api_key = st.session_state.get(f"api_key_{ai_provider}", "")
api_base = st.session_state.get("custom_base_url", "") \
    if provider_cfg.get("custom_base_url") else None
reviewer_mode = st.session_state.get("reviewer_mode", "same")
reviewer_provider = st.session_state.get("reviewer_provider_choice", ai_provider)
if reviewer_provider not in core.PROVIDERS:
    reviewer_provider = ai_provider
reviewer_model = st.session_state.get("reviewer_model", "")
reviewer_api_key = st.session_state.get("reviewer_api_key", "")
reviewer_base_url = st.session_state.get("reviewer_base_url", "")
saved_jobs = core.list_jobs()
app_view = st.session_state.get("app_view", "new")
workspace_mode = st.session_state.get("workspace_mode", False)

with st.sidebar:
    st.markdown(
                '<div class="tp-brand" aria-label="TransPraxis 译践">'
                f'<img class="tp-brand-mark" src="{_BRAND_MARK_URI}" alt="">'
                '<div class="tp-brand-copy"><strong>TransPraxis</strong><b>译践</b></div>'
                '<span>Translation Practice Workspace</span></div>',
                unsafe_allow_html=True)
    with st.container(key="new_task_action"):
        if st.button("新建任务", icon=":material/add:", width="stretch"):
            st.session_state.update(app_view="new", workspace_mode=False, task_step=1)
            st.rerun()
    if workspace_mode or st.session_state.get("active_job_id"):
        if st.button("当前任务", width="stretch", type="primary" if app_view == "workspace" else "secondary"):
            st.session_state.app_view = "workspace"
            st.rerun()
    if app_view == "new" and not workspace_mode:
        st.markdown('<div class="tp-nav-divider"></div>'
                    '<div class="tp-nav-label">当前任务</div>', unsafe_allow_html=True)
        with st.container(key="task_steps"):
            current_step = st.session_state.task_step
            for number, label in ((1, "文档与画像"), (2, "翻译策略"),
                                  (3, "交付内容"), (4, "确认运行")):
                status = "done" if number < current_step else "current" if number == current_step else "pending"
                icon = ":material/check_circle:" if status == "done" \
                    else ":material/radio_button_checked:" if status == "current" \
                    else ":material/radio_button_unchecked:"
                if st.button(f"{number:02d}  {label}", icon=icon,
                             key=f"task_step_{status}_{number}", width="stretch",
                             type="primary" if status == "current" else "secondary"):
                    _request_step(number)
                    st.rerun()
    st.markdown('<div class="tp-nav-label">资料库</div>', unsafe_allow_html=True)
    with st.container(key="library_nav"):
        if st.button("历史任务", icon=":material/history:", width="stretch",
                     type="primary" if app_view == "history" else "secondary"):
            st.session_state.app_view = "history"
            st.rerun()
        if st.button("术语库与记忆", icon=":material/menu_book:", width="stretch",
                     type="primary" if app_view == "library" else "secondary"):
            st.session_state.app_view = "library"
            st.rerun()
        if st.button("设置", icon=":material/settings:", width="stretch",
                     type="primary" if app_view == "settings" else "secondary"):
            st.session_state.app_view = "settings"
            st.rerun()
    with st.container(key="provider_status"):
        provider_col, manage_col = st.columns([3, 1])
        connection_status = st.session_state.get("provider_connection_status", "unverified")
        provider_col.markdown(f'<div class="tp-provider is-{connection_status}">'
                              f'<strong>{escape(str(ai_provider))}</strong>'
                              f'<span>{escape(str(ai_model or "未配置模型"))}</span></div>',
                              unsafe_allow_html=True)
        if manage_col.button("管理", key="manage_provider"):
            st.session_state.app_view = "settings"
            st.rerun()

# Pipeline defaults; preset is a template and strategy_config is the effective configuration.
preset_label = st.session_state.get("translation_preset", "标准")
if preset_label not in _PRESET_CONFIGS:
    preset_label = "标准"
if "strategy_config" not in st.session_state:
    st.session_state.strategy_config = dict(_PRESET_CONFIGS[preset_label])
if "output_config" not in st.session_state:
    st.session_state.output_config = dict(_PRESET_OUTPUTS[preset_label])
strategy_config = st.session_state.strategy_config
output_config = st.session_state.output_config
auto_term = strategy_config["auto_term"]
use_tm = strategy_config["use_tm"]
enable_review = strategy_config["enable_review"]
strict_terminology_governance = strategy_config["strict_terminology_governance"]
enable_annotate = output_config["enable_annotate"]
enable_report = output_config["enable_report"]
target_lang = st.session_state.get("target_lang", "简体中文")
user_glossary = st.session_state.get("task_glossary", [])
uploaded_files = []
run_clicked = False
resume_choice = None
job_choices = [f"{j['state'].get('filename', '?')} {core.progress_label(j['state'])}"
               for j in saved_jobs]
style_rules = st.session_state.get(
    "style_rules", "保持学术书面语；专有名词、作者姓名、机构名、引用标注、URL 等保留原文；标点遵循目标语言规范。")
annotation_colors = st.session_state.get("annotation_colors", {
    "rare": "C00000", "domain": "BF8F00", "hard": "008080"})
theory_choice = st.session_state.get("translation_theory_choice", "自动推荐（建议）")
if theory_choice == "自定义":
    translation_theory = st.session_state.get("custom_translation_theory", "").strip() \
        or "自定义理论框架"
elif theory_choice in ("自动推荐", "自动推荐（建议）"):
    translation_theory = "基于文本特征、案例证据与可用文献自动推荐理论框架"
else:
    translation_theory = theory_choice
_uploaded_literature = st.session_state.get("literature_upload_sources") or []
_registry_literature = st.session_state.get("literature_registry_sources")
if _registry_literature is None:
    _registry_literature = st.session_state.get("literature_sources") or []
literature_sources = [*_uploaded_literature, *_registry_literature] or None
research_settings = st.session_state.get("research_settings", {
    "target_words": 4200, "body_language": "zh-CN",
    "case_selection_policy": "mixed", "report_stage": "final_report",
    "analysis_dimensions": ["文本特征", "术语管理", "翻译策略", "译后编辑与质量控制"],
})
research_settings = dict(research_settings)
template_input = st.session_state.get("report_template_input")
if template_input:
    research_settings["report_template_contract"] = template_input.get("contract")
elif st.session_state.get("report_template_removed"):
    research_settings.pop("report_template_contract", None)


def _pipeline_kwargs(state=None):
    """Build the current UI configuration for a new or resumed worker."""
    state = state if isinstance(state, dict) else {}
    saved = state.get("pipeline_config") or {}
    academic_state = state.get("academic_state") or {}
    persisted = bool(saved or state.get("p1_done") or state.get("p2_done")
                     or academic_state.get("artifacts"))
    resume_report = saved.get("enable_report") if saved else \
        state.get("report_enabled", enable_report) if persisted else enable_report
    if state and (academic_state.get("artifacts") or academic_state.get(
            "current_stage") not in {None, "", "not_started"}):
        resume_report = True
    resume_annotate = saved.get("enable_annotate") if "enable_annotate" in saved \
        else state.get("enable_annotate", enable_annotate) if persisted else enable_annotate
    delivery = state.get("delivery_config") or output_config
    delivery = core.normalize_delivery_config(
        delivery, enable_report=resume_report, enable_annotate=resume_annotate)
    understanding_default = strategy_config.get("enable_understanding", True)
    if persisted and "enable_understanding" not in saved:
        understanding_default = bool(
            state.get("profile_done") or state.get("understanding_done")
            or state.get("quality_mode"))
    return {
        "provider": ai_provider,
        "api_key": api_key,
        "model": ai_model,
        "target_lang": saved.get("target_lang") or state.get("target_lang") or target_lang,
        "auto_term": saved.get("auto_term", auto_term),
        "enable_report": bool(resume_report),
        "translation_theory": saved.get("translation_theory") or
        state.get("theory") or translation_theory,
        "user_glossary": state.get("glossary") or user_glossary,
        "style_rules": saved.get("style_rules", style_rules),
        "enable_review": saved.get("enable_review", enable_review),
        "enable_annotate": bool(resume_annotate),
        "use_tm": saved.get("use_tm", use_tm),
        "enable_understanding": saved.get(
            "enable_understanding", understanding_default),
        "translator_base_url": api_base,
        "strict_terminology_governance": saved.get(
            "strict_terminology_governance", state.get(
                "quality_mode", strict_terminology_governance)),
        **({
            "reviewer_provider": reviewer_provider,
            "reviewer_model": reviewer_model,
            "reviewer_api_key": reviewer_api_key,
            "reviewer_base_url": reviewer_base_url,
        } if reviewer_mode == "separate" else {}),
        "research_settings": state.get("research_settings") or research_settings,
        "literature_sources": state.get("literature_sources") or literature_sources,
        "delivery_config": delivery,
    }


def _resume_job(job_id, state):
    return core.resume_job(
        job_id, state.get("filename") or "当前任务",
        _pipeline_kwargs(state), base_url=api_base)

# ================= Main views =================
setup_placeholder = st.empty()
with setup_placeholder.container():
    if app_view == "settings":
        _page_title("AI 引擎", "配置一次，所有新任务自动使用当前连接")
        if not core.is_onboarded():
            st.caption("首次使用：选择服务商 → 填写 API 密钥与模型 → 保存配置 → 点击「测试连接」通过后即可开始翻译。")
        pc1, pc2 = st.columns(2)
        ai_provider = pc1.selectbox("服务商", providers,
                                    index=providers.index(ai_provider), key="provider_choice",
                                    on_change=_reset_provider_connection,
                                    **_PERSIST_STATE)
        provider_cfg = core.PROVIDERS[ai_provider]
        model_opts = sorted(provider_cfg.get("models") or [], key=str.casefold)
        fetched_models = sorted(
            set(st.session_state.get(f"fetched_models_{ai_provider}") or []),
            key=str.casefold)
        if model_opts:
            default_model = provider_cfg.get("default_model")
            if default_model not in model_opts:
                default_model = model_opts[0]
            model_key = f"model_choice_{ai_provider}"
            if st.session_state.get(model_key, default_model) not in model_opts:
                st.session_state[model_key] = default_model
            ai_model = pc2.selectbox("模型", model_opts,
                                     index=model_opts.index(st.session_state.get(
                                         model_key, default_model)),
                                     key=model_key,
                                     on_change=_reset_provider_connection,
                                     **_PERSIST_STATE)
        elif fetched_models:
            model_key = f"fetched_model_choice_{ai_provider}"
            preferred_key = f"preferred_fetched_model_{ai_provider}"
            current_model = st.session_state.get(
                model_key, st.session_state.get(
                    preferred_key, st.session_state.get(f"model_choice_{ai_provider}")))
            if current_model not in fetched_models:
                current_model = fetched_models[0]
            ai_model = pc2.selectbox(
                "模型", fetched_models,
                index=fetched_models.index(current_model), key=model_key,
                on_change=_reset_provider_connection, args=(True,),
                **_PERSIST_STATE)
            st.session_state[f"model_choice_{ai_provider}"] = ai_model
        else:
            ai_model = pc2.text_input("模型", key=f"model_choice_{ai_provider}",
                                     placeholder=provider_cfg.get("model_hint") or "model-name",
                                     on_change=_reset_provider_connection,
                                     **_PERSIST_STATE)
        api_key = st.text_input("API 密钥", type="password", key=f"api_key_{ai_provider}",
                                on_change=_reset_provider_connection,
                                **_PERSIST_STATE)
        if provider_cfg.get("custom_base_url"):
            api_base = st.text_input("API 地址", key="custom_base_url",
                                     placeholder="https://your-relay.example.com/v1",
                                     on_change=_reset_provider_connection,
                                     **_PERSIST_STATE)
        else:
            api_base = None
        st.markdown("### 独立审校模型（可选）")
        reviewer_mode = st.radio(
            "审校模型",
            ["same", "separate"],
            index=0 if st.session_state.get("reviewer_mode", "same") == "same" else 1,
            format_func=lambda value: "与翻译模型相同" if value == "same" else "单独配置",
            key="reviewer_mode",
            horizontal=True,
            **_PERSIST_STATE,
        )
        if reviewer_mode == "separate":
            reviewer_provider = st.selectbox(
                "审校服务商", providers,
                index=providers.index(st.session_state.get(
                    "reviewer_provider_choice", ai_provider))
                if st.session_state.get("reviewer_provider_choice", ai_provider) in providers
                else providers.index(ai_provider),
                key="reviewer_provider_choice",
                **_PERSIST_STATE,
            )
            reviewer_model = st.text_input(
                "审校模型", key="reviewer_model",
                placeholder="例如 gpt-4.1-mini",
                **_PERSIST_STATE,
            )
            reviewer_api_key = st.text_input(
                "审校 API 密钥", type="password", key="reviewer_api_key",
                **_PERSIST_STATE,
            )
            reviewer_base_url = st.text_input(
                "审校 API 地址（可选）", key="reviewer_base_url",
                placeholder="留空使用服务商默认地址",
                **_PERSIST_STATE,
            )
        else:
            reviewer_provider = ai_provider
            reviewer_model = ""
            reviewer_api_key = ""
            reviewer_base_url = ""
        can_fetch_models = provider_cfg.get("kind") in ("openai", "openai_compat") \
            and (provider_cfg.get("custom_base_url") or not model_opts)
        if can_fetch_models:
            fetch_base = api_base or provider_cfg.get("base_url")
            if st.button("获取可用模型", width="stretch",
                         disabled=not (api_key and fetch_base),
                         help="从 OpenAI 兼容接口的 /models 目录读取可用模型"):
                with st.spinner("正在获取模型目录…"):
                    ok, fetched, msg = core.fetch_provider_models(
                        ai_provider, api_key, base_url=fetch_base)
                if ok:
                    st.session_state[f"fetched_models_{ai_provider}"] = fetched
                    selected = st.session_state.get(f"model_choice_{ai_provider}")
                    if selected not in fetched:
                        selected = fetched[0]
                    st.session_state[f"preferred_fetched_model_{ai_provider}"] = selected
                else:
                    st.session_state.pop(f"fetched_models_{ai_provider}", None)
                st.session_state.model_fetch_feedback = (ok, msg)
                st.rerun()
            if feedback := st.session_state.get("model_fetch_feedback"):
                ok, msg = feedback
                (st.success if ok else st.error)(msg)
        display_base = api_base or provider_cfg.get("base_url") or "由服务商管理"
        st.caption(f"接口地址：{display_base}")
        save_ready = bool(api_key and ai_model) and (
            reviewer_mode == "same"
            or bool(reviewer_provider and reviewer_model and reviewer_api_key)
        )
        save_btn, test_btn = st.columns(2)
        with save_btn:
            if st.button("保存配置", width="stretch",
                         disabled=not save_ready,
                         help="把服务商、模型与 API 密钥写入本地，重启应用后仍会保留"):
                core.save_provider_config(
                    ai_provider, ai_model, api_key, api_base,
                    reviewer=(
                        {"provider": reviewer_provider, "model": reviewer_model,
                         "api_key": reviewer_api_key, "base_url": reviewer_base_url}
                        if reviewer_mode == "separate" else None
                    ),
                )
                st.toast("AI 引擎配置已保存，重启应用后仍会保留")
        with test_btn:
            if st.button("测试连接", type="primary", width="stretch",
                         disabled=not (api_key and ai_model)):
                with st.spinner("正在验证连接…"):
                    ok, msg = core.test_provider(ai_provider, api_key,
                                                 ai_model, base_url=api_base)
                if ok:
                    core.mark_onboarded()
                st.session_state.provider_configured = ok
                st.session_state.provider_connection_status = \
                    "connected" if ok else "error"
                st.session_state.provider_test_feedback = (ok, msg)
                st.rerun()
        if feedback := st.session_state.get("provider_test_feedback"):
            ok, msg = feedback
            (st.success if ok else st.error)(msg)

    elif app_view == "new" and not workspace_mode:
        _page_title("新建翻译任务", "上传文档并配置翻译工作流")
        step = st.session_state.task_step
        if not core.is_onboarded() \
                and not st.session_state.get("onboarding_dismissed") \
                and not api_key:
            with st.container(key="onboarding_guide"):
                guide_col, action_col = st.columns([3, 1])
                guide_col.markdown(
                    '<div class="tp-onboard-card">'
                    '<div class="tp-style-card-head">'
                    '<span class="material-symbols-rounded" aria-hidden="true">rocket_launch</span>'
                    '<strong>首次使用 TransPraxis</strong></div>'
                    '<p>配置 AI 引擎后即可开始翻译。三步完成：</p>'
                    '<ol><li>选择服务商（DeepSeek / OpenAI / Gemini / 中转站…）</li>'
                    '<li>填写 API 密钥并选择模型</li>'
                    '<li>点击「测试连接」验证通过</li></ol></div>',
                    unsafe_allow_html=True)
                with action_col:
                    if st.button("前往设置", key="goto_settings_onboard",
                                 type="primary", width="stretch"):
                        st.session_state.app_view = "settings"
                        st.rerun()
                    if st.button("暂不配置", key="dismiss_onboarding",
                                 width="stretch"):
                        st.session_state.onboarding_dismissed = True
                        st.rerun()

        if step == 1:
            _step_title(1, "文档", "配置本次翻译任务的输入材料")
            if gate_message := st.session_state.pop("step_gate_message", None):
                st.warning(gate_message, icon=":material/info:")
            task_files = st.session_state.get("task_files") or []
            if task_files:
                first_job = core.load_job_state(core.file_job_id(task_files[0]["bytes"]))
                if first_job and first_job.get("p1_done"):
                    st.session_state.source_parse_state = "parsed"
                    if first_job.get("source_page_count"):
                        task_files[0]["pages"] = first_job["source_page_count"]
                with st.container(key="source_file_summary"):
                    st.markdown('<div class="tp-source-label">原文</div>',
                                unsafe_allow_html=True)
                    with st.container(key="source_file_card"):
                        st.markdown(_source_file_html(task_files), unsafe_allow_html=True)
                        st.button("移除原文", icon=":material/delete_outline:",
                                  key="remove_source", help="移除原文",
                                  on_click=_remove_source_documents)
            else:
                with st.container(key="source_documents"):
                    st.markdown('<div class="tp-source-label">原文</div>'
                                '<div class="tp-upload-copy">'
                                '<span class="material-symbols-rounded" aria-hidden="true">upload_file</span>'
                                '<span>拖入文件或点击选择</span>'
                                '<small>支持 PDF、DOCX · 单文件最大 200 MB</small></div>',
                                unsafe_allow_html=True)
                    uploaded_files = st.file_uploader("原文", type=["pdf", "docx"],
                                                      accept_multiple_files=True,
                                                      key=f"source_documents_"
                                                          f"{st.session_state.get('source_uploader_generation', 0)}",
                                                      label_visibility="collapsed",
                                                      help="支持 PDF 和 DOCX，可一次添加多个文件")
                if uploaded_files:
                    st.session_state.task_files = [
                        {"name": f.name, "bytes": f.getvalue()} for f in uploaded_files
                    ]
                    st.session_state.source_parse_state = "uploaded"
                    st.rerun()
            with st.container(key="target_language_field"):
                target_lang = st.selectbox(
                    "目标语言", ["简体中文", "繁体中文", "English", "日本語", "한국어",
                    "Deutsch", "Français", "Español", "Русский", "Português",
                                 "Italiano", "العربية"], key="target_lang",
                    **_PERSIST_STATE)
            term_label = st.session_state.get("task_glossary_name", "未添加")
            st.markdown('<div class="tp-field-head"><strong>术语库</strong>'
                        '<span>可选 · 用于保持术语与专名一致</span></div>',
                        unsafe_allow_html=True)
            if term_label == "未添加":
                with st.container(key="termbase_attach"):
                    if st.button("添加术语库", icon=":material/attach_file:",
                                 key="add_termbase"):
                        st.session_state.show_termbase_picker = True
                        st.rerun()
            else:
                with st.container(key="termbase_attached"):
                    attached_col, remove_col = st.columns([4, 1])
                    count = st.session_state.get("task_glossary_count")
                    count_text = f"{count:,} 条术语" if count is not None else "已添加"
                    attached_col.markdown(
                        f'<div class="tp-attachment"><div><strong>'
                        f'{escape(str(term_label))}</strong>'
                        f'<span>{count_text}</span></div></div>', unsafe_allow_html=True)
                    remove_col.button("移除", key="remove_termbase",
                                      on_click=_remove_task_termbase, width="stretch")
            if st.session_state.get("show_termbase_picker") and term_label == "未添加":
                with st.container(key="termbase_picker"):
                    termbase_file = st.file_uploader(
                        "选择术语库文件", type=["xlsx", "csv", "tbx", "tmx"],
                        help="支持 Trados / memoQ 常用的 TBX、TMX，以及 Excel、CSV")
                if termbase_file:
                    try:
                        if termbase_file.name.lower().endswith(".tmx"):
                            result = core.import_tmx(termbase_file)
                            st.session_state.task_glossary = []
                            st.session_state.task_glossary_count = result["added"]
                            st.success(f"已并入翻译记忆 {result['added']} 条")
                        else:
                            parser = core.parse_termbase if termbase_file.name.lower().endswith(".xlsx") \
                                else core.parse_termbase_csv if termbase_file.name.lower().endswith(".csv") \
                                else core.parse_termbase_tbx
                            st.session_state.task_glossary = parser(termbase_file)
                            st.session_state.task_glossary_count = len(st.session_state.task_glossary)
                            st.success(f"已添加 {len(st.session_state.task_glossary)} 条参考术语")
                            st.session_state.task_glossary_name = termbase_file.name
                        st.session_state.show_termbase_picker = False
                        st.rerun()
                    except ValueError as exc:
                        st.warning(str(exc))
            # Keep the current custom relay available to quick profiling, which
            # can run before the rest of the page reaches the pipeline setup.
            core.set_llm_base_url(api_base if provider_cfg.get("custom_base_url") else None)
            if task_files:
                _render_style_profile_section()
            _render_task_actions(next_step=2,
                                 next_disabled=not st.session_state.get("task_files"))

        elif step == 2:
            _step_title(2, "翻译策略", "选择适合本次任务的工作流；需要时可调整高级设置")
            with st.container(key="preset_cards"):
                preset_columns = st.columns(3)
                for column, label in zip(preset_columns, _PRESET_CONFIGS):
                    state = "selected" if label == preset_label else "idle"
                    with column.container(key=f"preset_card_{label}_{state}"):
                        st.markdown(_preset_card_html(label), unsafe_allow_html=True)
                        if st.button(f"选择{label}预设", key=f"choose_preset_{label}"):
                            _apply_preset(label)
                            st.toast(f"已恢复“{label}”预设")
                            st.rerun()
            strategy_config = st.session_state.strategy_config
            adjusted = _strategy_is_adjusted(preset_label, strategy_config)
            with st.container(key="strategy_advanced"):
                advanced_open = st.session_state.get("strategy_advanced_open", False)
                state_text = f'<strong>{preset_label} · 已调整</strong>' if adjusted \
                    else f'当前使用「{preset_label}」默认配置'
                trigger_icon = "expand_less" if advanced_open else "chevron_right"
                st.markdown(
                    '<div class="tp-advanced-trigger">'
                    '<span class="tp-advanced-title">'
                    f'<span class="material-symbols-rounded" aria-hidden="true">'
                    f'{trigger_icon}</span><strong>高级设置</strong></span></div>',
                    unsafe_allow_html=True)
                st.button("切换高级设置", key="toggle_strategy_advanced",
                          on_click=_toggle_advanced_strategy, width="stretch")
                if advanced_open:
                    with st.container(key="advanced_body"):
                        st.markdown(f'<div class="tp-strategy-state">{state_text}</div>',
                                    unsafe_allow_html=True)
                        st.markdown('<div class="tp-advanced-group">翻译辅助</div>',
                                    unsafe_allow_html=True)
                        _render_strategy_toggle(
                            "自动术语抽取", "从全文识别候选术语并用于翻译",
                            "auto_term", "strategy_auto_term", strategy_config)
                        _render_strategy_toggle(
                            "全文文档理解", "建立文档画像、语义单元、章节摘要和全文概要",
                            "enable_understanding", "strategy_understanding", strategy_config)
                        _render_strategy_toggle(
                            "复用翻译记忆", "精确复用已审校通过的历史译文",
                            "use_tm", "strategy_use_tm", strategy_config)
                        st.markdown('<div class="tp-advanced-group">质量控制</div>',
                                    unsafe_allow_html=True)
                        st.markdown(
                            '<div class="tp-readonly-setting">'
                            '<div class="tp-readonly-head">'
                            '<strong>基础一致性检查</strong><b>始终开启</b></div>'
                            '<span>自动检查漏译、保留项、源语残留和锁定术语</span>'
                            '</div>', unsafe_allow_html=True)
                        _render_strategy_toggle(
                            "独立审校", "使用独立模型阶段复核语义与术语，并保存审校证据",
                            "enable_review", "strategy_review", strategy_config)
                        st.markdown('<div class="tp-advanced-group">术语治理</div>',
                                    unsafe_allow_html=True)
                        _render_strategy_toggle(
                            "审核并冻结候选术语", "翻译前建立文档画像，并审核自动提取的候选术语",
                            "strict_terminology_governance", "strategy_strict_terms",
                            strategy_config)
            _render_task_actions(back_step=1, next_step=3)

        elif step == 3:
            _step_title(3, "交付内容", "选择要生成的文件与附加成果")
            output_config = st.session_state.output_config
            with st.container(key="deliver_translation"):
                st.markdown('<div class="tp-output-section-head"><strong>译文</strong>'
                            '<span>选择要生成的译文文件</span></div>',
                            unsafe_allow_html=True)
                trans_a, trans_b = st.columns(2)
                with trans_a:
                    st.checkbox(
                        "纯译文 DOCX",
                        value=output_config.get("deliver_plain_docx", True),
                        key="deliver_plain_docx", on_change=_set_output_option,
                        args=("deliver_plain_docx", "deliver_plain_docx"),
                        help="仅含译文的 Word 文档", **_PERSIST_STATE)
                    st.checkbox(
                        "双语对照 DOCX",
                        value=output_config.get("deliver_bilingual_docx", True),
                        key="deliver_bilingual_docx", on_change=_set_output_option,
                        args=("deliver_bilingual_docx", "deliver_bilingual_docx"),
                        help="原文与译文对照的 Word 文档", **_PERSIST_STATE)
                with trans_b:
                    st.checkbox(
                        "PDF 译文", value=output_config.get("deliver_pdf", False),
                        key="deliver_pdf", on_change=_set_output_option,
                        args=("deliver_pdf", "deliver_pdf"),
                        help="将译文导出为 PDF", **_PERSIST_STATE)
                    st.toggle("重点标注版", value=output_config["enable_annotate"],
                              key="output_annotate", on_change=_set_output_option,
                              args=("enable_annotate", "output_annotate"),
                              help="在双语文档中标出生僻词、专业术语和翻译难点句",
                              **_PERSIST_STATE)
                st.caption("重点标注版在双语文档中标出生僻词、专业术语和翻译难点句")
            with st.container(key="deliver_assets"):
                st.markdown('<div class="tp-output-section-head"><strong>语言资产</strong>'
                            '<span>术语与翻译记忆的导出格式</span></div>',
                            unsafe_allow_html=True)
                asset_a, asset_b = st.columns(2)
                with asset_a:
                    st.checkbox(
                        "术语表 XLSX",
                        value=output_config.get("deliver_terms_xlsx", True),
                        key="deliver_terms_xlsx", on_change=_set_output_option,
                        args=("deliver_terms_xlsx", "deliver_terms_xlsx"),
                        help="自动抽取与锁定术语的 Excel 表", **_PERSIST_STATE)
                    st.checkbox(
                        "TBX", value=output_config.get("deliver_tbx", False),
                        key="deliver_tbx", on_change=_set_output_option,
                        args=("deliver_tbx", "deliver_tbx"),
                        help="ISO 标准术语交换格式", **_PERSIST_STATE)
                with asset_b:
                    st.checkbox(
                        "TMX", value=output_config.get("deliver_tmx", False),
                        key="deliver_tmx", on_change=_set_output_option,
                        args=("deliver_tmx", "deliver_tmx"),
                        help="翻译记忆交换格式", **_PERSIST_STATE)
                    st.checkbox(
                        "JSONL", value=output_config.get("deliver_jsonl", False),
                        key="deliver_jsonl", on_change=_set_output_option,
                        args=("deliver_jsonl", "deliver_jsonl"),
                        help="双语段落 JSONL，便于后续处理", **_PERSIST_STATE)
            enable_annotate = output_config["enable_annotate"]
            with st.container(key="deliver_academic"):
                st.markdown('<div class="tp-output-section-head"><strong>研究资产</strong>'
                            '<span>学术增强模式的过程证据与写作产物</span></div>',
                            unsafe_allow_html=True)
                st.toggle("生成实践报告", value=output_config["enable_report"],
                          key="output_report", on_change=_set_output_option,
                          args=("enable_report", "output_report"),
                          help="启动证据约束的学术写作工作流",
                          **_PERSIST_STATE)
                st.caption("仅使用可追溯案例、项目数据与已导入文献证据")
                enable_report = output_config["enable_report"]
                if enable_report:
                    theory_choice = st.selectbox("理论框架", [
                        "自动推荐（建议）", "目的论 (Skopos Theory)",
                        "交际翻译与语义翻译 (Newmark)", "功能对等理论 (Nida)",
                        "文本类型理论 (Reiss)", "生态翻译学 (Hu Gengshen)",
                        "自定义"], key="translation_theory_choice",
                        **_PERSIST_STATE)
                    st.caption("根据文本特征、案例证据与可用文献确定；仅在证据支持时使用。")
                    if theory_choice == "自定义":
                        custom_theory = st.text_input(
                            "自定义理论框架", key="custom_translation_theory",
                            placeholder="输入理论名称或分析框架")
                        translation_theory = custom_theory.strip() or "自定义理论框架"
                    elif theory_choice == "自动推荐（建议）":
                        translation_theory = \
                            "基于文本特征、案例证据与可用文献自动推荐理论框架"
                    else:
                        translation_theory = theory_choice
                    with st.container(key="report_template_inputs"):
                        st.markdown(
                            '<div class="tp-output-section-head"><strong>报告结构模板</strong>'
                            '<span>先固定结构，再将证据分配到章节</span></div>',
                            unsafe_allow_html=True)
                        _render_report_template_input()
                    with st.container(key="literature_inputs"):
                        st.markdown(
                            '<div class="tp-output-section-head"><strong>参考文献与理论资料</strong>'
                            '<span>上传与本次翻译实践相关的论文、专著或研究资料</span></div>',
                            unsafe_allow_html=True)
                        st.caption(
                            "系统将从文献中提取可核验的理论依据，并仅在证据充分时用于实践报告。")
                        _render_literature_inputs()
                    study_a, study_b = st.columns(2)
                    with study_a:
                        st.checkbox(
                            "翻译过程证据",
                            value=output_config.get("deliver_evidence", True),
                            key="deliver_evidence", on_change=_set_output_option,
                            args=("deliver_evidence", "deliver_evidence"),
                            help="批次翻译、审校与修订的可追溯证据",
                            **_PERSIST_STATE)
                        st.checkbox(
                            "案例候选",
                            value=output_config.get("deliver_cases", False),
                            key="deliver_cases", on_change=_set_output_option,
                            args=("deliver_cases", "deliver_cases"),
                            help="符合资格的真实修订案例", **_PERSIST_STATE)
                    with study_b:
                        st.checkbox(
                            "学术写作工作区",
                            value=output_config.get("deliver_academic_workspace", False),
                            key="deliver_academic_workspace",
                            on_change=_set_output_option,
                            args=("deliver_academic_workspace",
                                  "deliver_academic_workspace"),
                            help="论证大纲与写作素材包", **_PERSIST_STATE)
                        st.checkbox(
                            "审校报告",
                            value=output_config.get("deliver_review_report", False),
                            key="deliver_review_report", on_change=_set_output_option,
                            args=("deliver_review_report", "deliver_review_report"),
                            help="审校发现与处理记录", **_PERSIST_STATE)
            _render_task_actions(back_step=2, next_step=4)

        else:
            _step_title(4, "确认运行", "核对任务、输出内容与运行环境")
            task_files = st.session_state.get("task_files") or []
            filename_summary = task_files[0]["name"] if len(task_files) == 1 \
                else f"{len(task_files)} 个文档"
            glossary_name = st.session_state.get("task_glossary_name", "未添加")
            style_template = st.session_state.get("style_template", "学术书面语")
            style_source = ""
            style_sel = st.session_state.get("style_selection")
            if style_sel:
                style_source = "接受系统推荐" if style_sel.get("source") == "accepted" \
                    else "用户调整"
            connection_status = st.session_state.get(
                "provider_connection_status", "unverified")
            can_start = bool(task_files and api_key and ai_model) and not bool(
                st.session_state.get("report_template_error"))
            if st.session_state.get("report_template_error"):
                st.warning("请移除或重新上传可解析的报告模板后再开始任务。")
            st.markdown(_summary_html(filename_summary, target_lang, preset_label,
                                      glossary_name, strategy_config, output_config,
                                      style_template, style_source),
                        unsafe_allow_html=True)
            st.markdown(_runtime_html(ai_provider, ai_model, connection_status,
                                      can_start), unsafe_allow_html=True)
            if not api_key:
                with st.container(key="engine_setup_banner"):
                    message_col, action_col = st.columns([4, 1])
                    message_col.warning(
                        "尚未配置 AI 引擎。开始任务前，请先完成服务商与 API 密钥设置。",
                        icon=":material/warning:")
                    action_col.button("前往设置", key="open_engine_settings",
                                      on_click=_open_provider_settings,
                                      width="stretch")
            elif connection_status == "error":
                with st.container(key="engine_connection_banner"):
                    message_col, action_col = st.columns([4, 1])
                    message_col.error(
                        "最近一次连接测试未通过。请检查服务商、模型或 API 地址后再开始任务。",
                        icon=":material/error:")
                    action_col.button("检查设置", key="open_engine_settings_error",
                                      on_click=_open_provider_settings,
                                      width="stretch")
            elif connection_status != "connected":
                with st.container(key="engine_connection_banner"):
                    message_col, action_col = st.columns([4, 1])
                    message_col.warning(
                        "AI 引擎尚未验证。建议先测试连接，确认可用后再开始任务。",
                        icon=":material/warning:")
                    action_col.button("测试连接", key="open_engine_settings_unverified",
                                      on_click=_open_provider_settings,
                                      width="stretch")
            run_clicked = _render_task_actions(
                back_step=3, next_label="开始任务", run=True,
                next_disabled=not can_start)

    elif app_view == "workspace":
        pass
    elif app_view == "history":
        _page_title("历史任务", "继续任务或查看已经生成的交付资产")
    elif app_view == "library":
        _page_title("术语库与翻译记忆", "管理跨任务复用的术语与已审校译文")

core.set_llm_base_url(api_base if provider_cfg.get("custom_base_url") else None)

if app_view == "settings":
    st.stop()
if app_view == "library":
    with st.container(border=True):
        _tm = core.load_tm()
        st.metric("已审校记忆", len(_tm))
        st.caption("翻译时精确命中会自动复用；通过独立审校的段落会自动入库。")
        if _tm:
            for _src in list(_tm)[-8:]:
                st.text(f"{(_src or '')[:54]} → {(_tm[_src].get('target') or '')[:54]}")
            _tm_confirm = st.checkbox("确认清空全部翻译记忆", key="library_tm_clear_confirm")
            if st.button("清空翻译记忆", disabled=not _tm_confirm, key="library_tm_clear"):
                core.save_tm({})
                st.rerun()
    _render_knowledge_library(saved_jobs)
    with st.expander("项目术语版本", expanded=False):
        if saved_jobs:
            for job in saved_jobs:
                st.markdown(f"**{job['state'].get('filename', '?')}**")
                _render_terminology_version(job["state"])
        else:
            st.caption("暂无项目术语版本。")
    st.stop()
if app_view == "history":
    if not saved_jobs:
        st.info("暂无历史任务。")
    else:
        for job in saved_jobs:
            with st.container(key=f"history_item_{job['job_id']}"):
                hc1, hc2 = st.columns([4, 1])
                filename = escape(str(job["state"].get("filename", "?")))
                runtime_view = core.build_job_runtime_view(job["job_id"], job["state"])
                status = escape(runtime_view["headline_status"])
                business_status = escape(core.task_status_label(job["state"], job["job_id"]))
                recovery = core.recovery_summary(job["job_id"], job["state"])
                hc1.markdown(f'<div class="tp-history-copy"><strong>{filename}</strong>'
                             f'<span>{status} · 业务阶段：{business_status}</span></div>',
                             unsafe_allow_html=True)
                action = "继续处理" if "resume" in runtime_view.get("available_actions", []) \
                    else "打开"
                if hc2.button(action, key=f"open_history_{job['job_id']}", width="stretch"):
                    st.session_state.update(active_job_id=job["job_id"], app_view="workspace",
                                            workspace_mode=True)
                    if action == "继续处理":
                        _resume_job(job["job_id"], job["state"])
                    st.rerun()
                st.caption(
                    f"自动保存已开启 · 最近保存进度 {_format_saved_at(recovery['last_saved_at'])} · "
                    f"已完成 {recovery['completed_batch_count']}/{recovery['total_batches']} 个处理批次")
                if runtime_view.get("current_operation"):
                    st.caption(f"当前步骤：{runtime_view['current_operation']}")
                if runtime_view.get("progress"):
                    completed, total = runtime_view["progress"]
                    st.caption(f"报告工作流：已完成 {completed} / {total} 个检查点")
                if recovery.get("current_batch"):
                    current = recovery["current_batch"]
                    st.warning(
                        f"第 {current['number']} 个处理批次中断，已保存到本批次 "
                        f"{current['completed_segments']}/{current['segment_count']} 段；"
                        "继续时只会重新执行未完成批次。")
                if recovery.get("recovered_tm_entries"):
                    st.caption(f"已恢复 {recovery['recovered_tm_entries']} 条翻译记忆同步记录。")
                _render_snapshot_versions(job["job_id"], job["state"], "history")
    st.stop()
if app_view == "new" and not workspace_mode and not run_clicked:
    st.stop()

# ================= 核心处理流（后台 worker，UI 轮询 runtime 状态）=================
pending_job = st.session_state.pop("pending_continue_job", None)

tasks = []
seen = set()
if run_clicked:
    task_inputs = st.session_state.get("task_files") or []
    has_resume = bool(saved_jobs and resume_choice and resume_choice != "— 不继续 —")
    if not task_inputs and not has_resume:
        st.error("请先上传待翻译文档，或在「上传与开始」卡片中选择要继续的本地任务。")
    else:
        st.session_state.update(workspace_mode=True, app_view="workspace")
        for f in task_inputs:
            file_bytes = f["bytes"]
            job_id = core.file_job_id(file_bytes)
            if job_id in seen:
                continue
            seen.add(job_id)
            tasks.append({"job_id": job_id, "filename": f["name"],
                          "file_bytes": file_bytes})
        if has_resume:
            job = saved_jobs[job_choices.index(resume_choice)]
            if job["job_id"] not in seen:
                tasks.append({"job_id": job["job_id"],
                              "filename": job["state"].get("filename", "?"),
                              "file_bytes": None})
                st.session_state.active_job_id = job["job_id"]
elif pending_job:
    job = next((j for j in (saved_jobs or []) if j["job_id"] == pending_job), None)
    if job:
        tasks.append({"job_id": job["job_id"],
                      "filename": job["state"].get("filename", "?"),
                      "file_bytes": None})
        st.session_state.active_job_id = job["job_id"]

if tasks:
    started_jobs = []
    for task in tasks:
        job_id, filename, file_bytes = task["job_id"], task["filename"], task["file_bytes"]
        if st.session_state.get("report_template_removed"):
            core.clear_report_template(job_id)
            st.session_state.doc_states.pop(job_id, None)
        if template_input:
            core.save_report_template(
                job_id, template_input.get("name") or "template.docx",
                template_input.get("bytes") or b"")
        state = st.session_state.doc_states.get(job_id) or core.load_job_state(job_id) \
            or core.new_job_state(filename)
        st.session_state.doc_states[job_id] = state

        # Report dependencies (research settings, literature, writer version) are
        # checked inside the backend before its early return.  Only skip here
        # when academic writing is explicitly disabled.
        if state["p1_done"] and state["p2_done"] and not enable_report \
                and (not enable_annotate or state.get("annotations_done")):
            started_jobs.append(job_id)
            continue

        try:
            # Step 01 的 Quick Profiling 产物：落盘为版本化 artifact，
            # 并把文档画像注入任务状态，让管线跳过重复画像。
            style_selection = st.session_state.get("style_selection")
            doc_profile = st.session_state.get("doc_profile")
            if style_selection:
                core.write_profile_artifacts(job_id, doc_profile, style_selection)
                if doc_profile and doc_profile.get("domain"):
                    job_state = core.load_job_state(job_id) or {}
                    if not job_state.get("profile_done"):
                        job_state["document_profile"] = doc_profile
                        job_state["profile_done"] = True
                        core.save_job_state(job_id, job_state)
            if task["file_bytes"] is not None:
                st.session_state.source_parse_state = "parsing"
            if file_bytes is None:
                started = core.resume_job(
                    job_id, filename, _pipeline_kwargs(state), base_url=api_base)
            else:
                started = core.start_job_worker(
                    job_id, filename, file_bytes, _pipeline_kwargs(state), base_url=api_base)
            if started or core.is_job_worker_alive(job_id):
                started_jobs.append(job_id)
                st.session_state.active_job_id = job_id
        except Exception as exc:  # setup failures remain visible in the UI
            st.error(f"无法启动 {filename}：{exc}")
    if started_jobs:
        st.session_state.update(
            active_job_id=started_jobs[0], app_view="workspace", workspace_mode=True,
            workspace_section="overview")
        st.rerun()

# ================= 术语准备与审核面板（刷新/重启后自动恢复）=================
saved_jobs_after = core.list_jobs()
active = st.session_state.get("active_job_id")
if active is None and saved_jobs_after:
    for job in saved_jobs_after:
        s = job["state"]
        if s.get("p1_done") and not s.get("p2_done") and s.get("quality_mode") \
                and s.get("glossary") is not None:
            active = job["job_id"]
            break
st.session_state.active_job_id = active

if active and not (app_view == "workspace" and st.session_state.get("active_job_id")):
    astate = core.load_job_state(active)
    if astate and astate.get("p1_done") and not astate.get("p2_done") \
            and astate.get("quality_mode") and astate.get("glossary") is not None \
            and astate.get("stage") not in ("TRANSLATING", "TRANSLATED", "ACADEMIC_WRITING", "REPORT_GENERATED", "REVIEW_REQUIRED"):
        box = st.container(border=True)
        box.subheader(f"术语准备与审核：{astate.get('filename', '?')}")
        _render_profile_editor(active, astate, box)

        entries = astate.get("glossary") or []
        frozen = astate.get("glossary_frozen")
        bypassed = astate.get("quality_bypass")
        if frozen:
            box.success(f"术语表已冻结：版本 v{frozen.get('version')} "
                        f"冻结时间 {frozen.get('frozen_at', '')}")
            with box.expander("高级诊断", expanded=False):
                st.caption(f"术语版本内容指纹：{frozen.get('glossary_hash', '')}")
        elif bypassed:
            box.info("已选择跳过人工冻结：术语以 provisional 建议注入翻译。")
        else:
            box.warning("术语尚未冻结：仍有候选术语待人工审核，「开始翻译」不可执行。"
                       "请完成审核后冻结，或选择跳过冻结。")

        box.markdown(_glossary_status_chips(entries), unsafe_allow_html=True)
        fc1, fc2, fc3 = box.columns([2, 1, 1])
        filter_status = fc1.selectbox(
            "状态筛选", ["全部", "locked", "provisional", "candidate", "rejected"],
            key=f"gfilter_status_{active}")
        only_conflicts = fc2.checkbox("只看冲突项", key=f"gfilter_conflict_{active}")
        filter_text = fc3.text_input("搜索源术语", key=f"gfilter_text_{active}")

        df = _glossary_dataframe(entries, astate.get("paras") or [])
        view_mask = pd.Series(True, index=df.index)
        if filter_status != "全部":
            view_mask &= df["status"].eq(filter_status)
        if only_conflicts:
            view_mask &= df["冲突"].eq("冲突")
        if filter_text.strip():
            view_mask &= df["source"].str.contains(filter_text.strip(), case=False, na=False)
        df_view = df[view_mask]
        if not view_mask.all():
            box.caption(f"已按条件筛选：显示 {len(df_view)} / {len(df)} 条术语。")

        edited = box.data_editor(
            df_view,
            key=f"glossary_editor_{active}",
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            column_config={
                "选择": st.column_config.CheckboxColumn("选择", default=False),
                "id": st.column_config.TextColumn("ID", disabled=True),
                "source": st.column_config.TextColumn("源术语", required=True),
                "proposed_target": st.column_config.TextColumn("建议译名"),
                "target": st.column_config.TextColumn("目标译名"),
                "preferred": st.column_config.TextColumn("首选译名"),
                "forbidden": st.column_config.TextColumn("禁止译名（;分隔）"),
                "behavior": st.column_config.SelectboxColumn(
                    "行为", options=["translate", "preserve"]),
                "status": st.column_config.SelectboxColumn(
                    "状态", options=["candidate", "provisional", "locked", "rejected"]),
                "domain": st.column_config.TextColumn("领域"),
                "scope": st.column_config.TextColumn("范围"),
                "note": st.column_config.TextColumn("备注"),
                "confidence": st.column_config.NumberColumn(
                    "置信度", min_value=0.0, max_value=1.0, step=0.05),
                "出现次数": st.column_config.NumberColumn("出现次数", disabled=True),
                "上下文": st.column_config.TextColumn("部分上下文", disabled=True),
                "证据": st.column_config.TextColumn("证据", disabled=True),
                "冲突": st.column_config.TextColumn("冲突", disabled=True),
                "payload": st.column_config.TextColumn("payload", disabled=True),
            },
        )

        selected = edited[edited["选择"].fillna(False)] if "选择" in edited.columns \
            else edited.iloc[0:0]
        sel_ids = [str(x) for x in selected["id"].tolist() if str(x)]

        c1, c2, c3 = box.columns(3)
        if c1.button("保存草稿", key=f"gs_{active}", width="stretch"):
            core.save_glossary_draft(
                active, _merge_edited_entries(entries, _df_to_entries(edited)))
            st.rerun()
        if c2.button("锁定选中术语", disabled=not sel_ids, key=f"gl_{active}",
                          width="stretch"):
            core.set_glossary_entry_status(active, sel_ids, "locked")
            st.rerun()
        if c3.button("拒绝选中术语", disabled=not sel_ids, key=f"gr_{active}",
                          width="stretch"):
            core.set_glossary_entry_status(active, sel_ids, "rejected")
            st.rerun()

        c4, c5, c6 = box.columns(3)
        if c4.button("冻结术语表并继续翻译", key=f"gf_{active}",
                          width="stretch"):
            core.freeze_glossary(
                active, entries=_merge_edited_entries(entries, _df_to_entries(edited)),
                frozen_by="用户")
            st.session_state["pending_continue_job"] = active
            st.rerun()
        if c5.button("跳过冻结并翻译", key=f"gb_{active}",
                          width="stretch"):
            core.save_glossary_draft(
                active, _merge_edited_entries(entries, _df_to_entries(edited)))
            core.bypass_freeze(active)
            st.session_state["pending_continue_job"] = active
            st.rerun()
        if c6.button("开始翻译", disabled=not (frozen or bypassed),
                     key=f"gt_{active}", width="stretch"):
            st.session_state["pending_continue_job"] = active
            st.rerun()
        if frozen and not bypassed:
            if box.button("返回修改（解除冻结）", key=f"gu_{active}",
                          width="stretch"):
                core.unfreeze_glossary(active)
                st.rerun()
        if not frozen and not bypassed:
            box.caption("翻译未开始：请先「冻结术语表并继续翻译」，"
                       "或选择跳过冻结（快速模式）。")

# ================= New task workspace =================
# Keep the legacy renderers below as implementation references for the
# academic/context surfaces, but route the product workspace through the
# compact shell above.
if app_view == "workspace":
    live_status = core.get_job_runtime_status(active).get("status") if active else None
    if live_status in {"resume_requested", "queued", "starting", "running",
                       "waiting_external", "cancelling"}:
        _render_live_workspace(active)
    else:
        _render_workspace_shell(active, core.load_job_state(active) if active else None)
    st.stop()

# ================= 动态渲染过程资产面板（基于磁盘任务，刷新后仍可用）=================
# Streamlit tabs execute both bodies on every rerun.  Use an explicit surface
# switch so delivery controls are not constructed while the academic surface
# is active.
workspace_surface = st.radio(
    "当前工作区", ["资产与交付", "文档上下文", "实践报告"], horizontal=True,
    key="workspace_surface")


def _render_delivery_surface():
    st.header("项目过程资产")
    with st.expander("翻译记忆（全局复用）", expanded=False):
        _tm = core.load_tm()
        st.caption(f"当前 {len(_tm)} 条已审校条目；精确命中时自动复用（跨任务全局）。")
        if _tm:
            with st.expander("预览最近条目", expanded=False):
                for _src in list(_tm)[-8:]:
                    st.caption(f"**{(_src or '')[:56]}** → {(_tm[_src].get('target') or '')[:56]}")
            _tm_confirm = st.checkbox("确认清空全部翻译记忆", key="tm_clear_confirm")
            if st.button("清空翻译记忆", disabled=not _tm_confirm,
                         key="tm_clear_go", width="stretch"):
                core.save_tm({})
                st.success("翻译记忆已清空")
                st.rerun()
        else:
            st.caption("暂无条目：翻译并通过独立审校的段落会自动入库。")
    if not saved_jobs_after:
        st.caption("暂无本地任务。上传文件并开始处理后，任务资产会显示在这里。")
    for job in saved_jobs_after:
        state = job["state"]
        filename = state.get("filename", "?")
        is_active = job["job_id"] == st.session_state.get("active_job_id")
        with st.expander(f"资产与交付: {filename}", expanded=is_active):
            dstatus = state.get("delivery_status") or "draft"
            snapshot_status = core.delivery_snapshot_status(job["job_id"], state)
            latest_snapshot = snapshot_status["latest"]
            snapshot_current = snapshot_status["current"]
            frozen_assets = {}
            if snapshot_current and latest_snapshot:
                frozen_assets = core.delivery_snapshot_assets(
                    job["job_id"], latest_snapshot["snapshot_version"])
            asset_prefix = _asset_prefix(state, snapshot_current)
            if dstatus == "final" and snapshot_current:
                st.success(
                    f"交付状态：最终交付版本 v{latest_snapshot['snapshot_version']}（已冻结）")
            elif dstatus == "final":
                st.warning(
                    "当前任务虽有最终状态，但没有可用的冻结交付版本；"
                    "请重新确认后生成最终交付版本。")
            elif dstatus == "review_required":
                st.warning(f"交付状态：{core.delivery_status_label(state)}"
                           "（存在必须处理问题，未最终交付）")
            else:
                st.caption(f"交付状态：{core.delivery_status_label(state)}"
                           "（当前为 draft 资产，尚未最终交付）")
                if latest_snapshot:
                    st.warning("当前工作版本已有变更；历史最终交付版本保持不变。")
            _render_snapshot_versions(job["job_id"], state, "assets")
            st.subheader("过程资产")
            col_d1, col_d2, col_d3, col_d4 = st.columns(4)

            with col_d1:
                if state.get("p1_done") and state.get("paras"):
                    data = frozen_assets.get("stage1_cleaned.docx") \
                        if snapshot_current else core.paragraphs_to_word(state["paras"])
                    st.download_button(
 "1. 洗净后原文",
                        data,
                        file_name=f"{asset_prefix}阶段1_清洗原文_{filename}.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
 key=f"d1_{job['job_id']}", width="stretch")
            with col_d2:
                if state.get("auto_terms"):
                    data = frozen_assets.get("auto_terms.xlsx") \
                        if snapshot_current else core.dict_to_excel(state["auto_terms"])
                    st.download_button(
 "1.5 提取术语库",
                        data,
                        file_name=f"{asset_prefix}自动抽词库_{filename}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
 key=f"dt_{job['job_id']}", width="stretch")
            with col_d3:
                if state.get("p2_done") and state.get("pairs"):
                    data = frozen_assets.get("stage2_bilingual.docx") if snapshot_current \
                        else core.pairs_to_word(
                            state["pairs"], annotations=state.get("annotations"),
                            colors=annotation_colors)
                    st.download_button(
 "2. 双语对照表",
                        data,
                        file_name=f"{asset_prefix}阶段2_双语对照_{filename}.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
 key=f"d2_{job['job_id']}", width="stretch")
            with col_d4:
                if state.get("p3_md"):
                    data = _report_docx_bytes(state, frozen_assets)
                    st.download_button(
 "3. 翻译实践报告",
                        data,
                        file_name=f"{asset_prefix}阶段3_实践报告_{filename}.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
 key=f"d3_{job['job_id']}", width="stretch")

            if state.get("document_profile"):
                prof = state["document_profile"]
                st.caption(
                    f"画像：领域 {prof.get('domain') or '?'} · "
 f"类型 {prof.get('genre') or '?'} 语域 {prof.get('register') or '?'} "
                    f"置信度 {prof.get('confidence') or 0}")

            if state.get("p2_done"):
                stats = state.get("review_stats") or {}
                st.caption(
                    f"审校：{stats.get('reviewed_segments', 0)} 段通过 · "
                    f"必须处理 {stats.get('blocking', 0)} · 建议检查 {stats.get('actionable', 0)} · "
                    f"仅供参考 {stats.get('informational', 0)} · "
                    f"记忆复用 {state.get('tm_used_count', 0)} 段")
                _render_delivery_review_queue(
                    job["job_id"], state, target_lang, ai_provider, ai_model,
                    api_key, style_rules)
                _render_delivery_gate(
                    job["job_id"], state, dstatus, target_lang,
                    ai_provider, ai_model)
                st.subheader("交付资产")
                exported = {} if snapshot_current else _assets.export_all(
                    state, job["job_id"], target_lang, ai_provider, ai_model,
                    source_filename=filename)
                ea1, ea2, ea3, ea4 = st.columns(4)
                with ea1:
                    data = frozen_assets.get("terms.tbx") if snapshot_current \
                        else exported["terms.tbx"]
                    st.download_button("TBX 术语库", data,
                                       file_name=f"{asset_prefix}terms_{filename}.tbx",
                                       mime="application/xml", key=f"tbx_{job['job_id']}", width="stretch")
                with ea2:
                    data = frozen_assets.get("memory.tmx") if snapshot_current \
                        else exported["memory.tmx"]
                    st.download_button("TMX 翻译记忆", data,
                                       file_name=f"{asset_prefix}memory_{filename}.tmx",
                                       mime="application/xml", key=f"tmx_{job['job_id']}", width="stretch")
                with ea3:
                    data = frozen_assets.get("bilingual.jsonl") if snapshot_current \
                        else exported["bilingual.jsonl"]
                    st.download_button("JSONL 双语段落", data,
                                       file_name=f"{asset_prefix}bilingual_{filename}.jsonl",
                                       mime="application/x-jsonlines", key=f"jl_{job['job_id']}", width="stretch")
                with ea4:
                    data = frozen_assets.get("delivery_manifest.json") if snapshot_current \
                        else exported["delivery_manifest.json"]
                    st.download_button("交付清单 manifest", data,
                                       file_name=f"{asset_prefix}delivery_manifest_{filename}.json",
                                       mime="application/json", key=f"mf_{job['job_id']}", width="stretch")
                evidence_data = frozen_assets.get("segment_evidence.jsonl") \
                    if snapshot_current else _report_evidence.export_segment_evidence_jsonl(
                        state, job["job_id"]).encode("utf-8")
                st.download_button(
                    "案例证据包 (.jsonl)",
                    evidence_data,
                    file_name=f"{asset_prefix}segment_evidence_{filename}.jsonl",
                    mime="application/x-jsonlines", key=f"ev_{job['job_id']}", width="stretch")
                if state.get("human_actions"):
                    with st.expander("人工处理记录"):
                        for action in state["human_actions"][-20:]:
                            st.caption(f"{action.get('timestamp')} {action.get('action')} "
                                       f"{action.get('finding_id')} {action.get('note')}")
                if state.get("findings"):
                    review_data = frozen_assets.get("review_report.md") \
                        if snapshot_current else core.findings_report_md(state)
                    st.download_button("审查报告 (.md)", review_data,
                                       file_name=f"{asset_prefix}审查报告_{filename}.md",
                                       mime="text/markdown", key=f"rr_{job['job_id']}", width="stretch")

            if state.get("p3_md"):
                st.markdown(state["p3_md"])
                st.caption("报告为 AI 生成初稿：案例需对照双语表逐条人工核查后再使用。")

                with st.expander("术语治理审计（注入日志 / 冻结版本）", expanded=False):
                    versions = state.get("glossary_versions") or []
                    if versions:
                        st.caption(f"冻结版本 {len(versions)} 个（内容变化才产生新版本，旧版本不覆盖）")
                        st.dataframe(pd.DataFrame([{
                            "版本": v.get("version"),
                            "冻结时间": (v.get("frozen_at") or "")[:19],
                            "glossary_hash": str(v.get("glossary_hash") or "")[:16],
                            "条数": len(v.get("entries") or []),
                        } for v in versions]), hide_index=True, width="stretch")
                    else:
                        st.caption("暂无冻结版本（快速模式跳过冻结时不生成版本）。")
                    injections = state.get("glossary_injection_log") or []
                    if injections:
                        st.caption(
                            f"翻译批次注入日志 {len(injections)} 批"
                            "（每批实际注入的术语 entry ID 均有记录）")
                        st.dataframe(pd.DataFrame([{
                            "批次": x.get("batch"),
                            "起始段": x.get("offset"),
                            "注入条数": len(x.get("entry_ids") or []),
                            "术语版本": x.get("glossary_version") or "-",
                            "hash": str(x.get("glossary_hash") or "")[:16],
                        } for x in injections[-100:]]), hide_index=True,
                                   width="stretch")
                    else:
                        st.caption("暂无批次注入日志。")

                del_key = f"confirm_del_{job['job_id']}"
                if st.button("删除该任务及本地进度", key=f"del_{job['job_id']}",
                          width="stretch"):
                    st.session_state[del_key] = True
                if st.session_state.get(del_key):
                    st.warning("删除后该任务的全部本地进度（翻译、术语、报告、资产）不可恢复。")
                    dc1, dc2 = st.columns(2)
                    if dc1.button("确认删除", key=f"del_yes_{job['job_id']}",
                          width="stretch"):
                        core.delete_job(job["job_id"])
                        st.session_state.doc_states.pop(job["job_id"], None)
                        st.session_state.pop(del_key, None)
                        st.rerun()
                    if dc2.button("取消", key=f"del_no_{job['job_id']}",
                          width="stretch"):
                        st.session_state.pop(del_key, None)
                        st.rerun()

def _render_academic_surface():
    st.header("学术写作工作区")
    if not saved_jobs_after:
        st.caption("暂无本地任务。上传文件并开始处理后，学术写作工作区会显示在这里。")
    for job in saved_jobs_after:
        state = job["state"]
        filename = state.get("filename", "?")
        is_active = job["job_id"] == st.session_state.get("active_job_id")
        with st.expander(f"学术写作: {filename}", expanded=is_active):
            if state.get("p2_done"):
                academic = state.get("academic_state") or {}
                quality = academic.get("quality_status") or academic.get("status") or "not_started"
                st.subheader("学术写作工作区")
                if quality == "pass":
                    st.success("学术状态：验证通过（仍需人工学术判断后提交）")
                elif quality == "pass_with_warnings":
                    st.warning("学术状态：通过，但存在证据缺口或低等级警告")
                elif quality in ("review_required", "fail", "failed"):
                    st.error(f"学术状态：{core.academic_status_label(state)}")
                else:
                    st.caption(f"学术状态：{core.academic_status_label(state)} · "
                               f"当前阶段 {academic.get('current_stage') or 'not_started'}")
                if academic.get("quality_dimensions"):
                    st.caption("质量维度：" + " · ".join(
                        f"{key}={value}" for key, value in academic[
                            "quality_dimensions"].items()))

                aevidence = core.load_academic_artifact(job["job_id"], "evidence")
                literature_sources_artifact = core.load_academic_artifact(
                    job["job_id"], "literature_sources")
                literature_evidence_artifact = core.load_academic_artifact(
                    job["job_id"], "literature_evidence")
                literature_claims_artifact = core.load_academic_artifact(
                    job["job_id"], "literature_claims")
                argument_artifact = core.load_academic_artifact(job["job_id"], "argument_plan")
                selected_cases = core.load_academic_artifact(job["job_id"], "selected_cases")
                outline_artifact = core.load_academic_artifact(job["job_id"], "outline")
                case_plans_artifact = core.load_academic_artifact(
                    job["job_id"], "case_analysis_plans")
                synthetic_artifact = core.load_academic_artifact(
                    job["job_id"], "synthetic_validation")
                validation_artifact = core.load_academic_artifact(job["job_id"], "validation")
                review_artifact = core.load_academic_artifact(job["job_id"], "review")
                literature_review_artifact = core.load_academic_artifact(
                    job["job_id"], "literature_support_review")
                quality_artifact = core.load_academic_artifact(
                    job["job_id"], "academic_quality")
                quality_repair_artifact = core.load_academic_artifact(
                    job["job_id"], "quality_repair_history")
                if aevidence:
                    astats = aevidence.get("project_evidence", {}).get("statistics", {})
                    coverage = aevidence.get("coverage_policy", {})
                    st.caption(
                        f"证据：扫描 {coverage.get('segments_scanned', 0)} 段（全语料） · "
                        f"候选案例 {len(aevidence.get('candidate_cases') or [])} · "
                        f"修复证据段 {astats.get('repaired_segments', 0)} · "
                        f"TM 复用 {astats.get('tm_reuse_count', 0)}")
                if selected_cases or outline_artifact:
                    st.caption(
                        f"真实修订案例 {(selected_cases or {}).get('authentic_revision_cases', 0)} · "
                        f"合成对比案例 {(selected_cases or {}).get('synthetic_contrast_cases', 0)} · "
                        f"提纲章节 {len((outline_artifact or {}).get('sections') or [])}")
                if synthetic_artifact:
                    synthetic_metrics = synthetic_artifact.get("metrics") or {}
                    if synthetic_artifact.get("pipeline_status") == "failed":
                        st.warning("合成对比案例生成失败；当前仅保留已验证的真实案例。")
                    st.caption(
                        f"合成案例：已生成模拟初译 "
 f"{synthetic_metrics.get('synthetic_baselines_generated', 0)} "
 f"不合理基线淘汰 {synthetic_metrics.get('baselines_rejected_as_implausible', 0)} "
                        f"学术合格 {synthetic_metrics.get('academically_eligible_synthetic_cases', 0)}")
                    with st.expander("查看 Synthetic Contrast Cases"):
                        for case in synthetic_artifact.get("items", []):
                            validation = case.get("validation") or {}
                            st.markdown(
 f"**{case.get('case_id')} Synthetic Contrast Case** — "
                                f"{'eligible' if validation.get('academic_case_eligible') else 'rejected'}")
                            st.caption(f"Source：{(case.get('source_text') or '')[:180]}")
                            st.caption(
                                f"Translation Difficulty：{(case.get('difficulty') or {}).get('reason') or '-'}")
                            st.caption(
                                f"Simulated Initial Translation："
                                f"{(case.get('synthetic_baseline') or {}).get('text') or '-'}")
                            st.caption(f"Error Diagnosis：{(case.get('error') or {}).get('diagnosis') or '-'}")
                            st.caption(
                                f"AI-Optimized Translation："
                                f"{(case.get('optimized_translation') or {}).get('text') or '-'}")
                            st.caption(
                                f"Validation：plausibility="
 f"{(case.get('baseline_plausibility') or {}).get('status', '-')} "
 f"repair={validation.get('repair_correctness', '-')} "
                                f"academic eligibility={validation.get('academic_case_eligible', False)}")
                if case_plans_artifact and case_plans_artifact.get("plans"):
                    plans = case_plans_artifact["plans"]
                    depth = (quality_artifact.get("diagnostics") or {}).get(
                        "case_analysis_depth") or {} if quality_artifact else {}
                    with st.expander("查看案例分析计划与质量"):
                        for plan in plans:
                            problem = plan.get("problem") or {}
                            effect = plan.get("translation_effect") or {}
                            mapping = plan.get("theory_mapping") or {}
                            depth_entry = depth.get(plan.get("case_id")) or {}
                            depth_line = " · ".join(
                                f"{k}={v.get('status', '?')}"
                                for k, v in list(depth_entry.items())[:5]) or "未评估"
                            st.markdown(
                                f"**{plan.get('case_id')} · "
                                f"{'Synthetic Contrast Case' if plan.get('case_type') == 'synthetic_contrast' else 'Authentic Revision Case'}** "
                                f"— {plan.get('evidence_level')} · "
                                f"深度：{depth_line}")
                            st.caption(
                                f"问题：{problem.get('statement') or '未计划'}"
                                f"{'（已落地）' if problem.get('grounded') else '（证据不足）'} · "
                                f"效果维度：{effect.get('dimension') or '-'} · "
                                f"理论：{mapping.get('concept') or plan.get('theory_connection_status')}")
                            human = plan.get("recommended_human_evidence") or []
                            if human:
                                st.caption("需要人工证据：" + "；".join(human[:3]))
                questions_artifact = core.load_academic_artifact(
                    job["job_id"], "human_evidence_questions")
                human_status = academic.get("human_evidence_status") or {}
                if human_status or (questions_artifact and questions_artifact.get("questions")):
                    st.subheader("人类证据收件箱")
                    if human_status:
                        st.caption(
                            f"待回答问题 {human_status.get('unanswered', 0)} · "
                            f"关键问题 {human_status.get('critical_questions', 0)} · "
                            f"已确认证据 {human_status.get('answered', 0)} · "
                            f"确认无法回忆 {human_status.get('unavailable_after_check', 0)} · "
                            f"矛盾 {human_status.get('conflicted', 0)}")
                    open_questions = [
                        q for q in (questions_artifact or {}).get("questions", [])
                        if q.get("status") == "open"]
                    if open_questions:
                        for q in open_questions:
                            case_id = q.get("case_id", "")
                            question = q.get("question", "")
                            context = q.get("context") or {}
                            with st.expander(
                                    f"{case_id} · {q.get('question_type', '')} · "
                                    f"{q.get('priority', '')}"):
                                st.caption(f"原文：{context.get('source', '')[:120]}")
                                if context.get("case_type") == "synthetic_contrast":
                                    st.caption(
                                        f"模拟初译：{context.get('synthetic_initial_translation', '')[:120]}")
                                    st.caption(
                                        f"优化译文：{context.get('optimized_translation', '')[:120]}")
                                else:
                                    st.caption(f"终译：{context.get('final_target', '')[:120]}")
                                st.markdown(f"**{question}**")
                                st.caption(
                                    "若不知道或没有相关记录，直接输入“不记得/没有相关记录”。")
                                answer = st.text_area(
                                    "你的回答", key=f"he_answer_{job['job_id']}_{q['question_id']}",
                                    height=70)
                                if st.button("提交证据",
                                             key=f"he_submit_{job['job_id']}_{q['question_id']}",
                                             disabled=not api_key):
                                    if not answer.strip():
                                        st.warning("请填写回答，或输入“不记得”。")
                                    else:
                                        try:
                                            entry = core.record_human_evidence(
                                                job["job_id"], q["question_id"], answer)
                                            st.success(
                                                f"已记录证据 {entry.get('human_evidence_id')} "
                                                f"（状态：{entry.get('status')}）。"
                                                "受影响章节将在下次重新生成时更新。")
                                        except Exception as exc:
                                            st.error(str(exc))
                if literature_sources_artifact:
                    lit_sources = literature_sources_artifact.get("sources") or []
                    lit_evidence_items = (literature_evidence_artifact or {}).get("items") or []
                    lit_claim_items = (literature_claims_artifact or {}).get("items") or []
                    grounded_count = sum(
                        x.get("evidence_grounded_status") in {
                            "grounded", "grounded_user_material"}
                        for x in lit_claim_items)
                    total_global = len((argument_artifact or {}).get("claims") or [])
                    total_sections = len((outline_artifact or {}).get("sections") or [])
                    st.markdown(_chain_flow([
                        ("文献来源", len(lit_sources), "已登记", "#1267e8"),
                        ("文献证据", len(lit_evidence_items), "逐字+位置+hash", "#0d9488"),
                        ("文献主张", len(lit_claim_items), f"已落地 {grounded_count}", "#7c3aed"),
                        ("全局论点", total_global, "", "#db2777"),
                        ("章节", total_sections, "", "#16a34a"),
                    ]), unsafe_allow_html=True)
                    if lit_sources:
                        with st.expander("按来源查看 来源→证据→主张→论点→章节 链路"):
                            source_options = {
                                f"{x.get('source_id')} · {x.get('title') or '未命名来源'}":
                                x.get("source_id") for x in lit_sources}
                            selected_source_id = st.selectbox(
                                "文献来源", source_options, key=f"lit_source_{job['job_id']}")
                            selected_source_id = source_options[selected_source_id]
                            selected_source = next(
                                x for x in lit_sources
                                if x.get("source_id") == selected_source_id)
                            st.json({k: v for k, v in selected_source.items()
                                     if k != "content_blocks"})
                            source_evidence = [x for x in lit_evidence_items
                                               if x.get("source_id") == selected_source_id]
                            source_claims = [x for x in lit_claim_items
                                             if x.get("source_id") == selected_source_id]
                            source_lc_ids = {x.get("literature_claim_id") for x in source_claims}
                            global_claims = [
                                x for x in (argument_artifact or {}).get("claims") or []
                                if source_lc_ids & set(x.get("literature_claims") or [])]
                            global_claim_ids = {x.get("claim_id") for x in global_claims}
                            source_sections = [
                                x for x in (outline_artifact or {}).get("sections") or []
                                if global_claim_ids & set(x.get("claims") or [])]
                            st.markdown(_chain_flow([
                                ("文献证据", len(source_evidence), "", "#0d9488"),
                                ("文献主张", len(source_claims), "", "#7c3aed"),
                                ("全局论点", len(global_claims), "", "#db2777"),
                                ("章节", len(source_sections), "", "#16a34a"),
                            ]), unsafe_allow_html=True)
                            if source_evidence:
                                st.dataframe(source_evidence, width="stretch")
                            if source_claims:
                                st.dataframe(source_claims, width="stretch")
                if validation_artifact:
                    summary = validation_artifact.get("summary") or {}
                    st.caption(
                        f"确定性验证：{validation_artifact.get('status')} · "
 f"错误 {summary.get('errors', 0)} 警告 {summary.get('warnings', 0)}")
                if review_artifact:
                    st.caption(
                        f"语义审稿：{review_artifact.get('status')} · "
                        f"问题 {len(review_artifact.get('issues') or [])}")
                if literature_review_artifact:
                    st.caption(
                        f"文献支持审校：{literature_review_artifact.get('status')} · "
                        f"问题 {len(literature_review_artifact.get('issues') or [])}")
                    if literature_review_artifact.get("issues"):
                        st.dataframe(literature_review_artifact["issues"],
                                   width="stretch")
                if quality_artifact:
                    q_dims = quality_artifact.get("dimensions") or {}
                    q_findings = quality_artifact.get("findings") or []
                    q_metrics = quality_artifact.get("metrics") or {}
                    aq_status = q_dims.get("literature_support") or "pass"
                    q_status_label = {
                        "pass": "通过", "pass_with_warnings": "通过（有警告）",
                        "review_required": "需复核", "fail": "失败",
                        "not_applicable": "不适用"}.get(aq_status, aq_status)
                    st.caption(
                        f"学术质量：发现 {len(q_findings)} 项 · 强案例 "
                        f"{q_metrics.get('strong_cases', 0)} · 弱案例 "
                        f"{q_metrics.get('weak_cases', 0)} · 泛化段率 "
                        f"{q_metrics.get('generic_paragraph_rate', 0)}")
                    if q_findings:
                        st.dataframe(q_findings, width="stretch")
                    if quality_repair_artifact and quality_repair_artifact.get("rounds"):
                        st.caption(
                            f"质量修复 {len(quality_repair_artifact['rounds'])} 轮 · "
                            f"案例替换 "
                            f"{sum(len(r.get('case_replacements') or []) for r in quality_repair_artifact['rounds'])}")

                def _queue_academic(scope, section_id=None):
                    if not api_key:
                        st.warning("请先在侧栏填写 API Key。")
                        return
                    core.invalidate_academic_report(job["job_id"], scope, section_id)
                    st.session_state["pending_continue_job"] = job["job_id"]
                    st.rerun()

                ac1, ac2, ac3, ac4, ac5, ac6 = st.columns(6)
                if ac1.button("重生成整篇", key=f"academic_all_{job['job_id']}",
                          width="stretch"):
                    _queue_academic("all")
                if ac2.button("重做规划", key=f"academic_plan_{job['job_id']}",
                          width="stretch"):
                    _queue_academic("planning")
                if ac3.button("重新验证", key=f"academic_val_{job['job_id']}",
                          width="stretch"):
                    _queue_academic("validation")
                if ac4.button("重新审稿", key=f"academic_review_{job['job_id']}",
                          width="stretch"):
                    _queue_academic("review")
                if ac5.button("文献审校", key=f"literature_review_{job['job_id']}",
                          width="stretch"):
                    _queue_academic("literature_review")
                if ac6.button("质量重评", key=f"quality_review_{job['job_id']}",
                          width="stretch"):
                    _queue_academic("quality")
                if outline_artifact and outline_artifact.get("sections"):
                    section_options = {
                        f"{x['section_id']} {x['title']}": x["section_id"]
                        for x in outline_artifact["sections"]}
                    chosen_section = st.selectbox(
                        "定点重生成章节", list(section_options),
                        key=f"academic_section_{job['job_id']}")
                    if st.button("重生成选中章节", key=f"academic_section_go_{job['job_id']}"):
                        _queue_academic("section", section_options[chosen_section])
                warning_path = core.job_dir(job["job_id"]) / "academic-evidence-warnings.md"
                if warning_path.is_file():
                    st.download_button(
                        "下载学术证据警告",
                        warning_path.read_bytes(),
                        file_name=f"academic-evidence-warnings_{filename}.md",
                        mime="text/markdown", key=f"academic_warn_{job['job_id']}",
                                   width="stretch")


if workspace_surface == "资产与交付":
    _render_delivery_surface()
elif workspace_surface == "文档上下文":
    if active:
        _render_context_surface(active, core.load_job_state(active) or {})
    else:
        st.header("文档上下文")
        st.info("请先打开一个当前任务，或从历史任务中选择任务。")
else:
    _render_academic_surface()
