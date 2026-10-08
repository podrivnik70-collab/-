# -*- coding: utf-8 -*-
"""Запись sapphira.log с ротацией (по размеру)."""

import os
import shutil
from datetime import datetime
from threading import Lock

_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_FILE = os.path.join(_SCRIPT_DIR, "logs", "sapphira.log")
MAX_SIZE = 5 * 1024 * 1024  # 5 МБ

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

_lock = Lock()


def write(text: str):
    """Дописывает строку в лог. Автоматически ротирует по размеру."""
    if not text:
        return
    try:
        with _lock:
            # Ротация
            if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > MAX_SIZE:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                shutil.move(LOG_FILE, f"{LOG_FILE}.{ts}")
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(text)
    except Exception:
        pass


def clear():
    try:
        with _lock:
            if os.path.exists(LOG_FILE):
                os.remove(LOG_FILE)
    except Exception:
        pass


def log_path() -> str:
    return LOG_FILE


if __name__ == "__main__":
    print(f"Лог: {LOG_FILE}")
    write(f"[{datetime.now().isoformat()}] тест 1\n")
    write(f"[{datetime.now().isoformat()}] тест 2\n")
    print(f"Размер: {os.path.getsize(LOG_FILE)} байт")
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        print("--- содержимое ---")
        print(f.read())