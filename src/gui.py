import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LIMITS = {
    "duration": (1, 3600),
    "producers": (1, 32),
    "consumers": (1, 32),
    "size": (1, 64),
}
SPEED_MAX = 3000          

PRESETS = {
    "Номын жишээ (5 нүд, 2P, 3C)": dict(size=5, producers=2, consumers=3, prod=1000, cons=1000),
    "Тэнцүү хурд (1P, 1C)":        dict(size=5, producers=1, consumers=1, prod=300, cons=300),
    "Producer давамгай → дүүрнэ":  dict(size=5, producers=3, consumers=1, prod=200, cons=1200),
    "Consumer давамгай → хоосорно": dict(size=5, producers=1, consumers=3, prod=1200, cons=200),
    "1 нүдтэй буфер (ээлжилнэ)":   dict(size=1, producers=2, consumers=2, prod=300, cons=300),
    "Том буфер (16 нүд)":          dict(size=16, producers=4, consumers=2, prod=150, cons=500),
}

# Өнгө
C = dict(
    bg="#f6f5f1", panel="#ffffff", ink="#1d1d1f", muted="#6e6e73", line="#d8d6cf",
    slot_empty="#ecebe6", prod="#2e7d5b", prod_soft="#d5ecdf",
    cons="#c2621b", cons_soft="#f6e0cd", wait="#c62f3a", wait_soft="#f7d6d8",
    sleep="#9a9a9f", accent="#2f5fb3",
)
FONT = "DejaVu Sans"
FLASH = 0.35              

class Model:
    def __init__(self):
        self.reset(5, 2, 3)

    def reset(self, size, n_prod, n_cons):
        self.size = size
        self.buf = [None] * size
        self.owner = [None] * size     # аль producer хийснийг харуулах
        self.count = self.in_ = self.out = 0
        self.produced = self.consumed = self.waits = 0
        self.threads = {}
        for i in range(1, n_prod + 1):
            self.threads[f"P{i}"] = {"state": "sleep", "since": 0.0, "n": 0}
        for i in range(1, n_cons + 1):
            self.threads[f"C{i}"] = {"state": "sleep", "since": 0.0, "n": 0}
        self.slot_flash = {}           # slot -> (kind, wall_time)
        self.samples = []              # (t_ms, count) - графикт
        self.last_t = 0
        self.speed = None
        self.end = None
        self.errors = []

    def apply(self, e):
        ev = e.get("ev")
        now = time.monotonic()
        t = e.get("t", self.last_t)
        self.last_t = max(self.last_t, t)

        if ev in ("produce", "consume"):
            self.buf = e["buf"]
            self.count, self.in_, self.out = e["count"], e["in"], e["out"]
            slot, who = e["slot"], e["who"]
            if ev == "produce":
                self.produced += 1
                self.owner[slot] = who
            else:
                self.consumed += 1
                self.owner[slot] = None
            self.slot_flash[slot] = (ev, now)
            th = self.threads.get(who)
            if th:
                th.update(state=ev, since=now)
                th["n"] += 1
            # графикийн цэг (20 мс-ээс ойр бол сүүлийнхийг солино)
            if self.samples and t - self.samples[-1][0] < 20:
                self.samples[-1] = (t, self.count)
            else:
                self.samples.append((t, self.count))
                if len(self.samples) > 6000:
                    del self.samples[:1000]
        elif ev == "wait":
            self.waits += 1
            th = self.threads.get(e["who"])
            if th:
                th.update(state="wait", since=now, reason=e.get("reason", ""))
        elif ev == "wake":
            th = self.threads.get(e["who"])
            if th:
                th.update(state="wake", since=now)
        elif ev == "speed":
            self.speed = (e["prod_ms"], e["cons_ms"])
        elif ev == "end":
            self.end = e
        elif ev == "error":
            self.errors.append(e.get("msg", "?"))


def short(v):
    """Том тоог нүдэнд багтаахаар богиносгоно: 1295355725 -> …5725"""
    s = str(v)
    return s if len(s) <= 5 else "…" + s[-4:]


def describe(e):
    """Event-ийг хүнд уншигдах мөр болгоно (лог цонхонд)."""
    t = e.get("t", 0) / 1000
    ev = e.get("ev")
    if ev == "produce":
        return f"{t:7.3f}s  {e['who']:>4} → нүд[{e['slot']}]  {e['item']}   буфер {e['count']}", "prod"
    if ev == "consume":
        return f"{t:7.3f}s  {e['who']:>4} ← нүд[{e['slot']}]  {e['item']}   буфер {e['count']}", "cons"
    if ev == "wait":
        why = "буфер ДҮҮРЭН (empty=0)" if e.get("reason") == "full" else "буфер ХООСОН (full=0)"
        return f"{t:7.3f}s  {e['who']:>4} ХҮЛЭЭЖ байна: {why}", "wait"
    if ev == "wake":
        return f"{t:7.3f}s  {e['who']:>4} сэрлээ", "wake"
    if ev == "speed":
        return f"{t:7.3f}s  хурд: producer ≤{e['prod_ms']}мс, consumer ≤{e['cons_ms']}мс", "info"
    if ev == "config":
        return (f"  эхэллээ: buffer={e['size']} P={e['producers']} C={e['consumers']} "
                f"хугацаа={e['sleep']}с", "info")
    if ev == "end":
        return f"{t:7.3f}s  ДУУСЛАА: produced={e['produced']} consumed={e['consumed']}", "info"
    if ev == "error":
        return f"{t:7.3f}s  АЛДАА: {e.get('msg')}", "wait"
    return json.dumps(e, ensure_ascii=False), "info"


class App:
    def __init__(self, root, binary):
        self.root = root
        self.binary = binary
        self.model = Model()
        self.proc = None
        self.q = queue.Queue()
        self.raw = []                   
        self.started_at = None
        self.duration = 0
        self.status = "idle"            
        self._speed_job = None

        root.title("Producer–Consumer · Bounded Buffer")
        root.configure(bg=C["bg"])
        root.geometry("1320x860")
        root.minsize(1100, 720)
        self._style()
        self._build()
        self.apply_preset(next(iter(PRESETS)))
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.tick()

    def _style(self):
        st = ttk.Style()
        st.theme_use("clam")
        st.configure(".", font=(FONT, 10), background=C["bg"], foreground=C["ink"])
        st.configure("Panel.TFrame", background=C["panel"])
        st.configure("Panel.TLabel", background=C["panel"])
        st.configure("H.TLabel", background=C["panel"], font=(FONT, 11, "bold"))
        st.configure("Muted.TLabel", background=C["panel"], foreground=C["muted"], font=(FONT, 9))
        st.configure("Err.TLabel", background=C["panel"], foreground=C["wait"], font=(FONT, 9))
        st.configure("Big.TLabel", background=C["panel"], font=(FONT, 16, "bold"))
        st.configure("Start.TButton", font=(FONT, 10, "bold"))

    def _build(self):
        left = ttk.Frame(self.root, style="Panel.TFrame", padding=14)
        left.pack(side="left", fill="y", padx=(12, 6), pady=12)
        right = ttk.Frame(self.root)
        right.pack(side="left", fill="both", expand=True, padx=(6, 12), pady=12)

        ttk.Label(left, text="Тохиргоо", style="H.TLabel").pack(anchor="w")
        ttk.Label(left, text="Бэлэн хувилбар", style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        self.preset = tk.StringVar()
        cb = ttk.Combobox(left, textvariable=self.preset, values=list(PRESETS),
                          state="readonly", width=30)
        cb.pack(anchor="w", fill="x")
        cb.bind("<<ComboboxSelected>>", lambda _e: self.apply_preset(self.preset.get()))

        self.vars = {}
        grid = ttk.Frame(left, style="Panel.TFrame")
        grid.pack(anchor="w", fill="x", pady=(10, 0))
        fields = [("size", "Буферийн хэмжээ"), ("producers", "Producer тоо"),
                  ("consumers", "Consumer тоо"), ("duration", "Хугацаа (сек)")]
        for r, (key, label) in enumerate(fields):
            lo, hi = LIMITS[key]
            ttk.Label(grid, text=label, style="Panel.TLabel").grid(row=r, column=0, sticky="w", pady=3)
            v = tk.StringVar()
            sp = ttk.Spinbox(grid, from_=lo, to=hi, textvariable=v, width=7)
            sp.grid(row=r, column=1, sticky="e", padx=(8, 0))
            ttk.Label(grid, text=f"{lo}..{hi}", style="Muted.TLabel").grid(row=r, column=2, padx=(6, 0))
            self.vars[key] = v
            self.__dict__[f"spin_{key}"] = sp
        self.vars["duration"].set("60")

        ttk.Label(left, text="Хурд (санамсаргүй sleep-ийн дээд хязгаар)",
                  style="Muted.TLabel").pack(anchor="w", pady=(14, 0))
        self.prod_ms = tk.IntVar(value=1000)
        self.cons_ms = tk.IntVar(value=1000)
        self._speed_row(left, "Producer", self.prod_ms, C["prod"])
        self._speed_row(left, "Consumer", self.cons_ms, C["cons"])
        ttk.Label(left, text="Ажиллаж байхад ч өөрчилж болно.",
                  style="Muted.TLabel").pack(anchor="w")

        btns = ttk.Frame(left, style="Panel.TFrame")
        btns.pack(fill="x", pady=(14, 0))
        self.btn_start = ttk.Button(btns, text="▶ Эхлүүлэх", style="Start.TButton", command=self.start)
        self.btn_stop = ttk.Button(btns, text="■ Зогсоох", command=self.stop)
        self.btn_reset = ttk.Button(btns, text="↺ Reset", command=self.reset)
        self.btn_start.pack(side="left", expand=True, fill="x")
        self.btn_stop.pack(side="left", expand=True, fill="x", padx=4)
        self.btn_reset.pack(side="left", expand=True, fill="x")

        self.err = ttk.Label(left, text="", style="Err.TLabel", wraplength=270, justify="left")
        self.err.pack(anchor="w", pady=(6, 0))

        # --- Тоолуур, семафор ---
        ttk.Separator(left).pack(fill="x", pady=10)
        ttk.Label(left, text="Төлөв", style="H.TLabel").pack(anchor="w")
        self.lbl_status = ttk.Label(left, text="", style="Panel.TLabel")
        self.lbl_status.pack(anchor="w", pady=(4, 0))
        self.progress = ttk.Progressbar(left, length=270, maximum=100)
        self.progress.pack(anchor="w", fill="x", pady=(4, 8))

        stats = ttk.Frame(left, style="Panel.TFrame")
        stats.pack(fill="x")
        self.stat = {}
        for i, (key, label) in enumerate([("produced", "Produced"), ("consumed", "Consumed"),
                                           ("waits", "Wait тоо"), ("rate", "item/сек")]):
            f = ttk.Frame(stats, style="Panel.TFrame")
            f.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 18), pady=2)
            self.stat[key] = ttk.Label(f, text="0", style="Big.TLabel")
            self.stat[key].pack(anchor="w")
            ttk.Label(f, text=label, style="Muted.TLabel").pack(anchor="w")

        ttk.Label(left, text="Синхрончлолын объектууд", style="Muted.TLabel").pack(anchor="w", pady=(10, 2))
        self.sem = tk.Canvas(left, width=270, height=96, bg=C["panel"], highlightthickness=0)
        self.sem.pack(anchor="w")

        ttk.Separator(left).pack(fill="x", pady=10)
        lb = ttk.Frame(left, style="Panel.TFrame")
        lb.pack(fill="x")
        ttk.Button(lb, text="Лог хадгалах", command=self.save_log).pack(side="left", expand=True, fill="x")
        ttk.Button(lb, text="Зөв эсэхийг шалгах", command=self.verify).pack(side="left", expand=True,
                                                                           fill="x", padx=(4, 0))

        # --- Баруун: дүрслэл, график, лог ---
        self.canvas = tk.Canvas(right, bg=C["panel"], highlightthickness=0, height=470)
        self.canvas.pack(fill="both", expand=True)
        bottom = ttk.Frame(right)
        bottom.pack(fill="x", pady=(8, 0))
        self.chart = tk.Canvas(bottom, bg=C["panel"], highlightthickness=0, height=200, width=470)
        self.chart.pack(side="left", fill="y")
        logf = ttk.Frame(bottom, style="Panel.TFrame", padding=(8, 6))
        logf.pack(side="left", fill="both", expand=True, padx=(8, 0))
        ttk.Label(logf, text="Event лог (бодит C програмаас)", style="Muted.TLabel").pack(anchor="w")
        self.log = tk.Text(logf, height=10, font=("DejaVu Sans Mono", 9), bg=C["panel"],
                           relief="flat", wrap="none", state="disabled")
        self.log.pack(fill="both", expand=True)
        for tag, col in [("prod", C["prod"]), ("cons", C["cons"]), ("wait", C["wait"]),
                         ("wake", C["accent"]), ("info", C["muted"])]:
            self.log.tag_configure(tag, foreground=col)

    def _speed_row(self, parent, name, var, color):
        f = ttk.Frame(parent, style="Panel.TFrame")
        f.pack(fill="x", pady=(4, 0))
        ttk.Label(f, text=name, style="Panel.TLabel", width=9).pack(side="left")
        val = ttk.Label(f, text="", style="Panel.TLabel", width=8, anchor="e")
        s = ttk.Scale(f, from_=0, to=SPEED_MAX, orient="horizontal", length=150,
                      command=lambda v: var.set(int(float(v)) // 10 * 10))
        s.set(var.get())
        s.pack(side="left")
        self.__dict__[f"scale_{name}"] = s
        val.pack(side="left")

        def changed(*_):
            val.config(text=f"≤{var.get()} мс")
            self.speed_changed()
        var.trace_add("write", changed)
        changed()

    # ---------------- үйлдлүүд ----------------
    def apply_preset(self, name):
        p = PRESETS.get(name)
        if not p:
            return
        self.preset.set(name)
        self.vars["size"].set(str(p["size"]))
        self.vars["producers"].set(str(p["producers"]))
        self.vars["consumers"].set(str(p["consumers"]))
        self.prod_ms.set(p["prod"])
        self.cons_ms.set(p["cons"])
        self.scale_Producer.set(p["prod"])
        self.scale_Consumer.set(p["cons"])

    def read_inputs(self):
        """Оролтыг шалгана. Алдаатай бол (None, мессеж) буцаана."""
        names = {"size": "Буферийн хэмжээ", "producers": "Producer тоо",
                 "consumers": "Consumer тоо", "duration": "Хугацаа"}
        out = {}
        for key, (lo, hi) in LIMITS.items():
            raw = self.vars[key].get().strip()
            try:
                v = int(raw)
            except ValueError:
                return None, f"{names[key]}: \"{raw}\" бүхэл тоо биш байна."
            if not lo <= v <= hi:
                return None, f"{names[key]}: {v} нь зөвшөөрөгдөх мужаас гадуур ({lo}..{hi})."
            out[key] = v
        return out, None

    def start(self):
        if self.status == "running":
            return
        cfg, err = self.read_inputs()
        if err:
            self.err.config(text="⚠ " + err)
            messagebox.showerror("Буруу оролт", err)
            return
        if not (os.path.isfile(self.binary) and os.access(self.binary, os.X_OK)):
            msg = (f"C програм олдсонгүй:\n{self.binary}\n\n"
                   "Эхлээд төслийн хавтсанд хөрвүүлнэ үү:\n"
                   "gcc -Wall -pthread src/buffer.c src/main.c -o pc")
            self.err.config(text="⚠ pc програм олдсонгүй")
            messagebox.showerror("Програм олдсонгүй", msg)
            return
        self.err.config(text="")
        p = PRESETS.get(self.preset.get())
        if not p or (p["size"], p["producers"], p["consumers"], p["prod"], p["cons"]) != (
                cfg["size"], cfg["producers"], cfg["consumers"],
                self.prod_ms.get(), self.cons_ms.get()):
            self.preset.set("(гараар тохируулсан)")
        cmd = [self.binary, "-j", str(cfg["duration"]), str(cfg["producers"]),
               str(cfg["consumers"]), str(cfg["size"]),
               str(self.prod_ms.get()), str(self.cons_ms.get())]
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, text=True, bufsize=1)
        except OSError as ex:
            messagebox.showerror("Эхлүүлж чадсангүй", str(ex))
            return
        self.model.reset(cfg["size"], cfg["producers"], cfg["consumers"])
        self.raw = []
        self.q = queue.Queue()
        self.duration = cfg["duration"]
        self.started_at = time.monotonic()
        self.status = "running"
        self.log_clear()
        self.log_add(f"$ {' '.join(os.path.relpath(c, ROOT) if i == 0 else c for i, c in enumerate(cmd))}",
                     "info")
        threading.Thread(target=self._reader, args=(self.proc, self.q), daemon=True).start()
        self._set_inputs_state("disabled")

    def _reader(self, proc, q):
        """Тусдаа thread: C програмын stdout-ийг мөр мөрөөр уншиж дараалалд хийнэ."""
        for line in proc.stdout:
            q.put(line)
        proc.wait()
        q.put(None)                    # дууссан тэмдэг

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.status = "stopped"

    def reset(self):
        self.stop()
        if self.proc:
            try:
                self.proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        self.status = "idle"
        self.started_at = None
        self.raw = []
        self.vars["duration"].set("60")
        self.apply_preset(next(iter(PRESETS)))
        cfg, _ = self.read_inputs()
        self.model.reset(cfg["size"], cfg["producers"], cfg["consumers"])
        self.err.config(text="")
        self.log_clear()
        self._set_inputs_state("normal")

    def speed_changed(self):
        """Слайдер хөдлөхөд 150 мс хүлээгээд нэг л команд илгээнэ (debounce)."""
        if self._speed_job:
            self.root.after_cancel(self._speed_job)
        self._speed_job = self.root.after(150, self._send_speed)

    def _send_speed(self):
        self._speed_job = None
        if self.status != "running" or not self.proc or self.proc.poll() is not None:
            return
        try:
            self.proc.stdin.write(f"prod_ms {self.prod_ms.get()}\ncons_ms {self.cons_ms.get()}\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def _set_inputs_state(self, state):
        for key in LIMITS:
            self.__dict__[f"spin_{key}"].config(state=state)

    def save_log(self):
        if not self.raw:
            messagebox.showinfo("Лог хоосон", "Эхлээд програмаа ажиллуулна уу.")
            return
        name = time.strftime("run_%Y%m%d_%H%M%S.jsonl")
        path = filedialog.asksaveasfilename(initialdir=os.path.join(ROOT, "tests"),
                                            initialfile=name, defaultextension=".jsonl")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(self.raw)
            self.log_add(f"  лог хадгалагдлаа: {path} ({len(self.raw)} мөр)", "info")

    def verify(self):
        """tests/check_log.py-г одоогийн ажиллагааны лог дээр ажиллуулна."""
        if not self.raw:
            messagebox.showinfo("Лог хоосон", "Эхлээд програмаа ажиллуулна уу.")
            return
        checker = os.path.join(ROOT, "tests", "check_log.py")
        if not os.path.isfile(checker):
            messagebox.showerror("Олдсонгүй", f"{checker} файл алга.")
            return
        r = subprocess.run([sys.executable, checker], input="".join(self.raw),
                           capture_output=True, text=True)
        title = "PASS" if r.returncode == 0 else "FAIL"
        (messagebox.showinfo if r.returncode == 0 else messagebox.showerror)(
            f"check_log.py: {title}", r.stdout + r.stderr)

    def on_close(self):
        self.stop()
        self.root.destroy()

    # ---------------- лог ----------------
    def log_clear(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def log_add(self, text, tag="info"):
        self.log.config(state="normal")
        self.log.insert("end", text + "\n", tag)
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > 400:
            self.log.delete("1.0", f"{lines - 400}.0")
        self.log.see("end")
        self.log.config(state="disabled")

    def tick(self):
        """40 мс тутам: ирсэн event-үүдийг загварт хэрэглээд дахин зурна."""
        processed, shown, finished = 0, [], False
        while processed < 40000:
            try:
                line = self.q.get_nowait()
            except queue.Empty:
                break
            if line is None:
                finished = True
                break
            processed += 1
            self.raw.append(line)
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            self.model.apply(e)
            shown.append(e)
        if len(shown) > 120:         
            self.log_add(f"  … {len(shown) - 120} event алгасав (бүгд лог файлд бий)", "info")
            shown = shown[-120:]
        for e in shown:
            self.log_add(*describe(e))
        if finished:
            self._finished()
        self.draw()
        self.root.after(40, self.tick)

    def _finished(self):
        err = ""
        if self.proc and self.proc.stderr:
            err = self.proc.stderr.read().strip()
        if self.status == "running":
            self.status = "finished"
        if err:
            self.err.config(text="⚠ " + err)
            self.log_add("  stderr: " + err, "wait")
        self._set_inputs_state("normal")

    # ---------------- зурах ----------------
    def draw(self):
        m = self.model
        if m.end and self.status == "running":   
            self.status = "finished"
        # статус, progress
        el = 0 if not self.started_at else time.monotonic() - self.started_at
        txt = {"idle": "Бэлэн. ▶ Эхлүүлэх дарна уу.",
               "running": f"Ажиллаж байна  {el:5.1f} / {self.duration} сек",
               "finished": f"Дууссан: {self.duration} сек (main sleep → exit)",
               "stopped": "Хэрэглэгч зогсоосон"}[self.status]
        self.lbl_status.config(text=txt)
        pct = 0 if not self.duration else min(100, m.last_t / 10 / self.duration)
        self.progress["value"] = 100 if self.status == "finished" else pct
        self.stat["produced"].config(text=str(m.produced))
        self.stat["consumed"].config(text=str(m.consumed))
        self.stat["waits"].config(text=str(m.waits))
        rate = m.consumed / (m.last_t / 1000) if m.last_t > 500 else 0
        self.stat["rate"].config(text=f"{rate:.1f}")
        self.draw_sem()
        self.draw_main()
        self.draw_chart()

    def draw_sem(self):
        m, c = self.model, self.sem
        c.delete("all")
        rows = [("empty", m.size - m.count, C["prod"], "сул"),
                ("full", m.count, C["cons"], "дүүрсэн")]
        for i, (name, val, col, hint) in enumerate(rows):
            y = 6 + i * 30
            c.create_text(0, y + 9, text=name, anchor="w", font=(FONT, 10, "bold"), fill=C["ink"])
            c.create_rectangle(52, y, 172, y + 18, fill=C["slot_empty"], outline="")
            w = 120 * val / max(1, m.size)
            c.create_rectangle(52, y, 52 + w, y + 18, fill=col, outline="")
            c.create_text(180, y + 9, text=f"{val}  {hint}", anchor="w", font=(FONT, 9), fill=C["muted"])
        y = 66
        c.create_text(0, y + 9, text="mutex", anchor="w", font=(FONT, 10, "bold"), fill=C["ink"])
        c.create_text(52, y + 9, text="buffer[in/out]-д нэг л thread хандана",
                      anchor="w", font=(FONT, 8), fill=C["muted"])

    def _thread_grid(self, names, x0, y0, width, color, soft):
        c, now = self.canvas, time.monotonic()
        n = len(names)
        per = min(n, 8 if n <= 16 else 16)
        gap = 6
        bw = min(118, (width - gap * (per - 1)) / per)
        bh = 40 if per <= 8 else 30
        for i, name in enumerate(names):
            th = self.model.threads[name]
            x = x0 + (i % per) * (bw + gap)
            y = y0 + (i // per) * (bh + gap)
            fresh = now - th["since"] < FLASH
            st = th["state"]
            if st == "wait":
                fill, out, label = C["wait_soft"], C["wait"], "ХҮЛЭЭЖ"
            elif st in ("produce", "consume") and fresh:
                fill, out, label = soft, color, "produce" if st == "produce" else "consume"
            elif st == "wake" and fresh:
                fill, out, label = soft, C["accent"], "сэрлээ"
            else:
                fill, out, label = C["panel"], C["line"], "sleep"
            c.create_rectangle(x, y, x + bw, y + bh, fill=fill, outline=out, width=2 if out != C["line"] else 1)
            if per <= 8:
                c.create_text(x + 6, y + bh / 2 - 7, text=name, anchor="w",
                              font=(FONT, 10, "bold"), fill=color)
                c.create_text(x + 6, y + bh / 2 + 8, text=f"{label} · {th['n']}", anchor="w",
                              font=(FONT, 8), fill=out if out != C["line"] else C["muted"])
            else:
                # олон thread үед зөвхөн нэр; төлөвийг өнгөөр нь ялгана
                c.create_text(x + bw / 2, y + bh / 2, text=name,
                              font=(FONT, 8, "bold"), fill=color)
        rows = (n + per - 1) // per
        return y0 + rows * (bh + gap)

    def draw_main(self):
        c, m, now = self.canvas, self.model, time.monotonic()
        c.delete("all")
        W = max(600, c.winfo_width())
        pad = 24
        prods = [k for k in m.threads if k[0] == "P"]
        cons = [k for k in m.threads if k[0] == "C"]

        c.create_text(pad, 18, text="Producer thread-үүд", anchor="w",
                      font=(FONT, 10, "bold"), fill=C["prod"])
        lx = W - pad   # өнгөний тайлбар
        for txt, fill, out in [("хүлээж байна (sem_wait)", C["wait_soft"], C["wait"]),
                               ("produce/consume", C["prod_soft"], C["prod"]),
                               ("sleep", C["panel"], C["line"])]:
            tid = c.create_text(lx, 18, text=txt, anchor="e", font=(FONT, 8), fill=C["muted"])
            lx = c.bbox(tid)[0] - 6          # бичгийн бодит өргөнийг хэмжинэ
            c.create_rectangle(lx - 12, 12, lx, 24, fill=fill, outline=out)
            lx -= 24
        y = self._thread_grid(prods, pad, 32, W - 2 * pad, C["prod"], C["prod_soft"])

        # --- буфер ---
        y += 14
        c.create_line(pad, y, W - pad, y, fill=C["line"])
        y += 16
        c.create_text(pad, y, text=f"Тойрог буфер  ({m.count}/{m.size} дүүрсэн)", anchor="w",
                      font=(FONT, 10, "bold"), fill=C["ink"])
        legend_x = W - pad
        for txt, col in [("out (дараагийн унших)", C["cons"]), ("in (дараагийн бичих)", C["prod"])]:
            c.create_text(legend_x, y, text="▲ " + txt, anchor="e", font=(FONT, 8), fill=col)
            legend_x -= 175
        y += 26
        per = min(m.size, 16)
        gap = 6
        sw = min(96, (W - 2 * pad - gap * (per - 1)) / per)
        sh = 54 if m.size <= 16 else 42
        row_h = sh + 30
        for i in range(m.size):
            x = pad + (i % per) * (sw + gap)
            yy = y + (i // per) * row_h
            v = m.buf[i] if i < len(m.buf) else None
            kind, t = m.slot_flash.get(i, ("", 0))
            fresh = now - t < FLASH
            if v is None:
                fill = C["cons_soft"] if (fresh and kind == "consume") else C["slot_empty"]
                outline = C["cons"] if (fresh and kind == "consume") else C["line"]
            else:
                fill = C["prod_soft"]
                outline = C["prod"] if fresh else C["prod_soft"]
            c.create_rectangle(x, yy, x + sw, yy + sh, fill=fill, outline=outline,
                               width=3 if fresh else 1)
            c.create_text(x + 4, yy + 3, text=str(i), anchor="nw", font=(FONT, 7), fill=C["muted"])
            if v is not None:
                c.create_text(x + sw / 2, yy + sh / 2 - 4, text=short(v),
                              font=(FONT, 9 if sw > 50 else 7, "bold"), fill=C["ink"])
                if m.owner[i] and sw > 40:
                    c.create_text(x + sw / 2, yy + sh - 9, text=m.owner[i], font=(FONT, 7),
                                  fill=C["prod"])
            # in / out заагч
            ay = yy + sh + 4
            both = m.in_ == m.out
            if i == m.in_:
                c.create_text(x + sw / 2 - (4 if both else 0), ay, text="▲in",
                              anchor="ne" if both else "n", font=(FONT, 8, "bold"), fill=C["prod"])
            if i == m.out:
                c.create_text(x + sw / 2 + (4 if both else 0), ay, text="▲out",
                              anchor="nw" if both else "n", font=(FONT, 8, "bold"), fill=C["cons"])
        y += ((m.size + per - 1) // per) * row_h + 4

        c.create_line(pad, y, W - pad, y, fill=C["line"])
        y += 18
        c.create_text(pad, y, text="Consumer thread-үүд", anchor="w",
                      font=(FONT, 10, "bold"), fill=C["cons"])
        self._thread_grid(cons, pad, y + 14, W - 2 * pad, C["cons"], C["cons_soft"])

    def draw_chart(self):
        c, m = self.chart, self.model
        c.delete("all")
        W, H = int(c["width"]), int(c["height"])
        l, r, t, b = 36, 12, 26, 24
        c.create_text(10, 12, text="Буферийн дүүргэлт (сүүлийн 20 сек)", anchor="w",
                      font=(FONT, 9, "bold"), fill=C["ink"])
        c.create_rectangle(l, t, W - r, H - b, outline=C["line"])
        top = m.size
        y_of = lambda v: H - b - (H - b - t) * v / max(1, top)
        c.create_line(l, y_of(top), W - r, y_of(top), fill=C["wait"], dash=(3, 3))
        c.create_text(l - 4, y_of(top), text=str(top), anchor="e", font=(FONT, 8), fill=C["wait"])
        c.create_text(l - 4, y_of(0), text="0", anchor="e", font=(FONT, 8), fill=C["muted"])
        c.create_text(W - r, y_of(top) - 8, text="дүүрэн → producer хүлээнэ", anchor="e",
                      font=(FONT, 7), fill=C["wait"])
        span = 20000
        t1 = max(m.last_t, span)
        t0 = t1 - span
        x_of = lambda tm: l + (W - r - l) * (tm - t0) / span
        for s in range(0, 21, 5):
            tm = t0 + s * 1000
            c.create_text(x_of(tm), H - b + 10, text=f"{tm / 1000:.0f}s", font=(FONT, 7),
                          fill=C["muted"])
        pts = []
        prev = 0
        for tm, v in m.samples:
            if tm < t0:
                prev = v
                continue
            if not pts:
                pts += [x_of(t0), y_of(prev)]
            pts += [x_of(tm), y_of(prev), x_of(tm), y_of(v)]   
            prev = v
        if pts:
            pts += [x_of(m.last_t), y_of(prev)]
            c.create_line(*pts, fill=C["accent"], width=2)


def main():
    ap = argparse.ArgumentParser(description="Producer-Consumer UI")
    ap.add_argument("--bin", default=os.path.join(ROOT, "pc"), help="C програмын зам (анхдагч ./pc)")
    args = ap.parse_args()
    root = tk.Tk()
    App(root, os.path.abspath(args.bin))
    root.mainloop()


if __name__ == "__main__":
    main()