# -*- coding: utf-8 -*-
"""Тёмная тема Sapphira для ttk + поддержка readonly Combobox."""

from tkinter import ttk

BG_MAIN   = "#1e1e1e"
BG_PANEL  = "#252526"
BG_INPUT  = "#3c3c3c"
BG_HOVER  = "#4a4a4a"
FG_TEXT   = "#e0e0e0"
FG_DIM    = "#858585"
ACCENT    = "#0e639c"
ACCENT_H  = "#1177bb"
BORDER    = "#3c3c3c"
GREEN     = "#89d185"
RED       = "#f48771"
YELLOW    = "#dcdcaa"
BLUE      = "#75beff"
PURPLE    = "#c586c0"
TEAL      = "#4ec9b0"


def apply(root):
    s = ttk.Style()
    try:
        s.theme_use("clam")
    except Exception:
        pass

    # ============ База ============
    s.configure(".", background=BG_PANEL, foreground=FG_TEXT,
                fieldbackground=BG_INPUT, bordercolor=BORDER,
                lightcolor=BG_INPUT, darkcolor=BG_INPUT,
                troughcolor=BG_MAIN, focuscolor=ACCENT)

    s.configure("TFrame", background=BG_PANEL)
    s.configure("TLabel", background=BG_PANEL, foreground=FG_TEXT)
    s.configure("TLabelframe", background=BG_PANEL, foreground=ACCENT,
                bordercolor=BORDER, relief="solid", borderwidth=1)
    s.configure("TLabelframe.Label", background=BG_PANEL, foreground=ACCENT,
                font=("Segoe UI", 9, "bold"))

    # ============ Кнопки ============
    s.configure("TButton", background=BG_INPUT, foreground=FG_TEXT,
                bordercolor=BORDER, focusthickness=0,
                padding=(10, 6), relief="flat", font=("Segoe UI", 9))
    s.map("TButton",
          background=[("active", BG_HOVER), ("pressed", ACCENT),
                      ("disabled", "#2a2a2a")],
          foreground=[("active", "#fff"), ("disabled", "#666")])

    s.configure("Accent.TButton", background=ACCENT, foreground="#fff",
                padding=(12, 6), font=("Segoe UI", 9, "bold"))
    s.map("Accent.TButton",
          background=[("active", ACCENT_H), ("pressed", "#0a4d7a")])

    s.configure("Green.TButton", background="#2d7d46", foreground="#fff",
                padding=(12, 6), font=("Segoe UI", 9, "bold"))
    s.map("Green.TButton", background=[("active", "#3a9c5a")])

    s.configure("Cloud.TButton", background="#6a3d9a", foreground="#fff",
                padding=(10, 6), font=("Segoe UI", 9, "bold"))
    s.map("Cloud.TButton", background=[("active", "#7e52b3")])

    # ============ Entry ============
    s.configure("TEntry",
                fieldbackground=BG_INPUT, foreground=FG_TEXT,
                bordercolor=BORDER, insertcolor=FG_TEXT,
                lightcolor=BG_INPUT, darkcolor=BG_INPUT, padding=5)
    s.map("TEntry",
          fieldbackground=[("disabled", "#2a2a2a"), ("!disabled", BG_INPUT)],
          foreground=[("disabled", "#666"), ("!disabled", FG_TEXT)])

    # ============ Combobox — КЛЮЧЕВОЙ ФИКС ============
    # В теме "clam" readonly Combobox рисует текст через selectbackground/
    # selectforeground. Если их не задать явно — белый текст на светлом фоне.
    s.configure("TCombobox",
                fieldbackground=BG_INPUT, background=BG_INPUT,
                foreground=FG_TEXT, arrowcolor=FG_TEXT,
                bordercolor=BORDER, lightcolor=BG_INPUT,
                darkcolor=BG_INPUT, padding=5)
    s.map("TCombobox",
          # Фон поля
          fieldbackground=[
              ("readonly", BG_INPUT),
              ("disabled", "#2a2a2a"),
              ("!disabled", BG_INPUT),
          ],
          # Цвет текста (значения)
          foreground=[
              ("readonly", FG_TEXT),
              ("disabled", "#666"),
              ("!disabled", FG_TEXT),
          ],
          # Фон области (важно для readonly)
          background=[
              ("readonly", BG_INPUT),
              ("disabled", "#2a2a2a"),
              ("active", BG_HOVER),
          ],
          # Фон выделенного текста (для readonly делаем как BG_INPUT)
          selectbackground=[
              ("readonly", BG_INPUT),
              ("!readonly", ACCENT),
          ],
          # Цвет выделенного текста (для readonly делаем как FG_TEXT)
          selectforeground=[
              ("readonly", FG_TEXT),
              ("!readonly", "#ffffff"),
          ],
          # Стрелка
          arrowcolor=[
              ("active", "#ffffff"),
              ("!active", FG_TEXT),
          ],
          # Рамка при фокусе
          bordercolor=[
              ("focus", ACCENT),
              ("!focus", BORDER),
          ])

    # Выпадающий список Combobox
    root.option_add("*TCombobox*Listbox*Background", BG_INPUT)
    root.option_add("*TCombobox*Listbox*Foreground", FG_TEXT)
    root.option_add("*TCombobox*Listbox*selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox*selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox*Font", ("Consolas", 10))

    # ============ Checkbutton ============
    s.configure("TCheckbutton",
                background=BG_PANEL, foreground=FG_TEXT,
                focuscolor=BG_PANEL)
    s.map("TCheckbutton",
          background=[("active", BG_PANEL)],
          foreground=[("active", "#ffffff")])

    # ============ Notebook ============
    s.configure("TNotebook", background=BG_MAIN, bordercolor=BORDER)
    s.configure("TNotebook.Tab", background=BG_PANEL, foreground=FG_TEXT,
                padding=(12, 8), font=("Segoe UI", 9))
    s.map("TNotebook.Tab",
          background=[("selected", BG_MAIN), ("active", BG_HOVER)],
          foreground=[("selected", "#fff"), ("active", "#fff")])

    # ============ Progressbar ============
    s.configure("Horizontal.TProgressbar",
                background=ACCENT, troughcolor=BG_MAIN,
                bordercolor=BORDER, lightcolor=ACCENT,
                darkcolor=ACCENT, thickness=8)

    # ============ Treeview ============
    s.configure("Treeview",
                background=BG_INPUT, foreground=FG_TEXT,
                fieldbackground=BG_INPUT, bordercolor=BORDER,
                font=("Consolas", 9))
    s.map("Treeview",
          background=[("selected", ACCENT)],
          foreground=[("selected", "#ffffff")])

    # ============ PanedWindow / Separator ============
    s.configure("TPanedwindow", background=BG_MAIN)
    s.configure("TSeparator", background=BORDER)

    # ============ Меню ============
    root.option_add("*Menu.background", BG_PANEL)
    root.option_add("*Menu.foreground", FG_TEXT)
    root.option_add("*Menu.activeBackground", ACCENT)
    root.option_add("*Menu.activeForeground", "#ffffff")

    root.configure(bg=BG_MAIN)


def add_paste_support(root, widget):
    """Универсальный Ctrl+C/V/X/A + правый клик.

    Использует event.keycode (VK-код Windows), который одинаков
    для русской и английской раскладки (V=86/М=86, C=67, X=88, A=65).
    """
    import tkinter as tk

    VK_A = 65
    VK_C = 67
    VK_V = 86
    VK_X = 88

    def _paste(event=None):
        try:
            text = root.clipboard_get()
        except tk.TclError:
            return "break"
        try:
            widget.insert("insert", text)
        except Exception:
            try:
                widget.insert(tk.INSERT, text)
            except Exception:
                pass
        return "break"

    def _copy(event=None):
        try:
            sel = widget.get("sel.first", "sel.last")
        except Exception:
            return "break"
        root.clipboard_clear()
        root.clipboard_append(sel)
        return "break"

    def _cut(event=None):
        _copy()
        try:
            widget.delete("sel.first", "sel.last")
        except Exception:
            pass
        return "break"

    def _select_all(event=None):
        try:
            widget.tag_add("sel", "1.0", "end")
            widget.mark_set("insert", "1.0")
            widget.see("insert")
        except Exception:
            pass
        return "break"

    def _on_ctrl(event):
        """Единый обработчик Control+<любая_буква>."""
        kc = getattr(event, "keycode", 0)
        if kc == VK_V:
            return _paste(event)
        if kc == VK_C:
            return _copy(event)
        if kc == VK_X:
            return _cut(event)
        if kc == VK_A:
            return _select_all(event)
        return None

    def _context_menu(event):
        m = tk.Menu(widget, tearoff=0)
        m.add_command(label="Копировать", command=_copy)
        m.add_command(label="Вставить", command=_paste)
        m.add_command(label="Вырезать", command=_cut)
        m.add_separator()
        m.add_command(label="Выделить всё", command=_select_all)
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()
        return "break"

    # Основной обработчик — ловит Control+любая клавиша
    try:
        widget.bind("<Control-KeyPress>", _on_ctrl)
    except Exception:
        pass

    # Плюс классические для совместимости
    extras = [
        ("<Shift-Insert>", _paste),
        ("<Control-Insert>", _copy),
        ("<Shift-Delete>", _cut),
        ("<Button-3>", _context_menu),
        ("<Button-2>", _context_menu),
    ]
    for seq, fn in extras:
        try:
            widget.bind(seq, fn)
        except Exception:
            pass
