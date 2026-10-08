# -*- coding: utf-8 -*-
"""Вкладка «Идеи»."""

import json
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from pathlib import Path

from sapphira.ui import theme as ui_theme

HERE = Path(__file__).resolve().parent
V2_ROOT = HERE.parent.parent.parent
IDEAS_FILE = V2_ROOT / "data" / "ideas.json"


def build(parent, app):
    f = ttk.Frame(parent)

    bar = ttk.Frame(f, padding=6)
    bar.pack(fill="x")
    ttk.Label(bar, text="Идеи из интернета",
              font=("Segoe UI", 11, "bold"),
              foreground=ui_theme.BLUE).pack(side="left")
    info_lbl = ttk.Label(bar, text="", foreground=ui_theme.FG_DIM)
    info_lbl.pack(side="left", padx=12)

    def refresh():
        load_ideas()

    def run_hunt():
        def worker():
            try:
                if str(V2_ROOT) not in sys.path:
                    sys.path.insert(0, str(V2_ROOT))
                from sapphira.features.project_hunter import hunt
                app.write("\n[hunter] Поиск идей...\n", "info")
                new = hunt(log_func=lambda m:
                           app.write(f"[hunter] {m}\n", "info"))
                app.write(f"[hunter] Найдено: {len(new)}\n", "ok")
                app.root.after(0, refresh)
            except Exception as e:
                app.write(f"[hunter] Ошибка: {e}\n", "err")
        threading.Thread(target=worker, daemon=True).start()

    ttk.Button(bar, text="Обновить",
               command=refresh).pack(side="right", padx=2)
    ttk.Button(bar, text="Найти идеи", style="Accent.TButton",
               command=run_hunt).pack(side="right", padx=2)

    paned = ttk.PanedWindow(f, orient="horizontal")
    paned.pack(fill="both", expand=True, padx=6, pady=4)

    left = ttk.Frame(paned)
    paned.add(left, weight=2)
    ttk.Label(left, text="Найденные идеи:",
              foreground=ui_theme.BLUE).pack(anchor="w", padx=4)
    listbox = tk.Listbox(left, bg=ui_theme.BG_INPUT, fg=ui_theme.FG_TEXT,
                          font=("Consolas", 9),
                          selectbackground=ui_theme.ACCENT, relief="flat")
    listbox.pack(fill="both", expand=True, padx=4, pady=4)

    right = ttk.Frame(paned)
    paned.add(right, weight=3)
    ttk.Label(right, text="Детали:",
              foreground=ui_theme.BLUE).pack(anchor="w", padx=4)
    details = scrolledtext.ScrolledText(
        right, wrap="word", font=("Consolas", 9),
        bg=ui_theme.BG_MAIN, fg=ui_theme.FG_TEXT, relief="flat")
    details.pack(fill="both", expand=True, padx=4, pady=4)

    actions = ttk.Frame(f)
    actions.pack(fill="x", padx=6, pady=(0, 6))
    ttk.Button(actions, text="В очередь задач",
               command=lambda: _to_queue(app, listbox)).pack(side="left", padx=2)
    ttk.Button(actions, text="Отклонить",
               command=lambda: _reject(listbox)).pack(side="left", padx=2)

    state = {"ideas": []}

    def load_ideas():
        try:
            if not IDEAS_FILE.exists():
                state["ideas"] = []
            else:
                data = json.loads(IDEAS_FILE.read_text(encoding="utf-8"))
                state["ideas"] = data.get("ideas", [])
        except Exception:
            state["ideas"] = []
        listbox.delete(0, "end")
        for idea in state["ideas"]:
            stars = "*" * int(idea.get("priority", 1))
            listbox.insert("end", f"{stars:<6} {idea.get('name', '')[:50]}")
        info_lbl.config(text=f"Всего идей: {len(state['ideas'])}")

    def on_select(e=None):
        sel = listbox.curselection()
        if not sel:
            return
        idea = state["ideas"][sel[0]]
        details.delete("1.0", "end")
        details.insert("1.0", (
            f"{idea.get('name', '')}\n"
            f"{idea.get('url', '')}\n"
            f"stars: {idea.get('stars', 0)}\n\n"
            f"Feature: {idea.get('feature', '')}\n"
            f"Verdict: {idea.get('verdict', '')}\n"
            f"Reason: {idea.get('reason', '')}\n"
            f"Priority: {idea.get('priority', 0)}/5\n\n"
            f"Description:\n{idea.get('description', '')}\n"
        ))

    listbox.bind("<<ListboxSelect>>", on_select)

    def _to_queue(app_ref, lb):
        sel = lb.curselection()
        if not sel:
            return
        idea = state["ideas"][sel[0]]
        try:
            task_text = (f"Реализуй фичу: {idea.get('feature', '')}. "
                          f"Пример: {idea.get('url', '')}")
            app_ref.queue.add(task_text)
            app_ref.write(f"[queue] +{task_text[:80]}\n", "ok")
            messagebox.showinfo("OK", "Добавлено в очередь")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def _reject(lb):
        sel = lb.curselection()
        if not sel:
            return
        idea = state["ideas"][sel[0]]
        if not messagebox.askyesno("Удалить", f"Удалить:\n{idea.get('name')}?"):
            return
        state["ideas"].pop(sel[0])
        try:
            IDEAS_FILE.write_text(
                json.dumps({"updated": 0, "ideas": state["ideas"]},
                            ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception:
            pass
        load_ideas()

    load_ideas()
    return f