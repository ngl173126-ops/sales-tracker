"""Partner Sales Tracker — Streamlit + Google Sheet.

Dữ liệu lưu trong 1 Google Sheet (tab "leads"). Nếu chưa cấu hình Secrets,
app tự chạy ở chế độ thử với file leads_local.csv để xem giao diện.
"""
import json
import random
import re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

# ============ CẤU HÌNH — sửa ở đây nếu team thay đổi ============
TEAM = ["Mạnh", "Gấu", "Trà", "Cá"]
REMIND_DAYS = 3  # số ngày giữa các lần nhắc lại
# ==================================================================

st.set_page_config(page_title="Partner Sales Tracker", page_icon=":material/handshake:", layout="wide")

STAGES = ["Lead", "Outreach", "Discovery", "Proposal", "Contracting", "Closed Won", "Closed Lost", "Disqualified"]
FORWARD = ["Lead", "Outreach", "Discovery", "Proposal", "Contracting", "Closed Won"]
DETAIL_STAGE = {
    "No Action": "Lead", "Researching": "Lead",
    "Outreach Sent": "Outreach", "Follow-up Sent": "Outreach", "Unresponsive": "Outreach",
    "In Dialogue": "Discovery", "Meeting Scheduled": "Discovery", "Meeting Conducted": "Discovery",
    "In Drafting": "Proposal", "Under Review": "Proposal", "Revision Requested": "Proposal", "Verbal Agreement": "Proposal",
    "Contract Sent": "Contracting", "Pending Signature": "Contracting",
    "Won: Signed & Active": "Closed Won", "Won: Pending Initial Payment": "Closed Won",
    "Lost: Competitor": "Closed Lost", "Lost: Budget": "Closed Lost", "Lost: Internal": "Closed Lost", "Lost: Ghosted": "Closed Lost",
    "Disqualified: Fit": "Disqualified", "Disqualified: Contact": "Disqualified", "Disqualified: Interest": "Disqualified",
}
DETAILS = list(DETAIL_STAGE)
MODELS = ["B2C/B2B2C", "Marketplace/B2B2C", "B2C/Product", "B2B"]
SIZES = ["0-50", "51-200", "201-500", "501-1000", "1001-5000", "5000+"]
DOMAINS = ["FMCG", "F&B", "BFSI", "Tech", "Retail", "E-commerce", "Manufacturing"]

# (key, nhãn, trạng thái chuyển tới khi tick, bước trước đó để tính hạn nhắc)
STEPS = [
    ("research", "Research", "Researching", None),
    ("outreach", "Outreach", "Outreach Sent", None),
    ("r1", "Nhắc 1", "Follow-up Sent", "outreach"),
    ("r2", "Nhắc 2", "Follow-up Sent", "r1"),
    ("r3", "Nhắc 3", "Follow-up Sent", "r2"),
    ("meeting", "Meeting", "Meeting Conducted", None),
    ("proposal", "Proposal", "Under Review", None),
    ("contracting", "Contracting", "Contract Sent", None),
    ("signed", "Signed", "Won: Signed & Active", None),
]
STEP = {k: (label, detail, after) for k, label, detail, after in STEPS}
LABEL2STEP = {label: k for k, label, _, _ in STEPS}

COLUMNS = ["id", "linkedin", "name", "title", "company", "model", "size", "domain", "email", "phone",
           "pic", "stage", "detail", "signal", "offer", "milestones", "ctas", "rejection",
           *[s[0] for s in STEPS], "last_action", "created_at"]

# Cột bảng chính -> trường dữ liệu (cột sửa được)
TEXT_COLS = {"LinkedIn": "linkedin", "Tên": "name", "Chức danh": "title", "Công ty": "company",
             "PIC": "pic", "Trạng thái": "detail"}


def secret(key):
    try:
        return st.secrets[key]
    except Exception:
        return None


# ---------------- Lưu trữ ----------------
class SheetStore:
    """Google Sheet: mỗi lead 1 dòng, dòng 1 là tiêu đề cột."""

    def __init__(self):
        import gspread
        from google.oauth2.service_account import Credentials

        self.gspread = gspread
        info = json.loads(secret("gcp_json"))
        creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        sh = gspread.authorize(creds).open_by_url(secret("sheet_url"))
        try:
            self.ws = sh.worksheet("leads")
        except gspread.WorksheetNotFound:
            self.ws = sh.add_worksheet("leads", rows=1000, cols=len(COLUMNS))
        header = [h.strip() for h in self.ws.row_values(1)]
        if not header:
            header = list(COLUMNS)
            self.ws.update(values=[header], range_name="A1")
        missing = [c for c in COLUMNS if c not in header]
        if missing:
            header += missing
            self.ws.update(values=[header], range_name="A1")
        self.header = header

    def load(self):
        values = self.ws.get_all_values()
        n = len(self.header)
        rows = [(r + [""] * n)[:n] for r in values[1:]]
        df = pd.DataFrame(rows, columns=self.header)
        # Dòng ai đó gõ tay thẳng vào Sheet mà chưa có id -> cấp id
        fix = []
        for i, r in df.iterrows():
            if not r["id"] and any(str(v).strip() for v in r.values):
                df.at[i, "id"] = uuid.uuid4().hex[:10]
                fix.append({"range": self.gspread.utils.rowcol_to_a1(i + 2, self.header.index("id") + 1),
                            "values": [[df.at[i, "id"]]]})
        if fix:
            self.ws.batch_update(fix, value_input_option="RAW")
        return df

    def append(self, records):
        self.ws.append_rows([[r.get(c, "") for c in self.header] for r in records], value_input_option="RAW")

    def update(self, changes):
        ids = self.ws.col_values(self.header.index("id") + 1)
        data = []
        for lid, fields in changes.items():
            if lid not in ids:
                continue
            row = ids.index(lid) + 1
            for k, v in fields.items():
                data.append({"range": self.gspread.utils.rowcol_to_a1(row, self.header.index(k) + 1), "values": [[v]]})
        if data:
            self.ws.batch_update(data, value_input_option="RAW")


class LocalStore:
    """Chế độ thử: lưu vào leads_local.csv cạnh app.py."""

    path = Path(__file__).with_name("leads_local.csv")

    def load(self):
        if not self.path.exists():
            return pd.DataFrame(columns=COLUMNS)
        return pd.read_csv(self.path, dtype=str, keep_default_na=False)

    def _save(self, df):
        df.to_csv(self.path, index=False)

    def append(self, records):
        df = normalize(self.load())
        self._save(pd.concat([df, pd.DataFrame(records)], ignore_index=True))

    def update(self, changes):
        df = normalize(self.load()).set_index("id")
        for lid, fields in changes.items():
            if lid in df.index:
                for k, v in fields.items():
                    df.at[lid, k] = v
        self._save(df.reset_index())


@st.cache_resource
def get_store():
    return SheetStore() if secret("gcp_json") and secret("sheet_url") else LocalStore()


def normalize(df):
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df.fillna("").astype(str)


@st.cache_data(ttl=20, show_spinner=False)
def load_df():
    return normalize(get_store().load())


def save_changes(changes, msg=None):
    if not changes:
        return
    get_store().update(changes)
    load_df.clear()
    st.session_state.ver = st.session_state.get("ver", 0) + 1
    if msg:
        st.session_state.flash = msg


# ---------------- Logic ngày & nhắc lại ----------------
def parse_d(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            pass
    return None


def ddmm(d):
    return d.strftime("%d/%m") if d else ""


def remind_due(r, k):
    after = STEP[k][2]
    if not parse_d(r["outreach"]):
        return None
    base = parse_d(r[after]) or (remind_due(r, after) if after != "outreach" else None)
    return base + timedelta(days=REMIND_DAYS) if base else None


def remind_active(r):
    if not parse_d(r["outreach"]):
        return False
    if any(parse_d(r[k]) for k in ("meeting", "proposal", "contracting", "signed")):
        return False
    return DETAIL_STAGE.get(r["detail"], r["stage"]) in ("Lead", "Outreach")


def next_due(r):
    if not remind_active(r):
        return None
    for k in ("r1", "r2", "r3"):
        if not parse_d(r[k]):
            return remind_due(r, k)
    return None


def due_label(r):
    d = next_due(r)
    if not d:
        return ""
    if d < date.today():
        return f"⚠️ trễ {ddmm(d)}"
    if d == date.today():
        return "⚠️ hôm nay"
    return ddmm(d)


def last_step(r):
    for k, label, _, _ in reversed(STEPS):
        d = parse_d(r[k])
        if d:
            return f"{label} · {ddmm(d)}"
    return ""


def advance(cur, k):
    """Tick 1 bước -> đẩy trạng thái lên nếu bước đó đi xa hơn trạng thái hiện tại."""
    stage = DETAIL_STAGE.get(cur["detail"], cur["stage"] or "Lead")
    if stage in ("Closed Lost", "Disqualified"):
        return {}
    new_detail = STEP[k][1]
    new_stage = DETAIL_STAGE[new_detail]
    ci, ni = FORWARD.index(stage) if stage in FORWARD else 0, FORWARD.index(new_stage)
    if ni > ci or (ni == ci and DETAILS.index(new_detail) > (DETAILS.index(cur["detail"]) if cur["detail"] in DETAILS else -1)):
        return {"detail": new_detail, "stage": new_stage}
    return {}


def norm_linkedin(url):
    u = url.strip()
    if not u:
        return ""
    if not u.startswith("http"):
        u = "https://" + u
    u = re.sub(r"[?#].*$", "", u).rstrip("/")
    u = re.sub(r"^https?://([a-z]{2,3}\.)?linkedin\.com", "https://www.linkedin.com", u, flags=re.I)
    return u


# ---------------- Bảng lead (tick là lưu) ----------------
def on_table_edit(editor_key, ids):
    edits = st.session_state[editor_key]["edited_rows"]
    rows = load_df().set_index("id")
    today = date.today().isoformat()
    changes, ticked = {}, []
    for idx, cols in edits.items():
        lid = ids[int(idx)]
        if lid not in rows.index:
            continue
        cur = rows.loc[lid].to_dict()
        ch = {}
        for col, val in cols.items():
            if col in LABEL2STEP:
                k = LABEL2STEP[col]
                if val and not cur[k]:
                    ch[k] = today
                    ch.update(advance({**cur, **ch}, k))
                    ticked.append(f"{col} – {cur['name'] or cur['company']}")
                elif not val and cur[k]:
                    ch[k] = ""
            elif col in TEXT_COLS:
                field = TEXT_COLS[col]
                if field == "linkedin":
                    val = norm_linkedin(val or "")
                ch[field] = (val or "").strip()
                if field == "detail" and ch[field] in DETAIL_STAGE:
                    ch["stage"] = DETAIL_STAGE[ch[field]]
        if ch:
            ch["last_action"] = today
            changes[lid] = ch
    save_changes(changes, ("Đã tick: " + ", ".join(ticked)) if ticked else "Đã lưu.")


def lead_table(df, key, hide=()):
    if df.empty:
        st.info("Chưa có lead nào ở đây.")
        return
    ids = list(df["id"])
    view = pd.DataFrame({
        "LinkedIn": df["linkedin"].values,
        "Tên": df["name"].values,
        "Chức danh": df["title"].values,
        "Công ty": df["company"].values,
        "PIC": df["pic"].values,
        "Trạng thái": df["detail"].values,
        **{label: df[k].map(lambda v: bool(parse_d(v))).values for k, label, _, _ in STEPS},
        "Hạn nhắc": [due_label(r) for _, r in df.iterrows()],
        "Gần nhất": [last_step(r) for _, r in df.iterrows()],
    })
    pics = TEAM + sorted(set(df["pic"]) - set(TEAM) - {""})
    cfg = {
        "LinkedIn": st.column_config.LinkColumn(
            "LinkedIn", width=95,
            display_text=r"https?://(?:www\.)?linkedin\.com/in/([^/?#]+).*"),
        "Tên": st.column_config.TextColumn("Tên", width=160),
        "Chức danh": st.column_config.TextColumn("Chức danh", width=170),
        "Công ty": st.column_config.TextColumn("Công ty", width=140),
        "PIC": st.column_config.SelectboxColumn("PIC", options=pics, width=75),
        "Trạng thái": st.column_config.SelectboxColumn("Trạng thái", options=DETAILS, width=135),
        "Hạn nhắc": st.column_config.TextColumn("Hạn nhắc", disabled=True, width=95,
                                                help=f"Sau khi Outreach, cứ {REMIND_DAYS} ngày nhắc 1 lần"),
        "Gần nhất": st.column_config.TextColumn("Bước gần nhất", disabled=True, width=120),
        **{label: st.column_config.CheckboxColumn(label, width=72, help="Tick = ghi ngày hôm nay")
           for _, label, _, _ in STEPS},
    }
    order = [c for c in view.columns if c not in hide]
    editor_key = f"{key}_{st.session_state.get('ver', 0)}"
    st.data_editor(view, key=editor_key, hide_index=True, column_config=cfg, column_order=order,
                   width="stretch", num_rows="fixed",
                   height=min(38 + 35 * len(view), 640),
                   on_change=on_table_edit, args=(editor_key, ids))


def detail_form(df, key):
    """Sửa đầy đủ thông tin 1 lead (các trường như file Excel cũ)."""
    if df.empty:
        return
    with st.expander("Sửa chi tiết 1 lead (email, SĐT, milestones, CTAs…)", icon=":material/edit_note:"):
        labels = {r.id: f"{r.name or '(chưa có tên)'} — {r.company or '(chưa có công ty)'}" for r in df.itertuples()}
        lid = st.selectbox("Chọn lead", list(labels), format_func=labels.get, key=f"{key}_pick")
        r = df.set_index("id").loc[lid]
        with st.form(f"{key}_form_{lid}_{st.session_state.get('ver', 0)}"):
            c1, c2 = st.columns(2)
            v = {}
            v["linkedin"] = c1.text_input("LinkedIn", r.linkedin)
            v["pic"] = c2.selectbox("PIC", [""] + TEAM, index=([""] + TEAM).index(r.pic) if r.pic in TEAM else 0)
            v["name"] = c1.text_input("Tên", r["name"])
            v["title"] = c2.text_input("Chức danh", r.title)
            v["company"] = c1.text_input("Công ty", r.company)
            v["detail"] = c2.selectbox("Trạng thái", DETAILS, index=DETAILS.index(r.detail) if r.detail in DETAILS else 0)
            v["email"] = c1.text_input("Email", r.email)
            v["phone"] = c2.text_input("Điện thoại", r.phone)
            c3, c4, c5 = st.columns(3)
            v["model"] = c3.selectbox("Business model", [""] + MODELS, index=([""] + MODELS).index(r.model) if r.model in MODELS else 0)
            v["size"] = c4.selectbox("Quy mô", [""] + SIZES, index=([""] + SIZES).index(r["size"]) if r["size"] in SIZES else 0)
            v["domain"] = c5.selectbox("Ngành", [""] + DOMAINS, index=([""] + DOMAINS).index(r.domain) if r.domain in DOMAINS else 0)
            v["signal"] = c1.text_input("Signal", r.signal)
            v["offer"] = c2.text_input("Offer", r.offer)
            v["milestones"] = st.text_area("Milestones (DD/MM/YYYY: chuyện gì đã xảy ra)", r.milestones, height=80)
            v["ctas"] = st.text_area("CTAs (Scope – CTA – Deadline)", r.ctas, height=80)
            v["rejection"] = st.text_input("Lý do từ chối", r.rejection)
            st.caption("Ngày từng bước — sửa nếu tick nhầm ngày")
            dcols = st.columns(5)
            for i, (k, label, _, _) in enumerate(STEPS):
                d = dcols[i % 5].date_input(label, value=parse_d(r[k]), format="DD/MM/YYYY", key=f"{key}_{lid}_{k}")
                v[k] = d.isoformat() if d else ""
            if st.form_submit_button("Lưu", type="primary"):
                ch = {k: (val.strip() if isinstance(val, str) else val) for k, val in v.items() if val != r[k]}
                if "linkedin" in ch:
                    ch["linkedin"] = norm_linkedin(ch["linkedin"])
                if "detail" in ch:
                    ch["stage"] = DETAIL_STAGE[ch["detail"]]
                if ch:
                    ch["last_action"] = date.today().isoformat()
                    save_changes({lid: ch}, "Đã lưu thông tin lead.")
                    st.rerun()


def random_split(ids, members):
    ids, members = ids[:], members[:]
    random.shuffle(ids)
    random.shuffle(members)
    return {lid: members[i % len(members)] for i, lid in enumerate(ids)}


# ---------------- Giao diện ----------------
st.markdown("""
<style>
.block-container{padding-top:2.2rem;padding-bottom:3rem}
[data-testid="stMetricValue"]{font-size:1.6rem}
h1{font-size:1.7rem!important}
</style>""", unsafe_allow_html=True)

# Mật khẩu (tuỳ chọn): thêm app_password vào Secrets để bật
pw = secret("app_password")
if pw and not st.session_state.get("authed"):
    st.title("Partner Sales Tracker")
    with st.form("login"):
        p = st.text_input("Mật khẩu của team", type="password")
        if st.form_submit_button("Vào", type="primary"):
            if p == pw:
                st.session_state.authed = True
                st.rerun()
            st.error("Sai mật khẩu.")
    st.stop()

if "flash" in st.session_state:
    st.toast(st.session_state.pop("flash"), icon=":material/check_circle:")

try:
    df = load_df()
except Exception as e:
    st.error("Không đọc được Google Sheet. Kiểm tra lại Secrets và đã share Sheet cho email service account chưa.")
    st.exception(e)
    st.stop()

with st.sidebar:
    st.markdown("### Partner Sales Tracker")
    qp_me = st.query_params.get("me")
    me = st.selectbox("Tôi là", TEAM, index=TEAM.index(qp_me) if qp_me in TEAM else None, placeholder="Chọn tên của bạn")
    if me and me != qp_me:
        st.query_params["me"] = me
    page = st.radio("Trang", [":material/person: Lead của tôi", ":material/search: Tra công ty",
                              ":material/add_link: Thêm lead LinkedIn", ":material/groups: Cả team"],
                    label_visibility="collapsed")
    if me:
        st.caption(f"Mẹo: lưu lại link trang này, lần sau mở là vào thẳng danh sách của {me}.")
    if isinstance(get_store(), LocalStore):
        st.warning("Đang chạy chế độ thử (lưu vào file CSV). Cấu hình Secrets để dùng Google Sheet.")
    if st.button("Tải lại dữ liệu", icon=":material/refresh:", width="stretch"):
        load_df.clear()
        st.rerun()

today = date.today()
df = df.copy()
df["_due"] = [next_due(r) for _, r in df.iterrows()]
if df.empty:
    st.info("Sheet đang trống. Kiểm tra tab **leads** trong Google Sheet đã có dữ liệu chưa, hoặc vào trang **Thêm lead LinkedIn** để thêm lead.")

# ===== Lead của tôi =====
if page.endswith("Lead của tôi"):
    if not me:
        st.title("Lead của tôi")
        st.info("Chọn tên của bạn ở thanh bên trái để xem danh sách lead được chia.")
        st.stop()
    mine = df[df.pic == me]
    st.title(f"Lead của {me}")
    due_now = mine[mine._due.map(lambda d: d is not None and d <= today)]
    not_out = mine[(mine.outreach == "") & ~mine.detail.str.startswith(("Lost", "Disqualified", "Won"))]
    talking = mine[mine.detail.map(lambda d: DETAIL_STAGE.get(d) in ("Discovery", "Proposal", "Contracting"))]
    m = st.columns(4)
    m[0].metric("Tổng lead", len(mine))
    m[1].metric("Cần nhắc hôm nay", len(due_now))
    m[2].metric("Chưa outreach", len(not_out))
    m[3].metric("Đang trao đổi", len(talking))

    f1, f2 = st.columns([3, 2])
    view = f1.segmented_control("Lọc", ["Tất cả", "Cần nhắc hôm nay", "Chưa outreach", "Đang trao đổi"],
                                default="Tất cả", label_visibility="collapsed") or "Tất cả"
    q = f2.text_input("Tìm", placeholder="Tìm tên, công ty, chức danh…", label_visibility="collapsed")
    show = {"Tất cả": mine, "Cần nhắc hôm nay": due_now, "Chưa outreach": not_out, "Đang trao đổi": talking}[view]
    if q:
        ql = q.lower()
        show = show[[ql in f"{n} {c} {t}".lower() for n, c, t in zip(show["name"], show["company"], show["title"])]]
    show = show.assign(_k=show._due.map(lambda d: d or date.max)).sort_values(["_k", "company"])
    st.caption("Tick vào ô là lưu luôn ngày hôm nay. Gõ tên & chức danh trực tiếp vào bảng.")
    lead_table(show, "mine", hide=("PIC",))
    detail_form(show, "mine")

# ===== Tra công ty =====
elif page.endswith("Tra công ty"):
    st.title("Tra công ty")
    counts = df[df.company != ""].groupby("company").size().sort_index()
    co = st.selectbox("Công ty", list(counts.index), index=None, placeholder="Gõ tên công ty…",
                      format_func=lambda c: f"{c}  ({counts[c]} người)")
    if co:
        sub = df[df.company == co]
        info = sub.iloc[0]
        meta = " · ".join(x for x in [info.domain, info.model, f"{info['size']} nhân sự" if info["size"] else ""] if x)
        st.subheader(co)
        if meta:
            st.caption(meta)
        st.markdown(f"**{len(sub)} người cần liên hệ** — PIC: {', '.join(sorted(set(sub.pic) - {''})) or 'chưa chia'}")
        lead_table(sub.sort_values("name"), "co", hide=("Công ty",))
        detail_form(sub, "co")
    else:
        st.caption(f"{len(counts)} công ty · {len(df)} người liên hệ")

# ===== Thêm lead LinkedIn =====
elif page.endswith("Thêm lead LinkedIn"):
    st.title("Thêm lead từ LinkedIn")
    st.markdown("Dán link LinkedIn, **mỗi dòng 1 người**. Có thể dán kèm thông tin, cách nhau bằng dấu `|` hoặc Tab:  \n"
                "`link | Tên | Chức danh | Công ty` — thiếu thì để trống, gõ tay sau trong bảng.")
    txt = st.text_area("Link LinkedIn", height=180, label_visibility="collapsed",
                       placeholder="https://www.linkedin.com/in/nguyen-van-a\nhttps://www.linkedin.com/in/tran-thi-b | Trần Thị B | HR Director | Jollibee Vietnam")
    c1, c2 = st.columns([2, 3])
    company_all = c1.text_input("Công ty chung (nếu cả list cùng 1 công ty)")
    members = c2.multiselect("Chia ngẫu nhiên cho", TEAM, default=TEAM)

    existing = set(df.linkedin.map(norm_linkedin)) - {""}
    parsed, dup = [], 0
    for line in txt.splitlines():
        parts = [p.strip() for p in re.split(r"\t|\|", line)]
        link = next((p for p in parts if "linkedin.com" in p.lower()), "")
        if not link:
            continue
        rest = [p for p in parts if p != link]
        link = norm_linkedin(link)
        if link in existing or any(p["linkedin"] == link for p in parsed):
            dup += 1
            continue
        parsed.append({"linkedin": link, "name": rest[0] if len(rest) > 0 else "",
                       "title": rest[1] if len(rest) > 1 else "",
                       "company": (rest[2] if len(rest) > 2 else "") or company_all.strip()})
    if txt.strip():
        st.caption(f"Đọc được **{len(parsed)}** link mới" + (f" · bỏ qua {dup} link đã có/trùng" if dup else ""))
        if parsed:
            st.dataframe(pd.DataFrame(parsed).rename(columns={"linkedin": "LinkedIn", "name": "Tên", "title": "Chức danh", "company": "Công ty"}),
                         hide_index=True, width="stretch",
                         column_config={"LinkedIn": st.column_config.LinkColumn(display_text=r"https?://(?:www\.)?linkedin\.com/in/([^/?#]+).*")})
    if st.button(f"Thêm {len(parsed)} lead & chia ngẫu nhiên", type="primary", disabled=not parsed or not members):
        now = datetime.now().isoformat(timespec="seconds")
        recs = [{**p, "id": uuid.uuid4().hex[:10], "stage": "Lead", "detail": "No Action", "created_at": now} for p in parsed]
        split = random_split([r["id"] for r in recs], members)
        for r in recs:
            r["pic"] = split[r["id"]]
        get_store().append(recs)
        load_df.clear()
        st.session_state.ver = st.session_state.get("ver", 0) + 1
        result = pd.Series([r["pic"] for r in recs]).value_counts()
        st.session_state.flash = "Đã thêm & chia: " + ", ".join(f"{k} {v}" for k, v in result.items())
        st.rerun()

# ===== Cả team =====
else:
    st.title("Cả team")
    if df.empty:
        st.stop()
    stage_of = df.detail.map(lambda d: DETAIL_STAGE.get(d, "Lead"))
    pivot = pd.crosstab(df.pic.replace("", "(chưa chia)"), stage_of).reindex(columns=[s for s in STAGES if s in set(stage_of)], fill_value=0)
    pivot["Cần nhắc hôm nay"] = df.groupby(df.pic.replace("", "(chưa chia)"))._due.apply(lambda s: sum(1 for d in s if d and d <= today))
    pivot["Tổng"] = pivot[[s for s in STAGES if s in pivot.columns]].sum(axis=1)
    st.dataframe(pivot, width="stretch")

    unassigned = df[df.pic == ""]
    with st.expander(f"Chia ngẫu nhiên lead chưa có PIC ({len(unassigned)})", icon=":material/shuffle:", expanded=bool(len(unassigned))):
        mem = st.multiselect("Chia cho", TEAM, default=TEAM, key="split_mem")
        if st.button("Chia ngay", type="primary", disabled=unassigned.empty or not mem):
            split = random_split(list(unassigned.id), mem)
            save_changes({lid: {"pic": p} for lid, p in split.items()},
                         "Đã chia: " + ", ".join(f"{k} {v}" for k, v in pd.Series(split).value_counts().items()))
            st.rerun()

    f1, f2 = st.columns([1, 2])
    who = f1.selectbox("PIC", ["Tất cả"] + TEAM + ["(chưa chia)"])
    q = f2.text_input("Tìm", placeholder="Tìm tên, công ty…", key="team_q")
    show = df if who == "Tất cả" else df[df.pic == ("" if who == "(chưa chia)" else who)]
    if q:
        ql = q.lower()
        show = show[[ql in f"{n} {c} {t}".lower() for n, c, t in zip(show["name"], show["company"], show["title"])]]
    lead_table(show.sort_values(["company", "name"]), "team")
    detail_form(show, "team")
