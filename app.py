# -*- coding: utf-8 -*-
"""
VERDANT IQ — Sustainable Procurement & Supplier Impact Analyzer
Single-file MVP: SQLite persistence, deterministic evidence-quality engine,
CSV/XLSX ingestion with row-level validation, live intake simulation,
role-gated review/approval, traceable exports, embedded self-test suite.
All data is SYNTHETIC and labeled. Decision support only — not certification.
"""
import io, os, json, math, time, random, hashlib, sqlite3, html as H
from string import Template
from pathlib import Path
from datetime import date, datetime, timezone, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS / DOMAIN CATALOGS
# ─────────────────────────────────────────────────────────────────────────────
APP_NAME = "Verdant IQ"
ENGINE_VERSION = "EQS-1.2.0"
SCHEMA_VERSION = "1.0.0"
DEFAULT_FACTOR_VER = "RF-2026.1-demo"
DB_PATH = Path("verdant_iq.db")
EVIDENCE_DIR = Path("evidence_store")
ANALYTICS = {"validated", "in_review", "approved"}
CATEGORIES = ["electricity", "fuel", "water", "waste", "materials"]
CAT_LABEL = {"electricity": "Electricity", "fuel": "Fuel", "water": "Water",
             "waste": "Waste", "materials": "Materials"}
ACTIVITY = {
    "electricity": {"grid_electricity": {"unit": "kWh", "label": "Grid electricity"}},
    "fuel": {"natural_gas": {"unit": "kWh", "label": "Natural gas"},
             "diesel": {"unit": "litre", "label": "Diesel"}},
    "water": {"water_supply": {"unit": "m3", "label": "Mains water supply"}},
    "waste": {"waste_landfill": {"unit": "kg", "label": "Waste to landfill"},
              "waste_recycling": {"unit": "kg", "label": "Waste recycled"}},
    "materials": {"steel": {"unit": "kg", "label": "Steel (cradle-to-gate)"},
                  "aluminium": {"unit": "kg", "label": "Aluminium (cradle-to-gate)"},
                  "plastic": {"unit": "kg", "label": "Plastic (cradle-to-gate)"}},
}
UNIT_TABLE = {
    "kWh": {"kwh": 1.0, "mwh": 1000.0},
    "litre": {"l": 1.0, "litre": 1.0, "liter": 1.0, "litres": 1.0, "liters": 1.0},
    "m3": {"m3": 1.0, "m³": 1.0, "cbm": 1.0},
    "kg": {"kg": 1.0, "t": 1000.0, "tonne": 1000.0, "tonnes": 1000.0, "ton": 1000.0},
}
MAX_QTY = {"grid_electricity": 5e7, "natural_gas": 5e7, "diesel": 2e6,
           "water_supply": 1e6, "waste_landfill": 5e7, "waste_recycling": 5e7,
           "steel": 1e8, "aluminium": 1e8, "plastic": 1e8}
EVIDENCE_TYPES = ["meter_read", "invoice", "third_party_audit",
                  "supplier_declaration", "estimate", "none"]
DOC_TYPES = {"meter_read", "invoice", "third_party_audit"}
VERIF = ["third_party", "internal_checked", "unverified"]
COLLECTION = ["measured", "calculated", "estimated"]
UNC = {"measured": 0.05, "calculated": 0.12, "estimated": 0.30}
REQUIRED_COLS = ["supplier_id", "category", "activity_type", "quantity", "unit",
                 "period_start", "period_end", "facility", "country",
                 "evidence_type", "evidence_ref", "verification", "data_collection"]
EQS_WEIGHTS = {"completeness": 0.25, "recency": 0.20, "verification": 0.20,
               "traceability": 0.15, "consistency": 0.20}
FACTOR_NOTE = ("Illustrative demo factors modeled on published UK GHG conversion "
               "factors (DEFRA/DESNZ) and IEA-style grid averages. SYNTHETIC — replace "
               "with a licensed, authoritative, dated factor set before production use.")
FACTORS = {
    "RF-2026.1-demo": {"published": "2026-01", "entries": {
        "grid_electricity": {"factor": 0.2070, "unit": "kWh", "source": "Demo · grid avg (location-based)"},
        "natural_gas": {"factor": 0.18396, "unit": "kWh", "source": "Demo · gross CV basis"},
        "diesel": {"factor": 2.6870, "unit": "litre", "source": "Demo · average biofuel blend"},
        "water_supply": {"factor": 0.1770, "unit": "m3", "source": "Demo · supply + treatment"},
        "waste_landfill": {"factor": 0.4460, "unit": "kg", "source": "Demo · mixed C&I landfill"},
        "waste_recycling": {"factor": 0.0210, "unit": "kg", "source": "Demo · closed-loop avg"},
        "steel": {"factor": 1.900, "unit": "kg", "source": "Demo · cradle-to-gate, global avg"},
        "aluminium": {"factor": 8.240, "unit": "kg", "source": "Demo · cradle-to-gate, global avg"},
        "plastic": {"factor": 3.140, "unit": "kg", "source": "Demo · cradle-to-gate, mixed polymer"}}},
    "RF-2025.2-demo": {"published": "2025-07", "entries": {
        "grid_electricity": {"factor": 0.2250, "unit": "kWh", "source": "Demo · prior grid avg"},
        "natural_gas": {"factor": 0.18410, "unit": "kWh", "source": "Demo · gross CV basis"},
        "diesel": {"factor": 2.6890, "unit": "litre", "source": "Demo · average blend"},
        "water_supply": {"factor": 0.1800, "unit": "m3", "source": "Demo · supply + treatment"},
        "waste_landfill": {"factor": 0.4500, "unit": "kg", "source": "Demo · mixed landfill"},
        "waste_recycling": {"factor": 0.0220, "unit": "kg", "source": "Demo · closed-loop avg"},
        "steel": {"factor": 1.950, "unit": "kg", "source": "Demo · prior cradle-to-gate"},
        "aluminium": {"factor": 8.600, "unit": "kg", "source": "Demo · prior cradle-to-gate"},
        "plastic": {"factor": 3.200, "unit": "kg", "source": "Demo · prior mixed polymer"}}},
}
ROLES = {
    "Administrator": {"name": "Amara Osei", "perms": {"import", "edit", "submit", "archive",
                      "review", "approve", "override", "export", "admin", "restore"}},
    "Analyst": {"name": "Lena Fischer", "perms": {"import", "edit", "submit", "archive", "export", "restore"}},
    "Reviewer": {"name": "Marcus Bell", "perms": {"review", "approve", "override", "export"}},
    "Stakeholder (read-only)": {"name": "Priya Nair", "perms": {"export"}},
}
PAGES = ["🏠 Command Center", "📥 Import & Validate", "🗂 Records", "🧮 Impact Analysis",
         "🕳 Evidence & Gaps", "⚖️ Review & Approve", "📄 Reports & Export",
         "🧪 Quality & Tests", "🛡 Admin & Governance"]
RECORD_COLS = ["record_id", "supplier_id", "category", "activity_type", "quantity", "unit",
               "period_start", "period_end", "facility", "country", "evidence_type",
               "evidence_ref", "verification", "data_collection", "status", "source",
               "import_file", "import_sha", "corrects", "flags", "notes", "submitted_at",
               "created_at", "updated_at", "schema_version", "factor_version"]
TABLES = ["suppliers", "records", "audit", "decisions", "overrides", "imports",
          "config", "tenders"]

# ─────────────────────────────────────────────────────────────────────────────
# THEME — dusk (dark) default, daylight optional
# ─────────────────────────────────────────────────────────────────────────────
DAY = dict(bg1="#F5F7FC", bg2="#E9EEF9", bg3="#EFF1FA", surface="#FFFFFF",
           ink="#131A33", muted="#5A6485", line="rgba(30,40,90,.16)",
           track="#E3E7F3", thumb="#5B6FD1", thumb_h="#6F82DE",
           brand="#312E81", brand2="#4338CA", accent="#4F46E5",
           sb1="#0F1535", sb2="#172052", sb_ink="#E6EAFB", sb_muted="#A3AEDB",
           sb_line="rgba(230,234,251,.18)", sb_field="rgba(255,255,255,.09)",
           shadow="0 1px 2px rgba(20,25,60,.06),0 10px 28px -20px rgba(20,25,60,.35)",
           shadow_h="0 2px 4px rgba(20,25,60,.08),0 16px 36px -18px rgba(20,25,60,.4)")
DUSK = dict(bg1="#0A0E1F", bg2="#0F1530", bg3="#0C1124", surface="#151C38",
            ink="#E6EAFB", muted="#96A0C8", line="rgba(230,234,251,.16)",
            track="#0F1530", thumb="#3A4A94", thumb_h="#5062B8",
            brand="#4F5FD8", brand2="#6674E8", accent="#60A5FA",
            sb1="#070B1A", sb2="#0C1230", sb_ink="#E6EAFB", sb_muted="#A3AEDB",
            sb_line="rgba(230,234,251,.16)", sb_field="rgba(255,255,255,.08)",
            shadow="0 1px 2px rgba(0,0,0,.4),0 12px 30px -18px rgba(0,0,0,.7)",
            shadow_h="0 2px 6px rgba(0,0,0,.5),0 18px 40px -16px rgba(0,0,0,.8)")
PALETTE_DAY = ["#4338CA", "#0EA5E9", "#D97706", "#DC2626", "#0D9488", "#C026D3", "#65A30D", "#DB2777"]
PALETTE_DUSK = ["#818CF8", "#38BDF8", "#FBBF24", "#F87171", "#2DD4BF", "#E879F9", "#A3E635", "#F472B6"]
GRADE_DAY = {"A": "#15803D", "B": "#65A30D", "C": "#D97706", "D": "#EA580C", "F": "#DC2626"}
GRADE_DUSK = {"A": "#4ADE80", "B": "#A3E635", "C": "#FBBF24", "D": "#FB923C", "F": "#F87171"}
GRADE_CHIP = {"A": ("#DCFCE7", "#14532D"), "B": ("#ECFCCB", "#3F6212"),
              "C": ("#FEF3C7", "#92400E"), "D": ("#FFEDD5", "#9A3412"),
              "F": ("#FEE2E2", "#991B1B")}
CAT_DAY = {"electricity": "#0EA5E9", "fuel": "#D97706", "water": "#0D9488",
           "waste": "#C026D3", "materials": "#4338CA"}
CAT_DUSK = {"electricity": "#38BDF8", "fuel": "#FBBF24", "water": "#2DD4BF",
            "waste": "#E879F9", "materials": "#818CF8"}
SEV_COLOR = {"critical": "#7F1D1D", "high": "#DC2626", "medium": "#D97706", "low": "#2563EB"}

CSS_T = Template("""
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Inter:wght@400;500;600;700&display=swap');
html,body,[class*="css"]{font-family:'Inter',system-ui,sans-serif;}
.stApp{background:linear-gradient(160deg,$bg1 0%,$bg2 46%,$bg3 100%);color:$ink;}
header[data-testid="stHeader"]{background:transparent;}
[data-testid="stToolbar"],#MainMenu,footer{visibility:hidden;}
.block-container{padding-top:1.1rem;padding-bottom:3rem;max-width:1440px;}
h1,h2,h3{font-family:'Fraunces',Georgia,serif !important;color:$ink;letter-spacing:-.01em;}
*::-webkit-scrollbar{width:10px;height:10px;}
*::-webkit-scrollbar-track{background:$track;border-radius:8px;}
*::-webkit-scrollbar-thumb{background:linear-gradient(180deg,$thumb,$brand);border-radius:8px;border:2px solid $track;}
*::-webkit-scrollbar-thumb:hover{background:$thumb_h;}
*{scrollbar-width:thin;scrollbar-color:$thumb $track;}
section[data-testid="stSidebar"]{background:linear-gradient(180deg,$sb1,$sb2);border-right:1px solid $sb_line;}
section[data-testid="stSidebar"] p,section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] span,section[data-testid="stSidebar"] .stMarkdown{color:$sb_ink;}
section[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"]>div{background:$sb_field;color:$sb_ink;border-color:$sb_line;border-radius:10px;}
section[data-testid="stSidebar"] div[role="radiogroup"]>label{padding:7px 10px;border-radius:10px;margin:1px 0;transition:background .15s;}
section[data-testid="stSidebar"] div[role="radiogroup"]>label:hover{background:rgba(255,255,255,.08);}
section[data-testid="stSidebar"] div[role="radiogroup"]>label:has(input:checked){background:rgba(129,140,248,.28);}
section[data-testid="stSidebar"] hr{border-color:$sb_line;}
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p{color:$sb_muted;}
.v-hero{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:4px;}
.v-title{font-family:'Fraunces',serif;font-size:27px;font-weight:700;color:$ink;line-height:1.1;}
.v-tag{font-size:12.5px;color:$muted;margin-top:2px;}
.v-rule{height:3px;border-radius:3px;margin:10px 0 18px;background:linear-gradient(90deg,#312E81,#4F46E5 30%,#0EA5E9 62%,#D97706 88%,#DC2626);}
.chip{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;border-radius:999px;font-size:11px;font-weight:600;border:1px solid $line;background:$surface;color:$ink;white-space:nowrap;}
.chip.demo{background:#FEF3C7;color:#92400E;border-color:#F59E0B;}
.v-card{background:$surface;border:1px solid $line;border-radius:16px;padding:16px 18px;box-shadow:$shadow;transition:transform .18s ease,box-shadow .18s ease;height:100%;}
.v-card:hover{transform:translateY(-2px);box-shadow:$shadow_h;}
.kpi .l{font-size:10.5px;text-transform:uppercase;letter-spacing:.12em;color:$muted;font-weight:600;}
.kpi .v{font-family:'Fraunces',serif;font-size:29px;font-weight:700;color:$ink;line-height:1.15;margin-top:3px;}
.kpi .d{font-size:12px;color:$muted;margin-top:3px;}
.kpi .bar{height:4px;border-radius:4px;margin-top:9px;}
.feed-item{display:flex;gap:10px;align-items:flex-start;padding:8px 11px;border-radius:10px;background:$surface;border:1px solid $line;border-left:4px solid #16A34A;margin-bottom:6px;font-size:12.5px;color:$ink;animation:vslide .35s ease;}
.feed-item.bad{border-left-color:#DC2626;}
.feed-item .t{color:$muted;font-size:11px;white-space:nowrap;}
@keyframes vslide{from{opacity:0;transform:translateY(7px);}to{opacity:1;transform:none;}}
.pulse-dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:#22C55E;box-shadow:0 0 0 0 rgba(34,197,94,.55);animation:vpulse 1.6s infinite;}
.pulse-dot.off{background:#94A3B8;animation:none;box-shadow:none;}
@keyframes vpulse{70%{box-shadow:0 0 0 9px rgba(34,197,94,0);}100%{box-shadow:0 0 0 0 rgba(34,197,94,0);}}
.stButton>button,.stDownloadButton>button{width:100%;border-radius:10px;border:1px solid $line;font-weight:600;transition:all .15s;background:$surface;color:$ink;}
.stButton>button:hover,.stDownloadButton>button:hover{transform:translateY(-1px);border-color:$brand2;color:$brand2;}
button[kind="primary"],button[data-testid="stBaseButton-primary"]{background:linear-gradient(135deg,#4338CA,#312E81) !important;color:#F3F7EE !important;border:none !important;}
button[kind="primary"]:hover,button[data-testid="stBaseButton-primary"]:hover{filter:brightness(1.12);color:#fff !important;}
button:disabled{opacity:.45;}
[data-testid="stVerticalBlockBorderWrapper"]{background:$surface;border:1px solid $line;border-radius:16px;box-shadow:$shadow;}
[data-testid="stExpander"]{border:1px solid $line;border-radius:12px;background:$surface;}
[data-testid="stDataFrame"]{border:1px solid $line;border-radius:12px;overflow:hidden;}
.stTextInput input,.stTextArea textarea,.stNumberInput input,
.stSelectbox div[data-baseweb="select"]>div,.stMultiSelect div[data-baseweb="select"]>div{background:$surface !important;color:$ink !important;border-color:$line !important;border-radius:10px !important;}
[data-testid="stSlider"] [role="slider"]{background:$brand2;border-color:$brand2;}
.stTabs [data-baseweb="tab-list"]{gap:6px;}
.stTabs [data-baseweb="tab"]{background:$surface;border:1px solid $line;border-radius:10px 10px 0 0;padding:8px 14px;font-weight:600;color:$muted;}
.stTabs [aria-selected="true"]{color:$brand2 !important;border-bottom:2px solid $brand2;}
[data-testid="stCaptionContainer"] p{color:$muted;}
.stAlert{border-radius:12px;}
code{color:$accent;}
""")

def pal(): return DUSK if st.session_state.get("dusk") else DAY
def chart_palette(): return PALETTE_DUSK if st.session_state.get("dusk") else PALETTE_DAY
def grade_colors(): return GRADE_DUSK if st.session_state.get("dusk") else GRADE_DAY
def cat_colors(): return CAT_DUSK if st.session_state.get("dusk") else CAT_DAY

def inject_css():
    st.markdown("<style>" + CSS_T.substitute(pal()) + "</style>", unsafe_allow_html=True)

def style_fig(fig, height=340, title=None, legend=True):
    p = pal()
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color=p["ink"], size=12),
        margin=dict(l=10, r=10, t=44 if title else 16, b=10), height=height,
        colorway=chart_palette(), showlegend=legend,
        title=dict(text=title, font=dict(family="Fraunces", size=17, color=p["ink"])),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
        hoverlabel=dict(bgcolor=p["surface"], font=dict(color=p["ink"])))
    fig.update_xaxes(gridcolor=p["line"], zerolinecolor=p["line"], linecolor=p["line"])
    fig.update_yaxes(gridcolor=p["line"], zerolinecolor=p["line"], linecolor=p["line"])
    return fig

def show_fig(fig, key=None):
    st.plotly_chart(fig, theme=None, width="stretch",
                    config={"displayModeBar": False}, key=key)

# ─────────────────────────────────────────────────────────────────────────────
# SMALL HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def utcnow(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def today_d(): return date.today()
def iso_minus(days=0, hours=0):
    return (datetime.now(timezone.utc) - timedelta(days=days, hours=hours)).isoformat(timespec="seconds")
def sget(r, c):
    v = r.get(c, "")
    if v is None or (isinstance(v, float) and math.isnan(v)): return ""
    try:
        if pd.isna(v): return ""
    except (TypeError, ValueError): pass
    return str(v).strip()
def flags_of(row):
    try: return json.loads(row.get("flags") or "[]")
    except (json.JSONDecodeError, TypeError): return []
def fmt_t(kg): return f"{kg/1000:,.1f} t"
def fmt_eur(v): return f"€{v:,.0f}"
def grade_for(x):
    return "A" if x >= 85 else "B" if x >= 70 else "C" if x >= 55 else "D" if x >= 40 else "F"
def grade_chip(g, score=None):
    bg, fg = GRADE_CHIP[g]
    txt = f"{g} · {score:.1f}" if score is not None else g
    return (f'<span class="chip" style="background:{bg};color:{fg};'
            f'border-color:{fg}55;font-weight:700;">{txt}</span>')
def sev_chip(s):
    c = SEV_COLOR.get(s, "#2563EB")
    return f'<span class="chip" style="background:{c}18;color:{c};border-color:{c}55;">{s.upper()}</span>'
def kpi(label, value, sub, accent):
    return (f'<div class="v-card kpi"><div class="l">{label}</div>'
            f'<div class="v">{value}</div><div class="d">{sub}</div>'
            f'<div class="bar" style="background:linear-gradient(90deg,{accent},{accent}33);"></div></div>')
def actor():
    role = st.session_state.get("role", "Administrator")
    return ROLES[role]["name"], role
def can(perm):
    return perm in ROLES[st.session_state.get("role", "Administrator")]["perms"]
def gate_hint(perm): return None if can(perm) else "Requires a role with this permission — switch role in the sidebar."
def jump(page):
    st.session_state.nav = page
    st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# DATA LAYER — SQLite, per-call connections, parameterized SQL
# ─────────────────────────────────────────────────────────────────────────────
def db_conn():
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    return con
def sql_df(q, p=()):
    con = db_conn()
    try: return pd.read_sql_query(q, con, params=p)
    finally: con.close()
def sql_exec(q, p=()):
    con = db_conn()
    try:
        con.execute(q, p); con.commit()
    finally: con.close()
def sql_scalar(q, p=()):
    con = db_conn()
    try:
        r = con.execute(q, p).fetchone()
        return r[0] if r else None
    finally: con.close()
def audit(action, entity, entity_id, detail=""):
    name, role = actor()
    sql_exec("INSERT INTO audit(ts,actor,role,action,entity,entity_id,detail) VALUES(?,?,?,?,?,?,?)",
             (utcnow(), name, role, action, entity, str(entity_id), str(detail)[:900]))
def load_suppliers(): return sql_df("SELECT * FROM suppliers ORDER BY supplier_id")
def load_records(): return sql_df("SELECT * FROM records ORDER BY created_at DESC, record_id DESC")
def load_audit(): return sql_df("SELECT * FROM audit ORDER BY id DESC")
def load_config():
    df = sql_df("SELECT * FROM config")
    return dict(zip(df["key"], df["value"])) if len(df) else {}
def set_config(k, v):
    sql_exec("INSERT INTO config(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))
def get_factor_version(): return load_config().get("factor_version", DEFAULT_FACTOR_VER)
def get_factors(ver=None): return FACTORS[ver or get_factor_version()]["entries"]
def load_overrides():
    return sql_df("SELECT * FROM overrides WHERE active=1")

def init_db():
    EVIDENCE_DIR.mkdir(exist_ok=True)
    con = db_conn()
    try:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS suppliers(supplier_id TEXT PRIMARY KEY,name TEXT,sector TEXT,
          country TEXT,tier INTEGER,annual_spend_eur REAL,renewal TEXT,contact TEXT,
          expected TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS records(record_id TEXT PRIMARY KEY,supplier_id TEXT,category TEXT,
          activity_type TEXT,quantity REAL,unit TEXT,period_start TEXT,period_end TEXT,facility TEXT,
          country TEXT,evidence_type TEXT,evidence_ref TEXT,verification TEXT,data_collection TEXT,
          status TEXT,source TEXT,import_file TEXT,import_sha TEXT,corrects TEXT,flags TEXT,notes TEXT,
          submitted_at TEXT,created_at TEXT,updated_at TEXT,schema_version TEXT,factor_version TEXT);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT,actor TEXT,
          role TEXT,action TEXT,entity TEXT,entity_id TEXT,detail TEXT);
        CREATE TABLE IF NOT EXISTS decisions(decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
          tender_id TEXT,ts TEXT,actor TEXT,role TEXT,approved_supplier TEXT,status TEXT,
          comment TEXT,weights TEXT,snapshot TEXT);
        CREATE TABLE IF NOT EXISTS overrides(supplier_id TEXT PRIMARY KEY,value REAL,reason TEXT,
          actor TEXT,ts TEXT,active INTEGER);
        CREATE TABLE IF NOT EXISTS imports(id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT,filename TEXT,
          sha256 TEXT,stored_path TEXT,rows_total INTEGER,rows_ok INTEGER,rows_err INTEGER,actor TEXT);
        CREATE TABLE IF NOT EXISTS config(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS tenders(tender_id TEXT PRIMARY KEY,code TEXT,title TEXT,
          budget_eur REAL,deadline TEXT,candidates TEXT,status TEXT,created_at TEXT);
        """)
        con.commit()
    finally:
        con.close()

def next_record_ids(n):
    mx = sql_scalar("SELECT MAX(CAST(substr(record_id,5) AS INTEGER)) FROM records") or 0
    return [f"OBS-{mx+i+1:06d}" for i in range(n)]

def insert_records(rows, source, import_file=None, import_sha=None, status="validated",
                   audit_action="RECORDS_CREATED"):
    ids = next_record_ids(len(rows))
    fv = get_factor_version()
    con = db_conn()
    try:
        for rid, r in zip(ids, rows):
            full = {c: r.get(c, "") for c in RECORD_COLS}
            full.update(record_id=rid, status=r.get("status", status), source=source,
                        import_file=import_file or "", import_sha=import_sha or "",
                        corrects=r.get("corrects", ""),
                        flags=json.dumps(r.get("flags", [])),
                        submitted_at=r.get("submitted_at", utcnow()),
                        created_at=utcnow(), updated_at=utcnow(),
                        schema_version=SCHEMA_VERSION, factor_version=fv)
            con.execute(f"INSERT INTO records({','.join(RECORD_COLS)}) VALUES({','.join('?'*len(RECORD_COLS))})",
                        tuple(full[c] for c in RECORD_COLS))
        con.commit()
    finally:
        con.close()
    audit(audit_action, "record", ",".join(ids[:6]) + ("…" if len(ids) > 6 else ""),
          json.dumps({"count": len(ids), "source": source}))
    return ids

def set_status(rid, new, reason=""):
    old = sql_scalar("SELECT status FROM records WHERE record_id=?", (rid,))
    sql_exec("UPDATE records SET status=?,updated_at=? WHERE record_id=?", (new, utcnow(), rid))
    audit("RECORD_STATUS", "record", rid, f"{old} → {new}" + (f" · {reason}" if reason else ""))

# ─────────────────────────────────────────────────────────────────────────────
# SYNTHETIC SEED — realistic, labeled, with deliberate gaps & exceptions
# ─────────────────────────────────────────────────────────────────────────────
SEED_SUPPLIERS = [
    dict(sid="SUP-01", name="Nordfjell Aluminium AS", sector="Metals", country="NO", tier=1,
         spend=6_800_000, contact="Ingrid Halvorsen", maturity=.92, skip=[], stale=False),
    dict(sid="SUP-02", name="BalticForge Steel OÜ", sector="Metals", country="EE", tier=1,
         spend=5_400_000, contact="Jaak Tamm", maturity=.75, skip=["water"], stale=False),
    dict(sid="SUP-03", name="Verdant Pack GmbH", sector="Packaging", country="DE", tier=1,
         spend=2_100_000, contact="Miriam Krug", maturity=.95, skip=[], stale=False),
    dict(sid="SUP-04", name="RheinChem Solutions AG", sector="Chemicals", country="DE", tier=1,
         spend=4_600_000, contact="Tobias Lang", maturity=.60, skip=["materials"], stale=False),
    dict(sid="SUP-05", name="Atlas Cement Works Ltd", sector="Construction", country="UK", tier=1,
         spend=3_900_000, contact="Fiona Whitmore", maturity=.50, skip=[], stale=False, contra=True),
    dict(sid="SUP-06", name="PureFlow Energy & Water plc", sector="Utilities", country="UK", tier=2,
         spend=1_700_000, contact="Dev Anand", maturity=.65, skip=["waste"], stale=False),
    dict(sid="SUP-07", name="Circla Textiles S.A.", sector="Textiles", country="PT", tier=2,
         spend=1_200_000, contact="Beatriz Lima", maturity=.45, skip=["materials"], stale=True),
    dict(sid="SUP-08", name="OakLine Logistics BV", sector="Logistics", country="NL", tier=1,
         spend=2_800_000, contact="Sanne de Vries", maturity=.60, skip=["water"], stale=False),
    dict(sid="SUP-09", name="Lumen IT Hardware Inc", sector="Electronics", country="US", tier=1,
         spend=3_300_000, contact="Dana Whitfield", maturity=.70, skip=["water"], stale=False),
    dict(sid="SUP-10", name="GrønData Centers ApS", sector="Data services", country="DK", tier=2,
         spend=2_500_000, contact="Mette Sørensen", maturity=.85, skip=[], stale=False),
    dict(sid="SUP-11", name="TerraFix Aggregates SARL", sector="Construction", country="FR", tier=2,
         spend=900_000, contact="Luc Moreau", maturity=.30, skip=["water", "waste"], stale=False),
    dict(sid="SUP-12", name="Solstice Catering Co.", sector="Food services", country="IE", tier=3,
         spend=450_000, contact="Aoife Byrne", maturity=.25, skip=["waste"], stale=True),
]
SECTOR_EXPECT = {
    "Metals": CATEGORIES, "Packaging": ["electricity", "water", "waste", "materials"],
    "Chemicals": CATEGORIES, "Construction": CATEGORIES,
    "Utilities": ["electricity", "fuel", "water", "waste"],
    "Textiles": ["electricity", "water", "waste", "materials"],
    "Logistics": ["electricity", "fuel", "water", "waste"],
    "Electronics": ["electricity", "water", "waste", "materials"],
    "Data services": ["electricity", "fuel", "water", "waste"],
    "Food services": ["electricity", "fuel", "water", "waste"],
}
MATURITY = {s["sid"]: s["maturity"] for s in SEED_SUPPLIERS}

def month_window(offset, anchor=None):
    a = anchor or today_d()
    y, m = a.year, a.month - offset
    while m <= 0: m += 12; y -= 1
    start = date(y, m, 1)
    nm = date(y + (m == 12), (m % 12) + 1, 1)
    return start, nm - timedelta(days=1)

def seed_database():
    rng = random.Random(19)
    now = utcnow()
    con = db_conn()
    try:
        for s in SEED_SUPPLIERS:
            con.execute("INSERT INTO suppliers VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (s["sid"], s["name"], s["sector"], s["country"], s["tier"], s["spend"],
                         (today_d() + timedelta(days=rng.randint(40, 300))).isoformat(),
                         s["contact"], json.dumps(SECTOR_EXPECT[s["sector"]]), now))
        con.commit()
    finally:
        con.close()

    rows, seq = [], 0
    scale = lambda s: max(0.35, s["spend"] / 2_500_000)
    base = {"electricity": 30_000, "fuel": 6_000, "water": 900, "waste": 12_000, "materials": 28_000}
    for s in SEED_SUPPLIERS:
        expected = [c for c in SECTOR_EXPECT[s["sector"]] if c not in s["skip"]]
        offsets = list(range(8, 14)) if s["stale"] else list(range(1, 7))
        short = s["name"].split()[0]
        for cat in expected:
            picks = rng.sample(offsets, min(4, len(offsets)))
            for off in picks:
                seq += 1
                ps, pe = month_window(off)
                if cat == "fuel":
                    act = "diesel" if (s["sector"] == "Logistics" or rng.random() < .4) else "natural_gas"
                elif cat == "waste":
                    act = "waste_landfill" if rng.random() < (0.8 if s["maturity"] < .5 else .45) else "waste_recycling"
                elif cat == "materials":
                    act = {"Metals": rng.choice(["aluminium", "steel"]),
                           "Construction": "steel"}.get(s["sector"], rng.choice(["plastic", "aluminium", "steel"]))
                else:
                    act = list(ACTIVITY[cat])[0]
                qty = round(rng.lognormvariate(math.log(base[cat] * scale(s)), 0.35), 1)
                r = rng.random()
                if r < s["maturity"]:
                    ev, vf, dc = rng.choice(["meter_read", "invoice", "third_party_audit"]), "third_party", "measured"
                elif r < s["maturity"] + (1 - s["maturity"]) * .5:
                    ev, vf, dc = rng.choice(["invoice", "supplier_declaration"]), "internal_checked", "calculated"
                else:
                    ev, vf, dc = rng.choice(["supplier_declaration", "estimate"]), "unverified", "estimated"
                flags, ref = [], f"DOC-{s['sid'][-2:]}{seq:03d}"
                if ev in DOC_TYPES and s["maturity"] < .6 and rng.random() < .3:
                    ref = ""; flags.append("missing_evidence_ref")
                status = "approved" if off >= 4 else ("in_review" if off in (2, 3) and rng.random() < .35 else "validated")
                rows.append(dict(supplier_id=s["sid"], category=cat, activity_type=act,
                                 quantity=qty, unit=ACTIVITY[cat][act]["unit"],
                                 period_start=ps.isoformat(), period_end=pe.isoformat(),
                                 facility=f"{short} Plant 01", country=s["country"],
                                 evidence_type=ev, evidence_ref=ref, verification=vf,
                                 data_collection=dc, status=status, flags=flags,
                                 notes="Synthetic seed record",
                                 submitted_at=(pe + timedelta(days=rng.randint(2, 9))).isoformat() + "T09:00:00+00:00"))
        if s["sid"] in ("SUP-04", "SUP-08", "SUP-11", "SUP-12"):
            ps = today_d().replace(day=1)
            rows.append(dict(supplier_id=s["sid"], category="electricity", activity_type="grid_electricity",
                             quantity=round(base["electricity"] * scale(s) * .4, 1), unit="kWh",
                             period_start=ps.isoformat(), period_end=today_d().isoformat(),
                             facility=f"{short} Plant 01", country=s["country"],
                             evidence_type="meter_read", evidence_ref=f"DOC-{s['sid'][-2:]}DRAFT",
                             verification="unverified", data_collection="measured", status="draft",
                             flags=[], notes="Month-to-date draft", submitted_at=utcnow()))
    ids = insert_records(rows, "seed", audit_action="SEED_RECORDS")

    # Deliberate exception fixtures ─ contradiction pair, correction chain, rejected row
    recs = load_records()
    atlas = recs[(recs.supplier_id == "SUP-05") & (recs.category == "electricity") &
                 (recs.status.isin(list(ANALYTICS)))].sort_values("period_end")
    if len(atlas):
        a = atlas.iloc[-1]
        dup = {c: a[c] for c in RECORD_COLS}
        dup.update(quantity=round(float(a["quantity"]) * 1.8, 1),
                   flags=["contradiction_pair"], notes="Duplicate metering feed — divergent totals",
                   status="validated", submitted_at=utcnow())
        insert_records([dup], "seed", audit_action="SEED_CONTRADICTION")
    oak = recs[(recs.supplier_id == "SUP-08") & (recs.activity_type == "diesel")].sort_values("period_end")
    if len(oak):
        o = oak.iloc[-1]
        set_status(o["record_id"], "archived", "Superseded by meter reconciliation")
        corr = {c: o[c] for c in RECORD_COLS}
        corr.update(quantity=round(float(o["quantity"]) * .92, 1), corrects=o["record_id"],
                    status="validated", flags=[], notes="Correction · supplier credit note CN-8841",
                    submitted_at=utcnow())
        insert_records([corr], "manual", audit_action="RECORD_CORRECTED")
    rej = dict(supplier_id="SUP-11", category="electricity", activity_type="grid_electricity",
               quantity=9.0e9, unit="kWh", period_start=month_window(2)[0].isoformat(),
               period_end=month_window(2)[1].isoformat(), facility="TerraFix Plant 01",
               country="FR", evidence_type="estimate", evidence_ref="", verification="unverified",
               data_collection="estimated", status="rejected",
               flags=["out_of_range"], notes="Rejected at intake: quantity exceeds plausibility bound",
               submitted_at=iso_minus(days=12))
    insert_records([rej], "import:supplier_portal_q3.csv", status="rejected", audit_action="SEED_REJECTED")

    # Tenders + one historical decision + one interim override
    tenders = [
        ("TND-01", "T26-114", "Depot rebuild — structural steel & aggregates", 2_400_000,
         (today_d() + timedelta(days=22)).isoformat(),
         json.dumps([{"sid": "SUP-02", "bid": 2_310_000}, {"sid": "SUP-05", "bid": 2_140_000},
                     {"sid": "SUP-11", "bid": 1_985_000}]), "open"),
        ("TND-02", "T26-121", "Regional facilities energy management", 1_150_000,
         (today_d() + timedelta(days=35)).isoformat(),
         json.dumps([{"sid": "SUP-06", "bid": 1_120_000}, {"sid": "SUP-10", "bid": 1_180_000},
                     {"sid": "SUP-08", "bid": 1_050_000}]), "correction_requested"),
        ("TND-03", "T26-108", "Circular materials supply agreement", 3_600_000,
         (today_d() + timedelta(days=9)).isoformat(),
         json.dumps([{"sid": "SUP-01", "bid": 3_550_000}, {"sid": "SUP-02", "bid": 3_420_000},
                     {"sid": "SUP-04", "bid": 3_610_000}]), "decided"),
    ]
    con = db_conn()
    try:
        for t in tenders:
            con.execute("INSERT INTO tenders VALUES(?,?,?,?,?,?,?,?)", (*t, iso_minus(days=30)))
        con.execute("INSERT INTO decisions(tender_id,ts,actor,role,approved_supplier,status,comment,weights,snapshot) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    ("TND-03", iso_minus(days=6), "Marcus Bell", "Reviewer", "SUP-01", "approved",
                     "Highest evidence quality (third-party metering) and lowest verified intensity. "
                     "Award conditional on quarterly BOM refresh.",
                     json.dumps({"impact": 40, "evidence": 35, "cost": 25}),
                     json.dumps({"note": "Seeded historical decision", "engine": ENGINE_VERSION,
                                 "factors": DEFAULT_FACTOR_VER})))
        con.execute("INSERT INTO overrides VALUES(?,?,?,?,?,1)",
                    ("SUP-05", 52.0, "Contradiction under investigation; interim cap pending re-metering.",
                     "Marcus Bell", iso_minus(days=3)))
        con.commit()
    finally:
        con.close()
    set_config("factor_version", DEFAULT_FACTOR_VER)
    set_config("retention_months", "84")
    set_config("schema_version", SCHEMA_VERSION)
    audit("SEED", "database", "all", "Synthetic demo dataset generated (seed=19) — 12 suppliers, 3 tenders")
    audit("DECISION_APPROVED", "tender", "TND-03", "SUP-01 · seeded historical approval")
    audit("OVERRIDE_SET", "supplier", "SUP-05", "EQS capped at 52.0 pending re-metering")

def ensure_seeded():
    init_db()
    if not len(load_suppliers()):
        seed_database()

# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION PIPELINE (pure — shared by import, simulation and tests)
# ─────────────────────────────────────────────────────────────────────────────
def issue(row, field, severity, message):
    return {"row": row, "field": field, "severity": severity, "message": message}

def to_canonical(activity, qty, unit):
    cat = next(c for c in ACTIVITY if activity in ACTIVITY[c])
    canonical = ACTIVITY[cat][activity]["unit"]
    u = str(unit).strip().lower()
    table = UNIT_TABLE[canonical]
    if u not in table:
        raise ValueError(f"unit '{unit}' not valid for {activity} (use {' or '.join(sorted(set(table)))})")
    factor = table[u]
    return qty * factor, canonical, (f"{qty:g} {unit} → {qty*factor:g} {canonical}" if factor != 1 else "")

def validate_rows(df, supplier_ids, existing_keys, today):
    """Return (clean_rows, issues). Errors block a row; warnings pass with flags."""
    issues, clean = [], []
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        return [], [issue(0, "columns", "error",
                          f"Missing required column(s): {', '.join(missing)}. Download the template for the exact schema.")]
    seen = set()
    for i, r in df.iterrows():
        row, errs, flags, conv = i + 2, 0, [], ""
        def bad(field, msg):
            nonlocal errs; errs += 1
            issues.append(issue(row, field, "error", msg))
        def warn(field, msg, flag):
            flags.append(flag)
            issues.append(issue(row, field, "warning", msg))
        sid = sget(r, "supplier_id")
        cat = sget(r, "category").lower()
        act = sget(r, "activity_type").lower()
        facility, country = sget(r, "facility"), sget(r, "country")
        ev, vf, dc = sget(r, "evidence_type").lower(), sget(r, "verification").lower(), sget(r, "data_collection").lower()
        ref = sget(r, "evidence_ref")
        if not sid: bad("supplier_id", "supplier_id is required.")
        elif sid not in supplier_ids: bad("supplier_id", f"Unknown supplier_id '{sid}' — see the supplier catalog in Records.")
        if cat not in ACTIVITY:
            bad("category", f"category '{cat}' invalid — use one of {', '.join(CATEGORIES)}.")
        elif act not in ACTIVITY[cat]:
            bad("activity_type", f"activity_type '{act}' invalid for {cat} — use {', '.join(ACTIVITY[cat])}.")
        raw_q = sget(r, "quantity")
        qty = None
        if raw_q == "": bad("quantity", "quantity is required (numeric, ≥ 0).")
        else:
            try:
                qty = float(raw_q)
                if math.isnan(qty) or math.isinf(qty): raise ValueError
            except ValueError:
                bad("quantity", f"quantity '{raw_q}' is not a number — enter plain numeric consumption.")
        q_can, unit_can = qty, sget(r, "unit")
        if qty is not None and act and cat in ACTIVITY and act in ACTIVITY.get(cat, {}):
            try:
                q_can, unit_can, conv = to_canonical(act, qty, sget(r, "unit"))
            except ValueError as e:
                bad("unit", str(e))
            if q_can is not None:
                if q_can < 0: bad("quantity", f"quantity {q_can:g} {unit_can} is negative — consumption must be ≥ 0.")
                elif q_can > MAX_QTY[act]: bad("quantity", f"quantity {q_can:g} {unit_can} exceeds plausibility bound {MAX_QTY[act]:g} — check units or split the period.")
                elif q_can == 0: warn("quantity", "Zero quantity recorded — confirm this is a true zero, not missing data.", "zero_quantity")
        ps = pd.to_datetime(sget(r, "period_start"), errors="coerce")
        pe = pd.to_datetime(sget(r, "period_end"), errors="coerce")
        ps_s = pe_s = ""
        if pd.isna(ps): bad("period_start", f"period_start '{sget(r,'period_start')}' is not a date — use YYYY-MM-DD.")
        else: ps_s = ps.strftime("%Y-%m-%d")
        if pd.isna(pe): bad("period_end", f"period_end '{sget(r,'period_end')}' is not a date — use YYYY-MM-DD.")
        else: pe_s = pe.strftime("%Y-%m-%d")
        if ps_s and pe_s:
            if ps >= pe: bad("period_end", "period_end must be after period_start.")
            if pe.date() > today + timedelta(days=31): bad("period_end", "period_end is in the future — reporting periods cannot be forecast.")
            if ps.date() < today - timedelta(days=1100): bad("period_start", "period_start is older than 3 years — outside the intake window.")
        if not facility: bad("facility", "facility is required (site or plant name).")
        if not country: bad("country", "country is required (ISO code, e.g. DE).")
        if ev not in EVIDENCE_TYPES: bad("evidence_type", f"evidence_type '{ev}' invalid — use {', '.join(EVIDENCE_TYPES)}.")
        if vf not in VERIF: bad("verification", f"verification '{vf}' invalid — use {', '.join(VERIF)}.")
        if dc not in COLLECTION: bad("data_collection", f"data_collection '{dc}' invalid — use {', '.join(COLLECTION)}.")
        if ev in DOC_TYPES and not ref:
            warn("evidence_ref", f"{ev} without evidence_ref — attach the document ID to make this traceable.", "missing_evidence_ref")
        if dc == "estimated" and vf == "third_party":
            warn("verification", "Estimated data marked third-party verified — confirm the verifier actually audited an estimate.", "meta_mismatch")
        key = (sid, act, facility, ps_s, pe_s) if (sid and act and facility and ps_s and pe_s) else None
        if key:
            if key in seen:
                bad("duplicate", f"Duplicate of an earlier row in this file ({sid} · {act} · {ps_s}). Remove one.")
            if key in existing_keys:
                bad("duplicate", f"Matches an existing record ({sid} · {act} · {ps_s}). Safe re-import: use Records › Correct to amend instead.")
            seen.add(key)
        if errs == 0:
            clean.append(dict(supplier_id=sid, category=cat, activity_type=act,
                              quantity=round(q_can, 4), unit=unit_can,
                              period_start=ps_s, period_end=pe_s, facility=facility, country=country,
                              evidence_type=ev, evidence_ref=ref, verification=vf, data_collection=dc,
                              flags=flags, notes=(conv + " · " if conv else "") + sget(r, "notes"),
                              submitted_at=utcnow()))
    return clean, issues

def existing_key_set(recs):
    if not len(recs): return set()
    return set(zip(recs.supplier_id, recs.activity_type, recs.facility, recs.period_start, recs.period_end))

# ─────────────────────────────────────────────────────────────────────────────
# DOMAIN ENGINE (pure, deterministic, versioned — runs headless)
# ─────────────────────────────────────────────────────────────────────────────
def detect_contradictions(recs):
    out = []
    if not len(recs): return out
    for key, g in recs.groupby(["supplier_id", "activity_type", "facility", "period_start", "period_end"]):
        if len(g) < 2: continue
        qmin, qmax = float(g.quantity.min()), float(g.quantity.max())
        if (qmin <= 0 and qmax > 0) or (qmin > 0 and qmax / qmin > 1.25):
            out.append({"key": list(key), "ids": list(g.record_id),
                        "divergence": round(qmax / max(qmin, 1e-9), 2)})
    return out

def doc_score(ev, ref):
    if ev in DOC_TYPES: return 1.0 if ref else 0.4
    if ev == "supplier_declaration": return 0.5 if ref else 0.3
    return 0.0

def evidence_score(sup, recs, today):
    """EQS = 100 · Σ wᵢ·sᵢ. Weights: completeness .25, recency .20, verification .20,
    traceability .15, consistency .20. Recency: 1.0 at ≤45d, linear to 0 at 365d."""
    expected = json.loads(sup["expected"]) if isinstance(sup["expected"], str) else sup["expected"]
    n = len(recs)
    warnings = []
    if n == 0:
        comp = dict(completeness=0.0, recency=0.0, verification=0.0, traceability=0.0, consistency=1.0)
        eqs = round(100 * EQS_WEIGHTS["consistency"], 1)
        return dict(components=comp, points={k: round(100 * EQS_WEIGHTS[k] * v, 1) for k, v in comp.items()},
                    eqs=eqs, grade=grade_for(eqs), age_days=None, contradictions=0,
                    warnings=["No usable records — supplier is a data blind spot."], n=0,
                    unverified_share=0.0, estimated_share=0.0, missing_ref_share=0.0)
    present = set(recs.category)
    completeness = len([c for c in expected if c in present]) / max(1, len(expected))
    newest = pd.to_datetime(recs.period_end).max().date()
    age = max(0, (today - newest).days)
    recency = 1.0 if age <= 45 else max(0.0, 1 - (age - 45) / 320)
    vmap = {"third_party": 1.0, "internal_checked": 0.6, "unverified": 0.15}
    verification = float(recs.verification.map(vmap).fillna(0.15).mean())
    traceability = float(np.mean([doc_score(str(r.evidence_type), str(r.evidence_ref or "")) for r in recs.itertuples()]))
    contras = detect_contradictions(recs)
    all_flags = [f for r in recs.itertuples() for f in flags_of({"flags": r.flags})]
    oor = all_flags.count("out_of_range")
    miss_share = sum(1 for r in recs.itertuples() if "missing_evidence_ref" in flags_of({"flags": r.flags})) / n
    consistency = max(0.0, 1 - 0.25 * len(contras) - 0.15 * oor - (0.1 if miss_share > 0.3 else 0))
    comp = dict(completeness=completeness, recency=recency, verification=verification,
                traceability=traceability, consistency=consistency)
    eqs = round(100 * sum(EQS_WEIGHTS[k] * v for k, v in comp.items()), 1)
    unv = float((recs.verification == "unverified").mean())
    est = float((recs.data_collection == "estimated").mean())
    if age > 120: warnings.append(f"Newest data is {age} days old — request a current reporting period.")
    if unv > 0.5: warnings.append(f"{unv:.0%} of records are unverified — commission internal checks or third-party audit.")
    if est > 0.4: warnings.append(f"{est:.0%} of records are estimates (±30%) — replace with metered or invoiced data.")
    if contras: warnings.append(f"{len(contras)} contradictory duplicate pair(s) — reconcile metering feeds before relying on totals.")
    if miss_share > 0.25: warnings.append(f"{miss_share:.0%} of documented records lack an evidence reference.")
    return dict(components=comp, points={k: round(100 * EQS_WEIGHTS[k] * v, 1) for k, v in comp.items()},
                eqs=eqs, grade=grade_for(eqs), age_days=age, contradictions=len(contras),
                warnings=warnings, n=n, unverified_share=unv, estimated_share=est,
                missing_ref_share=miss_share)

def supplier_emissions(recs, factors):
    """kgCO₂e = quantity × factor. Uncertainty: measured ±5%, calculated ±12%,
    estimated ±30%; combined in quadrature (independent errors assumed)."""
    if not len(recs):
        return dict(total_kg=0.0, abs_unc_kg=0.0, rel_unc=0.0, by_category={}, n=0, measured_share=0.0)
    by_cat, u2 = {}, 0.0
    total = 0.0
    for r in recs.itertuples():
        kg = float(r.quantity) * factors[r.activity_type]["factor"]
        total += kg
        by_cat[r.category] = by_cat.get(r.category, 0.0) + kg
        u2 += (kg * UNC.get(r.data_collection, 0.30)) ** 2
    abs_u = math.sqrt(u2)
    return dict(total_kg=total, abs_unc_kg=abs_u, rel_unc=abs_u / total if total > 0 else 0.0,
                by_category=by_cat, n=len(recs),
                measured_share=float((recs.data_collection == "measured").mean()))

def build_scorecard(sups, recs, factors, today, overrides=None):
    ov = {}
    if overrides is not None and len(overrides):
        ov = dict(zip(overrides.supplier_id, overrides.value))
    ana = recs[recs.status.isin(list(ANALYTICS))]
    rows = []
    for s in sups.itertuples():
        sr = ana[ana.supplier_id == s.supplier_id]
        es = evidence_score(s._asdict(), sr, today)
        em = supplier_emissions(sr, factors)
        expected = json.loads(s.expected)
        coverage = 100 * len([c for c in expected if c in set(sr.category)]) / max(1, len(expected))
        intensity = em["total_kg"] / (s.annual_spend_eur / 1000) if s.annual_spend_eur > 0 else 0.0
        eff = float(ov[s.supplier_id]) if s.supplier_id in ov else es["eqs"]
        rows.append(dict(supplier_id=s.supplier_id, name=s.name, sector=s.sector, country=s.country,
                         spend=s.annual_spend_eur, eqs_model=es["eqs"], eqs=round(eff, 1),
                         overridden=s.supplier_id in ov, grade=grade_for(eff),
                         coverage=round(coverage, 1), total_kg=round(em["total_kg"], 1),
                         unc_kg=round(em["abs_unc_kg"], 1), rel_unc=round(em["rel_unc"], 4),
                         intensity=round(intensity, 2), n_records=es["n"],
                         age_days=es["age_days"], contradictions=es["contradictions"],
                         measured_share=round(em["measured_share"], 3), **{f"c_{k}": round(v, 3) for k, v in es["components"].items()}))
    return pd.DataFrame(rows)

def build_gaps(sups, recs, scorecard, today):
    ana = recs[recs.status.isin(list(ANALYTICS))]
    gaps = []
    sev_w = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    actions = {
        "NO_DATA": "Onboard supplier: request 12 months of activity data with invoices/meter reads.",
        "MISSING_CATEGORY": "Request the missing category dataset; add it to the supplier data-sharing annex.",
        "STALE_DATA": "Request the latest reporting period; set a quarterly submission reminder.",
        "LOW_VERIFICATION": "Escalate to internal check or third-party verification for key records.",
        "MISSING_EVIDENCE": "Collect document IDs (invoice / meter photo / audit cert) for flagged records.",
        "CONTRADICTION": "Reconcile duplicate metering feeds; correct via Records › Correct with reason.",
        "ESTIMATE_HEAVY": "Replace estimates with measured or invoiced activity for material categories.",
    }
    for s in sups.itertuples():
        sr = ana[ana.supplier_id == s.supplier_id]
        sc = scorecard[scorecard.supplier_id == s.supplier_id].iloc[0]
        expected = json.loads(s.expected)
        prio = lambda sev: round(s.annual_spend_eur / 1e6 * sev_w[sev], 2)
        def add(scope, typ, sev, detail):
            gaps.append(dict(supplier_id=s.supplier_id, name=s.name, scope=scope, type=typ,
                             severity=sev, detail=detail, action=actions[typ], priority=prio(sev)))
        if not len(sr):
            add("All", "NO_DATA", "critical", "No usable records in the analytics window.")
            continue
        for c in expected:
            cr = sr[sr.category == c]
            if not len(cr):
                add(CAT_LABEL[c], "MISSING_CATEGORY", "high" if c in ("electricity", "waste") else "medium",
                    f"{CAT_LABEL[c]} is expected for {s.sector} but absent.")
            else:
                age = (today - pd.to_datetime(cr.period_end).max().date()).days
                if age > 240: add(CAT_LABEL[c], "STALE_DATA", "high", f"Newest {CAT_LABEL[c].lower()} record is {age} days old.")
                elif age > 120: add(CAT_LABEL[c], "STALE_DATA", "medium", f"Newest {CAT_LABEL[c].lower()} record is {age} days old.")
        if sc.contradictions and float(sr.quantity.min()) >= 0:
            for cd in detect_contradictions(sr):
                add(CAT_LABEL.get(cd["key"][1], cd["key"][1]), "CONTRADICTION", "high",
                    f"{cd['ids']} diverge ×{cd['divergence']} for {cd['key'][1]} ({cd['key'][3]}).")
        es = evidence_score(s._asdict(), sr, today)
        if es["unverified_share"] > 0.5: add("All", "LOW_VERIFICATION", "medium", f"{es['unverified_share']:.0%} unverified records.")
        if es["missing_ref_share"] > 0.25: add("All", "MISSING_EVIDENCE", "medium", f"{es['missing_ref_share']:.0%} of documented records lack references.")
        if es["estimated_share"] > 0.4: add("All", "ESTIMATE_HEAVY", "medium", f"{es['estimated_share']:.0%} estimated activity (±30%).")
    df = pd.DataFrame(gaps)
    if len(df): df = df.sort_values("priority", ascending=False).reset_index(drop=True)
    return df

def scenario_compute(recs, factors, grid_pct, eff_pct, div_pct):
    """What-if levers: grid decarbonization on Scope-2, efficiency on remaining
    electricity + fuel, landfill→recycling diversion at factor delta."""
    ana = recs[recs.status.isin(list(ANALYTICS))]
    g, e, d = grid_pct / 100, eff_pct / 100, div_pct / 100
    def calc(sr):
        by = supplier_emissions(sr, factors)
        elec = by["by_category"].get("electricity", 0.0)
        fuel = by["by_category"].get("fuel", 0.0)
        land_q = float(sr[sr.activity_type == "waste_landfill"].quantity.sum())
        f_delta = factors["waste_landfill"]["factor"] - factors["waste_recycling"]["factor"]
        grid_save = elec * g
        eff_save = (elec * (1 - g) + fuel) * e
        div_save = land_q * d * f_delta
        return by["total_kg"], grid_save, eff_save, div_save
    B, G, E, D = calc(ana)
    per = []
    for sid, sr in ana.groupby("supplier_id"):
        b, gg, ee, dd = calc(sr)
        per.append(dict(supplier_id=sid, baseline=b, scenario=b - gg - ee - dd,
                        delta_pct=-100 * (gg + ee + dd) / b if b > 0 else 0.0))
    return dict(baseline=B, grid_save=G, eff_save=E, div_save=D,
                total=B - G - E - D, per_supplier=pd.DataFrame(per))

# ─────────────────────────────────────────────────────────────────────────────
# LIVE INTAKE SIMULATION
# ─────────────────────────────────────────────────────────────────────────────
SIM_BASE = {"electricity": 30_000, "fuel": 6_000, "water": 900, "waste": 12_000, "materials": 28_000}

def sim_tick(force_defect=False):
    sups = load_suppliers()
    recs = load_records()
    s = sups.sample(1).iloc[0]
    sid = s.supplier_id
    expected = json.loads(s.expected)
    cat = random.choice(expected)
    act = random.choice(list(ACTIVITY[cat]))
    mat = MATURITY.get(sid, 0.6)
    ps, pe = month_window(1)
    qty = round(random.lognormvariate(math.log(SIM_BASE[cat] * max(0.35, s.annual_spend_eur / 2_500_000)), 0.4), 1)
    unit = ACTIVITY[cat][act]["unit"]
    r = random.random()
    ev, vf, dc = (("meter_read", "third_party", "measured") if r < mat else
                  ("invoice", "internal_checked", "calculated") if r < mat + (1 - mat) * .5 else
                  ("supplier_declaration", "unverified", "estimated"))
    row = dict(supplier_id=sid, category=cat, activity_type=act, quantity=qty, unit=unit,
               period_start=ps.isoformat(), period_end=pe.isoformat(),
               facility=f"{s['name'].split()[0]} Plant 01", country=s.country,
               evidence_type=ev, evidence_ref=f"SIM-{random.randint(1000,9999)}",
               verification=vf, data_collection=dc, notes="Live intake simulation")
    defect = None
    if force_defect or random.random() < 0.14:
        defect = random.choice(["negative", "unit", "supplier", "dates", "duplicate", "missing_ref"])
        if defect == "negative": row["quantity"] = -abs(qty)
        elif defect == "unit": row["unit"] = "kg" if unit != "kg" else "kWh"
        elif defect == "supplier": row["supplier_id"] = "SUP-99"
        elif defect == "dates": row["period_end"] = ps.isoformat(); row["period_start"] = pe.isoformat()
        elif defect == "duplicate" and len(recs):
            ex = recs[recs.supplier_id == sid]
            if len(ex):
                e0 = ex.iloc[0]
                for c in ("activity_type", "category", "facility", "period_start", "period_end", "unit"):
                    row[c] = e0[c]
            else: defect = "missing_ref"; row["evidence_ref"] = ""
        elif defect == "missing_ref": row["evidence_ref"] = ""
    clean, issues = validate_rows(pd.DataFrame([row]), set(sups.supplier_id),
                                  existing_key_set(recs), today_d())
    ok = len(clean) == 1
    rid, msg = "", ""
    if ok:
        rid = insert_records(clean, "simulation", audit_action="SIM_INTAKE")[0]
        n_sim = sql_scalar("SELECT COUNT(*) FROM records WHERE source='simulation'")
        if n_sim and n_sim > 160:
            old = sql_df("SELECT record_id FROM records WHERE source='simulation' ORDER BY created_at ASC LIMIT ?",
                         (n_sim - 160,))
            for orow in old.itertuples():
                sql_exec("DELETE FROM records WHERE record_id=?", (orow.record_id,))
            audit("SIM_PRUNE", "record", len(old), "Simulation buffer capped at 160 records")
        msg = "; ".join(i["message"] for i in issues if i["severity"] == "warning") or "Accepted · validated"
    else:
        msg = "; ".join(i["message"] for i in issues if i["severity"] == "error")[:180]
    evd = dict(ts=datetime.now(timezone.utc).strftime("%H:%M:%S"), sid=sid, name=s["name"],
               act=act, qty=qty, unit=unit, ok=ok, msg=msg, rid=rid, defect=defect or "")
    st.session_state.feed = ([evd] + st.session_state.feed)[:12]
    st.session_state.trend = (st.session_state.trend + [ok])[-48:]
    st.session_state.sim_ok += int(ok)
    st.session_state.sim_bad += int(not ok)
    return evd

# ─────────────────────────────────────────────────────────────────────────────
# IMPORT TEMPLATES
# ─────────────────────────────────────────────────────────────────────────────
def template_valid():
    recs = load_records()
    sups = load_suppliers()
    rows = []
    ps, pe = month_window(1)
    for i, s in enumerate(sups.itertuples()):
        cat = json.loads(s.expected)[i % len(json.loads(s.expected))]
        act = list(ACTIVITY[cat])[0]
        rows.append(dict(supplier_id=s.supplier_id, category=cat, activity_type=act,
                         quantity=round(1000 * (i + 1) * (2 if cat == "materials" else 1), 1),
                         unit=ACTIVITY[cat][act]["unit"], period_start=ps.isoformat(),
                         period_end=pe.isoformat(), facility=f"{s.name.split()[0]} Site A",
                         country=s.country, evidence_type="invoice",
                         evidence_ref=f"INV-2026-{100+i}", verification="internal_checked",
                         data_collection="measured"))
    return pd.DataFrame(rows)[REQUIRED_COLS]

def template_errors():
    ps, pe = month_window(1)
    base = dict(supplier_id="SUP-03", category="electricity", activity_type="grid_electricity",
                quantity=12500, unit="kWh", period_start=ps.isoformat(), period_end=pe.isoformat(),
                facility="Verdant Site A", country="DE", evidence_type="invoice",
                evidence_ref="INV-ERR-DEMO", verification="internal_checked", data_collection="measured")
    rows = [dict(base)]
    rows.append(dict(base, quantity=-500, evidence_ref="INV-ERR-1"))
    rows.append(dict(base, supplier_id="SUP-99", evidence_ref="INV-ERR-2"))
    rows.append(dict(base, unit="kg", evidence_ref="INV-ERR-3"))
    rows.append(dict(base, period_start=pe.isoformat(), period_end=ps.isoformat(), evidence_ref="INV-ERR-4"))
    rows.append(dict(base, evidence_ref=""))
    rows.append(dict(base, evidence_ref="INV-ERR-5"))
    return pd.DataFrame(rows)[REQUIRED_COLS]

# ─────────────────────────────────────────────────────────────────────────────
# EMBEDDED SELF-TEST SUITE (observable acceptance evidence)
# ─────────────────────────────────────────────────────────────────────────────
TEST_DAY = date(2026, 11, 13)

def run_self_tests():
    t0 = time.perf_counter()
    results = []
    F = FACTORS[DEFAULT_FACTOR_VER]["entries"]
    def mk(**kw):
        r = dict(record_id="OBS-T00001", supplier_id="SUP-T1", category="electricity",
                 activity_type="grid_electricity", quantity=10000.0, unit="kWh",
                 period_start=(TEST_DAY - timedelta(days=40)).isoformat(),
                 period_end=(TEST_DAY - timedelta(days=10)).isoformat(),
                 facility="Test Plant", country="DE", evidence_type="meter_read",
                 evidence_ref="DOC-T1", verification="third_party", data_collection="measured",
                 status="validated", flags="[]")
        r.update(kw); return r
    def sup(expected=("electricity", "water", "waste")):
        return {"supplier_id": "SUP-T1", "expected": json.dumps(list(expected)), "annual_spend_eur": 1e6}
    def check(tid, name, expected, actual, tol=None):
        try:
            ok = (abs(float(expected) - float(actual)) <= tol) if tol is not None else (expected == actual)
        except (TypeError, ValueError):
            ok = expected == actual
        results.append(dict(id=tid, test=name, expected=str(expected), actual=str(actual),
                            passed=bool(ok)))
    def safe(tid, name, fn):
        try: fn()
        except Exception as ex:
            results.append(dict(id=tid, test=name, expected="no exception",
                                actual=f"{type(ex).__name__}: {ex}", passed=False))

    safe("T01", "Electricity: 10,000 kWh × 0.2070 = 2,070 kg",
         lambda: check("T01", "Electricity: 10,000 kWh × 0.2070 = 2,070 kg", 2070.0,
                       round(supplier_emissions(pd.DataFrame([mk()]), F)["total_kg"], 4), tol=1e-6))
    def t02():
        q, u, _ = to_canonical("grid_electricity", 2, "MWh")
        kg = q * F["grid_electricity"]["factor"]
        check("T02", "Unit conversion: 2 MWh → 2,000 kWh → 414 kg", 414.0, round(kg, 4), tol=1e-6)
    safe("T02", "Unit conversion MWh→kWh", t02)
    safe("T03", "Diesel: 1,000 L × 2.687 = 2,687 kg",
         lambda: check("T03", "Diesel: 1,000 L × 2.687 = 2,687 kg", 2687.0,
                       round(supplier_emissions(pd.DataFrame([mk(category="fuel", activity_type="diesel",
                             quantity=1000, unit="litre")]), F)["total_kg"], 4), tol=1e-6))
    safe("T04", "Landfill: 10,000 kg × 0.446 = 4,460 kg",
         lambda: check("T04", "Landfill: 10,000 kg × 0.446 = 4,460 kg", 4460.0,
                       round(supplier_emissions(pd.DataFrame([mk(category="waste", activity_type="waste_landfill",
                             quantity=10000, unit="kg")]), F)["total_kg"], 4), tol=1e-6))
    def perfect_recs():
        rows = []
        for i, (cat, act, unit) in enumerate([("electricity", "grid_electricity", "kWh"),
                                              ("water", "water_supply", "m3"), ("waste", "waste_recycling", "kg")]):
            rows.append(mk(record_id=f"OBS-T1000{i}", category=cat, activity_type=act, unit=unit,
                           period_start=(TEST_DAY - timedelta(days=40 + i)).isoformat(),
                           period_end=(TEST_DAY - timedelta(days=10 + i)).isoformat()))
        return pd.DataFrame(rows)
    safe("T05", "Perfect evidence → EQS 100.0",
         lambda: check("T05", "Perfect evidence → EQS 100.0", 100.0,
                       evidence_score(sup(), perfect_recs(), TEST_DAY)["eqs"], tol=1e-6))
    safe("T06", "Empty supplier → EQS 20.0 (consistency floor only)",
         lambda: check("T06", "Empty supplier → EQS 20.0 (consistency floor only)", 20.0,
                       evidence_score(sup(), pd.DataFrame(columns=list(mk().keys())), TEST_DAY)["eqs"], tol=1e-6))
    def t07():
        r = pd.DataFrame([mk(period_end=(TEST_DAY - timedelta(days=205)).isoformat(),
                             period_start=(TEST_DAY - timedelta(days=235)).isoformat())])
        check("T07", "Recency at 205 days → 0.5 (linear decay)", 0.5,
              round(evidence_score(sup(("electricity",)), r, TEST_DAY)["components"]["recency"], 6), tol=1e-6)
    safe("T07", "Recency boundary math", t07)
    def t08():
        df = pd.DataFrame([dict(zip(REQUIRED_COLS, [mk()[c] for c in REQUIRED_COLS]))])
        df.loc[0, "quantity"] = -500
        clean, iss = validate_rows(df, {"SUP-T1"}, set(), TEST_DAY)
        ok = len(clean) == 0 and any(i["field"] == "quantity" and i["severity"] == "error" for i in iss)
        check("T08", "Negative quantity rejected with row-level error", True, ok)
    safe("T08", "Reject negative quantity", t08)
    def t09():
        df = pd.DataFrame([dict(zip(REQUIRED_COLS, [mk()[c] for c in REQUIRED_COLS]))])
        df.loc[0, "supplier_id"] = "SUP-99"
        clean, iss = validate_rows(df, {"SUP-T1"}, set(), TEST_DAY)
        check("T09", "Unknown supplier rejected (referential integrity)", True,
              len(clean) == 0 and any(i["field"] == "supplier_id" for i in iss))
    safe("T09", "Reject unknown supplier", t09)
    def t10():
        df = pd.DataFrame([dict(zip(REQUIRED_COLS, [mk()[c] for c in REQUIRED_COLS]))])
        df.loc[0, "unit"] = "kg"
        clean, iss = validate_rows(df, {"SUP-T1"}, set(), TEST_DAY)
        check("T10", "Wrong unit for activity rejected", True,
              len(clean) == 0 and any(i["field"] == "unit" for i in iss))
    safe("T10", "Reject unit mismatch", t10)
    def t11():
        df = pd.DataFrame([dict(zip(REQUIRED_COLS, [mk()[c] for c in REQUIRED_COLS]))])
        df.loc[0, "period_start"], df.loc[0, "period_end"] = df.loc[0, "period_end"], df.loc[0, "period_start"]
        clean, iss = validate_rows(df, {"SUP-T1"}, set(), TEST_DAY)
        check("T11", "Reversed dates rejected", True,
              len(clean) == 0 and any(i["field"] == "period_end" for i in iss))
    safe("T11", "Reject reversed dates", t11)
    def t12():
        row = dict(zip(REQUIRED_COLS, [mk()[c] for c in REQUIRED_COLS]))
        df = pd.DataFrame([row, dict(row)])
        clean, iss = validate_rows(df, {"SUP-T1"}, set(), TEST_DAY)
        check("T12", "In-file duplicate detected (1 clean, 1 error)", True,
              len(clean) == 1 and any(i["field"] == "duplicate" for i in iss))
    safe("T12", "In-file duplicate detection", t12)
    def t13():
        row = dict(zip(REQUIRED_COLS, [mk()[c] for c in REQUIRED_COLS]))
        key = ("SUP-T1", "grid_electricity", "Test Plant", row["period_start"], row["period_end"])
        clean, iss = validate_rows(pd.DataFrame([row]), {"SUP-T1"}, {key}, TEST_DAY)
        check("T13", "Existing key blocked → safe idempotent re-import", True,
              len(clean) == 0 and any("existing" in i["message"] for i in iss))
    safe("T13", "Safe re-import strategy", t13)
    safe("T14", "Measured uncertainty: ±5% of 2,070 = 103.5 kg",
         lambda: check("T14", "Measured uncertainty: ±5% of 2,070 = 103.5 kg", 103.5,
                       round(supplier_emissions(pd.DataFrame([mk()]), F)["abs_unc_kg"], 4), tol=1e-6))
    def t15():
        ok = (grade_for(85) == "A" and grade_for(84.9) == "B" and grade_for(70) == "B"
              and grade_for(55) == "C" and grade_for(40) == "D" and grade_for(39.9) == "F")
        check("T15", "Grade thresholds A≥85 B≥70 C≥55 D≥40", True, ok)
    safe("T15", "Grade boundaries", t15)
    def t16():
        r = perfect_recs()
        dup = mk(record_id="OBS-T20001", quantity=20000.0)
        rr = pd.concat([r, pd.DataFrame([dup])], ignore_index=True)
        n = len(detect_contradictions(rr))
        cons = evidence_score(sup(), rr, TEST_DAY)["components"]["consistency"]
        check("T16", "Contradiction pair detected; consistency 1.0→0.75", True, n == 1 and abs(cons - 0.75) < 1e-6)
    safe("T16", "Contradiction detection & penalty", t16)
    def t17():
        sups, recs = load_suppliers(), load_records()
        a = build_scorecard(sups, recs, F, TEST_DAY, load_overrides())
        b = build_scorecard(sups, recs, F, TEST_DAY, load_overrides())
        check("T17", "Reproducibility: identical scorecards on identical inputs", True, a.equals(b))
    safe("T17", "Deterministic reproducibility", t17)
    def t18():
        df = pd.DataFrame([{"supplier_id": "SUP-T1", "quantity": 5}])
        clean, iss = validate_rows(df, {"SUP-T1"}, set(), TEST_DAY)
        check("T18", "Missing columns → actionable file-level error", True,
              len(clean) == 0 and iss and iss[0]["field"] == "columns")
    safe("T18", "Missing-column handling", t18)
    def t19():
        sc = scenario_compute(pd.DataFrame([mk()]), F, 50, 0, 0)
        check("T19", "Scenario: 50% grid lever halves 2,070 → 1,035 kg", 1035.0, round(sc["total"], 4), tol=1e-6)
    safe("T19", "Scenario lever arithmetic", t19)
    def t20():
        row = dict(zip(REQUIRED_COLS, [mk()[c] for c in REQUIRED_COLS]))
        row["quantity"] = 2; row["unit"] = "MWh"
        clean, iss = validate_rows(pd.DataFrame([row]), {"SUP-T1"}, set(), TEST_DAY)
        check("T20", "MWh row converts to 2,000 kWh with lineage note", True,
              len(clean) == 1 and clean[0]["quantity"] == 2000 and "→" in clean[0]["notes"])
    safe("T20", "Conversion lineage note", t20)
    ms = round((time.perf_counter() - t0) * 1000, 1)
    return results, all(r["passed"] for r in results), ms

# ─────────────────────────────────────────────────────────────────────────────
# REPORTS
# ─────────────────────────────────────────────────────────────────────────────
REPORT_CSS = """
body{font-family:Georgia,'Times New Roman',serif;background:#F5F7FC;color:#131A33;margin:0;padding:34px 42px;}
h1{font-size:26px;margin:0 0 4px;color:#312E81;} h2{font-size:17px;margin:26px 0 8px;color:#312E81;border-bottom:2px solid #4F46E5;padding-bottom:4px;}
.meta{font-family:Arial,sans-serif;font-size:11px;color:#5A6485;margin-bottom:6px;}
.rule{height:3px;background:linear-gradient(90deg,#312E81,#4F46E5,#0EA5E9,#D97706);border-radius:3px;margin:10px 0 18px;}
table.rt{border-collapse:collapse;width:100%;font-family:Arial,sans-serif;font-size:12px;background:#fff;}
table.rt th{background:#312E81;color:#F3F7EE;padding:7px 9px;text-align:left;}
table.rt td{border-bottom:1px solid #D5DAEE;padding:6px 9px;}
table.rt tr:nth-child(even) td{background:#F1F3FB;}
.note{background:#FEF3C7;border:1px solid #F59E0B;border-radius:8px;padding:10px 14px;font-family:Arial,sans-serif;font-size:12px;color:#92400E;margin:14px 0;}
.ok{background:#DCFCE7;border:1px solid #16A34A;border-radius:8px;padding:10px 14px;font-family:Arial,sans-serif;font-size:12.5px;color:#14532D;margin:14px 0;}
ul{font-family:Arial,sans-serif;font-size:12.5px;}
"""

def report_meta(kind):
    name, role = actor()
    return (f'<div class="meta">Generated {utcnow()} · by {H.escape(name)} ({H.escape(role)}) · '
            f'Engine {ENGINE_VERSION} · Factors {get_factor_version()} · Schema {SCHEMA_VERSION}</div>')

def report_html(kind, sups, recs, sc, gaps, factors_ver):
    fv = factors_ver
    parts = [f"<html><head><style>{REPORT_CSS}</style></head><body>",
             f"<h1>🌿 Verdant IQ — {H.escape(kind)}</h1>", report_meta(kind), '<div class="rule"></div>',
             '<div class="note"><b>SYNTHETIC DEMO DATA.</b> Decision support only — not a certification, '
             'assurance opinion or regulatory compliance statement. Factors are illustrative; replace with a '
             'licensed authoritative set and obtain qualified review before real procurement use.</div>']
    if kind == "Portfolio summary":
        total = sc.total_kg.sum()
        parts += ["<h2>Portfolio position</h2>",
                  f"<ul><li>Suppliers tracked: <b>{len(sc)}</b></li>"
                  f"<li>Reported footprint (partial boundary): <b>{total/1000:,.1f} tCO₂e</b></li>"
                  f"<li>Spend-weighted evidence quality: <b>{np.average(sc.eqs, weights=sc.spend):.1f}/100</b></li>"
                  f"<li>Open data gaps: <b>{len(gaps)}</b> ({int((gaps.severity.isin(['high','critical'])).sum()) if len(gaps) else 0} high/critical)</li></ul>",
                  "<h2>Supplier scorecard</h2>",
                  sc[["supplier_id", "name", "eqs", "grade", "coverage", "total_kg", "intensity", "n_records"]]
                  .rename(columns={"eqs": "EQS", "total_kg": "kgCO2e", "intensity": "kg/€k", "coverage": "coverage %"})
                  .to_html(index=False, escape=True, classes="rt")]
        if len(gaps):
            parts += ["<h2>Priority gaps (top 12)</h2>",
                      gaps.head(12)[["name", "scope", "type", "severity", "action"]]
                      .to_html(index=False, escape=True, classes="rt")]
    elif kind == "Supplier scorecard":
        sid = st.session_state.get("rp_supplier", sc.iloc[0].supplier_id)
        row = sc[sc.supplier_id == sid].iloc[0]
        s = sups[sups.supplier_id == sid].iloc[0]
        sr = recs[(recs.supplier_id == sid) & (recs.status.isin(list(ANALYTICS)))]
        es = evidence_score(s.to_dict(), sr, today_d())
        parts += [f"<h2>{H.escape(s['name'])} · {H.escape(s['sector'])} · {H.escape(s['country'])}</h2>",
                  f'<div class="ok"><b>Evidence Quality Score: {row.eqs:.1f}/100 (Grade {row.grade})</b>'
                  + (" · includes authorized manual override" if row.overridden else "")
                  + f' · Reported footprint {row.total_kg/1000:,.1f} tCO₂e ±{row.rel_unc:.0%}'
                  + f' · Coverage {row.coverage:.0f}% of expected categories</div>',
                  "<h2>Score composition (EQS-1.2.0)</h2>",
                  pd.DataFrame([{"Component": k.title(), "Weight": f"{EQS_WEIGHTS[k]:.0%}",
                                 "Raw (0–1)": round(v, 3), "Points": es["points"][k]}
                                for k, v in es["components"].items()]).to_html(index=False, classes="rt"),
                  "<h2>Data quality warnings</h2><ul>" +
                  ("".join(f"<li>{H.escape(w)}</li>" for w in es["warnings"]) or "<li>None — evidence meets all component thresholds.</li>") + "</ul>",
                  "<h2>Records & lineage (analytics window)</h2>",
                  sr[["record_id", "activity_type", "quantity", "unit", "period_end", "evidence_type",
                      "verification", "data_collection", "status", "source"]]
                  .to_html(index=False, escape=True, classes="rt")]
        sg = gaps[gaps.supplier_id == sid] if len(gaps) else pd.DataFrame()
        if len(sg):
            parts += ["<h2>Open gaps & remediation</h2>",
                      sg[["scope", "type", "severity", "detail", "action"]].to_html(index=False, escape=True, classes="rt")]
    else:  # Tender decision report
        tenders = sql_df("SELECT * FROM tenders")
        tid = st.session_state.get("rp_tender", tenders.iloc[0].tender_id)
        t = tenders[tenders.tender_id == tid].iloc[0]
        cands = json.loads(t.candidates)
        rows = []
        for c in cands:
            r = sc[sc.supplier_id == c["sid"]].iloc[0]
            rows.append(dict(Supplier=r["name"], Bid_EUR=c["bid"], EQS=r.eqs, Grade=r.grade,
                             Coverage_pct=r.coverage, Intensity_kg_per_EURk=r.intensity))
        parts += [f"<h2>{H.escape(t.code)} · {H.escape(t.title)}</h2>",
                  f"<ul><li>Budget: {fmt_eur(t.budget_eur)} · Deadline: {t.deadline} · Status: <b>{t.status}</b></li></ul>",
                  "<h2>Candidate comparison</h2>",
                  pd.DataFrame(rows).to_html(index=False, escape=True, classes="rt")]
        dec = sql_df("SELECT * FROM decisions WHERE tender_id=? ORDER BY decision_id DESC LIMIT 1", (tid,))
        if len(dec):
            d = dec.iloc[0]
            parts += ["<h2>Human decision (authoritative)</h2>",
                      f'<div class="ok"><b>{H.escape(d.status.upper())}</b> · supplier {H.escape(d.approved_supplier or "—")} '
                      f'· by {H.escape(d.actor)} ({H.escape(d.role)}) at {H.escape(d.ts)}<br>'
                      f'Reason: {H.escape(d.comment)}</div>',
                      f'<div class="meta">Weights: {H.escape(d.weights)} · Snapshot: {H.escape(d.snapshot)[:400]}…</div>']
        else:
            parts += ['<div class="note">No human decision recorded yet — comparison above is provisional analysis, not an award.</div>']
    parts += [f"<h2>Reference factors · {H.escape(fv)} (published {FACTORS[fv]['published']})</h2>",
              pd.DataFrame([{"Activity": a, "Factor (kgCO₂e/unit)": v["factor"], "Unit": v["unit"], "Source": v["source"]}
                            for a, v in FACTORS[fv]["entries"].items()]).to_html(index=False, escape=True, classes="rt"),
              f'<div class="meta">{H.escape(FACTOR_NOTE)}</div>',
              "<h2>Calculation boundary</h2><ul>"
              "<li>Operational records only: Scope 1 fuel, Scope 2 location-based electricity, water, waste, cradle-to-gate materials.</li>"
              "<li>Not a full lifecycle assessment; upstream transport, use-phase and end-of-life excluded in MVP.</li>"
              "<li>Uncertainty: measured ±5%, calculated ±12%, estimated ±30%, combined in quadrature.</li></ul>",
              "</body></html>"]
    return "".join(parts)

# ─────────────────────────────────────────────────────────────────────────────
# SHARED UI
# ─────────────────────────────────────────────────────────────────────────────
def render_header(subtitle):
    p = pal()
    name, role = actor()
    leaf = ('<svg width="42" height="42" viewBox="0 0 42 42"><defs>'
            '<linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">'
            '<stop offset="0" stop-color="#6366F1"/><stop offset="1" stop-color="#312E81"/></linearGradient></defs>'
            '<rect x="1" y="1" width="40" height="40" rx="12" fill="url(#lg)"/>'
            '<path d="M21 33c-7-4-10-9-10-16 7 0 12 3 14 9 1-8 4-12 8-14 1 9-2 17-12 21z" fill="#F3F7EE" opacity=".95"/>'
            '<path d="M21 33c0-8 2-13 7-18" stroke="#312E81" stroke-width="1.4" fill="none"/></svg>')
    st.markdown(
        f'<div class="v-hero">{leaf}<div><div class="v-title">Verdant IQ</div>'
        f'<div class="v-tag">Sustainable Procurement & Supplier Impact Analyzer · {H.escape(subtitle)}</div></div>'
        f'<div style="margin-left:auto;display:flex;gap:6px;flex-wrap:wrap;">'
        f'<span class="chip demo">⚠ SYNTHETIC DEMO DATA</span>'
        f'<span class="chip">👤 {H.escape(name)} · {H.escape(role)}</span>'
        f'<span class="chip">⚙ {ENGINE_VERSION}</span>'
        f'<span class="chip">📚 {get_factor_version()}</span>'
        f'<span class="chip">🗓 {today_d().isoformat()}</span></div></div><div class="v-rule"></div>',
        unsafe_allow_html=True)

def render_footer():
    st.markdown(
        f'<div style="margin-top:30px;font-size:11px;color:{pal()["muted"]};border-top:1px solid {pal()["line"]};padding-top:10px;">'
        f'Verdant IQ · local SQLite MVP · synthetic demo data · decision support only — human approval required for awards · '
        f'Engine {ENGINE_VERSION} · Factors {get_factor_version()} · open-source dependencies, no API keys</div>',
        unsafe_allow_html=True)

def render_sidebar():
    with st.sidebar:
        st.markdown("### 🌿 Verdant IQ")
        st.caption("Evidence quality · impact comparison · data-gap intelligence for procurement.")
        st.selectbox("Acting as", list(ROLES), key="role",
                     format_func=lambda r: f"{r} — {ROLES[r]['name']}")
        st.caption(f"Permissions: {', '.join(sorted(ROLES[st.session_state.role]['perms']))}")
        st.divider()
        st.radio("Navigate", PAGES, key="nav", label_visibility="collapsed")
        st.divider()
        st.toggle("🌙 Dusk mode (off = daylight)", key="dusk")
        st.toggle("▶ Live intake simulation", key="live_sim")
        st.selectbox("Intake cadence", ["Relaxed · 5s", "Normal · 2.5s", "Fast · 1.2s"], key="sim_speed_label")
        st.divider()
        with st.expander("ℹ About & licenses"):
            st.markdown("**Open-source stack:** Streamlit (Apache-2.0), pandas (BSD-3), "
                        "NumPy (BSD-3), Plotly (MIT), openpyxl (MIT), SQLite (public domain). "
                        "All permissive for commercial use. No paid APIs, no keys, no telemetry. "
                        "Data is synthetic; see Admin › Product docs for the threat model and runbook.")
        cfg = load_config()
        if cfg.get("schema_version") != SCHEMA_VERSION:
            st.warning("Schema version differs from app — use Admin › Reset to rebuild the demo DB.")
        st.caption(f"DB: {DB_PATH.name} · evidence files: {EVIDENCE_DIR.name}/")

SIM_SPEED = {"Relaxed · 5s": 5.0, "Normal · 2.5s": 2.5, "Fast · 1.2s": 1.2}

def load_ctx():
    sups, recs = load_suppliers(), load_records()
    sc = build_scorecard(sups, recs, get_factors(), today_d(), load_overrides())
    gaps = build_gaps(sups, recs, sc, today_d())
    return sups, recs, sc, gaps

# ─────────────────────────────────────────────────────────────────────────────
# PAGE 1 — COMMAND CENTER (live)
# ─────────────────────────────────────────────────────────────────────────────
def page_command():
    render_header("Command Center")
    sups, recs, sc, gaps = load_ctx()
    live = st.session_state.live_sim
    interval = SIM_SPEED[st.session_state.sim_speed_label] if live else None

    def live_body():
        if st.session_state.live_sim:
            sim_tick()
        sups2, recs2, sc2, gaps2 = load_ctx()
        ana = recs2[recs2.status.isin(list(ANALYTICS))]
        w_eqs = float(np.average(sc2.eqs, weights=sc2.spend)) if sc2.spend.sum() > 0 else 0.0
        total = float(sc2.total_kg.sum())
        rel = float(np.average(sc2.rel_unc, weights=sc2.total_kg.clip(lower=1)))
        pend = int((recs2.status == "in_review").sum())
        open_t = int((sql_df("SELECT status FROM tenders").status != "decided").sum())
        hi = int(gaps2.severity.isin(["high", "critical"]).sum()) if len(gaps2) else 0
        cols = st.columns(6)
        cards = [
            kpi("Suppliers", len(sups2), f"{len(sc2[sc2.grade.isin(['A','B'])])} at grade A/B", "#4338CA"),
            kpi("Records", len(recs2), f"{len(ana)} in analytics · {int((recs2.status=='draft').sum())} drafts", "#0E7490"),
            kpi("Portfolio EQS", f"{w_eqs:.1f}", f"spend-weighted · grade {grade_for(w_eqs)}", "#0EA5E9"),
            kpi("Footprint", fmt_t(total), f"partial boundary · ±{rel:.0%}", "#2563EB"),
            kpi("Open gaps", len(gaps2), f"{hi} high/critical severity", "#D97706"),
            kpi("Awaiting review", pend + open_t, f"{pend} records · {open_t} tenders", "#C026D3"),
        ]
        for c, h in zip(cols, cards):
            c.markdown(h, unsafe_allow_html=True)
        st.markdown("")
        lc, rc = st.columns([1.55, 1])
        with lc:
            dot = "pulse-dot" if st.session_state.live_sim else "pulse-dot off"
            state = "LIVE INTAKE · running" if st.session_state.live_sim else "INTAKE PAUSED"
            st.markdown(f'<div style="display:flex;align-items:center;gap:8px;margin:2px 0 8px;">'
                        f'<span class="{dot}"></span><b style="font-size:13px;">{state}</b>'
                        f'<span class="chip">✔ {st.session_state.sim_ok} accepted</span>'
                        f'<span class="chip" style="color:#DC2626;">✕ {st.session_state.sim_bad} flagged</span></div>',
                        unsafe_allow_html=True)
            feed_html = ""
            for e in st.session_state.feed:
                cls = "feed-item" if e["ok"] else "feed-item bad"
                icon = "✅" if e["ok"] else "⛔"
                tail = e["rid"] if e["ok"] else e["msg"]
                feed_html += (f'<div class="{cls}"><span>{icon}</span>'
                              f'<div style="flex:1;"><b>{H.escape(e["name"])}</b> · {e["act"]} '
                              f'{e["qty"]:,.0f} {e["unit"]}<br><span style="color:{pal()["muted"]};">{H.escape(tail[:110])}</span></div>'
                              f'<span class="t">{e["ts"]}Z</span></div>')
            st.markdown(feed_html or '<div class="feed-item">Warming up intake…</div>', unsafe_allow_html=True)
        with rc:
            trend = st.session_state.trend or [True]
            fig = go.Figure(go.Bar(y=[1] * len(trend),
                                   marker_color=["#16A34A" if t else "#DC2626" for t in trend]))
            fig.update_xaxes(visible=False); fig.update_yaxes(visible=False)
            style_fig(fig, height=110, legend=False)
            fig.update_layout(margin=dict(l=0, r=0, t=6, b=0), bargap=0.25)
            st.caption("Intake pulse — green accepted · red rejected by validation")
            show_fig(fig, key="cc_pulse")
            rate = 100 * sum(trend) / len(trend)
            st.markdown(f'<div class="v-card" style="padding:12px 14px;"><b style="font-size:13px;">Acceptance rate {rate:.0f}%</b>'
                        f'<div style="font-size:12px;color:{pal()["muted"]};">Every submission runs the same validator as file import. '
                        f'Simulation buffer capped at 160 records.</div></div>', unsafe_allow_html=True)
            if st.button("⚡ Inject a defective submission", key="cc_defect"):
                sim_tick(force_defect=True)
            st.caption("Try it — watch the validator catch bad units, negatives, duplicates and unknown suppliers in real time.")

    frag = getattr(st, "fragment", None)
    if frag is not None:
        frag(run_every=interval)(live_body)()
    else:
        live_body()
        if st.button("▸ Advance intake one tick", key="cc_manual_tick"):
            sim_tick(); st.rerun()

    with st.expander("🧭 5-minute demo script — the full procurement loop"):
        c1, c2, c3, c4 = st.columns(4)
        st.markdown("**1 ▸ Import** the sample file (valid + broken rows) and watch row-level errors → "
                    "**2 ▸ Analyze** evidence scores and run a what-if scenario → "
                    "**3 ▸ Review** a tender as Marcus Bell and approve with a reason → "
                    "**4 ▸ Export** the traceable HTML report. Reset anytime in Admin.")
        if c1.button("📥 Import demo file"): jump(PAGES[1])
        if c2.button("🧮 Open analysis"): jump(PAGES[3])
        if c3.button("⚖️ Review a tender"): jump(PAGES[5])
        if c4.button("📄 Export report"): jump(PAGES[6])

    st.markdown("")
    g1, g2 = st.columns(2)
    with g1:
        d = sc.sort_values("eqs")
        fig = go.Figure(go.Bar(x=d.eqs, y=d.name, orientation="h",
                               marker_color=[grade_colors()[g] for g in d.grade],
                               text=[f"{g} · {v:.0f}" for g, v in zip(d.grade, d.eqs)],
                               textposition="outside", cliponaxis=False))
        fig.add_vline(x=70, line_dash="dash", line_color="#D97706",
                      annotation_text="review threshold 70", annotation_font_size=11)
        fig.update_xaxes(range=[0, 108])
        style_fig(fig, 380, "Evidence Quality Score by supplier", legend=False)
        show_fig(fig, key="cc_eqs")
    with g2:
        fig = go.Figure(go.Scatter(
            x=sc.intensity, y=sc.eqs, mode="markers+text",
            text=sc.name.str.split().str[0], textposition="top center", textfont_size=10,
            marker=dict(size=np.sqrt(sc.spend) / 55 + 10, color=[grade_colors()[g] for g in sc.grade],
                        opacity=.85, line=dict(width=1, color=pal()["surface"])),
            customdata=np.stack([sc.name, sc.spend, sc.coverage], axis=-1),
            hovertemplate="<b>%{customdata[0]}</b><br>Intensity %{x:.1f} kg/€k · EQS %{y:.1f}"
                          "<br>Spend €%{customdata[1]:,.0f} · coverage %{customdata[2]:.0f}%<extra></extra>"))
        med = float(sc.intensity.median())
        fig.add_vline(x=med, line_dash="dot", line_color=pal()["muted"])
        fig.add_hline(y=70, line_dash="dot", line_color=pal()["muted"])
        for x, y, t in [(0.05, 0.97, "★ Leaders"), (0.95, 0.97, "Verify & coach"),
                        (0.05, 0.06, "Data blind spots"), (0.95, 0.06, "Engage on impact")]:
            fig.add_annotation(xref="paper", yref="paper", x=x, y=y, text=t, showarrow=False,
                               font=dict(size=11, color=pal()["muted"]),
                               xanchor="left" if x < .5 else "right")
        style_fig(fig, 380, "Impact intensity vs evidence quality (bubble = spend)", legend=False)
        fig.update_xaxes(title="kgCO₂e per €k spend"); fig.update_yaxes(title="EQS", range=[0, 105])
        show_fig(fig, key="cc_scatter")
    g3, g4 = st.columns(2)
    with g3:
        top = sc.sort_values("total_kg", ascending=False).head(8)
        ana = recs[recs.status.isin(list(ANALYTICS))]
        F = get_factors()
        fig = go.Figure()
        for cat in CATEGORIES:
            vals = []
            for sid in top.supplier_id:
                sr = ana[(ana.supplier_id == sid) & (ana.category == cat)]
                vals.append(supplier_emissions(sr, F)["total_kg"] / 1000)
            fig.add_bar(x=top.name.str.split().str[0], y=vals, name=CAT_LABEL[cat],
                        marker_color=cat_colors()[cat])
        fig.update_layout(barmode="stack")
        style_fig(fig, 360, "Reported footprint by category · top 8 (tCO₂e)")
        fig.update_yaxes(title="tCO₂e")
        show_fig(fig, key="cc_stack")
    with g4:
        if len(gaps):
            sev = gaps.severity.value_counts()
            fig = go.Figure(go.Pie(labels=[s.title() for s in sev.index], values=sev.values, hole=.62,
                                   marker=dict(colors=[SEV_COLOR[s] for s in sev.index]),
                                   textinfo="label+value", textfont_size=12))
            style_fig(fig, 360, f"Open data gaps · {len(gaps)} findings")
            show_fig(fig, key="cc_gaps")
        else:
            st.success("No open data gaps — portfolio evidence is complete. 🎉")
    st.markdown("#### 🧾 Recent audit trail")
    aud = load_audit().head(8)[["ts", "actor", "action", "entity_id", "detail"]]
    st.dataframe(aud, hide_index=True, width="stretch", height=250)

# ─────────────────────────────────────────────────────────────────────────────
# PAGE 2 — IMPORT & VALIDATE
# ─────────────────────────────────────────────────────────────────────────────
def page_import():
    render_header("Import & Validate — CSV / XLSX with row-level errors and preserved originals")
    sups, recs = load_suppliers(), load_records()
    c1, c2, c3 = st.columns(3)
    c1.download_button("⬇ Valid sample CSV (12 rows)", template_valid().to_csv(index=False).encode(),
                       "verdant_sample_valid.csv", "text/csv", key="im_tpl_ok")
    c2.download_button("⬇ Broken sample CSV (5 errors, 1 warning)", template_errors().to_csv(index=False).encode(),
                       "verdant_sample_errors.csv", "text/csv", key="im_tpl_bad")
    schema_doc = pd.DataFrame([
        {"column": c, "rule": r} for c, r in [
            ("supplier_id", "must exist in catalog (SUP-01…SUP-12)"),
            ("category / activity_type", f"{' · '.join(CATEGORIES)}; activity must match category"),
            ("quantity / unit", "numeric ≥ 0, plausibility bound; MWh→kWh, t→kg auto-converted"),
            ("period_start / period_end", "YYYY-MM-DD, start < end, not future, ≤ 3 years old"),
            ("evidence_type", ", ".join(EVIDENCE_TYPES)),
            ("verification / data_collection", f"{' / '.join(VERIF)} · {' / '.join(COLLECTION)}"),
            ("duplicate key", "supplier+activity+facility+period — existing keys blocked (safe re-import)"),
        ]])
    with c3.popover("📐 Schema rules"):
        st.dataframe(schema_doc, hide_index=True, width="stretch")
    st.markdown("")
    up = st.file_uploader("Drop a supplier activity file (.csv or .xlsx, ≤ 8 MB)",
                          type=["csv", "xlsx"], key="im_up")
    if up is None:
        st.info("No file yet — download a sample above and upload it here. The broken sample demonstrates "
                "actionable row-level rejection without touching existing records.")
    else:
        raw = up.getvalue()
        if len(raw) > 8 * 1024 * 1024:
            st.error("File exceeds the 8 MB intake limit. Split it by period or supplier."); return
        try:
            df = pd.read_csv(io.BytesIO(raw)) if up.name.lower().endswith(".csv") else \
                 pd.read_excel(io.BytesIO(raw), engine="openpyxl")
        except ImportError:
            st.error("Excel support needs openpyxl — run: pip install openpyxl"); return
        except Exception as ex:
            st.error(f"Could not parse '{up.name}': {ex}. Save as UTF-8 CSV or .xlsx and retry."); return
        if not len(df):
            st.error("File contains zero data rows — nothing to import."); return
        clean, issues = validate_rows(df, set(sups.supplier_id), existing_key_set(recs), today_d())
        errs = [i for i in issues if i["severity"] == "error"]
        warns = [i for i in issues if i["severity"] == "warning"]
        sha = hashlib.sha256(raw).hexdigest()
        m1, m2, m3, m4 = st.columns(4)
        m1.markdown(kpi("Rows read", len(df), up.name, "#2563EB"), unsafe_allow_html=True)
        m2.markdown(kpi("Valid", len(clean), "ready to commit", "#4338CA"), unsafe_allow_html=True)
        m3.markdown(kpi("Errors", len(errs), "block their rows", "#DC2626"), unsafe_allow_html=True)
        m4.markdown(kpi("Warnings", len(warns), "import with flags", "#D97706"), unsafe_allow_html=True)
        t1, t2, t3 = st.tabs([f"✅ Valid preview ({len(clean)})", f"⛔ Issues ({len(issues)})", "🔐 File fingerprint"])
        with t1:
            if clean:
                st.dataframe(pd.DataFrame(clean).drop(columns=["flags", "submitted_at"]),
                             hide_index=True, width="stretch", height=280)
            else:
                st.warning("No valid rows — fix the errors below and re-upload.")
        with t2:
            if issues:
                idf = pd.DataFrame(issues)
                idf["severity"] = idf.severity.map({"error": "⛔ error", "warning": "⚠ warning"})
                st.dataframe(idf, hide_index=True, width="stretch", height=280)
                st.download_button("⬇ Download error report (CSV)", pd.DataFrame(issues).to_csv(index=False).encode(),
                                   f"errors_{up.name}.csv", "text/csv", key="im_err_dl")
            else:
                st.success("Zero issues — every row passed all 14 validation checks.")
        with t3:
            st.markdown(f"**SHA-256** `{sha}`")
            st.caption("The original bytes are preserved in evidence_store/ on commit; the database keeps "
                       "filename + checksum + row counts. Validated source data is never silently overwritten.")
        strict = st.checkbox("Strict mode — block the whole file if any row has an error", value=False, key="im_strict")
        blocked = (strict and errs) or not clean
        if st.button(f"📥 Commit {len(clean)} valid rows", type="primary", key="im_commit",
                     disabled=blocked or not can("import"), help=gate_hint("import")):
            stored = EVIDENCE_DIR / f"{sha}_{up.name}"
            if not stored.exists(): stored.write_bytes(raw)
            ids = insert_records(clean, f"import:{up.name}", import_file=up.name, import_sha=sha)
            name, _ = actor()
            sql_exec("INSERT INTO imports(ts,filename,sha256,stored_path,rows_total,rows_ok,rows_err,actor) "
                     "VALUES(?,?,?,?,?,?,?,?)",
                     (utcnow(), up.name, sha, str(stored), len(df), len(clean), len(df) - len(clean), name))
            audit("IMPORT_COMMIT", "file", up.name,
                  json.dumps({"ok": len(clean), "blocked": len(df) - len(clean), "sha": sha[:16]}))
            st.success(f"Imported {len(clean)} records ({ids[0]}…{ids[-1]}). "
                       f"{len(df)-len(clean)} row(s) skipped safely — existing records untouched.")
            st.toast("Import committed ✔", icon="📥")
        if blocked and can("import"):
            st.caption("Commit is blocked: no valid rows, or strict mode is on with errors present.")
        if not can("import"):
            st.caption("🔒 Your role is read-only for intake — switch to Analyst or Administrator to commit.")
    st.markdown("#### Import history & preserved originals")
    hist = sql_df("SELECT * FROM imports ORDER BY id DESC")
    if len(hist):
        st.dataframe(hist[["ts", "filename", "rows_total", "rows_ok", "rows_err", "actor", "sha256"]],
                     hide_index=True, width="stretch")
        files = sorted(EVIDENCE_DIR.glob("*"))
        if files:
            with st.expander(f"🗄 Original source files ({len(files)})"):
                for f in files[:10]:
                    b = f.read_bytes()
                    st.download_button(f"⬇ {f.name} ({len(b)/1024:.1f} KB)", b, f.name, key=f"im_orig_{f.name}")
    else:
        st.caption("No imports yet — history, checksums and originals will appear here after your first commit.")

# ─────────────────────────────────────────────────────────────────────────────
# PAGE 3 — RECORDS
# ─────────────────────────────────────────────────────────────────────────────
def page_records():
    render_header("Records — lifecycle, lineage, corrections and bulk actions")
    sups, recs = load_suppliers(), load_records()
    views = {"All records": None, "Exceptions & flags": "exc", "Awaiting review": "in_review",
             "Approved": "approved", "Drafts": "draft", "Simulation intake": "sim", "Archived": "archived"}
    f0, f1, f2, f3 = st.columns([1.2, 1.2, 1, 1])
    view = f0.selectbox("Saved view", list(views), key="rc_view")
    fsup = f1.multiselect("Supplier", sups.name.tolist(), key="rc_sup")
    fcat = f2.multiselect("Category", CATEGORIES, format_func=lambda c: CAT_LABEL[c], key="rc_cat")
    fsrc = f3.selectbox("Sort by", ["Newest submitted", "Quantity ↓", "Supplier", "Status"], key="rc_sort")
    q = st.text_input("🔎 Search record ID, facility, activity or notes", key="rc_q")
    df = recs.copy()
    v = views[view]
    if v == "exc": df = df[(df.status == "rejected") | (df.flags.str.contains("missing_evidence_ref|contradiction|out_of_range", na=False))]
    elif v == "sim": df = df[df.source == "simulation"]
    elif v: df = df[df.status == v]
    if fsup: df = df[df.name.isin([])] if False else df[df.supplier_id.isin(sups[sups.name.isin(fsup)].supplier_id)]
    if fcat: df = df[df.category.isin(fcat)]
    if q:
        mask = df[["record_id", "facility", "activity_type", "notes", "supplier_id"]].astype(str)\
               .apply(lambda col: col.str.contains(q, case=False, na=False)).any(axis=1)
        df = df[mask]
    df = {"Newest submitted": df.sort_values("submitted_at", ascending=False),
          "Quantity ↓": df.sort_values("quantity", ascending=False),
          "Supplier": df.sort_values(["supplier_id", "period_end"]),
          "Status": df.sort_values(["status", "supplier_id"])}[fsrc]
    size = st.select_slider("Rows per page", [10, 25, 50, 100], value=25, key="rc_size")
    pages = max(1, math.ceil(len(df) / size))
    page = st.number_input(f"Page (of {pages})", 1, pages, 1, key="rc_page")
    sl = df.iloc[(page - 1) * size: page * size]
    st.caption(f"Showing {len(sl)} of {len(df)} matching records · {len(recs)} total in database")
    st.dataframe(sl[["record_id", "supplier_id", "category", "activity_type", "quantity", "unit",
                     "period_start", "period_end", "evidence_type", "verification", "status", "source"]],
                 hide_index=True, width="stretch", height=340,
                 column_config={"quantity": st.column_config.NumberColumn(format="%.1f")})
    if not len(df):
        st.info("No records match these filters."); return
    st.markdown("#### 🔬 Record detail & lifecycle")
    rid = st.selectbox("Open record", sl.record_id.tolist(), key="rc_open")
    r = recs[recs.record_id == rid].iloc[0]
    s = sups[sups.supplier_id == r.supplier_id].iloc[0]
    F = get_factors()
    kg = float(r.quantity) * F[r.activity_type]["factor"]
    u = kg * UNC.get(r.data_collection, .3)
    d1, d2 = st.columns(2)
    with d1:
        st.markdown(f'<div class="v-card"><b style="font-size:15px;">{r.record_id}</b> '
                    f'<span class="chip">{r.status}</span><br>'
                    f'<div style="font-size:13px;margin-top:8px;">{H.escape(s["name"])} · {CAT_LABEL[r.category]} · '
                    f'{ACTIVITY[r.category][r.activity_type]["label"]}<br>'
                    f'<b>{float(r.quantity):,.1f} {r.unit}</b> · {r.period_start} → {r.period_end}<br>'
                    f'Facility: {H.escape(r.facility)} ({r.country})<br>'
                    f'Evidence: {r.evidence_type} {("· " + H.escape(r.evidence_ref)) if r.evidence_ref else ""} · '
                    f'{r.verification} · {r.data_collection}<br>'
                    f'Computed: <b>{kg:,.1f} kgCO₂e ±{u:,.1f}</b> ({UNC.get(r.data_collection,.3):.0%})'
                    f'</div></div>', unsafe_allow_html=True)
        fl = flags_of(r)
        if fl: st.markdown(" ".join(f'<span class="chip" style="color:#D97706;">⚠ {f}</span>' for f in fl),
                           unsafe_allow_html=True)
    with d2:
        chain = f"corrects → {r.corrects}" if r.corrects else "original entry"
        st.markdown(f'<div class="v-card"><b>🧬 Lineage</b><div style="font-size:12.5px;margin-top:6px;">'
                    f'Source: <code>{H.escape(r.source)}</code><br>'
                    f'File: {H.escape(r.import_file) or "—"} · SHA: <code>{(r.import_sha or "")[:16] or "—"}</code><br>'
                    f'Chain: {chain} · Schema {r.schema_version} · Factors {r.factor_version}<br>'
                    f'Submitted {r.submitted_at} · Updated {r.updated_at}</div></div>', unsafe_allow_html=True)
        hist = sql_df("SELECT ts,actor,action,detail FROM audit WHERE entity_id LIKE ? ORDER BY id DESC LIMIT 6",
                      (f"%{rid}%",))
        if len(hist): st.dataframe(hist, hide_index=True, width="stretch", height=150)
    b1, b2, b3, b4 = st.columns(4)
    if r.status == "draft" and b1.button("✔ Validate", key="rc_val", disabled=not can("edit"), help=gate_hint("edit")):
        set_status(rid, "validated"); st.toast(f"{rid} validated"); st.rerun()
    if r.status == "validated" and b2.button("📨 Submit for review", key="rc_sub", disabled=not can("submit"), help=gate_hint("submit")):
        set_status(rid, "in_review"); st.toast(f"{rid} sent to reviewer"); st.rerun()
    if r.status == "in_review":
        reason = st.text_input("Review comment (required to reject)", key="rc_rev_reason")
        if b2.button("✅ Approve record", key="rc_ap", disabled=not can("approve"), help=gate_hint("approve")):
            set_status(rid, "approved", reason or "Approved"); st.toast(f"{rid} approved"); st.rerun()
        if b3.button("⛔ Reject record", key="rc_rej", disabled=not can("approve"), help=gate_hint("approve")):
            if not reason.strip(): st.warning("A rejection reason is required.")
            else: set_status(rid, "rejected", reason); st.toast(f"{rid} rejected"); st.rerun()
    if r.status not in ("archived",) and b4.button("🗄 Archive", key="rc_arch", disabled=not can("archive"), help=gate_hint("archive")):
        st.session_state.undo.append((rid, r.status))
        set_status(rid, "archived", "Archived by operator"); st.toast(f"{rid} archived — undo below"); st.rerun()
    if r.status == "archived" and b1.button("♻ Restore", key="rc_rest", disabled=not can("restore"), help=gate_hint("restore")):
        set_status(rid, "validated", "Restored from archive"); st.rerun()
    with st.expander("✏️ Correct this record (creates a linked new version — original is archived, never overwritten)"):
        if not can("edit"):
            st.caption("🔒 Requires Analyst or Administrator.")
        else:
            cc1, cc2, cc3 = st.columns(3)
            nq = cc1.number_input("Corrected quantity", 0.0, float(MAX_QTY[r.activity_type]), float(r.quantity), key="rc_cq")
            nev = cc2.selectbox("Evidence type", EVIDENCE_TYPES, index=EVIDENCE_TYPES.index(r.evidence_type), key="rc_ce")
            nvf = cc3.selectbox("Verification", VERIF, index=VERIF.index(r.verification), key="rc_cv")
            cref = st.text_input("Evidence reference", r.evidence_ref, key="rc_cr")
            creason = st.text_input("Correction reason (required)", key="rc_cwhy",
                                    placeholder="e.g. Meter reconciliation against credit note CN-…")
            if st.button("💾 Save correction", key="rc_csave", type="primary"):
                if not creason.strip():
                    st.warning("A correction reason is required for the audit trail.")
                else:
                    corr = {c: r[c] for c in RECORD_COLS}
                    corr.update(quantity=nq, evidence_type=nev, verification=nvf, evidence_ref=cref,
                                corrects=rid, status="validated", flags=[],
                                notes=f"Correction · {creason}", submitted_at=utcnow())
                    new_id = insert_records([corr], "manual", audit_action="RECORD_CORRECTED")[0]
                    set_status(rid, "archived", f"Superseded by {new_id}: {creason}")
                    st.success(f"Created {new_id} linked to {rid}. Original preserved in archive.")
                    st.rerun()
    if st.session_state.undo:
        st.markdown("#### ↩ Undo recent archives")
        for i, (urid, prev) in enumerate(list(st.session_state.undo)[-5:]):
            u1, u2 = st.columns([3, 1])
            u1.caption(f"{urid} (was: {prev})")
            if u2.button("Undo", key=f"rc_undo_{i}_{urid}"):
                set_status(urid, prev, "Undo archive")
                st.session_state.undo = [x for x in st.session_state.undo if x[0] != urid]
                st.rerun()
    with st.expander("📦 Bulk archive (Administrator)"):
        picks = st.multiselect("Select records", df.record_id.tolist()[:100], key="rc_bulk")
        if st.button(f"Archive {len(picks)} selected", key="rc_bulk_go",
                     disabled=not can("admin") or not picks, help=gate_hint("admin")):
            for prid in picks:
                prev = recs[recs.record_id == prid].iloc[0].status
                st.session_state.undo.append((prid, prev))
                set_status(prid, "archived", "Bulk archive")
            st.toast(f"{len(picks)} archived — undo available above"); st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# PAGE 4 — IMPACT ANALYSIS (live scenario workbench)
# ─────────────────────────────────────────────────────────────────────────────
def page_analysis():
    render_header("Impact Analysis — deterministic engine, live what-if levers, full explanations")
    sups, recs, sc, gaps = load_ctx()
    left, main = st.columns([0.95, 2.3])
    with left:
        with st.container(border=True):
            st.markdown("##### 🎛 Scenario controls · applied live")
            default_sups = sc.sort_values("spend", ascending=False).head(6).name.tolist()
            picks = st.multiselect("Suppliers in scope", sups.name.tolist(), default=default_sups, key="an_sups")
            metric = st.radio("Metric", ["Absolute (tCO₂e)", "Intensity (kg/€k spend)"], key="an_metric")
            st.slider("Grid decarbonization %", 0, 60, 25, key="an_grid",
                      help="Reduces Scope-2 electricity factor — e.g. PPA or national grid trend.")
            st.slider("Supplier efficiency %", 0, 30, 10, key="an_eff",
                      help="Cuts remaining electricity + fuel activity after the grid lever.")
            st.slider("Landfill → recycling diversion %", 0, 100, 40, key="an_div",
                      help="Moves waste mass from landfill factor to recycling factor.")
            st.slider("Evidence review threshold", 50, 90, 70, key="an_target")
            st.toggle("Show uncertainty bands", True, key="an_unc")
            st.selectbox("Scenario factor set", list(FACTORS), index=list(FACTORS).index(get_factor_version()),
                         key="an_fv", help="Compare against a prior approved factor version (rollback preview).")
            if st.button("↺ Reset scenario", key="an_reset"):
                for k, v in [("an_grid", 25), ("an_eff", 10), ("an_div", 40), ("an_target", 70)]:
                    st.session_state[k] = v
                st.rerun()
            st.caption(f"Active production factors: **{get_factor_version()}** · engine **{ENGINE_VERSION}**. "
                       "Scenario levers never mutate stored records.")
    sids = sups[sups.name.isin(picks)].supplier_id.tolist() or sups.supplier_id.tolist()
    sr = recs[recs.supplier_id.isin(sids)]
    F = FACTORS[st.session_state.an_fv]["entries"]
    scn = scenario_compute(sr, F, st.session_state.an_grid, st.session_state.an_eff, st.session_state.an_div)
    with main:
        base, tot = scn["baseline"], scn["total"]
        delta = -100 * (base - tot) / base if base > 0 else 0
        k1, k2, k3, k4 = st.columns(4)
        k1.markdown(kpi("Baseline", fmt_t(base), f"{len(sids)} suppliers · partial boundary", "#2563EB"), unsafe_allow_html=True)
        k2.markdown(kpi("Scenario", fmt_t(tot), f"{delta:.1f}% vs baseline", "#4338CA"), unsafe_allow_html=True)
        k3.markdown(kpi("Grid lever", "−" + fmt_t(scn["grid_save"]), f"{st.session_state.an_grid}% decarbonization", "#65A30D"), unsafe_allow_html=True)
        k4.markdown(kpi("Efficiency + diversion", "−" + fmt_t(scn["eff_save"] + scn["div_save"]),
                        f"{st.session_state.an_eff}% eff · {st.session_state.an_div}% diversion", "#D97706"), unsafe_allow_html=True)
        fig = go.Figure(go.Waterfall(
            x=["Baseline", f"Grid −{st.session_state.an_grid}%", f"Efficiency −{st.session_state.an_eff}%",
               f"Diversion {st.session_state.an_div}%", "Scenario"],
            measure=["absolute", "relative", "relative", "relative", "total"],
            y=[base / 1000, -scn["grid_save"] / 1000, -scn["eff_save"] / 1000, -scn["div_save"] / 1000, 0],
            text=[f"{base/1000:,.0f}", f"−{scn['grid_save']/1000:,.0f}", f"−{scn['eff_save']/1000:,.0f}",
                  f"−{scn['div_save']/1000:,.0f}", f"{tot/1000:,.0f}"],
            textposition="outside",
            decreasing=dict(marker=dict(color="#65A30D")),
            totals=dict(marker=dict(color="#2563EB")),
            connector=dict(line=dict(color=pal()["muted"], width=1))))
        style_fig(fig, 340, "Scenario waterfall (tCO₂e)", legend=False)
        show_fig(fig, key="an_water")
        per = scn["per_supplier"].merge(sups[["supplier_id", "name", "annual_spend_eur"]], on="supplier_id")
        scx = sc.set_index("supplier_id")
        if st.session_state.an_metric.startswith("Intensity"):
            per["baseline"] = per.apply(lambda r: r.baseline / (r.annual_spend_eur / 1000), axis=1)
            per["scenario"] = per.apply(lambda r: r.scenario / (r.annual_spend_eur / 1000), axis=1)
            unit_lbl = "kgCO₂e / €k"
        else:
            per["baseline"] /= 1000; per["scenario"] /= 1000
            unit_lbl = "tCO₂e"
        per = per.sort_values("baseline", ascending=False)
        err = [float(scx.loc[sid, "rel_unc"]) * b if st.session_state.an_unc else 0 for sid, b in zip(per.supplier_id, per.scenario)]
        fig = go.Figure()
        fig.add_bar(x=per.name.str.split().str[0], y=per.baseline, name="Baseline", marker_color="#2563EB")
        fig.add_bar(x=per.name.str.split().str[0], y=per.scenario, name="Scenario", marker_color="#65A30D",
                    error_y=dict(type="data", array=err, visible=st.session_state.an_unc, color=pal()["muted"]))
        fig.update_layout(barmode="group")
        style_fig(fig, 330, f"Baseline vs scenario by supplier ({unit_lbl}) · bars = ± uncertainty")
        show_fig(fig, key="an_bars")
        show = per[["name", "baseline", "scenario", "delta_pct"]].rename(
            columns={"name": "Supplier", "baseline": f"Baseline ({unit_lbl})",
                     "scenario": f"Scenario ({unit_lbl})", "delta_pct": "Δ %"})
        st.dataframe(show, hide_index=True, width="stretch",
                     column_config={f"Baseline ({unit_lbl})": st.column_config.NumberColumn(format="%.1f"),
                                    f"Scenario ({unit_lbl})": st.column_config.NumberColumn(format="%.1f"),
                                    "Δ %": st.column_config.NumberColumn(format="%.1f%%")})
    st.divider()
    st.markdown("### 🔎 Supplier deep-dive & explanation panel")
    focus_name = st.selectbox("Focus supplier", [n for n in sups.name if n in picks] or sups.name.tolist(), key="an_focus")
    fs = sups[sups.name == focus_name].iloc[0]
    fr = recs[(recs.supplier_id == fs.supplier_id) & (recs.status.isin(list(ANALYTICS)))]
    es = evidence_score(fs.to_dict(), fr, today_d())
    em = supplier_emissions(fr, F)
    row = sc[sc.supplier_id == fs.supplier_id].iloc[0]
    d1, d2, d3 = st.columns([1, 1.15, 1.15])
    with d1:
        gauge = go.Figure(go.Indicator(
            mode="gauge+number", value=row.eqs,
            number=dict(font=dict(size=40, family="Fraunces", color=pal()["ink"])),
            gauge=dict(axis=dict(range=[0, 100], tickcolor=pal()["muted"]),
                       bar=dict(color=grade_colors()[row.grade], thickness=.32),
                       bgcolor="rgba(0,0,0,0)", borderwidth=0,
                       steps=[dict(range=[0, 40], color="rgba(220,38,38,.14)"),
                              dict(range=[40, 70], color="rgba(217,119,6,.14)"),
                              dict(range=[70, 100], color="rgba(101,163,13,.14)")],
                       threshold=dict(line=dict(color="#D97706", width=3),
                                      value=st.session_state.an_target))))
        style_fig(gauge, 250, f"EQS · Grade {row.grade}" + (" · adjusted" if row.overridden else ""), legend=False)
        show_fig(gauge, key="an_gauge")
        st.markdown(grade_chip(row.grade, row.eqs) +
                    (f' <span class="chip" style="color:#C026D3;">✎ override of {row.eqs_model:.1f}</span>' if row.overridden else ""),
                    unsafe_allow_html=True)
    with d2:
        comp = es["components"]
        fig = go.Figure(go.Bar(x=[v * 100 for v in comp.values()], y=[k.title() for k in comp],
                               orientation="h", marker_color=chart_palette()[:5],
                               text=[f"{es['points'][k]:.1f} / {EQS_WEIGHTS[k]*100:.0f} pts" for k in comp],
                               textposition="outside", cliponaxis=False))
        fig.update_xaxes(range=[0, 118])
        style_fig(fig, 280, "Component scores (0–100) · earned / available pts", legend=False)
        show_fig(fig, key="an_comp")
    with d3:
        if em["by_category"]:
            fig = go.Figure(go.Pie(labels=[CAT_LABEL[c] for c in em["by_category"]],
                                   values=[v / 1000 for v in em["by_category"].values()], hole=.6,
                                   marker=dict(colors=[cat_colors()[c] for c in em["by_category"]]),
                                   textinfo="label+percent"))
            fig.add_annotation(text=f"±{em['rel_unc']:.0%}", showarrow=False,
                               font=dict(size=17, family="Fraunces", color=pal()["ink"]))
            style_fig(fig, 280, f"Footprint mix · {em['total_kg']/1000:,.1f} tCO₂e", legend=False)
            show_fig(fig, key="an_donut")
        else:
            st.warning("No analytics-window records — this supplier is a data blind spot.")
    with st.expander("🧠 Why this score? — inputs, rules, provenance, uncertainty, reviewer status", expanded=True):
        e1, e2 = st.columns(2)
        with e1:
            st.markdown("**Rule trace (EQS-1.2.0)** — `EQS = 100 · Σ wᵢ·s`")
            st.dataframe(pd.DataFrame([{"Component": k.title(), "Weight": f"{EQS_WEIGHTS[k]:.0%}",
                                        "Raw score": round(v, 3), "Points": es["points"][k]}
                                       for k, v in comp.items()]), hide_index=True, width="stretch")
            if len(fr):
                ex = fr.sort_values("quantity", ascending=False).iloc[0]
                fkg = float(ex.quantity) * F[ex.activity_type]["factor"]
                st.markdown(f"**Hand-check:** `{float(ex.quantity):,.1f} {ex.unit} × "
                            f"{F[ex.activity_type]['factor']} kg/{ex.unit} = {fkg:,.1f} kgCO₂e` "
                            f"± {UNC[ex.data_collection]:.0%} ({ex.data_collection})")
            st.markdown(f"**Uncertainty:** quadrature of per-record bands → ±{em['abs_unc_kg']:,.0f} kg "
                        f"({em['rel_unc']:.0%} of total). Measured share: {em['measured_share']:.0%}.")
            dec = sql_df("SELECT status,actor,ts FROM decisions WHERE approved_supplier=? ORDER BY decision_id DESC LIMIT 1",
                         (fs.supplier_id,))
            ov = load_overrides()
            ovr = ov[ov.supplier_id == fs.supplier_id]
            st.markdown("**Reviewer status:** " +
                        (f"decision {dec.iloc[0].status} by {dec.iloc[0].actor} ({dec.iloc[0].ts})" if len(dec) else "no tender decision yet") +
                        (" · **manual override active**" if len(ovr) else ""))
            srcs = fr.source.value_counts()
            st.markdown("**Lineage:** " + (" · ".join(f"{k} ×{v}" for k, v in srcs.items()) or "no records"))
        with e2:
            st.markdown(f"**Factors used · {st.session_state.an_fv}** (published {FACTORS[st.session_state.an_fv]['published']})")
            used = sorted(set(fr.activity_type)) or ["grid_electricity"]
            st.dataframe(pd.DataFrame([{"Activity": a, "kgCO₂e/unit": F[a]["factor"], "Unit": F[a]["unit"],
                                        "Source": F[a]["source"]} for a in used]),
                         hide_index=True, width="stretch")
            st.caption(FACTOR_NOTE)
            if es["warnings"]:
                for w in es["warnings"]: st.warning(w)
            else:
                st.success("No data-quality warnings — all component thresholds met.")
        if can("override"):
            st.markdown("**✎ Manual override (audited)**")
            o1, o2 = st.columns([1, 2])
            oval = o1.slider("Override EQS", 0.0, 100.0, float(row.eqs), 0.5, key="an_ov")
            owhy = o2.text_input("Reason (required, stored in audit + reports)", key="an_ovwhy")
            if st.button("Apply override", key="an_ovgo"):
                if not owhy.strip(): st.warning("An override reason is required.")
                else:
                    name, _ = actor()
                    sql_exec("INSERT INTO overrides VALUES(?,?,?,?,?,1) ON CONFLICT(supplier_id) DO UPDATE "
                             "SET value=excluded.value,reason=excluded.reason,actor=excluded.actor,ts=excluded.ts,active=1",
                             (fs.supplier_id, oval, owhy, name, utcnow()))
                    audit("OVERRIDE_SET", "supplier", fs.supplier_id, f"EQS→{oval} · {owhy}")
                    st.toast("Override applied and audited"); st.rerun()
        else:
            st.caption("🔒 Manual overrides require the Reviewer or Administrator role.")

# ─────────────────────────────────────────────────────────────────────────────
# PAGE 5 — EVIDENCE & GAPS
# ─────────────────────────────────────────────────────────────────────────────
def page_gaps():
    render_header("Evidence & Gaps — where procurement decisions are flying blind")
    sups, recs, sc, gaps = load_ctx()
    ana = recs[recs.status.isin(list(ANALYTICS))]
    k1, k2, k3, k4 = st.columns(4)
    hi = int(gaps.severity.isin(["high", "critical"]).sum()) if len(gaps) else 0
    k1.markdown(kpi("Open findings", len(gaps), "across all suppliers", "#D97706"), unsafe_allow_html=True)
    k2.markdown(kpi("High / critical", hi, "fix before award decisions", "#DC2626"), unsafe_allow_html=True)
    k3.markdown(kpi("Below grade C", int((sc.eqs < 55).sum()), "suppliers needing engagement", "#EA580C"), unsafe_allow_html=True)
    est = float((ana.data_collection == "estimated").mean()) if len(ana) else 0
    k4.markdown(kpi("Estimated activity", f"{est:.0%}", "of records carry ±30% bands", "#C026D3"), unsafe_allow_html=True)
    st.markdown("#### 🗺 Freshness heatmap — days since newest record, per expected category")
    names = sups.name.tolist()
    z, text, anns = [], [], []
    for i, s in enumerate(sups.itertuples()):
        expected = json.loads(s.expected)
        zr, tr = [], []
        for j, cat in enumerate(CATEGORIES):
            if cat not in expected:
                zr.append(np.nan); tr.append("not expected for sector"); continue
            cr = ana[(ana.supplier_id == s.supplier_id) & (ana.category == cat)]
            if not len(cr):
                zr.append(400.0); tr.append("MISSING — no records")
                anns.append(dict(x=j, y=i, text="✕", showarrow=False, font=dict(color="#fff", size=15)))
            else:
                age = (today_d() - pd.to_datetime(cr.period_end).max().date()).days
                zr.append(float(min(age, 399))); tr.append(f"{age} days since newest")
                anns.append(dict(x=j, y=i, text=f"{age}d", showarrow=False,
                                 font=dict(color="#fff" if age > 180 else pal()["ink"], size=10)))
        z.append(zr); text.append(tr)
    fig = go.Figure(go.Heatmap(z=z, x=[CAT_LABEL[c] for c in CATEGORIES], y=names, text=text,
                               hovertemplate="<b>%{y}</b> · %{x}<br>%{text}<extra></extra>",
                               colorscale=[[0, "#166534"], [.25, "#65A30D"], [.5, "#D97706"],
                                           [.75, "#DC2626"], [1, "#7F1D1D"]],
                               zmin=0, zmax=400, xgap=4, ygap=4,
                               colorbar=dict(title="days", thickness=12)))
    fig.update_layout(annotations=anns)
    fig.update_yaxes(autorange="reversed")
    style_fig(fig, 32 * len(names) + 130, legend=False)
    show_fig(fig, key="gp_heat")
    st.caption("✕ = expected category with zero records · blank = not expected for that sector · red = stale.")
    st.markdown("#### 📋 Gap register — prioritized by spend × severity")
    if not len(gaps):
        st.success("No open gaps. Portfolio evidence is complete and fresh. 🎉"); return
    f1, f2, f3 = st.columns(3)
    fsev = f1.multiselect("Severity", ["critical", "high", "medium", "low"], key="gp_sev")
    fsup = f2.multiselect("Supplier", sorted(gaps.name.unique()), key="gp_sup")
    ftyp = f3.multiselect("Type", sorted(gaps.type.unique()), key="gp_typ")
    g = gaps.copy()
    if fsev: g = g[g.severity.isin(fsev)]
    if fsup: g = g[g.name.isin(fsup)]
    if ftyp: g = g[g.type.isin(ftyp)]
    gdisp = g.copy()
    gdisp["severity"] = gdisp.severity.map({"critical": "🟥 critical", "high": "🔴 high",
                                           "medium": "🟠 medium", "low": "🔵 low"})
    st.dataframe(gdisp[["name", "scope", "type", "severity", "detail", "action", "priority"]],
                 hide_index=True, width="stretch", height=330,
                 column_config={"priority": st.column_config.NumberColumn(format="%.2f")})
    st.download_button("⬇ Download gap register (CSV)", g.to_csv(index=False).encode(),
                       "verdant_gap_register.csv", "text/csv", key="gp_dl")
    st.markdown("#### 🎯 Where to spend analyst time this week")
    top = gaps.groupby(["supplier_id", "name"], sort=False).agg(
        findings=("type", "count"), priority=("priority", "sum")).reset_index().sort_values("priority", ascending=False).head(4)
    cols = st.columns(len(top))
    for c, t in zip(cols, top.itertuples()):
        sup_gaps = gaps[gaps.supplier_id == t.supplier_id].head(2)
        acts = "".join(f"<li>{H.escape(a.action)}</li>" for a in sup_gaps.itertuples())
        c.markdown(f'<div class="v-card"><b>{H.escape(t.name)}</b>'
                   f'<div style="font-size:12px;color:{pal()["muted"]};">{t.findings} findings · priority {t.priority:.1f}</div>'
                   f'<ul style="font-size:12px;padding-left:16px;margin:8px 0 0;">{acts}</ul></div>',
                   unsafe_allow_html=True)
    st.markdown("")
    if st.button("🗂 Work these records now", key="gp_jump"): jump(PAGES[2])
    with st.expander("📖 Remediation playbook — what each finding means"):
        st.markdown("""
| Finding | Trigger | Default action | Suggested owner |
|---|---|---|---|
| NO_DATA | 0 usable records | Onboard with 12-month data request | Category manager |
| MISSING_CATEGORY | Expected category absent | Data-sharing annex + request | Analyst |
| STALE_DATA | Newest > 120d (high > 240d) | Quarterly submission reminder | Analyst |
| CONTRADICTION | Duplicate key diverges > 25% | Reconcile feeds; audited correction | Analyst + Reviewer |
| LOW_VERIFICATION | > 50% unverified | Internal check / third-party audit | Reviewer |
| MISSING_EVIDENCE | > 25% lacking doc IDs | Collect invoices / meter photos | Supplier contact |
| ESTIMATE_HEAVY | > 40% estimated | Replace with measured activity | Supplier contact |
""")

# ─────────────────────────────────────────────────────────────────────────────
# PAGE 6 — REVIEW & APPROVE
# ─────────────────────────────────────────────────────────────────────────────
def page_review():
    render_header("Review & Approve — human decisions with reasons, weights and audit")
    sups, recs, sc, gaps = load_ctx()
    tenders = sql_df("SELECT * FROM tenders ORDER BY tender_id")
    tab1, tab2 = st.tabs(["🏛 Tender decisions", f"📑 Record approvals ({int((recs.status=='in_review').sum())})"])
    with tab1:
        tid = st.selectbox("Tender", tenders.tender_id.tolist(), key="rv_tender",
                           format_func=lambda t: f"{tenders[tenders.tender_id==t].iloc[0].code} · "
                                                 f"{tenders[tenders.tender_id==t].iloc[0].title} "
                                                 f"[{tenders[tenders.tender_id==t].iloc[0].status}]")
        t = tenders[tenders.tender_id == tid].iloc[0]
        cands = json.loads(t.candidates)
        i1, i2, i3 = st.columns(3)
        i1.markdown(kpi("Budget", fmt_eur(t.budget_eur), f"deadline {t.deadline}", "#2563EB"), unsafe_allow_html=True)
        i2.markdown(kpi("Candidates", len(cands), "environmental + cost comparison", "#4338CA"), unsafe_allow_html=True)
        i3.markdown(kpi("Status", t.status.replace("_", " "), "human approval required for award", "#C026D3"), unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown("##### ⚖️ Decision weights · live")
            w1, w2, w3 = st.columns(3)
            wi = w1.slider("Impact intensity %", 0, 100, 40, key="rv_wi")
            we = w2.slider("Evidence quality %", 0, 100, 35, key="rv_we")
            wc = w3.slider("Cost %", 0, 100, 25, key="rv_wc")
            tot_w = max(1, wi + we + wc)
            st.caption(f"Normalized: impact {wi/tot_w:.0%} · evidence {we/tot_w:.0%} · cost {wc/tot_w:.0%}")
        rows = []
        for c in cands:
            r = sc[sc.supplier_id == c["sid"]].iloc[0]
            rows.append(dict(sid=c["sid"], name=r["name"], bid=c["bid"], eqs=r.eqs, grade=r.grade,
                             coverage=r.coverage, intensity=r.intensity))
        cdf = pd.DataFrame(rows)
        def norm_inv(series):
            lo, hi = series.min(), series.max()
            return pd.Series([100.0] * len(series)) if hi - lo < 1e-9 else 100 * (hi - series) / (hi - lo)
        cdf["impact_score"] = norm_inv(cdf.intensity).round(1)
        cdf["evidence_score"] = cdf.eqs
        cdf["cost_score"] = norm_inv(cdf.bid).round(1)
        cdf["composite"] = ((wi * cdf.impact_score + we * cdf.evidence_score + wc * cdf.cost_score) / tot_w).round(1)
        winner = cdf.sort_values("composite", ascending=False).iloc[0]
        c1, c2 = st.columns([1.5, 1])
        with c1:
            st.dataframe(cdf[["name", "bid", "eqs", "grade", "coverage", "intensity",
                              "impact_score", "evidence_score", "cost_score", "composite"]].rename(
                columns={"name": "Supplier", "bid": "Bid €", "eqs": "EQS", "grade": "Grade",
                         "coverage": "Cov %", "intensity": "kg/€k", "composite": "Composite"}),
                hide_index=True, width="stretch",
                column_config={"Bid €": st.column_config.NumberColumn(format="%.0f"),
                               "Composite": st.column_config.NumberColumn(format="%.1f")})
            caveats = []
            if winner.coverage < 60: caveats.append(f"coverage only {winner.coverage:.0f}% — close category gaps before award")
            if winner.grade in ("D", "F"): caveats.append(f"evidence grade {winner.grade} — high data risk")
            if float(cdf.loc[cdf.sid == winner.sid, "eqs"].iloc[0]) < st.session_state.get("an_target", 70):
                caveats.append("below the evidence review threshold")
            cond = "CONDITIONAL — " + "; ".join(caveats) if caveats else "Unconditional on current evidence"
            st.markdown(f'<div class="v-card" style="border-left:5px solid #4338CA;">'
                        f'<b style="font-size:15px;">Recommendation: {H.escape(winner["name"])}</b> '
                        f'{grade_chip(winner.grade)}<br>'
                        f'<div style="font-size:13px;margin-top:6px;">Composite {winner.composite:.1f}/100 · '
                        f'{cond}.<br><i>Analysis is decision support — the award below requires an authorized human.</i></div></div>',
                        unsafe_allow_html=True)
        with c2:
            fig = go.Figure()
            axes = ["Completeness", "Recency", "Verification", "Traceability", "Consistency"]
            for i, r in enumerate(cdf.itertuples()):
                srow = sc[sc.supplier_id == r.sid].iloc[0]
                vals = [float(srow[f"c_{k.lower()}"]) * 100 for k in axes]
                fig.add_trace(go.Scatterpolar(r=vals + vals[:1], theta=axes + axes[:1], fill="toself",
                                              name=r.name.split()[0], opacity=.55,
                                              line=dict(color=chart_palette()[i % 8], width=2)))
            fig.update_layout(polar=dict(bgcolor="rgba(0,0,0,0)",
                                         radialaxis=dict(range=[0, 100], gridcolor=pal()["line"],
                                                         tickfont=dict(size=9, color=pal()["muted"])),
                                         angularaxis=dict(gridcolor=pal()["line"],
                                                          tickfont=dict(size=10, color=pal()["ink"]))))
            style_fig(fig, 330, "Evidence profile radar")
            show_fig(fig, key="rv_radar")
        st.markdown("#### ✍️ Record the human decision")
        d1, d2 = st.columns([1, 2])
        pick = d1.selectbox("Award to", cdf.sid.tolist(), index=int(cdf.index[cdf.sid == winner.sid][0]),
                            format_func=lambda s: cdf[cdf.sid == s].iloc[0]["name"], key="rv_pick")
        comment = d2.text_area("Decision reason (required — appears in the report and audit)", key="rv_comment",
                               placeholder="e.g. Best verified intensity; award conditional on quarterly BOM refresh…")
        b1, b2, b3 = st.columns(3)
        snapshot = json.dumps({"candidates": cdf.to_dict("records"),
                               "weights": {"impact": wi, "evidence": we, "cost": wc},
                               "engine": ENGINE_VERSION, "factors": get_factor_version(), "ts": utcnow()})
        def write_decision(status, supplier):
            name, role = actor()
            sql_exec("INSERT INTO decisions(tender_id,ts,actor,role,approved_supplier,status,comment,weights,snapshot) "
                     "VALUES(?,?,?,?,?,?,?,?,?)",
                     (tid, utcnow(), name, role, supplier, status, comment,
                      json.dumps({"impact": wi, "evidence": we, "cost": wc}), snapshot))
            sql_exec("UPDATE tenders SET status=? WHERE tender_id=?",
                     ("decided" if status in ("approved", "rejected") else "correction_requested", tid))
            audit(f"DECISION_{status.upper()}", "tender", tid, f"{supplier or '—'} · {comment[:200]}")
            st.toast(f"Decision recorded: {status}", icon="⚖️"); st.rerun()
        if b1.button("✅ Approve award", type="primary", key="rv_ok",
                     disabled=not can("approve"), help=gate_hint("approve")):
            if not comment.strip(): st.warning("A decision reason is required.")
            else: write_decision("approved", pick)
        if b2.button("🔁 Request correction", key="rv_fix", disabled=not can("review"), help=gate_hint("review")):
            if not comment.strip(): st.warning("Describe what must be corrected.")
            else: write_decision("correction_requested", pick)
        if b3.button("⛔ Reject all bids", key="rv_no", disabled=not can("approve"), help=gate_hint("approve")):
            if not comment.strip(): st.warning("A rejection reason is required.")
            else: write_decision("rejected", "")
        with st.expander("📜 Decision history for this tender"):
            dec = sql_df("SELECT * FROM decisions WHERE tender_id=? ORDER BY decision_id DESC", (tid,))
            if len(dec):
                st.dataframe(dec[["ts", "actor", "role", "status", "approved_supplier", "comment"]],
                             hide_index=True, width="stretch")
                st.json(json.loads(dec.iloc[0].snapshot), expanded=False)
            else:
                st.caption("No decisions yet — the comparison above is provisional analysis.")
    with tab2:
        queue = recs[recs.status == "in_review"]
        if not len(queue):
            st.success("Record review queue is clear. 🎉 New submissions arrive via the live intake or import.")
        else:
            st.caption(f"{len(queue)} records awaiting a reviewer. Approvals and rejections are audited.")
            for r in queue.head(12).itertuples():
                s = sups[sups.supplier_id == r.supplier_id].iloc[0]
                c1, c2, c3, c4 = st.columns([2.6, 1.6, 1, 1])
                c1.markdown(f"**{r.record_id}** · {s['name']} — {r.activity_type} "
                            f"{float(r.quantity):,.0f} {r.unit} ({r.period_end})")
                why = c2.text_input("Reason", key=f"rvq_why_{r.record_id}", label_visibility="collapsed",
                                    placeholder="reason (required to reject)")
                if c3.button("✅ Approve", key=f"rvq_ok_{r.record_id}", disabled=not can("approve"), help=gate_hint("approve")):
                    set_status(r.record_id, "approved", why or "Record approved")
                    st.toast(f"{r.record_id} approved"); st.rerun()
                if c4.button("⛔ Reject", key=f"rvq_no_{r.record_id}", disabled=not can("approve"), help=gate_hint("approve")):
                    if not why.strip(): st.warning(f"Enter a rejection reason for {r.record_id}.")
                    else:
                        set_status(r.record_id, "rejected", why)
                        st.toast(f"{r.record_id} rejected"); st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# PAGE 7 — REPORTS & EXPORT
# ─────────────────────────────────────────────────────────────────────────────
def page_reports():
    render_header("Reports & Export — traceable, versioned, decision-ready")
    sups, recs, sc, gaps = load_ctx()
    kind = st.radio("Report type", ["Portfolio summary", "Supplier scorecard", "Tender decision"],
                    horizontal=True, key="rp_kind")
    if kind == "Supplier scorecard":
        st.selectbox("Supplier", sups.supplier_id.tolist(), key="rp_supplier",
                     format_func=lambda s: sups[sups.supplier_id == s].iloc[0]["name"])
    if kind == "Tender decision":
        tenders = sql_df("SELECT * FROM tenders")
        st.selectbox("Tender", tenders.tender_id.tolist(), key="rp_tender",
                     format_func=lambda t: f"{tenders[tenders.tender_id==t].iloc[0].code} · "
                                           f"{tenders[tenders.tender_id==t].iloc[0].title}")
    html_doc = report_html(kind, sups, recs, sc, gaps, get_factor_version())
    with st.expander("📦 What's inside every report"):
        st.markdown("- Generation timestamp, author and role · engine, factor and schema versions\n"
                    "- Synthetic-data disclaimer and calculation boundary (what is and isn't included)\n"
                    "- Score composition with weights and raw component values\n"
                    "- Data-quality warnings, gap remediation actions, record-level lineage\n"
                    "- Human decision block with reason, weights and candidate snapshot (tender reports)\n"
                    "- Full reference-factor table with sources and publication date")
    st.markdown("#### 👁 Live preview")
    components.html(html_doc, height=560, scrolling=True)
    st.markdown("#### ⬇ Downloads")
    bundle = {"meta": {"generated": utcnow(), "engine": ENGINE_VERSION, "factors": get_factor_version(),
                       "schema": SCHEMA_VERSION, "data": "SYNTHETIC DEMO — decision support only"},
              "suppliers": sups.to_dict("records"), "records": recs.to_dict("records"),
              "scorecard": sc.to_dict("records"), "gaps": gaps.to_dict("records") if len(gaps) else [],
              "decisions": sql_df("SELECT * FROM decisions").to_dict("records"),
              "audit": load_audit().to_dict("records")}
    d1, d2, d3, d4 = st.columns(4)
    if d1.download_button("📄 Report (HTML)", html_doc.encode("utf-8"),
                          f"verdant_{kind.lower().replace(' ','_')}.html", "text/html", key="rp_html"):
        audit("EXPORT", "report", kind, "HTML report downloaded")
    if d2.download_button("📊 Scorecard (CSV)", sc.to_csv(index=False).encode(),
                          "verdant_scorecard.csv", "text/csv", key="rp_csv"):
        audit("EXPORT", "report", "scorecard", "CSV scorecard downloaded")
    if d3.download_button("🗃 Full bundle (JSON)", json.dumps(bundle, default=str, indent=1).encode(),
                          "verdant_bundle.json", "application/json", key="rp_json"):
        audit("EXPORT", "report", "bundle", "JSON bundle downloaded")
    if d4.download_button("🧾 Audit log (CSV)", load_audit().to_csv(index=False).encode(),
                          "verdant_audit.csv", "text/csv", key="rp_audit"):
        audit("EXPORT", "report", "audit", "Audit log downloaded")
    st.caption("Every export is itself an audited event. Stakeholders (read-only) may export; "
               "only Reviewers/Administrators can create decisions.")

# ─────────────────────────────────────────────────────────────────────────────
# PAGE 8 — QUALITY & TESTS
# ─────────────────────────────────────────────────────────────────────────────
def page_quality():
    render_header("Quality & Tests — the acceptance evidence, computed live")
    if st.session_state.tests is None or st.button("🔁 Re-run full suite", key="qt_run"):
        st.session_state.tests = run_self_tests()
    results, ok, ms = st.session_state.tests
    passed = sum(r["passed"] for r in results)
    if ok:
        st.success(f"✅ {passed}/{len(results)} tests passed in {ms} ms — engine is deterministic and hand-checkable.")
    else:
        st.error(f"❌ {passed}/{len(results)} passed — inspect failures below before trusting outputs.")
    df = pd.DataFrame(results)
    df["passed"] = df.passed.map({True: "✅ PASS", False: "❌ FAIL"})
    st.dataframe(df, hide_index=True, width="stretch", height=430)
    c1, c2 = st.columns(2)
    with c1.expander("🧮 Hand-checkable examples"):
        st.markdown("""
| Input | Rule | Expected |
|---|---|---|
| 10,000 kWh grid electricity | × 0.2070 kg/kWh | **2,070.0 kgCO₂e** |
| 2 MWh | convert ×1000 → kWh | **2,000 kWh → 414.0 kg** |
| 1,000 L diesel | × 2.687 kg/L | **2,687.0 kg** |
| 10,000 kg landfill waste | × 0.446 kg/kg | **4,460.0 kg** |
| Perfect evidence, 3/3 categories | EQS weights | **100.0 / grade A** |
| Supplier with zero records | consistency floor only | **20.0 / grade F** |
| Newest data 205 days old | (205−45)/320 decay | **recency = 0.5** |
| Duplicate pair 100 vs 200 | >25% divergence | **consistency 1.0 → 0.75** |
""")
    with c2.expander("📏 Formulas, boundaries & rule provenance"):
        st.markdown(f"""
**Engine {ENGINE_VERSION}** — deterministic, pure functions, no UI coupling.
- `kgCO₂e = quantity × factor(activity, version)` — factors dated `{FACTORS[get_factor_version()]['published']}`.
- `EQS = 100 · (0.25·completeness + 0.20·recency + 0.20·verification + 0.15·traceability + 0.20·consistency)`
- Recency: 1.0 at ≤45 days, linear to 0 at 365. Verification map: third-party 1.0 / internal 0.6 / unverified 0.15.
- Consistency penalties: −0.25 per contradiction pair, −0.15 per out-of-range flag, −0.1 if >30% missing refs.
- Uncertainty: measured ±5%, calculated ±12%, estimated ±30%; totals combined in quadrature.
- Boundary: operational Scope 1+2 (location-based), water, waste, cradle-to-gate materials. **Not a full LCA.**
- Grades: A≥85 · B≥70 · C≥55 · D≥40 · F<40. Overrides are human, reasoned and audited — never silent.
""")
    with st.expander("✅ Acceptance checklist — observable pass/pending, no fabricated claims"):
        exports = int((load_audit().action == "EXPORT").sum())
        imports = int(sql_scalar("SELECT COUNT(*) FROM imports") or 0)
        chk = [
            ("Import documented sample file", "Ready — templates on Import page" if imports == 0 else f"Done · {imports} import(s) committed", imports > 0),
            ("Malformed rows rejected with actionable errors", f"Verified by T08–T13, T18 ({'pass' if ok else 'FAIL'})", ok),
            ("Reproducible calculation results", f"Verified by T17 ({'pass' if ok else 'FAIL'})", ok),
            ("Traceable output explanations", "Built-in — Analysis › Why this score", True),
            ("Export of a report", "Ready — Reports page" if exports == 0 else f"Done · {exports} export event(s)", exports > 0),
            ("Automated test suite passing", f"{passed}/{len(results)} in {ms} ms", ok),
            ("Clean-DB repeatability", "Ready — Admin › Reset & reseed (admin only)", True),
            ("Real-user impact validated", "NOT CLAIMED — requires pilot with permissioned real data", False),
        ]
        st.dataframe(pd.DataFrame([{"Criterion": a, "Status": b, "Met": "✅" if c else "⏳ pending"}
                                   for a, b, c in chk]), hide_index=True, width="stretch")
    with st.expander("🖥 Headless engine — runs without opening the UI"):
        st.code("""from app import validate_rows, evidence_score, supplier_emissions, FACTORS
# Pure functions: typed inputs in, structured dicts out, explicit errors.
F = FACTORS["RF-2026.1-demo"]["entries"]
em = supplier_emissions(records_df, F)      # -> total_kg, abs_unc_kg, by_category…
es = evidence_score(supplier_row, recs_df, today)  # -> components, eqs, grade, warnings
clean, issues = validate_rows(df, supplier_ids, existing_keys, today)""", language="python")
    with st.expander("🤖 ML policy & limitations (honest by design"):
        st.markdown("""
- **MVP uses deterministic rules only** — auditability beats opacity for procurement evidence.
- No model is trained on this synthetic data, and **no real-world predictive performance is claimed**.
- A future gap-risk classifier would: target `gap_closed_within_90d`, split by supplier and time,
  compare against the rule baseline, report precision/recall + calibration per sector, and ship with
  model card, training-data version and rollback — only on permissioned real data.
- Factors here are illustrative; production requires licensed authoritative sets (e.g. DEFRA/IEA) and qualified domain review.
- This software is **decision support**, not certification, assurance or regulatory compliance.
""")

# ─────────────────────────────────────────────────────────────────────────────
# PAGE 9 — ADMIN & GOVERNANCE
# ─────────────────────────────────────────────────────────────────────────────
def page_admin():
    render_header("Admin & Governance — access, reference data, backups, audit, product docs")
    tabs = st.tabs(["🔐 Governance", "📚 Reference data", "💾 Data & backup", "🧾 Audit log",
                    "📖 Data dictionary", "📘 Product docs"])
    with tabs[0]:
        st.markdown("#### Access-control matrix (enforced on every action, not just hidden in UI)")
        perms = ["import", "edit", "submit", "archive", "review", "approve", "override", "export", "admin", "restore"]
        matrix = pd.DataFrame([{**{"Action": p}, **{r: ("✔" if p in ROLES[r]["perms"] else "—") for r in ROLES}}
                               for p in perms])
        st.dataframe(matrix, hide_index=True, width="stretch")
        c1, c2 = st.columns(2)
        with c1:
            ret = st.number_input("Retention policy (months)", 12, 120,
                                  int(load_config().get("retention_months", 84)), key="ad_ret")
            if st.button("Save retention policy", key="ad_ret_go", disabled=not can("admin"), help=gate_hint("admin")):
                set_config("retention_months", ret)
                audit("CONFIG_SET", "config", "retention_months", str(ret))
                st.toast("Retention policy saved")
            st.caption("Policy is recorded now; automated enforcement job is post-MVP (documented in runbook).")
        with c2:
            st.markdown("#### Active manual overrides")
            ov = load_overrides()
            if len(ov):
                st.dataframe(ov[["supplier_id", "value", "reason", "actor", "ts"]], hide_index=True, width="stretch")
                pick = st.selectbox("Revoke override", ov.supplier_id.tolist(), key="ad_ov_pick")
                if st.button("Revoke", key="ad_ov_go", disabled=not can("override"), help=gate_hint("override")):
                    sql_exec("UPDATE overrides SET active=0 WHERE supplier_id=?", (pick,))
                    audit("OVERRIDE_REVOKED", "supplier", pick, "Override revoked — model score restored")
                    st.toast("Override revoked"); st.rerun()
            else:
                st.caption("No active overrides — all scores are model-computed.")
    with tabs[1]:
        st.markdown("#### Emission-factor catalog — dated, sourced, versioned, rollback-ready")
        cur = get_factor_version()
        pick = st.selectbox("Active factor version", list(FACTORS), index=list(FACTORS).index(cur), key="ad_fv")
        if st.button("Apply / rollback factor version", key="ad_fv_go", disabled=not can("admin"), help=gate_hint("admin")):
            if pick != cur:
                set_config("factor_version", pick)
                audit("FACTOR_VERSION_SET", "config", "factor_version", f"{cur} → {pick}")
                st.toast(f"Factors switched to {pick} — all analytics recompute deterministically"); st.rerun()
            else:
                st.info("Already active.")
        for ver, fs in FACTORS.items():
            with st.expander(f"{'🟢' if ver == cur else '⚪'} {ver} · published {fs['published']}", expanded=(ver == cur)):
                st.dataframe(pd.DataFrame([{"Activity": a, "Factor kgCO₂e/unit": v["factor"],
                                            "Unit": v["unit"], "Source": v["source"]}
                                           for a, v in fs["entries"].items()]),
                             hide_index=True, width="stretch")
        st.caption(FACTOR_NOTE)
        st.markdown(f"**Engine changelog** — `{ENGINE_VERSION}`: current EQS weights & contradiction penalty · "
                    "`EQS-1.1.x`: pre-override era (superseded) · rollback of factors is one click above; "
                    "engine rollback = redeploy prior tagged release (runbook).")
    with tabs[2]:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Backup")
            data = DB_PATH.read_bytes()
            st.download_button(f"⬇ Download database backup ({len(data)/1024:.0f} KB)", data,
                               f"verdant_backup_{today_d().isoformat()}.db", "application/octet-stream", key="ad_bak")
            st.caption("Backup = records, suppliers, decisions, overrides, imports, audit, config. "
                       "Original uploaded files live in evidence_store/ — copy that folder alongside the .db.")
            n_files = len(list(EVIDENCE_DIR.glob("*")))
            st.markdown(f"**Evidence store:** {n_files} preserved original file(s).")
        with c2:
            st.markdown("#### Restore from backup")
            up = st.file_uploader("Upload a Verdant .db backup", type=["db", "sqlite", "sqlite3"], key="ad_restore")
            confirm = st.checkbox("I understand this replaces the current database", key="ad_restore_cf")
            if st.button("Restore", key="ad_restore_go", disabled=not can("admin") or not confirm or up is None,
                         help=gate_hint("admin")):
                raw = up.getvalue()
                if not raw.startswith(b"SQLite format 3"):
                    st.error("Not a SQLite file — restore aborted, current data untouched.")
                else:
                    tmp = Path("restore_tmp.db"); tmp.write_bytes(raw)
                    try:
                        con = sqlite3.connect(tmp)
                        have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                        con.close()
                        if not set(TABLES).issubset(have):
                            raise ValueError(f"missing tables: {set(TABLES)-have}")
                        os.replace(tmp, DB_PATH)
                        st.session_state.feed, st.session_state.trend = [], []
                        audit("RESTORE", "database", "all", f"Restored from {up.name}")
                        st.toast("Database restored"); st.rerun()
                    except Exception as ex:
                        tmp.unlink(missing_ok=True)
                        st.error(f"Restore validation failed: {ex}. Current data untouched.")
        st.divider()
        st.markdown("#### Reset demo (clean-database repeatability)")
        rc = st.checkbox("Confirm full reset — drops all tables and reseeds synthetic data", key="ad_reset_cf")
        if st.button("🧨 Reset & reseed", key="ad_reset_go", disabled=not can("admin") or not rc, help=gate_hint("admin")):
            con = db_conn()
            try:
                for t in TABLES: con.execute(f"DROP TABLE IF EXISTS {t}")
                con.commit()
            finally: con.close()
            init_db(); seed_database()
            st.session_state.feed, st.session_state.trend = [], []
            st.session_state.sim_ok = st.session_state.sim_bad = 0
            st.session_state.tests = None
            audit("RESET", "database", "all", "Clean reset & reseed executed")
            st.toast("Fresh synthetic dataset seeded"); st.rerun()
    with tabs[3]:
        aud = load_audit()
        c1, c2 = st.columns(2)
        fa = c1.multiselect("Action", sorted(aud.action.unique()), key="ad_aud_a")
        fu = c2.multiselect("Actor", sorted(aud.actor.unique()), key="ad_aud_u")
        v = aud.copy()
        if fa: v = v[v.action.isin(fa)]
        if fu: v = v[v.actor.isin(fu)]
        st.caption(f"{len(v)} of {len(aud)} audit events · append-only, never edited")
        st.dataframe(v[["ts", "actor", "role", "action", "entity", "entity_id", "detail"]],
                     hide_index=True, width="stretch", height=430)
        st.download_button("⬇ Audit CSV", v.to_csv(index=False).encode(), "verdant_audit.csv",
                           "text/csv", key="ad_aud_dl")
    with tabs[4]:
        dd = pd.DataFrame([
            ("record_id", "TEXT PK", "—", "Stable observation ID OBS-nnnnnn", "auto", "internal", "unique, sequential"),
            ("supplier_id", "TEXT FK", "—", "Owning supplier", "catalog", "internal", "must exist in suppliers"),
            ("category", "TEXT", "—", "Impact domain", "import/manual", "internal", ", ".join(CATEGORIES)),
            ("activity_type", "TEXT", "—", "Factor key", "import/manual", "internal", "must match category"),
            ("quantity", "REAL", "canonical unit", "Activity amount", "meter/invoice/estimate", "internal", "≥0, ≤ plausibility bound"),
            ("unit", "TEXT", "—", "Canonical unit after conversion", "validator", "internal", "kWh / litre / m3 / kg"),
            ("period_start/end", "TEXT", "ISO date", "Reporting window", "source doc", "internal", "start<end, ≤31d future, ≤3y old"),
            ("facility / country", "TEXT", "—", "Site & jurisdiction", "source doc", "internal", "required, non-empty"),
            ("evidence_type", "TEXT", "—", "Document class", "supplier", "internal", ", ".join(EVIDENCE_TYPES)),
            ("evidence_ref", "TEXT", "—", "Document ID / checksum link", "supplier", "confidential", "warn if doc-type & empty"),
            ("verification", "TEXT", "—", "Assurance level", "reviewer", "internal", ", ".join(VERIF)),
            ("data_collection", "TEXT", "—", "Measurement basis → uncertainty", "supplier", "internal", ", ".join(COLLECTION)),
            ("status", "TEXT", "—", "Lifecycle state", "workflow", "internal", "draft→validated→in_review→approved/rejected→archived"),
            ("source / import_file / import_sha", "TEXT", "—", "Lineage: file, row batch, checksum", "pipeline", "internal", "immutable after insert"),
            ("corrects", "TEXT", "—", "Prior version in correction chain", "workflow", "internal", "original archived, never overwritten"),
            ("flags", "TEXT JSON", "—", "Quality warnings carried on record", "validator", "internal", "list of known flag keys"),
            ("schema/factor_version", "TEXT", "—", "Transformation & reference versions", "pipeline", "internal", "pinned at write time"),
            ("annual_spend_eur", "REAL", "EUR", "Intensity denominator", "procurement", "confidential", "> 0"),
            ("audit.detail", "TEXT", "—", "Change reasons — no secrets logged", "server", "internal", "≤900 chars, parameterized SQL"),
        ], columns=["Field", "Type", "Unit", "Meaning", "Source", "Sensitivity", "Validation rule"])
        st.dataframe(dd, hide_index=True, width="stretch", height=520)
    with tabs[5]:
        with st.expander("📄 One-page product brief"):
            st.markdown("""
**Problem.** Procurement teams award contracts on price while environmental claims arrive as
inconsistent PDFs, spreadsheets and declarations. Analysts spend days reconciling units, chasing
evidence and defending numbers they can't trace. **Buyer (initial).** A municipal procurement
sustainability lead running 20–200 supplier tenders/year. **Value proposition.** Score evidence
quality deterministically, compare impact per euro, and surface exactly which data gaps block a
defensible award — with every number traceable to a source row, factor version and human decision.
**Current workflow failures.** Manual unit errors, stale data treated as current, unverifiable
declarations counted equally with audited meters, no audit trail on overrides, no repeatable report.
**Measurable improvement targets (to validate in pilot, not claimed).** Evidence-check time per
tender ↓50%; 100% of awards carry a reasoned, audited decision; 0 silent data overwrites; report
generation < 1 minute. **Scope.** One narrow loop end-to-end: import → validate → score → compare →
review → approve → export, locally on Windows with synthetic data.
""")
        with st.expander("👥 Personas, roles & permissions"):
            st.markdown("""
| Persona | Role | Enters data | Reviews | Approves | Key need |
|---|---|---|---|---|---|
| Lena, sustainability analyst | Analyst | ✔ imports, corrections | — | — | fast validation, actionable errors |
| Marcus, procurement reviewer | Reviewer | — | ✔ records & tenders | ✔ awards, overrides | traceable reasons, risk flags |
| Amara, program administrator | Administrator | ✔ | ✔ | ✔ | governance, backups, factor versions |
| Priya, budget stakeholder | Read-only | — | — | — | exportable, defensible reports |

Permissions are enforced at the action layer (`can(perm)` re-checked before every write), not merely hidden in the UI.
""")
        with st.expander("🔄 Record lifecycle & exception paths"):
            st.code("""Supplier / file / simulation
      │  validate_rows()  ── errors ─▶ row-level report (original preserved, nothing written)
      ▼
    DRAFT ──validate──▶ VALIDATED ──submit──▶ IN_REVIEW ──approve──▶ APPROVED ──▶ export
      │                     │                    │ reject
      │                     │ correct            ▼
      │                     ▼                 REJECTED ──correct & resubmit──▶ VALIDATED
      │              new version linked        │
      └────────────▶ ARCHIVED ◀────────────────┘   (originals never overwritten)

Exceptions: missing category → gap register · stale > 120d → STALE_DATA ·
contradictory duplicates > 25% → CONTRADICTION + consistency penalty ·
out-of-range → blocked at intake · late data → recency decay, never silent acceptance.""", language="text")
        with st.expander("🗂 Prioritized backlog"):
            st.markdown("""
| Tier | Capability |
|---|---|
| **MVP (this build)** | CSV/XLSX validation · EQS engine · gap register · scenario levers · roles & audit · tender approval · HTML/CSV/JSON export · self-tests · backup/restore · factor rollback |
| **Post-MVP** | FastAPI service layer (Pydantic, pagination, rate limits) · PostgreSQL multi-user · scheduled supplier reminders · evidence OCR assist · gap-closure classifier on real data · retention enforcement job |
| **Enterprise** | SSO/directory integration · audit export streaming · Docker + Linux hosting · SLA docs · custom licensed factor packs · API integrations (ERP/SRM) via documented adapters, mocked in dev |
""")
        with st.expander("⚠ Risk register"):
            st.markdown("""
| Risk | Domain | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| Demo factors mistaken for authoritative | Domain validity | Med | High | Loud synthetic labels; dated sources; qualified review gate |
| Garbage-in estimates treated as measured | Data quality | High | High | ±30% bands, ESTIMATE_HEAVY gaps, verification weighting |
| Confidential supplier bids leaked | Security | Med | High | Local-first SQLite, sensitivity classes, no secrets in logs, parameterized SQL |
| Reviewers rubber-stamp recommendations | Adoption | Med | Med | Mandatory reasons, conditional flags, radar transparency |
| DB corruption / interrupted import | Operational | Low | High | Per-file transactions, preserved originals, backup/restore with validation |
| Scope creep into full LCA claims | Domain validity | Med | High | Explicit boundary docs; decision-support positioning only |
""")
        with st.expander("🛡 Threat model & sensitive-data handling"):
            st.markdown("""
- **Assets:** supplier bids (confidential), evidence refs, decision reasons. **Actors:** four local roles; no network exposure in MVP.
- **Controls:** parameterized SQL everywhere (injection), HTML-escaped report content (XSS), 8 MB upload cap + type check,
  checksummed originals, append-only audit, no sensitive values in log details, role checks before every mutation.
- **Deployment posture:** local Windows demo → Docker + PostgreSQL + HTTPS + hashed passwords (argon2/bcrypt) + server-side
  authorization + rate-limited paginated API for the team edition. Secrets via environment variables only; none in this repo.
- **Not claimed:** certification, compliance attestation, or penetration-tested status.
""")
        with st.expander("🧰 Operator runbook — backup, restore, upgrade, PostgreSQL path"):
            st.markdown("""
1. **Backup:** Admin ▸ Data & backup ▸ download `.db`; copy `evidence_store/` beside it. Test restore into a scratch folder monthly.
2. **Restore:** upload `.db`, confirm; header + table validation runs before replacement; failure leaves current data untouched.
3. **Upgrade:** back up → pull new release → `pip install -r requirements.txt` → run Quality ▸ suite → verify schema version; engine rollback = redeploy prior tag.
4. **PostgreSQL migration:** schema is already normalized with stable IDs and JSON side-columns; swap the connection layer,
   map TEXT dates→DATE, REAL→DOUBLE PRECISION, add per-table migrations (Alembic), enable row-level auth for multi-user.
5. **Incident response:** stop intake toggle → backup current state → inspect audit log → restore last good backup → re-run suite → record incident in audit.
""")
        with st.expander("💼 Commercial tiers, pricing hypothesis & 90-day roadmap"):
            st.markdown("""
| Tier | What | Pricing hypothesis (to test in pilot) |
|---|---|---|
| Local MVP | 1 operator, SQLite, full loop | Free evaluation with synthetic dataset |
| Team | PostgreSQL, roles, approvals, shared audit | Per-seat annual subscription |
| Enterprise | SSO, deployment controls, API, SLA docs | Per-site license + support contract |

**Pilot success metric:** ≥50% reduction in evidence-check hours per tender across 5 real tenders, with
100% reasoned decisions — measured with the customer, not inferred. **90-day roadmap:** weeks 1–2 pilot
onboarding + feedback log · 3–6 FastAPI + PostgreSQL team edition · 7–10 reminder automation + licensed
factor pack · 11–13 pricing validation + enterprise deployment guide. Willingness to pay is validated
through interviews and a paid pilot before any revenue claim.
""")
        with st.expander("🧬 Entity relationships & license inventory"):
            st.code("""suppliers 1───* records *───1 imports(file, sha256)
suppliers 1───* overrides      records *───1 records (corrects chain)
tenders   1───* decisions      decisions include weight+score snapshot JSON
config(factor_version, retention, schema)   audit(app-only, every material change)
reference: FACTORS[version][activity] — dated, sourced, rollback-ready""", language="text")
            st.markdown("""
| Dependency | License | Commercial use |
|---|---|---|
| Streamlit | Apache-2.0 | ✔ permissive |
| pandas / NumPy | BSD-3-Clause | ✔ permissive |
| Plotly | MIT | ✔ permissive |
| openpyxl | MIT | ✔ permissive |
| SQLite | Public domain | ✔ unrestricted |

SBOM = `pip freeze` at deploy time (versions intentionally unpinned in this demo per request;
pin in production). No paid APIs. No external datasets bundled — all data synthetic and labeled.
""")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    st.set_page_config(page_title="Verdant IQ — Supplier Impact Analyzer", page_icon="🌿",
                       layout="wide", initial_sidebar_state="expanded")
    defaults = {"role": "Administrator", "dusk": True, "live_sim": True,
                "sim_speed_label": "Normal · 2.5s", "nav": PAGES[0],
                "feed": [], "trend": [], "sim_ok": 0, "sim_bad": 0,
                "undo": [], "tests": None}
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v
    ensure_seeded()
    if "bootstrapped" not in st.session_state:
        for _ in range(4): sim_tick()
        st.session_state.bootstrapped = True
    render_sidebar()
    inject_css()
    page = st.session_state.nav
    if page == PAGES[0]: page_command()
    elif page == PAGES[1]: page_import()
    elif page == PAGES[2]: page_records()
    elif page == PAGES[3]: page_analysis()
    elif page == PAGES[4]: page_gaps()
    elif page == PAGES[5]: page_review()
    elif page == PAGES[6]: page_reports()
    elif page == PAGES[7]: page_quality()
    else: page_admin()
    render_footer()

if __name__ == "__main__":
    main()