# -*- coding: utf-8 -*-
"""Модальные диалоги UI."""
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from sapphira.ui import theme as ui_theme


class ModelAdviceDialog:
    """Диалог рекомендации моделей.

    Результат в self.result:
      - "apply"  — применить рекомендации
      - "manual" — оставить текущие
      - None     — закрыт крестиком
    Дополнительно:
      - self.wait_download — пользователь просил дождаться скачивания
    """

    def __init__(self, parent, recommendation: dict,
                 skip_types: list = None, on_download=None):
        self.parent = parent
        self.rec = recommendation
        self.skip_types = skip_types or []
        self.on_download = on_download
        self.result = None
        self.skip_checked = False
        self.wait_download = False

        self.win = tk.Toplevel(parent)
        self.win.title("⚙ Авто-подбор моделей")
        self.win.geometry("640x520")
        self.win.configure(bg=ui_theme.BG_MAIN)
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.grab_set()

        parent.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - 640) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - 520) // 2
        self.win.geometry(f"+{max(x, 0)}+{max(y, 0)}")

        self._build()

    def _build(self):
        top = tk.Frame(self.win, bg=ui_theme.BG_MAIN, pady=12)
        top.pack(fill="x", padx=20)
        tk.Label(top, text="⚙  Рекомендация моделей",
                 font=("Segoe UI", 14, "bold"),
                 bg=ui_theme.BG_MAIN, fg=ui_theme.BLUE).pack(anchor="w")

        a = self.rec["analysis"]
        action_label = {
            "code": "Написание кода", "testing": "Тесты",
            "docs": "Документация", "refactor": "Рефакторинг",
        }.get(a["action"], a["action"])
        mode_label = {
            "create": "Создание нового проекта",
            "edit": "Улучшение существующего",
        }.get(a["mode"], a["mode"])
        size_label = {
            "small": "небольшой", "medium": "средний", "large": "большой",
        }.get(a["size"], a["size"])

        info = tk.Frame(self.win, bg=ui_theme.BG_PANEL, padx=14, pady=10)
        info.pack(fill="x", padx=20)
        tk.Label(info, text=f"Тип: {mode_label}, {action_label}",
                 font=("Segoe UI", 10),
                 bg=ui_theme.BG_PANEL, fg=ui_theme.FG_TEXT,
                 anchor="w").pack(fill="x")
        tk.Label(info, text=f"Размер проекта: {size_label}",
                 font=("Segoe UI", 9),
                 bg=ui_theme.BG_PANEL, fg=ui_theme.FG_DIM,
                 anchor="w").pack(fill="x")

        tk.Label(self.win, text="Модели для этой задачи:",
                 font=("Segoe UI", 10, "bold"),
                 bg=ui_theme.BG_MAIN, fg=ui_theme.FG_TEXT,
                 anchor="w").pack(fill="x", padx=20, pady=(12, 4))

        table = tk.Frame(self.win, bg=ui_theme.BG_PANEL, padx=10, pady=8)
        table.pack(fill="x", padx=20)

        for label, key in [("Планирование", "planner"),
                            ("Написание кода", "coder"),
                            ("Быстрый судья", "judge_fast"),
                            ("Строгий судья", "judge_strict")]:
            m = self.rec["models"][key]
            r = tk.Frame(table, bg=ui_theme.BG_PANEL)
            r.pack(fill="x", pady=2)
            tk.Label(r, text=f"{label:<20}", font=("Consolas", 9),
                     bg=ui_theme.BG_PANEL, fg=ui_theme.FG_DIM,
                     anchor="w", width=18).pack(side="left")
            tk.Label(r, text=f"{m['name']:<30}", font=("Consolas", 9),
                     bg=ui_theme.BG_PANEL, fg=ui_theme.FG_TEXT,
                     anchor="w").pack(side="left")
            icon = "✅" if m.get("installed") else "⚠"
            color = ui_theme.GREEN if m.get("installed") else ui_theme.YELLOW
            tk.Label(r, text=icon, font=("Segoe UI", 10),
                     bg=ui_theme.BG_PANEL, fg=color).pack(side="left", padx=4)

        missing = self.rec.get("missing", [])
        if missing:
            warn = tk.Frame(self.win, bg="#3a2f00", padx=14, pady=10)
            warn.pack(fill="x", padx=20, pady=(12, 0))
            total = self.rec.get("total_download_gb", 0)
            tk.Label(warn, text=f"⚠  Отсутствуют модели ({total} ГБ):",
                     font=("Segoe UI", 9, "bold"),
                     bg="#3a2f00", fg=ui_theme.YELLOW,
                     anchor="w").pack(fill="x")
            for m in missing:
                tk.Label(warn,
                         text=f"   • {m['name']} — {m['size_gb']} ГБ ({m['role']})",
                         font=("Consolas", 9),
                         bg="#3a2f00", fg=ui_theme.FG_TEXT,
                         anchor="w").pack(fill="x")

        self.skip_var = tk.BooleanVar(value=False)
        skip = tk.Frame(self.win, bg=ui_theme.BG_MAIN)
        skip.pack(fill="x", padx=20, pady=(8, 0))
        tk.Checkbutton(skip,
                       text=f"Больше не показывать для типа «{a['mode']} + {a['action']}»",
                       variable=self.skip_var,
                       bg=ui_theme.BG_MAIN, fg=ui_theme.FG_DIM,
                       activebackground=ui_theme.BG_MAIN,
                       activeforeground=ui_theme.FG_TEXT,
                       selectcolor=ui_theme.BG_INPUT,
                       font=("Segoe UI", 8)).pack(anchor="w")

        btns = tk.Frame(self.win, bg=ui_theme.BG_MAIN, pady=14)
        btns.pack(fill="x", padx=20)

        tk.Button(btns, text="✅ Применить рекомендации",
                  font=("Segoe UI", 10, "bold"),
                  bg=ui_theme.ACCENT, fg="white",
                  relief="flat", padx=14, pady=8, cursor="hand2",
                  command=self._apply).pack(side="left")

        if missing and self.on_download:
            tk.Button(btns, text=f"📥 Скачать ({total} ГБ)",
                      font=("Segoe UI", 10),
                      bg="#c17d00", fg="white",
                      relief="flat", padx=14, pady=8, cursor="hand2",
                      command=self._download).pack(side="left", padx=6)

        tk.Button(btns, text="Вручную",
                  font=("Segoe UI", 10),
                  bg=ui_theme.BG_PANEL, fg=ui_theme.FG_TEXT,
                  relief="flat", padx=14, pady=8, cursor="hand2",
                  command=self._manual).pack(side="right")

    def _apply(self):
        self.result = "apply"
        self.skip_checked = self.skip_var.get()
        self.win.destroy()

    def _manual(self):
        self.result = "manual"
        self.skip_checked = self.skip_var.get()
        self.win.destroy()

    def _download(self):
        """Скачать отсутствующие модели. Спрашивает: ждать или фоном?"""
        total = self.rec.get("total_download_gb", 0)
        from tkinter import messagebox as mb
        wait = mb.askyesno(
            "Скачивание моделей",
            f"Скачать {total} ГБ?\n\n"
            "ДА — задача подождёт завершения, потом запустится\n"
            "     с рекомендованной моделью.\n\n"
            "НЕТ — задача запустится сейчас с fallback-моделью,\n"
            "     а скачивание пойдёт в фоне.",
            parent=self.win,
        )
        self.wait_download = wait
        self.result = "apply"
        self.skip_checked = self.skip_var.get()
        self.win.destroy()
        # Вызываем callback ПОСЛЕ закрытия своего окна
        if self.on_download:
            for m in self.rec.get("missing", []):
                try:
                    self.on_download(m["name"], wait=wait)
                except TypeError:
                    self.on_download(m["name"])

    def show(self):
        self.win.wait_window()
        return self.result, self.skip_checked


class DownloadProgressDialog:
    """Модальное окно прогресса скачивания модели.

    Блокирует вызывающий код через wait_window().
    Возвращает True если скачалось, False если отменено/ошибка.
    """

    def __init__(self, parent, model_name, download_func):
        self.parent = parent
        self.model_name = model_name
        self.download_func = download_func
        self.success = False
        self.cancelled = False

        self.win = tk.Toplevel(parent)
        self.win.title(f"📥 Скачивание {model_name}")
        self.win.geometry("500x180")
        self.win.configure(bg=ui_theme.BG_MAIN)
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        parent.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - 500) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - 180) // 2
        self.win.geometry(f"+{max(x, 0)}+{max(y, 0)}")

        self._build()
        self._start()

    def _build(self):
        tk.Label(self.win, text=f"📥 Скачивание {self.model_name}",
                 font=("Segoe UI", 12, "bold"),
                 bg=ui_theme.BG_MAIN, fg=ui_theme.BLUE).pack(pady=(20, 8))

        self.status = tk.Label(self.win, text="Подготовка...",
                                font=("Segoe UI", 9),
                                bg=ui_theme.BG_MAIN, fg=ui_theme.FG_DIM)
        self.status.pack()

        self.progress = ttk.Progressbar(self.win, mode="determinate",
                                         length=420)
        self.progress.pack(fill="x", padx=40, pady=12)

        tk.Button(self.win, text="Отменить",
                  font=("Segoe UI", 9),
                  bg=ui_theme.BG_PANEL, fg=ui_theme.FG_TEXT,
                  relief="flat", padx=14, pady=4, cursor="hand2",
                  command=self._on_cancel).pack()

    def _start(self):
        def worker():
            self.download_func(self._on_progress, self._on_done)
        threading.Thread(target=worker, daemon=True).start()

    def _on_progress(self, rid, pct, txt):
        def _do():
            if pct >= 0:
                self.progress["value"] = pct
                self.status.config(text=f"{pct}% — {txt}",
                                    foreground=ui_theme.YELLOW)
            else:
                self.status.config(text=txt[:80],
                                    foreground=ui_theme.FG_DIM)
        try:
            self.win.after(0, _do)
        except Exception:
            pass

    def _on_done(self, rid, ok, err):
        self.success = ok
        def _do():
            if ok:
                self.status.config(text="✅ Готово",
                                    foreground=ui_theme.GREEN)
                self.progress["value"] = 100
                self.win.after(800, self.win.destroy)
            else:
                self.status.config(text=f"✗ {err[:100]}",
                                    foreground=ui_theme.RED)
                self.win.after(2000, self.win.destroy)
        try:
            self.win.after(0, _do)
        except Exception:
            pass

    def _on_cancel(self):
        self.cancelled = True
        try:
            from sapphira.models import manager as model_manager
            model_manager.cancel_pull() if hasattr(model_manager, "cancel_pull") else None
        except Exception:
            pass
        self.win.destroy()

    def show(self):
        self.win.wait_window()
        return self.success