# -*- coding: utf-8 -*-
"""KnowledgeBase — база знаний успешных решений.

Когда файл одобрен обоими судьями — сохраняем пару (task, code) в KB.
Позже при похожей задаче находим примеры и подкладываем в промпт Кодера.

Поиск — простой TF-подобный по словам (без эмбеддингов), т.к. KB небольшая.
"""

import re
import time
from datetime import datetime
from sapphira.config import Config


STOP_WORDS = {
    "и", "в", "на", "с", "по", "для", "не", "что", "как", "это",
    "the", "a", "an", "of", "to", "in", "is", "for", "with", "on", "at",
    "создай", "сделай", "напиши", "файл", "файла", "файлы", "проект",
}


def _tokenize(text: str) -> set:
    """Разбивает текст на значимые слова (без стоп-слов)."""
    words = re.findall(r"\w+", text.lower())
    return {w for w in words if len(w) > 3 and w not in STOP_WORDS}


class KnowledgeBase:
    def __init__(self):
        data = Config.load("knowledge")
        if "entries" not in data:
            data["entries"] = []
        self.data = data

    def save(self):
        Config.save("knowledge")

    # ---------- Добавление ----------
    def add_solution(self, task: str, filename: str, code: str,
                     verdict: str = "OK", score: float = 0.0):
        """Сохраняет успешное решение."""
        entry = {
            "task": task[:300],
            "filename": filename,
            "code": code[:2000],
            "verdict": verdict,
            "score": score,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "keywords": list(_tokenize(task + " " + filename)),
        }
        self.data["entries"].append(entry)
        # Ограничиваем размер
        if len(self.data["entries"]) > 300:
            self.data["entries"] = self.data["entries"][-300:]
        self.save()

    # ---------- Поиск ----------
    def search_similar(self, task: str, top_k: int = 3,
                       min_score: float = 0.25) -> list:
        """Ищет похожие решения по пересечению ключевых слов."""
        query = _tokenize(task)
        if not query:
            return []

        scored = []
        for entry in self.data["entries"]:
            entry_kw = set(entry.get("keywords", []))
            if not entry_kw:
                continue
            overlap = len(query & entry_kw)
            score = overlap / max(len(query), 1)
            if score >= min_score:
                scored.append((score, entry))

        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:top_k]]

    # ---------- Контекст для промпта ----------
    def get_context(self, task: str, max_chars: int = 1500) -> str:
        similar = self.search_similar(task)
        if not similar:
            return ""

        parts = []
        total = 0
        for e in similar:
            block = (f"Похожая задача: {e['task']}\n"
                     f"Файл: {e['filename']}\n"
                     f"Решение:\n{e['code'][:600]}")
            parts.append(block)
            total += len(block)
            if total >= max_chars:
                break

        return "\n\n---\n\n".join(parts)

    # ---------- Статистика ----------
    def stats(self) -> str:
        return f"База знаний: {len(self.data.get('entries', []))} примеров"

    def clear(self):
        self.data["entries"] = []
        self.save()

    def list_recent(self, n: int = 20) -> list:
        return list(reversed(self.data["entries"][-n:]))


if __name__ == "__main__":
    print("=== knowledge.py самотест ===\n")

    kb = KnowledgeBase()
    kb.clear()

    print("Добавляем 3 решения...")
    kb.add_solution(
        task="Создай калькулятор: utils.py с add/sub/mul/div",
        filename="utils.py",
        code="def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b",
        verdict="OK", score=0.85,
    )
    kb.add_solution(
        task="Напиши парсер CSV с фильтрацией",
        filename="parser.py",
        code="import csv\n\ndef parse(path):\n    with open(path) as f:\n        return list(csv.DictReader(f))",
        verdict="OK", score=0.9,
    )
    kb.add_solution(
        task="Telegram-бот на Python",
        filename="bot.py",
        code="from telegram import Update\nfrom telegram.ext import ApplicationBuilder",
        verdict="OK", score=0.8,
    )

    print(f"\n{kb.stats()}\n")

    print("Поиск 'калькулятор для чисел':")
    for e in kb.search_similar("калькулятор для чисел"):
        print(f"  • {e['filename']}: {e['task'][:60]}")

    print("\nПоиск 'обработка CSV файлов':")
    for e in kb.search_similar("обработка CSV файлов"):
        print(f"  • {e['filename']}: {e['task'][:60]}")

    print("\nКонтекст для промпта 'напиши калькулятор':")
    ctx = kb.get_context("напиши калькулятор")
    print(ctx[:300])

    print("\n✅ knowledge готов")