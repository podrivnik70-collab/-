# -*- coding: utf-8 -*-
"""Единая точка чтения/записи всех настроек Sapphira.

Все JSON-конфиги лежат в data/ рядом с проектом.
Никакой код, кроме этого модуля, не открывает их напрямую.
"""

import os
import json
import shutil
from datetime import datetime
from threading import Lock

# --- Пути ---
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../Сапфира версия 2
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
MODELS_DIR = os.path.join(SCRIPT_DIR, "models")
WORKSPACE_DIR = os.path.join(SCRIPT_DIR, "workspace")
LOGS_DIR = os.path.join(SCRIPT_DIR, "logs")

for _d in (DATA_DIR, MODELS_DIR, WORKSPACE_DIR, LOGS_DIR):
    os.makedirs(_d, exist_ok=True)

# --- Имена файлов в data/ ---
FILES = {
    "settings":       "settings.json",
    "api":            "api_config.json",
    "history":        "tasks_history.json",
    "queue":          "tasks_queue.json",
    "knowledge":      "knowledge_base.json",
    "model_cache":    "model_cache.json",
    "catalog_cache":  "catalog_cache.json",
    "manifest":       "models_manifest.json",
    "app_state":      "app_state.json",
}

# --- Значения по умолчанию ---
DEFAULTS = {
    "settings": {
        "profile_key": "code",
        "planner_model": "",
        "coder_model": "",
        "judge_junior_model": "",
        "judge_senior_model": "",
        "chat_model": "",
        "attempts": 5,
        "max_chunks": 5,
        "validate": True,
        "chunking": True,
        "autotest": False,
        "autoreadme": True,
        "rag": True,
        "task_web": False,
        "chat_rag": True,
        "chat_docs": False,
        "chat_web": True,
        "max_tokens": 4096,
        "temperature": 0.3,
        "context_length": 8192,
    },
    "api": {
        "provider": "openrouter",
        "api_key": "",
        "base_url": "",
        "extra_models": [],
    },
    "history": [],
    "queue": {"tasks": []},
    "knowledge": {"entries": []},
    "model_cache": {},
    "catalog_cache": {"updated": 0, "models": []},
    "manifest": {"installed": []},
    "app_state": {
        "workspace": WORKSPACE_DIR,
        "first_run_done": False,
    },
}


class _Config:
    """Синглтон: один экземпляр на весь процесс."""
    _instance = None
    _lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self._cache = {}
        self._dirty = set()

    # === Пути ===
    def path(self, name: str) -> str:
        """Полный путь к JSON-файлу: Config.path('settings')."""
        if name not in FILES:
            raise KeyError(f"Неизвестный конфиг: {name}")
        return os.path.join(DATA_DIR, FILES[name])

    # === Чтение ===
    def load(self, name: str):
        """Загружает конфиг. Кэширует. Возвращает dict/list."""
        if name in self._cache:
            return self._cache[name]

        path = self.path(name)
        default = DEFAULTS.get(name)

        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Мержим с дефолтами (если словарь)
                if isinstance(data, dict) and isinstance(default, dict):
                    merged = {**default, **data}
                    self._cache[name] = merged
                    return merged
                self._cache[name] = data
                return data
            except Exception:
                # Битый файл → бэкап и дефолт
                self._backup_broken(path)

        # Нет файла — используем дефолт и сохраняем
        import copy
        data = copy.deepcopy(default) if default is not None else {}
        self._cache[name] = data
        self.save(name)
        return data

    def _backup_broken(self, path):
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.move(path, f"{path}.broken_{ts}")
        except Exception:
            pass

    # === Запись ===
    def save(self, name: str):
        """Сохраняет конфиг на диск. Атомарно."""
        if name not in self._cache:
            return
        path = self.path(name)
        tmp = path + ".tmp"
        try:
            with self._lock:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._cache[name], f, ensure_ascii=False, indent=2)
                os.replace(tmp, path)
            self._dirty.discard(name)
        except Exception as e:
            print(f"[config] Не сохранить {name}: {e}")

    def save_all(self):
        for name in list(self._cache.keys()):
            self.save(name)

    # === Точечный доступ ===
    def get(self, name: str, key=None, default=None):
        data = self.load(name)
        if key is None:
            return data
        if isinstance(data, dict):
            return data.get(key, default)
        return default

    def set(self, name: str, key, value):
        data = self.load(name)
        if isinstance(data, dict):
            data[key] = value
            self.save(name)

    def update(self, name: str, **kwargs):
        data = self.load(name)
        if isinstance(data, dict):
            data.update(kwargs)
            self.save(name)

    # === Хелперы ===
    def reset(self, name: str):
        """Сбрасывает конфиг до дефолта."""
        import copy
        self._cache[name] = copy.deepcopy(DEFAULTS.get(name, {}))
        self.save(name)

    def info(self):
        """Для отладки — куда всё пишется."""
        return {
            "script_dir": SCRIPT_DIR,
            "data_dir": DATA_DIR,
            "models_dir": MODELS_DIR,
            "workspace": WORKSPACE_DIR,
            "logs_dir": LOGS_DIR,
            "files": {n: self.path(n) for n in FILES},
        }


# --- Глобальный экземпляр ---
Config = _Config()


# ============ Самотест ============
if __name__ == "__main__":
    print("=== Config самотест ===\n")
    info = Config.info()
    print("Пути:")
    for k, v in info.items():
        if k == "files":
            print("  files:")
            for fn, fp in v.items():
                print(f"    {fn:<15} → {fp}")
        else:
            print(f"  {k:<12} {v}")

    print("\nЧтение settings:")
    s = Config.load("settings")
    print(f"  profile_key = {Config.get('settings', 'profile_key')}")
    print(f"  attempts    = {Config.get('settings', 'attempts')}")
    print(f"  temperature = {Config.get('settings', 'temperature')}")

    print("\nЗапись / чтение:")
    Config.set("settings", "temperature", 0.7)
    print(f"  temperature = {Config.get('settings', 'temperature')} (после set)")
    Config.set("settings", "temperature", 0.3)

    print("\nПроверка на диске:")
    path = Config.path("settings")
    print(f"  {path} существует: {os.path.exists(path)}")
    print(f"  размер: {os.path.getsize(path)} байт")

    print("\nВсе конфиги:")
    for name in FILES:
        Config.load(name)
        p = Config.path(name)
        ok = "✓" if os.path.exists(p) else "✗"
        print(f"  {ok} {FILES[name]}")