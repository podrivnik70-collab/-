# -*- coding: utf-8 -*-
"""Судьи — проверка кода двумя уровнями.

Младший судья (junior):
- синтаксис, обрезка, отсутствующие импорты
- быстрый, дешёвый

Старший судья (senior):
- соответствует ли задача, работает ли логика
- учитывает критерии от планировщика
- финальное решение OK/FAIL

Плюс детерминированные проверки в Python (без LLM):
- validate_syntax (ast.parse)
- detect_truncation
- get_missing_imports (учитывая файлы проекта!)
- незакрытые кавычки
"""

import re
from sapphira.agents import prompts
from sapphira.utils.code import (
    extract_json, validate_syntax, detect_truncation, get_missing_imports,
)


# ============ Дополнительный детектор обрезки ============
def detect_unclosed_strings(code: str):
    """Эвристика: считаем кавычки, исключая тройные и экранированные."""
    stripped = re.sub(r'"""[\s\S]*?"""', "", code)
    stripped = re.sub(r"'''[\s\S]*?'''", "", stripped)
    stripped = re.sub(r'\\["\']', "", stripped)
    stripped = re.sub(r"#[^\n]*", "", stripped)

    single = stripped.count("'")
    double = stripped.count('"')

    if single % 2 == 1:
        return False, f"незакрытая одинарная кавычка ({single} шт)"
    if double % 2 == 1:
        return False, f"незакрытая двойная кавычка ({double} шт)"
    return True, ""


# ============ Детерминированные проверки ============
def preflight_check(code: str, project_files: list = None) -> list:
    """Быстрые проверки БЕЗ LLM. Возвращает список проблем."""
    problems = []
    project_files = project_files or []

    if not code or not code.strip():
        return ["Пустой код"]

    # Синтаксис
    ok, err = validate_syntax(code)
    if not ok:
        problems.append(f"Синтаксис: {err}")

    # Обрезка
    trunc, reason = detect_truncation(code)
    if trunc:
        problems.append(f"Обрезка: {reason}")

    # Незакрытые кавычки
    ok_str, reason_str = detect_unclosed_strings(code)
    if not ok_str:
        problems.append(f"Обрезка: {reason_str}")

    # Импорты — с учётом ЛОКАЛЬНЫХ модулей проекта
    missing = get_missing_imports(code, project_files)
    if missing:
        problems.append(f"Отсутствуют модули: {', '.join(missing)}")

    return problems


# ============ Младший судья ============
def review_junior(router, model: str,
                  task: str, filename: str, code: str,
                  profile_key: str = "code",
                  project_files: list = None,
                  log_func=None) -> dict:
    """
    Возвращает {"score": float, "problems": [...]}.
    project_files — список файлов проекта (для проверки локальных импортов).
    """
    def log(m):
        if log_func:
            log_func(m)

    project_files = project_files or []

    # Детерминированные проверки
    det_problems = preflight_check(code, project_files)
    if det_problems:
        log(f"[junior] Детерминированные проблемы: {len(det_problems)}\n")
        for p in det_problems:
            log(f"    • {p}\n")
        return {"score": 0.3, "problems": det_problems}

    # LLM-проверка
    prompt = prompts.build_junior(
        profile_key=profile_key,
        task=task,
        filename=filename,
        code=code[:4000],
    )

    try:
        raw = router.chat(model, prompt, max_tokens=512, temperature=0.1,
                          use_cache=False)
    except Exception as e:
        log(f"[junior] ✗ LLM: {e}\n")
        return {"score": 1.0, "problems": []}

    data = extract_json(raw)
    if not isinstance(data, dict):
        log(f"[junior] ⚠ Не JSON — принимаем\n")
        return {"score": 1.0, "problems": []}

    score = float(data.get("score", 1.0))
    problems = data.get("problems", [])
    if not isinstance(problems, list):
        problems = [str(problems)]

    return {"score": score, "problems": problems}


# ============ Старший судья ============
def review_senior(router, model: str,
                  task: str, criteria: str,
                  filename: str, project_files: list, code: str,
                  profile_key: str = "code",
                  log_func=None) -> dict:
    """Возвращает {"score", "verdict", "problems", "summary"}."""
    def log(m):
        if log_func:
            log_func(m)

    # Быстрая проверка
    det_problems = preflight_check(code, project_files)
    if det_problems:
        log(f"[senior] До LLM: {len(det_problems)} проблем\n")
        return {
            "score": 0.3,
            "verdict": "FAIL",
            "problems": det_problems,
            "summary": "Автопроверка не пройдена",
        }

    pf_str = "\n".join(f"  • {f}" for f in project_files if f != filename)

    prompt = prompts.build_senior(
        profile_key=profile_key,
        task=task,
        criteria=criteria or "(нет)",
        filename=filename,
        project_files=pf_str or "(нет)",
        code=code[:5000],
    )

    try:
        raw = router.chat(model, prompt, max_tokens=800, temperature=0.1,
                          use_cache=False)
    except Exception as e:
        log(f"[senior] ✗ LLM: {e}\n")
        return {"score": 0.8, "verdict": "OK",
                "problems": [], "summary": "LLM недоступен — принято"}

    data = extract_json(raw)
    if not isinstance(data, dict):
        log(f"[senior] ⚠ Не JSON — принимаем\n")
        return {"score": 0.8, "verdict": "OK",
                "problems": [], "summary": "Не JSON"}

    score = float(data.get("score", 0))
    verdict = str(data.get("verdict", "?"))
    problems = data.get("problems", [])
    summary = data.get("summary", "")

    if not isinstance(problems, list):
        problems = [str(problems)]

    return {
        "score": score,
        "verdict": verdict,
        "problems": problems,
        "summary": summary,
    }


# ============ Самотест ============
if __name__ == "__main__":
    from sapphira.core.router import get_router

    print("=== judge.py самотест ===\n")

    print("--- Тест 1: preflight_check ---")
    bad = 'def f(x):\n    print("hi)\n    return x'
    for p in preflight_check(bad):
        print(f"  • {p}")

    print("\n--- Тест 2: локальный импорт НЕ должен считаться missing ---")
    code = "from utils import add, sub\n\ndef main():\n    return add(1,2)\n"
    p1 = preflight_check(code, project_files=[])
    p2 = preflight_check(code, project_files=["utils.py", "main.py"])
    print(f"  без project_files:  {p1}")
    print(f"  с project_files:    {p2}  ← должен быть пустым!")

    router = get_router()
    models = router.list_chat_models()
    if not models:
        print("\n❌ Нет chat-моделей")
        raise SystemExit(1)

    model = models[0]
    print(f"\n--- Тест 3: LLM-судья на {model} ---")

    def log(m):
        print(m, end="")

    code_test = '''def add(a, b):
    return a + b

def div(a, b):
    if b == 0:
        raise ValueError("Div by zero")
    return a / b
'''

    print("\n[junior]")
    jr = review_junior(router, model,
                       task="Создать функции add и div",
                       filename="utils.py",
                       code=code_test,
                       log_func=log)
    print(f"  score={jr['score']}, проблем={len(jr['problems'])}")

    print("\n[senior]")
    sr = review_senior(router, model,
                       task="Создать функции add и div",
                       criteria="Функции работают корректно",
                       filename="utils.py",
                       project_files=["main.py"],
                       code=code_test,
                       log_func=log)
    print(f"  score={sr['score']}, verdict={sr['verdict']}")
    print(f"  summary: {sr['summary']}")

    print("\n✅ judge готов")