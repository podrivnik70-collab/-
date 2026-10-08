# -*- coding: utf-8 -*-
"""Вкладка «Улучшение v3» — запуск upgrade_loop из UI Sapphira."""

import os
import re
import sys
import subprocess
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

from sapphira.ui import theme as ui_theme

HERE = Path(__file__).resolve().parent
V2_ROOT = HERE.parent.parent.parent


def build(parent, app):
    f = ttk.Frame(parent)

    state = {
        "process": None,
        "thread": None,
        "total": 0,
        "done": 0,
        "failed": 0,
        "current_file": "",
        "running": False,
    }

    # ─── Верхняя панель настроек ─────────────────
    cfg = ttk.LabelFrame(f, text="  ⚙ Настройки  ", padding=8)
    cfg.pack(fill="x", padx=6, pady=6)

    row1 = ttk.Frame(cfg)
    row1.pack(fill="x", pady=2)
    ttk.Label(row1, text="Путь к v3:", width=12).pack(side="left")
    v3_var = tk.StringVar(value=str(Path.home() / "Desktop" / "Сапфира" / "Сапфира версия 3"))
    ttk.Entry(row1, textvariable=v3_var).pack(side="left", fill="x", expand=True, padx=4)

    def choose_v3():
        d = filedialog.askdirectory(initialdir=v3_var.get() or str(V2_ROOT.parent))
        if d:
            v3_var.set(d)
    ttk.Button(row1, text="Выбрать...", command=choose_v3).pack(side="left", padx=2)

    row2 = ttk.Frame(cfg)
    row2.pack(fill="x", pady=2)
    ttk.Label(row2, text="Часов:", width=12).pack(side="left")
    hours_var = tk.StringVar(value="8")
    ttk.Entry(row2, textvariable=hours_var, width=6).pack(side="left", padx=4)

    ttk.Label(row2, text="Мин/файл:").pack(side="left", padx=(10, 4))
    mpf_var = tk.StringVar(value="20")
    ttk.Entry(row2, textvariable=mpf_var, width=6).pack(side="left", padx=4)

    ttk.Label(row2, text="Кодер:").pack(side="left", padx=(10, 4))
    coder_var = tk.StringVar(value="Qwen3.5-9B")
    coder_combo = ttk.Combobox(row2, textvariable=coder_var, state="readonly", width=28)
    coder_combo.pack(side="left", padx=4)

    ttk.Label(row2, text="Судья:").pack(side="left", padx=(10, 4))
    judge_var = tk.StringVar(value="Qwen2.5-Coder-7B-Instruct")
    judge_combo = ttk.Combobox(row2, textvariable=judge_var, state="readonly", width=28)
    judge_combo.pack(side="left", padx=4)

    # Заполняем combo при старте
    def refresh_models():
        try:
            models = app.router.list_chat_models()
            coder_combo["values"] = models
            judge_combo["values"] = models
            if models and coder_var.get() not in models:
                coder_var.set(models[0])
            if models and judge_var.get() not in models:
                judge_var.set(models[0])
        except Exception:
            pass
    app.root.after(500, refresh_models)

    # ─── Кнопки управления ────────────────────────
    btn_row = ttk.Frame(f)
    btn_row.pack(fill="x", padx=6, pady=(0, 4))

    btn_start = ttk.Button(btn_row, text="▶ Запустить цикл", style="Accent.TButton")
    btn_stop = ttk.Button(btn_row, text="■ Стоп", state="disabled")
    btn_report = ttk.Button(btn_row, text="📊 Открыть отчёт")
    btn_clear = ttk.Button(btn_row, text="🗑 Очистить лог")
    btn_start.pack(side="left", padx=2)
    btn_stop.pack(side="left", padx=2)
    btn_report.pack(side="left", padx=2)
    btn_clear.pack(side="left", padx=2)

    status_lbl = ttk.Label(btn_row, text="Ожидание", foreground=ui_theme.FG_DIM)
    status_lbl.pack(side="right", padx=8)

    # ─── Прогресс ─────────────────────────────────
    prog_row = ttk.Frame(f)
    prog_row.pack(fill="x", padx=6)
    progress = ttk.Progressbar(prog_row, mode="determinate")
    progress.pack(side="left", fill="x", expand=True, padx=2)
    prog_lbl = ttk.Label(prog_row, text="0/0", foreground=ui_theme.FG_DIM, width=10)
    prog_lbl.pack(side="left", padx=4)

    # ─── Лог ─────────────────────────────────────
    log_frame = ttk.LabelFrame(f, text="  📋 Лог в реальном времени  ", padding=4)
    log_frame.pack(fill="both", expand=True, padx=6, pady=6)
    log_widget = scrolledtext.ScrolledText(
        log_frame, wrap="word", font=("Consolas", 9),
        bg=ui_theme.BG_MAIN, fg=ui_theme.FG_TEXT,
        insertbackground=ui_theme.FG_TEXT, relief="flat", borderwidth=0)
    log_widget.pack(fill="both", expand=True)
    for tag, color in [("ok", ui_theme.GREEN), ("err", ui_theme.RED),
                        ("warn", ui_theme.YELLOW), ("info", ui_theme.BLUE),
                        ("dim", ui_theme.FG_DIM)]:
        log_widget.tag_config(tag, foreground=color)

    # ─── Хелперы ──────────────────────────────────
    def append_log(text, tag=None):
        def _do():
            log_widget.insert("end", text + "\n", tag or "info")
            log_widget.see("end")
        app.root.after(0, _do)

    def set_status(text, color=ui_theme.FG_DIM):
        app.root.after(0, lambda: status_lbl.config(text=text, foreground=color))

    def update_progress():
        def _do():
            progress["maximum"] = max(state["total"], 1)
            progress["value"] = state["done"] + state["failed"]
            prog_lbl.config(text=f"{state['done']+state['failed']}/{state['total']}")
        app.root.after(0, _do)

    # ─── Запуск ───────────────────────────────────
    def on_start():
        if state["running"]:
            return

        v3 = v3_var.get().strip()
        if not Path(v3).is_dir():
            messagebox.showerror("Ошибка", f"Папка не найдена:\n{v3}")
            return
        if not (Path(v3) / "sapphira").is_dir():
            messagebox.showerror("Ошибка", f"В папке нет sapphira/:\n{v3}")
            return

        try:
            hours = float(hours_var.get())
            mpf = int(mpf_var.get())
        except ValueError:
            messagebox.showerror("Ошибка", "Часы и мин/файл должны быть числами")
            return

        state["running"] = True
        state["total"] = 0
        state["done"] = 0
        state["failed"] = 0
        state["current_file"] = ""

        log_widget.delete("1.0", "end")
        btn_start.config(state="disabled")
        btn_stop.config(state="normal")
        set_status("Запуск...", ui_theme.YELLOW)
        append_log(f"=== Запуск цикла на {hours}ч ===", "ok")
        append_log(f"Кодер:  {coder_var.get()}", "info")
        append_log(f"Судья:  {judge_var.get()}", "info")
        append_log(f"Цель:   {v3}", "info")
        append_log("")

        cmd = [
            sys.executable, "upgrade_loop.py",
            "--target", v3,
            "--hours", str(hours),
            "--coder", coder_var.get(),
            "--judge", judge_var.get(),
            "--minutes-per-file", str(mpf),
        ]

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            # НЕ используем CREATE_NO_WINDOW чтобы видеть вывод
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            proc = subprocess.Popen(
                cmd,
                cwd=str(V2_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
            state["process"] = proc
        except Exception as e:
            append_log(f"Не удалось запустить: {e}", "err")
            state["running"] = False
            btn_start.config(state="normal")
            btn_stop.config(state="disabled")
            return

        # Thread читает stdout
        def reader():
            try:
                for line in proc.stdout:
                    _handle_line(line.rstrip())
            except Exception as e:
                append_log(f"[reader] {e}", "err")
            finally:
                proc.wait()
                rc = proc.returncode
                app.root.after(0, lambda: _on_finish(rc))
        state["thread"] = threading.Thread(target=reader, daemon=True)
        state["thread"].start()

    def _handle_line(line):
        """Разбирает строку из stdout upgrade_loop."""
        if not line:
            return

        # Задачи: N
        m = re.search(r"Задач:\s+(\d+)", line)
        if m:
            state["total"] = int(m.group(1))
            update_progress()

        # FILE: path
        m = re.search(r"\[INFO\]\s+FILE:\s+(.+)$", line)
        if m:
            state["current_file"] = m.group(1).strip()
            append_log("")
            append_log(f"📁 {state['current_file']}", "info")

        # УСПЕХ
        if "УСПЕХ" in line:
            state["done"] += 1
            update_progress()
            append_log(line, "ok")
            return

        # FAIL
        if re.search(r"\[INFO\]\s+FAIL\s*$", line):
            state["failed"] += 1
            update_progress()
            append_log(line, "err")
            return

        # Откат / судья против
        if "rollback" in line or "судья против" in line:
            append_log(line, "warn")
            return

        # Ошибки
        if "[WARN]" in line or "[ERROR]" in line or "Traceback" in line:
            append_log(line, "warn")
            return

        # Итог
        if "DONE." in line:
            append_log("")
            append_log(line, "ok")
            set_status("Завершено", ui_theme.GREEN)
            return

        # Всё остальное
        append_log(line, "dim")

    def _on_finish(rc):
        state["running"] = False
        state["process"] = None
        btn_start.config(state="normal")
        btn_stop.config(state="disabled")
        if rc == 0:
            set_status("Завершено", ui_theme.GREEN)
            append_log("")
            append_log("✅ Цикл завершён. Отчёт готов.", "ok")
        else:
            set_status(f"Остановлено (код {rc})", ui_theme.YELLOW)
            append_log(f"\nЦикл остановлен (код {rc})", "warn")

    def on_stop():
        if not state["process"]:
            return
        if not messagebox.askyesno("Стоп", "Остановить цикл?"):
            return
        try:
            state["process"].terminate()
            set_status("Останавливаю...", ui_theme.YELLOW)
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def on_report():
        v3 = v3_var.get().strip()
        report = Path(v3) / "upgrade_report.md"
        if not report.exists():
            messagebox.showinfo("Отчёт", "Отчёта ещё нет — цикл не завершён.")
            return
        try:
            os.startfile(str(report))
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def on_clear():
        log_widget.delete("1.0", "end")
        state["done"] = 0
        state["failed"] = 0
        state["total"] = 0
        update_progress()
        set_status("Очищено", ui_theme.FG_DIM)

    btn_start.config(command=on_start)
    btn_stop.config(command=on_stop)
    btn_report.config(command=on_report)
    btn_clear.config(command=on_clear)

    return f