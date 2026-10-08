# -*- coding: utf-8 -*-
"""Orchestrator — главный цикл Sapphira.

Принимает задачу и прогоняет её через агентов:
1. Планировщик → список файлов
2. Топосортировка по зависимостям
3. Для каждого файла:
   - Кодер генерирует код
   - Младший судья проверяет синтаксис
   - Старший судья проверяет логику
   - Если FAIL — возврат кодеру с проблемами (до max_attempts)
4. Сохранение файлов в workspace
5. Опционально: README.md
"""

import os
import time
from datetime import datetime

from sapphira.core.router import get_router
from sapphira.agents import planner, coder, judge


# ============ Результат ============
class TaskResult:
    def __init__(self, task: str, workspace: str):
        self.task = task
        self.workspace = workspace
        self.files = {}
        self.plan = None
        self.entry_point = None
        self.started_at = time.time()
        self.finished_at = None

    def set_file(self, filename, code, status, attempts, verdict=None):
        self.files[filename] = {
            "code": code,
            "status": status,
            "attempts": attempts,
            "verdict": verdict,
        }

    def ok_count(self):
        return sum(1 for f in self.files.values() if f["status"] == "done")

    def fail_count(self):
        return sum(1 for f in self.files.values() if f["status"] == "failed")

    def duration(self):
        end = self.finished_at or time.time()
        return round(end - self.started_at, 1)

    def summary(self):
        lines = [
            f"Задача: {self.task[:100]}",
            f"Workspace: {self.workspace}",
            f"Время: {self.duration()}с",
            f"Файлов: {len(self.files)} (готово: {self.ok_count()}, "
            f"провалено: {self.fail_count()})",
            "",
            "Файлы:",
        ]
        for fn, info in self.files.items():
            icon = "✅" if info["status"] == "done" else "❌"
            v = f" [{info['verdict']}]" if info.get("verdict") else ""
            lines.append(f"  {icon} {fn} — попыток: {info['attempts']}{v}")
        return "\n".join(lines)


# ============ Главный класс ============
class Orchestrator:
    def __init__(self, log_func=None):
        self.router = get_router()
        self.log = log_func or print
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def _save_file(self, workspace: str, filename: str, code: str) -> bool:
        try:
            path = os.path.join(workspace, filename)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(code)
            return True
        except Exception as e:
            self.log(f"[orch] ✗ Не сохранить {filename}: {e}\n")
            return False

    def _process_file(self, step: dict, task: str,
                      profile_key: str,
                      project_files: list,
                      criteria: str,
                      planner_model: str,
                      coder_model: str,
                      junior_model: str,
                      senior_model: str,
                      max_attempts: int,
                      use_chunking: bool) -> dict:
        filename = step["file"]
        base_action = step["action"]
        action = base_action
        prev_problems = []
        chunks = 1

        self.log(f"\n{'═' * 60}\n📁 {filename}\n{'═' * 60}\n")

        last_code = ""

        for attempt in range(1, max_attempts + 1):
            if self.cancelled:
                break
            self.log(f"\n───── Раунд {attempt}/{max_attempts} ─────\n")

            # === Кодер ===
            if use_chunking:
                code, chunks = coder.generate_chunked(
                    self.router, coder_model,
                    filename=filename,
                    task=task,
                    action=action,
                    profile_key=profile_key,
                    project_files=project_files,
                    max_chunks=5,
                    requirements="\n".join(prev_problems) if prev_problems else "",
                    log_func=self.log,
                )
            else:
                code = coder.generate(
                    self.router, coder_model,
                    filename=filename,
                    task=task,
                    action=action,
                    profile_key=profile_key,
                    project_files=project_files,
                    requirements="\n".join(prev_problems) if prev_problems else "",
                    log_func=self.log,
                )

            if not code:
                self.log(f"[orch] ✗ Пустой код\n")
                prev_problems = ["Пустой ответ"]
                continue

            last_code = code

            # === Младший судья (С ПЕРЕДАЧЕЙ project_files!) ===
            self.log(f"[orch] ⚖ Младший судья...\n")
            jr = judge.review_junior(
                self.router, junior_model,
                task=task, filename=filename, code=code,
                profile_key=profile_key,
                project_files=project_files,   # ← ФИКС
                log_func=self.log,
            )
            self.log(f"[orch] junior score={jr['score']}, "
                     f"проблем={len(jr['problems'])}\n")

            if jr["problems"]:
                prev_problems = jr["problems"]
                action = (f"{base_action}. Исправь: "
                          + ", ".join(map(str, prev_problems)))
                continue

            # === Старший судья ===
            self.log(f"[orch] ⚖⚖ Старший судья...\n")
            sr = judge.review_senior(
                self.router, senior_model,
                task=task, criteria=criteria,
                filename=filename, project_files=project_files, code=code,
                profile_key=profile_key,
                log_func=self.log,
            )
            self.log(f"[orch] senior score={sr['score']}, "
                     f"verdict={sr['verdict']}\n")

            if sr["verdict"] == "OK" and sr["score"] >= 0.75:
                self.log(f"[orch] ✅ {filename} ОДОБРЕН\n")
                return {
                    "code": code,
                    "status": "done",
                    "attempts": attempt,
                    "verdict": f"{sr['verdict']} {sr['score']}",
                    "chunks": chunks,
                }
            else:
                prev_problems = sr["problems"] or [sr["summary"]]
                action = (f"{base_action}. Старший: "
                          + ", ".join(map(str, prev_problems)))

        self.log(f"[orch] ❌ {filename} НЕ ОДОБРЕН после {max_attempts} попыток\n")
        return {
            "code": last_code,
            "status": "failed",
            "attempts": max_attempts,
            "verdict": "FAIL",
            "chunks": chunks,
        }

    def _generate_readme(self, task: str, workspace: str,
                         files: list, model: str):
        self.log(f"\n[orch] 📖 README.md...\n")
        fl = "\n".join(f"  • {f}" for f in files)
        prompt = ("Напиши README.md для проекта.\n\n"
                  f"Задача: {task}\n\nФайлы:\n{fl}\n\n"
                  "Структура: # Название, ## Описание, ## Установка, "
                  "## Использование. Только markdown, без обёрток.")
        try:
            raw = self.router.chat(model, prompt, max_tokens=1500,
                                   temperature=0.4, use_cache=False)
        except Exception as e:
            self.log(f"[orch] README: {e}\n")
            return

        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.lower().startswith("markdown"):
                raw = raw[8:].lstrip()
        try:
            path = os.path.join(workspace, "README.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(raw)
            self.log(f"[orch] ✓ README.md ({len(raw)} симв)\n")
        except Exception as e:
            self.log(f"[orch] README: {e}\n")

    def run_task(self, task: str, workspace: str,
                 profile_key: str = "code",
                 planner_model: str = None,
                 coder_model: str = None,
                 junior_model: str = None,
                 senior_model: str = None,
                 max_attempts: int = 3,
                 use_chunking: bool = True,
                 make_readme: bool = True) -> TaskResult:
        self.cancelled = False
        result = TaskResult(task, workspace)

        default_model = (self.router.list_chat_models() or [""])[0]
        planner_model = planner_model or default_model
        coder_model = coder_model or default_model
        junior_model = junior_model or default_model
        senior_model = senior_model or default_model

        if not default_model:
            self.log("[orch] ✗ Нет доступных моделей\n")
            return result

        self.log(f"\n{'═' * 60}\n"
                 f"ЗАДАЧА: {task[:120]}\n"
                 f"Workspace: {workspace}\n"
                 f"Профиль: {profile_key}\n"
                 f"{'═' * 60}\n\n")

        plan = planner.make_plan(
            self.router, planner_model, task,
            profile_key=profile_key,
            log_func=self.log,
        )
        result.plan = plan
        result.entry_point = plan["entry_point"]

        self.log(f"[orch] План: {len(plan['steps'])} файл(ов)\n")
        for i, s in enumerate(plan["steps"], 1):
            deps = s["dependencies"]
            dstr = f" ← {', '.join(deps)}" if deps else ""
            self.log(f"  {i}. {s['file']:<20}{dstr}\n")

        os.makedirs(workspace, exist_ok=True)
        project_files = [s["file"] for s in plan["steps"]]

        for i, step in enumerate(plan["steps"], 1):
            if self.cancelled:
                self.log("[orch] Отменено пользователем\n")
                break
            self.log(f"\n[{i}/{len(plan['steps'])}] {step['file']}...\n")

            info = self._process_file(
                step=step, task=task, profile_key=profile_key,
                project_files=project_files,
                criteria=plan.get("criteria", ""),
                planner_model=planner_model,
                coder_model=coder_model,
                junior_model=junior_model,
                senior_model=senior_model,
                max_attempts=max_attempts,
                use_chunking=use_chunking,
            )

            result.set_file(
                step["file"], info["code"],
                info["status"], info["attempts"],
                info.get("verdict"),
            )
            if info["code"]:
                self._save_file(workspace, step["file"], info["code"])

        if make_readme and not self.cancelled:
            ok_files = [fn for fn, info in result.files.items()
                        if info["status"] == "done"]
            if ok_files:
                self._generate_readme(task, workspace,
                                      project_files, coder_model)

        result.finished_at = time.time()
        self.log(f"\n{'═' * 60}\nИТОГ\n{'═' * 60}\n{result.summary()}\n")
        return result


# ============ CLI ============
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--task", "-t", required=True)
    parser.add_argument("--workspace", "-w",
                        default=os.path.join(
                            os.path.dirname(os.path.dirname(
                                os.path.dirname(os.path.abspath(__file__)))),
                            "workspace"))
    parser.add_argument("--profile", "-p", default="code")
    parser.add_argument("--attempts", "-a", type=int, default=3)
    parser.add_argument("--no-chunking", action="store_true")
    parser.add_argument("--no-readme", action="store_true")

    args = parser.parse_args()

    def log(m):
        print(m, end="")

    orch = Orchestrator(log_func=log)
    res = orch.run_task(
        task=args.task,
        workspace=args.workspace,
        profile_key=args.profile,
        max_attempts=args.attempts,
        use_chunking=not args.no_chunking,
        make_readme=not args.no_readme,
    )

    print(f"\nФайлы в {args.workspace}:")
    for f in os.listdir(args.workspace):
        p = os.path.join(args.workspace, f)
        if os.path.isfile(p):
            print(f"  • {f} ({os.path.getsize(p)} байт)")