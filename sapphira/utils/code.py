# -*- coding: utf-8 -*-
"""Утилиты для работы с кодом от LLM:
- extract_code(text) → чистое содержимое файла
- extract_json(text) → dict/list из ответа
- validate_syntax(code) → (ok, error)
- detect_truncation(code) → (обрезан?, причина)
- remove_duplicate_prefix(existing, new_part) → продолжение без дублей
- get_imports(code) / get_missing_imports(code, project_files)
- topological_sort(steps) → порядок сборки проекта
"""

import re
import ast
import json
import os
import importlib.util


# ============ Извлечение кода ============
_CODE_FENCE = re.compile(
    r"```(?:python|py|markdown|md|txt|json)?\s*\n?(.*?)\n?```",
    re.DOTALL,
)


def extract_code(text: str):
    """Достаёт содержимое из ```-блока. Если блоков нет — возвращает как есть."""
    if not text:
        return None
    m = _CODE_FENCE.search(text)
    if m:
        return m.group(1).strip()
    stripped = text.strip()
    return stripped if stripped else None


def extract_json(text: str):
    """Ищет JSON в тексте (в т.ч. внутри ```json)."""
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?\s*", "", text).replace("```", "")
    for pattern in (r"\{.*\}", r"\[.*\]"):
        m = re.search(pattern, cleaned, re.DOTALL)
        if not m:
            continue
        raw = m.group(0)
        try:
            return json.loads(raw)
        except Exception:
            for closer in ("}", "]"):
                idx = raw.rfind(closer)
                if idx != -1:
                    try:
                        return json.loads(raw[:idx + 1])
                    except Exception:
                        continue
    return None


# ============ Валидация синтаксиса ============
def validate_syntax(code: str):
    """Возвращает (ok: bool, error: str)."""
    if not code:
        return False, "пустой код"
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, f"SyntaxError: {e.msg} (строка {e.lineno})"
    except Exception as e:
        return False, str(e)


# ============ Проверка обрезки ============
TRUNCATION_MARKERS = [
    "... (продолжение)",
    "...(продолжение)",
    "# ... далее",
    "# (продолжение)",
    "# ... код ...",
    "pass  # TODO",
    "pass  # заглушка",
    "pass  # stub",
]


def detect_truncation(code: str):
    """Возвращает (обрезан: bool, причина: str)."""
    if not code:
        return True, "пустой"

    for m in TRUNCATION_MARKERS:
        if m in code:
            return True, f"маркер: '{m}'"

    pairs = [("(", ")"), ("[", "]"), ("{", "}")]
    for open_c, close_c in pairs:
        if code.count(open_c) > code.count(close_c):
            return True, f"незакрытые {open_c}"

    lines = [l for l in code.split("\n") if l.strip()]
    if not lines:
        return True, "нет непустых строк"

    last = lines[-1].rstrip()
    if last.endswith(":"):
        return True, "строка на ':'"
    if last.endswith(("+", "-", "*", "/", "=", ",", "and", "or", "not", "in", "is")):
        return True, "оборванный оператор"

    if len(lines) == 1 and len(lines[0]) < 15:
        return True, f"одна короткая строка ({len(lines[0])} симв)"

    return False, ""


# ============ Удаление дублей при склейке чанков ============
def remove_duplicate_prefix(existing: str, new_part: str) -> str:
    """
    Убирает из начала new_part строки, которые уже есть в конце existing.
    Используется при склейке продолжений кода от LLM.
    """
    if not existing or not new_part:
        return new_part

    ex_lines = [l.strip() for l in existing.split("\n") if l.strip()]
    new_lines = new_part.split("\n")

    # Смотрим на последние 30 строк существующего
    tail = set(ex_lines[-30:]) if len(ex_lines) >= 30 else set(ex_lines)

    # Ищем первую строку в new_part, которой нет в tail
    start = 0
    for i, line in enumerate(new_lines):
        s = line.strip()
        if not s:
            continue
        if s not in tail:
            start = i
            break
    else:
        # Все строки — дубликаты
        return ""

    return "\n".join(new_lines[start:])


# ============ Проверка импортов ============
STDLIB = {
    "os", "sys", "re", "json", "time", "datetime", "math", "random",
    "threading", "subprocess", "tkinter", "collections", "itertools",
    "functools", "pathlib", "shutil", "hashlib", "socket", "queue",
    "logging", "unittest", "argparse", "csv", "sqlite3", "pickle",
    "base64", "urllib", "http", "email", "html", "xml", "io",
    "contextlib", "typing", "dataclasses", "enum", "abc", "copy",
    "glob", "tempfile", "traceback", "warnings", "weakref", "asyncio",
    "concurrent", "multiprocessing", "signal", "platform", "string",
    "textwrap", "unicodedata", "difflib", "decimal", "fractions",
    "statistics", "operator", "heapq", "bisect", "zipfile", "tarfile",
    "uuid", "secrets", "ssl", "struct", "array", "binascii",
}


def get_imports(code: str) -> set:
    """Возвращает множество импортируемых top-level модулей."""
    result = set()
    try:
        tree = ast.parse(code)
    except Exception:
        return result
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                result.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module.split(".")[0])
    return result


def get_missing_imports(code: str, project_files: list) -> list:
    """Возвращает список внешних модулей, которых нет в системе."""
    project_mods = {os.path.basename(f).replace(".py", "") for f in project_files}
    missing = []
    for m in get_imports(code):
        if m in STDLIB or m in project_mods or m in missing:
            continue
        try:
            if importlib.util.find_spec(m) is None:
                missing.append(m)
        except Exception:
            missing.append(m)
    return missing


# ============ Топологическая сортировка (Kahn) ============
def topological_sort(steps: list) -> list:
    """
    steps: [{"file": "...", "dependencies": [...]}, ...]
    Возвращает список в порядке сборки: сначала зависимости.
    """
    file_to_step = {s["file"]: s for s in steps}
    in_degree = {s["file"]: 0 for s in steps}

    for s in steps:
        for dep in s.get("dependencies", []) or []:
            if dep in file_to_step:
                in_degree[s["file"]] += 1

    queue = [s["file"] for s in steps if in_degree[s["file"]] == 0]
    result = []

    while queue:
        fn = queue.pop(0)
        result.append(file_to_step[fn])
        for s in steps:
            if fn in (s.get("dependencies", []) or []):
                in_degree[s["file"]] -= 1
                if in_degree[s["file"]] == 0:
                    queue.append(s["file"])

    if len(result) < len(steps):
        for s in steps:
            if s not in result:
                result.append(s)

    return result


# ============ Самотест ============
if __name__ == "__main__":
    print("=== code.py самотест ===\n")

    t1 = "Вот код:\n```python\ndef hi():\n    return 1\n```\nГотово."
    print("extract_code:", repr(extract_code(t1)))

    t2 = 'Ответ:\n```json\n{"score": 0.9}\n```'
    print("extract_json:", extract_json(t2))

    print("validate ok:  ", validate_syntax("def f():\n    return 1"))
    print("validate bad: ", validate_syntax("def f(\n    return 1"))

    print("trunc (  ):", detect_truncation("def f("))
    print("trunc (:) :", detect_truncation("def f():"))
    print("trunc (ok):", detect_truncation("def f():\n    return 1\n"))
    print("trunc (1s):", detect_truncation("x=1"))

    # remove_duplicate_prefix
    existing = "def add(a, b):\n    return a + b"
    new_part = "def add(a, b):\n    return a + b\ndef sub(a, b):\n    return a - b"
    cleaned = remove_duplicate_prefix(existing, new_part)
    print(f"\nremove_dup:")
    print(f"  было:  {len(new_part)} симв")
    print(f"  стало: {len(cleaned)} симв (должно быть только 'def sub...')")
    print(f"  результат: {cleaned!r}")

    code = "import os\nimport requests\nfrom qwen_tts import X\n"
    print(f"\nimports: {get_imports(code)}")
    print(f"missing: {get_missing_imports(code, [])}")

    steps = [
        {"file": "main.py", "dependencies": ["utils.py"]},
        {"file": "utils.py", "dependencies": []},
        {"file": "config.py", "dependencies": []},
    ]
    print(f"sort: {[s['file'] for s in topological_sort(steps)]}")

    print("\n✅ code готов")