# -*- coding: utf-8 -*-
"""ProjectMemory — состояние выполнения задачи в workspace.

Хранит project_state.json:
- какие файлы были в плане
- их статус (pending/done/failed)
- сколько попыток
- backup-версии каждого файла
"""

import os
import re
import json
import time
import shutil
from datetime import datetime


class ProjectMemory:
    def __init__(self, workspace: str):
        self.workspace = workspace
        self.state_file = os.path.join(workspace, "project_state.json")
        self.backup_dir = os.path.join(workspace, "backups")
        os.makedirs(self.backup_dir, exist_ok=True)
        self.data = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"task": "", "files": {}, "entry_point": None,
                "started_at": 0, "finished_at": 0}

    def save(self):
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def start_task(self, task: str, plan_steps: list, entry: str = None):
        self.data = {
            "task": task,
            "files": {},
            "entry_point": entry,
            "started_at": time.time(),
            "finished_at": 0,
        }
        for s in plan_steps:
            fn = s.get("file", "main.py")
            self.data["files"][fn] = {
                "action": s.get("action", ""),
                "dependencies": s.get("dependencies", []),
                "status": "pending",
                "attempts": 0,
                "verdict": None,
                "chunks": 0,
                "versions": [],
            }
        self.save()

    def mark_done(self, fn: str, attempts: int, verdict: str = "OK"):
        if fn in self.data["files"]:
            self.data["files"][fn].update({
                "status": "done",
                "attempts": attempts,
                "verdict": verdict,
            })
            self.save()

    def mark_failed(self, fn: str, problems: list = None):
        if fn in self.data["files"]:
            self.data["files"][fn].update({
                "status": "failed",
                "problems": problems or [],
            })
            self.save()

    def set_chunks(self, fn: str, n: int):
        if fn in self.data["files"]:
            self.data["files"][fn]["chunks"] = n
            self.save()

    def backup_version(self, filename: str, code: str, attempt: int):
        """Сохраняет копию версии файла в backups/."""
        safe = re.sub(r"[^\w.]", "_", filename)
        name = f"{safe}_attempt{attempt}_{int(time.time())}.py"
        try:
            with open(os.path.join(self.backup_dir, name), "w",
                      encoding="utf-8") as f:
                f.write(code)
            if filename in self.data["files"]:
                self.data["files"][filename]["versions"].append(name)
            self.save()
            return name
        except Exception:
            return None

    def has_unfinished(self) -> tuple:
        """Возвращает (есть_незаконченное, task)."""
        for fn, info in self.data.get("files", {}).items():
            if info.get("status") in ("pending", "in_progress"):
                return True, self.data.get("task", "")
        return False, ""

    def finish(self):
        self.data["finished_at"] = time.time()
        self.save()

    def summary(self) -> str:
        lines = []
        for fn, info in self.data.get("files", {}).items():
            icon = {"pending": "⏳", "done": "✅",
                    "failed": "❌"}.get(info["status"], "?")
            att = info.get("attempts", 0)
            v = info.get("verdict", "—")
            ch = info.get("chunks", 0)
            ch_str = f", чанков: {ch}" if ch > 1 else ""
            lines.append(f"  {icon} {fn} — {info['status']} "
                         f"(попыток: {att}, {v}{ch_str})")
        return "\n".join(lines) if lines else "  (пусто)"


if __name__ == "__main__":
    import tempfile
    tmp = tempfile.mkdtemp()
    print(f"=== memory.py самотест ===\nTemp dir: {tmp}\n")

    mem = ProjectMemory(tmp)
    mem.start_task(
        task="Тест",
        plan_steps=[
            {"file": "utils.py", "action": "функции",
             "dependencies": []},
            {"file": "main.py", "action": "CLI",
             "dependencies": ["utils.py"]},
        ],
        entry="main.py",
    )
    print(f"После start_task:")
    print(mem.summary())

    mem.backup_version("utils.py", "def add(a,b): return a+b", 1)
    mem.mark_done("utils.py", attempts=1, verdict="OK 0.85")
    mem.set_chunks("utils.py", 1)
    mem.mark_failed("main.py", problems=["что-то не так"])

    print(f"\nПосле операций:")
    print(mem.summary())

    has_unfinished, task = mem.has_unfinished()
    print(f"\nЕсть незавершённые: {has_unfinished} (task: {task!r})")
    print(f"Entry point: {mem.data['entry_point']}")

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print("\n✅ memory готов")