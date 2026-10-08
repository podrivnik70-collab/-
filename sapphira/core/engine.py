# -*- coding: utf-8 -*-
"""LocalEngine — обёртка над llama-cpp-python для GGUF-моделей.

Держит ДВА независимых экземпляра:
- _chat_llama   — для chat-моделей (Qwen, DeepSeek и др.)
- _embed_llama  — для embedder (nomic-embed-text и др.)

При импорте автоматически подкладывает CUDA-DLL (cublas, cudart) рядом
с llama.dll, чтобы Windows их нашёл. Работает и на CPU-сборках.

Автодетект embedder по имени (.gguf): если в имени есть "embed" → embedding=True.
Для embedder'ов n_ctx принудительно ≤ n_ctx_train (у nomic 2048) и mean pooling.
"""

import os
import sys
import glob
import shutil
import threading
from sapphira.config import Config, MODELS_DIR


# ============================================================
# ПОДГОТОВКА DLL (Windows)
# ============================================================
_dll_prepared = False


def _prepare_dlls():
    """Копирует CUDA-DLL из nvidia-пакетов в llama_cpp/lib/."""
    global _dll_prepared
    if _dll_prepared:
        return
    _dll_prepared = True

    if sys.platform != "win32":
        return

    llama_lib = None
    for p in sys.path:
        candidate = os.path.join(p, "llama_cpp", "lib")
        if os.path.isdir(candidate):
            llama_lib = candidate
            break
    if not llama_lib:
        return

    nvidia_dlls = {}
    patterns = [
        "cudart64_*.dll", "cublas64_*.dll", "cublasLt64_*.dll",
        "nvrtc64_*.dll", "nvrtc-builtins64_*.dll",
    ]
    for p in sys.path:
        nvidia_root = os.path.join(p, "nvidia")
        if not os.path.isdir(nvidia_root):
            continue
        for bin_dir in glob.glob(os.path.join(nvidia_root, "*", "bin")):
            for pat in patterns:
                for full in glob.glob(os.path.join(bin_dir, pat)):
                    nvidia_dlls[os.path.basename(full)] = full

    for name, src in nvidia_dlls.items():
        dst = os.path.join(llama_lib, name)
        if os.path.exists(dst):
            continue
        try:
            shutil.copy2(src, dst)
        except Exception:
            pass

    try:
        os.add_dll_directory(llama_lib)
    except Exception:
        pass

    for p in sys.path:
        nvidia_root = os.path.join(p, "nvidia")
        if not os.path.isdir(nvidia_root):
            continue
        for bin_dir in glob.glob(os.path.join(nvidia_root, "*", "bin")):
            try:
                os.add_dll_directory(bin_dir)
            except Exception:
                pass


_prepare_dlls()


# ============================================================
# ЗАГРУЗКА llama_cpp
# ============================================================
_llama_cpp_cache = None
_llama_cpp_error = None


def _load_llama_cpp():
    global _llama_cpp_cache, _llama_cpp_error
    if _llama_cpp_cache is not None:
        return _llama_cpp_cache
    if _llama_cpp_error is not None:
        return None
    try:
        import llama_cpp
        _llama_cpp_cache = llama_cpp
        return llama_cpp
    except Exception as e:
        _llama_cpp_error = str(e)
        return None


def last_llama_error() -> str:
    return _llama_cpp_error or ""


def has_gpu_support() -> bool:
    llama_cpp = _load_llama_cpp()
    if llama_cpp is None:
        return False
    try:
        return bool(llama_cpp.llama_supports_gpu_offload())
    except Exception:
        return False


def is_embedder_name(name: str) -> bool:
    low = (name or "").lower()
    markers = ("embed", "bge-", "gte-", "e5-", "mxbai-", "jina-embed")
    return any(m in low for m in markers)


def list_installed_models() -> list:
    manifest = Config.load("manifest").get("installed", [])
    result = []
    for m in manifest:
        path = os.path.join(MODELS_DIR, m.get("filename", ""))
        if os.path.exists(path):
            result.append({
                "name": m.get("name", ""),
                "repo_id": m.get("repo_id", ""),
                "filename": m.get("filename"),
                "path": path,
                "size_gb": round(os.path.getsize(path) / (1024 ** 3), 2),
                "purpose": m.get("purpose", ""),
            })
    if not result and os.path.isdir(MODELS_DIR):
        for f in sorted(os.listdir(MODELS_DIR)):
            if f.lower().endswith(".gguf"):
                path = os.path.join(MODELS_DIR, f)
                result.append({
                    "name": f[:-5], "repo_id": "", "filename": f,
                    "path": path,
                    "size_gb": round(os.path.getsize(path) / (1024 ** 3), 2),
                    "purpose": "",
                })
    return result


def _resolve_model_path(name_or_path: str) -> tuple:
    if os.path.exists(name_or_path):
        return name_or_path, os.path.basename(name_or_path)
    for m in list_installed_models():
        if m["name"] == name_or_path or m["filename"] == name_or_path:
            return m["path"], m["name"]
    raise FileNotFoundError(f"Модель '{name_or_path}' не найдена в {MODELS_DIR}")


# ============================================================
# ОСНОВНОЙ КЛАСС
# ============================================================
class LocalEngine:
    def __init__(self):
        self._chat_llama = None
        self._chat_path = None
        self._chat_name = None
        self._chat_lock = threading.Lock()

        self._embed_llama = None
        self._embed_path = None
        self._embed_name = None
        self._embed_lock = threading.Lock()

        self._infer_lock = threading.Lock()
        self.n_threads = max(1, (os.cpu_count() or 4) - 1)
        self.verbose = False

    def _ctx_for(self, name: str) -> int:
        if is_embedder_name(name):
            return 2048
        return int(Config.get("settings", "context_length") or 8192)

    def _temperature(self) -> float:
        return float(Config.get("settings", "temperature") or 0.3)

    def _max_tokens(self) -> int:
        return int(Config.get("settings", "max_tokens") or 4096)

    def _ensure_chat(self, model_name_or_path: str):
        path, name = _resolve_model_path(model_name_or_path)
        if self._chat_llama is not None and self._chat_path == path:
            return
        if self._chat_llama is not None:
            self.unload_chat()

        llama_cpp = _load_llama_cpp()
        if llama_cpp is None:
            raise RuntimeError(
                f"llama-cpp-python не загрузился. Ошибка: {last_llama_error()}"
            )

        with self._chat_lock:
            gpu_ok = has_gpu_support()
            n_gpu_layers = -1 if gpu_ok else 0
            n_ctx = self._ctx_for(name)
            print(f"[engine] Загрузка chat: {name} "
                  f"(ctx={n_ctx}, GPU offload={gpu_ok})...")

            self._chat_llama = llama_cpp.Llama(
                model_path=path,
                n_ctx=n_ctx,
                n_threads=self.n_threads,
                n_gpu_layers=n_gpu_layers,
                verbose=self.verbose,
                embedding=False,
            )
            self._chat_path = path
            self._chat_name = name
            print(f"[engine] ✓ {name} готов")

    def _ensure_embed(self, model_name_or_path: str):
        path, name = _resolve_model_path(model_name_or_path)
        if self._embed_llama is not None and self._embed_path == path:
            return
        if self._embed_llama is not None:
            self.unload_embed()

        llama_cpp = _load_llama_cpp()
        if llama_cpp is None:
            raise RuntimeError(
                f"llama-cpp-python не загрузился. Ошибка: {last_llama_error()}"
            )

        with self._embed_lock:
            gpu_ok = has_gpu_support()
            n_gpu_layers = -1 if gpu_ok else 0
            n_ctx = self._ctx_for(name)
            print(f"[engine] Загрузка embedder: {name} "
                  f"(ctx={n_ctx}, GPU offload={gpu_ok})...")

            # pooling_type=1 → LLAMA_POOLING_TYPE_MEAN (для nomic-embed и др.)
            self._embed_llama = llama_cpp.Llama(
                model_path=path,
                n_ctx=n_ctx,
                n_threads=self.n_threads,
                n_gpu_layers=n_gpu_layers,
                verbose=self.verbose,
                embedding=True,
                pooling_type=1,
            )
            self._embed_path = path
            self._embed_name = name
            print(f"[engine] ✓ {name} (embedder) готов")

    def unload_chat(self):
        with self._chat_lock:
            self._chat_llama = None
            self._chat_path = None
            self._chat_name = None

    def unload_embed(self):
        with self._embed_lock:
            self._embed_llama = None
            self._embed_path = None
            self._embed_name = None

    def unload_all(self):
        self.unload_chat()
        self.unload_embed()

    def chat_loaded(self) -> bool:
        return self._chat_llama is not None

    def embed_loaded(self) -> bool:
        return self._embed_llama is not None

    def current_chat_model(self) -> str:
        return self._chat_name or ""

    def current_embed_model(self) -> str:
        return self._embed_name or ""

    def chat(self, model_name: str, prompt: str,
             system: str = None, max_tokens: int = None,
             temperature: float = None) -> str:
        if is_embedder_name(model_name):
            raise ValueError(f"'{model_name}' — embedder, не для чата.")
        self._ensure_chat(model_name)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self._chat_messages(messages, max_tokens, temperature)

    def chat_history(self, model_name: str, messages: list,
                     max_tokens: int = None,
                     temperature: float = None) -> str:
        if is_embedder_name(model_name):
            raise ValueError(f"'{model_name}' — embedder, не для чата.")
        self._ensure_chat(model_name)
        return self._chat_messages(messages, max_tokens, temperature)

    def _chat_messages(self, messages, max_tokens=None, temperature=None) -> str:
        if self._chat_llama is None:
            raise RuntimeError("Chat-модель не загружена")
        with self._infer_lock:
            resp = self._chat_llama.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens or self._max_tokens(),
                temperature=temperature if temperature is not None
                            else self._temperature(),
            )
        try:
            return resp["choices"][0]["message"]["content"] or ""
        except Exception:
            return ""

    def embed(self, model_name: str, text: str) -> list:
        if not is_embedder_name(model_name):
            raise ValueError(
                f"'{model_name}' — не embedder. Нужна модель с 'embed' в имени."
            )
        self._ensure_embed(model_name)
        if not text.strip():
            return []
        with self._infer_lock:
            out = self._embed_llama.create_embedding(text)
        try:
            return out["data"][0]["embedding"]
        except Exception:
            return []

    def embed_batch(self, model_name: str, texts: list) -> list:
        return [self.embed(model_name, t) for t in texts]

    def info(self) -> dict:
        return {
            "chat_loaded": self.chat_loaded(),
            "chat_model": self.current_chat_model(),
            "embed_loaded": self.embed_loaded(),
            "embed_model": self.current_embed_model(),
            "gpu_support": has_gpu_support(),
            "n_threads": self.n_threads,
        }


_engine = None
_engine_lock = threading.Lock()


def get_engine() -> LocalEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = LocalEngine()
    return _engine


if __name__ == "__main__":
    print("=== LocalEngine самотест ===\n")

    llama_cpp = _load_llama_cpp()
    if llama_cpp is None:
        print("❌ llama-cpp-python не загрузился")
        print(f"Ошибка: {last_llama_error()}")
        raise SystemExit(1)

    print(f"✅ llama-cpp-python: {llama_cpp.__version__}")
    print(f"   GPU offload: {has_gpu_support()}")

    print(f"\nПапка моделей: {MODELS_DIR}")
    for m in list_installed_models():
        kind = "embedder" if is_embedder_name(m["name"]) else "chat"
        print(f"  • {m['name']:<35} {m['size_gb']:>5} ГБ  [{kind}]")

    print("\n✅ Движок готов")