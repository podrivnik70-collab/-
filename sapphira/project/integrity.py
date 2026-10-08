# -*- coding: utf-8 -*-
"""Integrity — проверка целостности проекта после генерации.

Что проверяет:
- Все файлы из плана существуют
- Каждый .py файл проходит ast.parse
- Импорты внутри проекта ссылаются на существующие модули
- Обрезанных файлов нет

Возвращает список проблем (пустой = всё чисто).
"""

import os
import ast
from sapphira.utils.code import (
    validate_syntax, detect_truncation, get_missing_imports,
)


def check_project(workspace: str, expected_files: list = None) -> list:
    """
    Проверяет workspace.
    expected_files — список файлов из плана.
    Возвращает [{"file": ..., "issue": ...}, ...].
    """
    problems = []
    expected_files = expected_files or []

    # 1. Все ли файлы на месте
    for fn in expected_files:
        path = os.path.join(workspace, fn)
        if not os.path.exists(path):
            problems.append({
                "file": fn,
                "issue": "файл не создан",
            })

    # 2. Сканируем .py-файлы
    py_files = []
    if os.path.isdir(workspace):
        for fn in os.listdir(workspace):
            if fn.endswith(".py"):
                py_files.append(fn)

    for fn in py_files:
        path = os.path.join(workspace, fn)
        try:
            with open(path, "r", encoding="utf-8") as f:
                code = f.read()
        except Exception as e:
            problems.append({"file": fn, "issue": f"не читается: {e}"})
            continue

        # Синтаксис
        ok, err = validate_syntax(code)
        if not ok:
            problems.append({"file": fn, "issue": f"синтаксис: {err}"})

        # Обрезка
        trunc, reason = detect_truncation(code)
        if trunc:
            problems.append({"file": fn, "issue": f"обрезка: {reason}"})

        # Отсутствующие внешние модули
        missing = get_missing_imports(code, py_files)
        if missing:
            problems.append({
                "file": fn,
                "issue": f"нет модулей: {', '.join(missing)}",
            })

    return problems


def format_report(problems: list) -> str:
    """Форматирует список проблем в читаемый вид."""
    if not problems:
        return "✅ Проект целостен — проблем не найдено"
    lines = [f"⚠ Найдено проблем: {len(problems)}"]
    for p in problems:
        lines.append(f"  • {p['file']}: {p['issue']}")
    return "\n".join(lines)


if __name__ == "__main__":
    import tempfile
    import shutil

    print("=== integrity.py самотест ===\n")

    tmp = tempfile.mkdtemp()

    # Создаём хороший проект
    with open(os.path.join(tmp, "utils.py"), "w", encoding="utf-8") as f:
        f.write("def add(a, b):\n    return a + b\n")

    with open(os.path.join(tmp, "main.py"), "w", encoding="utf-8") as f:
        f.write("from utils import add\nprint(add(1, 2))\n")

    print("Тест 1: хороший проект")
    probs = check_project(tmp, expected_files=["utils.py", "main.py"])
    print(format_report(probs))

    # Ломаем main.py
    with open(os.path.join(tmp, "main.py"), "w", encoding="utf-8") as f:
        f.write("from utils import add\nprint(add(1, 2)\n")

    print("\nТест 2: сломанный синтаксис")
    probs = check_project(tmp, expected_files=["utils.py", "main.py"])
    print(format_report(probs))

    # Пропавший файл
    os.remove(os.path.join(tmp, "utils.py"))
    print("\nТест 3: пропавший utils.py")
    probs = check_project(tmp, expected_files=["utils.py", "main.py"])
    print(format_report(probs))

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n✅ integrity готов")