# -*- coding: utf-8 -*-
"""Router — единый интерфейс для чата и эмбеддингов.

Скрывает от UI разницу между локальными GGUF-моделями и облачными API.
Правила:
- "cloud/..."  → CloudClient (OpenRouter, DeepSeek, Groq, ...)
- иначе        → LocalEngine (GGUF через llama-cpp-python)

Кэш: только для локальных chat() без system-промпта.
Не кэшируем chat_history (разные диалоги) и cloud (там деньги).
"""

import threading
from sapphira.core.engine import (
    get_engine, list_installed_models, is_embedder_name, has_gpu_support,
)
from sapphira.core.cloud import (
    CloudClient, is_cloud_model, get_provider_models,
)
from sapphira.core.cache import ModelCache


class Router:
    def __init__(self):
        self.local = get_engine()
        self.cloud = CloudClient()
        self.cache = ModelCache()

    # ============ Список моделей ============
    def list_all_models(self) -> list:
        """Все модели: локальные + cloud/... (если есть ключ)."""
        local = [m["name"] for m in list_installed_models()]
        cloud = []
        if self.cloud.has_key():
            cloud = get_provider_models()
        return local + cloud

    def list_chat_models(self) -> list:
        """Только chat-модели (без embedder'ов)."""
        local = [m["name"] for m in list_installed_models()
                 if not is_embedder_name(m["name"])]
        cloud = get_provider_models() if self.cloud.has_key() else []
        return local + cloud

    def list_embed_models(self) -> list:
        """Только embedder'ы (для RAG)."""
        return [m["name"] for m in list_installed_models()
                if is_embedder_name(m["name"])]

    def is_available(self, model: str) -> bool:
        if not model:
            return False
        if is_cloud_model(model):
            return self.cloud.has_key()
        return any(m["name"] == model for m in list_installed_models())

    # ============ Чат ============
    def chat(self, model: str, prompt: str,
             system: str = None,
             max_tokens: int = 4096,
             temperature: float = 0.3,
             use_cache: bool = True) -> str:
        """Одиночный запрос. Кэш только для локальных без system."""
        if is_cloud_model(model):
            return self.cloud.chat(
                model, prompt, system=system,
                temperature=temperature, max_tokens=max_tokens,
            )

        # Локально — кэш
        if use_cache and not system:
            cached = self.cache.get(model, prompt)
            if cached is not None:
                return cached

        answer = self.local.chat(
            model, prompt, system=system,
            max_tokens=max_tokens, temperature=temperature,
        )

        if use_cache and not system and answer:
            self.cache.set(model, prompt, answer)
        return answer

    def chat_history(self, model: str, messages: list,
                     max_tokens: int = 4096,
                     temperature: float = 0.3) -> str:
        """Многоходовой диалог. Без кэша."""
        if is_cloud_model(model):
            return self.cloud.chat_history(
                model, messages,
                temperature=temperature, max_tokens=max_tokens,
            )
        return self.local.chat_history(
            model, messages,
            max_tokens=max_tokens, temperature=temperature,
        )

    # ============ Эмбеддинги ============
    def embed(self, model: str, text: str) -> list:
        """Эмбеддинг. Только локально."""
        if is_cloud_model(model):
            raise ValueError("Эмбеддинги через облако не поддерживаются.")
        return self.local.embed(model, text)

    def embed_batch(self, model: str, texts: list) -> list:
        return self.local.embed_batch(model, texts)

    # ============ Управление ============
    def unload_all(self):
        self.local.unload_all()

    def status(self) -> dict:
        return {
            "chat_loaded": self.local.chat_loaded(),
            "chat_model": self.local.current_chat_model(),
            "embed_loaded": self.local.embed_loaded(),
            "embed_model": self.local.current_embed_model(),
            "cloud_key": self.cloud.has_key(),
            "gpu": has_gpu_support(),
            "cache": self.cache.stats(),
        }


# ============ Глобальный экземпляр ============
_router = None
_router_lock = threading.Lock()


def get_router() -> Router:
    global _router
    with _router_lock:
        if _router is None:
            _router = Router()
    return _router


# ============ Самотест ============
if __name__ == "__main__":
    print("=== router.py самотест ===\n")

    r = get_router()

    print("Статус:")
    for k, v in r.status().items():
        print(f"  {k:<14} {v}")

    print("\nChat-модели:")
    for m in r.list_chat_models():
        print(f"  {m}")

    print("\nEmbed-модели:")
    for m in r.list_embed_models():
        print(f"  {m}")

    # Реальный тест
    chat = r.list_chat_models()
    if chat:
        model = chat[0]
        print(f"\nТест чата на {model}...")
        import time
        t0 = time.time()
        ans = r.chat(model, "Скажи одно слово: приветствие", max_tokens=10)
        print(f"За {time.time()-t0:.2f}с: {ans}")

    print("\n✅ Router готов")