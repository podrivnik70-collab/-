# -*- coding: utf-8 -*-
"""RAG — семантический поиск по коду проекта через nomic-embed-text.

Оптимизирован под nomic-embed-text-v1.5:
- префикс "search_document: " при индексации
- префикс "search_query: " при поиске
- фильтрация мусора (заглушки, пустые файлы)
- вес по типу чанка: function > class > module > text

Кэш: .rag_index.json в workspace, переиспользуется по хэшу кода.
"""

import os
import ast
import json
import math
import hashlib
from sapphira.config import Config, MODELS_DIR


# ============ Структура чанка ============
class CodeChunk:
    def __init__(self, file_path: str, name: str, kind: str,
                 start_line: int, end_line: int, code: str):
        self.file_path = file_path
        self.name = name
        self.kind = kind
        self.start_line = start_line
        self.end_line = end_line
        self.code = code

    def to_dict(self):
        return {
            "file_path": self.file_path,
            "name": self.name,
            "kind": self.kind,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "code": self.code[:2000],
        }

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d[k] for k in
                      ("file_path", "name", "kind", "start_line",
                       "end_line", "code")})


# ============ Фильтр мусора ============
def _is_stub(code: str) -> bool:
    """
    True, если чанк — заглушка (только docstring, import, pass,
    или слишком короткий). Такие пропускаем.
    """
    stripped = code.strip()
    if len(stripped) < 50:
        return True

    # Убираем docstring
    try:
        tree = ast.parse(stripped)
        if not tree.body:
            return True
        # Все тела — только Pass / Expr(docstring) / Import?
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                return False
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign,
                                 ast.Return, ast.If, ast.For, ast.While,
                                 ast.With, ast.Try, ast.Raise)):
                return False
        return True
    except SyntaxError:
        return False


# ============ Разбиение Python-файла ============
def _chunk_python(code: str, file_path: str) -> list:
    chunks = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    lines = code.split("\n")

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno - 1
            end = node.end_lineno or start + 1
            body = "\n".join(lines[start:end])
            if not _is_stub(body):
                chunks.append(CodeChunk(file_path, node.name, "function",
                                        start + 1, end, body))
        elif isinstance(node, ast.ClassDef):
            start = node.lineno - 1
            end = node.end_lineno or start + 1
            body = "\n".join(lines[start:end])
            if not _is_stub(body):
                chunks.append(CodeChunk(file_path, node.name, "class",
                                        start + 1, end, body))

    if not chunks and not _is_stub(code):
        chunks.append(CodeChunk(file_path, os.path.basename(file_path),
                                "module", 1, len(lines), code))

    return chunks


def _chunk_text(code: str, file_path: str) -> list:
    chunks = []
    paragraphs = [p.strip() for p in code.split("\n\n") if p.strip()]
    for i, p in enumerate(paragraphs):
        if len(p) < 100:
            continue
        if len(p) > 800:
            p = p[:800]
        chunks.append(CodeChunk(file_path, f"para_{i+1}", "text",
                                i + 1, i + 1, p))
    return chunks


# ============ Косинусная близость ============
def _cosine(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ============ Веса по типу ============
_KIND_WEIGHT = {
    "function": 1.10,   # функции важнее всего
    "class":    1.05,
    "module":   1.00,
    "text":     0.90,
}


# ============ Основной класс ============
class RAGEngine:
    def __init__(self, workspace: str, embed_model: str = None):
        self.workspace = os.path.abspath(workspace)
        self.index_path = os.path.join(self.workspace, ".rag_index.json")
        self.chunks = []

        if embed_model:
            self.embed_model = embed_model
        else:
            self.embed_model = self._find_embed_model()

        self._load_index()

    def _find_embed_model(self) -> str:
        manifest = Config.load("manifest").get("installed", [])
        for m in manifest:
            name = m.get("name", "").lower()
            if any(k in name for k in ("embed", "nomic", "bge", "e5")):
                return m["name"]
        if os.path.isdir(MODELS_DIR):
            for f in os.listdir(MODELS_DIR):
                if "embed" in f.lower() and f.endswith(".gguf"):
                    return f[:-5]
        return ""

    def index_workspace(self, log_func=None, max_files: int = 100) -> int:
        def log(m):
            if log_func:
                log_func(m)

        if not self.embed_model:
            log("[rag] Нет embedder-модели\n")
            return 0

        py_files, text_files = [], []
        for root, dirs, files in os.walk(self.workspace):
            dirs[:] = [d for d in dirs
                       if d not in ("backups", "__pycache__", ".git",
                                    "snapshots", "venv", ".venv")]
            for f in files:
                p = os.path.join(root, f)
                if f.endswith(".py"):
                    py_files.append(p)
                elif f.endswith((".md", ".txt")):
                    text_files.append(p)

        py_files = py_files[:max_files]
        text_files = text_files[:max_files]

        log(f"[rag] Индексация: {len(py_files)} .py, "
            f"{len(text_files)} .md/.txt\n")

        all_chunks = []
        for f in py_files:
            try:
                code = open(f, "r", encoding="utf-8").read()
                all_chunks.extend(_chunk_python(code, f))
            except Exception:
                pass
        for f in text_files:
            try:
                code = open(f, "r", encoding="utf-8").read()
                all_chunks.extend(_chunk_text(code, f))
            except Exception:
                pass

        if not all_chunks:
            log("[rag] Нечего индексировать (одни заглушки)\n")
            return 0

        from sapphira.core.router import get_router
        router = get_router()

        log(f"[rag] Считаю эмбеддинги ({len(all_chunks)} чанков)...\n")

        new_index = []
        cache_hits = 0
        for i, ch in enumerate(all_chunks):
            h = hashlib.md5(ch.code.encode("utf-8")).hexdigest()

            old = next((c for c in self.chunks if c.get("hash") == h), None)
            if old:
                new_index.append(old)
                cache_hits += 1
                continue

            try:
                # ПРЕФИКС для документов
                text = f"search_document: {ch.kind} {ch.name}\n{ch.code[:800]}"
                emb = router.embed(self.embed_model, text)
                if emb:
                    new_index.append({
                        "chunk": ch.to_dict(),
                        "embed": emb,
                        "hash": h,
                    })
            except Exception as e:
                log(f"[rag] ⚠ {ch.name}: {e}\n")

            if (i + 1) % 30 == 0:
                log(f"[rag]   {i+1}/{len(all_chunks)}\n")

        self.chunks = new_index
        self._save_index()
        log(f"[rag] ✓ Проиндексировано {len(self.chunks)} чанков "
            f"(из кэша: {cache_hits})\n")
        return len(self.chunks)

    def search(self, query: str, top_k: int = 5,
               min_score: float = 0.3) -> list:
        if not self.chunks or not self.embed_model:
            return []

        from sapphira.core.router import get_router
        router = get_router()

        try:
            # ПРЕФИКС для запроса
            q_text = f"search_query: {query}"
            q_emb = router.embed(self.embed_model, q_text)
        except Exception:
            return []

        if not q_emb:
            return []

        scored = []
        for entry in self.chunks:
            score = _cosine(q_emb, entry["embed"])
            if score < min_score:
                continue
            kind = entry["chunk"].get("kind", "module")
            weight = _KIND_WEIGHT.get(kind, 1.0)
            scored.append((score * weight, entry["chunk"]))

        scored.sort(key=lambda x: -x[0])
        return scored[:top_k]

    def get_context(self, query: str, top_k: int = 5,
                    max_chars: int = 3000) -> str:
        results = self.search(query, top_k=top_k)
        if not results:
            return ""

        parts = []
        total = 0
        for score, chunk in results:
            rel = os.path.relpath(chunk["file_path"], self.workspace)
            block = (f"# {rel} :: {chunk['name']} "
                     f"({chunk['kind']}, score={score:.2f})\n"
                     f"{chunk['code'][:800]}")
            parts.append(block)
            total += len(block)
            if total >= max_chars:
                break

        return "\n\n---\n\n".join(parts)

    def stats(self) -> str:
        if not self.chunks:
            return f"RAG: (пусто) embed={self.embed_model or '—'}"
        return f"RAG: {len(self.chunks)} чанков, embed={self.embed_model}"

    def _load_index(self):
        if not os.path.exists(self.index_path):
            return
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.chunks = data.get("chunks", [])
        except Exception:
            self.chunks = []

    def _save_index(self):
        try:
            with open(self.index_path, "w", encoding="utf-8") as f:
                json.dump({"chunks": self.chunks}, f, ensure_ascii=False)
        except Exception:
            pass

    def clear(self):
        self.chunks = []
        try:
            if os.path.exists(self.index_path):
                os.remove(self.index_path)
        except Exception:
            pass


# ============ Самотест ============
if __name__ == "__main__":
    print("=== rag.py самотест ===\n")

    workspace = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))

    test_dir = os.path.join(workspace, "sapphira")
    print(f"Тест на: {test_dir}\n")

    # Удаляем старый кэш — тестируем свежую индексацию
    old_index = os.path.join(test_dir, ".rag_index.json")
    if os.path.exists(old_index):
        os.remove(old_index)
        print("Старый .rag_index.json удалён\n")

    rag = RAGEngine(test_dir)
    print(f"Embedder: {rag.embed_model or '(не найден)'}")

    if not rag.embed_model:
        print("\n⚠ Нет embedder")
        raise SystemExit(0)

    def log(m):
        print(m, end="")

    print(f"\n--- Индексация ---")
    n = rag.index_workspace(log_func=log, max_files=40)

    if n == 0:
        raise SystemExit(0)

    print(f"\n--- Поиск (min_score=0.3) ---")
    tests = [
        ("проверка синтаксиса python кода", "validate_syntax"),
        ("загрузка GGUF модели на GPU", "engine/Llama"),
        ("отправка запроса в OpenAI API", "cloud/chat"),
        ("топологическая сортировка файлов", "topological_sort"),
    ]

    for query, expected in tests:
        print(f"\nЗапрос: {query!r}  (ожидаем ~{expected})")
        results = rag.search(query, top_k=3)
        if not results:
            print("  ✗ ничего")
            continue
        for score, ch in results:
            rel = os.path.relpath(ch["file_path"], workspace)
            print(f"  {score:.3f} | {rel} :: {ch['name']} ({ch['kind']})")

    print(f"\n{rag.stats()}")
    print("\n✅ rag готов")