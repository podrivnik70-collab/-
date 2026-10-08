# -*- coding: utf-8 -*-
"""Определяет режим задачи: создать новый проект или улучшить существующий."""

import os
import re
from pathlib import Path

# Слова-триггеры режима "улучшить"
EDIT_TRIGGERS = [
    "улучши", "улучшить", "улучшение",
    "исправь", "исправить",
    "добавь в", "добавить в",
    "переделай", "переделать",
    "оптимизируй", "оптимизировать",
    "отрефактори", "отрефакторить",
    "дополни", "дополнить",
    "доработай", "доработать",
    "почини", "починить",
    "измени в", "изменить в",
    "обнови в", "обновить в",
    "перепиши в", "переписать",
    "модернизируй",
    "рефакторинг",
    "улучшение проекта",
]


def _find_path_in_text(text: str) -> str:
    """Ищет путь к папке в тексте. Поддерживает пробелы в пути.

    Алгоритм: находим стартовую позицию (C:\, UNC, /, ./), потом
    жадно наращиваем до конца, проверяя существование через isdir.
    Берём самый длинный существующий путь.
    """
    # Возможные стартовые позиции
    starts = []
    for m in re.finditer(r'[A-Za-z]:[\\\/]', text):
        starts.append(m.start())
    for m in re.finditer(r'\\\\', text):
        starts.append(m.start())
    for m in re.finditer(r'(?<![\w:])/', text):  # / не после буквы (не после http:)
        starts.append(m.start())
    for m in re.finditer(r'\.\.?/', text):
        starts.append(m.start())

    if not starts:
        return ""

    # Для каждой стартовой позиции — ищем самый длинный существующий путь
    best = ""
    for start in sorted(set(starts)):
        # Наращиваем от конца строки к началу
        # Сначала берём всё до конца строки, потом отрезаем по одному символу
        tail = text[start:]

        # Разные "концы" — до символов-разделителей секции задачи
        # (тире с пробелами, точка с запятой и т.п.)
        candidates = [tail]

        # Ищем короткие варианты — до " — " (тире с пробелами), до " ;"
        for sep in [" — ", " – ", " - ", " ; ", "\n"]:
            idx_sep = tail.find(sep)
            if idx_sep > 0:
                candidates.append(tail[:idx_sep])

        # Проверяем каждый кандидат от длинного к короткому
        for cand in candidates:
            cand = cand.strip().rstrip(".,;:")
            if not cand:
                continue
            if os.path.isdir(cand):
                if len(cand) > len(best):
                    best = cand
                break

        # Если не нашли с "жёстким" разделителем — попробуем итеративно отрезать хвост
        if not best:
            word = tail
            # Отрезаем по одному слову от конца (по 3 символа минимум)
            for cut in range(len(word), 2, -1):
                candidate = word[:cut].rstrip(".,;:-— ")
                if len(candidate) >= 4 and os.path.isdir(candidate):
                    if len(candidate) > len(best):
                        best = candidate
                    break

    return best

def detect_mode(task: str, default_workspace: str = "") -> dict:
    """
    Определяет режим и путь.

    Возвращает:
    {
        "mode": "create" | "edit",
        "path": "путь или None",
        "task_clean": "задача без пути (только действие)",
        "reason": "почему выбрано"
    }
    """
    task = task.strip()
    if not task:
        return {"mode": "create", "path": None, "task_clean": task,
                "reason": "пустая задача"}

    low = task.lower()

    # Есть ли слово-триггер?
    has_trigger = any(t in low for t in EDIT_TRIGGERS)

    # Есть ли путь в тексте?
    path_str = _find_path_in_text(task)
    path_exists = bool(path_str) and os.path.isdir(path_str)

    if not has_trigger:
        return {"mode": "create", "path": None, "task_clean": task,
                "reason": "нет слов-триггеров улучшения"}

    if not path_str:
        return {"mode": "create", "path": None, "task_clean": task,
                "reason": "триггер есть, но путь не указан"}

    if not path_exists:
        # Возможно, пользователь имел в виду рабочую папку + относительный путь
        if default_workspace and not os.path.isabs(path_str):
            candidate = os.path.join(default_workspace, path_str)
            if os.path.isdir(candidate):
                path_str = candidate
                path_exists = True

    if not path_exists:
        return {"mode": "create", "path": None, "task_clean": task,
                "reason": f"путь '{path_str}' не существует"}

    # Убираем путь из текста задачи (для чистого промпта)
    task_clean = task.replace(path_str, "").strip()
    task_clean = re.sub(r'\s*[-—]\s*', ' ', task_clean, count=1)
    task_clean = re.sub(r'\s+', ' ', task_clean).strip(" ,.-")

    if not task_clean:
        task_clean = "Улучшить проект"

    return {
        "mode": "edit",
        "path": path_str,
        "task_clean": task_clean,
        "reason": f"триггер + существующий путь",
    }


if __name__ == "__main__":
    print("=== task_mode.py самотест ===\n")

    tests = [
        "Создай калькулятор на Python",
        "Улучши проект в C:\\Users\\Домашние\\Desktop\\Сапфира\\Сапфира версия 3 — добавь кэш",
        "Исправь баг в C:\\несуществующий\\путь",
        "Доработай проект C:\\Users\\Домашние\\Desktop\\Сапфира\\Сапфира версия 2",
        "Оптимизируй /home/user/bot",
        "Улучши — добавь тесты",
    ]

    for t in tests:
        result = detect_mode(t)
        print(f"Задача: {t[:70]}")
        print(f"  → mode={result['mode']}")
        print(f"  → path={result['path']}")
        print(f"  → clean={result['task_clean'][:60]}")
        print(f"  → reason={result['reason']}")
        print()