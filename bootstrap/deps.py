# -*- coding: utf-8 -*-
"""Список pip-пакетов для проверки и установки."""

# (import_name, pip_name, обязательно, размер_МБ)
DEPENDENCIES = [
    ("requests",  "requests",            True,  1),
    ("numpy",     "numpy",               True,  20),
    ("psutil",    "psutil",              True,  1),
    ("ddgs",      "ddgs",                False, 2),
    ("PyPDF2",    "PyPDF2",              False, 1),
    ("docx",      "python-docx",         False, 2),
    ("pandas",    "pandas",              False, 60),
    ("openpyxl",  "openpyxl",            False, 5),
    ("llama_cpp", "llama-cpp-python",    True,  200),
]


def check_all():
    """Возвращает {pip_name: (installed, required)}."""
    import importlib.util
    result = {}
    for mod, pip, req, _size in DEPENDENCIES:
        try:
            installed = importlib.util.find_spec(mod) is not None
        except Exception:
            installed = False
        result[pip] = (installed, req)
    return result


def get_missing():
    """Список [(pip_name, required), ...]."""
    check = check_all()
    return [(pip, req) for pip, (inst, req) in check.items() if not inst]


if __name__ == "__main__":
    print("=== deps.py самотест ===\n")
    check = check_all()
    for pip, (inst, req) in check.items():
        mark = "✅" if inst else ("❌" if req else "💤")
        note = "" if req else " (опционально)"
        print(f"  {mark} {pip}{note}")
    print(f"\nОтсутствуют: {len(get_missing())}")