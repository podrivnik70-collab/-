# -*- coding: utf-8 -*-
"""project_hunter.py - Ищет похожие AI-проекты на GitHub/HuggingFace."""

import os
import re
import sys
import json
import time
import requests
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
V2_ROOT = HERE.parent.parent
DATA_DIR = V2_ROOT / "data"
IDEAS_FILE = DATA_DIR / "ideas.json"

GITHUB_QUERIES = [
    "local ai agent coder",
    "llm orchestrator local",
    "local coding assistant",
    "ai agent framework python",
    "self improving ai agent",
]

HF_QUERIES = [
    ("qwen3", "gguf"),
    ("coder", "gguf"),
]


def _load_ideas():
    if IDEAS_FILE.exists():
        try:
            return json.loads(IDEAS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"updated": 0, "ideas": []}


def _save_ideas(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IDEAS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8")


def fetch_github_repos(query, limit=10):
    url = "https://api.github.com/search/repositories"
    params = {"q": query, "sort": "stars", "order": "desc", "per_page": limit}
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "Sapphira-Hunter"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=20)
        if r.status_code != 200:
            return []
        items = r.json().get("items", [])
        out = []
        for it in items:
            out.append({
                "source": "github",
                "name": it.get("full_name", ""),
                "url": it.get("html_url", ""),
                "description": (it.get("description") or "")[:300],
                "stars": it.get("stargazers_count", 0),
                "language": it.get("language", ""),
                "updated": (it.get("updated_at") or "")[:10],
            })
        return out
    except Exception as e:
        print(f"[hunter] GitHub error: {e}")
        return []


def fetch_hf_models(query, filter_tag="gguf", limit=10):
    url = "https://huggingface.co/api/models"
    params = {"search": query, "filter": filter_tag, "sort": "downloads",
              "direction": -1, "limit": limit}
    try:
        r = requests.get(url, params=params, timeout=20)
        if r.status_code != 200:
            return []
        items = r.json()
        out = []
        for it in items:
            out.append({
                "source": "huggingface",
                "name": it.get("id", ""),
                "url": f"https://huggingface.co/{it.get('id', '')}",
                "description": (it.get("pipeline_tag") or "")[:200],
                "stars": it.get("likes", 0),
                "downloads": it.get("downloads", 0),
                "updated": (it.get("lastModified") or "")[:10],
            })
        return out
    except Exception as e:
        print(f"[hunter] HF error: {e}")
        return []


ANALYZE_PROMPT = """Ты - аналитик проектов. Оцени, полезна ли идея проекта для Sapphira.

SAPPHIRA - локальный AI-агент для программирования на GGUF-моделях,
GUI на tkinter, Windows, 8 ГБ VRAM.

ПРОЕКТ:
- Источник: {source}
- Название: {name}
- Описание: {description}
- Ссылка: {url}
- Звёзд/лайков: {stars}

Ответь JSON:
{{
  "verdict": "Полезно" | "Не полезно" | "Возможно",
  "feature": "краткое название фичи",
  "reason": "почему",
  "priority": 1-5
}}
"""


def analyze_with_llm(router, model, project):
    prompt = ANALYZE_PROMPT.format(**project)
    try:
        raw = router.chat(model, prompt, max_tokens=400,
                           temperature=0.2, use_cache=False)
    except Exception as e:
        print(f"[hunter] LLM error: {e}")
        return None

    raw = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "")
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return {
            "verdict": data.get("verdict", "?"),
            "feature": data.get("feature", "")[:80],
            "reason": data.get("reason", "")[:300],
            "priority": int(data.get("priority", 1)),
        }
    except Exception:
        return None


def hunt(log_func=None, model=None, max_per_query=5, save=True):
    def log(m):
        if log_func:
            log_func(m)
        print(f"[hunter] {m}")

    if str(V2_ROOT) not in sys.path:
        sys.path.insert(0, str(V2_ROOT))
    try:
        from sapphira.core.router import get_router
        router = get_router()
    except Exception as e:
        log(f"Router не загрузился: {e}")
        return []

    chat_models = router.list_chat_models()
    if not chat_models:
        return []
    if not model or model not in chat_models:
        for pref in ("Qwen3.5-9B", "Qwen2.5-Coder-7B-Instruct"):
            if pref in chat_models:
                model = pref
                break
        else:
            model = chat_models[0]
    log(f"Модель: {model}")

    ideas_data = _load_ideas()
    known_urls = {i["url"] for i in ideas_data.get("ideas", [])}
    new_ideas = []

    for q in GITHUB_QUERIES:
        log(f"GitHub: {q}")
        for repo in fetch_github_repos(q, limit=max_per_query):
            if repo["url"] in known_urls or repo["stars"] < 100:
                continue
            log(f"  {repo['name']} ({repo['stars']} stars)")
            verdict = analyze_with_llm(router, model, repo)
            if not verdict or verdict["verdict"] == "Не полезно":
                continue
            idea = {**repo, **verdict, "found_at": datetime.now().isoformat()}
            new_ideas.append(idea)
            known_urls.add(repo["url"])
            log(f"  IDEA: {verdict['feature']}")
        time.sleep(2)

    for q, tag in HF_QUERIES:
        log(f"HF: {q}")
        for m in fetch_hf_models(q, filter_tag=tag, limit=max_per_query):
            if m["url"] in known_urls or m.get("downloads", 0) < 10000:
                continue
            verdict = analyze_with_llm(router, model, m)
            if not verdict or verdict["verdict"] == "Не полезно":
                continue
            idea = {**m, **verdict, "found_at": datetime.now().isoformat()}
            new_ideas.append(idea)
            known_urls.add(m["url"])
        time.sleep(2)

    if save and new_ideas:
        ideas_data["ideas"].extend(new_ideas)
        ideas_data["updated"] = time.time()
        ideas_data["ideas"].sort(
            key=lambda x: (-x.get("priority", 1), x.get("found_at", "")))
        _save_ideas(ideas_data)
        log(f"Сохранено: {len(new_ideas)}")

    return new_ideas


if __name__ == "__main__":
    hunt()