# -*- coding: utf-8 -*-
"""Планировщик — превращает задачу в план из файлов.

Вход:  задача (строка) + профиль + контекст (KB/веб/документы)
Выход: {"steps": [...], "criteria": "...", "entry_point": "..."}

Шаги потом сортируются топологически (utils.code.topological_sort),
чтобы зависимости создавались раньше тех, кто их использует.
"""

import json
from sapphira.agents import prompts
from sapphira.utils.code import extract_json, topological_sort


# ============ Нормализация ============
def _normalize_step(s, default_ext: str) -> dict:
    """Приводит элемент плана к единому виду."""
    if isinstance(s, str):
        return {
            "file": f"main{default_ext}",
            "action": s,
            "dependencies": [],
        }
    if not isinstance(s, dict):
        return None

    deps = s.get("dependencies", [])
    if not isinstance(deps, list):
        deps = []

    return {
        "file": (s.get("file") or s.get("filename")
                 or f"main{default_ext}"),
        "action": (s.get("action") or s.get("description")
                   or s.get("task") or "выполнить"),
        "dependencies": [str(d) for d in deps if d],
    }


# ============ Основная функция ============
def make_plan(router, model: str, task: str,
              profile_key: str = "code",
              context: str = "",
              log_func=None) -> dict:
    """
    Строит план через LLM.

    router     — sapphira.core.router.Router
    model      — имя модели (локальной или cloud/...)
    task       — текст задачи
    profile_key — 'code' / 'text' / 'analysis' / ...
    context    — строка с дополнительным контекстом (KB, веб, документы)
    log_func   — callback для логов (str) -> None

    Возвращает:
    {
        "steps": [{"file": "...", "action": "...", "dependencies": [...]}],
        "criteria": "…",
        "entry_point": "…" or None,
    }
    """
    def log(m):
        if log_func:
            log_func(m)

    profile = prompts.get_profile(profile_key)
    default_ext = profile["ext"]

    prompt = prompts.build_planner(profile_key, task, context)
    log(f"[planner] Запрос к {model} ({len(prompt)} симв)...\n")

    raw = router.chat(
        model, prompt,
        max_tokens=2048,
        temperature=0.2,
        use_cache=False,  # план должен быть свежим
    )

    log(f"[planner] Ответ ({len(raw)} симв):\n{raw[:400]}\n\n")

    # Парсим JSON
    data = extract_json(raw)

    steps_raw = None
    criteria = ""
    entry = None

    if isinstance(data, dict):
        steps_raw = (data.get("steps")
                     or data.get("plan")
                     or data.get("files"))
        criteria = data.get("criteria", "") or ""
        entry = data.get("entry_point") or data.get("entry")
    elif isinstance(data, list):
        steps_raw = data

    if not steps_raw:
        log(f"[planner] ⚠ JSON без steps — fallback: один файл\n")
        steps_raw = [{
            "file": f"main{default_ext}",
            "action": task,
            "dependencies": [],
        }]
        entry = f"main{default_ext}"

    # Нормализация
    steps = []
    for s in steps_raw:
        n = _normalize_step(s, default_ext)
        if n:
            steps.append(n)

    if not steps:
        steps = [{
            "file": f"main{default_ext}",
            "action": task,
            "dependencies": [],
        }]

    # Топологическая сортировка
    steps = topological_sort(steps)

    # Автовыбор entry_point
    if not entry:
        # Ищем файл, от которого зависят все остальные (или main)
        for candidate in [f"main{default_ext}", "main.py", "app.py", "index.md"]:
            if any(s["file"] == candidate for s in steps):
                entry = candidate
                break
        if not entry:
            entry = steps[-1]["file"]  # последний по порядку сборки

    return {
        "steps": steps,
        "criteria": criteria,
        "entry_point": entry,
    }


# ============ Самотест ============
if __name__ == "__main__":
    from sapphira.core.router import get_router

    print("=== planner.py самотест ===\n")

    router = get_router()
    chat_models = router.list_chat_models()
    if not chat_models:
        print("❌ Нет chat-моделей")
        raise SystemExit(1)

    model = chat_models[0]
    print(f"Модель: {model}\n")

    task = ("Создай проект: калькулятор на Python. "
            "Файлы: utils.py (функции add/sub/mul/div), "
            "main.py (CLI-интерфейс, импортирует utils).")

    def log(m):
        print(m, end="")

    result = make_plan(router, model, task, profile_key="code", log_func=log)

    print("\n" + "=" * 50)
    print("РЕЗУЛЬТАТ ПЛАНА")
    print("=" * 50)
    print(f"Entry point: {result['entry_point']}")
    print(f"Criteria:    {result['criteria'][:200]}")
    print(f"\nШаги ({len(result['steps'])}):")
    for i, s in enumerate(result["steps"], 1):
        deps = s["dependencies"]
        dstr = f"  ← {', '.join(deps)}" if deps else ""
        print(f"  {i}. {s['file']:<20} {s['action'][:60]}{dstr}")

    print("\n✅ planner готов")