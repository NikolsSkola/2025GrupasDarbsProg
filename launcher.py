"""
launcher.py  —  12a Project Launcher
────────────────────────────────────
Place this file in the SAME folder as:
  12a_bruno_kumpins_datu_izstrade.py
  12_a_NikolsGabriels_TestaAplikacija.py
  Dastins_Jevdokimovs_12a_blackjack_cardlab_v22.py
  TestDB.db
  users.csv  (auto-created on first run)
"""

import tkinter as tk
from tkinter import messagebox
import csv
import os
import importlib.util
import multiprocessing as mp

# ── File paths ──────────────────────────────────────────────────────────────
THIS_DIR     = os.path.dirname(os.path.abspath(__file__))
CSV_FILE     = os.path.join(THIS_DIR, "users.csv")
FILE_NIKOLS  = os.path.join(THIS_DIR, "12.a_NikolsGabriels_TestaAplikacija.py")
FILE_DASTINS = os.path.join(THIS_DIR, "Dastins_Jevdokimovs_12a_blackjack_cardlab_v22.py")
FILE_BRUNO   = os.path.join(THIS_DIR, "12a_bruno_kumpins_datu_izstrade.py")


# ── CSV helpers ──────────────────────────────────────────────────────────────
def init_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="") as f:
            csv.writer(f).writerow(["username", "password"])


# ── Module loader ────────────────────────────────────────────────────────────
def _load_module(name, path):
    if not os.path.exists(path):
        messagebox.showerror("File not found",
                             f"Cannot find:\n{path}\n\n"
                             "Make sure all project files are in the same folder as launcher.py")
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ══════════════════════════════════════════════════════════════════════════════
# MAIN APP
# ══════════════════════════════════════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("12a Project Launcher")
        self.geometry("400x300")
        self.configure(bg="#2b2b2b")
        self.current_frame = None
        self.show_frame(LoginPage)

    def show_frame(self, frame_class, **kwargs):
        if self.current_frame is not None:
            self.current_frame.destroy()
        self.current_frame = frame_class(self, **kwargs)
        self.current_frame.pack(fill="both", expand=True)


# ──────────────────────────────────────────────────────────────────────────────
# LOGIN PAGE  — Bruno's code verbatim; success goes to HubPage
# ──────────────────────────────────────────────────────────────────────────────
class LoginPage(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg="#2b2b2b")

        tk.Label(self, text="Login", font=("Arial", 22, "bold"), fg="white", bg="#2b2b2b").pack(pady=20)

        self.username = tk.Entry(self, font=("Arial", 12))
        self.password = tk.Entry(self, font=("Arial", 12), show="*")

        self._styled_label("Username")
        self.username.pack(pady=5)

        self._styled_label("Password")
        self.password.pack(pady=5)

        tk.Button(self, text="Login", font=("Arial", 12), bg="#4CAF50", fg="white",
                  command=self.login).pack(pady=15)

        tk.Button(self, text="Register", font=("Arial", 10), bg="#2196F3", fg="white",
                  command=lambda: master.show_frame(RegisterPage)).pack()

    def _styled_label(self, text):
        tk.Label(self, text=text, font=("Arial", 12), fg="white", bg="#2b2b2b").pack()

    def login(self):
        username = self.username.get()
        password = self.password.get()

        with open(CSV_FILE, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["username"] == username and row["password"] == password:
                    self.master.geometry("400x380")
                    mod = _load_module("nikols_app", FILE_NIKOLS)
                    if mod is None:
                        return
                    top = tk.Toplevel(self.master)
                    top.title("Programming Learning Platform — Nikols Gabriels")
                    try:
                        mod.PageNavigator(top)
                    except Exception as e:
                        messagebox.showerror("Error", str(e), parent=self.master)
                        top.destroy()
                    return
                
        messagebox.showerror("Error", "Invalid username or password")


# ──────────────────────────────────────────────────────────────────────────────
# REGISTER PAGE  — Bruno's code verbatim
# ──────────────────────────────────────────────────────────────────────────────
class RegisterPage(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg="#2b2b2b")

        tk.Label(self, text="Register", font=("Arial", 22, "bold"), fg="white", bg="#2b2b2b").pack(pady=20)

        self.username = tk.Entry(self, font=("Arial", 12))
        self.password = tk.Entry(self, font=("Arial", 12), show="*")

        self._styled_label("New Username")
        self.username.pack(pady=5)

        self._styled_label("New Password")
        self.password.pack(pady=5)

        tk.Button(self, text="Create Account", font=("Arial", 12), bg="#FF9800", fg="white",
                  command=self.register).pack(pady=15)

        tk.Button(self, text="Back to Login", font=("Arial", 10), bg="#757575", fg="white",
                  command=lambda: master.show_frame(LoginPage)).pack()

    def _styled_label(self, text):
        tk.Label(self, text=text, font=("Arial", 12), fg="white", bg="#2b2b2b").pack()

    def register(self):
        username = self.username.get()
        password = self.password.get()

        if username == "" or password == "":
            messagebox.showerror("Error", "All fields required")
            return

        with open(CSV_FILE, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["username"] == username:
                    messagebox.showerror("Error", "Username already exists")
                    return

        with open(CSV_FILE, "a", newline="") as f:
            csv.writer(f).writerow([username, password])

        messagebox.showinfo("Success", "Account created")
        self.master.show_frame(LoginPage)

# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    mp.freeze_support()
    init_csv()
    app = App()
    app.mainloop()