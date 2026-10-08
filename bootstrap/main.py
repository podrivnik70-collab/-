# -*- coding: utf-8 -*-
"""Bootstrap Sapphira — окно первичной установки.

Показывает прогресс, ставит недостающие пакеты, запускает sapphira.
"""

import os
import sys
import subprocess
import threading
import tkinter as tk
from tkinter import ttk

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from bootstrap.deps import DEPENDENCIES, check_all, get_missing


BG     = "#1e1e1e"
BG_PAN = "#252526"
FG     = "#e0e0e0"
FG_DIM = "#858585"
ACCENT = "#0e639c"
GREEN  = "#89d185"
RED    = "#f48771"
YELLOW = "#dcdcaa"


class BootstrapWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Sapphira — Первичная установка")
        self.root.geometry("640x520")
        self.root.configure(bg=BG)

        w, h = 640, 520
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        self.cancelled = False
        self._build()

    def _build(self):
        head = tk.Frame(self.root, bg=BG, pady=16)
        head.pack(fill="x")
        tk.Label(head, text="💎", font=("Segoe UI", 30),
                 bg=BG, fg=ACCENT).pack()
        tk.Label(head, text="Sapphira", font=("Segoe UI", 18, "bold"),
                 bg=BG, fg=FG).pack()
        tk.Label(head, text="Первичная настройка",
                 font=("Segoe UI", 10), bg=BG, fg=FG_DIM).pack()

        self.main = tk.Frame(self.root, bg=BG_PAN, padx=16, pady=16)
        self.main.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        tk.Label(self.main, text="Проверяю систему...",
                 font=("Segoe UI", 11), bg=BG_PAN, fg=FG).pack(anchor="w")

        self.log = tk.Text(self.main, height=14, bg=BG, fg=FG,
                           relief="flat", font=("Consolas", 9),
                           borderwidth=0, wrap="word")
        self.log.pack(fill="both", expand=True, pady=(8, 8))
        for tag, color in [("ok", GREEN), ("err", RED),
                           ("warn", YELLOW), ("dim", FG_DIM)]:
            self.log.tag_config(tag, foreground=color)

        self.progress = ttk.Progressbar(self.main, mode="determinate")
        self.progress.pack(fill="x", pady=(0, 8))

        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=16, pady=(0, 12))
        self.status = tk.Label(bar, text="", bg=BG, fg=FG_DIM,
                                font=("Segoe UI", 9))
        self.status.pack(side="left")

        self.btn_install = tk.Button(
            bar, text="Установить", font=("Segoe UI", 10, "bold"),
            bg=ACCENT, fg="white", relief="flat", padx=20, pady=6,
            cursor="hand2", command=self._install, state="disabled")
        self.btn_install.pack(side="right", padx=4)

        self.btn_close = tk.Button(
            bar, text="Отмена", font=("Segoe UI", 10),
            bg=BG_PAN, fg=FG, relief="flat", padx=16, pady=6,
            cursor="hand2", command=self._close)
        self.btn_close.pack(side="right", padx=4)

        self.root.after(200, self._diagnose)

    # ---------- Логика ----------
    def _log(self, text, tag=None):
        def _do():
            if tag:
                self.log.insert("end", text + "\n", tag)
            else:
                self.log.insert("end", text + "\n")
            self.log.see("end")
        self.root.after(0, _do)

    def _diagnose(self):
        self._log("Проверка системы...", "ok")
        self._log(f"  Python: {sys.version.split()[0]}")
        self._log(f"  Путь:   {sys.executable}")

        try:
            from sapphira.features.system_info import get_system_report
            r = get_system_report(force=True)
            self._log(f"  CPU:    {r['cpu']}")
            self._log(f"  RAM:    {r['ram_gb']} ГБ")
            self._log(f"  GPU:    {r['gpu']}")
            self._log(f"  VRAM:   {r['vram_mb']} МБ")
        except Exception:
            self._log("  (не удалось прочитать железо)", "dim")

        self._log("")
        self._log("Проверка пакетов...")

        check = check_all()
        for pip, (installed, required) in check.items():
            if installed:
                self._log(f"  ✅ {pip}", "ok")
            else:
                mark = "❌" if required else "⚠️"
                tag = "err" if required else "warn"
                note = "" if required else " (опционально)"
                self._log(f"  {mark} {pip}{note}", tag)

        missing = get_missing()
        if not missing:
            self._log("\n✅ Всё установлено. Запускаю Sapphira...", "ok")
            self.status.config(text="Готово")
            self.root.after(700, self._launch_sapphira)
            return

        req_missing = [m for m in missing if m[1]]
        self._log(f"\nОтсутствует: {len(missing)}")
        self.status.config(text=f"Нужно установить: {len(missing)}")
        self.btn_install.config(state="normal",
                                text="Установить всё")
        if not req_missing:
            self.btn_close.config(text="Пропустить и запустить",
                                   command=self._launch_sapphira)

    def _install(self):
        self.btn_install.config(state="disabled")
        self.btn_close.config(state="disabled")
        self.cancelled = False
        threading.Thread(target=self._install_worker, daemon=True).start()

    def _install_worker(self):
        missing = get_missing()
        total = len(missing)
        self._log(f"\n=== Установка ({total}) ===")

        for i, (pip, required) in enumerate(missing, 1):
            if self.cancelled:
                break
            self._set_progress(int((i - 1) * 100 / total),
                                f"[{i}/{total}] {pip}")
            self._log(f"\n[{i}/{total}] {pip}...")

            if pip == "llama-cpp-python":
                ok = self._install_llama_cpp()
            else:
                ok = self._pip_install(pip)

            if ok:
                self._log(f"  ✓ {pip}", "ok")
            else:
                tag = "err" if required else "warn"
                self._log(f"  ✗ {pip} — пропущен", tag)

        self._set_progress(100, "Готово")

        # Финальная проверка
        still = get_missing()
        req_still = [m for m in still if m[1]]
        if req_still:
            self._log(f"\n❌ Не установлены: {[p for p,_ in req_still]}", "err")
            self._log("Проверь интернет и попробуй снова.", "err")
            self.root.after(0, lambda: self.btn_install.config(state="normal"))
            self.root.after(0, lambda: self.btn_close.config(
                state="normal", text="Закрыть", command=self._close))
            return

        self._log("\n✅ Установка завершена. Запускаю Sapphira...", "ok")
        self.root.after(1200, self._launch_sapphira)

    def _pip_install(self, package):
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "pip", "install",
                 "--upgrade", package],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
            for line in proc.stdout:
                line = line.rstrip()
                if any(k in line for k in ("Downloading", "Installing",
                                            "ERROR", "Successfully")):
                    self._log(f"  {line[:90]}", "dim")
            proc.wait()
            return proc.returncode == 0
        except Exception as e:
            self._log(f"  {e}", "err")
            return False

    def _install_llama_cpp(self):
        # CUDA-детект
        cuda_tag = "cpu"
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=driver_version",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
            if r.returncode == 0 and r.stdout.strip():
                major = int(r.stdout.strip().split(".")[0])
                if major >= 525:
                    cuda_tag = "cu121"
                elif major >= 520:
                    cuda_tag = "cu118"
        except Exception:
            pass

        if cuda_tag != "cpu":
            # Пробуем официальный индекс
            url = f"https://abetlen.github.io/llama-cpp-python/whl/{cuda_tag}"
            self._log(f"  CUDA {cuda_tag}", "dim")
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-m", "pip", "install",
                     "--upgrade", "--force-reinstall",
                     "llama-cpp-python",
                     "--extra-index-url", url],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    creationflags=subprocess.CREATE_NO_WINDOW
                        if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
                for line in proc.stdout:
                    line = line.rstrip()
                    if "Downloading" in line or "Successfully" in line:
                        self._log(f"  {line[:90]}", "dim")
                proc.wait()
                if proc.returncode == 0:
                    return True
            except Exception:
                pass

        # CPU-fallback
        self._log("  CPU fallback", "dim")
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "pip", "install",
                 "--upgrade", "llama-cpp-python",
                 "--extra-index-url",
                 "https://abetlen.github.io/llama-cpp-python/whl/cpu"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
            for line in proc.stdout:
                line = line.rstrip()
                if "Downloading" in line or "Successfully" in line:
                    self._log(f"  {line[:90]}", "dim")
            proc.wait()
            return proc.returncode == 0
        except Exception as e:
            self._log(f"  {e}", "err")
            return False

    def _set_progress(self, value, label=None):
        def _do():
            self.progress["value"] = value
            if label:
                self.status.config(text=label)
        self.root.after(0, _do)

    def _launch_sapphira(self):
        try:
            subprocess.Popen(
                [sys.executable, "-m", "sapphira"],
                cwd=ROOT,
                creationflags=subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
            self.root.after(500, self.root.destroy)
        except Exception as e:
            self._log(f"Не запустить Sapphira: {e}", "err")

    def _close(self):
        self.cancelled = True
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    try:
        import tkinter  # noqa
    except ImportError:
        print("tkinter не найден. Переустанови Python с tcl/tk.")
        sys.exit(1)
    BootstrapWindow().run()


if __name__ == "__main__":
    main()