import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import sys
from io import StringIO
import time
import traceback
import threading
import sqlite3
import json
import os

#Datubāzes ceļš
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "TestDB.db")


def db_connect():
    #Atgriež savienojumu ar datubāzi (row_factory = sqlite3.Row)
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(
            f"Datubāze '{DB_PATH}' nav atrasta!\n"

        )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ieladet_navigacijas_struktura():
    #Ielādē navigācijas struktūru no datubāzes.
    #Atgriež: {section_name: {chapter_name: [lapa_num, ...]}, ...}
    conn = db_connect()
    # Katram līmenim izmanto atsevišķu kursoru,
    # lai ligzdotie fetchall() nepārrakstītu viens otru.
    c_sec  = conn.cursor()
    c_chap = conn.cursor()
    c_page = conn.cursor()

    struktūra = {}
    for sec in c_sec.execute("SELECT id, nosaukums FROM sections ORDER BY id").fetchall():
        nodaļas = {}
        for chap in c_chap.execute(
                "SELECT id, nosaukums FROM chapters WHERE section_id=? ORDER BY id",
                (sec["id"],)).fetchall():
            lapas = [
                r["lapa_num"]
                for r in c_page.execute(
                    "SELECT lapa_num FROM pages WHERE chapter_id=? ORDER BY lapa_num",
                    (chap["id"],)).fetchall()
            ]
            nodaļas[chap["nosaukums"]] = lapas
        struktūra[sec["nosaukums"]] = nodaļas
    conn.close()
    return struktūra


def lapa_id(section, chapter, lapa_num):
    #Atgriež pages.id pēc sekcijas, nodaļas un lapas numura.
    conn = db_connect()
    c = conn.cursor()
    row = c.execute("""
        SELECT p.id FROM pages p
        JOIN chapters ch ON ch.id = p.chapter_id
        JOIN sections s  ON s.id  = ch.section_id
        WHERE s.nosaukums=? AND ch.nosaukums=? AND p.lapa_num=?
    """, (section, chapter, int(lapa_num))).fetchone()
    conn.close()
    return row["id"] if row else None


def ieladet_challenge(section, chapter, lapa):
    #Ielādē kodēšanas uzdevumu no datubāzes. Atgriež dict vai None.
    pid = lapa_id(section, chapter, lapa)
    if pid is None:
        return None
    conn = db_connect()
    c = conn.cursor()
    ch = c.execute("SELECT * FROM challenges WHERE page_id=?", (pid,)).fetchone()
    if ch is None:
        conn.close()
        return None
    testi = c.execute(
        "SELECT * FROM challenge_testi WHERE page_id=? ORDER BY id",
        (pid,)).fetchall()
    conn.close()

    test_cases = []
    for t in testi:
        inp = json.loads(t["ievaddati_json"]) if t["ievaddati_json"] else None
        test_cases.append({
            "input": inp,
            "expected_output": t["sagaidita_izvade"],
            "description": t["apraksts"] or "",
        })
    return {
        "title": ch["virsraksts"],
        "description": ch["apraksts"],
        "starter_code": ch["starter_code"],
        "max_time": ch["max_laiks"],
        "test_cases": test_cases,
    }


def ieladet_theory(section, chapter, lapa):
    #Ielādē teorijas lapu no datubāzes. Atgriež dict vai None.
    pid = lapa_id(section, chapter, lapa)
    if pid is None:
        return None
    conn = db_connect()
    c = conn.cursor()
    tp = c.execute("SELECT * FROM theory_pages WHERE page_id=?", (pid,)).fetchone()
    if tp is None:
        conn.close()
        return None
    sekcijas = c.execute(
        "SELECT * FROM theory_sections WHERE page_id=? ORDER BY id",
        (pid,)).fetchall()
    conn.close()
    return {
        "title": tp["virsraksts"],
        "sections": [{"type": s["tips"], "content": s["saturs"]} for s in sekcijas],
    }


def ieladet_test(section, chapter, lapa):
    #Ielādē pārbaudes darbu no datubāzes. Atgriež dict vai None.
    pid = lapa_id(section, chapter, lapa)
    if pid is None:
        return None
    conn = db_connect()
    c = conn.cursor()
    t = c.execute("SELECT * FROM tests WHERE page_id=?", (pid,)).fetchone()
    if t is None:
        conn.close()
        return None
    jautajumi_rows = c.execute(
        "SELECT * FROM test_jautajumi WHERE test_id=? ORDER BY id",
        (pid,)).fetchall()

    jautajumi = []
    for j in jautajumi_rows:
        if j["tips"] == "multiple_choice":
            opcijas = [
                o["teksts"]
                for o in c.execute(
                    "SELECT teksts FROM mc_opcijas WHERE jautajums_id=? ORDER BY id",
                    (j["id"],))
            ]
            jautajumi.append({
                "type": "multiple_choice",
                "question": j["jautajums"],
                "options": opcijas,
                "correct_answer": j["pareiza_atbilde"],
                "points": j["punkti"],
            })
        elif j["tips"] == "coding":
            tc_rows = c.execute(
                "SELECT * FROM test_jaut_testi WHERE jautajums_id=? ORDER BY id",
                (j["id"],)).fetchall()
            test_cases = []
            for tc in tc_rows:
                inp = json.loads(tc["ievaddati_json"]) if tc["ievaddati_json"] else None
                test_cases.append({
                    "input": inp,
                    "expected_output": tc["sagaidita_izvade"],
                    "description": tc["apraksts"] or "",
                })
            jautajumi.append({
                "type": "coding",
                "question": j["jautajums"],
                "starter_code": j["starter_code"] or "# Raksti kodu šeit\n",
                "max_time": j["max_laiks"] or 1.0,
                "points": j["punkti"],
                "test_cases": test_cases,
            })

    conn.close()
    return {
        "title": t["virsraksts"],
        "description": t["apraksts"],
        "passing_score": t["nokartosanas_sl"],
        "questions": jautajumi,
    }

class TimeoutException(Exception):
    #Izņēmums, kas tiek izsaukts, kad koda izpilde pārsniedz laika ierobežojumu
    pass

def run_with_timeout(func, args=(), kwargs={}, timeout_duration=5):
    #Izpildīt funkciju ar laika ierobežojumu - darbojas visās operētājsistēmās
    result = {'completed': False, 'exception': None, 'value': None}
    
    def target():
        try:
            result['value'] = func(*args, **kwargs)
            result['completed'] = True
        except Exception as e:
            result['exception'] = e
    
    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
    thread.join(timeout_duration)
    
    if thread.is_alive():
        raise TimeoutException(f"Koda izpilde pārsniedza {timeout_duration} sekunžu limitu!")
    
    if result['exception']:
        raise result['exception']
    
    return result['completed']

class PageNavigator:
    def __init__(self, root):
        self.root = root
        self.root.title("Programmēšanas Mācību Platforma")
        self.root.geometry("1200x700")
        
        # Drošības iestatījumi
        self.blocked_imports = {
            'os', 'sys', 'subprocess', 'shutil', 'socket', 'urllib',
            'requests', 'pickle', 'shelve', 'importlib', '__import__',
            'eval', 'exec', 'compile', 'open', 'file', 'input',
            'multiprocessing', 'threading', 'ctypes', 'pty', 'commands'
        }
        
        self.blocked_builtins = {
            '__import__', 'eval', 'exec', 'compile', 'open', 
            'input', 'execfile', 'reload', 'file'
        }
        
        self.max_execution_time = 5
        
        # Izveidot galvenos rāmjus
        self.sidebar_frame = tk.Frame(root, width=220, bg='lightgray')
        self.sidebar_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        self.sidebar_frame.pack_propagate(False)
        
        self.content_frame = tk.Frame(root, bg='white')
        self.content_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        #Ielādē navigācijas struktūru no datubāzes
        try:
            self.navigation_structure = ieladet_navigacijas_struktura()
        except FileNotFoundError as e:
            messagebox.showerror("Datubāzes kļūda", str(e))
            root.destroy()
            return

        # Challenges, theory_pages un theory_tests tiek ielādēti dinamiski
        # katru reizi, kad tiek atvērta konkrēta lapa (sk. show_page metodi).
        # Tas nozīmē, ka izmaiņas DB Browser tiek redzamas pēc lapas pārlādēšanas.
        
        # Izsekot testu mēģinājumiem
        self.current_test_answers = {}
        self.test_submitted = False
        
        self.current_page = None
        self.setup_sidebar()
        self.show_welcome_page()
    
    def setup_sidebar(self):
        title_label = tk.Label(self.sidebar_frame, text="Navigācija",
                              bg='lightgray', font=('Arial', 14, 'bold'))
        title_label.pack(pady=(10, 2))

        refresh_btn = tk.Button(self.sidebar_frame, text="Atsvaidzināt",
                                bg='#5c85d6', fg='white', font=('Arial', 9),
                                relief=tk.FLAT, padx=6, pady=2,
                                command=self.refresh_sidebar)
        refresh_btn.pack(pady=(0, 6))

        self.tree = ttk.Treeview(self.sidebar_frame, show='tree')
        self.tree.pack(fill=tk.BOTH, expand=True, padx=5)

        self.tree.tag_configure('section', font=('Arial', 10, 'bold'))
        self.tree.bind('<<TreeviewSelect>>', self.on_item_selected)

        self._fill_sidebar_tree()

    def _fill_sidebar_tree(self):
        #Nodzēš esošos koka elementus un no jauna aizpilda no datubāzes.
        # Saglabāt atvērtās sekcijas
        expanded = set()
        for i in self.tree.get_children():
            if self.tree.item(i, 'open'):
                expanded.add(self.tree.item(i, 'text').strip(' ').strip())

        for item in self.tree.get_children():
            self.tree.delete(item)

        # Ielādēt struktūru tieši no DB (ne no kešota self.navigation_structure)
        self.navigation_structure = ieladet_navigacijas_struktura()

        for section, chapters in self.navigation_structure.items():
            section_id = self.tree.insert("", "end", text=f" {section}",
                                          values=[section], tags=('section',))
            if section in expanded:
                self.tree.item(section_id, open=True)

            for chapter, pages in chapters.items():
                chapter_id = self.tree.insert(section_id, "end",
                                              text=f"  {chapter}",
                                              values=[f"{section}|{chapter}"])
                for page in pages:
                    self.tree.insert(chapter_id, "end",
                                     text=f"    Lapa {page}",
                                     values=[f"{section}|{chapter}|{page}"])

    def refresh_sidebar(self):
        #Atsvaidzina navigācijas koku no datubāzes.
        self._fill_sidebar_tree()
    
    def on_item_selected(self, event):
        selected = self.tree.selection()
        if selected:
            item = self.tree.item(selected[0])
            values = item['values']
            if values and '|' in str(values[0]):
                parts = str(values[0]).split('|')
                if len(parts) == 3:
                    section, chapter, page = parts
                    self.show_page(section, chapter, page)
    
    def clear_content(self):
        for widget in self.content_frame.winfo_children():
            widget.destroy()
    
    def show_welcome_page(self):
        self.clear_content()
        self.current_page = None
        
        welcome_label = tk.Label(self.content_frame, 
                                text="Laipni Lūdzam Programmēšanas Mācību Platformā!", 
                                font=('Arial', 18, 'bold'), bg='white')
        welcome_label.pack(pady=50)
        
        desc_label = tk.Label(self.content_frame, 
                             text="Izvēlies sadaļu no navigācijas:\n\n"
                                  "Kodēšanas Uzdevumi - Praktizē savas programmēšanas prasmes\n"
                                  "Teorija - Apgūsti programmēšanas konceptus\n"
                                  "Pārbaudes Darbi - Pārbaudi savas zināšanas",
                             font=('Arial', 12), bg='white', justify=tk.LEFT)
        desc_label.pack(pady=20)
    
    def show_page(self, section, chapter, page):
        self.current_page = (section, chapter, page)
        
        if section == "Kodēšanas Uzdevumi":
            self.show_coding_challenge(section, chapter, page)
        elif section == "Teorija":
            self.show_theory_page(section, chapter, page)
        elif section == "Pārbaudes Darbi":
            self.show_theory_test(section, chapter, page)
    
    # Teorijas lapas
    def show_theory_page(self, section, chapter, page):
        self.clear_content()
        
        theory = ieladet_theory(section, chapter, page)
        if theory is None:
            self.show_placeholder_page(section, chapter, page, "Teorija")
            return
        
        # Izveidot ritināmu audeklu
        canvas = tk.Canvas(self.content_frame, bg='white')
        scrollbar = ttk.Scrollbar(self.content_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='white')
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Virsraksts
        title_label = tk.Label(scrollable_frame, text=theory['title'], 
                              font=('Arial', 20, 'bold'), bg='white')
        title_label.pack(pady=(20, 10), padx=30, anchor='w')
        
        # Nodaļas info
        info_label = tk.Label(scrollable_frame, text=f"{chapter} - Lapa {page}", 
                             font=('Arial', 10), bg='white', fg='gray')
        info_label.pack(padx=30, anchor='w', pady=(0, 20))
        
        # Renderēt sekcijas
        for section_data in theory['sections']:
            if section_data['type'] == 'heading':
                heading = tk.Label(scrollable_frame, text=section_data['content'],
                                  font=('Arial', 14, 'bold'), bg='white')
                heading.pack(pady=(15, 5), padx=30, anchor='w')
            
            elif section_data['type'] == 'text':
                text = tk.Label(scrollable_frame, text=section_data['content'],
                               font=('Arial', 11), bg='white', justify=tk.LEFT,
                               wraplength=900, anchor='w')
                text.pack(pady=5, padx=30, anchor='w')
            
            elif section_data['type'] == 'code':
                code_frame = tk.Frame(scrollable_frame, bg='#2d2d2d', relief=tk.RAISED, bd=2)
                code_frame.pack(pady=10, padx=30, fill=tk.X)
                
                code_text = tk.Text(code_frame, font=('Courier', 11), bg='#2d2d2d',
                                   fg='#f8f8f2', wrap=tk.NONE, height=section_data['content'].count('\n') + 2,
                                   relief=tk.FLAT, padx=15, pady=10)
                code_text.insert('1.0', section_data['content'])
                code_text.config(state='disabled')
                code_text.pack(fill=tk.X)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        self.add_navigation_buttons()
    
    #Kodēšanas uzdevumi
    def show_coding_challenge(self, section, chapter, page):
        self.clear_content()
        
        challenge = ieladet_challenge(section, chapter, page)
        if challenge is None:
            self.show_placeholder_page(section, chapter, page, "Kodēšanas Uzdevums")
            return
        
        main_container = tk.Frame(self.content_frame, bg='white')
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        left_frame = tk.Frame(main_container, bg='white', width=400)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 10))
        left_frame.pack_propagate(False)
        
        right_frame = tk.Frame(main_container, bg='white')
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Uzdevuma apraksts
        title_label = tk.Label(left_frame, text=challenge['title'], 
                              font=('Arial', 16, 'bold'), bg='white')
        title_label.pack(pady=(10, 5), anchor='w')
        
        info_label = tk.Label(left_frame, text=f"{chapter} - Lapa {page}", 
                             font=('Arial', 10), bg='white', fg='gray')
        info_label.pack(anchor='w', pady=(0, 15))
        
        desc_label = tk.Label(left_frame, text="Uzdevums:", 
                             font=('Arial', 12, 'bold'), bg='white')
        desc_label.pack(anchor='w', pady=(0, 5))
        
        desc_text = tk.Label(left_frame, text=challenge['description'], 
                            font=('Arial', 11), bg='white', justify=tk.LEFT,
                            wraplength=380)
        desc_text.pack(anchor='w', pady=(0, 15))
        
        # Parādīt testu gadījumu skaitu
        test_count_label = tk.Label(left_frame, 
                                   text=f"Testu gadījumi: {len(challenge['test_cases'])}", 
                                   font=('Arial', 11, 'bold'), bg='white', fg='blue')
        test_count_label.pack(anchor='w', pady=(0, 10))
        
        # Piemēra izvade (parāda tikai pirmo testu)
        if challenge['test_cases']:
            first_test = challenge['test_cases'][0]
            expected_label = tk.Label(left_frame, text="Piemēra Izvade:", 
                                     font=('Arial', 12, 'bold'), bg='white')
            expected_label.pack(anchor='w', pady=(0, 5))
            
            if first_test['input']:
                input_str = ", ".join([f"{k}={v}" for k, v in first_test['input'].items()])
                input_label = tk.Label(left_frame, text=f"Ievaddati: {input_str}", 
                                      font=('Arial', 10), bg='white', fg='gray')
                input_label.pack(anchor='w', padx=10)
            
            expected_frame = tk.Frame(left_frame, bg='#f0f0f0', relief=tk.SUNKEN, bd=1)
            expected_frame.pack(fill=tk.X, pady=(5, 15))
            
            expected_text = tk.Label(expected_frame, text=first_test['expected_output'], 
                                    font=('Courier', 10), bg='#f0f0f0', justify=tk.LEFT,
                                    anchor='w')
            expected_text.pack(padx=10, pady=10, anchor='w')
        
        # Koda redaktors
        editor_label = tk.Label(right_frame, text="Tavs Kods:", 
                               font=('Arial', 12, 'bold'), bg='white')
        editor_label.pack(anchor='w', pady=(0, 5))
        
        self.code_editor = scrolledtext.ScrolledText(right_frame, 
                                                     font=('Courier', 11),
                                                     wrap=tk.WORD,
                                                     height=15,
                                                     bg='#1e1e1e',
                                                     fg='#d4d4d4',
                                                     insertbackground='white')
        self.code_editor.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        self.code_editor.insert('1.0', challenge['starter_code'])
        
        # Pogas
        control_frame = tk.Frame(right_frame, bg='white')
        control_frame.pack(fill=tk.X, pady=(0, 10))
        
        run_btn = tk.Button(control_frame, text="Palaist Kodu", 
                           command=lambda: self.run_code(challenge),
                           bg='#4CAF50', fg='white', font=('Arial', 11, 'bold'),
                           padx=20, pady=8)
        run_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        clear_btn = tk.Button(control_frame, text="Notīrīt Izvadi", 
                             command=self.clear_output,
                             bg='#ff9800', fg='white', font=('Arial', 11),
                             padx=15, pady=8)
        clear_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        reset_btn = tk.Button(control_frame, text="Atiestatīt Kodu", 
                             command=lambda: self.reset_code(challenge),
                             bg='#f44336', fg='white', font=('Arial', 11),
                             padx=15, pady=8)
        reset_btn.pack(side=tk.LEFT)
        
        # Izvade
        output_label = tk.Label(right_frame, text="Izvade:", 
                               font=('Arial', 12, 'bold'), bg='white')
        output_label.pack(anchor='w', pady=(0, 5))
        
        self.output_text = scrolledtext.ScrolledText(right_frame, 
                                                     font=('Courier', 10),
                                                     wrap=tk.WORD,
                                                     height=8,
                                                     bg='#f5f5f5',
                                                     state='disabled')
        self.output_text.pack(fill=tk.BOTH, expand=True)
        
        self.add_navigation_buttons()
    
    #Pārbaudes darbs
    def show_theory_test(self, section, chapter, page):
        self.clear_content()
        
        test_key = (section, chapter, page)
        test = ieladet_test(section, chapter, page)
        if test is None:
            self.show_placeholder_page(section, chapter, page, "Pārbaudes Darbs")
            return
        
        # Atiestatīt testa stāvokli
        if test_key not in self.current_test_answers:
            self.current_test_answers[test_key] = {}
            self.test_submitted = False
        
        # Izveidot ritināmu audeklu
        canvas = tk.Canvas(self.content_frame, bg='white')
        scrollbar = ttk.Scrollbar(self.content_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='white')
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Testa galvene
        title_label = tk.Label(scrollable_frame, text=test['title'], 
                              font=('Arial', 18, 'bold'), bg='white')
        title_label.pack(pady=(20, 5), padx=30, anchor='w')
        
        desc_label = tk.Label(scrollable_frame, text=test['description'], 
                             font=('Arial', 11), bg='white', fg='gray')
        desc_label.pack(padx=30, anchor='w', pady=(0, 5))
        
        total_points = sum(q['points'] for q in test['questions'])
        points_label = tk.Label(scrollable_frame, 
                               text=f"Kopējie Punkti: {total_points} | Nokārtošanas Slieksnis: {test['passing_score']}%", 
                               font=('Arial', 10, 'bold'), bg='white', fg='blue')
        points_label.pack(padx=30, anchor='w', pady=(0, 20))
        
        # Renderēt jautājumus
        for i, question in enumerate(test['questions']):
            q_num = i + 1
            
            # Jautājuma konteiners
            q_frame = tk.Frame(scrollable_frame, bg='#f9f9f9', relief=tk.RAISED, bd=2)
            q_frame.pack(fill=tk.X, padx=30, pady=10)
            
            # Jautājuma galvene
            q_header = tk.Label(q_frame, 
                               text=f"Jautājums {q_num} ({question['points']} punkti)", 
                               font=('Arial', 12, 'bold'), bg='#f9f9f9')
            q_header.pack(anchor='w', padx=15, pady=(10, 5))
            
            if question['type'] == 'multiple_choice':
                # Jautājuma teksts
                q_text = tk.Label(q_frame, text=question['question'],
                                 font=('Arial', 11), bg='#f9f9f9', justify=tk.LEFT,
                                 wraplength=900)
                q_text.pack(anchor='w', padx=15, pady=5)
                
                # Varianti
                var = tk.IntVar(value=-1)
                if test_key in self.current_test_answers and q_num in self.current_test_answers[test_key]:
                    var.set(self.current_test_answers[test_key][q_num])
                
                for j, option in enumerate(question['options']):
                    rb = tk.Radiobutton(q_frame, text=option, variable=var, value=j,
                                       font=('Arial', 10), bg='#f9f9f9',
                                       command=lambda v=var, n=q_num, k=test_key: self.save_mc_answer(k, n, v.get()))
                    rb.pack(anchor='w', padx=30, pady=2)
                
                # Parādīt rezultātu, ja iesniegts
                if self.test_submitted:
                    user_answer = self.current_test_answers[test_key].get(q_num, -1)
                    correct = question['correct_answer']
                    
                    if user_answer == correct:
                        result_label = tk.Label(q_frame, text="Pareizi!", 
                                               font=('Arial', 10, 'bold'), 
                                               bg='#f9f9f9', fg='green')
                    else:
                        result_label = tk.Label(q_frame, 
                                               text=f"Nepareizi! Pareizā atbilde: {question['options'][correct]}", 
                                               font=('Arial', 10, 'bold'), 
                                               bg='#f9f9f9', fg='red')
                    result_label.pack(anchor='w', padx=15, pady=(5, 10))
            
            elif question['type'] == 'coding':
                # Jautājuma teksts
                q_text = tk.Label(q_frame, text=question['question'],
                                 font=('Arial', 11), bg='#f9f9f9', justify=tk.LEFT,
                                 wraplength=900)
                q_text.pack(anchor='w', padx=15, pady=5)
                
                # Testu gadījumu skaits
                test_count = len(question.get('test_cases', []))
                if test_count > 0:
                    test_info = tk.Label(q_frame, 
                                       text=f"Šis jautājums tiks pārbaudīts ar {test_count} testu gadījumiem", 
                                       font=('Arial', 9), bg='#f9f9f9', fg='blue')
                    test_info.pack(anchor='w', padx=15, pady=3)
                
                # Koda redaktors
                code_editor = scrolledtext.ScrolledText(q_frame, 
                                                        font=('Courier', 10),
                                                        height=8,
                                                        bg='#1e1e1e',
                                                        fg='#d4d4d4',
                                                        insertbackground='white')
                code_editor.pack(fill=tk.X, padx=15, pady=10)
                
                # Ielādēt saglabāto kodu vai sākuma kodu
                if test_key in self.current_test_answers and q_num in self.current_test_answers[test_key]:
                    code_editor.insert('1.0', self.current_test_answers[test_key][q_num]['code'])
                else:
                    code_editor.insert('1.0', question['starter_code'])
                
                # Saglabāt kodu pie izmaiņām
                def save_code(event=None, editor=code_editor, key=test_key, num=q_num):
                    if key not in self.current_test_answers:
                        self.current_test_answers[key] = {}
                    self.current_test_answers[key][num] = {
                        'code': editor.get('1.0', tk.END),
                        'type': 'coding'
                    }
                
                code_editor.bind('<KeyRelease>', save_code)
                
                # Parādīt rezultātu, ja iesniegts
                if self.test_submitted:
                    saved_answer = self.current_test_answers[test_key].get(q_num, {})
                    if saved_answer and 'result' in saved_answer:
                        result = saved_answer['result']
                        
                        if result['all_passed']:
                            result_label = tk.Label(q_frame, 
                                                   text=f"Pareizi! Visi {result['passed']}/{result['total']} testi nokārtoti ({result['time']:.4f}s)", 
                                                   font=('Arial', 10, 'bold'), 
                                                   bg='#f9f9f9', fg='green')
                        else:
                            result_label = tk.Label(q_frame, 
                                                   text=f"Nepareizi! Nokārtoti tikai {result['passed']}/{result['total']} testi", 
                                                   font=('Arial', 10, 'bold'), 
                                                   bg='#f9f9f9', fg='red')
                        result_label.pack(anchor='w', padx=15, pady=(5, 5))
                        
                        # Parādīt detalizētus rezultātus
                        if 'details' in result:
                            details_text = "\n".join(result['details'])
                            details_label = tk.Label(q_frame, text=details_text,
                                                   font=('Courier', 9), bg='#f9f9f9', 
                                                   justify=tk.LEFT, fg='gray')
                            details_label.pack(anchor='w', padx=30, pady=(0, 10))
        
        # Iesniegt pogu
        if not self.test_submitted:
            submit_btn = tk.Button(scrollable_frame, text="Iesniegt Testu", 
                                  command=lambda: self.submit_test(test_key, test, scrollable_frame),
                                  bg='#2196F3', fg='white', font=('Arial', 12, 'bold'),
                                  padx=30, pady=10)
            submit_btn.pack(pady=30)
        else:
            # Parādīt galīgos rezultātus
            self.show_test_results(scrollable_frame, test_key, test)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        self.add_navigation_buttons()
    
    def save_mc_answer(self, test_key, q_num, answer):
        if test_key not in self.current_test_answers:
            self.current_test_answers[test_key] = {}
        self.current_test_answers[test_key][q_num] = answer
    
    def submit_test(self, test_key, test, parent_frame):
        # Novērtēt testu
        total_points = 0
        earned_points = 0
        
        for i, question in enumerate(test['questions']):
            q_num = i + 1
            total_points += question['points']
            
            if question['type'] == 'multiple_choice':
                user_answer = self.current_test_answers[test_key].get(q_num, -1)
                if user_answer == question['correct_answer']:
                    earned_points += question['points']
            
            elif question['type'] == 'coding':
                saved_answer = self.current_test_answers[test_key].get(q_num, {})
                if saved_answer and 'code' in saved_answer:
                    code = saved_answer['code']
                    result = self.grade_coding_question(code, question)
                    
                    # Saglabāt rezultātu
                    self.current_test_answers[test_key][q_num]['result'] = result
                    
                    if result['all_passed']:
                        earned_points += question['points']
        
        self.test_submitted = True
        
        # Atsvaidzināt lapu, lai parādītu rezultātus
        section, chapter, page = self.current_page
        self.show_theory_test(section, chapter, page)
    
    def show_test_results(self, parent_frame, test_key, test):
        # Aprēķināt rezultātu
        total_points = sum(q['points'] for q in test['questions'])
        earned_points = 0
        
        for i, question in enumerate(test['questions']):
            q_num = i + 1
            
            if question['type'] == 'multiple_choice':
                user_answer = self.current_test_answers[test_key].get(q_num, -1)
                if user_answer == question['correct_answer']:
                    earned_points += question['points']
            
            elif question['type'] == 'coding':
                saved_answer = self.current_test_answers[test_key].get(q_num, {})
                if saved_answer and 'result' in saved_answer and saved_answer['result']['all_passed']:
                    earned_points += question['points']
        
        percentage = (earned_points / total_points) * 100
        passed = percentage >= test['passing_score']
        
        # Rezultātu kaste
        results_frame = tk.Frame(parent_frame, bg='#e3f2fd', relief=tk.RAISED, bd=3)
        results_frame.pack(fill=tk.X, padx=30, pady=20)
        
        results_title = tk.Label(results_frame, text="Testa Rezultāti", 
                                font=('Arial', 16, 'bold'), bg='#e3f2fd')
        results_title.pack(pady=10)
        
        score_label = tk.Label(results_frame, 
                              text=f"Rezultāts: {earned_points}/{total_points} ({percentage:.1f}%)", 
                              font=('Arial', 14), bg='#e3f2fd')
        score_label.pack(pady=5)
        
        if passed:
            status_label = tk.Label(results_frame, text="NOKĀRTOTS!", 
                                   font=('Arial', 14, 'bold'), bg='#e3f2fd', fg='green')
        else:
            status_label = tk.Label(results_frame, text="NENOKĀRTOTS", 
                                   font=('Arial', 14, 'bold'), bg='#e3f2fd', fg='red')
        status_label.pack(pady=5)
        
        # Atkārtot pogu
        retake_btn = tk.Button(results_frame, text="Atkārtot Testu", 
                              command=lambda: self.retake_test(test_key),
                              bg='#ff9800', fg='white', font=('Arial', 11),
                              padx=20, pady=8)
        retake_btn.pack(pady=10)
    
    def retake_test(self, test_key):
        # Notīrīt testa datus
        if test_key in self.current_test_answers:
            del self.current_test_answers[test_key]
        self.test_submitted = False
        
        # Pārlādēt testu
        section, chapter, page = self.current_page
        self.show_theory_test(section, chapter, page)
    
    def grade_coding_question(self, code, question):
        #Novērtēt kodēšanas jautājumu ar vairākiem testu gadījumiem
        test_cases = question.get('test_cases', [])
        
        if not test_cases:
            # Ja nav testu gadījumu, izmantot veco metodi
            return self.grade_single_test(code, question)
        
        passed_tests = 0
        total_tests = len(test_cases)
        details = []
        total_time = 0
        
        for i, test_case in enumerate(test_cases):
            redirected_output = StringIO()
            old_stdout = sys.stdout
            sys.stdout = redirected_output
            
            try:
                # Drošības pārbaude
                is_safe, security_msg = self.check_code_security(code)
                if not is_safe:
                    sys.stdout = old_stdout
                    return {
                        'all_passed': False,
                        'passed': 0,
                        'total': total_tests,
                        'error': security_msg,
                        'time': 0,
                        'details': [f"Drošības kļūda: {security_msg}"]
                    }
                
                # Izveidot drošu izpildes vidi
                safe_builtins = {
                    'print': print, 'range': range, 'len': len, 'str': str,
                    'int': int, 'float': float, 'bool': bool, 'list': list,
                    'dict': dict, 'tuple': tuple, 'set': set, 'abs': abs,
                    'max': max, 'min': min, 'sum': sum, 'sorted': sorted,
                    'enumerate': enumerate, 'zip': zip
                }
                
                restricted_globals = {
                    '__builtins__': safe_builtins,
                    '__name__': '__main__',
                }
                
                # Pievienot ievaddatus kā mainīgos
                if test_case['input']:
                    restricted_globals.update(test_case['input'])
                
                start_time = time.time()
                
                def execute_code():
                    exec(code, restricted_globals)
                
                run_with_timeout(execute_code, timeout_duration=self.max_execution_time)
                
                execution_time = time.time() - start_time
                total_time += execution_time
                sys.stdout = old_stdout
                
                user_output = redirected_output.getvalue()
                
                if user_output == test_case['expected_output']:
                    passed_tests += 1
                    details.append(f"Tests {i+1}: Nokārtots - {test_case.get('description', '')}")
                else:
                    details.append(f"Tests {i+1}: Nenokārtots - {test_case.get('description', '')}")
                    details.append(f"  Sagaidīts: {repr(test_case['expected_output'])}")
                    details.append(f"  Saņemts: {repr(user_output)}")
            
            except TimeoutException:
                sys.stdout = old_stdout
                details.append(f"Tests {i+1}: Laika limits pārsniegts")
            except Exception as e:
                sys.stdout = old_stdout
                details.append(f"Tests {i+1}: Kļūda - {str(e)}")
        
        return {
            'all_passed': passed_tests == total_tests,
            'passed': passed_tests,
            'total': total_tests,
            'time': total_time / total_tests if total_tests > 0 else 0,
            'details': details
        }
    
    def grade_single_test(self, code, question):
        #Novērtēt ar vienu testu
        redirected_output = StringIO()
        old_stdout = sys.stdout
        sys.stdout = redirected_output
        
        try:
            is_safe, security_msg = self.check_code_security(code)
            if not is_safe:
                sys.stdout = old_stdout
                return {
                    'all_passed': False,
                    'passed': 0,
                    'total': 1,
                    'error': security_msg,
                    'time': 0
                }
            
            safe_builtins = {
                'print': print, 'range': range, 'len': len, 'str': str,
                'int': int, 'float': float, 'bool': bool, 'list': list,
                'dict': dict, 'tuple': tuple, 'set': set, 'abs': abs,
                'max': max, 'min': min, 'sum': sum, 'sorted': sorted,
                'enumerate': enumerate, 'zip': zip
            }
            
            restricted_globals = {
                '__builtins__': safe_builtins,
                '__name__': '__main__',
            }
            
            start_time = time.time()
            
            def execute_code():
                exec(code, restricted_globals)
            
            run_with_timeout(execute_code, timeout_duration=self.max_execution_time)
            
            execution_time = time.time() - start_time
            sys.stdout = old_stdout
            
            user_output = redirected_output.getvalue()
            
            if user_output == question['expected_output']:
                return {
                    'all_passed': True,
                    'passed': 1,
                    'total': 1,
                    'time': execution_time
                }
            else:
                return {
                    'all_passed': False,
                    'passed': 0,
                    'total': 1,
                    'error': f"Izvades neatbilstība",
                    'time': execution_time
                }
        
        except TimeoutException:
            sys.stdout = old_stdout
            return {
                'all_passed': False,
                'passed': 0,
                'total': 1,
                'error': 'Koda izpildes laika limits',
                'time': self.max_execution_time
            }
        except Exception as e:
            sys.stdout = old_stdout
            return {
                'all_passed': False,
                'passed': 0,
                'total': 1,
                'error': str(e),
                'time': 0
            }
    
    #Koda izpilde un drošība
    def check_code_security(self, code):
        #Pārbaudīt, vai kods nesatur bīstamas operācijas
        code_lower = code.lower()
        
        for blocked in self.blocked_imports:
            if f'import {blocked}' in code_lower or f'from {blocked}' in code_lower:
                return False, f"Drošības kļūda: Imports '{blocked}' nav atļauts."
        
        for builtin in self.blocked_builtins:
            if builtin in code:
                return False, f"Drošības kļūda: Funkcija '{builtin}' nav atļauta."
        
        dangerous_patterns = [
            ('open(', 'failu operācijas'),
            ('file(', 'failu operācijas'),
            ('with open', 'failu operācijas'),
            ('__', 'dunder metodes'),
        ]
        
        for pattern, description in dangerous_patterns:
            if pattern in code_lower:
                return False, f"Drošības kļūda: {description} nav atļautas."
        
        if 'while True' in code or 'while 1' in code:
            if 'break' not in code:
                return False, "Brīdinājums: 'while True' bez break var izraisīt bezgalīgu ciklu."
        
        return True, "Kods izturēja drošības pārbaudes"
    
    def run_code(self, challenge):
        #Izpildīt kodu kodēšanas uzdevumiem ar vairākiem testiem
        code = self.code_editor.get('1.0', tk.END)
        
        self.output_text.config(state='normal')
        self.output_text.delete('1.0', tk.END)
        
        is_safe, security_msg = self.check_code_security(code)
        if not is_safe:
            self.output_text.insert('1.0', f"{security_msg}\n\n", 'error')
            self.output_text.insert(tk.END, "Tavs kods netika izpildīts drošības apsvērumu dēļ.", 'error')
            self.output_text.tag_config('error', foreground='red', font=('Courier', 10, 'bold'))
            self.output_text.config(state='disabled')
            return
        
        # Palaist visus testu gadījumus
        test_cases = challenge.get('test_cases', [])
        if not test_cases:
            self.output_text.insert('1.0', "Nav testu gadījumu šim uzdevumam.", 'error')
            self.output_text.config(state='disabled')
            return
        
        passed_tests = 0
        total_tests = len(test_cases)
        total_time = 0
        
        self.output_text.insert('1.0', f"=== Palaiž {total_tests} testus ===\n\n")
        
        for i, test_case in enumerate(test_cases):
            old_stdout = sys.stdout
            redirected_output = StringIO()
            sys.stdout = redirected_output
            
            try:
                safe_builtins = {
                    'print': print, 'range': range, 'len': len, 'str': str,
                    'int': int, 'float': float, 'bool': bool, 'list': list,
                    'dict': dict, 'tuple': tuple, 'set': set, 'abs': abs,
                    'max': max, 'min': min, 'sum': sum, 'sorted': sorted,
                    'enumerate': enumerate, 'zip': zip, 'map': map,
                    'filter': filter, 'all': all, 'any': any, 'round': round,
                    'pow': pow, 'divmod': divmod, 'chr': chr, 'ord': ord,
                    'reversed': reversed
                }
                
                restricted_globals = {
                    '__builtins__': safe_builtins,
                    '__name__': '__main__',
                }
                
                # Pievienot ievaddatus
                if test_case['input']:
                    restricted_globals.update(test_case['input'])
                
                start_time = time.time()
                
                def execute_code():
                    exec(code, restricted_globals)
                
                try:
                    run_with_timeout(execute_code, timeout_duration=self.max_execution_time)
                except TimeoutException:
                    raise TimeoutException(f"Koda izpilde pārsniedza {self.max_execution_time} sekundes!")
                
                execution_time = time.time() - start_time
                total_time += execution_time
                sys.stdout = old_stdout
                
                user_output = redirected_output.getvalue()
                
                # Rezultāta ziņojums
                test_header = f"Tests {i+1}/{total_tests}"
                if test_case.get('description'):
                    test_header += f" - {test_case['description']}"
                
                self.output_text.insert(tk.END, f"─── {test_header} ───\n")
                
                if test_case['input']:
                    input_str = ", ".join([f"{k}={v}" for k, v in test_case['input'].items()])
                    self.output_text.insert(tk.END, f"Ievaddati: {input_str}\n")
                
                self.output_text.insert(tk.END, f"Izvade: {user_output}")
                
                if user_output == test_case['expected_output']:
                    passed_tests += 1
                    self.output_text.insert(tk.END, "NOKĀRTOTS\n\n", 'success')
                else:
                    self.output_text.insert(tk.END, "NENOKĀRTOTS\n", 'error')
                    self.output_text.insert(tk.END, f"Sagaidīts: {test_case['expected_output']}\n", 'error')
                    self.output_text.insert(tk.END, f"Saņemts: {user_output}\n\n", 'error')
                
            except TimeoutException as te:
                sys.stdout = old_stdout
                self.output_text.insert(tk.END, f"Tests {i+1}: LAIKA LIMITS PĀRSNIEGTS\n\n", 'error')
            except Exception as e:
                sys.stdout = old_stdout
                self.output_text.insert(tk.END, f"Tests {i+1}: KĻŪDA - {str(e)}\n\n", 'error')
        
        # Galīgais kopsavilkums
        avg_time = total_time / total_tests if total_tests > 0 else 0
        
        self.output_text.insert(tk.END, "\n=== KOPSAVILKUMS ===\n")
        self.output_text.insert(tk.END, f"Nokārtoti: {passed_tests}/{total_tests} testi\n")
        self.output_text.insert(tk.END, f"Vidējais laiks: {avg_time:.4f} sekundes\n\n")
        
        if passed_tests == total_tests:
            self.output_text.insert(tk.END, "LIELISKI! Visi testi nokārtoti!\n", 'success')
            
            if avg_time <= challenge.get('max_time', 1.0):
                self.output_text.insert(tk.END, f"ĀTRS! Laiks ir limita robežās ({challenge.get('max_time', 1.0)}s)\n", 'success')
            else:
                self.output_text.insert(tk.END, f"LĒNS! Laiks pārsniedz limitu ({challenge.get('max_time', 1.0)}s)\n", 'warning')
                self.output_text.tag_config('warning', foreground='orange', font=('Courier', 10, 'bold'))
        else:
            self.output_text.insert(tk.END, "Daži testi nenokārtoti. Mēģini vēlreiz!\n", 'error')
        
        self.output_text.tag_config('success', foreground='green', font=('Courier', 10, 'bold'))
        self.output_text.tag_config('error', foreground='red', font=('Courier', 10, 'bold'))
        self.output_text.config(state='disabled')
    
    def clear_output(self):
        self.output_text.config(state='normal')
        self.output_text.delete('1.0', tk.END)
        self.output_text.config(state='disabled')
    
    def reset_code(self, challenge):
        if messagebox.askyesno("Atiestatīt Kodu", "Vai esi pārliecināts?"):
            self.code_editor.delete('1.0', tk.END)
            self.code_editor.insert('1.0', challenge['starter_code'])
            self.clear_output()
    
    #Navigācija
    def show_placeholder_page(self, section, chapter, page, page_type):
        self.clear_content()
        
        label = tk.Label(self.content_frame, 
                        text=f"Nav {page_type} satura priekš {chapter} - Lapa {page}", 
                        font=('Arial', 14), bg='white')
        label.pack(pady=50)
        
        self.add_navigation_buttons()
    
    def add_navigation_buttons(self):
        nav_frame = tk.Frame(self.content_frame, bg='white')
        nav_frame.pack(side=tk.BOTTOM, pady=20)
        
        prev_btn = tk.Button(nav_frame, text="Iepriekšējā", 
                           command=self.previous_page,
                           padx=15, pady=5)
        prev_btn.pack(side=tk.LEFT, padx=10)
        
        home_btn = tk.Button(nav_frame, text="Sākums", 
                           command=self.show_welcome_page,
                           padx=15, pady=5)
        home_btn.pack(side=tk.LEFT, padx=10)
        
        next_btn = tk.Button(nav_frame, text="Nākamā →", 
                           command=self.next_page,
                           padx=15, pady=5)
        next_btn.pack(side=tk.LEFT, padx=10)
    
    def previous_page(self):
        if self.current_page is None:
            return
        
        section, chapter, page = self.current_page
        page_num = int(page)
        
        if page_num > 1:
            self.show_page(section, chapter, str(page_num - 1))
        else:
            # Iet uz iepriekšējo nodaļu
            chapters = list(self.navigation_structure[section].keys())
            current_idx = chapters.index(chapter)
            
            if current_idx > 0:
                prev_chapter = chapters[current_idx - 1]
                last_page = self.navigation_structure[section][prev_chapter][-1]
                self.show_page(section, prev_chapter, str(last_page))
    
    def next_page(self):
        if self.current_page is None:
            return
        
        section, chapter, page = self.current_page
        page_num = int(page)
        max_page = self.navigation_structure[section][chapter][-1]
        
        if page_num < max_page:
            self.show_page(section, chapter, str(page_num + 1))
        else:
            # Iet uz nākamo nodaļu
            chapters = list(self.navigation_structure[section].keys())
            current_idx = chapters.index(chapter)
            
            if current_idx < len(chapters) - 1:
                next_chapter = chapters[current_idx + 1]
                self.show_page(section, next_chapter, "1")


if __name__ == "__main__":
    root = tk.Tk()
    app = PageNavigator(root)
    root.mainloop()