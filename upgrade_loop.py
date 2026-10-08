# -*- coding: utf-8 -*-
"""upgrade_loop.py - Цикл самомодернизации Sapphira v3."""

import os
import re
import sys
import json
import time
import shutil
import argparse
import subprocess
from datetime import datetime
from pathlib import Path

V2_ROOT = Path(__file__).resolve().parent
TARGET_ROOT = None


def _assert_safe(path):
    path = path.resolve()
    v2 = V2_ROOT.resolve()
    tgt = TARGET_ROOT.resolve()
    if str(path).startswith(str(v2)):
        raise RuntimeError(f"[STOP] v2! {path}")
    if not str(path).startswith(str(tgt)):
        raise RuntimeError(f"[STOP] вне v3! {path}")


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--hours", type=float, default=6.0)
    ap.add_argument("--coder", default="Qwen3.5-9B")
    ap.add_argument("--judge", default="Qwen2.5-Coder-7B-Instruct")
    ap.add_argument("--minutes-per-file", type=int, default=15)
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--tasks", default="upgrade_tasks.json")
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args()


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


def log_md(path, msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n### [{ts}] {msg}\n")
    except Exception:
        pass


def extract_code(text):
    if not text:
        return None
    m = re.search(r"```(?:python|py)?\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r"```\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    if re.match(r"^\s*(import |from |def |class |#)", text):
        return text.strip()
    return None


def extract_json(text):
    if not text:
        return None
    text = re.sub(r"```(?:json)?\s*", "", text).replace("```", "")
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    raw = m.group(0)
    try:
        return json.loads(raw)
    except Exception:
        try:
            return json.loads(raw[:raw.rfind("}") + 1])
        except Exception:
            return None


PROMPT_IMPROVE = """Ты - опытный Python-разработчик. Улучшаешь код Sapphira.

ЦЕЛЬ:
{goal}

КОД ФАЙЛА ({filename}, {lines} строк):
{code}

ТРЕБОВАНИЯ:
1. Верни ВЕСЬ файл целиком в одном python-блоке.
2. Сохрани публичные функции/классы.
3. Не добавляй внешних зависимостей.
4. PEP-8.

ОТВЕТ: только python-блок с полным файлом.
"""

PROMPT_JUDGE = """Проверь код.

ЦЕЛЬ: {goal}

КОД:
{code}

Ответь JSON:
{{"ok": true/false, "problems": [], "summary": ""}}
"""


def module_name_for(path):
    try:
        rel = path.relative_to(TARGET_ROOT / "sapphira")
        parts = list(rel.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        return "sapphira." + ".".join(parts)
    except Exception:
        return None


def test_module(path, timeout=60):
    mod = module_name_for(path)
    if not mod:
        try:
            src = path.read_text(encoding="utf-8")
            compile(src, str(path), "exec")
            return True, "syntax OK"
        except SyntaxError as e:
            return False, f"SyntaxError: {e}"
        except Exception as e:
            return False, str(e)
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(TARGET_ROOT)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        r = subprocess.run(
            [sys.executable, "-m", mod],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            cwd=str(TARGET_ROOT), env=env,
            creationflags=subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode == 0, out[:2000]
    except subprocess.TimeoutExpired:
        return False, f"Timeout {timeout}s"
    except Exception as e:
        return False, str(e)


class LLM:
    def __init__(self, coder, judge):
        sys.path.insert(0, str(V2_ROOT))
        from sapphira.core.router import get_router
        self.router = get_router()
        self.coder = coder
        self.judge = judge
        available = self.router.list_chat_models()
        log(f"Модели: {available}")
        for role, m in [("coder", coder), ("judge", judge)]:
            if m not in available:
                fb = available[0] if available else m
                log(f"[!] '{m}' не найдена ({role}), использую {fb}", "WARN")
                if role == "coder":
                    self.coder = fb
                else:
                    self.judge = fb

    def improve(self, filename, code, goal):
        prompt = PROMPT_IMPROVE.format(
            goal=goal, filename=filename,
            lines=len(code.split("\n")), code=code)
        try:
            raw = self.router.chat(self.coder, prompt,
                                    max_tokens=8192, temperature=0.3,
                                    use_cache=False)
            return extract_code(raw), raw
        except Exception as e:
            log(f"improve error: {e}", "ERROR")
            return None, str(e)

    def judge_check(self, code, goal):
        prompt = PROMPT_JUDGE.format(goal=goal, code=code[:6000])
        try:
            raw = self.router.chat(self.judge, prompt,
                                    max_tokens=512, temperature=0.1,
                                    use_cache=False)
            return extract_json(raw) or {}
        except Exception as e:
            log(f"judge error: {e}", "ERROR")
            return {}


class UpgradeLoop:
    def __init__(self, args):
        self.args = args
        self.deadline = time.time() + args.hours * 3600
        self.stop_file = V2_ROOT / "STOP"
        self.tasks_file = V2_ROOT / args.tasks
        self.backup_dir = (TARGET_ROOT / "_upgrade_backup"
                           / datetime.now().strftime("%Y%m%d_%H%M%S"))
        self.log_file_path = TARGET_ROOT / "upgrade_log.md"
        # log_file не используется
        self.llm = LLM(coder=args.coder, judge=args.judge)
        self.stats = {
            "files_processed": 0, "files_success": 0, "files_failed": 0,
            "attempts_total": 0, "attempts_ok": 0, "attempts_rollback": 0,
        }

    def stop_requested(self):
        return self.stop_file.exists()

    def run(self):
        log("=" * 60)
        log("UPGRADE LOOP STARTED")
        log(f"  from: {V2_ROOT}")
        log(f"  to:   {TARGET_ROOT}")
        log(f"  hours: {self.args.hours}")
        log(f"  coder: {self.llm.coder}")
        log(f"  judge: {self.llm.judge}")
        log("=" * 60)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # Архивируем старый лог, чтобы не копить записи
        if self.log_file_path.exists():
            try:
                old = self.log_file_path.read_text(encoding="utf-8")
                if old.strip():
                    archive = self.log_file_path.with_suffix(".prev.md")
                    archive.write_text(old, encoding="utf-8")
                    self.log_file_path.write_text("", encoding="utf-8")
            except Exception:
                pass

        log_md(self.log_file_path, f"# Запуск на {self.args.hours}ч")
        tasks = self.load_tasks()
        log(f"Задач: {len(tasks)}")
        for task in tasks:
            if time.time() >= self.deadline:
                log("Время вышло", "WARN")
                break
            if self.stop_requested():
                log("STOP файл", "WARN")
                break
            self.process_task(task)
        log_md(self.log_file_path,
               f"Итоги: processed={self.stats['files_processed']}, "
               f"OK={self.stats['files_success']}, "
               f"FAIL={self.stats['files_failed']}")
        log("=" * 60)
        log(f"DONE. OK={self.stats['files_success']} FAIL={self.stats['files_failed']}")
        log("=" * 60)

        # Автогенерация отчёта
        try:
            sys.path.insert(0, str(V2_ROOT))
            from report_builder import build_report
            log("Генерирую отчёт...")
            rpt = build_report(V2_ROOT, TARGET_ROOT)
            if rpt:
                log(f"Отчёт: {rpt}")
        except Exception as e:
            log(f"Отчёт не сгенерирован: {e}", "WARN")

    def load_tasks(self):
        if not self.tasks_file.exists():
            log(f"Нет файла {self.tasks_file}", "ERROR")
            return []
        with open(self.tasks_file, "r", encoding="utf-8") as f:
            return json.load(f).get("tasks", [])

    def process_task(self, task):
        rel_path = task.get("file")
        goal = task.get("goal", "улучшить код")
        if not rel_path:
            return
        target = TARGET_ROOT / rel_path
        if not target.exists():
            log(f"[!] Нет файла: {target}", "WARN")
            return
        try:
            _assert_safe(target)
        except RuntimeError as e:
            log(str(e), "ERROR")
            return
        log(f"\n{'-' * 60}")
        log(f"FILE: {rel_path}")
        log(f"GOAL: {goal[:80]}")
        log(f"{'-' * 60}")
        log_md(self.log_file_path, f"\n## {rel_path}")
        log_md(self.log_file_path, f"**Цель:** {goal}")
        self.stats["files_processed"] += 1
        file_start = time.time()
        success = False
        for attempt in range(1, self.args.max_attempts + 1):
            if time.time() - file_start > self.args.minutes_per_file * 60:
                log(f"Timeout - skip", "WARN")
                break
            if self.stop_requested() or time.time() >= self.deadline:
                break
            self.stats["attempts_total"] += 1
            log(f"\n> Попытка {attempt}/{self.args.max_attempts}")
            try:
                original = target.read_text(encoding="utf-8")
            except Exception as e:
                log(f"Не читается: {e}", "ERROR")
                break
            log(f"  -> {self.llm.coder} ({len(original)} симв)...")
            t0 = time.time()
            new_code, raw = self.llm.improve(rel_path, original, goal)
            log(f"  <- {time.time()-t0:.1f}s")

            # Детектор отсутствия изменений
            if new_code and new_code.strip() == original.strip():
                log("  ~ без изменений", "WARN")
                log_md(self.log_file_path,
                       f"- попытка {attempt}: без изменений")
                break

            if not new_code:
                log("  x нет кода", "WARN")
                continue
            if len(new_code) < 50:
                log(f"  x коротко ({len(new_code)})", "WARN")
                continue
            try:
                compile(new_code, str(target), "exec")
            except SyntaxError as e:
                log(f"  x SyntaxError: {e}", "WARN")
                continue
            backup_path = self.backup_dir / Path(rel_path).name
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup_path)
            log("  backup OK")
            try:
                target.write_text(new_code, encoding="utf-8")
            except Exception as e:
                log(f"  x не записать: {e}", "ERROR")
                shutil.copy2(backup_path, target)
                continue
            log("  тест...")
            ok_test, out = test_module(target)
            if not ok_test:
                log(f"  x тест упал: {out[:200]}", "WARN")
                shutil.copy2(backup_path, target)
                self.stats["attempts_rollback"] += 1
                log("  rollback")
                log_md(self.log_file_path,
                       f"- попытка {attempt}: ❌ тест упал, откат")
                continue
            log("  модуль OK")
            log("  судья...")
            verdict = self.llm.judge_check(new_code, goal)
            if verdict.get("ok") is False:
                log("  судья против (оставляю)", "WARN")
            log(f"  УСПЕХ ({len(original)} -> {len(new_code)})")
            log_md(self.log_file_path,
                   f"- попытка {attempt}: ✅ применено "
                   f"({len(original)} -> {len(new_code)})")
            self.stats["attempts_ok"] += 1
            success = True
            log_md(self.log_file_path, f"- OK ({len(original)} -> {len(new_code)})")
            break
        if success:
            self.stats["files_success"] += 1
        else:
            self.stats["files_failed"] += 1
            log("  FAIL")
            log_md(self.log_file_path, f"- ❌ не улучшено")


def main():
    global TARGET_ROOT
    args = parse_args()
    TARGET_ROOT = Path(args.target).resolve()
    if not TARGET_ROOT.exists():
        print(f"[!] Нет папки: {TARGET_ROOT}")
        return
    if not (TARGET_ROOT / "sapphira").is_dir():
        print(f"[!] Нет sapphira в {TARGET_ROOT}")
        return
    if TARGET_ROOT == V2_ROOT.resolve():
        print("[!] TARGET = v2 - запрещено!")
        return
    if args.dry_run:
        with open(V2_ROOT / args.tasks, "r", encoding="utf-8") as f:
            tasks = json.load(f).get("tasks", [])
        print("=" * 60)
        print(f"DRY RUN: {len(tasks)} файлов")
        print(f"  from: {V2_ROOT}")
        print(f"  to:   {TARGET_ROOT}")
        print("=" * 60)
        for t in tasks:
            target = TARGET_ROOT / t["file"]
            exists = "OK" if target.exists() else "NO"
            print(f"  [{exists}] {t['file']:<40} -> {t['goal'][:60]}")
        return
    loop = UpgradeLoop(args)
    try:
        loop.run()
    except KeyboardInterrupt:
        log("\nПрервано", "WARN")


if __name__ == "__main__":
    main()
