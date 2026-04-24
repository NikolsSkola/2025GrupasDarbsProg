import tkinter as tk
from tkinter import messagebox
import csv
import os
import importlib.util
import multiprocessing as mp

THIS_DIR     = os.path.dirname(os.path.abspath(__file__))
CSV_FILE     = os.path.join(THIS_DIR, "users.csv")
FILE_NIKOLS  = os.path.join(THIS_DIR, "12.a_NikolsGabriels_TestaAplikacija.py")
FILE_DASTINS = os.path.join(THIS_DIR, "Dastins_Jevdokimovs_12a_blackjack_cardlab_v22.py")
FILE_BRUNO   = os.path.join(THIS_DIR, "12a_bruno_kumpins_datu_izstrade.py")

#CSV helpers
def init_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="") as f:
            csv.writer(f).writerow(["username", "password"])

#Module loader
def loadModule(name, path):
    if not os.path.exists(path):
        messagebox.showerror("File not found",
                             f"Cannot find:\n{path}\n\n"
                             "Make sure all project files are in the same folder as launcher.py")
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

#Galvenā aplikācija

colDark = "#373E40"
colDCyan = "#305252"
colCyan = "#488286"
colGray = "#77878B"
colLCyan = "#B7D5D4"

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Login")
        self.geometry("400x300")
        self.configure(bg="#2b2b2b")
        self.current_frame = None
        self.show_frame(LoginPage)

    def show_frame(self, frame_class, **kwargs):
        if self.current_frame is not None:
            self.current_frame.destroy()
        self.current_frame = frame_class(self, **kwargs)
        self.current_frame.pack(fill="both", expand=True)

#Login lapa

class LoginPage(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=colDark)

        tk.Label(self, text="Login", font=("Arial", 22, "bold"), fg="white", bg=colDark).pack(pady=20)

        self.username_canvas, self.username_entry = self._pill_entry("Username")
        self.password_canvas, self.password_entry = self._pill_entry("Password", secret=True)

        self._pill_button("Login", self.login)
        self._pill_button("Register", lambda: master.show_frame(RegisterPage))

    def _draw_box(self, canvas, color, x2=300, y2=40, r=12):
        canvas.delete("box")
        x1, y1 = 0, 4
        canvas.create_arc(x1, y1, x1+2*r, y1+2*r, start=90, extent=90, fill=color, outline=color, tags="box")
        canvas.create_arc(x2-2*r, y1, x2, y1+2*r, start=0, extent=90, fill=color, outline=color, tags="box")
        canvas.create_arc(x1, y2-2*r, x1+2*r, y2, start=180, extent=90, fill=color, outline=color, tags="box")
        canvas.create_arc(x2-2*r, y2-2*r, x2, y2, start=270, extent=90, fill=color, outline=color, tags="box")
        canvas.create_rectangle(x1+r, y1, x2-r, y2, fill=color, outline=color, tags="box")
        canvas.create_rectangle(x1, y1+r, x2, y2-r, fill=color, outline=color, tags="box")

    def _pill_entry(self, placeholder, secret=False):
        canvas = tk.Canvas(self, width=300, height=45, bg=colDark, highlightthickness=0)
        canvas.pack(pady=5)

        self._draw_box(canvas, colGray)

        entry = tk.Entry(canvas, font=("Arial", 13), bg=colGray, fg="white",
                         insertbackground=colDCyan, relief="flat", width=22, bd=0,
                         highlightthickness=0, show="")
        canvas.create_window(150, 22, window=entry)

        for widget in (canvas, entry):
            widget.bind("<Enter>", lambda e, c=canvas, en=entry: [
                self._draw_box(c, colLCyan, 300, 45), en.config(bg=colLCyan, fg=colDCyan)])
            widget.bind("<Leave>", lambda e, c=canvas, en=entry: (
                None if en == self.master.focus_get() else [
                self._draw_box(c, colGray, 300, 45), en.config(bg=colGray, fg="white")]))

        entry.insert(0, placeholder)

        def on_focus_in(event, en=entry):
            if en.get() == placeholder:
                en.delete(0, tk.END)
            en.config(bg=colLCyan, fg=colDCyan)
            self._draw_box(canvas, colLCyan, 300, 45)
            if secret:
                en.config(show="*")

        def on_focus_out(event, en=entry):
            if en.get() == "":
                en.config(show="")
                en.insert(0, placeholder)
            en.config(bg=colGray, fg="white")
            self._draw_box(canvas, colGray, 300, 45)

        entry.bind("<FocusIn>", on_focus_in)
        entry.bind("<FocusOut>", on_focus_out)

        return canvas, entry

    def _pill_button(self, text, command):
        canvas = tk.Canvas(self, width=200, height=38, bg=colDark, highlightthickness=0)
        canvas.pack(pady=8)

        self._draw_box(canvas, colCyan, 200, 38)

        label = tk.Label(canvas, text=text, font=("Arial", 12, "bold"),
                         bg=colCyan, fg="white", cursor="hand2")
        canvas.create_window(100, 19, window=label)

        for widget in (canvas, label):
            widget.bind("<Enter>", lambda e, c=canvas, lb=label: [
                self._draw_box(c, colLCyan, 200, 38), lb.config(bg=colLCyan, fg=colDCyan)])
            widget.bind("<Leave>", lambda e, c=canvas, lb=label: [
                self._draw_box(c, colCyan, 200, 38), lb.config(bg=colCyan, fg="white")])
            widget.bind("<Button-1>", lambda e: command())

    def login(self):
        username = self.username_entry.get()
        password = self.password_entry.get()

        with open(CSV_FILE, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["username"] == username and row["password"] == password:
                    self.master.geometry("400x380")
                    mod = loadModule("nikols_app", FILE_NIKOLS)
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

# Registrācijas lapa

class RegisterPage(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=colDark)

        tk.Label(self, text="Register", font=("Arial", 22, "bold"), fg="white", bg=colDark).pack(pady=20)

        self.username_canvas, self.username_entry = self._pill_entry("New Username")
        self.password_canvas, self.password_entry = self._pill_entry("New Password", secret=True)

        self._pill_button("Create Account", self.register)
        self._pill_button("Back to Login", lambda: master.show_frame(LoginPage))

    def _draw_box(self, canvas, color, x2=300, y2=40, r=12):
        canvas.delete("box")
        x1, y1 = 0, 4
        canvas.create_arc(x1, y1, x1+2*r, y1+2*r, start=90, extent=90, fill=color, outline=color, tags="box")
        canvas.create_arc(x2-2*r, y1, x2, y1+2*r, start=0, extent=90, fill=color, outline=color, tags="box")
        canvas.create_arc(x1, y2-2*r, x1+2*r, y2, start=180, extent=90, fill=color, outline=color, tags="box")
        canvas.create_arc(x2-2*r, y2-2*r, x2, y2, start=270, extent=90, fill=color, outline=color, tags="box")
        canvas.create_rectangle(x1+r, y1, x2-r, y2, fill=color, outline=color, tags="box")
        canvas.create_rectangle(x1, y1+r, x2, y2-r, fill=color, outline=color, tags="box")

    def _pill_entry(self, placeholder, secret=False):
        canvas = tk.Canvas(self, width=300, height=45, bg=colDark, highlightthickness=0)
        canvas.pack(pady=5)

        self._draw_box(canvas, colGray)

        entry = tk.Entry(canvas, font=("Arial", 13), bg=colGray, fg="white",
                         insertbackground=colDCyan, relief="flat", width=22, bd=0,
                         highlightthickness=0, show="")
        canvas.create_window(150, 22, window=entry)

        for widget in (canvas, entry):
            widget.bind("<Enter>", lambda e, c=canvas, en=entry: [
                self._draw_box(c, colLCyan, 300, 45), en.config(bg=colLCyan, fg=colDCyan)])
            widget.bind("<Leave>", lambda e, c=canvas, en=entry: (
                None if en == self.master.focus_get() else [
                self._draw_box(c, colGray, 300, 45), en.config(bg=colGray, fg="white")]))

        entry.insert(0, placeholder)

        def on_focus_in(event, en=entry):
            if en.get() == placeholder:
                en.delete(0, tk.END)
            en.config(bg=colLCyan, fg=colDCyan)
            self._draw_box(canvas, colLCyan, 300, 45)
            if secret:
                en.config(show="*")

        def on_focus_out(event, en=entry):
            if en.get() == "":
                en.config(show="")
                en.insert(0, placeholder)
            en.config(bg=colGray, fg="white")
            self._draw_box(canvas, colGray, 300, 45)

        entry.bind("<FocusIn>", on_focus_in)
        entry.bind("<FocusOut>", on_focus_out)

        return canvas, entry

    def _pill_button(self, text, command):
        canvas = tk.Canvas(self, width=200, height=38, bg=colDark, highlightthickness=0)
        canvas.pack(pady=8)

        self._draw_box(canvas, colCyan, 200, 38)

        label = tk.Label(canvas, text=text, font=("Arial", 12, "bold"),
                         bg=colCyan, fg="white", cursor="hand2")
        canvas.create_window(100, 19, window=label)

        for widget in (canvas, label):
            widget.bind("<Enter>", lambda e, c=canvas, lb=label: [
                self._draw_box(c, colLCyan, 200, 38), lb.config(bg=colLCyan, fg=colDCyan)])
            widget.bind("<Leave>", lambda e, c=canvas, lb=label: [
                self._draw_box(c, colCyan, 200, 38), lb.config(bg=colCyan, fg="white")])
            widget.bind("<Button-1>", lambda e: command())

    def register(self):
        username = self.username_entry.get()
        password = self.password_entry.get()

        if username == "New Username":
            username = ""
        if password == "New Password":
            password = ""

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
            writer = csv.writer(f)
            writer.writerow([username, password])

        messagebox.showinfo("Success", "Account created")
        self.master.show_frame(LoginPage)

if __name__ == "__main__":
    mp.freeze_support()
    init_csv()
    app = App()
    app.mainloop()