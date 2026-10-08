# -*- coding: utf-8 -*-
"""ProjectEditor — режим улучшения существующего проекта.

Использует тот же pipeline что upgrade_loop, но:
- Одна итерация (не бесконечно)
- Задача задаётся пользователем
- Работает с любым проектом (не только Sapphira)
"""

import os
import re
import ast
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Импортируем утилиты
from sapphira.utils.code import (
    extract_code, extract_json, validate_syntax,
    detect_truncation, topological_sort,
)


PROMPT_ANALYZE_PROJECT = """Ты — аналитик проекта. Пользователь хочет улучшить существующий проект.

ЗАДАЧА ПОЛЬЗОВАТЕЛЯ:
{task}

ФАЙЛЫ ПРОЕКТА ({n_files} файлов, папка: {root}):
{file_list}

ОПРЕДЕЛИ, какие файлы нужно изменить для выполнения задачи.

Ответь JSON:
{{
  "files_to_change": [
    {{"file": "относительный/путь.py", "action": "что сделать с файлом"}},
    ...
  ],
  "summary": "общая суть изменений"
}}

ПРАВИЛА:
- Только файлы, которые реально нужно править (не более 7).
- Если задача касается одного файла — только он.
- Если нужен новый файл — не указывай его здесь (он будет создан).
- Если задача непонятна — верни {{"files_to_change": [], "summary": "не понял"}}.

ОТВЕТ: только JSON.
"""

PROMPT_IMPROVE_FILE = """Ты — опытный разработчик. Измени файл СТРОГО по задаче.

ЗАДАЧА:
{task}

ФАЙЛ: {filename}
ЧТО СДЕЛАТЬ: {action}

ТЕКУЩИЙ КОД:
{code}

КРИТИЧЕСКИ ВАЖНО:
1. Верни ВЕСЬ файл целиком в одном блоке ```python ... ```.
2. Внеси МИНИМАЛЬНЫЕ изменения — только то, что требует задача.
3. НЕ переписывай существующие функции, docstrings, комментарии.
4. Если задача про добавление комментария/строки — просто добавь их, остальное не трогай.
5. Проверь что ВСЕ тройные кавычки закрыты парно.
6. Проверь что все скобки и отступы корректны.

ОТВЕТ: только блок ```python ... ``` без пояснений.
"""


def _collect_files(root: Path, max_files: int = 100):
    """Собирает .py, .md, .js файлы в проекте."""
    result = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".py", ".md", ".txt", ".js", ".ts", ".json"):
            continue
        # Исключения
        parts = set(p.parts)
        if parts & {"__pycache__", "node_modules", ".git", "venv", ".venv",
                     "backups", "_upgrade_backup", "snapshots"}:
            continue
        try:
            size = p.stat().st_size
        except Exception:
            continue
        if size > 500_000:  # > 500 КБ — пропускаем
            continue
        result.append(p)
        if len(result) >= max_files:
            break
    return result


class ProjectEditor:
    def __init__(self, router, coder_model, judge_model,
                 log_func=None):
        self.router = router
        self.coder = coder_model
        self.judge = judge_model
        self.log = log_func or print
        self.backup_dir = None
        self.changed_files = []
        self.failed_files = []
        self.skipped_files = []

    def _backup(self, path: Path):
        if self.backup_dir is None:
            self.backup_dir = path.parent / "_edit_backup" / \
                datetime.now().strftime("%Y%m%d_%H%M%S")
            self.backup_dir.mkdir(parents=True, exist_ok=True)
        dest = self.backup_dir / path.name
        try:
            shutil.copy2(path, dest)
            return dest
        except Exception:
            return None

    def _test_python(self, path: Path, timeout: int = 30):
        """Проверяет что .py файл синтаксически валиден."""
        try:
            code = path.read_text(encoding="utf-8", errors="replace")
            compile(code, str(path), "exec")
            return True, "syntax OK"
        except SyntaxError as e:
            return False, f"SyntaxError: {e}"
        except Exception as e:
            return False, str(e)

    # ============ Анализ ============
    def analyze(self, root: Path, task: str):
        files = _collect_files(root)
        if not files:
            self.log(f"[edit] В {root} нет подходящих файлов", "WARN")
            return []

        # Формируем список
        lines = []
        for f in files:
            rel = f.relative_to(root).as_posix()
            try:
                size = f.stat().st_size
                lines.append(f"  {rel} ({size} байт)")
            except Exception:
                lines.append(f"  {rel}")
        file_list = "\n".join(lines)

        prompt = PROMPT_ANALYZE_PROJECT.format(
            task=task, root=root,
            n_files=len(files), file_list=file_list)

        self.log(f"[edit] Анализирую {len(files)} файлов...", "INFO")
        try:
            raw = self.router.chat(self.coder, prompt,
                                    max_tokens=2000, temperature=0.3,
                                    use_cache=False)
        except Exception as e:
            self.log(f"[edit] Ошибка анализа: {e}", "ERROR")
            return []

        data = extract_json(raw)
        if not data or not isinstance(data, dict):
            self.log(f"[edit] Не удалось разобрать ответ LLM", "WARN")
            self.log(f"  {raw[:300]}", "WARN")
            return []

        files_to_change = data.get("files_to_change", [])
        summary = data.get("summary", "")
        self.log(f"[edit] План: {summary}", "INFO")
        self.log(f"[edit] Файлов к правке: {len(files_to_change)}", "INFO")
        for item in files_to_change:
            self.log(f"  → {item.get('file')}: {item.get('action','')[:60]}", "INFO")

        return files_to_change

    # ============ Правка одного файла ============
    def edit_one(self, root: Path, rel_file: str, action: str, task: str):
        path = root / rel_file
        if not path.exists():
            self.log(f"[edit] Файл не найден: {rel_file}", "WARN")
            self.skipped_files.append(rel_file)
            return False

        try:
            original = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            self.log(f"[edit] Не читается {rel_file}: {e}", "ERROR")
            self.skipped_files.append(rel_file)
            return False

        prompt = PROMPT_IMPROVE_FILE.format(
            task=task, filename=rel_file, action=action, code=original)

        self.log(f"[edit] Правлю {rel_file}...", "INFO")
        t0 = time.time()
        try:
            raw = self.router.chat(self.coder, prompt,
                                    max_tokens=8192, temperature=0.3,
                                    use_cache=False)
        except Exception as e:
            self.log(f"[edit] Ошибка LLM: {e}", "ERROR")
            self.failed_files.append(rel_file)
            return False
        self.log(f"[edit]   <- {time.time()-t0:.1f}s", "INFO")

        new_code = extract_code(raw)
        if not new_code:
            self.log(f"[edit] Пустой ответ", "WARN")
            self.failed_files.append(rel_file)
            return False

        if new_code.strip() == original.strip():
            self.log(f"[edit] Без изменений", "WARN")
            self.skipped_files.append(rel_file)
            return False

        # Синтаксис
        if path.suffix == ".py":
            try:
                compile(new_code, str(path), "exec")
            except SyntaxError as e:
                self.log(f"[edit] SyntaxError: {e}", "WARN")
                self.failed_files.append(rel_file)
                return False

        # Backup
        self._backup(path)

        # Записать
        try:
            path.write_text(new_code, encoding="utf-8")
        except Exception as e:
            self.log(f"[edit] Не записать: {e}", "ERROR")
            self.failed_files.append(rel_file)
            return False

        # Тест для .py
        if path.suffix == ".py":
            ok, msg = self._test_python(path)
            if not ok:
                # Откат
                if self.backup_dir:
                    backup = self.backup_dir / path.name
                    if backup.exists():
                        shutil.copy2(backup, path)
                self.log(f"[edit] Откат {rel_file}: {msg}", "WARN")
                self.failed_files.append(rel_file)
                return False

        self.log(f"[edit]   ✅ {rel_file} ({len(original)} → {len(new_code)})", "OK")
        self.changed_files.append(rel_file)
        return True

    # ============ Главный метод ============
    def run(self, root_path: str, task: str):
        root = Path(root_path).resolve()
        if not root.is_dir():
            self.log(f"[edit] Не папка: {root}", "ERROR")
            return {"ok": False, "error": "не папка"}

        self.log("=" * 60, "INFO")
        self.log(f"[edit] Проект: {root}", "INFO")
        self.log(f"[edit] Задача: {task}", "INFO")
        self.log("=" * 60, "INFO")

        files_to_change = self.analyze(root, task)
        if not files_to_change:
            self.log("[edit] Нечего менять", "WARN")
            return {"ok": False, "error": "нет файлов к правке",
                    "changed": [], "failed": [], "skipped": []}

        for item in files_to_change:
            rel = item.get("file", "").replace("\\", "/").lstrip("/")
            action = item.get("action", "улучшить")
            if not rel:
                continue
            self.edit_one(root, rel, action, task)

        # Итог
        self.log("=" * 60, "INFO")
        self.log(f"[edit] Изменено: {len(self.changed_files)}", "OK")
        self.log(f"[edit] Провалено: {len(self.failed_files)}", "WARN")
        self.log(f"[edit] Пропущено: {len(self.skipped_files)}", "INFO")
        if self.backup_dir:
            self.log(f"[edit] Backup: {self.backup_dir}", "INFO")
        self.log("=" * 60, "INFO")

        return {
            "ok": len(self.changed_files) > 0,
            "changed": self.changed_files,
            "failed": self.failed_files,
            "skipped": self.skipped_files,
            "backup": str(self.backup_dir) if self.backup_dir else None,
        }


if __name__ == "__main__":
    print("=== project_editor.py самотест ===")
    print("Модуль готов. Для теста нужен Router и запущенная Sapphira.")