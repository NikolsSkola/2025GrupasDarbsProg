import tkinter as tk
from tkinter import filedialog, messagebox
import csv
import math
import os
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg 
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

# CSV file path
CSV_FILE = "users.csv"


# Ensure CSV exists
def init_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["username", "password"])  # header


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("User Login System")
        self.geometry("400x300")
        self.configure(bg="#2b2b2b")
        self.calculator_windows = []
        self.current_frame = None

        self.show_frame(LoginPage)

    def show_frame(self, frame_class):
        if self.current_frame is not None:
            self.current_frame.destroy()

        self.current_frame = frame_class(self)
        self.current_frame.pack(fill="both", expand=True)


# ---------------------- LOGIN PAGE ----------------------
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
                    self.master.show_frame(WelcomePage)
                    return

        messagebox.showerror("Error", "Invalid username or password")


# ---------------------- REGISTER PAGE ----------------------
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

        # Check if username already exists
        with open(CSV_FILE, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["username"] == username:
                    messagebox.showerror("Error", "Username already exists")
                    return

        # Add new user
        with open(CSV_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([username, password])

        messagebox.showinfo("Success", "Account created")
        self.master.show_frame(LoginPage)


# ---------------------- WELCOME PAGE ----------------------
class WelcomePage(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg="#2b2b2b")

        # Logout text in top-right
        logout = tk.Label(
            self,
            text="Logout",
            font=("Arial", 10, "underline"),
            fg="#f44336",
            bg="#2b2b2b",
            cursor="hand2"
        )
        logout.place(relx=1.0, x=-10, y=10, anchor="ne")
        logout.bind("<Button-1>", lambda e: master.show_frame(LoginPage))

        # Main welcome text
        tk.Label(
            self,
            text="Welcome!",
            font=("Arial", 24, "bold"),
            fg="white",
            bg="#2b2b2b"
        ).pack(pady=40)

        # Button to open correlation calculator
        tk.Button(
            self,
            text="Open Correlation Coefficient Calculator",
            font=("Arial", 12),
            bg="#2196F3",
            fg="white",
            command=self.open_ccalculator
        ).pack(pady=20)
        
        # Button to open distribution calculator
        tk.Button(
            self,
            text="Open Normal Distribution Calculator",
            font=("Arial", 12),
            bg="#2196F3",
            fg="white",
            command=self.open_NDcalculator
        ).pack(pady=20)

    def open_ccalculator(self):
        win = CCalcWindow(self.master)
        self.master.calculator_windows.append(win)
    
    def open_NDcalculator(self):
        NormDist(self.master)



# ---------------------- NORMAL DISTRIBUTION ----------------------
class NormDist(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.master = master
        
        self.title("Normal Distribution Calculator")
        self.geometry("950x700")
        self.configure(bg="#2b2b2b")

        title = tk.Label(
            self,
            text="Normal Distribution Calculator",
            font=("Arial", 26, "bold"),
            fg="white",
            bg="#2b2b2b"
        )
        title.pack(pady=10)

        # Main frame
        self.main = tk.Frame(self, bg="#2b2b2b")
        self.main.pack(fill="both", expand=True)

        # Styles
        label_style = {"fg": "white", "bg": "#2b2b2b"}
        entry_style = {"font": ("Arial", 14), "width": 10}

        # ---------------- INPUTS ----------------
        tk.Label(self.main, text="Mean μ (value that centers the curve):", **label_style)\
            .grid(row=0, column=0, sticky="w", padx=10, pady=5)
        self.mean_entry = tk.Entry(self.main, **entry_style)
        self.mean_entry.grid(row=0, column=1)

        tk.Label(self.main, text="Standard deviation σ (spread of the curve):", **label_style)\
            .grid(row=1, column=0, sticky="w", padx=10, pady=5)
        self.sd_entry = tk.Entry(self.main, **entry_style)
        self.sd_entry.grid(row=1, column=1)

        # ---------------- MODE SELECTION ----------------
        tk.Label(self.main, text="Select mode:", **label_style)\
            .grid(row=2, column=0, sticky="w", padx=10, pady=10)

        self.mode = tk.StringVar(value="above")

        modes = [
            ("Above (P(X > x))", "above"),
            ("Below (P(X < x))", "below"),
            ("Between (P(x < X < y))", "between"),
            ("Outside (P(X < x or X > y))", "outside")
        ]

        col = 1
        for text, val in modes:
            tk.Radiobutton(
                self.main, text=text, variable=self.mode, value=val,
                fg="white", bg="#2b2b2b", selectcolor="#2b2b2b",
                font=("Arial", 12)
            ).grid(row=2, column=col, padx=10)
            col += 1

        # ---------------- VALUE INPUTS ----------------
        tk.Label(self.main, text="Value x:", **label_style)\
            .grid(row=3, column=0, sticky="w", padx=10, pady=5)
        self.x_entry = tk.Entry(self.main, **entry_style)
        self.x_entry.grid(row=3, column=1)

        tk.Label(self.main, text="Value y (for between/outside):", **label_style)\
            .grid(row=4, column=0, sticky="w", padx=10, pady=5)
        self.y_entry = tk.Entry(self.main, **entry_style)
        self.y_entry.grid(row=4, column=1)
        
        # Default values
        self.mean_entry.insert(0, "0")
        self.sd_entry.insert(0, "1")
        self.x_entry.insert(0, "-1.96")
        self.y_entry.insert(0, "1.96")

        # ---------------- CALCULATE BUTTON ----------------
        tk.Button(
            self.main, text="Calculate Probability", font=("Arial", 16),
            command=self.calculate_probability
        ).grid(row=5, column=0, columnspan=2, pady=15)

        self.result_label = tk.Label( self.main, text="Probability: ", font=("Arial", 16), **label_style)
        self.result_label.grid(row=6, column=0, columnspan=2, pady=10)

        # ---------------- INVERSE CALCULATOR ----------------
        tk.Label(self.main, text="Inverse Calculator (enter %):", **label_style)\
            .grid(row=7, column=0, sticky="w", padx=10, pady=10)

        self.inv_entry = tk.Entry(self.main, **entry_style)
        self.inv_entry.grid(row=7, column=1)

        tk.Button(
            self.main, text="Calculate Inverse", font=("Arial", 16),
            command=self.calculate_inverse
        ).grid(row=8, column=0, columnspan=2, pady=10)

        self.inv_label = tk.Label(self.main, text="Inverse result:", **label_style, font=("Arial", 16))
        self.inv_label.grid(row=9, column=0, columnspan=2, pady=10)

        # ---------------- MATPLOTLIB PLOT ----------------
        self.fig = Figure(figsize=(7, 4), facecolor="#2b2b2b")
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor("#2b2b2b")
        self.ax.tick_params(colors="white")
        self.fig.subplots_adjust(
            left=0.12,
            right=0.95,
            top=0.90,
            bottom=0.15
        )

        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(pady=20)

    # ---------------- MATH FUNCTIONS ----------------
    def pdf(self, x, mean, sd):
        return (1 / (sd * math.sqrt(2 * math.pi))) * math.exp(-0.5 * ((x - mean) / sd) ** 2)

    def cdf(self, x, mean, sd):
        return 0.5 * (1 + math.erf((x - mean) / (sd * math.sqrt(2))))

    def inv_cdf(self, p, mean, sd):
        # Acklam approximation
        if p <= 0 or p >= 1:
            return float("nan")

        a = [-3.969683028665376e+01, 2.209460984245205e+02,
             -2.759285104469687e+02, 1.383577518672690e+02,
             -3.066479806614716e+01, 2.506628277459239e+00]

        b = [-5.447609879822406e+01, 1.615858368580409e+02,
             -1.556989798598866e+02, 6.680131188771972e+01,
             -1.328068155288572e+01]

        c = [-7.784894002430293e-03, -3.223964580411365e-01,
             -2.400758277161838e+00, -2.549732539343734e+00,
              4.374664141464968e+00,  2.938163982698783e+00]

        d = [7.784695709041462e-03, 3.224671290700398e-01,
             2.445134137142996e+00, 3.754408661907416e+00]

        plow = 0.02425
        phigh = 1 - plow

        if p < plow:
            q = math.sqrt(-2 * math.log(p))
            x = (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
                ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
        elif p > phigh:
            q = math.sqrt(-2 * math.log(1 - p))
            x = -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
                 ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
        else:
            q = p - 0.5
            r = q * q
            x = (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5]) * q / \
                (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1)

        return mean + sd * x

    # ---------------- PROBABILITY CALCULATION ----------------
    def calculate_probability(self):
        try:
            mean = float(self.mean_entry.get())
            sd = float(self.sd_entry.get())
            x = float(self.x_entry.get()) if self.x_entry.get() else None
            y = float(self.y_entry.get()) if self.y_entry.get() else None   

            mode = self.mode.get()


            if mode in ("between", "outside") and x is not None and y is not None:
                if x > y:
                    x, y = y, x
                    
            if mode == "above":
                p = 1 - self.cdf(x, mean, sd)

            elif mode == "below":
                p = self.cdf(x, mean, sd)

            elif mode == "between":
                p = self.cdf(y, mean, sd) - self.cdf(x, mean, sd)

            elif mode == "outside":
                p = self.cdf(x, mean, sd) + (1 - self.cdf(y, mean, sd))

            p = max(0, min(1, p))
            
            self.result_label.config(text=f"Probability: {p*100:.4f}%")

            self.update_plot(mean, sd, x, y, mode)

        except:
            self.result_label.config(text="Invalid input")

    # ---------------- INVERSE CALCULATION ----------------
    def calculate_inverse(self):
        try:
            mean = float(self.mean_entry.get())
            sd = float(self.sd_entry.get())
            p = float(self.inv_entry.get()) / 100
            mode = self.mode.get()

            x = float(self.x_entry.get()) if self.x_entry.get() else None

            if mode == "above":
                result = self.inv_cdf(1 - p, mean, sd)

            elif mode == "below":
                result = self.inv_cdf(p, mean, sd)

            elif mode == "between":
                # find y such that CDF(y) - CDF(x) = p
                base = self.cdf(x, mean, sd)
                result = self.inv_cdf(base + p, mean, sd)
                target = base + p
                
                if target >= 1:
                    maxp = (1 - base) * 100
                    self.inv_label.config(text=f"Impossible. Max is {maxp:.4f}%")
                    return

            elif mode == "outside":
                # symmetric: half on each side
                tail = p / 2
                left = self.inv_cdf(tail, mean, sd)
                right = self.inv_cdf(1 - tail, mean, sd)

                self.inv_label.config(text=f"Inverse result: {left:.4f} and {right:.4f}")
                return

            self.inv_label.config(text=f"Inverse result: {result:.4f}")

        except:
            self.inv_label.config(text="Invalid input")

    # ---------------- PLOT ----------------
    def update_plot(self, mean, sd, x, y, mode):
        self.ax.clear()
        self.ax.set_facecolor("#2b2b2b")
        self.ax.tick_params(colors="white")

        xs = np.linspace(mean - 4*sd, mean + 4*sd, 400)
        ys = np.array([self.pdf(v, mean, sd) for v in xs])

        # Draw full curve
        self.ax.plot(xs, ys, color="cyan", linewidth=2)

        # ---------------- SHADING ----------------
        if mode == "above":
            mask = xs >= x
            self.ax.fill_between(xs[mask], ys[mask], color="cyan", alpha=0.3)

        elif mode == "below":
            mask = xs <= x
            self.ax.fill_between(xs[mask], ys[mask], color="cyan", alpha=0.3)

        elif mode == "between":
            mask = (xs >= x) & (xs <= y)
            self.ax.fill_between(xs[mask], ys[mask], color="cyan", alpha=0.3)

        elif mode == "outside":
            # LEFT TAIL
            left_mask = xs <= x
            self.ax.fill_between(xs[left_mask], ys[left_mask], color="cyan", alpha=0.3)

            # RIGHT TAIL
            right_mask = xs >= y
            self.ax.fill_between(xs[right_mask], ys[right_mask], color="cyan", alpha=0.3)

        # ---------------- VERTICAL LINES ----------------
        if x is not None:
            self.ax.axvline(x, color="yellow", linestyle="--", linewidth=2)

        if y is not None and mode in ("between", "outside"):
            self.ax.axvline(y, color="yellow", linestyle="--", linewidth=2)

        self.ax.set_title("Normal Distribution", color="white", fontsize=16)
        self.canvas.draw()

#_____________________________________________________________



# ---------------------- CORRELATION CALC ----------------------
class CCalcWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.master = master

        self.title("Correlation Coefficient Calculator")
        self.geometry("500x400")
        self.configure(bg="#2b2b2b")
        
        self.plot_frame = tk.Frame(self, bg="#2b2b2b") 
        self.plot_frame.pack(fill="both", expand=True, pady=10)

        self.data = []          # Loaded CSV data (list of dicts)
        self.columns = []       # Column names

        # Title
        tk.Label(
            self,
            text="Correlation Coefficient Calculator",
            font=("Arial", 16, "bold"),
            fg="white",
            bg="#2b2b2b"
        ).pack(pady=20)

        # Button to load CSV
        tk.Button(
            self,
            text="Select CSV File",
            font=("Arial", 12),
            bg="#2196F3",
            fg="white",
            command=self.load_csv
        ).pack(pady=10)

        # Dropdowns for selecting columns
        self.col1_var = tk.StringVar()
        self.col2_var = tk.StringVar()

        tk.Label(self, text="Select Variable X:", fg="white", bg="#2b2b2b").pack(pady=5)
        self.col1_menu = tk.OptionMenu(self, self.col1_var, ())
        self.col1_menu.pack()

        tk.Label(self, text="Select Variable Y:", fg="white", bg="#2b2b2b").pack(pady=5)
        self.col2_menu = tk.OptionMenu(self, self.col2_var, ())
        self.col2_menu.pack()

        # Calculate button
        tk.Button(
            self,
            text="Calculate Correlation",
            font=("Arial", 12),
            bg="#4CAF50",
            fg="white",
            command=self.calculate_correlation
        ).pack(pady=20)

        # Result label
        self.result_label = tk.Label(
            self,
            text="",
            font=("Arial", 14),
            fg="white",
            bg="#2b2b2b"
        )
        self.result_label.pack(pady=10)

        # Handle manual close
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------- CSV LOADING ----------------
    def load_csv(self):
        file_path = filedialog.askopenfilename(
            title="Select CSV File",
            filetypes=[("CSV Files", "*.csv")]
    )

        if not file_path:
            return

        try:
        # Detect delimiter automatically
            with open(file_path, "r", encoding="utf-8") as f:
                sample = f.read(2048)
                dialect = csv.Sniffer().sniff(sample)
                f.seek(0)
                reader = csv.DictReader(f, dialect=dialect)
                self.data = list(reader)
                self.columns = reader.fieldnames

            if not self.data or not self.columns:
                raise ValueError("CSV contains no usable data")

            self.update_dropdowns()
            messagebox.showinfo("Success", "CSV loaded successfully")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load CSV:\n{e}")

    def update_dropdowns(self):
        # Clear old menus
        self.col1_menu["menu"].delete(0, "end")
        self.col2_menu["menu"].delete(0, "end")

        for col in self.columns:
            self.col1_menu["menu"].add_command(
                label=col, command=lambda c=col: self.col1_var.set(c)
            )
            self.col2_menu["menu"].add_command(
                label=col, command=lambda c=col: self.col2_var.set(c)
            )

        # Set defaults
        if self.columns:
            self.col1_var.set(self.columns[0])
            self.col2_var.set(self.columns[1] if len(self.columns) > 1 else self.columns[0])

    # ---------------- CORRELATION CALCULATION ----------------
    def calculate_correlation(self):
        col1 = self.col1_var.get()
        col2 = self.col2_var.get()

        x_vals = self.extract_numeric_column(col1)
        y_vals = self.extract_numeric_column(col2)

        if len(x_vals) < 2 or len(y_vals) < 2:
            messagebox.showerror("Error", "Not enough numeric data in selected columns")
            return

        # Ensure equal length by trimming to the shortest
        n = min(len(x_vals), len(y_vals))
        x_vals = x_vals[:n]
        y_vals = y_vals[:n]

        try:
            r = self.pearson_correlation(x_vals, y_vals)
            self.result_label.config(text=f"Correlation (r): {r:.4f}")

            # Show the plot
            self.show_plot(x_vals, y_vals, r)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to calculate correlation:\n{e}")


    def pearson_correlation(self, x, y):
        n = len(x)
        mean_x = sum(x) / n
        mean_y = sum(y) / n

        numerator = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
        denominator = math.sqrt(
            sum((x[i] - mean_x) ** 2 for i in range(n)) *
            sum((y[i] - mean_y) ** 2 for i in range(n))
        )

        if denominator == 0:
            raise ValueError("Division by zero — one variable has no variance")

        return numerator / denominator
    def extract_numeric_column(self, col_name):
        values = []

        for row in self.data:
            raw = row.get(col_name, "").strip()

            if raw == "":
                continue  # skip empty cells

            # Replace comma decimal separators
            raw = raw.replace(",", ".")

            # Try converting to float
            try:
                num = float(raw)
                values.append(num)
            except:
                continue  # skip non-numeric values

        return values

    def show_plot(self, x_vals, y_vals, r):
        # Clear previous plot
        for widget in self.plot_frame.winfo_children():
            widget.destroy()

        # Create a matplotlib figure
        fig, ax = plt.subplots(figsize=(5, 4), dpi=100)
        ax.scatter(x_vals, y_vals, color="cyan", label="Data Points")

        # Regression line
        try:
            m = sum((x_vals[i] - sum(x_vals)/len(x_vals)) * (y_vals[i] - sum(y_vals)/len(y_vals)) for i in range(len(x_vals))) / \
                sum((x - sum(x_vals)/len(x_vals))**2 for x in x_vals)
            b = (sum(y_vals)/len(y_vals)) - m * (sum(x_vals)/len(x_vals))
            line_x = [min(x_vals), max(x_vals)]
            line_y = [m * x + b for x in line_x]
            ax.plot(line_x, line_y, color="yellow", label="Regression Line")
        except:
            pass  # If regression fails, skip it

        # Labels and title
        ax.set_title(f"Scatter Plot (r = {r:.4f})", color="white")
        ax.set_xlabel("X Values", color="white")
        ax.set_ylabel("Y Values", color="white")

        # Dark theme
        ax.set_facecolor("#2b2b2b")
        fig.patch.set_facecolor("#2b2b2b")
        ax.tick_params(colors="white")
        ax.spines["bottom"].set_color("white")
        ax.spines["left"].set_color("white")
        ax.spines["top"].set_color("white")
        ax.spines["right"].set_color("white")

        # Embed into Tkinter
        canvas = FigureCanvasTkAgg(fig, master=self.plot_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    # ---------------- WINDOW CLOSE ----------------
    def on_close(self):
        if self in self.master.calculator_windows:
            self.master.calculator_windows.remove(self)
        self.destroy()



# ---------------------- RUN APP ----------------------
if __name__ == "__main__":
    init_csv()
    app = App()
    app.mainloop()
    
"""
problems:
Inside:
when you reverse the x and y, the probabilyty becomes negative, and the graph shows everything non colored, it should always be positive aswell as colored between the two values.
aswell for the inside inverse, it should ignore the value y value because it is searching for the y value based on the percentage.
also if the selected percentage (for inverse) is higher than possible for the current x, then show  and error includint the max percentage possible from the current x (basically use the "above" for the error)

outside has a lot of problems:
-it doesnt subtract the area in the graph between the 2 values
-same as "inside" for negatievs, its even more fugged upp, it now shows a probability above 100%
-aswell for the inverse as "inside" it shoud 

"""
