"""
admin.py  —  TestDB.db administratora logs
──────────────────────────────────────────
Vienkāršs Tkinter administratora rīks visu tabulu rediģēšanai.

Novieto šo failu tajā pašā mapē, kur atrodas:
  TestDB.db
  launcher.py
  12_a_NikolsGabriels_TestaAplikacija.py
  utt.

Palaist:  python admin.py
"""

import os
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

# ─── Faila ceļš ──────────────────────────────────────────────────────────────
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(THIS_DIR, "TestDB.db")


# ─── DB savienojums ──────────────────────────────────────────────────────────
def db():
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(
            f"Datubāze nav atrasta:\n{DB_PATH}\n\n"
            "Pārliecinies, ka admin.py atrodas tajā pašā mapē, kur TestDB.db."
        )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ─── Entītāšu apraksti ───────────────────────────────────────────────────────
# Katrai entītātei: tabulas nosaukums, lasāmais nosaukums un formas lauki.
# Lauks: (kolonna, etiķete, vidžeta tips, [opcijas])
ENTITY = {
    "section": {
        "table": "sections",
        "label": "Sadaļa",
        "fields": [("nosaukums", "Nosaukums", "entry")],
    },
    "chapter": {
        "table": "chapters",
        "label": "Nodaļa",
        "fields": [("nosaukums", "Nosaukums", "entry")],
    },
    "page": {
        "table": "pages",
        "label": "Lapa",
        "fields": [
            ("lapa_num",  "Lapas numurs (kārtošanai)", "entry"),
            ("lapa_tips", "Tips (mainās, pievienojot saturu)", "readonly"),
        ],
    },
    "challenge": {
        "table": "challenges",
        "label": "Kodēšanas uzdevums",
        "fields": [
            ("virsraksts",   "Virsraksts",            "entry"),
            ("apraksts",     "Apraksts",              "text"),
            ("starter_code", "Sākuma kods",           "text"),
            ("max_laiks",    "Maks. izpildes laiks (sek.)", "entry"),
        ],
    },
    "challenge_test": {
        "table": "challenge_testi",
        "label": "Uzdevuma tests",
        "fields": [
            ("apraksts",         "Apraksts",                                   "entry"),
            ("ievaddati_json",   "Ievaddati JSON formātā (piem. {\"a\":5,\"b\":10}). Atstāj tukšu, ja nav.", "text"),
            ("sagaidita_izvade", "Sagaidītā izvade",                           "text"),
        ],
    },
    "theory_page": {
        "table": "theory_pages",
        "label": "Teorijas lapa",
        "fields": [("virsraksts", "Virsraksts", "entry")],
    },
    "theory_section": {
        "table": "theory_sections",
        "label": "Teorijas bloks",
        "fields": [
            ("tips",   "Tips",   "combo", ["text", "heading", "code"]),
            ("saturs", "Saturs", "text"),
        ],
    },
    "test": {
        "table": "tests",
        "label": "Pārbaudes darbs",
        "fields": [
            ("virsraksts",      "Virsraksts",                  "entry"),
            ("apraksts",        "Apraksts",                    "text"),
            ("nokartosanas_sl", "Nokārtošanas slieksnis (%)",  "entry"),
        ],
    },
    "test_jautajums": {
        "table": "test_jautajumi",
        "label": "Jautājums",
        "fields": [
            ("tips",            "Tips", "combo", ["multiple_choice", "code"]),
            ("jautajums",       "Jautājums",                                 "text"),
            ("punkti",          "Punkti",                                    "entry"),
            ("pareiza_atbilde", "Pareizās atbildes opcijas ID (tikai multiple_choice)", "entry"),
            ("starter_code",    "Sākuma kods (tikai code tipam)",            "text"),
            ("max_laiks",       "Maks. izpildes laiks (tikai code tipam)",   "entry"),
        ],
    },
    "mc_opcija": {
        "table": "mc_opcijas",
        "label": "Atbildes opcija",
        "fields": [("teksts", "Teksts", "entry")],
    },
    "test_jaut_test": {
        "table": "test_jaut_testi",
        "label": "Jautājuma tests",
        "fields": [
            ("apraksts",         "Apraksts",                  "entry"),
            ("ievaddati_json",   "Ievaddati JSON formātā",    "text"),
            ("sagaidita_izvade", "Sagaidītā izvade",          "text"),
        ],
    },
}

# Skaitliskās kolonnas (lai pareizi konvertētu no ievades)
INT_COLS   = {"lapa_num", "punkti", "nokartosanas_sl", "pareiza_atbilde"}
FLOAT_COLS = {"max_laiks"}


# ─── Koka navigācija ────────────────────────────────────────────────────────
def get_children(node_type, node_id):
    """Atgriež [(bērna_tips, bērna_id, etiķete), ...]."""
    conn = db()
    out = []
    try:
        if node_type is None:
            for r in conn.execute("SELECT id, nosaukums FROM sections ORDER BY id"):
                out.append(("section", r["id"], f"[#{r['id']}] {r['nosaukums']}"))

        elif node_type == "section":
            for r in conn.execute(
                "SELECT id, nosaukums FROM chapters WHERE section_id=? ORDER BY id",
                (node_id,)
            ):
                out.append(("chapter", r["id"], f"[#{r['id']}] {r['nosaukums']}"))

        elif node_type == "chapter":
            for r in conn.execute(
                "SELECT id, lapa_num, lapa_tips FROM pages WHERE chapter_id=? ORDER BY lapa_num",
                (node_id,)
            ):
                out.append(("page", r["id"],
                            f"Lapa {r['lapa_num']} [{r['lapa_tips']}] (#{r['id']})"))

        elif node_type == "page":
            p = conn.execute("SELECT lapa_tips FROM pages WHERE id=?", (node_id,)).fetchone()
            if p:
                if p["lapa_tips"] == "challenge":
                    r = conn.execute(
                        "SELECT id, virsraksts FROM challenges WHERE page_id=?",
                        (node_id,)
                    ).fetchone()
                    if r:
                        out.append(("challenge", r["id"],
                                    f"[#{r['id']}] {r['virsraksts'] or '(bez nosaukuma)'}"))
                elif p["lapa_tips"] == "theory":
                    r = conn.execute(
                        "SELECT id, virsraksts FROM theory_pages WHERE page_id=?",
                        (node_id,)
                    ).fetchone()
                    if r:
                        out.append(("theory_page", r["id"],
                                    f"[#{r['id']}] {r['virsraksts'] or '(bez nosaukuma)'}"))
                elif p["lapa_tips"] == "test":
                    r = conn.execute(
                        "SELECT id, virsraksts FROM tests WHERE page_id=?",
                        (node_id,)
                    ).fetchone()
                    if r:
                        out.append(("test", r["id"],
                                    f"[#{r['id']}] {r['virsraksts'] or '(bez nosaukuma)'}"))

        elif node_type == "challenge":
            row = conn.execute("SELECT page_id FROM challenges WHERE id=?", (node_id,)).fetchone()
            if row:
                for r in conn.execute(
                    "SELECT id, apraksts FROM challenge_testi WHERE page_id=? ORDER BY id",
                    (row["page_id"],)
                ):
                    out.append(("challenge_test", r["id"],
                                f"[#{r['id']}] {r['apraksts'] or '(bez apraksta)'}"))

        elif node_type == "theory_page":
            row = conn.execute("SELECT page_id FROM theory_pages WHERE id=?", (node_id,)).fetchone()
            if row:
                for r in conn.execute(
                    "SELECT id, tips, saturs FROM theory_sections WHERE page_id=? ORDER BY id",
                    (row["page_id"],)
                ):
                    snippet = (r["saturs"] or "").replace("\n", " ")[:50]
                    out.append(("theory_section", r["id"],
                                f"[#{r['id']}] [{r['tips']}] {snippet}"))

        elif node_type == "test":
            # NB: test_jautajumi.test_id glabā page_id, nevis tests.id
            row = conn.execute("SELECT page_id FROM tests WHERE id=?", (node_id,)).fetchone()
            if row:
                for r in conn.execute(
                    "SELECT id, tips, jautajums FROM test_jautajumi WHERE test_id=? ORDER BY id",
                    (row["page_id"],)
                ):
                    snippet = (r["jautajums"] or "").replace("\n", " ")[:50]
                    out.append(("test_jautajums", r["id"],
                                f"[#{r['id']}] [{r['tips']}] {snippet}"))

        elif node_type == "test_jautajums":
            q = conn.execute("SELECT tips FROM test_jautajumi WHERE id=?", (node_id,)).fetchone()
            if q:
                if q["tips"] == "multiple_choice":
                    for r in conn.execute(
                        "SELECT id, teksts FROM mc_opcijas WHERE jautajums_id=? ORDER BY id",
                        (node_id,)
                    ):
                        out.append(("mc_opcija", r["id"], f"[#{r['id']}] {r['teksts']}"))
                elif q["tips"] == "code":
                    for r in conn.execute(
                        "SELECT id, apraksts FROM test_jaut_testi WHERE jautajums_id=? ORDER BY id",
                        (node_id,)
                    ):
                        out.append(("test_jaut_test", r["id"],
                                    f"[#{r['id']}] {r['apraksts'] or '(bez apraksta)'}"))
    finally:
        conn.close()
    return out


def addable_children(node_type, node_id):
    """Kādus bērnus var pievienot šim mezglam?"""
    if node_type is None:
        return ["section"]
    if node_type == "section":
        return ["chapter"]
    if node_type == "chapter":
        return ["page"]
    if node_type == "page":
        # tikai viens tipa bērns; ja tāds jau ir, pievienot nevar
        existing = get_children("page", node_id)
        return [] if existing else ["challenge", "theory_page", "test"]
    if node_type == "challenge":
        return ["challenge_test"]
    if node_type == "theory_page":
        return ["theory_section"]
    if node_type == "test":
        return ["test_jautajums"]
    if node_type == "test_jautajums":
        conn = db()
        q = conn.execute("SELECT tips FROM test_jautajumi WHERE id=?", (node_id,)).fetchone()
        conn.close()
        if not q:
            return []
        if q["tips"] == "multiple_choice":
            return ["mc_opcija"]
        if q["tips"] == "code":
            return ["test_jaut_test"]
    return []


# ─── Pievienošana ar saprātīgiem noklusējumiem ──────────────────────────────
def insert_child(parent_type, parent_id, child_type):
    conn = db()
    try:
        c = conn.cursor()

        if child_type == "section":
            c.execute("INSERT INTO sections(nosaukums) VALUES (?)", ("Jauna sadaļa",))

        elif child_type == "chapter":
            c.execute("INSERT INTO chapters(section_id, nosaukums) VALUES (?, ?)",
                      (parent_id, "Jauna nodaļa"))

        elif child_type == "page":
            n = c.execute(
                "SELECT COALESCE(MAX(lapa_num), 0) + 1 FROM pages WHERE chapter_id=?",
                (parent_id,)
            ).fetchone()[0]
            c.execute("INSERT INTO pages(chapter_id, lapa_num, lapa_tips) VALUES (?, ?, ?)",
                      (parent_id, n, "challenge"))

        elif child_type == "challenge":
            c.execute("UPDATE pages SET lapa_tips='challenge' WHERE id=?", (parent_id,))
            c.execute(
                "INSERT INTO challenges(page_id, virsraksts, apraksts, starter_code, max_laiks) "
                "VALUES (?, ?, ?, ?, ?)",
                (parent_id, "Jauns uzdevums", "Apraksta teksts...", "# Tavs kods\n", 1.0)
            )

        elif child_type == "theory_page":
            c.execute("UPDATE pages SET lapa_tips='theory' WHERE id=?", (parent_id,))
            c.execute("INSERT INTO theory_pages(page_id, virsraksts) VALUES (?, ?)",
                      (parent_id, "Jauna teorijas lapa"))

        elif child_type == "test":
            c.execute("UPDATE pages SET lapa_tips='test' WHERE id=?", (parent_id,))
            c.execute(
                "INSERT INTO tests(page_id, virsraksts, apraksts, nokartosanas_sl) "
                "VALUES (?, ?, ?, ?)",
                (parent_id, "Jauns pārbaudes darbs", "Apraksta teksts...", 60)
            )

        elif child_type == "challenge_test":
            page_id = c.execute("SELECT page_id FROM challenges WHERE id=?",
                                (parent_id,)).fetchone()[0]
            c.execute(
                "INSERT INTO challenge_testi(page_id, apraksts, ievaddati_json, sagaidita_izvade) "
                "VALUES (?, ?, ?, ?)",
                (page_id, "Jauns tests", None, "")
            )

        elif child_type == "theory_section":
            page_id = c.execute("SELECT page_id FROM theory_pages WHERE id=?",
                                (parent_id,)).fetchone()[0]
            c.execute("INSERT INTO theory_sections(page_id, tips, saturs) VALUES (?, ?, ?)",
                      (page_id, "text", "Jauns teksta saturs"))

        elif child_type == "test_jautajums":
            # NB: test_jautajumi.test_id glabā page_id, nevis tests.id
            page_id = c.execute("SELECT page_id FROM tests WHERE id=?",
                                (parent_id,)).fetchone()[0]
            c.execute(
                "INSERT INTO test_jautajumi(test_id, tips, jautajums, punkti, max_laiks) "
                "VALUES (?, ?, ?, ?, ?)",
                (page_id, "multiple_choice", "Jauns jautājums", 10, 1.0)
            )

        elif child_type == "mc_opcija":
            c.execute("INSERT INTO mc_opcijas(jautajums_id, teksts) VALUES (?, ?)",
                      (parent_id, "Jauna opcija"))

        elif child_type == "test_jaut_test":
            c.execute(
                "INSERT INTO test_jaut_testi(jautajums_id, apraksts, ievaddati_json, sagaidita_izvade) "
                "VALUES (?, ?, ?, ?)",
                (parent_id, "Jauns tests", None, "")
            )
        else:
            return None

        new_id = c.lastrowid
        conn.commit()
        return new_id
    finally:
        conn.close()


# ─── Kaskādes dzēšana ───────────────────────────────────────────────────────
def delete_node(node_type, node_id):
    # Vispirms rekursīvi izdzēš visus bērnus
    for ct, cid, _ in get_children(node_type, node_id):
        delete_node(ct, cid)

    conn = db()
    try:
        # Īpašie gadījumi: tabulām ar saiti uz page_id, ne id
        if node_type == "challenge":
            row = conn.execute("SELECT page_id FROM challenges WHERE id=?",
                               (node_id,)).fetchone()
            if row:
                conn.execute("DELETE FROM challenge_testi WHERE page_id=?", (row["page_id"],))
            conn.execute("DELETE FROM challenges WHERE id=?", (node_id,))

        elif node_type == "theory_page":
            row = conn.execute("SELECT page_id FROM theory_pages WHERE id=?",
                               (node_id,)).fetchone()
            if row:
                conn.execute("DELETE FROM theory_sections WHERE page_id=?", (row["page_id"],))
            conn.execute("DELETE FROM theory_pages WHERE id=?", (node_id,))

        else:
            table = ENTITY[node_type]["table"]
            conn.execute(f"DELETE FROM {table} WHERE id=?", (node_id,))

        conn.commit()
    finally:
        conn.close()


# ─── Lasīšana / saglabāšana ─────────────────────────────────────────────────
def load_record(node_type, node_id):
    table = ENTITY[node_type]["table"]
    conn = db()
    try:
        return conn.execute(f"SELECT * FROM {table} WHERE id=?", (node_id,)).fetchone()
    finally:
        conn.close()


def save_record(node_type, node_id, values):
    table  = ENTITY[node_type]["table"]
    fields = ENTITY[node_type]["fields"]

    cleaned = {}
    for fld in fields:
        col, _, widget = fld[0], fld[1], fld[2]
        if widget == "readonly":
            continue  # nesaglabā readonly laukus
        v = values.get(col, "")
        s = str(v).strip()
        if col in INT_COLS:
            cleaned[col] = int(s) if s else None
        elif col in FLOAT_COLS:
            cleaned[col] = float(s) if s else None
        else:
            cleaned[col] = v if v != "" else None

    if not cleaned:
        return

    set_clause = ", ".join(f"{c}=?" for c in cleaned)
    params     = list(cleaned.values()) + [node_id]
    conn = db()
    try:
        conn.execute(f"UPDATE {table} SET {set_clause} WHERE id=?", params)
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# Galvenais logs
# ═══════════════════════════════════════════════════════════════════════════
class AdminApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TestDB — Administratora rīks")
        self.geometry("1150x720")
        self.minsize(900, 500)

        self.current_type = None
        self.current_id   = None
        self.field_widgets = {}

        self._build_toolbar()
        self._build_body()
        self._build_status()

        self.refresh_tree()

    # ─── UI uzbūve ───────────────────────────────────────────────────────
    def _build_toolbar(self):
        bar = tk.Frame(self, padx=6, pady=6)
        bar.pack(fill="x")

        tk.Button(bar, text="+ Pievienot bērnu", width=18,
                  command=self.on_add).pack(side="left", padx=2)
        tk.Button(bar, text="Dzēst", width=10,
                  command=self.on_delete).pack(side="left", padx=2)
        tk.Button(bar, text="Saglabāt izmaiņas", width=18,
                  command=self.on_save).pack(side="left", padx=2)
        tk.Button(bar, text="Pārlādēt no DB", width=14,
                  command=self.refresh_tree).pack(side="left", padx=2)

        tk.Label(bar, text=f"  DB:  {DB_PATH}",
                 anchor="w", fg="gray").pack(side="left", padx=10)

    def _build_body(self):
        paned = tk.PanedWindow(self, orient="horizontal", sashrelief="raised", sashwidth=4)
        paned.pack(fill="both", expand=True, padx=6, pady=2)

        # Koka rāmis
        tree_frame = tk.Frame(paned)
        self.tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
        ysb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        paned.add(tree_frame, minsize=320, width=440)

        # Formas konteineris
        self.form_outer = tk.Frame(paned)
        paned.add(self.form_outer, minsize=400)

        self._build_empty_form()

    def _build_empty_form(self):
        for w in self.form_outer.winfo_children():
            w.destroy()
        tk.Label(self.form_outer,
                 text="Izvēlies elementu kreisajā kokā, lai to rediģētu.\n\n"
                      "Pievienot jaunu sadaļu: izvēlies tukšu vietu un spied “+ Pievienot bērnu”.",
                 fg="gray", justify="left", padx=20, pady=20).pack(anchor="nw")

    def _build_status(self):
        self.status = tk.Label(self, text="Gatavs.", anchor="w",
                               bd=1, relief="sunken", padx=6, pady=2)
        self.status.pack(fill="x", side="bottom")

    def set_status(self, msg):
        self.status.config(text=msg)

    # ─── Iid utilītas ────────────────────────────────────────────────────
    @staticmethod
    def parse_iid(iid):
        if not iid:
            return (None, None)
        t, i = iid.split(":", 1)
        return (t, int(i))

    # ─── Koka pārzīmēšana ───────────────────────────────────────────────
    def refresh_tree(self):
        # saglabā stāvokli
        sel = self.tree.selection()
        sel_iid = sel[0] if sel else None
        expanded = set()

        def collect(node):
            for c in self.tree.get_children(node):
                if self.tree.item(c, "open"):
                    expanded.add(c)
                collect(c)
        collect("")

        # pārzīmē
        self.tree.delete(*self.tree.get_children())
        try:
            self._populate("", None, None)
        except Exception as e:
            messagebox.showerror("Kļūda", f"Neizdevās ielādēt datubāzi:\n{e}")
            return

        # atjauno
        def restore(node):
            for c in self.tree.get_children(node):
                if c in expanded:
                    self.tree.item(c, open=True)
                restore(c)
        restore("")

        if sel_iid and self.tree.exists(sel_iid):
            self.tree.selection_set(sel_iid)
            self.tree.focus(sel_iid)
            self.tree.see(sel_iid)
        else:
            self._build_empty_form()
            self.current_type = None
            self.current_id   = None

        self.set_status("Pārlādēts no datubāzes.")

    def _populate(self, parent_iid, node_type, node_id):
        for ct, cid, label in get_children(node_type, node_id):
            iid = f"{ct}:{cid}"
            self.tree.insert(parent_iid, "end", iid=iid, text=label)
            self._populate(iid, ct, cid)

    # ─── Atlase un formas attēlošana ────────────────────────────────────
    def on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            self._build_empty_form()
            self.current_type = None
            self.current_id   = None
            return
        t, i = self.parse_iid(sel[0])
        self.show_form(t, i)

    def show_form(self, node_type, node_id):
        for w in self.form_outer.winfo_children():
            w.destroy()
        self.field_widgets = {}
        self.current_type  = node_type
        self.current_id    = node_id

        spec = ENTITY[node_type]
        rec = load_record(node_type, node_id)
        if rec is None:
            tk.Label(self.form_outer, text="Ieraksts nav atrasts.").pack()
            return

        # Galvene
        hdr = tk.Frame(self.form_outer, padx=12, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text=spec["label"], font=("Arial", 14, "bold")).pack(anchor="w")
        tk.Label(hdr, text=f"id = {node_id}    tabula = {spec['table']}",
                 fg="gray").pack(anchor="w")

        ttk.Separator(self.form_outer, orient="horizontal").pack(fill="x", padx=12)

        # Ritināms ķermenis (lai garas formas neizjauc logu)
        body_outer = tk.Frame(self.form_outer)
        body_outer.pack(fill="both", expand=True, padx=12, pady=8)

        canvas = tk.Canvas(body_outer, highlightthickness=0)
        vsb = ttk.Scrollbar(body_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        body = tk.Frame(canvas)
        body_id = canvas.create_window((0, 0), window=body, anchor="nw")

        def _on_body_configure(_e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        body.bind("<Configure>", _on_body_configure)

        def _on_canvas_configure(e):
            canvas.itemconfig(body_id, width=e.width)
        canvas.bind("<Configure>", _on_canvas_configure)

        # Lauki
        for fld in spec["fields"]:
            col, label, widget = fld[0], fld[1], fld[2]
            opts = fld[3] if len(fld) > 3 else None

            tk.Label(body, text=label, anchor="w").pack(fill="x", pady=(8, 2))
            val = rec[col] if col in rec.keys() else ""
            val = "" if val is None else str(val)

            if widget == "entry":
                w = tk.Entry(body)
                w.insert(0, val)
                w.pack(fill="x")

            elif widget == "readonly":
                w = tk.Entry(body)
                w.insert(0, val)
                w.config(state="readonly")
                w.pack(fill="x")

            elif widget == "combo":
                w = ttk.Combobox(body, values=opts, state="readonly")
                w.set(val)
                w.pack(fill="x")

            elif widget == "text":
                fr = tk.Frame(body)
                fr.pack(fill="both", expand=False)
                # garums atkarīgs no satura
                height = 8 if len(val) > 80 or "\n" in val else 4
                w = tk.Text(fr, height=height, wrap="word", undo=True)
                sb = ttk.Scrollbar(fr, orient="vertical", command=w.yview)
                w.configure(yscrollcommand=sb.set)
                w.pack(side="left", fill="both", expand=True)
                sb.pack(side="right", fill="y")
                w.insert("1.0", val)
            else:
                w = tk.Entry(body)
                w.insert(0, val)
                w.pack(fill="x")

            self.field_widgets[col] = (widget, w)

    def collect_form(self):
        out = {}
        for col, (wtype, w) in self.field_widgets.items():
            if wtype == "text":
                out[col] = w.get("1.0", "end-1c")
            elif wtype == "readonly":
                continue
            else:
                out[col] = w.get()
        return out

    # ─── Darbības ───────────────────────────────────────────────────────
    def on_save(self):
        if self.current_type is None:
            self.set_status("Nav izvēlēts neviens ieraksts.")
            return
        try:
            values = self.collect_form()
            save_record(self.current_type, self.current_id, values)
            self.set_status(f"Saglabāts: {ENTITY[self.current_type]['label']} (id={self.current_id})")
            self.refresh_tree()
        except ValueError as e:
            messagebox.showerror("Nederīga vērtība",
                                 f"Skaitliska lauka vērtība nav korekta.\n\n{e}")
        except Exception as e:
            messagebox.showerror("Kļūda saglabājot", str(e))

    def on_add(self):
        sel = self.tree.selection()
        if sel:
            t, i = self.parse_iid(sel[0])
        else:
            t, i = None, None

        opts = addable_children(t, i)
        if not opts:
            messagebox.showinfo(
                "Nav iespējams",
                "Šim ierakstam nevar pievienot bērnu.\n\n"
                "Padoms: izvēlies cita tipa ierakstu (piem. nodaļu, lai pievienotu lapu)."
            )
            return

        if len(opts) == 1:
            chosen = opts[0]
        else:
            chosen = ChooseTypeDialog(self, opts).result
            if not chosen:
                return

        try:
            new_id = insert_child(t, i, chosen)
            if new_id is None:
                messagebox.showerror("Kļūda", "Nevarēja izveidot ierakstu.")
                return
            self.refresh_tree()
            new_iid = f"{chosen}:{new_id}"
            if self.tree.exists(new_iid):
                # atver visus vecākus
                p = self.tree.parent(new_iid)
                while p:
                    self.tree.item(p, open=True)
                    p = self.tree.parent(p)
                self.tree.selection_set(new_iid)
                self.tree.focus(new_iid)
                self.tree.see(new_iid)
            self.set_status(f"Pievienots: {ENTITY[chosen]['label']} (id={new_id})")
        except Exception as e:
            messagebox.showerror("Kļūda pievienojot", str(e))

    def on_delete(self):
        sel = self.tree.selection()
        if not sel:
            self.set_status("Nav izvēlēts neviens ieraksts.")
            return
        t, i = self.parse_iid(sel[0])
        label = ENTITY[t]["label"]
        if not messagebox.askyesno(
            "Apstiprini dzēšanu",
            f"Vai tiešām dzēst:\n\n  {label} (id={i})\n\n"
            "un VISUS tā bērnus (kaskādes dzēšana)?\n\n"
            "Šo darbību nevar atcelt."
        ):
            return
        try:
            delete_node(t, i)
            self.refresh_tree()
            self._build_empty_form()
            self.current_type = None
            self.current_id   = None
            self.set_status(f"Dzēsts: {label} (id={i})")
        except Exception as e:
            messagebox.showerror("Kļūda dzēšot", str(e))


# ─── Tipa izvēles dialogs ───────────────────────────────────────────────
class ChooseTypeDialog(tk.Toplevel):
    def __init__(self, master, options):
        super().__init__(master)
        self.title("Izvēlies bērna tipu")
        self.resizable(False, False)
        self.result = None

        tk.Label(self, text="Kādu bērnu pievienot?",
                 padx=20, pady=10).pack(anchor="w")
        self.var = tk.StringVar(value=options[0])
        for o in options:
            tk.Radiobutton(self, text=ENTITY[o]["label"], variable=self.var,
                           value=o).pack(anchor="w", padx=20)

        bf = tk.Frame(self); bf.pack(pady=12)
        tk.Button(bf, text="OK", width=10, command=self._ok).pack(side="left", padx=5)
        tk.Button(bf, text="Atcelt", width=10, command=self._cancel).pack(side="left", padx=5)

        self.transient(master)
        self.grab_set()
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self._cancel())
        self.wait_window(self)

    def _ok(self):
        self.result = self.var.get()
        self.destroy()

    def _cancel(self):
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    AdminApp().mainloop()