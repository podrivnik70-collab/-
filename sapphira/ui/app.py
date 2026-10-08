# -*- coding: utf-8 -*-
"""Главное окно Sapphira v2.

Верх: профиль + 4 модели (Планировщик/Кодер/Мл/Ст) + раунды + чанки
Опции: чекбоксы + пресеты + API + Кэш + База + Компоненты
Индикаторы: цветные ● для активного агента + мониторинг ресурсов
Задача: textarea + кнопки запуска
Панель: Notebook (Файлы/Модели/Логи/Документы/Очередь) + Чат
Низ: рабочая папка, прогресс, статус, API
"""

import os
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

from sapphira import config
from sapphira.ui import theme as ui_theme
from sapphira.ui.tooltip import Tooltip
from sapphira.core.router import get_router
from sapphira.agents.orchestrator import Orchestrator
from sapphira.agents import prompts
from sapphira.project.history import TaskHistory
from sapphira.project.queue import TaskQueue
from sapphira.project import integrity
from sapphira.features import documents
from sapphira.features.knowledge import KnowledgeBase
from sapphira.features.system_info import get_system_report
from sapphira.models import manager as model_manager
from sapphira.models import catalog as model_catalog
from sapphira.utils.log_writer import write as log_write

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


class SapphiraApp:
    def __init__(self, root):
        self.root = root
        self.root.title("💎 Sapphira")
        self.root.geometry("1500x980")

        ui_theme.apply(self.root)

        self.router = get_router()
        self.history = TaskHistory()
        self.queue = TaskQueue()
        self.kb = KnowledgeBase()
        self.orch = None
        self.orch_thread = None
        self.stop_flag = False

        self.chat_history = []
        self.loaded_documents = []

        self._build_ui()
        self._attach_tooltips()
        # ВАЖНО: сначала модели, потом settings поверх
        self._refresh_models()
        self._refresh_installed()
        self._load_settings()
        self._show_catalog()
        self.root.after(500, self._monitor)
        self.root.after(1000, self._refresh_sys_info)

    # ============================================================
    # ВЕРХНЯЯ ПАНЕЛЬ
    # ============================================================
    def _build_ui(self):
        self._build_top()
        self._build_task_area()
        self._build_main()
        self._build_bottom()

    def _build_top(self):
        top = ttk.Frame(self.root, padding=(8, 6))
        top.pack(fill="x", padx=8, pady=(6, 2))

        # --- Строка 1: профиль + 4 модели ---
        r1 = ttk.Frame(top)
        r1.pack(fill="x")

        ttk.Label(r1, text="Тип задачи:").pack(side="left", padx=(0, 4))
        self.profile_combo = ttk.Combobox(
            r1, width=22, state="readonly",
            values=[v["label"] for k, v in prompts.PROFILES.items()])
        self.profile_combo.set(prompts.PROFILES["code"]["label"])
        self.profile_combo.pack(side="left", padx=(0, 14))
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_change)

        ttk.Label(r1, text="Планирование:").pack(side="left", padx=(0, 4))
        self.planner_combo = ttk.Combobox(r1, width=26, state="readonly")
        self.planner_combo.pack(side="left", padx=(0, 10))
        self.planner_combo.bind("<<ComboboxSelected>>", lambda e: self._save_settings())

        ttk.Label(r1, text="Написание кода:").pack(side="left", padx=(0, 4))
        self.coder_combo = ttk.Combobox(r1, width=26, state="readonly")
        self.coder_combo.pack(side="left", padx=(0, 10))
        self.coder_combo.bind("<<ComboboxSelected>>", lambda e: self._save_settings())

        # --- Строка 2: судьи + раунды + чанки ---
        r2 = ttk.Frame(top)
        r2.pack(fill="x", pady=(4, 0))

        ttk.Label(r2, text="⚖ Быстрый судья:",
                  foreground=ui_theme.TEAL).pack(side="left", padx=(0, 4))
        self.judge_junior_combo = ttk.Combobox(r2, width=26, state="readonly")
        self.judge_junior_combo.pack(side="left", padx=(0, 10))
        self.judge_junior_combo.bind("<<ComboboxSelected>>", lambda e: self._save_settings())

        ttk.Label(r2, text="⚖⚖ Строгий судья:",
                  foreground=ui_theme.PURPLE).pack(side="left", padx=(0, 4))
        self.judge_senior_combo = ttk.Combobox(r2, width=26, state="readonly")
        self.judge_senior_combo.pack(side="left", padx=(0, 10))
        self.judge_senior_combo.bind("<<ComboboxSelected>>", lambda e: self._save_settings())

        ttk.Label(r2, text="Попыток на файл:").pack(side="left", padx=(10, 4))
        self.attempts_var = tk.StringVar(value="3")
        ttk.Entry(r2, textvariable=self.attempts_var, width=4).pack(side="left", padx=(0, 10))

        ttk.Label(r2, text="Частей для длинных файлов:").pack(side="left", padx=(0, 4))
        self.chunks_var = tk.StringVar(value="5")
        ttk.Entry(r2, textvariable=self.chunks_var, width=4).pack(side="left", padx=(0, 10))

        # --- Строка 3: чекбоксы + пресеты + сервис ---
        r3 = ttk.Frame(top)
        r3.pack(fill="x", pady=(6, 0))

        self.validate_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="Проверять синтаксис", variable=self.validate_var).pack(side="left", padx=2)
        self.chunking_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="✂ Писать по частям", variable=self.chunking_var).pack(side="left", padx=2)
        self.autotest_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(r3, text="🧪 Создавать тесты", variable=self.autotest_var).pack(side="left", padx=2)
        self.autoreadme_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="📖 Создавать README", variable=self.autoreadme_var).pack(side="left", padx=2)
        self.rag_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="🧠 Искать в проекте", variable=self.rag_var).pack(side="left", padx=2)
        self.task_web_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(r3, text="🌐 Искать в интернете", variable=self.task_web_var).pack(side="left", padx=2)
        self.auto_model_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(r3, text="⚙ Авто-подбор", variable=self.auto_model_var).pack(side="left", padx=2)

        ttk.Separator(r3, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Button(r3, text="⚡ Быстро",
                   command=lambda: self._apply_preset("fast")).pack(side="left", padx=2)
        ttk.Button(r3, text="⚖ Баланс",
                   command=lambda: self._apply_preset("balance")).pack(side="left", padx=2)
        ttk.Button(r3, text="☁ Облако",
                   command=lambda: self._apply_preset("cloud")).pack(side="left", padx=2)

        ttk.Separator(r3, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Button(r3, text="⚙ API", style="Cloud.TButton",
                   command=self._open_api_settings).pack(side="left", padx=2)
        ttk.Button(r3, text="🗑 Кэш",
                   command=self._clear_cache).pack(side="left", padx=2)
        ttk.Button(r3, text="🧠 База",
                   command=self._show_kb).pack(side="left", padx=2)
        ttk.Button(r3, text="🔄 Модели",
                   command=self._refresh_models).pack(side="left", padx=2)

    def _attach_tooltips(self):
        """Tooltips для непонятных элементов UI."""
        def _tp(widget, text):
            try:
                if widget is not None:
                    Tooltip(widget, text)
            except Exception:
                pass

        # Tooltips на чекбоксы (у них есть StringVar/BooleanVar)
        # Найти сами виджеты сложно, поэтому ставим на переменные через
        # интроспекцию — только если атрибут существует.
        for attr_name, tip in [
            ("validate_var",   "Проверять синтаксис Python автоматически"),
            ("chunking_var",   "Разбивать длинные файлы на части"),
            ("autotest_var",   "Генерировать pytest-тесты"),
            ("autoreadme_var", "Создавать README.md в конце проекта"),
            ("rag_var",        "Искать похожий код в проекте как подсказку"),
            ("task_web_var",   "Искать информацию в интернете"),
        ]:
            try:
                var = getattr(self, attr_name, None)
                widget = getattr(var, "_tk", None) or getattr(var, "widget", None) if var else None
                # Не можем достать виджет из BooleanVar напрямую — пропускаем
            except Exception:
                pass

    def _build_task_area(self):
        frame = ttk.LabelFrame(self.root, text="  📝 Задача  ", padding=(8, 6))
        frame.pack(fill="x", padx=8, pady=(6, 4))

        # Индикаторы агентов слева
        ind = ttk.Frame(frame)
        ind.pack(side="left", padx=(0, 10))

        ttk.Label(ind, text="Агенты:", foreground=ui_theme.FG_DIM,
                  font=("Segoe UI", 8)).pack(anchor="w")

        self.indicators = {}
        for key, label, color in [
            ("planner", "● План", ui_theme.YELLOW),
            ("coder", "● Код", ui_theme.BLUE),
            ("junior", "● Мл", ui_theme.TEAL),
            ("senior", "● Ст", ui_theme.PURPLE),
            ("chunk", "● Чанк", ui_theme.YELLOW),
        ]:
            lbl = tk.Label(ind, text=label, fg="#3a3a3a", bg=ui_theme.BG_PANEL,
                           font=("Segoe UI", 9, "bold"))
            lbl.pack(anchor="w")
            self.indicators[key] = (lbl, color)

        # Textarea задачи
        self.task_text = tk.Text(frame, height=4, wrap="word",
                                 bg=ui_theme.BG_INPUT, fg=ui_theme.FG_TEXT,
                                 insertbackground=ui_theme.FG_TEXT,
                                 relief="flat", borderwidth=0,
                                 font=("Consolas", 10))
        self.task_text.pack(side="left", fill="both", expand=True)
        ui_theme.add_paste_support(self.root, self.task_text)
        self.task_text.insert("1.0",
                              "Создай файл hello.py с print('Привет, мир!')")

        # Кнопки справа
        btns = ttk.Frame(frame)
        btns.pack(side="right", padx=(10, 0))

        self.btn_run = ttk.Button(btns, text="▶ Запустить задачу",
                                   style="Accent.TButton", command=self._run_task)
        self.btn_run.pack(fill="x", pady=2)
        ttk.Button(btns, text="➕ В очередь",
                   command=self._add_to_queue).pack(fill="x", pady=2)
        ttk.Button(btns, text="▶▶ Запустить очередь",
                   style="Cloud.TButton",
                   command=self._run_queue).pack(fill="x", pady=2)
        self.btn_stop = ttk.Button(btns, text="■ Стоп",
                                    command=self._stop, state="disabled")
        self.btn_stop.pack(fill="x", pady=2)

    def _build_main(self):
        paned = ttk.PanedWindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=4)
        self.paned = paned

        # --- Левая часть: Notebook ---
        left = ttk.Frame(paned)
        paned.add(left, weight=3)

        nb = ttk.Notebook(left)
        nb.pack(fill="both", expand=True)

        self._build_files_tab(nb)
        self._build_models_tab(nb)
        self._build_logs_tab(nb)
        self._build_docs_tab(nb)
        self._build_queue_tab(nb)

        # Вкладка Идеи
        try:
            from sapphira.ui.tabs import ideas as ideas_tab
            nb.add(ideas_tab.build(nb, self), text="Идеи")
        except Exception as e:
            print(f"[ui] ideas tab: {e}")

        # Вкладка Тест моделей
        try:
            from sapphira.ui.tabs import benchmark_tab
            nb.add(benchmark_tab.build(nb, self), text="Тест моделей")
        except Exception as e:
            print(f"[ui] benchmark tab: {e}")


        right = ttk.Frame(paned, width=460)
        paned.add(right, weight=1)
        self._build_chat(right)

        self.root.after(250, lambda: paned.sashpos(0, 1010))

    def _build_files_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="📁 Файлы")

        paned = ttk.PanedWindow(f, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned)
        paned.add(left, weight=1)
        ttk.Label(left, text="Дерево проекта:",
                  foreground=ui_theme.BLUE).pack(anchor="w", padx=4, pady=2)
        self.tree = ttk.Treeview(left, show="tree")
        self.tree.pack(fill="both", expand=True, padx=4)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        ttk.Button(left, text="🔄 Обновить",
                   command=self._refresh_tree).pack(fill="x", padx=4, pady=2)
        ttk.Button(left, text="💾 Сохранить",
                   command=self._save_file).pack(fill="x", padx=4, pady=2)
        ttk.Button(left, text="▶ Запустить",
                   command=self._run_file).pack(fill="x", padx=4, pady=2)

        right = ttk.Frame(paned)
        paned.add(right, weight=3)
        self.edit_label = ttk.Label(right, text="(выбери файл)",
                                    foreground=ui_theme.FG_DIM)
        self.edit_label.pack(anchor="w", padx=4, pady=2)
        self.editor = scrolledtext.ScrolledText(
            right, wrap="word", font=("Consolas", 10),
            bg=ui_theme.BG_MAIN, fg=ui_theme.FG_TEXT,
            insertbackground=ui_theme.FG_TEXT,
            relief="flat", borderwidth=0)
        self.editor.pack(fill="both", expand=True, padx=4, pady=4)
        ui_theme.add_paste_support(self.root, self.editor)

        self.current_edit_file = None
        self.root.after(300, self._refresh_tree)

    def _build_models_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="🤖 Модели")

        # Инфо о системе
        sys_frame = ttk.LabelFrame(f, text="  💻 Система  ", padding=8)
        sys_frame.pack(fill="x", padx=6, pady=6)
        self.sys_label = tk.Label(sys_frame, text="...", justify="left",
                                  anchor="w", bg=ui_theme.BG_PANEL,
                                  fg=ui_theme.FG_TEXT,
                                  font=("Consolas", 9))
        self.sys_label.pack(fill="x")

        # Внутренний Notebook: Установленные / Каталог
        inner = ttk.Notebook(f)
        inner.pack(fill="both", expand=True, padx=6, pady=6)

        # --- Установленные ---
        inst_tab = ttk.Frame(inner)
        inner.add(inst_tab, text="✅ Установленные")
        self.inst_list = tk.Listbox(inst_tab, bg=ui_theme.BG_INPUT,
                                     fg=ui_theme.FG_TEXT,
                                     font=("Consolas", 9),
                                     selectbackground=ui_theme.ACCENT,
                                     relief="flat")
        self.inst_list.pack(fill="both", expand=True, padx=4, pady=4)
        b1 = ttk.Frame(inst_tab)
        b1.pack(fill="x", padx=4, pady=2)
        ttk.Button(b1, text="🔄 Обновить",
                   command=self._refresh_installed).pack(side="left", padx=2)
        ttk.Button(b1, text="🗑 Удалить",
                   command=self._delete_selected_model).pack(side="left", padx=2)
        ttk.Button(b1, text="📥 Импорт из Ollama",
                   command=self._import_from_ollama).pack(side="left", padx=8)

        # --- Каталог ---
        cat_tab = ttk.Frame(inner)
        inner.add(cat_tab, text="📦 Каталог")
        self.cat_list = tk.Listbox(cat_tab, bg=ui_theme.BG_INPUT,
                                    fg=ui_theme.FG_TEXT,
                                    font=("Consolas", 9),
                                    selectbackground=ui_theme.ACCENT,
                                    relief="flat")
        self.cat_list.pack(fill="both", expand=True, padx=4, pady=4)
        b2 = ttk.Frame(cat_tab)
        b2.pack(fill="x", padx=4, pady=2)
        ttk.Button(b2, text="🔄 Обновить с HF",
                   command=self._refresh_catalog).pack(side="left", padx=2)
        ttk.Button(b2, text="📥 Скачать",
                   style="Accent.TButton",
                   command=self._download_selected).pack(side="left", padx=2)

        # Прогресс загрузки
        prog = ttk.LabelFrame(f, text="  📥 Прогресс  ", padding=8)
        prog.pack(fill="x", padx=6, pady=(0, 6))
        self.model_prog_label = ttk.Label(prog, text="Ожидание...",
                                           foreground=ui_theme.FG_DIM)
        self.model_prog_label.pack(anchor="w")
        self.model_progress = ttk.Progressbar(prog, mode="determinate")
        self.model_progress.pack(fill="x", pady=4)

    def _build_logs_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="📋 Логи")

        bar = ttk.Frame(f)
        bar.pack(fill="x", padx=4, pady=2)
        ttk.Label(bar, text="Поиск:").pack(side="left")
        self.log_search = ttk.Entry(bar, width=30)
        self.log_search.pack(side="left", padx=4)
        ttk.Button(bar, text="🔍",
                   command=self._search_logs).pack(side="left", padx=2)
        ttk.Button(bar, text="Сброс",
                   command=self._reset_log_search).pack(side="left", padx=2)
        ttk.Button(bar, text="🗑 Очистить",
                   command=lambda: self.log.delete("1.0", "end")).pack(side="left", padx=8)

        self.log = scrolledtext.ScrolledText(
            f, wrap="word", font=("Consolas", 9),
            bg=ui_theme.BG_MAIN, fg=ui_theme.FG_TEXT,
            insertbackground=ui_theme.FG_TEXT,
            relief="flat", borderwidth=0)
        self.log.pack(fill="both", expand=True, padx=4, pady=4)
        for tag, color in [
            ("ok", ui_theme.GREEN), ("err", ui_theme.RED),
            ("info", ui_theme.BLUE), ("warn", ui_theme.YELLOW),
            ("cycle", ui_theme.PURPLE), ("junior", ui_theme.TEAL),
            ("senior", ui_theme.PURPLE), ("cloud", ui_theme.PURPLE),
            ("find", "#ffd700"),
        ]:
            self.log.tag_config(tag, foreground=color)
        ui_theme.add_paste_support(self.root, self.log)

    def _build_docs_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="📄 Документы")

        bar = ttk.Frame(f)
        bar.pack(fill="x", padx=4, pady=4)
        ttk.Button(bar, text="➕ Добавить",
                   command=self._add_doc).pack(side="left", padx=2)
        ttk.Button(bar, text="🗑 Очистить",
                   command=self._clear_docs).pack(side="left", padx=2)
        ttk.Label(bar, text="(PDF, DOCX, CSV, XLSX, JSON, TXT)",
                  foreground=ui_theme.FG_DIM).pack(side="left", padx=10)

        self.docs_list = tk.Listbox(f, bg=ui_theme.BG_INPUT,
                                     fg=ui_theme.FG_TEXT,
                                     font=("Consolas", 9),
                                     selectbackground=ui_theme.ACCENT,
                                     relief="flat")
        self.docs_list.pack(fill="both", expand=True, padx=4, pady=4)
        self.docs_list.bind("<<ListboxSelect>>", self._on_doc_select)

        ttk.Label(f, text="Превью:", foreground=ui_theme.BLUE).pack(anchor="w", padx=4)
        self.doc_preview = scrolledtext.ScrolledText(
            f, wrap="word", font=("Consolas", 9),
            bg=ui_theme.BG_MAIN, fg=ui_theme.FG_TEXT,
            height=10, relief="flat", borderwidth=0)
        self.doc_preview.pack(fill="both", expand=True, padx=4, pady=4)

    def _build_queue_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="📋 Очередь")

        bar = ttk.Frame(f)
        bar.pack(fill="x", padx=4, pady=4)
        ttk.Button(bar, text="🔄 Обновить",
                   command=self._refresh_queue).pack(side="left", padx=2)
        ttk.Button(bar, text="🧹 Готовые",
                   command=self._clear_done_queue).pack(side="left", padx=2)

        self.queue_text = scrolledtext.ScrolledText(
            f, wrap="word", font=("Consolas", 10),
            bg=ui_theme.BG_MAIN, fg=ui_theme.FG_TEXT,
            relief="flat", borderwidth=0)
        self.queue_text.pack(fill="both", expand=True, padx=4, pady=4)

    def _build_chat(self, parent):
        h = ttk.Frame(parent, padding=(8, 6))
        h.pack(fill="x")
        ttk.Label(h, text="💬 Чат с AI",
                  font=("Segoe UI", 11, "bold"),
                  foreground=ui_theme.BLUE).pack(side="left")
        ttk.Button(h, text="🗑", width=3,
                   command=self._clear_chat).pack(side="right")

        mf = ttk.Frame(parent, padding=(8, 4))
        mf.pack(fill="x")
        ttk.Label(mf, text="Модель:").pack(side="left")
        self.chat_model_combo = ttk.Combobox(mf, state="readonly")
        self.chat_model_combo.pack(side="left", fill="x", expand=True, padx=4)
        self.chat_model_combo.bind("<<ComboboxSelected>>", lambda e: self._save_settings())

        copt = ttk.Frame(parent, padding=(8, 2))
        copt.pack(fill="x")
        self.chat_rag_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(copt, text="🧠 Искать в проекте", variable=self.chat_rag_var).pack(side="left", padx=2)
        self.chat_web_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(copt, text="🌐 Искать в интернете", variable=self.chat_web_var).pack(side="left", padx=2)

        self.chat_display = scrolledtext.ScrolledText(
            parent, wrap="word", font=("Consolas", 10),
            bg=ui_theme.BG_MAIN, fg=ui_theme.FG_TEXT,
            insertbackground=ui_theme.FG_TEXT,
            relief="flat", borderwidth=0)
        for tag, color in [("user", ui_theme.BLUE),
                           ("ai", ui_theme.GREEN),
                           ("cloud", ui_theme.PURPLE),
                           ("err", ui_theme.RED),
                           ("sys", ui_theme.FG_DIM)]:
            self.chat_display.tag_config(tag, foreground=color)
        self.chat_display.pack(fill="both", expand=True, padx=8, pady=4)
        ui_theme.add_paste_support(self.root, self.chat_display)

        inp = ttk.Frame(parent, padding=(8, 4))
        inp.pack(fill="x")
        self.chat_input = tk.Text(inp, height=3, wrap="word",
                                   bg=ui_theme.BG_INPUT, fg=ui_theme.FG_TEXT,
                                   insertbackground=ui_theme.FG_TEXT,
                                   relief="flat", borderwidth=0,
                                   font=("Consolas", 10))
        self.chat_input.pack(fill="x")
        ui_theme.add_paste_support(self.root, self.chat_input)
        self.chat_input.bind("<Return>", self._on_chat_enter)

        b = ttk.Frame(parent, padding=(8, 4))
        b.pack(fill="x")
        ttk.Button(b, text="▶ Отправить", style="Accent.TButton",
                   command=self._send_chat).pack(side="left", fill="x",
                                                  expand=True, padx=2)
        ttk.Button(b, text="🚀 Как задачу", style="Green.TButton",
                   command=self._chat_as_task).pack(side="left", padx=2)

    def _build_bottom(self):
        b = ttk.Frame(self.root, padding=(8, 4))
        b.pack(fill="x", padx=8, pady=(2, 6))

        # --- Рабочая папка ---
        row1 = ttk.Frame(b)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="Рабочая папка:").pack(side="left")
        self.ws_entry = ttk.Entry(row1)
        self.ws_entry.insert(0, config.WORKSPACE_DIR)
        self.ws_entry.pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row1, text="Выбрать...",
                   command=self._choose_workspace).pack(side="left", padx=2)
        ttk.Button(row1, text="📂",
                   command=self._open_workspace).pack(side="left", padx=2)
        ttk.Button(row1, text="📊",
                   command=self._show_status).pack(side="left", padx=2)
        ttk.Button(row1, text="📦",
                   command=self._export_zip).pack(side="left", padx=2)

        # --- Прогресс + статус + мониторинг ---
        row2 = ttk.Frame(b)
        row2.pack(fill="x", pady=(4, 0))

        self.progress = ttk.Progressbar(row2, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.status_label = ttk.Label(row2, text="Готово",
                                       foreground=ui_theme.GREEN)
        self.status_label.pack(side="left", padx=6)

        self.api_label = ttk.Label(row2, text="API: не настроен",
                                    foreground=ui_theme.FG_DIM)
        self.api_label.pack(side="right", padx=6)

        self.monitor_label = ttk.Label(row2, text="",
                                        foreground=ui_theme.FG_DIM)
        self.monitor_label.pack(side="right", padx=6)

        self.kb_label = ttk.Label(row2, text="",
                                   foreground=ui_theme.FG_DIM)
        self.kb_label.pack(side="right", padx=6)

        self.gpu_label = ttk.Label(row2, text="",
                                    foreground=ui_theme.FG_DIM)
        self.gpu_label.pack(side="right", padx=6)

    # ============================================================
    # ЛОГИРОВАНИЕ / UI-ХЕЛПЕРЫ
    # ============================================================
    def write(self, text, tag=None):
        def _do():
            if tag:
                self.log.insert("end", text, tag)
            else:
                self.log.insert("end", text)
            self.log.see("end")
        self.root.after(0, _do)
        log_write(text)

    def set_status(self, text, color=ui_theme.YELLOW):
        self.root.after(0, lambda: self.status_label.config(
            text=text, foreground=color))

    def set_progress(self, value, maximum=100):
        def _do():
            self.progress["maximum"] = maximum
            self.progress["value"] = value
        self.root.after(0, _do)

    def _highlight_agent(self, name):
        for key, (lbl, color) in self.indicators.items():
            lbl.config(fg="#3a3a3a")
        if name and name in self.indicators:
            self.indicators[name][0].config(fg=self.indicators[name][1])

    def _highlight_async(self, name):
        self.root.after(0, self._highlight_agent, name)

    # ============================================================
    # ПРЕСЕТЫ / ПРОФИЛЬ
    # ============================================================
    def _on_profile_change(self, e=None):
        self._save_settings()

    def _apply_preset(self, name):
        models = self.router.list_chat_models()
        if not models:
            messagebox.showwarning("Модели", "Нет установленных моделей")
            return

        if name == "fast":
            # Одна модель для всего
            m = models[0]
            self.planner_combo.set(m)
            self.coder_combo.set(m)
            self.judge_junior_combo.set(m)
            self.judge_senior_combo.set(m)
            self.attempts_var.set("2")
            self.chunks_var.set("3")
            self.chunking_var.set(False)

        elif name == "balance":
            # Планировщик + Кодер + один судья
            m = models[0]
            self.planner_combo.set(m)
            self.coder_combo.set(m)
            self.judge_junior_combo.set(m)
            self.judge_senior_combo.set(m)
            self.attempts_var.set("3")
            self.chunks_var.set("5")
            self.chunking_var.set(True)
            self.validate_var.set(True)

        elif name == "cloud":
            cloud = [m for m in models if m.startswith("cloud/")]
            if not cloud:
                if not self.router.cloud.has_key():
                    messagebox.showwarning("API", "Сначала настрой API-ключ")
                    return
                cloud = [m for m in self.router.list_all_models()
                         if m.startswith("cloud/")]
            if cloud:
                m = cloud[0]
                self.planner_combo.set(m)
                self.coder_combo.set(m)
                self.judge_junior_combo.set(m)
                self.judge_senior_combo.set(m)

        self.write(f"[+] Пресет: {name}\n", "ok")
        self._save_settings()

    # ============================================================
    # ЗАДАЧА
    # ============================================================
    def _maybe_show_advice(self, task, mode_info):
        """Диалог рекомендации моделей. True — продолжать, False — отменить."""
        if not self.auto_model_var.get():
            return True
        try:
            from sapphira.features.model_advisor import recommend, get_installed_models
            from sapphira.ui.dialogs import ModelAdviceDialog

            installed = get_installed_models()
            rec = recommend(task, mode=mode_info["mode"],
                            root_path=mode_info.get("path"),
                            installed_models=installed)

            a = rec["analysis"]
            type_key = f"{a['mode']}+{a['action']}"
            skip_types = config.Config.get("settings", "skip_model_advice_types") or []

            if type_key in skip_types:
                return True

            dlg = ModelAdviceDialog(self.root, rec, on_download=self._download_recommended)
            result, skip_checked = dlg.show()

            # Если пользователь выбрал "ждать" — модели уже скачались,
            # пересчитываем рекомендации
            if getattr(dlg, "wait_download", False):
                try:
                    installed = get_installed_models()
                    rec = recommend(task, mode=mode_info["mode"],
                                    root_path=mode_info.get("path"),
                                    installed_models=installed)
                    m = rec["models"]
                    self.planner_combo.set(m["planner"]["name"])
                    self.coder_combo.set(m["coder"]["name"])
                    self.judge_junior_combo.set(m["judge_fast"]["name"])
                    self.judge_senior_combo.set(m["judge_strict"]["name"])
                    self.write(f"[auto-model] После скачивания — Кодер: {m['coder']['name']}\n", "ok")
                except Exception as _e:
                    print(f"[ui] recalc: {_e}")

            if result is None:
                return False

            if skip_checked and type_key not in skip_types:
                skip_types.append(type_key)
                config.Config.set("settings", "skip_model_advice_types", skip_types)

            if result == "apply":
                m = rec["models"]
                self.planner_combo.set(m["planner"]["name"])
                self.coder_combo.set(m["coder"]["name"])
                self.judge_junior_combo.set(m["judge_fast"]["name"])
                self.judge_senior_combo.set(m["judge_strict"]["name"])
                self.write(f"[auto-model] Кодер: {m['coder']['name']}\n", "ok")

            return True
        except Exception as e:
            import traceback
            self.write(f"[auto-model] Ошибка: {e}\n", "err")
            self.write(traceback.format_exc() + "\n", "err")
            return True

    def _download_recommended(self, model_name, wait=False):
        """Скачать рекомендованную модель по известному repo_id."""
        try:
            from sapphira.models import manager as model_manager
            from sapphira.features.model_advisor import get_repo_id

            repo_id = get_repo_id(model_name)

            # Если точного нет — пробуем найти в каталоге HF
            if not repo_id:
                self.write(f"[auto-download] Нет известного repo_id для {model_name}, ищу в каталоге HF...\n", "warn")
                try:
                    from sapphira.models import catalog as model_catalog
                    all_models = model_catalog.enrich_for_ui()
                    def _n(s):
                        s = s.lower()
                        for suf in ["-instruct", "_instruct", "-gguf", "_gguf", ".gguf"]:
                            s = s.replace(suf, "")
                        return s.replace("/", " ").replace(":", " ").replace(".", " ").strip()
                    target = _n(model_name)
                    for m in all_models:
                        nm = _n(m.get("name", ""))
                        if target and (target == nm or target in nm):
                            repo_id = m.get("repo_id", "")
                            break
                except Exception as e:
                    self.write(f"[auto-download] Ошибка поиска: {e}\n", "warn")

            if not repo_id:
                self.write(f"[auto-download] ✗ Модель {model_name} не найдена нигде\n", "err")
                self.write(f"[auto-download] Скачай вручную во вкладке «Модели» → Каталог\n", "warn")
                return

            self.write(f"[auto-download] repo_id = {repo_id}\n", "info")

            if wait:
                from sapphira.ui.dialogs import DownloadProgressDialog

                def dl(on_prog, on_done):
                    try:
                        model_manager.pull_model(
                            repo_id,
                            on_progress=on_prog,
                            on_done=on_done,
                        )
                    except Exception as e:
                        on_done(repo_id, False, str(e))

                self.write(f"[auto-download] Скачиваю {model_name} (с ожиданием)...\n", "info")
                dlg = DownloadProgressDialog(self.root, model_name, dl)
                ok = dlg.show()
                if ok:
                    self.write(f"[auto-download] ✅ {model_name} готова\n", "ok")
                    self._refresh_models()
                    self._refresh_installed()
                else:
                    self.write(f"[auto-download] ✗ Прервано\n", "warn")
            else:
                self.write(f"[auto-download] Скачиваю {model_name} в фоне...\n", "info")
                def worker():
                    try:
                        model_manager.pull_model(
                            repo_id,
                            on_progress=lambda rid, pct, txt:
                                self.set_progress(pct, 100) if pct >= 0 else None,
                            on_done=lambda rid, ok, err:
                                self.root.after(0, self._refresh_models) if ok else None,
                        )
                    except Exception as e:
                        self.write(f"[auto-download] {e}\n", "err")
                import threading
                threading.Thread(target=worker, daemon=True).start()
        except Exception as e:
            self.write(f"[auto-download] {e}\n", "err")


    def _run_task(self):
        task = self.task_text.get("1.0", "end").strip()

        # Определение режима: создать или улучшить
        try:
            from sapphira.agents.task_mode import detect_mode
            mode_info = detect_mode(task, default_workspace=self.ws_entry.get().strip())
        except Exception as e:
            print(f'[ui] task_mode: {e}')
            mode_info = {'mode': 'create', 'path': None, 'task_clean': task}

        if not self._maybe_show_advice(task, mode_info):
            return

        if mode_info['mode'] == 'edit':
            self._run_edit_task(mode_info['path'], mode_info['task_clean'])
            return
        if not task:
            messagebox.showwarning("Пусто", "Введи задачу")
            return

        planner = self.planner_combo.get()
        coder = self.coder_combo.get()
        junior = self.judge_junior_combo.get()
        senior = self.judge_senior_combo.get()

        if not all([planner, coder, junior, senior]):
            messagebox.showwarning("Модели", "Выбери все 4 модели")
            return

        profile_key = "code"
        for k, v in prompts.PROFILES.items():
            if v["label"] == self.profile_combo.get():
                profile_key = k
                break

        attempts = int(self.attempts_var.get() or 3)
        workspace = self.ws_entry.get().strip() or config.WORKSPACE_DIR

        self.log.delete("1.0", "end")
        self.set_status("Запускаю...", ui_theme.YELLOW)
        self.set_progress(0, 100)
        self.btn_run.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.stop_flag = False

        self.history.add(task, workspace=workspace, status="started")
        self.orch = Orchestrator(log_func=lambda m: self.write(m))

        def worker():
            try:
                result = self.orch.run_task(
                    task=task,
                    workspace=workspace,
                    profile_key=profile_key,
                    planner_model=planner,
                    coder_model=coder,
                    junior_model=junior,
                    senior_model=senior,
                    max_attempts=attempts,
                    use_chunking=self.chunking_var.get(),
                    make_readme=self.autoreadme_var.get(),
                )
                self.history.update_last(
                    "done" if result.fail_count() == 0 else "partial",
                    files=list(result.files.keys()),
                    duration=result.duration(),
                )
                for fn, info in result.files.items():
                    if info["status"] == "done":
                        self.kb.add_solution(task, fn, info["code"][:2000])
                probs = integrity.check_project(
                    workspace, expected_files=list(result.files.keys()))
                self.write(f"\n{integrity.format_report(probs)}\n",
                           "ok" if not probs else "warn")
                self.set_status(f"Готово за {result.duration()}с",
                                ui_theme.GREEN)
                self.root.after(0, self._refresh_tree)
            except Exception as e:
                self.write(f"\n[!] {e}\n", "err")
                self.history.update_last("error")
                self.set_status("Ошибка", ui_theme.RED)
            finally:
                self.root.after(0, lambda: self.set_progress(0, 100))
                self.root.after(0, lambda: self.btn_run.config(state="normal"))
                self.root.after(0, lambda: self.btn_stop.config(state="disabled"))

        self.orch_thread = threading.Thread(target=worker, daemon=True)
        self.orch_thread.start()

    def _run_edit_task(self, project_path, task_clean):
        """Режим улучшения существующего проекта."""
        import threading
        from sapphira.agents.project_editor import ProjectEditor

        coder = self.coder_combo.get()
        judge = self.judge_senior_combo.get() or self.judge_combo.get()

        if not coder:
            messagebox.showwarning("Модели", "Выбери Написание кода")
            return

        self.log.delete("1.0", "end")
        self.set_status("Анализирую проект...", ui_theme.YELLOW)
        self.set_progress(0, 100)
        self.btn_run.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.stop_flag = False

        self.write("Режим: улучшение существующего проекта\n", "info")
        self.write(f"Проект: {project_path}\n", "info")
        self.write(f"Задача: {task_clean}\n\n", "info")

        editor = ProjectEditor(
            router=self.router,
            coder_model=coder,
            judge_model=judge or coder,
            log_func=lambda m, tag=None: self.write(m + "\n", tag or "info"),
        )

        def worker():
            try:
                result = editor.run(project_path, task_clean)
                if result.get("ok"):
                    self.set_status(
                        f"Готово: {len(result[chr(39)+chr(99)+chr(104)+chr(97)+chr(110)+chr(103)+chr(101)+chr(100)+chr(39)]) if False else len(result.get(chr(99)+chr(104)+chr(97)+chr(110)+chr(103)+chr(101)+chr(100),[]))} файлов",
                        ui_theme.GREEN)
                else:
                    self.set_status("Ничего не изменилось", ui_theme.YELLOW)
            except Exception as e:
                self.write(f"\n[!] {e}\n", "err")
                self.set_status("Ошибка", ui_theme.RED)
            finally:
                self.root.after(0, lambda: self.btn_run.config(state="normal"))
                self.root.after(0, lambda: self.btn_stop.config(state="disabled"))
                self.root.after(0, self._refresh_tree)

        threading.Thread(target=worker, daemon=True).start()


    def _stop(self):
        self.stop_flag = True
        if self.orch:
            self.orch.cancel()
        self.set_status("Стоп", ui_theme.RED)

    def _add_to_queue(self):
        task = self.task_text.get("1.0", "end").strip()
        if not task:
            return
        self.queue.add(task, workspace=self.ws_entry.get().strip())
        self.write(f"[queue] +{task[:80]}\n", "ok")
        self._refresh_queue()

    def _run_queue(self):
        if not self.queue.data.get("tasks"):
            messagebox.showinfo("Очередь", "Пусто")
            return

        def worker():
            while not self.stop_flag:
                nxt = self.queue.next_task()
                if not nxt:
                    break
                self.queue.mark(nxt["task"], "running")
                self.root.after(0, self._refresh_queue)
                self.root.after(0, lambda t=nxt["task"]: (
                    self.task_text.delete("1.0", "end"),
                    self.task_text.insert("1.0", t),
                ))
                try:
                    self.orch = Orchestrator(log_func=lambda m: self.write(m))
                    self.orch.run_task(
                        task=nxt["task"],
                        workspace=self.ws_entry.get().strip(),
                        profile_key="code",
                        planner_model=self.planner_combo.get(),
                        coder_model=self.coder_combo.get(),
                        junior_model=self.judge_junior_combo.get(),
                        senior_model=self.judge_senior_combo.get(),
                        max_attempts=int(self.attempts_var.get() or 3),
                    )
                    self.queue.mark(nxt["task"], "done")
                except Exception as e:
                    self.write(f"[queue] ! {e}\n", "err")
                    self.queue.mark(nxt["task"], "failed")
                self.root.after(0, self._refresh_queue)

        threading.Thread(target=worker, daemon=True).start()

    # ============================================================
    # ЧАТ
    # ============================================================
    def _on_chat_enter(self, e):
        if e.state & 0x0001:
            return None
        self._send_chat()
        return "break"

    def _send_chat(self):
        text = self.chat_input.get("1.0", "end").strip()
        if not text:
            return
        model = self.chat_model_combo.get()
        if not model:
            messagebox.showwarning("Модель", "Выбери модель")
            return

        self.chat_display.insert("end", f"\n👤 Вы:\n{text}\n\n", "user")
        self.chat_display.see("end")
        self.chat_input.delete("1.0", "end")
        self.chat_history.append({"role": "user", "content": text})

        self.chat_display.insert("end", "💭 Печатаю...\n", "sys")
        self.chat_display.see("end")

        threading.Thread(target=self._chat_worker,
                         args=(model,), daemon=True).start()

    def _chat_worker(self, model):
        try:
            msgs = [{"role": m["role"], "content": m["content"]}
                    for m in self.chat_history]
            answer = self.router.chat_history(model, msgs,
                                               max_tokens=2048,
                                               temperature=0.5)
            self.chat_history.append({"role": "assistant", "content": answer})
            self.root.after(0, lambda: self._chat_show(answer, model))
        except Exception as e:
            self.root.after(0, lambda: self._chat_show(
                f"[Ошибка] {e}", model, True))

    def _chat_show(self, text, model, error=False):
        cur = self.chat_display.get("1.0", "end")
        idx = cur.rfind("💭 Печатаю...")
        if idx != -1:
            self.chat_display.delete(f"1.0 + {idx} chars",
                                      f"1.0 + {idx + 14} chars")
        tag = "err" if error else (
            "cloud" if model.startswith("cloud/") else "ai")
        self.chat_display.insert("end", f"🤖 Sapphira:\n{text}\n\n", tag)
        self.chat_display.see("end")

    def _clear_chat(self):
        self.chat_display.delete("1.0", "end")
        self.chat_history = []

    def _chat_as_task(self):
        for m in reversed(self.chat_history):
            if m["role"] == "user":
                self.task_text.delete("1.0", "end")
                self.task_text.insert("1.0", m["content"])
                return

    # ============================================================
    # ФАЙЛЫ
    # ============================================================
    def _refresh_tree(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        ws = self.ws_entry.get().strip()
        if not os.path.isdir(ws):
            return
        for root, dirs, files in os.walk(ws):
            dirs[:] = [d for d in dirs
                       if d not in ("backups", "__pycache__", ".git")]
            for f in sorted(files):
                if f.endswith((".py", ".md", ".txt", ".json")):
                    p = os.path.join(root, f)
                    self.tree.insert("", "end",
                                     text=os.path.relpath(p, ws),
                                     values=[p])

    def _on_tree_select(self, e=None):
        sel = self.tree.selection()
        if not sel:
            return
        p = self.tree.item(sel[0])["values"][0]
        if not os.path.exists(p):
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                content = f.read()
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", content)
            self.edit_label.config(text=p, foreground=ui_theme.BLUE)
            self.current_edit_file = p
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def _save_file(self):
        if not self.current_edit_file:
            return
        try:
            with open(self.current_edit_file, "w", encoding="utf-8") as f:
                f.write(self.editor.get("1.0", "end-1c"))
            self.write("[file] сохранён\n", "ok")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def _run_file(self):
        if not self.current_edit_file:
            return
        self._save_file()
        import subprocess
        try:
            r = subprocess.run(["python", self.current_edit_file],
                               capture_output=True, text=True, timeout=30,
                               encoding="utf-8", errors="replace")
            out = r.stdout if r.returncode == 0 else (r.stderr or r.stdout)
            self.write(f"\n▶ {os.path.basename(self.current_edit_file)}:\n"
                       f"{out[:1000]}\n",
                       "ok" if r.returncode == 0 else "err")
        except Exception as e:
            self.write(f"[!] {e}\n", "err")

    # ============================================================
    # МОДЕЛИ
    # ============================================================
    def _refresh_models(self):
        chat = self.router.list_chat_models()
        if not chat:
            self.write("[!] Нет моделей — скачай во вкладке 🤖 Модели\n", "err")
            return
        for combo in (self.planner_combo, self.coder_combo,
                      self.judge_junior_combo, self.judge_senior_combo,
                      self.chat_model_combo):
            combo["values"] = chat
            if combo.get() not in chat:
                combo.set(chat[0])
        self.write(f"[+] Модели: {len(chat)}\n", "ok")

    def _refresh_installed(self):
        self.inst_list.delete(0, "end")
        for m in model_manager.get_installed():
            self.inst_list.insert(
                "end",
                f"{m['name']:<40} {m['size_gb']:>6} ГБ  "
                f"[{m['purpose'] or '—'}]")

    def _show_catalog(self):
        self.cat_list.delete(0, "end")
        models = model_catalog.enrich_for_ui()
        for m in models[:50]:
            self.cat_list.insert(
                "end",
                f"{m['name'][:45]:<48} ~{m['size_gb']:>5} ГБ  "
                f"[{m['purpose']}]")

    def _refresh_catalog(self):
        self.write("[catalog] Обновление с HuggingFace...\n", "info")

        def worker():
            model_catalog.refresh_catalog(
                limit=80, log_func=lambda m: self.write(m, "info"))
            self.root.after(0, self._show_catalog)

        threading.Thread(target=worker, daemon=True).start()

    def _download_selected(self):
        sel = self.cat_list.curselection()
        if not sel:
            messagebox.showinfo("Выбор", "Выбери модель в каталоге")
            return
        models = model_catalog.enrich_for_ui()
        m = models[sel[0]]

        if not messagebox.askyesno("Скачать",
                                    f"Скачать {m['name']}?\n"
                                    f"Размер: ~{m['size_gb']} ГБ"):
            return

        self.write(f"[download] {m['name']}\n", "info")
        self.model_prog_label.config(text=f"📥 {m['name']}...",
                                      foreground=ui_theme.YELLOW)

        def on_prog(rid, pct, txt):
            def _do():
                if pct >= 0:
                    self.model_progress["value"] = pct
                    self.model_prog_label.config(
                        text=f"📥 {m['name']}: {pct}%")
            self.root.after(0, _do)

        def on_done(rid, ok, err):
            def _do():
                if ok:
                    self.model_prog_label.config(
                        text=f"✅ {m['name']} установлена",
                        foreground=ui_theme.GREEN)
                    self.model_progress["value"] = 100
                    self._refresh_installed()
                    self._refresh_models()
                else:
                    self.model_prog_label.config(
                        text=f"✗ {err}", foreground=ui_theme.RED)
            self.root.after(0, _do)

        def worker():
            model_manager.pull_model(m["repo_id"],
                                      on_progress=on_prog,
                                      on_done=on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _delete_selected_model(self):
        sel = self.inst_list.curselection()
        if not sel:
            return
        installed = model_manager.get_installed()
        m = installed[sel[0]]
        if messagebox.askyesno("Удалить", f"Удалить {m['name']}?"):
            model_manager.delete_model(m["name"])
            self._refresh_installed()
            self._refresh_models()

    def _import_from_ollama(self):
        messagebox.showinfo(
            "Импорт из Ollama",
            "Ollama-модели лежат в отдельной папке и не совместимы\n"
            "с нашим GGUF-движком напрямую.\n\n"
            "Решение: скачай Qwen-модель в каталоге (кнопка «📥 Скачать»).\n"
            "Она уже оптимизирована для GPU.")

    def _refresh_sys_info(self):
        try:
            r = get_system_report()
            recs = ("30B+" if r["vram_mb"] >= 24000 else
                    "14B-20B" if r["vram_mb"] >= 16000 else
                    "14B" if r["vram_mb"] >= 12000 else
                    "7B-8B" if r["vram_mb"] >= 8000 else
                    "3B-7B")
            txt = (f"CPU:  {r['cpu']}\n"
                   f"RAM:  {r['ram_gb']} ГБ\n"
                   f"GPU:  {r['gpu']}\n"
                   f"VRAM: {r['vram_mb']} МБ  →  рекомендуется {recs}")
            self.sys_label.config(text=txt)
        except Exception as e:
            self.sys_label.config(text=f"Ошибка: {e}")

    # ============================================================
    # ДОКУМЕНТЫ
    # ============================================================
    def _add_doc(self):
        p = filedialog.askopenfilename()
        if not p:
            return
        text, err = documents.read(p)
        if err:
            messagebox.showerror("Ошибка", err)
            return
        self.loaded_documents.append(
            {"path": p, "name": os.path.basename(p), "text": text})
        self.docs_list.insert("end",
                              f"{os.path.basename(p)} ({len(text)} симв)")

    def _on_doc_select(self, e=None):
        sel = self.docs_list.curselection()
        if not sel:
            return
        doc = self.loaded_documents[sel[0]]
        self.doc_preview.delete("1.0", "end")
        self.doc_preview.insert("1.0", doc["text"][:10000])

    def _clear_docs(self):
        self.loaded_documents = []
        self.docs_list.delete(0, "end")
        self.doc_preview.delete("1.0", "end")

    # ============================================================
    # ОЧЕРЕДЬ
    # ============================================================
    def _refresh_queue(self):
        self.queue_text.delete("1.0", "end")
        for i, t in enumerate(self.queue.data.get("tasks", []), 1):
            icon = {"pending": "⏳", "running": "🔄",
                    "done": "✅", "failed": "❌"}.get(t["status"], "?")
            self.queue_text.insert("end",
                                    f"{i}. {icon} {t['task'][:100]}\n")

    def _clear_done_queue(self):
        self.queue.clear_done()
        self._refresh_queue()

    # ============================================================
    # МОНИТОРИНГ
    # ============================================================
    def _monitor(self):
        try:
            st = self.router.status()
            self.gpu_label.config(
                text="GPU ✓" if st["gpu"] else "CPU",
                foreground=ui_theme.GREEN if st["gpu"] else ui_theme.FG_DIM)
            self.kb_label.config(text=self.kb.stats())

            if self.router.cloud.has_key():
                self.api_label.config(text="API ✓",
                                       foreground=ui_theme.GREEN)
            else:
                self.api_label.config(text="API: не настроен",
                                       foreground=ui_theme.FG_DIM)

            if HAS_PSUTIL:
                cpu = psutil.cpu_percent(interval=0.1)
                ram = psutil.virtual_memory().percent
                txt = f"CPU:{cpu:.0f}% RAM:{ram:.0f}%"

                try:
                    import subprocess
                    r = subprocess.run(
                        ["nvidia-smi",
                         "--query-gpu=utilization.gpu,memory.used,memory.total",
                         "--format=csv,noheader,nounits"],
                        capture_output=True, text=True, timeout=2,
                        creationflags=subprocess.CREATE_NO_WINDOW
                            if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
                    if r.returncode == 0 and r.stdout.strip():
                        p = r.stdout.strip().split(",")
                        if len(p) >= 3:
                            txt += (f" GPU:{p[0].strip()}% "
                                    f"VRAM:{p[1].strip()}/{p[2].strip()}")
                except Exception:
                    pass

                self.monitor_label.config(text=txt)
        except Exception:
            pass
        self.root.after(3000, self._monitor)

    # ============================================================
    # НАСТРОЙКИ
    # ============================================================
    def _load_settings(self):
        s = config.Config.load("settings")
        if not s:
            return

        # Профиль
        pk = s.get("profile_key", "code")
        if pk in prompts.PROFILES:
            self.profile_combo.set(prompts.PROFILES[pk]["label"])

        # Модели — только если в списке
        chat = self.router.list_chat_models()
        for key, combo in [
            ("planner_model", self.planner_combo),
            ("coder_model", self.coder_combo),
            ("judge_junior_model", self.judge_junior_combo),
            ("judge_senior_model", self.judge_senior_combo),
            ("chat_model", self.chat_model_combo),
        ]:
            val = s.get(key, "")
            if val and val in chat:
                combo.set(val)

        # Числа
        if s.get("attempts"):
            self.attempts_var.set(str(s["attempts"]))
        if s.get("max_chunks"):
            self.chunks_var.set(str(s["max_chunks"]))

        # Чекбоксы
        for k, v in [
            ("validate", self.validate_var), ("chunking", self.chunking_var),
            ("autotest", self.autotest_var), ("autoreadme", self.autoreadme_var),
            ("rag", self.rag_var), ("task_web", self.task_web_var),
        ]:
            if k in s:
                v.set(bool(s[k]))

        # Workspace
        if s.get("workspace"):
            self.ws_entry.delete(0, "end")
            self.ws_entry.insert(0, s["workspace"])

    def _save_settings(self):
        try:
            s = config.Config.load("settings")
            s.update({
                "profile_key": next(
                    (k for k, v in prompts.PROFILES.items()
                     if v["label"] == self.profile_combo.get()), "code"),
                "planner_model": self.planner_combo.get(),
                "coder_model": self.coder_combo.get(),
                "judge_junior_model": self.judge_junior_combo.get(),
                "judge_senior_model": self.judge_senior_combo.get(),
                "chat_model": self.chat_model_combo.get(),
                "attempts": int(self.attempts_var.get() or 3),
                "max_chunks": int(self.chunks_var.get() or 5),
                "validate": self.validate_var.get(),
                "chunking": self.chunking_var.get(),
                "autotest": self.autotest_var.get(),
                "autoreadme": self.autoreadme_var.get(),
                "rag": self.rag_var.get(),
                "task_web": self.task_web_var.get(),
                "auto_model": self.auto_model_var.get(),
                "workspace": self.ws_entry.get().strip(),
            })
            config.Config.save("settings")
        except Exception:
            pass

    # ============================================================
    # API / КЭШ / БАЗА
    # ============================================================
    def _open_api_settings(self):
        win = tk.Toplevel(self.root)
        win.title("⚙ API")
        win.geometry("620x520")
        win.configure(bg=ui_theme.BG_MAIN)
        win.grab_set()

        f = ttk.Frame(win, padding=16)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="⚙ Настройки облачного API",
                  font=("Segoe UI", 12, "bold"),
                  foreground=ui_theme.PURPLE).pack(anchor="w", pady=(0, 12))

        ttk.Label(f, text="Провайдер:").pack(anchor="w")
        from sapphira.core.cloud import PROVIDERS
        provider_var = tk.StringVar(
            value=config.Config.get("api", "provider") or "openrouter")
        pv = ttk.Combobox(f, textvariable=provider_var,
                          values=list(PROVIDERS.keys()), state="readonly")
        pv.pack(fill="x", pady=(2, 10))

        ttk.Label(f, text="API-ключ:").pack(anchor="w")
        key_var = tk.StringVar(value=config.Config.get("api", "api_key") or "")
        ke = ttk.Entry(f, textvariable=key_var, show="*")
        ke.pack(fill="x", pady=(2, 10))
        show = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="Показать",
                        variable=show,
                        command=lambda: ke.config(show="" if show.get() else "*")
                        ).pack(anchor="w")

        ttk.Label(f, text="Base URL (пусто = по умолчанию):").pack(anchor="w", pady=(10, 0))
        url_var = tk.StringVar(value=config.Config.get("api", "base_url") or "")
        ttk.Entry(f, textvariable=url_var).pack(fill="x", pady=(2, 10))

        ttk.Label(f, text="Доп. модели (через запятую):").pack(anchor="w")
        extra_var = tk.StringVar(
            value=", ".join(config.Config.get("api", "extra_models") or []))
        ttk.Entry(f, textvariable=extra_var).pack(fill="x", pady=(2, 10))

        status_lbl = ttk.Label(f, text="", foreground=ui_theme.FG_DIM)
        status_lbl.pack(anchor="w", pady=8)

        def save():
            config.Config.set("api", "provider", provider_var.get())
            config.Config.set("api", "api_key", key_var.get().strip())
            config.Config.set("api", "base_url", url_var.get().strip())
            config.Config.set("api", "extra_models",
                              [m.strip() for m in extra_var.get().split(",")
                               if m.strip()])
            status_lbl.config(text="✓ Сохранено", foreground=ui_theme.GREEN)
            self._refresh_models()

        def test():
            config.Config.set("api", "provider", provider_var.get())
            config.Config.set("api", "api_key", key_var.get().strip())
            config.Config.set("api", "base_url", url_var.get().strip())
            status_lbl.config(text="Проверка...", foreground=ui_theme.YELLOW)
            win.update()
            ok, msg = self.router.cloud.test_connection()
            status_lbl.config(
                text=f"{'✓' if ok else '✗'} {msg}",
                foreground=ui_theme.GREEN if ok else ui_theme.RED)

        bf = ttk.Frame(f)
        bf.pack(fill="x", pady=10)
        ttk.Button(bf, text="💾 Сохранить",
                   style="Accent.TButton", command=save).pack(side="left", padx=4)
        ttk.Button(bf, text="🔌 Проверить",
                   style="Cloud.TButton", command=test).pack(side="left", padx=4)
        ttk.Button(bf, text="Закрыть",
                   command=win.destroy).pack(side="right", padx=4)

    def _clear_cache(self):
        from sapphira.core.cache import ModelCache
        ModelCache().clear()
        self.write("[+] Кэш очищен\n", "ok")

    def _show_kb(self):
        win = tk.Toplevel(self.root)
        win.title("🧠 База знаний")
        win.geometry("720x520")
        win.configure(bg=ui_theme.BG_MAIN)
        st = scrolledtext.ScrolledText(win, wrap="word",
                                        font=("Consolas", 9),
                                        bg=ui_theme.BG_MAIN,
                                        fg=ui_theme.FG_TEXT)
        st.pack(fill="both", expand=True, padx=6, pady=6)
        entries = self.kb.data.get("entries", [])
        st.insert("end", f"Всего: {len(entries)}\n\n")
        for i, e in enumerate(reversed(entries[-30:]), 1):
            st.insert("end",
                      f"{i}. {e['task'][:80]}\n   Файл: {e['filename']}\n\n")
        st.config(state="disabled")

    # ============================================================
    # РАБОЧАЯ ПАПКА
    # ============================================================
    def _choose_workspace(self):
        d = filedialog.askdirectory(initialdir=self.ws_entry.get())
        if d:
            self.ws_entry.delete(0, "end")
            self.ws_entry.insert(0, d)
            self._save_settings()
            self._refresh_tree()

    def _open_workspace(self):
        p = self.ws_entry.get().strip()
        if os.path.isdir(p):
            os.startfile(p)

    def _show_status(self):
        msg = f"{self.kb.stats()}\n"
        msg += f"Очередь: {len(self.queue.data.get('tasks', []))}\n"
        msg += f"История: {len(self.history.data)}"
        messagebox.showinfo("Статус", msg)

    def _export_zip(self):
        ws = self.ws_entry.get().strip()
        if not os.path.isdir(ws):
            return
        import zipfile
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        zp = os.path.join(ws, f"project_{ts}.zip")
        try:
            with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(ws):
                    dirs[:] = [d for d in dirs
                               if d not in ("backups", "__pycache__")]
                    for f in files:
                        if f.endswith(".zip"):
                            continue
                        fp = os.path.join(root, f)
                        zf.write(fp, os.path.relpath(fp, ws))
            messagebox.showinfo("OK", f"Создан:\n{zp}")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    # ============================================================
    # ПОИСК ПО ЛОГАМ
    # ============================================================
    def _search_logs(self):
        q = self.log_search.get().strip()
        self.log.tag_remove("find", "1.0", "end")
        if not q:
            return
        count = 0
        start = "1.0"
        while True:
            pos = self.log.search(q, start, stopindex="end", nocase=True)
            if not pos:
                break
            end = f"{pos}+{len(q)}c"
            self.log.tag_add("find", pos, end)
            start = end
            count += 1
        self.write(f"[🔍] {count}\n", "find")

    def _reset_log_search(self):
        self.log_search.delete(0, "end")
        self.log.tag_remove("find", "1.0", "end")


def run():
    root = tk.Tk()
    app = SapphiraApp(root)
    root.mainloop()





