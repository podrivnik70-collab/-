# -*- coding: utf-8 -*-
"""report_builder.py - Человекочитаемый отчёт о модернизации v3.

Читает upgrade_log.md и бэкапы, строит upgrade_report.md
с diff-ами, метриками и вердиктами судьи.
"""

import os
import re
import sys
import json
import difflib
import argparse
from datetime import datetime
from pathlib import Path


def parse_log(log_path):
    """Парсит upgrade_log.md и возвращает список записей (только успешные)."""
    if not log_path.exists():
        return []

    text = log_path.read_text(encoding="utf-8", errors="replace")
    entries = []
    current = None

    for line in text.split("\n"):
        line = line.rstrip()

        # Заголовок файла (строка может быть "## path.py" или "### [ts] ## path.py")
        m = re.search(r"##\s+(sapphira/[\w/\.\-]+\.py)", line)
        if m:
            if current and current.get("result") == "✅":
                entries.append(current)
            current = {"file": m.group(1), "attempts": [], "result": "?"}
            continue

        # Цель
        m = re.search(r"\*\*Цель:\*\*\s+(.+?)$", line)
        if m and current:
            current["goal"] = m.group(1).strip()
            continue

        # Попытка с результатом
        m = re.search(r"- попытка (\d+):\s*(.+?)$", line)
        if m and current:
            status = m.group(2).strip()
            current["attempts"].append({"n": int(m.group(1)), "status": status})
            if "✅" in status or "применено" in status:
                current["result"] = "✅"
            elif "❌" in status:
                current["result"] = "❌"
            continue

    if current and current.get("result") == "✅":
        entries.append(current)

    # Если ни один не помечен ✅ — возвращаем все (не теряем данные)
    if not entries:
        return [e for e in [current] if e]
    return entries


def parse_console_log(v2_root):
    """Парсит stdout вывод (сохранённый из консоли пользователем — опционально)."""
    return []


def find_backups(v3_root, file_rel_path):
    """Находит все версии бэкапа для файла, отсортированные по времени."""
    backup_root = v3_root / "_upgrade_backup"
    if not backup_root.exists():
        return []

    target = Path(file_rel_path).name
    found = []
    for session_dir in sorted(backup_root.iterdir()):
        if not session_dir.is_dir():
            continue
        for f in session_dir.iterdir():
            if f.name == target or f.name.endswith("__" + target):
                found.append(f)
    return found


def count_functions(code):
    """Считает количество def и class через ast."""
    import ast
    try:
        tree = ast.parse(code)
        n_func = sum(1 for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        n_cls = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
        return n_func, n_cls
    except Exception:
        return 0, 0


def build_diff(old_code, new_code, max_lines=40):
    """Возвращает unified diff (первые N строк)."""
    diff = list(difflib.unified_diff(
        old_code.splitlines(), new_code.splitlines(),
        fromfile="before", tofile="after", lineterm="", n=2))
    if len(diff) > max_lines:
        diff = diff[:max_lines] + ["... (diff обрезан)"]
    return "\n".join(diff)


def build_report(v2_root, v3_root, output_path=None):
    v2_root = Path(v2_root).resolve()
    v3_root = Path(v3_root).resolve()
    log_path = v3_root / "upgrade_log.md"
    if output_path is None:
        output_path = v3_root / "upgrade_report.md"

    entries = parse_log(log_path)
    if not entries:
        print(f"[report] Нет данных в {log_path}")
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"# Отчёт о модернизации Sapphira v3",
        f"",
        f"**Дата:** {now}",
        f"**Источник:** `{v2_root}`",
        f"**Цель:**   `{v3_root}`",
        f"",
        f"## Сводка",
        f"",
        f"| Файл | Было | Стало | Δ | Функции | Итог |",
        f"|------|------|-------|---|---------|------|",
    ]

    total_old = 0
    total_new = 0
    n_ok = 0
    n_fail = 0

    details = []

    for e in entries:
        file_rel = e["file"]
        new_file = v3_root / file_rel
        if not new_file.exists():
            continue

        new_code = new_file.read_text(encoding="utf-8", errors="replace")
        new_size = len(new_code)

        # Ищем backup (старый)
        backups = find_backups(v3_root, file_rel)
        old_code = None
        old_size = 0
        if backups:
            oldest = backups[0]
            try:
                old_code = oldest.read_text(encoding="utf-8", errors="replace")
                old_size = len(old_code)
            except Exception:
                pass

        if old_code is None:
            # fallback: берём файл из v2 (оригинал)
            old_file = v2_root / file_rel
            if old_file.exists():
                old_code = old_file.read_text(encoding="utf-8", errors="replace")
                old_size = len(old_code)

        delta = new_size - old_size
        delta_str = f"{delta:+d}" if old_size else "?"
        n_func_old, n_cls_old = count_functions(old_code) if old_code else (0, 0)
        n_func_new, n_cls_new = count_functions(new_code)
        func_str = f"{n_func_new}({n_func_new - n_func_old:+d})"

        # Определяем результат
        result = "?"
        for a in e["attempts"]:
            if "✅" in a["status"] or "применено" in a["status"]:
                result = "✅"
                break
            if "❌" in a["status"]:
                result = "❌"

        if result == "✅":
            n_ok += 1
        elif result == "❌":
            n_fail += 1

        total_old += old_size
        total_new += new_size

        lines.append(
            f"| `{Path(file_rel).name}` | {old_size} | {new_size} | "
            f"{delta_str} | {func_str} | {result} |"
        )

        # Собираем детали
        details.append({
            "file": file_rel,
            "goal": e.get("goal", "—"),
            "old_code": old_code or "",
            "new_code": new_code,
            "old_size": old_size,
            "new_size": new_size,
            "delta": delta,
            "func_old": (n_func_old, n_cls_old),
            "func_new": (n_func_new, n_cls_new),
            "attempts": e["attempts"],
            "result": result,
        })

    total_delta = total_new - total_old
    lines += [
        f"",
        f"**Итого:** обработано {len(entries)} файлов, "
        f"{n_ok} успешно, {n_fail} провалено.",
        f"Общий объём: {total_old} → {total_new} симв "
        f"({total_delta:+d}, {total_delta * 100 // max(total_old, 1)}%)",
        f"",
        f"---",
        f"",
        f"## Детали по файлам",
        f"",
    ]

    for d in details:
        lines.append(f"### {d['result']} `{d['file']}`")
        lines.append(f"")
        lines.append(f"**Цель:** {d['goal']}")
        lines.append(f"**Размер:** {d['old_size']} → {d['new_size']} "
                     f"({d['delta']:+d})")
        lines.append(f"**Функций:** {d['func_old'][0]} → {d['func_new'][0]} "
                     f"({d['func_new'][0] - d['func_old'][0]:+d}), "
                     f"классов: {d['func_old'][1]} → {d['func_new'][1]}")
        lines.append(f"")
        if d["attempts"]:
            lines.append(f"**Попытки:**")
            for a in d["attempts"]:
                lines.append(f"- Попытка {a['n']}: {a['status']}")
            lines.append(f"")
        if d["old_code"] and d["new_code"] and d["old_code"] != d["new_code"]:
            diff_text = build_diff(d["old_code"], d["new_code"])
            lines.append(f"**Изменения (diff):**")
            lines.append(f"")
            lines.append("```diff")
            lines.append(diff_text)
            lines.append("```")
            lines.append(f"")
        lines.append(f"---")
        lines.append(f"")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[report] Отчёт: {output_path}")
    print(f"[report] Файлов: {len(entries)}, OK: {n_ok}, FAIL: {n_fail}")
    return output_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v2", default=None,
                    help="Путь к v2 (по умолчанию: где лежит скрипт)")
    ap.add_argument("--v3", required=True,
                    help="Путь к v3")
    ap.add_argument("--output", default=None,
                    help="Куда сохранить отчёт")
    args = ap.parse_args()

    v2 = args.v2 or Path(__file__).resolve().parent
    build_report(v2, args.v3, args.output)


if __name__ == "__main__":
    main()