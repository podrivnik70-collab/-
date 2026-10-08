# -*- coding: utf-8 -*-
"""TaskHistory — история выполненных задач.

Хранит data/tasks_history.json: список из записей
{task, time, status, files, duration, workspace}.
"""

import os
import json
from datetime import datetime
from sapphira.config import Config


class TaskHistory:
    def __init__(self):
        self.data = Config.load("history") or []

    def add(self, task: str, workspace: str, status: str = "started"):
        self.data.append({
            "task": task[:300],
            "workspace": workspace,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": status,
            "files": [],
            "duration": 0,
        })
        Config.save("history")

    def update_last(self, status: str, files: list = None, duration: float = 0):
        if self.data:
            self.data[-1]["status"] = status
            if files:
                self.data[-1]["files"] = list(set(files))
            self.data[-1]["duration"] = round(duration, 1)
            Config.save("history")

    def get_last(self, n: int = 20) -> list:
        return self.data[-n:]

    def clear(self):
        self.data = []
        Config.save("history")

    def stats(self) -> str:
        done = sum(1 for x in self.data if x["status"] == "done")
        fail = sum(1 for x in self.data if x["status"] in ("error", "failed"))
        return f"История: {len(self.data)} задач ({done} OK, {fail} FAIL)"


if __name__ == "__main__":
    print("=== history.py самотест ===\n")
    h = TaskHistory()
    h.clear()

    h.add("Создай калькулятор", workspace="workspace/test1")
    h.update_last("done", files=["utils.py", "main.py"], duration=13.3)

    h.add("Парсер CSV", workspace="workspace/test2")
    h.update_last("error", files=["parser.py"], duration=8.5)

    print(h.stats())
    print("\nПоследние 5:")
    for i, x in enumerate(h.get_last(5), 1):
        print(f"  {i}. [{x['time']}] {x['status']:<8} "
              f"{x['duration']:>5}с  {x['task'][:60]}")

    print("\n✅ history готов")