# -*- coding: utf-8 -*-
"""CloudClient — работа с облачными API: OpenRouter, DeepSeek, OpenAI, Groq, Gemini.

Все они имеют OpenAI-совместимый интерфейс /chat/completions.
Пользователь может работать целиком в облаке — без скачивания моделей вообще.
"""

import requests
from sapphira.config import Config


# ============ Провайдеры ============
PROVIDERS = {
    "openrouter": {
        "label": "OpenRouter (агрегатор)",
        "base_url": "https://openrouter.ai/api/v1",
        "models": [
            "meta-llama/llama-3.3-70b-instruct:free",
            "google/gemini-2.0-flash-exp:free",
            "deepseek/deepseek-chat",
            "anthropic/claude-3.5-sonnet",
            "openai/gpt-4o-mini",
        ],
        "note": "Много моделей, в т.ч. бесплатных (:free). Ключ: openrouter.ai",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "note": "Очень дешёвый, отличный код. Ключ: platform.deepseek.com",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o-mini", "gpt-4o"],
        "note": "Классика. Ключ: platform.openai.com",
    },
    "groq": {
        "label": "Groq (быстрый)",
        "base_url": "https://api.groq.com/openai/v1",
        "models": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
        ],
        "note": "Очень быстрый инференс, есть бесплатный тариф. Ключ: console.groq.com",
    },
    "gemini": {
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "models": ["gemini-2.0-flash-exp", "gemini-1.5-flash"],
        "note": "Есть бесплатный тариф. Ключ: aistudio.google.com",
    },
    "custom": {
        "label": "Свой OpenAI-совместимый",
        "base_url": "",
        "models": [],
        "note": "Укажи base_url и модели вручную",
    },
}

# Префикс для cloud-моделей в UI: "cloud/deepseek-chat"
CLOUD_PREFIX = "cloud/"


# ============ Утилиты ============
def is_cloud_model(model_name: str) -> bool:
    return (model_name or "").startswith(CLOUD_PREFIX)


def get_real_name(model_name: str) -> str:
    return model_name.replace(CLOUD_PREFIX, "", 1) if is_cloud_model(model_name) else model_name


def get_provider_models(provider_key: str = None) -> list:
    """Список моделей для UI: ['cloud/deepseek-chat', ...]"""
    if provider_key is None:
        provider_key = Config.get("api", "provider") or "openrouter"
    p = PROVIDERS.get(provider_key, {})
    base = p.get("models", []) or []
    extra = Config.get("api", "extra_models") or []
    all_models = list(dict.fromkeys(base + extra))
    return [CLOUD_PREFIX + m for m in all_models]


def get_provider_info(provider_key: str = None) -> dict:
    if provider_key is None:
        provider_key = Config.get("api", "provider") or "openrouter"
    return PROVIDERS.get(provider_key, {})


# ============ Клиент ============
class CloudClient:
    def __init__(self):
        pass

    # --- Конфиг ---
    def get_api_key(self) -> str:
        env = (
            __import__("os").getenv("OPENROUTER_API_KEY")
            or __import__("os").getenv("DEEPSEEK_API_KEY")
            or __import__("os").getenv("OPENAI_API_KEY")
        )
        if env:
            return env
        return Config.get("api", "api_key") or ""

    def get_base_url(self) -> str:
        custom = (Config.get("api", "base_url") or "").strip()
        if custom:
            return custom
        provider = Config.get("api", "provider") or "openrouter"
        return PROVIDERS.get(provider, {}).get("base_url", "")

    def has_key(self) -> bool:
        return bool(self.get_api_key().strip())

    # --- Запросы ---
    def chat(self, model: str, prompt: str, system: str = None,
             temperature: float = 0.3, max_tokens: int = 4096,
             timeout: int = 120) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat_history(model, messages, temperature, max_tokens, timeout)

    def chat_history(self, model: str, messages: list,
                     temperature: float = 0.3, max_tokens: int = 4096,
                     timeout: int = 120) -> str:
        key = self.get_api_key()
        if not key:
            raise RuntimeError("API-ключ не указан")

        real = get_real_name(model)
        url = f"{self.get_base_url().rstrip('/')}/chat/completions"

        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        if "openrouter" in url:
            headers["HTTP-Referer"] = "https://sapphira.local"
            headers["X-Title"] = "Sapphira"

        payload = {
            "model": real,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if r.status_code != 200:
            raise RuntimeError(f"API {r.status_code}: {r.text[:300]}")

        data = r.json()
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError):
            raise RuntimeError(f"Неожиданный ответ API: {str(data)[:200]}")

    # --- Тест соединения ---
    def test_connection(self) -> tuple:
        key = self.get_api_key()
        if not key:
            return False, "API-ключ не указан"
        try:
            url = f"{self.get_base_url().rstrip('/')}/models"
            r = requests.get(
                url,
                headers={"Authorization": f"Bearer {key}"},
                timeout=10,
            )
            if r.status_code == 200:
                return True, "OK"
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)


# ============ Самотест ============
if __name__ == "__main__":
    print("=== cloud.py самотест ===\n")

    print("Провайдеры:")
    for k, p in PROVIDERS.items():
        print(f"  • {k:<12} {p['label']}")
        print(f"    {p['note']}")

    print(f"\nТекущий провайдер: {Config.get('api', 'provider') or 'openrouter'}")
    print(f"API-ключ: {'✓ есть' if Config.get('api', 'api_key') else '✗ нет'}")

    print("\nДоступные cloud-модели:")
    for m in get_provider_models():
        print(f"  {m}")

    print("\nРазбор имени:")
    for name in ["cloud/deepseek-chat", "qwen2.5-coder-7b"]:
        print(f"  {name:<25} → cloud: {is_cloud_model(name)}, real: {get_real_name(name)!r}")

    c = CloudClient()
    if c.has_key():
        print("\nТест соединения...")
        ok, msg = c.test_connection()
        print(f"  {'✓' if ok else '✗'} {msg}")
    else:
        print("\n[i] Тест соединения пропущен — нет API-ключа")
        print("    (Настраивается потом в UI: Настройки → API)")