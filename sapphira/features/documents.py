# -*- coding: utf-8 -*-
"""Чтение документов: PDF, DOCX, CSV, XLSX, JSON, TXT/MD.
Возвращает чистый текст для промпта."""

import os
import json

# --- Опциональные зависимости ---
try:
    import PyPDF2
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

try:
    import docx
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


MAX_CHARS = 10_000  # ограничение на размер текста из одного файла


def read(path: str) -> tuple:
    """Возвращает (text, error). Если error непустой — text = ''."""
    if not os.path.exists(path):
        return "", "Файл не найден"
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".txt", ".md"):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()[:MAX_CHARS], ""
        if ext == ".pdf":
            if not HAS_PDF:
                return "", "Установи PyPDF2"
            with open(path, "rb") as f:
                r = PyPDF2.PdfReader(f)
                text = "\n".join(p.extract_text() for p in r.pages if p.extract_text())
            return text[:MAX_CHARS], ""
        if ext == ".docx":
            if not HAS_DOCX:
                return "", "Установи python-docx"
            d = docx.Document(path)
            return "\n".join(p.text for p in d.paragraphs)[:MAX_CHARS], ""
        if ext == ".csv":
            if not HAS_PANDAS:
                return "", "Установи pandas"
            return pd.read_csv(path).to_string()[:MAX_CHARS], ""
        if ext in (".xlsx", ".xls"):
            if not HAS_PANDAS:
                return "", "Установи pandas openpyxl"
            return pd.read_excel(path).to_string()[:MAX_CHARS], ""
        if ext == ".json":
            with open(path, "r", encoding="utf-8") as f:
                return json.dumps(json.load(f), ensure_ascii=False, indent=2)[:MAX_CHARS], ""
        # Прочее — пробуем как текст
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()[:MAX_CHARS], ""
    except Exception as e:
        return "", f"Ошибка: {e}"


def supported_extensions() -> list:
    return [".txt", ".md", ".pdf", ".docx", ".csv", ".xlsx", ".xls", ".json"]


if __name__ == "__main__":
    import tempfile
    print("=== documents самотест ===\n")
    print(f"PDF:    {'✓' if HAS_PDF else '✗ (pip install PyPDF2)'}")
    print(f"DOCX:   {'✓' if HAS_DOCX else '✗ (pip install python-docx)'}")
    print(f"Pandas: {'✓' if HAS_PANDAS else '✗ (pip install pandas openpyxl)'}")
    print()

    # TXT
    p = os.path.join(tempfile.gettempdir(), "sapphira_test.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("Привет, Sapphira!\nВторая строка.")
    text, err = read(p)
    print(f"TXT test: err={err!r}, len={len(text)}, first={text[:40]!r}")

    # JSON
    p2 = os.path.join(tempfile.gettempdir(), "sapphira_test.json")
    with open(p2, "w", encoding="utf-8") as f:
        json.dump({"key": "значение", "n": 42}, f, ensure_ascii=False)
    text, err = read(p2)
    print(f"JSON test: err={err!r}, len={len(text)}")

    # Несуществующий
    text, err = read("C:/nonexistent_file.xyz")
    print(f"Missing test: err={err!r}")