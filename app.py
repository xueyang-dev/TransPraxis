"""TransPraxis / 译践 Streamlit 界面层。

信息架构：左侧产品导航 + 四步任务创建 + 运行后任务工作台。AI Provider
与翻译记忆属于全局设置；学术报告属于翻译后的下游工作流，不占据文档首屏。
"""
import base64
import inspect
import json
import re
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

import core
from transpraxis import assets as _assets
from transpraxis import academic_validator as _academic_validator
from transpraxis import context as _context
from transpraxis import delivery as _delivery
from transpraxis import knowledge as _knowledge
from transpraxis import literature_evidence as _literature_evidence
from transpraxis import report_evidence as _report_evidence

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
 padding: 28px 40px 56px;
}
.tp-workspace-shell { min-height: 2px; }
.st-key-workspace_exit_actions { margin-bottom:8px; }
.st-key-workspace_exit_actions .stButton > button {
 min-height:32px; padding:0 10px; border-color:transparent; background:transparent;
 color:var(--tp-sub); font-size:12px; justify-content:flex-start;
}
.st-key-workspace_exit_actions .stButton > button:hover {
 border-color:var(--tp-line); background:#fff; color:var(--tp-ink);
}
.tp-workspace-topbar {
 display:flex; align-items:flex-start; justify-content:space-between; gap:24px;
 padding: 4px 0 22px; border-bottom:1px solid var(--tp-line);
}
.tp-workspace-topbar h1 { margin:0; font-size:24px !important; line-height:1.25 !important; }
.tp-workspace-eyebrow { margin-bottom:8px; color:var(--tp-sub); font-size:12px; font-weight:600; letter-spacing:.04em; text-transform:uppercase; }
.tp-workspace-meta { margin-top:8px; color:var(--tp-sub); font-size:13px; }
.tp-workspace-status { display:flex; align-items:center; gap:8px; padding-top:7px; color:var(--tp-sub); font-size:13px; white-space:nowrap; }
.tp-status-dot { width:9px; height:9px; border-radius:50%; background:#f59e0b; }
.tp-status-dot.is-success { background:var(--tp-success); }
.tp-status-dot.is-danger { background:var(--tp-danger); }
.tp-status-dot.is-neutral { background:#94a3b8; }
.tp-workspace-layout { margin-top:24px; }
.st-key-workspace_nav_col, .st-key-workspace_context_col, .st-key-workspace_main_col { min-width:0; }
.st-key-workspace_nav_col {
 position:sticky; top:24px; align-self:flex-start; z-index:10;
 padding-right:18px; border-right:1px solid var(--tp-line-subtle);
 min-height:calc(100vh - 140px);
}
.tp-workspace-nav-title { margin:4px 0 12px; color:var(--tp-ink); font-size:12px; font-weight:700; letter-spacing:.04em; text-transform:uppercase; }
.tp-workspace-nav-caption { margin:0 0 14px; color:var(--tp-sub); font-size:12px; line-height:1.55; }
.st-key-workspace_nav .stButton > button {
 min-height:42px; margin:2px 0; justify-content:flex-start; padding:0 12px;
 border-color:transparent; background:transparent; color:#536176; font-size:14px;
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
.tp-nav-badge {
 display:inline-flex; align-items:center; justify-content:center; min-width:20px; height:20px;
 padding:0 6px; border-radius:999px; background:#fff0ef; color:#b42318;
 font-size:11px; font-weight:750; line-height:1; font-variant-numeric:tabular-nums;
}
.tp-workspace-nav-item { display:flex; align-items:center; gap:10px; }
.tp-workspace-nav-item i { width:7px; height:7px; border:1.5px solid currentColor; border-radius:50%; }
.tp-workspace-nav-item.is-active i { background:currentColor; }
.st-key-workspace_main_col { padding:0 26px; }
.tp-workspace-main h2 { margin:2px 0 5px; font-size:22px !important; }
.tp-workspace-main h3 { margin:0; font-size:15px !important; }
.tp-section-kicker { color:var(--tp-sub); font-size:12px; font-weight:650; text-transform:uppercase; letter-spacing:.06em; }
.tp-section-lead { margin:5px 0 22px; color:var(--tp-sub); font-size:14px; }
.tp-overview-hero { padding:22px 24px; border:1px solid #d8e5fa; border-radius:14px; background:linear-gradient(135deg,#f8fbff,#fff); }
.tp-overview-hero strong { display:block; color:var(--tp-ink); font-size:19px; }
.tp-overview-hero p { margin:8px 0 16px; color:var(--tp-sub); font-size:13px; }
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
 position:sticky; top:24px; align-self:flex-start; padding-left:18px;
}
.tp-info-card { padding:17px; border:1px solid var(--tp-line); border-radius:12px; background:#fff; }
.tp-info-card + .tp-info-card { margin-top:12px; }
.tp-info-card h3 { margin:0 0 13px; }
.tp-info-stat { display:flex; align-items:baseline; justify-content:space-between; gap:8px; padding:8px 0; border-bottom:1px solid var(--tp-line-subtle); }
.tp-info-stat:last-child { border-bottom:0; }
.tp-info-stat span { color:var(--tp-sub); font-size:12px; }
.tp-info-stat b { color:var(--tp-ink); font-size:15px; font-variant-numeric:tabular-nums; }
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
.tp-report-header, .tp-delivery-header { padding:20px 22px; border:1px solid var(--tp-line); border-radius:14px; background:#fff; }
.tp-report-header h3, .tp-delivery-header h3 { margin:0; font-size:19px !important; }
.tp-report-toolbar { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; }
.tp-report-toolbar h3 { margin:0; color:var(--tp-ink); font-size:20px !important; line-height:1.3 !important; }
.tp-report-toolbar-copy { min-width:0; }
.tp-report-toolbar-kicker { margin-bottom:7px; color:var(--tp-sub); font-size:11px; font-weight:750; letter-spacing:.08em; text-transform:uppercase; }
.tp-report-meta { margin-top:8px; color:var(--tp-sub); font-size:12px; line-height:1.55; }
.tp-report-toolbar-status { display:flex; align-items:center; gap:8px; padding-top:3px; color:var(--tp-ink); font-size:13px; white-space:nowrap; }
.tp-report-actions { display:flex; align-items:center; gap:8px; margin-top:14px; }
.st-key-report_actions [data-testid="stDownloadButton"] > button,
.st-key-report_actions .stButton > button { min-height:38px; }
.st-key-report-actions-caption { margin-top:8px; color:var(--tp-faint); font-size:11px; line-height:1.5; }
.tp-report-outline { margin:16px 0 0; padding:14px 16px; border:1px solid var(--tp-line); border-radius:10px; background:#fbfcfe; }
.tp-report-outline-title { margin-bottom:8px; color:var(--tp-ink); font-size:12px; font-weight:750; }
.tp-report-outline a { display:block; padding:4px 0; color:var(--tp-sub); font-size:12px; line-height:1.45; text-decoration:none; }
.tp-report-outline a:hover, .tp-report-outline a:focus-visible { color:var(--tp-primary); text-decoration:underline; }
.tp-report-outline a.is-chapter { color:var(--tp-ink); font-weight:650; }
.tp-report-outline a.is-subsection { padding-left:16px; }
.tp-report-review { margin-top:16px; padding:15px 16px; border:1px solid #f2d39a; border-radius:10px; background:#fffaf0; }
.tp-report-review-title { color:#704d00; font-size:13px; font-weight:750; }
.tp-report-review-item { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; padding:10px 0; border-top:1px solid #f3e5c8; }
.tp-report-review-copy { min-width:0; }
.tp-report-review-copy strong { display:block; color:#5e4300; font-size:13px; }
.tp-report-review-copy span { display:block; margin-top:3px; color:#786442; font-size:12px; line-height:1.55; }
.tp-report-review-item .stButton > button { min-height:32px; padding:0 9px; border-color:#e6c98f; background:#fff; color:#704d00; font-size:11px; white-space:nowrap; }
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
.tp-report-empty-note { margin-top:9px; color:var(--tp-faint); font-size:12px; line-height:1.6; }
.tp-report-tech-note { color:var(--tp-sub); font-size:12px; line-height:1.6; }
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
@media (max-width: 1050px) {
 [data-testid="stMainBlockContainer"]:has(.tp-workspace-shell) { padding:22px 24px 48px; }
 .st-key-workspace_main_col { padding:0 18px; }
 .st-key-workspace_context_col { padding-left:0; margin-top:20px; }
 .st-key-translation_inspector { padding-left:0; }
 .st-key-workspace_nav_col { position:static; min-height:auto; padding-right:0; padding-bottom:14px; border-right:0; border-bottom:1px solid var(--tp-line-subtle); }
 .tp-card-grid, .tp-stage-grid { grid-template-columns:1fr; }
}
@media (max-width: 760px) {
 [data-testid="stMainBlockContainer"]:has(.tp-workspace-shell) { padding:16px 14px 40px; }
 .tp-workspace-topbar { display:block; }
 .tp-workspace-status { padding-top:12px; }
 .st-key-workspace_main_col { padding:0; }
 .tp-review-pane, .tp-review-pane + .tp-review-pane { min-height:auto; margin:0; border-radius:12px; }
 .tp-report-toolbar { display:block; }
 .tp-report-toolbar-status { padding-top:12px; }
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
        "enable_review": False, "strict_terminology_governance": False,
    },
    "标准": {
        "auto_term": True, "use_tm": True,
        "enable_review": False, "strict_terminology_governance": False,
    },
    "学术增强": {
        "auto_term": True, "use_tm": True,
        "enable_review": True, "strict_terminology_governance": True,
    },
}

def _default_output_config():
    return {
        "enable_annotate": False, "enable_report": False,
        "deliver_plain_docx": True, "deliver_bilingual_docx": True,
        "deliver_pdf": False, "deliver_terms_xlsx": True,
        "deliver_tbx": False, "deliver_tmx": False, "deliver_jsonl": False,
        "deliver_evidence": True, "deliver_cases": False,
        "deliver_academic_workspace": False, "deliver_review_report": False,
    }


_PRESET_OUTPUTS = {
    "快速": {**_default_output_config()},
    "标准": {**_default_output_config()},
    "学术增强": {**_default_output_config(), "enable_report": True},
}


def _apply_preset(label):
    for key in ("strategy_auto_term", "strategy_use_tm", "strategy_review",
                "strategy_strict_terms", "output_annotate", "output_report"):
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
        "标准": ("兼顾质量与效率", "术语增强 → 翻译 → 基础检查",
                 ("术语更一致", "成本适中")),
        "学术增强": ("适合需要完整过程证据的任务",
                 "术语治理 → 翻译 → 独立审校 → 学术证据",
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
    readiness = ("可启动", "is-success") if can_start else ("需要配置", "is-warning")
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
    status = core.task_status_label(state)
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
                "从断点继续", type="primary", key=f"resume_workspace_{job_id}",
                width="stretch"):
            st.session_state.update(
                active_job_id=job_id, app_view="workspace", workspace_mode=True,
                pending_continue_job=job_id)
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
    any_pending = False
    for job in saved_jobs:
        state = job["state"]
        candidates = [item for item in state.get("knowledge_candidates") or []
                      if isinstance(item, dict) and not item.get("decision")]
        if not candidates:
            continue
        any_pending = True
        filename = state.get("filename", "?")
        with st.expander(f"{filename} · {len(candidates)} 条待确认词条", expanded=True):
            for candidate in candidates:
                context = _knowledge.candidate_context(candidate, state)
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
    if not any_pending:
        st.info("当前没有待确认词条。通过审校的译文会在后续批次产生新的知识观察。")


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
    snapshot = core.delivery_snapshot_status(job_id, state) if job_id else {"current": False}
    if state.get("delivery_status") == "final" and snapshot.get("current"):
        return "已冻结", "success"
    if _delivery.unresolved_blocking(state):
        return "待审查", "warning"
    if state.get("p2_done") and (state.get("p3_done") or not state.get("report_enabled", True)):
        return "可交付", "success"
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
        f'<div class="tp-workspace-status"><span class="tp-status-dot is-{tone}"></span>'
        f'<strong>{escape(status)}</strong></div></div>', unsafe_allow_html=True)


def _render_workspace_nav(section, state, job_id=""):
    st.markdown('<div class="tp-workspace-nav-title">项目导航</div>'
                '<div class="tp-workspace-nav-caption">从这里进入每个工作阶段。</div>',
                unsafe_allow_html=True)
    contexts, counts = _workspace_findings_counts(state)
    terms_done = bool(state.get("glossary_frozen") or state.get("quality_bypass")
                      or (state.get("auto_terms") and not state.get("quality_mode")))
    snapshot = core.delivery_snapshot_status(job_id, state) if job_id else {"current": False}
    statuses = {
        "translation": "done" if state.get("p2_done") else "pending",
        "terms": "done" if terms_done else "active" if state.get("p1_done") else "pending",
        "review": "active" if contexts else "done" if state.get("p2_done") else "pending",
        "report": "done" if state.get("p3_done") else "active" if state.get("p2_done") else "pending",
        "delivery": "done" if snapshot.get("current") else "pending",
    }
    labels = [("overview", "概览", None), ("translation", "翻译", None),
              ("terms", "术语", None), ("review", "审校", counts["blocking"] or None),
              ("report", "报告", None), ("delivery", "交付", None)]
    with st.container(key="workspace_nav"):
        for value, label, count in labels:
            active = value == section
            status = statuses.get(value, "active" if active else "pending")
            icon = (":material/radio_button_checked:" if active
                    else ":material/check_circle:" if status == "done"
                    else ":material/radio_button_unchecked:")
            with st.container(key=f"workspace_nav_item_{value}"):
                label_col, badge_col = st.columns([5, 1], gap="small")
                with label_col:
                    if st.button(label, icon=icon, key=f"workspace_nav_{value}", width="stretch",
                                 type="primary" if active else "secondary"):
                        st.session_state.workspace_section = value
                        st.rerun()
                if count:
                    with badge_col:
                        st.markdown(f'<span class="tp-nav-badge">{count}</span>',
                                    unsafe_allow_html=True)


def _render_workspace_project_details(state):
    with st.expander("项目详情", expanded=False):
        st.caption(f"源文件：{state.get('filename') or '—'}")
        st.caption(f"段落：{len(state.get('paras') or []):,} · 目标语言：{state.get('target_lang') or '简体中文'}")


def _translation_pair_status(pair):
    if pair.get("human_edited"):
        return "↻"
    if pair.get("reviewed"):
        return "✓"
    return "●"


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
        if st.button("✨ AI 重译", key=f"translation_retranslate_{selected_id}",
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


def _render_workspace_report_context(job_id, state):
    academic = state.get("academic_state") or {}
    artifacts = _report_artifacts(job_id)
    outline = artifacts.get("outline") or {}
    cases = artifacts.get("selected_cases") or {}
    real_case_count = sum(
        item.get("case_type") != "synthetic_contrast"
        for item in cases.get("cases") or [])
    quality = academic.get("quality_status") or academic.get("status") or "not_started"
    quality_label = _report_quality_label(quality)
    report_stage = _workspace_report_stage(job_id, state)
    validation = artifacts.get("validation") or {}
    groups = _report_issue_groups(artifacts, academic)
    if not state.get("p3_md"):
        st.markdown('<div class="tp-info-card"><h3>报告状态</h3>'
                    '<div class="tp-info-stat"><span>当前状态</span><b>尚未生成</b></div>'
                    '<p class="tp-tech-detail">完成翻译后，报告草稿与验证结果会显示在这里。</p>'
                    '</div>', unsafe_allow_html=True)
        _render_workspace_project_details(state)
        return
    st.markdown('<div class="tp-info-card"><h3>报告概况</h3>'
                f'<div class="tp-info-stat"><span>验证状态</span><b>{escape(_report_validation_label(validation.get("status")))}</b></div>'
                f'<div class="tp-info-stat"><span>质量状态</span><b>{escape(quality_label)}</b></div>'
                f'<div class="tp-info-stat"><span>真实案例数量</span><b>{real_case_count:,}</b></div>'
                f'<div class="tp-info-stat"><span>文献证据</span><b>{escape(_report_literature_status(artifacts))}</b></div>'
                f'<div class="tp-info-stat"><span>待处理问题</span><b>{len(groups):,}</b></div>'
                '</div>', unsafe_allow_html=True)
    st.markdown('<div class="tp-info-card"><h3>当前工作稿</h3>'
                f'<div class="tp-info-stat"><span>报告状态</span><b>{escape(report_stage)}</b></div>'
                '<p class="tp-tech-detail">报告可继续编辑；最终交付确认仍在“交付”页面完成。</p>'
                '</div>', unsafe_allow_html=True)
    _render_workspace_project_details(state)


def _render_workspace_delivery_context(job_id, state):
    snapshot = core.delivery_snapshot_status(job_id, state)
    latest = snapshot.get("latest") or {}
    approval = latest.get("approval") or {}
    st.markdown('<div class="tp-info-card"><h3>版本信息</h3>'
                f'<div class="tp-info-stat"><span>当前版本</span><b>{("v" + str(latest.get("snapshot_version"))) if latest else "工作版本"}</b></div>'
                f'<div class="tp-info-stat"><span>状态</span><b>{"已冻结" if snapshot.get("current") else "未冻结"}</b></div>'
                f'<div class="tp-info-stat"><span>确认人</span><b>{escape(str(approval.get("actor") or "—"))}</b></div>'
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
    elif section == "report":
        _render_workspace_report_context(job_id, state)
    elif section == "delivery":
        _render_workspace_delivery_context(job_id, state)


def _render_workspace_overview(job_id, state):
    contexts, counts = _workspace_findings_counts(state)
    status, tone = _workspace_status(state, job_id)
    blockers = counts["blocking"]
    st.markdown('<h2>概览</h2>'
                '<div class="tp-section-lead">当前任务与项目进度</div>',
                unsafe_allow_html=True)
    action_text = (f"{blockers} 个必须处理问题阻止最终交付。" if blockers
                   else "当前没有交付阻塞，可以准备最终版本。")
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
        ("最终交付", _workspace_status(state, job_id)[0] == "已冻结", False),
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
                                                   help="✓ 已审校 · ● 待审 · ↻ 已修改"),
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
                    pairs[index]["target"] = suggested_target
                    pairs[index]["accepted_target"] = suggested_target
                    pairs[index]["target_provenance"] = "reviewed"
                    pairs[index]["reviewed"] = True
                    pairs[index]["review_status"] = "reviewed_clean"
                    core.save_job_state(job_id, latest)
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


_REPORT_CASE_ISSUES = {
    "case_count_status_mismatch", "insufficient_core_revision_cases",
    "invalid_selected_case", "non_revision_case_used_as_revision_analysis",
    "synthetic_pipeline_unavailable", "synthetic_only_without_eligible_cases",
    "ineligible_synthetic_case_selected", "synthetic_case_provenance_mismatch",
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


def _report_artifacts(job_id):
    return {
        name: core.load_academic_artifact(job_id, name)
        for name in (
            "selected_cases", "outline", "validation", "review",
            "literature_sources", "literature_evidence", "literature_claims",
            "literature_support_review", "academic_quality",
            "human_evidence_questions",
        )
    }


def _report_quality_label(status):
    return {
        "pass": "已验证", "pass_with_warnings": "已验证 · 有警告",
        "review_required": "需要复核", "fail": "需要复核",
        "failed": "生成失败", "not_started": "未生成",
        "stale": "需要重新生成", "in_progress": "生成中",
    }.get(status, "—")


def _report_validation_label(status):
    return {
        "pass": "通过", "pass_with_warnings": "通过 · 有警告",
        "fail": "需要复核", "review_required": "需要复核",
    }.get(status, "未生成")


def _report_literature_status(artifacts):
    sources = (artifacts.get("literature_sources") or {}).get("sources") or []
    evidence = (artifacts.get("literature_evidence") or {}).get("items") or []
    claims = (artifacts.get("literature_claims") or {}).get("items") or []
    if not sources:
        return "未使用"
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
    """Use the same markdown_to_word path for Report and Delivery surfaces."""
    if frozen_assets and frozen_assets.get("stage3_report.docx"):
        return frozen_assets["stage3_report.docx"]
    report = state.get("p3_md")
    if not report:
        return None
    return core.markdown_to_word(
        report, state.get("theory") or "翻译实践").getvalue()


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
    text = re.sub(r"\b(?:seg|claim|rq|lit-claim|lit-evidence|human-ev)-[A-Za-z0-9_.:-]+\b",
                  "对应证据", text)
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
    return text.strip()


def _report_issue_category(issue):
    issue_type = str(issue.get("type") or "")
    if issue_type in _REPORT_CASE_ISSUES:
        return "案例不足"
    if issue_type in _REPORT_STATISTIC_ISSUES:
        return "统计验证失败"
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
    for issue in list(validation.get("issues") or []) \
            + list(review.get("issues") or []) \
            + list(literature_review.get("issues") or []) \
            + list(quality.get("findings") or []):
        category = _report_issue_category(issue)
        add(category, _report_issue_detail(category, issue), issue.get("section_id"))

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
    for category in ("案例不足", "文献证据缺失", "引用需要确认",
                     "统计验证失败", "章节需要重新生成", "需要人工补充"):
        if category not in groups:
            continue
        group = groups[category]
        sections = sorted(group["sections"], key=str)
        if category == "案例不足":
            action = "查看案例选择"
        elif category == "文献证据缺失":
            action = "查看文献证据"
        elif category in {"引用需要确认", "统计验证失败"}:
            action = "查看验证结果"
        elif category == "章节需要重新生成":
            action = f"定位第 {sections[0]} 节" if len(sections) == 1 else "定位章节"
        else:
            action = "查看补充问题"
        group["action"] = action
        ordered.append(group)
    return ordered


def _render_report_issue_summary(job_id, groups):
    st.markdown('<div class="tp-report-review"><div class="tp-report-review-title">'
                '报告需要复核</div>', unsafe_allow_html=True)
    for index, group in enumerate(groups):
        details = " ".join(group["details"][:2])
        st.markdown('<div class="tp-report-review-item"><div class="tp-report-review-copy">'
                    f'<strong>{escape(group["category"])}</strong>'
                    f'<span>{escape(details)}</span></div>', unsafe_allow_html=True)
        action_col, _ = st.columns([1.1, 4.9], gap="small")
        with action_col:
            if st.button(group["action"], key=f"report_issue_action_{job_id}_{index}",
                         width="stretch"):
                st.session_state[f"report_review_open_{job_id}"] = True
                st.session_state[f"report_review_focus_{job_id}"] = group["category"]
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


def _render_workspace_report(job_id, state):
    academic = state.get("academic_state") or {}
    quality = academic.get("quality_status") or academic.get("status") or "not_started"
    report_stage = _workspace_report_stage(job_id, state)
    tone = "warning" if quality in ("review_required", "fail", "failed") else \
        "success" if report_stage == "已冻结" else "neutral"
    artifacts = _report_artifacts(job_id)
    selected_cases = artifacts.get("selected_cases") or {}
    report = _clean_report_for_display(state.get("p3_md"))
    headings = _report_headings(report)
    outline = artifacts.get("outline") or {}
    case_count = len(selected_cases.get("cases") or [])
    chapter_count = len(outline.get("sections") or []) or sum(
        item["level"] == 2 for item in headings)
    groups = _report_issue_groups(artifacts, academic)
    updated = _report_updated_label(job_id, state, academic)
    quality_label = _report_quality_label(quality)
    validation_label = _report_validation_label(
        (artifacts.get("validation") or {}).get("status"))
    st.markdown('<div class="tp-section-kicker">下游成果</div><h2>报告</h2>'
                '<div class="tp-section-lead">以报告阅读为中心；复核与技术诊断按需展开。</div>',
                unsafe_allow_html=True)
    st.markdown('<div class="tp-report-header"><div class="tp-report-toolbar">'
                '<div class="tp-report-toolbar-copy"><div class="tp-report-toolbar-kicker">'
                '报告工作区</div><h3>翻译实践报告</h3>'
                f'<div class="tp-report-meta">最后更新 {escape(updated)} · '
                f'{chapter_count:,} 个章节 · {case_count:,} 个案例 · '
                f'验证：{escape(validation_label)} · 质量：{escape(quality_label)}</div></div>'
                f'<div class="tp-report-toolbar-status">{_workspace_status_badge(report_stage, tone)}'
                '</div></div></div>', unsafe_allow_html=True)

    if report:
        with st.container(key=f"report_actions_{job_id}"):
            action_a, action_b, action_c = st.columns([1.55, 1.25, 1.25], gap="small")
            docx_data = _report_docx_bytes(state)
            filename = Path(str(state.get("filename") or "report")).stem or "report"
            validation_status = (artifacts.get("validation") or {}).get("status")
            draft_label = "导出当前草稿 DOCX" if quality != "pass" or \
                validation_status != "pass" else "导出 DOCX"
            with action_a:
                st.download_button(
                    draft_label, docx_data,
                    file_name=f"{filename}_翻译实践报告_草稿.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"report_docx_{job_id}", width="stretch")
            with action_b:
                st.download_button(
                    "导出 Markdown", state.get("p3_md", "").encode("utf-8"),
                    file_name=f"{filename}_翻译实践报告_草稿.md", mime="text/markdown",
                    key=f"report_markdown_{job_id}", width="stretch")
            with action_c:
                if groups:
                    if st.button("查看复核问题", key=f"report_review_{job_id}",
                                 width="stretch"):
                        st.session_state[f"report_review_open_{job_id}"] = True
                        st.rerun()
                else:
                    st.caption("当前无待处理问题")
        st.markdown('<div class="tp-report-empty-note">DOCX 是可继续编辑的报告草稿；'
                    '这不代表最终交付审批。</div>', unsafe_allow_html=True)
        if groups and st.session_state.get(f"report_review_open_{job_id}"):
            _render_report_issue_summary(job_id, groups)
        if headings:
            outline_links = []
            for item in headings:
                css = "is-chapter" if item["level"] <= 2 else "is-subsection"
                outline_links.append(
                    f'<a class="{css}" href="#{escape(item["anchor"])}">'
                    f'{escape(item["title"])}</a>')
            st.markdown('<div class="tp-report-outline"><div class="tp-report-outline-title">'
                        '报告目录</div>' + "".join(outline_links) + '</div>',
                        unsafe_allow_html=True)
        st.markdown('<div class="tp-report-body">', unsafe_allow_html=True)
        st.markdown(_report_markdown_with_anchors(report, headings),
                    unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="tp-empty">报告尚未生成。</div>', unsafe_allow_html=True)

    with st.expander("技术详情 / 高级诊断", expanded=False):
        st.markdown('<div class="tp-report-tech-note">这里保留验证产物、章节来源和原始报告，'
                    '用于定位问题；正常阅读不会显示这些内部字段。</div>',
                    unsafe_allow_html=True)
        artifact_meta = academic.get("artifacts") or {}
        if artifact_meta:
            st.dataframe(pd.DataFrame([{
                "产物": key, "版本": value.get("version", "—"),
                "更新时间": str(value.get("updated_at", "—"))[:19],
            } for key, value in artifact_meta.items()]), hide_index=True, width="stretch")
        for label, artifact_name in (("验证产物", "validation"),
                                     ("语义复核", "review"),
                                     ("质量评估", "academic_quality")):
            artifact = artifacts.get(artifact_name)
            if artifact:
                with st.expander(label, expanded=False):
                    st.json(artifact)
        if state.get("p3_md"):
            st.code(state.get("p3_md"), language="markdown")


def _render_workspace_delivery(job_id, state):
    contexts, counts = _workspace_findings_counts(state)
    blockers = _delivery.unresolved_blocking(state)
    snapshot = core.delivery_snapshot_status(job_id, state)
    latest = snapshot.get("latest")
    frozen = bool(state.get("glossary_frozen") or state.get("quality_bypass") or not state.get("quality_mode"))
    report_ready = bool(state.get("p3_done") or not state.get("report_enabled", True))
    st.markdown('<div class="tp-section-kicker">工作流最后一步</div><h2>最终交付</h2>'
                '<div class="tp-section-lead">确认后生成不可变版本；当前工作版本仍可继续修改。</div>',
                unsafe_allow_html=True)
    st.markdown('<div class="tp-delivery-header"><h3>准备状态</h3>'
                '<div class="tp-checklist">'
                f'<div class="tp-check-row"><i>✓</i>翻译完成</div>'
                f'<div class="tp-check-row{"" if frozen else " is-warning"}"><i>{"✓" if frozen else "!"}</i>术语{"已冻结" if frozen else "尚未冻结"}</div>'
                f'<div class="tp-check-row{"" if not blockers else " is-warning"}><i>{"✓" if not blockers else "!"}</i>审校{"完成" if not blockers else f"还有 {len(blockers)} 个必须处理问题"}</div>'
                f'<div class="tp-check-row{"" if report_ready else " is-warning"}"><i>{"✓" if report_ready else "!"}</i>报告{"草稿已生成" if report_ready else "尚未生成"}</div>'
                '</div></div>', unsafe_allow_html=True)
    if blockers:
        st.warning(f"{len(blockers)} 个必须处理问题仍会阻止最终版本。处理问题，或明确接受剩余风险。")
        accept = st.checkbox("我已检查这些问题，并确认接受剩余风险", key=f"workspace_delivery_accept_{job_id}")
        note = st.text_input("接受风险说明", key=f"workspace_delivery_note_{job_id}", placeholder="说明为什么可以接受…")
        if st.button("接受风险并冻结最终版本", type="primary", disabled=not accept,
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
        if st.button("确认并冻结最终版本", type="primary", key=f"workspace_delivery_final_{job_id}", width="stretch"):
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
            st.markdown(f'<div class="tp-version"><strong>v{item.get("snapshot_version")} · Frozen</strong>'
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
    exported = _assets.export_all(state, job_id, target_lang, ai_provider, ai_model,
                                  source_filename=state.get("filename", ""))
    frozen_assets = core.delivery_snapshot_assets(job_id, latest.get("snapshot_version")) \
        if snapshot.get("current") and latest else {}
    def asset_bytes(name):
        return frozen_assets.get(name) or exported.get(name)
    term_count = len(state.get("glossary") or state.get("auto_terms") or [])
    assets = [
        ("双语文本", "bilingual.jsonl", f"translation.jsonl · {len(state.get('pairs') or []):,} segments", "application/x-jsonlines"),
        ("术语库", "terms.tbx", f"terminology.tbx · {term_count:,} terms", "application/xml"),
        ("翻译记忆", "memory.tmx", f"translation-memory.tmx · {len(state.get('pairs') or []):,} units", "application/xml"),
        ("Delivery Manifest", "delivery_manifest.json", "manifest.json · 任务版本与资产清单", "application/json"),
    ]
    if state.get("findings"):
        assets.append(("案例证据包", "segment_evidence.jsonl", "审校证据与段落 provenance", "application/x-jsonlines"))
    if state.get("p3_md"):
        report_docx = _report_docx_bytes(state, frozen_assets)
        assets.append(("实践报告", "stage3_report.docx", "翻译实践报告 · DOCX", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
    st.markdown('<div class="tp-section-label" style="margin-top:24px">交付文件</div><div class="tp-asset-list">', unsafe_allow_html=True)
    for index, (label, key, description, mime) in enumerate(assets):
        data = report_docx if key == "stage3_report.docx" else asset_bytes(key)
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
    if section not in {"overview", "translation", "terms", "review", "report", "delivery"}:
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
            elif section == "report":
                _render_workspace_report(job_id, state)
            else:
                _render_workspace_delivery(job_id, state)
    with context_col:
        with st.container(key="workspace_context_col"):
            _render_workspace_context(job_id, state, section)

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
    "case_selection_policy": "mixed", "case_limit": 5,
    "analysis_dimensions": ["文本特征", "术语管理", "翻译策略", "译后编辑与质量控制"],
})

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
        save_btn, test_btn = st.columns(2)
        with save_btn:
            if st.button("保存配置", width="stretch",
                         disabled=not (api_key and ai_model),
                         help="把服务商、模型与 API 密钥写入本地，重启应用后仍会保留"):
                core.save_provider_config(ai_provider, ai_model, api_key,
                                          api_base)
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
            can_start = bool(task_files and api_key and ai_model)
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
                status = escape(core.task_status_label(job["state"]))
                recovery = core.recovery_summary(job["job_id"], job["state"])
                hc1.markdown(f'<div class="tp-history-copy"><strong>{filename}</strong>'
                             f'<span>{status}</span></div>', unsafe_allow_html=True)
                if hc2.button("打开", key=f"open_history_{job['job_id']}", width="stretch"):
                    st.session_state.update(active_job_id=job["job_id"], app_view="workspace",
                                            workspace_mode=True)
                    st.rerun()
                st.caption(
                    f"自动保存已开启 · 最近保存进度 {_format_saved_at(recovery['last_saved_at'])} · "
                    f"已完成 {recovery['completed_batch_count']}/{recovery['total_batches']} 个处理批次")
                if recovery.get("current_batch"):
                    current = recovery["current_batch"]
                    st.warning(
                        f"第 {current['number']} 个处理批次中断，已保存到本批次 "
                        f"{current['completed_segments']}/{current['segment_count']} 段；"
                        "继续时只会重新执行未完成批次。")
                if recovery.get("recovered_tm_entries"):
                    st.caption(f"已恢复 {recovery['recovered_tm_entries']} 条翻译记忆同步记录。")
                _render_snapshot_versions(job["job_id"], job["state"], "history")
                if recovery.get("can_resume") and st.button(
                        "从断点继续", type="primary", key=f"resume_history_{job['job_id']}",
                        width="stretch"):
                    st.session_state.update(
                        active_job_id=job["job_id"], app_view="workspace",
                        workspace_mode=True, pending_continue_job=job["job_id"])
                    st.rerun()
    st.stop()
if app_view == "new" and not workspace_mode and not run_clicked:
    st.stop()

# ================= 核心处理流（断点续传状态机，实时落盘）=================
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
        setup_placeholder.empty()
        _page_title("任务工作区", "任务正在运行，进度会自动保存")
        wp_left, wp_right = st.columns([1, 2.5])
        with wp_left:
            st.markdown('<div class="tp-pipeline" style="padding:16px 18px">'
                        '<div class="tp-section-sub" style="margin-bottom:8px">处理流程</div>'
                        '<div class="tp-flow" style="display:block;line-height:2.15">'
                        '<span>文档解析</span><br/><span>段落重建</span><br/>'
                        '<span>术语抽取</span><br/><span>批次翻译</span><br/>'
                        '<span>独立审校</span><br/><span>Evidence</span><br/>'
                        '<span>实践报告</span></div></div>', unsafe_allow_html=True)
        wp_status = wp_right.empty()
        wp_status.info("准备工作流…")
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
    overall_bar = st.progress(0)
    for task_idx, task in enumerate(tasks):
        job_id, filename, file_bytes = task["job_id"], task["filename"], task["file_bytes"]
        state = st.session_state.doc_states.get(job_id) or core.load_job_state(job_id) \
            or core.new_job_state(filename)
        st.session_state.doc_states[job_id] = state

        # Report dependencies (research settings, literature, writer version) are
        # checked inside the backend before its early return.  Only skip here
        # when academic writing is explicitly disabled.
        if state["p1_done"] and state["p2_done"] and not enable_report \
                and (not enable_annotate or state.get("annotations_done")):
            overall_bar.progress((task_idx + 1) / len(tasks))
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
            with st.status(f"正在处理：{filename}", expanded=True) as status:
                state = core.run_job_pipeline(
                    job_id, filename, file_bytes,
                    provider=ai_provider, api_key=api_key, model=ai_model,
                    target_lang=target_lang, auto_term=auto_term,
                    enable_report=enable_report, translation_theory=translation_theory,
                    user_glossary=user_glossary,
                    style_rules=style_rules, enable_review=enable_review,
                    enable_annotate=enable_annotate, use_tm=use_tm,
                    strict_terminology_governance=strict_terminology_governance,
                    research_settings=research_settings,
                    literature_sources=literature_sources,
                    on_status=lambda label: (
                        status.update(label=label, state="running"),
                        wp_status.info(label) if run_clicked else None),
                    on_caption=lambda text: st.caption(text),
                )
                st.session_state.doc_states[job_id] = state
                st.session_state.active_job_id = job_id
                if state.get("p1_done"):
                    st.session_state.source_parse_state = "parsed"
                for warn in state.get("warnings", []):
                    st.warning(warn)
                if state["p1_done"] and state["p2_done"] \
                        and (not enable_report or state["p3_done"]):
                    academic_quality = (state.get("academic_state") or {}).get(
                        "quality_status") if enable_report else None
                    if academic_quality in ("fail", "failed"):
                        status.update(
                            label=f"{filename} 翻译完成，但学术报告验证失败（可单独重验/重生成）",
                            state="error")
                    elif academic_quality == "review_required":
                        status.update(
                            label=f"{filename} 翻译完成，学术报告需要人工复核",
                            state="complete")
                    elif academic_quality == "pass_with_warnings":
                        status.update(
                            label=f"{filename} 报告已生成并通过验证，但存在证据警告",
                            state="complete")
                    elif state.get("has_blocking"):
                        status.update(
                            label=f"{filename} 流程完成，但有必须处理问题待确认（见资产面板审查报告）",
                            state="complete")
                    else:
                        status.update(
                            label=f"{filename} 流程完成（交付状态：draft，"
                                  f"可在资产面板确认最终交付）",
                            state="complete")
                else:
                    status.update(
                        label=f"{filename} 进度已保存（当前阶段：{state.get('stage', '?')}），"
                              f"可在下方继续操作",
                        state="complete")
        except Exception as e:
            if task["file_bytes"] is not None and not state.get("p1_done"):
                st.session_state.source_parse_state = "error"
            if "学术写作阶段失败" in str(e):
                st.error(f"{filename} 翻译已保存，但学术写作失败：{e}。"
                         "可在下方学术写作工作区重新生成，不需要重跑翻译。")
            else:
                st.error(f"{filename} 翻译流程中断: {e}。进度已保存到本地 outputs/ 目录，"
                         f"刷新页面后可在「上传与开始」卡片中选择本地任务继续！")
            st.session_state.doc_states[job_id] = \
                core.load_job_state(job_id) or st.session_state.doc_states[job_id]

        overall_bar.progress((task_idx + 1) / len(tasks))

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
