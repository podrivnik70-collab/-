# -*- coding: utf-8 -*-
"""TaskQueue — очередь отложенных задач.

Хранит data/tasks_queue.json: {"tasks": [{task, status, added}, ...]}
Статусы: pending / running / done / failed.
"""

import time
from datetime import datetime
from sapphira.config import Config


class TaskQueue:
    def __init__(self):
        self.data = Config.load("queue") or {"tasks": []}
        if "tasks" not in self.data:
            self.data["tasks"] = []

    def save(self):
        Config.save("queue")

    def add(self, task: str, workspace: str = ""):
        self.data["tasks"].append({
            "task": task,
            "workspace": workspace,
            "status": "pending",
            "added": datetime.now().strftime("%H:%M:%S"),
        })
        self.save()

    def next_task(self) -> dict:
        for t in self.data["tasks"]:
            if t["status"] == "pending":
                return t
        return None

    def mark(self, task_text: str, status: str):
        for t in self.data["tasks"]:
            if t["task"] == task_text:
                t["status"] = status
                break
        self.save()

    def clear_done(self):
        self.data["tasks"] = [
            t for t in self.data["tasks"]
            if t["status"] not in ("done", "failed")
        ]
        self.save()

    def clear_all(self):
        self.data["tasks"] = []
        self.save()

    def stats(self) -> str:
        p = sum(1 for t in self.data["tasks"] if t["status"] == "pending")
        r = sum(1 for t in self.data["tasks"] if t["status"] == "running")
        d = sum(1 for t in self.data["tasks"] if t["status"] == "done")
        f = sum(1 for t in self.data["tasks"] if t["status"] == "failed")
        return f"Очередь: {p} ждут, {r} работают, {d} готово, {f} провалено"

    def list_all(self) -> list:
        return list(self.data["tasks"])


if __name__ == "__main__":
    print("=== queue.py самотест ===\n")
    q = TaskQueue()
    q.clear_all()

    q.add("Калькулятор")
    q.add("Парсер CSV")
    q.add("Telegram-бот")

    print(q.stats())
    print("\nСписок:")
    for i, t in enumerate(q.list_all(), 1):
        print(f"  {i}. [{t['status']:<8}] {t['task']}")

    print("\nБерём следующую:")
    nxt = q.next_task()
    print(f"  {nxt['task']}")
    q.mark(nxt["task"], "done")

    print(f"\n{q.stats()}")
    q.clear_done()
    print(f"После clear_done: {q.stats()}")

    q.clear_all()
    print("\n✅ queue готов")