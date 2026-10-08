# -*- coding: utf-8 -*-
"""Вкладка «Тест моделей» — benchmark скачанных моделей. v2."""
import csv
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from sapphira.ui import theme as ui_theme


def build(parent, app):
    f = ttk.Frame(parent)

    # Всё состояние в простом словаре, никаких set для selected —
    # будем каждый раз читать галочки напрямую
    state = {
        "running": False,
        "stop": False,
        "results": [],
        "started_at": 0,
    }

    # ─── Верх: список моделей с галочками ───
    top = ttk.LabelFrame(f, text="  Модели для теста  ", padding=8)
    top.pack(fill="x", padx=6, pady=6)

    left = ttk.Frame(top)
    left.pack(side="left", fill="both", expand=True)

    info_lbl = ttk.Label(left,
                          text="Отметьте 1-4 модели галочками, потом нажмите «Запустить тест»",
                          foreground=ui_theme.YELLOW)
    info_lbl.pack(anchor="w")

    scroll_wrap = ttk.Frame(left)
    scroll_wrap.pack(fill="both", expand=True, pady=4)

    canvas = tk.Canvas(scroll_wrap, bg=ui_theme.BG_INPUT,
                        highlightthickness=0, height=130)
    scrollbar = ttk.Scrollbar(scroll_wrap, orient="vertical",
                                command=canvas.yview)
    inner = tk.Frame(canvas, bg=ui_theme.BG_INPUT)

    inner.bind("<Configure>",
               lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    # Список (имя → BooleanVar)
    check_vars = {}

    def _get_checked():
        """Возвращает список выбранных имён (читает галочки напрямую)."""
        return [name for name, var in check_vars.items() if var.get()]

    def _on_check():
        checked = _get_checked()
        n = len(checked)
        if n == 0:
            info_lbl.config(
                text="Ничего не выбрано. Отметьте 1-4 модели галочками.",
                foreground=ui_theme.YELLOW)
        elif n > 4:
            info_lbl.config(
                text=f"Слишком много ({n}). Снимите лишние галочки.",
                foreground=ui_theme.RED)
        else:
            names = ", ".join(checked)
            info_lbl.config(
                text=f"Выбрано ({n}): {names[:100]}",
                foreground=ui_theme.GREEN)

    def _refresh_models():
        # Очищаем
        for w in inner.winfo_children():
            w.destroy()
        check_vars.clear()

        try:
            models = app.router.list_chat_models()
            if not models:
                tk.Label(inner, text="Нет доступных моделей",
                         bg=ui_theme.BG_INPUT, fg=ui_theme.RED,
                         font=("Consolas", 10)).pack(anchor="w", padx=4, pady=4)
            else:
                # Проверяем объём VRAM чтобы помечать "тяжёлые"
                total_vram = 8192
                try:
                    from sapphira.features.system_info import get_system_report
                    total_vram = get_system_report().get("vram_mb", 8192)
                except Exception:
                    pass

                for m in models:
                    v = tk.BooleanVar(master=app.root, value=False)
                    check_vars[m] = v
                    # Определяем примерный размер по имени
                    est_gb = 4.5
                    import re as _re
                    match = _re.search(r"(\d+(?:\.\d+)?)\s*[bB]", m)
                    if match:
                        est_gb = float(match.group(1)) * 0.65 + 0.3
                    heavy = (est_gb * 1024 + 800) > total_vram

                    label = m + ("   ⚠ велика для 8 ГБ VRAM" if heavy else "")
                    cb = tk.Checkbutton(
                        inner, text=label, variable=v,
                        bg=ui_theme.BG_INPUT,
                        fg=ui_theme.RED if heavy else ui_theme.FG_TEXT,
                        activebackground=ui_theme.BG_INPUT,
                        activeforeground=ui_theme.FG_TEXT,
                        selectcolor=ui_theme.BG_PANEL,
                        anchor="w", font=("Consolas", 10),
                        command=_on_check,
                    )
                    cb.pack(fill="x", padx=4, pady=1)
        except Exception as e:
            tk.Label(inner, text=f"Ошибка: {e}",
                     bg=ui_theme.BG_INPUT, fg=ui_theme.RED).pack()

        _on_check()

    # ─── Кнопки справа ───
    right = ttk.Frame(top)
    right.pack(side="right", padx=10, fill="y")

    btn_run = ttk.Button(right, text="▶ Запустить тест",
                          style="Accent.TButton")
    btn_run.pack(fill="x", pady=2)

    btn_stop = ttk.Button(right, text="⏹ Стоп", state="disabled")
    btn_stop.pack(fill="x", pady=2)

    btn_export = ttk.Button(right, text="💾 Экспорт CSV", state="disabled")
    btn_export.pack(fill="x", pady=2)

    ttk.Button(right, text="🗑 Очистить",
               command=lambda: _clear_results()).pack(fill="x", pady=2)
    ttk.Button(right, text="🔄 Обновить",
               command=_refresh_models).pack(fill="x", pady=2)

    # ─── Прогресс ───
    prog_frame = ttk.LabelFrame(f, text="  Прогресс  ", padding=6)
    prog_frame.pack(fill="x", padx=6, pady=(0, 4))

    status_lbl = ttk.Label(prog_frame, text="Готово",
                            foreground=ui_theme.FG_DIM)
    status_lbl.pack(anchor="w")

    progress = ttk.Progressbar(prog_frame, mode="determinate")
    progress.pack(fill="x", pady=4)

    step_lbl = ttk.Label(prog_frame, text="", foreground=ui_theme.BLUE)
    step_lbl.pack(anchor="w")

    # ─── Результаты ───
    res_frame = ttk.LabelFrame(f, text="  Результаты  ", padding=6)
    res_frame.pack(fill="both", expand=True, padx=6, pady=6)

    columns = ("model", "speed", "quality", "vram", "load", "score")
    tree = ttk.Treeview(res_frame, columns=columns, show="headings",
                        height=10)
    tree.heading("model", text="Модель")
    tree.heading("speed", text="Скорость, т/с")
    tree.heading("quality", text="Качество, /10")
    tree.heading("vram", text="VRAM, МБ")
    tree.heading("load", text="Загрузка, с")
    tree.heading("score", text="Балл")
    tree.column("model", width=280, anchor="w")
    tree.column("speed", width=100, anchor="center")
    tree.column("quality", width=100, anchor="center")
    tree.column("vram", width=90, anchor="center")
    tree.column("load", width=100, anchor="center")
    tree.column("score", width=80, anchor="center")
    tree.pack(fill="both", expand=True)

    # ─── Функции ───
    def _clear_results():
        tree.delete(*tree.get_children())
        state["results"] = []
        btn_export.config(state="disabled")
        progress["value"] = 0
        status_lbl.config(text="Готово", foreground=ui_theme.FG_DIM)
        step_lbl.config(text="")

    def _run():
        # СБРОС застрявшего флага — без вопросов
        state["running"] = False
        state["stop"] = False

        checked = _get_checked()
        app.write(f"\n[bench] Нажата кнопка. Выбрано моделей: {len(checked)}\n", "info")
        for m in checked:
            app.write(f"[bench]   • {m}\n", "info")

        if not checked:
            messagebox.showwarning("Пусто", "Отметьте галочкой 1-4 модели")
            return
        if len(checked) > 4:
            messagebox.showwarning("Много",
                                    f"Выбрано {len(checked)}. Максимум 4.")
            return

        selected = sorted(checked)

        state["running"] = True
        state["started_at"] = time.time()
        state["results"] = []
        btn_run.config(state="disabled")
        btn_stop.config(state="normal")
        btn_export.config(state="disabled")
        tree.delete(*tree.get_children())

        app.write(f"[bench] Старт: {', '.join(selected)}\n", "info")

        def worker():
            try:
                from sapphira.features.benchmark import run_benchmark
                total_models = len(selected)
                for mi, model in enumerate(selected, 1):
                    if state["stop"]:
                        break
                    app.root.after(0, lambda m=model, i=mi, t=total_models:
                                    status_lbl.config(
                                        text=f"[{i}/{t}] {m}",
                                        foreground=ui_theme.BLUE))
                    app.write(f"\n[bench] Модель {mi}/{total_models}: {model}\n", "info")

                    def _prog(i, tot, name):
                        pct = int(100 * (i / max(tot, 1)))
                        app.root.after(0, lambda:
                                        step_lbl.config(
                                            text=f"  Тест {i+1}/{tot}: {name}"))
                        app.root.after(0, lambda p=pct:
                                        progress.configure(value=p))

                    def _log(text, level="info"):
                        tag = "err" if level == "err" else (
                            "ok" if level == "ok" else "info")
                        app.write(f"[bench] {text}\n", tag)

                    r = run_benchmark(
                        model,
                        router=app.router,
                        progress_cb=_prog,
                        log_cb=_log,
                        stop_flag=lambda: state["stop"],
                    )
                    if r.get("tests"):
                        state["results"].append(r)
                        app.root.after(0, lambda rr=r: _add_result(rr))

                    pct_model = int(100 * mi / total_models)
                    app.root.after(0, lambda p=pct_model:
                                    progress.configure(value=p))
            except Exception as e:
                app.write(f"[bench] ОШИБКА: {e}\n", "err")
                import traceback
                app.write(traceback.format_exc() + "\n", "err")
            finally:
                state["running"] = False
                app.root.after(0, _on_finish)

        threading.Thread(target=worker, daemon=True).start()

    def _stop():
        state["stop"] = True
        status_lbl.config(text="Останавливаю...", foreground=ui_theme.YELLOW)

    def _on_finish():
        state["running"] = False
        btn_run.config(state="normal")
        btn_stop.config(state="disabled")
        if state["results"]:
            btn_export.config(state="normal")
        if state["stop"]:
            status_lbl.config(text="Остановлено", foreground=ui_theme.YELLOW)
        else:
            n = len(state["results"])
            status_lbl.config(text=f"Готово ({n} моделей)",
                               foreground=ui_theme.GREEN)
            progress["value"] = 100
        step_lbl.config(text="")

    def _add_result(r):
        tree.insert("", "end", values=(
            r.get("model", ""),
            r.get("speed_avg", 0),
            r.get("quality_avg", 0),
            r.get("vram_peak_mb", 0),
            r.get("load_time", 0),
            r.get("final_score", 0),
        ))

    def _export():
        if not state["results"]:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile="benchmark_results.csv",
            filetypes=[("CSV", "*.csv"), ("Все", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as fp:
                w = csv.writer(fp, delimiter=";")
                w.writerow(["Модель", "Скорость т/с", "Качество /10",
                             "VRAM МБ", "Загрузка с", "Итоговый балл"])
                for r in state["results"]:
                    w.writerow([
                        r.get("model", ""),
                        r.get("speed_avg", 0),
                        r.get("quality_avg", 0),
                        r.get("vram_peak_mb", 0),
                        r.get("load_time", 0),
                        r.get("final_score", 0),
                    ])
                w.writerow([])
                w.writerow(["=== Детали ==="])
                for r in state["results"]:
                    w.writerow([])
                    w.writerow([r.get("model", "")])
                    w.writerow(["Тест", "Балл", "Время с",
                                 "Ток/с", "Комментарий"])
                    for t in r.get("tests", []):
                        w.writerow([t.get("name", ""), t.get("score", 0),
                                     t.get("time", 0), t.get("tps", 0),
                                     t.get("comment", "")])
            app.write(f"[bench] Экспорт: {path}\n", "ok")
            messagebox.showinfo("OK", f"Сохранено:\n{path}")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    btn_run.config(command=_run)
    btn_stop.config(command=_stop)
    btn_export.config(command=_export)

    app.root.after(300, _refresh_models)

    return f