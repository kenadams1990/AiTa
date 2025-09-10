from fastapi import FastAPI, Body
from pydantic import BaseModel
from typing import Optional
import re, csv, os, datetime, requests, json

app = FastAPI(title="AiTa", version="0.1.0")

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA = os.path.join(ROOT, "data")
DOCS = os.path.join(ROOT, "docs")
LOGS = os.path.join(ROOT, "logs")
POLICY_PATH = os.path.join(DOCS, "policy.json")

with open(POLICY_PATH) as f:
    POLICY = json.load(f)

BLOCK_RE = re.compile("|".join(POLICY["block_patterns"])) if POLICY["block_patterns"] else None


class AskReq(BaseModel):
    question: str
    teacher_id: str = "engineering"
    mode: str = "student"  # "student" | "sub"


def _shorten_to_sentences(text: str, max_sents: int = 2) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(parts[:max_sents]).strip()


def _blocked(q: str) -> bool:
    return bool(BLOCK_RE.search(q)) if BLOCK_RE else False


def _ollama(prompt: str) -> str:
    # Local only; model is pulled via `ollama pull llama3.1:8b`
    r = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": "llama3.1:8b", "prompt": prompt, "stream": False},
        timeout=120,
    )
    r.raise_for_status()
    return r.json().get("response", "").strip()


def _retrieve_context(q: str, teacher_id: str) -> str:
    # Placeholder: wire to your existing Chroma collection on disk.
    # Keep it dead-simple for the pilot: concatenate top-k passages from teacher docs.
    # If retrieval is empty, return "" so we deflect.
    try:
        # TODO: connect to chroma client on disk and fetch top-k. For now, naive fallback:
        ctx_files = [
            os.path.join(DOCS, "procedures.txt"),
            os.path.join(DOCS, "syllabus.txt"),
            os.path.join(DOCS, "faq.csv"),
        ]
        snippets = []
        for p in ctx_files:
            if os.path.exists(p) and p.endswith(".txt"):
                with open(p) as f:
                    snippets.append(f.read()[:2000])
        return "\n\n".join(snippets)[:4000]
    except Exception:
        return ""


def _log_unknown(q: str, teacher_id: str, reason: str):
    os.makedirs(LOGS, exist_ok=True)
    path = os.path.join(LOGS, f"unknowns_{teacher_id}.csv")
    new_file = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["ts", "teacher_id", "question", "reason"])
        w.writerow([datetime.datetime.utcnow().isoformat(), teacher_id, q, reason])


@app.post("/ask")
def ask(payload: AskReq):
    q = payload.question.strip()

    if payload.mode == "sub":
        # Substitute gets only the day plan and emergency card
        plan_path = os.path.join(DOCS, "procedures.txt")
        plan = open(plan_path).read()[:600] if os.path.exists(plan_path) else "Day plan not found."
        return {"answer": _shorten_to_sentences(plan, 2)}

    if _blocked(q):
        _log_unknown(q, payload.teacher_id, "blocked_by_policy")
        return {"answer": POLICY["fallback_text"]}

    ctx = _retrieve_context(q, payload.teacher_id)
    if not ctx:
        _log_unknown(q, payload.teacher_id, "no_context")
        return {"answer": POLICY["fallback_text"]}

    system = (
        "You are a classroom TA. Answer in at most two short sentences. "
        "If the question is not answerable from the provided context, say: 'Ask your teacher.'"
    )
    prompt = f"{system}\n\nContext:\n{ctx}\n\nQuestion: {q}\nAnswer:"
    try:
        raw = _ollama(prompt)
    except Exception:
        _log_unknown(q, payload.teacher_id, "ollama_error")
        return {"answer": POLICY["fallback_text"]}

    if not raw or "Ask your teacher" in raw:
        _log_unknown(q, payload.teacher_id, "model_uncertain")
        return {"answer": POLICY["fallback_text"]}

    return {"answer": _shorten_to_sentences(raw, POLICY["answer_max_sentences"])}


@app.get("/unknowns")
def unknowns(teacher_id: str = "engineering"):
    path = os.path.join(LOGS, f"unknowns_{teacher_id}.csv")
    if not os.path.exists(path):
        return {"rows": []}
    with open(path) as f:
        rows = list(csv.reader(f))
    header, data = rows[0], rows[1:]
    return {"header": header, "rows": data}

