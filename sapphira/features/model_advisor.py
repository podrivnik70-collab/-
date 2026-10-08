# -*- coding: utf-8 -*-
"""Анализ задачи и рекомендация моделей.

Правила основаны на типе задачи, действии и размере проекта.
Не использует LLM — быстро и предсказуемо.
"""

import os
from pathlib import Path


# Каталог рекомендуемых моделей
# (имя для Ollama, размер ГБ, роль, приоритет)
# Точные репозитории на HuggingFace (проверенные)
KNOWN_REPOS = {
    # Qwen2.5-Coder
    "Qwen2.5-Coder-0.5B-Instruct":   "Qwen/Qwen2.5-Coder-0.5B-Instruct-GGUF",
    "Qwen2.5-Coder-1.5B-Instruct":   "Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF",
    "Qwen2.5-Coder-3B-Instruct":     "Qwen/Qwen2.5-Coder-3B-Instruct-GGUF",
    "Qwen2.5-Coder-7B-Instruct":     "bartowski/Qwen2.5-Coder-7B-Instruct-GGUF",
    "Qwen2.5-Coder-14B-Instruct":    "bartowski/Qwen2.5-Coder-14B-Instruct-GGUF",
    "Qwen2.5-Coder-32B-Instruct":    "bartowski/Qwen2.5-Coder-32B-Instruct-GGUF",
    # Qwen3
    "Qwen3-4B":                       "Qwen/Qwen3-4B-GGUF",
    "Qwen3-8B":                       "Qwen/Qwen3-8B-GGUF",
    "Qwen3-14B":                      "Qwen/Qwen3-14B-GGUF",
    "Qwen3-30B-A3B":                  "Qwen/Qwen3-30B-A3B-GGUF",
    # Qwen3.5
    "Qwen3.5-4B":                     "unsloth/Qwen3.5-4B-GGUF",
    "Qwen3.5-9B":                     "unsloth/Qwen3.5-9B-GGUF",
    # Qwen3.8
    "Qwen3.8-27B":                    "unsloth/Qwen3.8-27B-GGUF",
    # DeepSeek
    "DeepSeek-R1-7B":                 "unsloth/DeepSeek-R1-Distill-Qwen-7B-GGUF",
    "DeepSeek-R1-14B":                "unsloth/DeepSeek-R1-Distill-Qwen-14B-GGUF",
    # Embedder
    "nomic-embed-text-v1.5":          "nomic-ai/nomic-embed-text-v1.5-GGUF",
}


def get_repo_id(model_name: str) -> str:
    """Возвращает repo_id для известной модели или ''."""
    # Точное совпадение
    if model_name in KNOWN_REPOS:
        return KNOWN_REPOS[model_name]
    # По нормализованному имени (убираем суффиксы)
    def _n(s):
        s = s.lower().replace("-instruct", "").replace("_instruct", "")
        s = s.replace("-gguf", "").replace("_gguf", "")
        s = s.replace(".gguf", "").replace(":", "-")
        return s.strip()
    target = _n(model_name)
    for k, v in KNOWN_REPOS.items():
        if _n(k) == target:
            return v
    return ""


MODEL_CATALOG = {
    "planner": [
        ("Qwen3.5-9B", 6.2, "Планирование"),
        ("Qwen2.5-Coder-7B-Instruct", 4.4, "Планирование"),
        ("Qwen3.8-27B", 15.8, "Планирование"),
    ],
    "coder_simple": [
        ("Qwen2.5-Coder-7B-Instruct", 4.4, "Простой код"),
        ("Qwen3.5-9B", 6.2, "Простой код"),
    ],
    "coder_complex": [
        ("Qwen2.5-Coder-14B-Instruct", 9.0, "Сложный код"),
        ("Qwen3.5-9B", 6.2, "Сложный код"),
        ("Qwen2.5-Coder-7B-Instruct", 4.4, "Сложный код (fallback)"),
    ],
    "judge_fast": [
        ("Qwen2.5-Coder-7B-Instruct", 4.4, "Быстрый судья"),
        ("Qwen3.5-9B", 6.2, "Быстрый судья"),
    ],
    "judge_strict": [
        ("Qwen3.5-9B", 6.2, "Строгий судья"),
        ("Qwen2.5-Coder-14B-Instruct", 9.0, "Строгий судья"),
        ("Qwen3.8-27B", 15.8, "Строгий судья"),
    ],
}

# Триггеры для определения действия
ACTION_TRIGGERS = {
    "testing": ["тест", "test", "pytest"],
    "docs": ["readme", "документ", "docstring", "комментар"],
    "refactor": ["рефактор", "refactor", "переписать", "переделать"],
    "code": [],  # default
}


def _detect_action(task: str) -> str:
    """Определяет тип действия по тексту задачи."""
    low = task.lower()
    for action, triggers in ACTION_TRIGGERS.items():
        if action == "code":
            continue
        for t in triggers:
            if t in low:
                return action
    return "code"


def _detect_size(root_path: str = None, mode: str = "create") -> str:
    """Определяет размер проекта."""
    if mode == "create" or not root_path:
        return "small"
    try:
        root = Path(root_path)
        if not root.is_dir():
            return "small"
        count = 0
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            count += 1
            if count > 100:
                break
        if count < 20:
            return "small"
        if count <= 100:
            return "medium"
        return "large"
    except Exception:
        return "small"


def _pick_model(role: str, candidates: list) -> tuple:
    """Выбирает первую доступную модель из candidates."""
    for name, size, desc in candidates:
        yield name, size, desc


def _pick_target(candidates: list, installed_set: set) -> dict:
    """
    Возвращает целевую модель (первую в списке) и информацию:
    - если целевая установлена → используем её
    - если нет, но есть fallback → используем fallback, но целевую
      добавляем в missing
    - если ничего нет → используем целевую, добавляем в missing
    """
    if not candidates:
        return {"target": None, "use": None, "need_download": False}

    target_name, target_size, target_desc = candidates[0]

    if target_name in installed_set:
        return {
            "target": {"name": target_name, "size_gb": target_size, "desc": target_desc},
            "use": {"name": target_name, "size_gb": target_size, "desc": target_desc,
                    "installed": True},
            "need_download": False,
        }

    # Ищем fallback
    fallback = None
    for name, size, desc in candidates[1:]:
        if name in installed_set:
            fallback = (name, size, desc)
            break

    return {
        "target": {"name": target_name, "size_gb": target_size, "desc": target_desc},
        "use": {
            "name": fallback[0] if fallback else target_name,
            "size_gb": fallback[1] if fallback else target_size,
            "desc": (fallback[2] if fallback else target_desc) + " (fallback)",
            "installed": bool(fallback),
        },
        "need_download": True,
    }


def recommend(task: str, mode: str = "create", root_path: str = None,
              installed_models: list = None) -> dict:
    """Возвращает рекомендацию моделей."""
    installed_models = installed_models or []
    installed_set = set(installed_models)

    action = _detect_action(task)
    size = _detect_size(root_path, mode)

    # Правила
    if mode == "edit" and size in ("medium", "large"):
        coder_key = "coder_complex"
    elif action in ("refactor", "testing"):
        coder_key = "coder_complex"
    else:
        coder_key = "coder_simple"

    if action == "docs":
        planner_key = "planner"
        judge_fast_key = "judge_fast"
        judge_strict_key = "judge_fast"
        coder_key = "coder_simple"
    else:
        planner_key = "planner"
        judge_fast_key = "judge_fast"
        judge_strict_key = "judge_strict"

    # Выбираем
    planner = _pick_target(MODEL_CATALOG.get(planner_key, []), installed_set)
    coder = _pick_target(MODEL_CATALOG.get(coder_key, []), installed_set)
    judge_fast = _pick_target(MODEL_CATALOG.get(judge_fast_key, []), installed_set)
    judge_strict = _pick_target(MODEL_CATALOG.get(judge_strict_key, []), installed_set)

    models = {
        "planner": planner["use"],
        "coder": coder["use"],
        "judge_fast": judge_fast["use"],
        "judge_strict": judge_strict["use"],
    }

    # Собираем missing — только целевые, которых нет
    missing_names = set()
    missing_list = []
    for role_data in (planner, coder, judge_fast, judge_strict):
        if role_data["need_download"] and role_data["target"]:
            t = role_data["target"]
            if t["name"] not in missing_names:
                missing_names.add(t["name"])
                missing_list.append({
                    "name": t["name"],
                    "size_gb": t["size_gb"],
                    "role": t["desc"],
                })

    total_gb = sum(m["size_gb"] for m in missing_list)

    return {
        "analysis": {"mode": mode, "action": action, "size": size},
        "models": models,
        "missing": missing_list,
        "total_download_gb": round(total_gb, 1),
    }

def get_installed_models() -> list:
    """Возвращает список установленных моделей через Sapphira."""
    try:
        import sys
        from pathlib import Path
        v2 = Path(__file__).resolve().parent.parent.parent
        if str(v2) not in sys.path:
            sys.path.insert(0, str(v2))
        from sapphira.core.router import get_router
        return get_router().list_chat_models()
    except Exception:
        return []


if __name__ == "__main__":
    print("=== model_advisor самотест ===\n")

    installed = get_installed_models()
    print(f"Установлено: {installed}\n")

    tests = [
        ("Создай калькулятор на Python", "create", None),
        ("Улучши проект в C:\\Users\\Домашние\\Desktop\\Сапфира\\Сапфира версия 3 — добавь кэш",
         "edit", "C:\\Users\\Домашние\\Desktop\\Сапфира\\Сапфира версия 3"),
        ("Отрефактори проект C:\\Users\\Домашние\\Desktop\\Сапфира\\Сапфира версия 3",
         "edit", "C:\\Users\\Домашние\\Desktop\\Сапфира\\Сапфира версия 3"),
        ("Напиши README для проекта", "create", None),
        ("Создай pytest-тесты для utils.py", "create", None),
    ]

    for task, mode, path in tests:
        r = recommend(task, mode=mode, root_path=path,
                      installed_models=installed)
        print(f"Задача: {task[:60]}")
        print(f"  Анализ: {r['analysis']}")
        for role, m in r["models"].items():
            icon = "OK" if m["installed"] else "нет"
            print(f"    [{role:12}] {m['name']:<30} {icon}")
        if r["missing"]:
            print(f"  Нужно скачать: {r['total_download_gb']} ГБ")
        print()