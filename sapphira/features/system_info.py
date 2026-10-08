# -*- coding: utf-8 -*-
"""Информация о системе: CPU, RAM, GPU, VRAM.
Результат кэшируется — nvidia-smi запускается один раз за сессию."""

import platform
import subprocess
import re


_cache = None


def _run(cmd, timeout=5):
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return r.returncode, (r.stdout or "").strip()
    except Exception:
        return -1, ""


def _cpu_name() -> str:
    try:
        return platform.processor() or "Неизвестный CPU"
    except Exception:
        return "Неизвестный CPU"


def _ram_gb() -> float:
    try:
        import psutil
        return round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except ImportError:
        code, out = _run(["wmic", "ComputerSystem", "get", "TotalPhysicalMemory"])
        m = re.search(r"(\d+)", out)
        if m:
            return round(int(m.group(1)) / (1024 ** 3), 1)
    return 0.0


def _gpu_info():
    """Возвращает (имя, VRAM_МБ)."""
    code, out = _run([
        "nvidia-smi", "--query-gpu=name,memory.total",
        "--format=csv,noheader,nounits",
    ])
    if code == 0 and out:
        first = out.split("\n")[0]
        parts = [p.strip() for p in first.split(",")]
        if len(parts) >= 2:
            try:
                return parts[0], int(parts[1])
            except ValueError:
                pass
    return "Не найдена", 0


def get_system_report(force=False) -> dict:
    """Возвращает {cpu, ram_gb, gpu, vram_mb}. Кэшируется."""
    global _cache
    if _cache is not None and not force:
        return _cache
    gpu_name, vram = _gpu_info()
    _cache = {
        "cpu": _cpu_name(),
        "ram_gb": _ram_gb(),
        "gpu": gpu_name,
        "vram_mb": vram,
    }
    return _cache


def recommend_models(report: dict = None) -> list:
    """Текстовые рекомендации по размеру моделей."""
    if report is None:
        report = get_system_report()
    vram = report.get("vram_mb", 0)
    if vram >= 24000:
        return ["30B+ модели (Q4_K_M)"]
    if vram >= 16000:
        return ["14B–20B модели (Q4_K_M)"]
    if vram >= 12000:
        return ["14B модели (Q4_K_M)"]
    if vram >= 8000:
        return ["7B–8B модели (Q4_K_M)"]
    if vram >= 6000:
        return ["7B модели (Q4_K_M)"]
    return ["3B–7B модели (Q4_K_M) или CPU-режим"]


if __name__ == "__main__":
    print("=== system_info самотест ===\n")
    r = get_system_report(force=True)
    print(f"CPU:   {r['cpu']}")
    print(f"RAM:   {r['ram_gb']} ГБ")
    print(f"GPU:   {r['gpu']}")
    print(f"VRAM:  {r['vram_mb']} МБ\n")
    print("Рекомендации:")
    for rec in recommend_models(r):
        print(f"  • {rec}")