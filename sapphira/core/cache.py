# -*- coding: utf-8 -*-
"""Кэш ответов моделей. Ключ — md5(модель + промпт)."""

import hashlib
from threading import Lock
from sapphira.config import Config


class ModelCache:
    def __init__(self):
        self._lock = Lock()
        self._data = Config.load("model_cache")
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _key(model: str, prompt: str) -> str:
        raw = f"{model}|{prompt}".encode("utf-8")
        return hashlib.md5(raw).hexdigest()

    def get(self, model: str, prompt: str):
        k = self._key(model, prompt)
        with self._lock:
            if k in self._data:
                self.hits += 1
                return self._data[k]
        self.misses += 1
        return None

    def set(self, model: str, prompt: str, response: str):
        if not response:
            return
        k = self._key(model, prompt)
        with self._lock:
            self._data[k] = response
            # Ограничим размер: 1000 записей
            if len(self._data) > 1000:
                for old in list(self._data.keys())[:200]:
                    del self._data[old]
            Config.save("model_cache")

    def clear(self):
        with self._lock:
            self._data.clear()
            self.hits = 0
            self.misses = 0
            Config.save("model_cache")

    def stats(self) -> dict:
        total = self.hits + self.misses
        rate = round(self.hits * 100 / total, 1) if total else 0
        return {
            "hits": self.hits,
            "misses": self.misses,
            "entries": len(self._data),
            "hit_rate": rate,
        }

    def __len__(self):
        return len(self._data)


if __name__ == "__main__":
    print("=== ModelCache самотест ===\n")
    c = ModelCache()
    c.clear()

    print("Пустой кэш:", c.stats())

    c.set("qwen2.5-coder:7b", "напиши hello world", "print('hi')")
    print("После записи:", c.stats())

    r = c.get("qwen2.5-coder:7b", "напиши hello world")
    print(f"Получено: {r!r}")

    r = c.get("qwen2.5-coder:7b", "другой промпт")
    print(f"Промах: {r!r}")

    print("Итог:", c.stats())