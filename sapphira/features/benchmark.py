# -*- coding: utf-8 -*-
"""Benchmark моделей: 5 стандартных тестов + метрики.

Измеряем:
- Скорость: токены/с (приблизительно, через длину ответа / время)
- Качество: % пройденных проверок (0-10 баллов за тест)
- VRAM: пик использования (nvidia-smi)
- Итог: 0.4*скорость_norm + 0.6*качество
"""

import os
import re
import sys
import json
import time
import subprocess
from pathlib import Path


# ─── Хелперы для проверки ответов ───
def _extract_code(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"```(?:python|py)?\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text.strip()


def _extract_json(text: str):
    if not text:
        return None
    text = re.sub(r"```(?:json)?\s*", "", text).replace("```", "")
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        try:
            return json.loads(m.group(0)[:m.group(0).rfind("}") + 1])
        except Exception:
            return None


# ─── Чекеры ───
def check_code_add(answer: str) -> tuple:
    """Возвращает (score 0-10, комментарий)."""
    code = _extract_code(answer)
    if not code:
        return 0, "Пусто"
    if "def add" not in code:
        return 2, "Нет функции add"
    try:
        compile(code, "<test>", "exec")
    except SyntaxError as e:
        return 1, f"SyntaxError: {e.msg}"

    # Проверяем что функция работает
    ns = {}
    try:
        exec(code, ns)
        if "add" not in ns:
            return 3, "add не определена"
        result = ns["add"](2, 3)
        if result == 5:
            return 10, "add(2,3)=5 ✓"
        return 5, f"add(2,3)={result}, ожидалось 5"
    except Exception as e:
        return 3, f"Не выполняется: {e}"


def check_json_answer(answer: str) -> tuple:
    """Проверка JSON ответа."""
    data = _extract_json(answer)
    if data is None:
        return 0, "Не JSON"
    if not isinstance(data, dict):
        return 3, "Не словарь"
    if data.get("status") == "ok" and data.get("count") == 3:
        return 10, "Все ключи верные"
    if "status" in data or "count" in data:
        return 6, "Часть ключей верна"
    return 4, "JSON валиден, но ключи не те"


def check_logic_explanation(answer: str) -> tuple:
    """Объяснение рекурсии — проверяем ключевые слова."""
    if not answer:
        return 0, "Пусто"
    low = answer.lower()
    keywords = [
        ("рекурс", 4),           # упоминает рекурсию
        ("функц", 2),            # говорит о функции
        ("себ", 3),              # вызывает сама себя
        ("услов", 2),            # условие выхода
        ("базов", 2),            # базовый случай
        ("стек", 2),             # стек
    ]
    score = 0
    found = []
    for kw, pts in keywords:
        if kw in low:
            score += pts
            found.append(kw)
    score = min(score, 10)
    comment = f"Ключевые слова: {', '.join(found)}" if found else "Нет ключевых слов"
    return score, comment


def check_bug_fix(answer: str) -> tuple:
    """Поиск фикса деления на ноль."""
    code = _extract_code(answer)
    if not code:
        return 0, "Пусто"
    low = code.lower()

    # Проверяем что в коде есть защита
    if "if" in low and ("== 0" in code or "!= 0" in code or "== 0.0" in code):
        if "zerodivision" in low or "raise" in low:
            return 10, "Защита + исключение"
        return 8, "Защита от деления на ноль"
    if "zerodivision" in low or "try" in low and "except" in low:
        return 7, "Через try/except"
    if "def f" in code:
        return 4, "Код есть, но нет защиты"
    return 2, "Не то"


def check_planning(answer: str) -> tuple:
    """Проверка JSON-плана."""
    data = _extract_json(answer)
    if data is None:
        return 0, "Не JSON"
    if not isinstance(data, dict):
        return 3, "Не словарь"
    steps = data.get("steps") or data.get("plan") or data.get("files")
    if not isinstance(steps, list):
        return 4, "Нет steps"
    if len(steps) < 3:
        return 5, f"Мало шагов: {len(steps)}"
    # Проверяем что каждый шаг — словарь с file/action
    valid = 0
    for s in steps:
        if isinstance(s, dict) and (s.get("file") or s.get("action")):
            valid += 1
    if valid == len(steps):
        return 10, f"{len(steps)} шагов, все валидны"
    return 6, f"{valid}/{len(steps)} шагов валидны"


# ─── Тесты ───
TESTS = [
    {
        "id": "code_add",
        "name": "Простой код",
        "prompt": "Напиши функцию Python add(a, b), возвращающую сумму двух чисел. Только код, без объяснений и примеров.",
        "max_tokens": 150,
        "checker": check_code_add,
    },
    {
        "id": "json",
        "name": "JSON ответ",
        "prompt": 'Верни ровно один JSON-объект, без markdown: {"status": "ok", "count": 3}',
        "max_tokens": 80,
        "checker": check_json_answer,
    },
    {
        "id": "logic",
        "name": "Объяснение",
        "prompt": "Объясни в 2-3 предложениях что такое рекурсия.",
        "max_tokens": 200,
        "checker": check_logic_explanation,
    },
    {
        "id": "bug_fix",
        "name": "Fix бага",
        "prompt": "Вот код с багом:\n```python\ndef f(x):\n    return x / 0\n```\nИсправь так, чтобы не было деления на ноль. Верни только исправленный код.",
        "max_tokens": 150,
        "checker": check_bug_fix,
    },
    {
        "id": "planning",
        "name": "Планирование",
        "prompt": 'Разбей задачу на 3 файла: "Написать парсер CSV с фильтрацией". Верни только JSON: {"steps": [{"file": "имя", "action": "что делать"}, ...]}',
        "max_tokens": 400,
        "checker": check_planning,
    },
]


# ─── VRAM через nvidia-smi ───
def _get_vram_used_mb() -> int:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        if r.returncode == 0:
            return int(r.stdout.strip().split("\n")[0])
    except Exception:
        pass
    return 0


# ─── Основная функция ───
def run_benchmark(model_name: str, router,
                  progress_cb=None, log_cb=None,
                  stop_flag=None) -> dict:
    """
    Запускает 5 тестов на одной модели.

    progress_cb(i, total, test_name) — прогресс
    log_cb(text, level)              — логирование
    stop_flag                        — функция () -> bool (True = остановить)

    Возвращает:
    {
        "model": ...,
        "tests": [{name, score, time, tokens_per_sec, comment}, ...],
        "speed_avg": ...,        # среднее токенов/с
        "quality_avg": ...,      # средний балл 0-10
        "vram_peak_mb": ...,     # пик VRAM
        "final_score": ...,      # итоговый балл 0-10
    }
    """
    def log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)
        print(f"[bench] {msg}")

    total = len(TESTS)

    # Выгружаем ВСЁ что было загружено до нас
    try:
        router.unload_all()
        time.sleep(1.0)
    except Exception:
        pass

    vram_before = _get_vram_used_mb()
    log(f"Старт теста: {model_name}")
    log(f"VRAM до загрузки: {vram_before} МБ")

    # Прогрев — загружаем модель
    log("Прогрев модели...", "info")
    t0 = time.time()
    try:
        router.chat(model_name, "2+2=", max_tokens=5,
                    temperature=0.1, use_cache=False)
    except Exception as e:
        log(f"Ошибка загрузки модели: {e}", "err")
        try:
            router.unload_all()
        except Exception:
            pass
        return {"model": model_name, "error": str(e), "tests": [],
                "speed_avg": 0, "quality_avg": 0, "vram_peak_mb": 0,
                "load_time": 0, "final_score": 0}

    load_time = time.time() - t0
    vram_loaded = _get_vram_used_mb()
    log(f"Модель загружена за {load_time:.1f}с, VRAM: {vram_loaded} МБ",
        "ok")

    results = []
    speed_sum = 0
    quality_sum = 0
    vram_peak = vram_loaded

    for i, test in enumerate(TESTS):
        if stop_flag and stop_flag():
            log("Остановлено пользователем", "warn")
            break

        if progress_cb:
            progress_cb(i, total, test["name"])

        log(f"[{i+1}/{total}] {test['name']}...", "info")
        t0 = time.time()
        try:
            answer = router.chat(
                model_name, test["prompt"],
                max_tokens=test["max_tokens"],
                temperature=0.2,
                use_cache=False,
            )
            elapsed = time.time() - t0
        except Exception as e:
            log(f"  Ошибка: {e}", "err")
            results.append({
                "id": test["id"], "name": test["name"],
                "score": 0, "time": 0, "tps": 0,
                "comment": f"Ошибка: {e}",
            })
            continue

        # Оценка
        score, comment = test["checker"](answer)
        # Токенов ≈ len(answer)/4
        approx_tokens = max(len(answer) // 4, 1)
        tps = round(approx_tokens / max(elapsed, 0.1), 1)

        # VRAM пик
        cur_vram = _get_vram_used_mb()
        vram_peak = max(vram_peak, cur_vram)

        results.append({
            "id": test["id"],
            "name": test["name"],
            "score": score,
            "time": round(elapsed, 2),
            "tps": tps,
            "comment": comment,
        })
        speed_sum += tps
        quality_sum += score
        log(f"  ✓ {score}/10  ({tps} т/с, {elapsed:.1f}с)  {comment}",
            "ok")

    if progress_cb:
        progress_cb(total, total, "Готово")

    # Метрики
    n = len(results) or 1
    speed_avg = round(speed_sum / n, 1)
    quality_avg = round(quality_sum / n, 2)
    vram_peak_mb = vram_peak - vram_before if vram_peak > vram_before else 0

    # Нормированная скорость: 0.1 * sqrt(tps) (мягкое сглаживание)
    speed_norm = min(10, (speed_avg ** 0.5) * 1.2)
    # Итог: 40% скорость + 60% качество
    final_score = round(0.4 * speed_norm + 0.6 * quality_avg, 2)

    log(f"ИТОГ: скорость={speed_avg} т/с, качество={quality_avg}/10, "
        f"VRAM={vram_peak_mb} МБ, балл={final_score}", "ok")

    # Выгружаем модель после теста
    try:
        router.unload_all()
        time.sleep(1.0)
    except Exception:
        pass

    return {
        "model": model_name,
        "tests": results,
        "speed_avg": speed_avg,
        "quality_avg": quality_avg,
        "vram_peak_mb": vram_peak_mb,
        "load_time": round(load_time, 1),
        "final_score": final_score,
    }


# ─── Самотест ───
if __name__ == "__main__":
    print("=== benchmark.py самотест ===\n")

    # Тестируем чекеры
    print("1. check_code_add('def add(a, b): return a + b'):")
    print("  ", check_code_add("def add(a, b):\n    return a + b"))

    print("\n2. check_json_answer('{\"status\": \"ok\", \"count\": 3}'):")
    print("  ", check_json_answer('{"status": "ok", "count": 3}'))

    print("\n3. check_logic_explanation('Рекурсия - это когда функция вызывает саму себя. Есть базовый случай для выхода.'):")
    print("  ", check_logic_explanation(
        "Рекурсия - это когда функция вызывает саму себя. "
        "Есть базовый случай для выхода."))

    print("\n4. check_bug_fix('def f(x):\\n    if x == 0:\\n        raise ZeroDivisionError\\n    return 1/x'):")
    print("  ", check_bug_fix(
        "def f(x):\n    if x == 0:\n        raise ZeroDivisionError\n    return 1/x"))

    print("\n5. check_planning('{\"steps\": [{\"file\": \"a\", \"action\": \"b\"}, ...]}'):")
    print("  ", check_planning(
        '{"steps": [{"file": "a", "action": "b"}, '
        '{"file": "c", "action": "d"}, {"file": "e", "action": "f"}]}'))

    print("\n✅ benchmark готов")