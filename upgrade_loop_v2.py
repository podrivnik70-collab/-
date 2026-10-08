# -*- coding: utf-8 -*-
"""upgrade_loop_v2.py - Цикл самомодернизации с auto-extend.

Отличия от v1:
- Когда задачи в upgrade_tasks.json закончились, LLM генерирует новые.
- Каждые N кругов вызывается project_hunter для свежих идей.
- Помнит историю улучшений (не повторяется).
- Стоп после 3 пустых кругов подряд (или deadline).
"""

import os
import re
import sys
import json
import time
import shutil
import argparse
import subprocess
import io
from datetime import datetime
from pathlib import Path

# UTF-8 для stdout/stderr
try:
    if sys.stdout and hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                       errors="replace", line_buffering=True)
    if sys.stderr and hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                       errors="replace", line_buffering=True)
except Exception:
    pass

V2_ROOT = Path(__file__).resolve().parent
TARGET_ROOT = None
STOP_FILE = V2_ROOT / "STOP"


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
    ap.add_argument("--hours", type=float, default=8.0)
    ap.add_argument("--coder", default="Qwen3.5-9B")
    ap.add_argument("--judge", default="Qwen2.5-Coder-7B-Instruct")
    ap.add_argument("--planner", default=None, help="Модель для генерации задач")
    ap.add_argument("--minutes-per-file", type=int, default=20)
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--tasks", default="upgrade_tasks.json")
    ap.add_argument("--auto-extend", action="store_true",
                    help="Генерировать новые задачи при пустом списке")
    ap.add_argument("--hunter-every", type=int, default=2,
                    help="Каждые N кругов запускать project_hunter")
    ap.add_argument("--max-empty-rounds", type=int, default=3,
                    help="Стоп после N пустых кругов подряд")
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
2. Сохрани все публичные функции/классы.
3. Не добавляй внешних зависимостей.
4. PEP-8.
5. НЕ меняй форматирование комментариев-разделителей (# ===, # ---) если задача этого не требует.
6. НЕ переделывай рабочее, если оно не относится к задаче.

ОТВЕТ: только python-блок с полным файлом.
"""

PROMPT_JUDGE = """Проверь код после улучшения.

ЦЕЛЬ: {goal}

НОВЫЙ КОД:
{code}

Ответь JSON:
{{"ok": true/false, "problems": [], "summary": ""}}
"""

PROMPT_GENERATE_TASKS = """Ты — аналитик проекта. Предложи конкретные улучшения для Sapphira v3.

ТЕКУЩИЕ ФАЙЛЫ (путь, размер в символах, число функций):
{files}

УЖЕ УЛУЧШЕНО (не предлагать их повторно с той же целью):
{done}

ЗАДАЧА: предложи {count} КОНКРЕТНЫХ улучшений в JSON.

ФОРМАТ:
{{
  "tasks": [
    {{"file": "sapphira/...", "goal": "конкретное действие"}},
    ...
  ]
}}

ПРАВИЛА:
- Только конкретные действия ("Добавь кэш на X", "Улучши Y в Z"), не "сделай лучше".
- Файл должен существовать в списке.
- Не дублируй пары (файл+цель) из "уже улучшено".
- Приоритет: файлы с меньшим улучшением, большие файлы, сложные модули.
- Если улучшать нечего — верни {{"tasks": []}}.

ОТВЕТ: только JSON, без пояснений.
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
    def __init__(self, coder, judge, planner=None):
        sys.path.insert(0, str(V2_ROOT))
        from sapphira.core.router import get_router
        self.router = get_router()
        self.coder = coder
        self.judge = judge
        self.planner = planner or coder
        available = self.router.list_chat_models()
        log(f"Доступные модели: {available}")
        for role, m in [("coder", coder), ("judge", judge), ("planner", self.planner)]:
            if m not in available:
                fb = available[0] if available else m
                log(f"[!] '{m}' не найдена ({role}), использую {fb}", "WARN")
                if role == "coder":
                    self.coder = fb
                elif role == "judge":
                    self.judge = fb
                else:
                    self.planner = fb

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

    def generate_tasks(self, context, done, count=5):
        prompt = PROMPT_GENERATE_TASKS.format(
            files=context, done=done, count=count)
        try:
            raw = self.router.chat(self.planner, prompt,
                                    max_tokens=2000, temperature=0.4,
                                    use_cache=False)
            log(f"[generator] Ответ ({len(raw)} симв)", "INFO")
            data = extract_json(raw)
            if not data or not isinstance(data, dict):
                return []
            tasks = data.get("tasks", [])
            if not isinstance(tasks, list):
                return []
            valid = []
            for t in tasks:
                if isinstance(t, dict) and t.get("file") and t.get("goal"):
                    valid.append({
                        "file": str(t["file"]),
                        "goal": str(t["goal"])[:400],
                    })
            return valid
        except Exception as e:
            log(f"generate_tasks error: {e}", "ERROR")
            return []


class History:
    """История улучшений — чтобы не повторяться."""
    def __init__(self, path):
        self.path = path
        self.data = self._load()

    def _load(self):
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"rounds": [], "improved": []}

    def save(self):
        try:
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception:
            pass

    def add_round(self, rnum, done, ok, fail, empty):
        self.data["rounds"].append({
            "round": rnum,
            "time": datetime.now().isoformat(timespec="seconds"),
            "done": done, "ok": ok, "fail": fail, "empty": empty,
        })
        self.save()

    def add_improved(self, filename, goal):
        h = self._hash(filename, goal)
        self.data["improved"].append({
            "file": filename, "goal_hash": h,
            "when": datetime.now().isoformat(timespec="seconds"),
        })
        if len(self.data["improved"]) > 500:
            self.data["improved"] = self.data["improved"][-500:]
        self.save()

    def is_done(self, filename, goal):
        h = self._hash(filename, goal)
        return any(x.get("goal_hash") == h for x in self.data["improved"])

    def improved_files(self):
        return set(x["file"] for x in self.data["improved"])

    @staticmethod
    def _hash(filename, goal):
        import hashlib
        return hashlib.md5(f"{filename}|{goal[:200]}".encode()).hexdigest()[:12]


class UpgradeLoop:
    def __init__(self, args):
        self.args = args
        self.deadline = time.time() + args.hours * 3600
        self.tasks_file = V2_ROOT / args.tasks
        self.backup_dir = (TARGET_ROOT / "_upgrade_backup"
                           / datetime.now().strftime("%Y%m%d_%H%M%S"))
        self.log_file_path = TARGET_ROOT / "upgrade_log.md"
        self.history_path = TARGET_ROOT / "_upgrade_history.json"
        self.history = History(self.history_path)
        self.llm = LLM(args.coder, args.judge, args.planner)
        self.stats = {
            "rounds": 0, "files_processed": 0, "files_success": 0,
            "files_failed": 0, "files_empty": 0,
            "attempts_total": 0, "attempts_ok": 0, "attempts_rollback": 0,
            "tasks_generated": 0, "ideas_hunted": 0,
        }

    def stop_requested(self):
        return STOP_FILE.exists()

    # ============ Сбор контекста ============
    def collect_context(self):
        """Обходит v3, собирает список файлов с размерами."""
        lines = []
        imp = self.history.improved_files()
        for p in sorted((TARGET_ROOT / "sapphira").rglob("*.py")):
            rel = p.relative_to(TARGET_ROOT).as_posix()
            try:
                code = p.read_text(encoding="utf-8", errors="replace")
                n_func = len(re.findall(r"^\s*def ", code, re.MULTILINE))
                n_cls = len(re.findall(r"^\s*class ", code, re.MULTILINE))
                mark = " [уже улучшался]" if rel in imp else ""
                lines.append(f"  {rel}: {len(code)} симв, {n_func} def, {n_cls} class{mark}")
            except Exception:
                pass
        return "\n".join(lines)

    def collect_done(self):
        """Список пар (файл, цель) уже улучшенных."""
        seen = set()
        lines = []
        for x in self.history.data.get("improved", [])[-30:]:
            key = x.get("file", "")
            if key not in seen:
                seen.add(key)
                lines.append(f"  {key}")
        return "\n".join(lines) if lines else "(пока ничего)"

    # ============ Генерация задач ============
    def generate_new_tasks(self):
        log("=" * 60)
        log("🧠 Генерация новых задач через LLM...", "INFO")
        context = self.collect_context()
        done = self.collect_done()
        new_tasks = self.llm.generate_tasks(context, done, count=5)
        if not new_tasks:
            log("  LLM не предложила задач", "WARN")
            return []
        # Фильтр дублей
        filtered = []
        for t in new_tasks:
            target = TARGET_ROOT / t["file"]
            if not target.exists():
                log(f"  ✗ пропуск {t['file']} (нет файла)", "WARN")
                continue
            if self.history.is_done(t["file"], t["goal"]):
                log(f"  ✗ пропуск {t['file']} (уже было)", "WARN")
                continue
            filtered.append(t)
        log(f"  ✓ новых задач: {len(filtered)}")
        return filtered

    # ============ Project hunter ============
    def hunt_ideas(self):
        log("=" * 60)
        log("🌐 Запускаю project_hunter...", "INFO")
        try:
            sys.path.insert(0, str(V2_ROOT))
            from sapphira.features.project_hunter import hunt
            ideas = hunt(model=self.llm.planner,
                         log_func=lambda m: log(f"  [hunter] {m}", "INFO"))
            self.stats["ideas_hunted"] += len(ideas)
            # Конвертируем идеи в задачи
            tasks = []
            for idea in ideas[:3]:  # не больше 3 задач за раз
                if idea.get("verdict") == "Полезно":
                    # Ищем подходящий файл для улучшения
                    # Простейшая эвристика: класть в orchestrator или coder
                    tasks.append({
                        "file": "sapphira/features/knowledge.py",
                        "goal": f"Реализуй фичу по идее: {idea.get('feature','')}",
                    })
            log(f"  ✓ найдено идей: {len(ideas)}, задач создано: {len(tasks)}")
            return tasks
        except Exception as e:
            log(f"  [hunter] ошибка: {e}", "ERROR")
            return []

    # ============ Сохранение/загрузка задач ============
    def load_tasks(self):
        if not self.tasks_file.exists():
            return []
        try:
            data = json.loads(self.tasks_file.read_text(encoding="utf-8"))
            return data.get("tasks", [])
        except Exception:
            return []

    def save_tasks(self, tasks):
        try:
            self.tasks_file.write_text(
                json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as e:
            log(f"Не сохранить задачи: {e}", "ERROR")

    # ============ Обработка одного файла ============
    def process_one(self, task):
        rel_path = task.get("file")
        goal = task.get("goal", "улучшить код")
        if not rel_path:
            return "skip"
        target = TARGET_ROOT / rel_path
        if not target.exists():
            log(f"[!] Нет файла: {target}", "WARN")
            return "skip"
        try:
            _assert_safe(target)
        except RuntimeError as e:
            log(str(e), "ERROR")
            return "skip"

        log(f"\n{'-' * 60}")
        log(f"📁 {rel_path}")
        log(f"🎯 {goal[:100]}")
        log(f"{'-' * 60}")

        log_md(self.log_file_path, f"\n## {rel_path}")
        log_md(self.log_file_path, f"**Цель:** {goal}")

        self.stats["files_processed"] += 1
        file_start = time.time()

        for attempt in range(1, self.args.max_attempts + 1):
            if time.time() - file_start > self.args.minutes_per_file * 60:
                log(f"⏰ > {self.args.minutes_per_file} мин — skip", "WARN")
                log_md(self.log_file_path, f"- попытка {attempt}: ⏰ timeout")
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

            if new_code and new_code.strip() == original.strip():
                log("  ~ без изменений", "WARN")
                log_md(self.log_file_path, f"- попытка {attempt}: без изменений")
                self.stats["files_empty"] += 1
                return "empty"

            if not new_code:
                log("  x нет кода", "WARN")
                log_md(self.log_file_path, f"- попытка {attempt}: ❌ нет кода")
                continue

            if len(new_code) < 50:
                log(f"  x коротко ({len(new_code)})", "WARN")
                continue

            try:
                compile(new_code, str(target), "exec")
            except SyntaxError as e:
                log(f"  x SyntaxError: {e}", "WARN")
                log_md(self.log_file_path,
                       f"- попытка {attempt}: ❌ SyntaxError: {e}")
                continue

            # Backup
            backup_path = self.backup_dir / Path(rel_path).name
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup_path)
            log(f"  💾 backup")

            try:
                target.write_text(new_code, encoding="utf-8")
            except Exception as e:
                log(f"  x не записать: {e}", "ERROR")
                shutil.copy2(backup_path, target)
                continue

            log(f"  🧪 тест модуля...")
            ok_test, out = test_module(target)
            if not ok_test:
                log(f"  x тест упал: {out[:200]}", "WARN")
                shutil.copy2(backup_path, target)
                self.stats["attempts_rollback"] += 1
                log(f"  ↩ rollback")
                log_md(self.log_file_path,
                       f"- попытка {attempt}: ❌ тест упал, откат")
                continue
            log(f"  ✓ модуль OK")

            log(f"  ⚖ судья...")
            verdict = self.llm.judge_check(new_code, goal)
            if verdict.get("ok") is False:
                log(f"  ⚠ судья против (оставляю)", "WARN")

            log(f"  ✅ УСПЕХ ({len(original)} -> {len(new_code)})")
            log_md(self.log_file_path,
                   f"- попытка {attempt}: ✅ применено "
                   f"({len(original)} -> {len(new_code)})")
            self.stats["attempts_ok"] += 1
            self.stats["files_success"] += 1
            self.history.add_improved(rel_path, goal)
            return "ok"

        log(f"  ❌ не улучшено")
        log_md(self.log_file_path, f"- ❌ не улучшено")
        self.stats["files_failed"] += 1
        return "fail"

    # ============ Один круг ============
    def run_round(self, rnum):
        tasks = self.load_tasks()
        log("=" * 60)
        log(f"🔁 КРУГ {rnum}: задач в очереди = {len(tasks)}")
        log("=" * 60)

        if not tasks:
            if not self.args.auto_extend:
                return "empty_noextend"
            # Генерируем
            new_tasks = self.generate_new_tasks()

            # Каждые N кругов — hunter
            if not new_tasks and rnum > 1 and (rnum % self.args.hunter_every == 0):
                new_tasks = self.hunt_ideas()

            if not new_tasks:
                log("  ⚠ задач нет (LLM + hunter молчат)", "WARN")
                return "empty"

            self.stats["tasks_generated"] += len(new_tasks)
            self.save_tasks(new_tasks)
            tasks = new_tasks
            log(f"  ✓ сгенерировано {len(tasks)} задач")

        # Обрабатываем все задачи
        ok = fail = empty = 0
        for task in tasks:
            if self.stop_requested():
                log("STOP-файл найден", "WARN")
                return "stopped"
            if time.time() >= self.deadline:
                log("Время вышло", "WARN")
                return "timeout"

            result = self.process_one(task)
            if result == "ok":
                ok += 1
            elif result == "fail":
                fail += 1
            elif result == "empty":
                empty += 1

        # Очищаем файл задач (обработали)
        self.save_tasks([])
        self.history.add_round(rnum, len(tasks), ok, fail, empty)
        self.stats["rounds"] = rnum

        log("")
        log(f"📊 Круг {rnum}: OK={ok} FAIL={fail} EMPTY={empty}")
        return "done"

    # ============ Главный цикл ============
    def run(self):
        log("=" * 60)
        log(f"UPGRADE LOOP v2 (auto-extend={'ON' if self.args.auto_extend else 'OFF'})")
        log(f"  from: {V2_ROOT}")
        log(f"  to:   {TARGET_ROOT}")
        log(f"  hours: {self.args.hours}")
        log(f"  coder: {self.llm.coder}")
        log(f"  judge: {self.llm.judge}")
        log(f"  planner: {self.llm.planner}")
        log("=" * 60)

        self.backup_dir.mkdir(parents=True, exist_ok=True)
        if not self.log_file_path.exists():
            log_md(self.log_file_path,
                   f"# Запуск v2 на {self.args.hours}ч (auto-extend="
                   f"{'ON' if self.args.auto_extend else 'OFF'})")

        empty_rounds = 0
        rnum = 0
        while True:
            if self.stop_requested():
                log("STOP-файл", "WARN")
                break
            if time.time() >= self.deadline:
                log("Время вышло", "WARN")
                break

            rnum += 1
            status = self.run_round(rnum)

            if status == "stopped" or status == "timeout":
                break
            if status == "empty_noextend":
                log("Auto-extend выключен, задач нет — завершаю")
                break
            if status == "empty":
                empty_rounds += 1
                if empty_rounds >= self.args.max_empty_rounds:
                    log(f"{empty_rounds} пустых кругов подряд — стоп")
                    break
                log(f"Пустой круг {empty_rounds}/{self.args.max_empty_rounds}, "
                    f"сплю 5 мин...", "WARN")
                for _ in range(30):
                    if self.stop_requested():
                        break
                    time.sleep(10)
            else:
                empty_rounds = 0

        # Итоги
        log("=" * 60)
        log(f"DONE. Кругов: {self.stats['rounds']}, "
            f"OK={self.stats['files_success']}, FAIL={self.stats['files_failed']}, "
            f"EMPTY={self.stats['files_empty']}")
        log(f"  Задач сгенерировано: {self.stats['tasks_generated']}")
        log(f"  Идей найдено: {self.stats['ideas_hunted']}")
        log("=" * 60)

        # Отчёт
        try:
            sys.path.insert(0, str(V2_ROOT))
            from report_builder import build_report
            log("Генерирую отчёт...")
            rpt = build_report(V2_ROOT, TARGET_ROOT)
            if rpt:
                log(f"Отчёт: {rpt}")
        except Exception as e:
            log(f"Отчёт не сгенерирован: {e}", "WARN")


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
        print("[!] TARGET = v2 — запрещено!")
        return

    if args.dry_run:
        print("=" * 60)
        print(f"DRY RUN")
        print(f"  from: {V2_ROOT}")
        print(f"  to:   {TARGET_ROOT}")
        print(f"  auto-extend: {args.auto_extend}")
        print("=" * 60)
        return

    loop = UpgradeLoop(args)
    try:
        loop.run()
    except KeyboardInterrupt:
        log("\nПрервано вручную", "WARN")


if __name__ == "__main__":
    main()