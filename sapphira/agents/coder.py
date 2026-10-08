# -*- coding: utf-8 -*-
"""Кодер — генерирует код файла + автодобор обрезанных чанков.

Две задачи:
1. generate()           — обычная генерация файла с ретраями
2. generate_chunked()   — если ответ обрезан, догенерировать остаток

Вход: filename, task, action, project_files, requirements (что исправить)
Выход: чистый код файла (без ```-обёрток)
"""

import re
from sapphira.agents import prompts
from sapphira.utils.code import (
    extract_code, detect_truncation, remove_duplicate_prefix,
)


# ============ Утилита: склеивание продолжений ============
def _tail(text: str, n_lines: int = 40) -> str:
    """Возвращает последние n непустых строк."""
    lines = [l for l in text.split("\n") if l.strip()]
    return "\n".join(lines[-n_lines:])


# ============ Одиночная генерация ============
def generate(router, model: str,
             filename: str, task: str, action: str,
             profile_key: str = "code",
             project_files: list = None,
             context_block: str = "",
             requirements: str = "",
             log_func=None) -> str:
    """
    Генерирует код файла. Возвращает чистый код или "" при ошибке.

    requirements — список проблем от судей, которые надо исправить.
    """
    def log(m):
        if log_func:
            log_func(m)

    project_files = project_files or []
    pf_str = "\n".join(f"  • {f}" for f in project_files if f != filename)

    req_block = ""
    if requirements:
        req_block = ("=== ИСПРАВЬ СЛЕДУЮЩИЕ ПРОБЛЕМЫ ===\n" + requirements)

    prompt = prompts.build_coder(
        profile_key=profile_key,
        filename=filename,
        task=task,
        action=action,
        project_files=pf_str or "(нет)",
        context_block=context_block,
        requirements_block=req_block,
    )

    log(f"[coder] {filename} ({len(prompt)} симв)...\n")

    raw = router.chat(
        model, prompt,
        max_tokens=4096,
        temperature=0.2,
        use_cache=False,  # код всегда уникален
    )

    code = extract_code(raw)
    if not code:
        log(f"[coder] ⚠ Пустой ответ\n")
        return ""

    log(f"[coder] ✓ {len(code)} симв\n")
    return code


# ============ Генерация с чанкингом ============
def generate_chunked(router, model: str,
                     filename: str, task: str, action: str,
                     profile_key: str = "code",
                     project_files: list = None,
                     max_chunks: int = 5,
                     context_block: str = "",
                     requirements: str = "",
                     log_func=None) -> tuple:
    """
    Генерирует код с автодобором обрезанных чанков.

    Возвращает (code, chunks_count). chunks_count >= 1.
    Если код полный с первого раза — chunks=1.
    """
    def log(m):
        if log_func:
            log_func(m)

    code = generate(
        router, model, filename, task, action,
        profile_key=profile_key,
        project_files=project_files,
        context_block=context_block,
        requirements=requirements,
        log_func=log_func,
    )
    if not code:
        return "", 0

    chunks = 1
    truncated, reason = detect_truncation(code)

    if not truncated:
        log(f"[coder] ✓ 1 чанк ({len(code)} симв)\n")
        return code, 1

    log(f"[coder] ⚠ Обрезано: {reason}. Догенерирую...\n")

    for i in range(2, max_chunks + 1):
        tail = _tail(code, 40)
        prompt = prompts.build_continue(
            filename=filename,
            tail=tail,
            action=action,
            task=task,
        )

        log(f"[coder] [чанк {i}/{max_chunks}] ...\n")
        try:
            raw = router.chat(
                model, prompt,
                max_tokens=4096,
                temperature=0.2,
                use_cache=False,
            )
        except Exception as e:
            log(f"[coder] ✗ Ошибка: {e}\n")
            break

        cont = extract_code(raw) or raw.strip()
        if not cont or len(cont.strip()) < 10:
            log(f"[coder] ⚠ Пустой чанк\n")
            break

        cleaned = remove_duplicate_prefix(code, cont)
        if not cleaned or len(cleaned.strip()) < 10:
            log(f"[coder] ⚠ Всё дубликат — стоп\n")
            break

        code = code + "\n" + cleaned
        chunks = i
        log(f"[coder] ✓ Чанк {i}: +{len(cleaned)} (итого {len(code)})\n")

        truncated, reason = detect_truncation(code)
        if not truncated:
            log(f"[coder] ✓ Готово! ({chunks} чанков)\n")
            return code, chunks

    log(f"[coder] ⚠ Не удалось добить ({chunks} чанков, осталось обрезано)\n")
    return code, chunks


# ============ Самотест ============
if __name__ == "__main__":
    from sapphira.core.router import get_router

    print("=== coder.py самотест ===\n")

    router = get_router()
    chat_models = router.list_chat_models()
    if not chat_models:
        print("❌ Нет chat-моделей")
        raise SystemExit(1)

    model = chat_models[0]
    print(f"Модель: {model}\n")

    def log(m):
        print(m, end="")

    # Тест 1: простой файл
    print("--- Тест 1: простой файл ---")
    code1 = generate(
        router, model,
        filename="utils.py",
        task="Калькулятор на Python",
        action="Функции add(a,b), sub(a,b), mul(a,b), div(a,b).",
        profile_key="code",
        log_func=log,
    )
    print(f"\nРезультат ({len(code1)} симв):")
    print(code1[:600])
    print("...\n")

    # Тест 2: с чанкингом
    print("--- Тест 2: сложный файл с чанкингом ---")
    code2, chunks = generate_chunked(
        router, model,
        filename="main.py",
        task="Калькулятор на Python",
        action="CLI-интерфейс: принимает команды add/sub/mul/div, "
               "использует функции из utils.py, обрабатывает ошибки.",
        profile_key="code",
        project_files=["utils.py"],
        max_chunks=3,
        log_func=log,
    )
    print(f"\nРезультат: {len(code2)} симв, {chunks} чанков")
    print(code2[:600])

    print("\n✅ coder готов")