"""Run the evaluation sets against the local code (calls the real LLM APIs from .env).

usage: python tests/eval/run_local.py [--sets regression,followup,eval35,extra6,user30] [--out FILE]

Prints one line per question plus pass counts; writes every answer to a JSON
file under tests/eval/results/ (gitignored) for later comparison.
"""
import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")
logging.disable(logging.WARNING)

from questions import EVAL35, EXTRA6, FOLLOWUPS, REGRESSION, TEXTBOOK, USER30  # noqa: E402
from rag_service import KnowledgeBase, answer_question, resolve_api_key  # noqa: E402

ALL_SETS = ("regression", "followup", "eval35", "extra6", "user30")


def summarize(r, started):
    return {
        "mode": r["mode"],
        "provider": r.get("provider_used"),
        "pages": [p.get("page") for p in r["passages"]],
        "web": [w.get("title") for w in r.get("web_sources", []) or []],
        "answer": r["answer"],
        "seconds": round(time.time() - started, 1),
    }


def check(r, allowed, extra):
    if r["mode"] not in allowed:
        return f"mode {r['mode']} not in {sorted(allowed)}"
    if extra:
        result = extra(r)
        return None if result is True else result
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sets", default=",".join(ALL_SETS))
    parser.add_argument("--out")
    args = parser.parse_args()
    sets = [s.strip() for s in args.sets.split(",") if s.strip()]
    out_path = Path(args.out) if args.out else ROOT / "tests/eval/results" / f"local-{datetime.now():%Y%m%d-%H%M}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    kb = KnowledgeBase()
    keys = dict(typhoon_api_key=resolve_api_key("typhoon"), gemini_api_key=resolve_api_key("gemini"))
    out, summary = {}, []

    def ask(q, history=None):
        started = time.time()
        r = answer_question(kb, q, history=history, **keys)
        return r, summarize(r, started)

    for name in sets:
        rows = out[name] = []
        if name in ("eval35", "extra6", "user30"):
            questions = [(q, True) for q in (EVAL35 if name == "eval35" else EXTRA6)] if name != "user30" else USER30
            for i, (q, inside) in enumerate(questions, 1):
                _, row = ask(q)
                rows.append({"no": i, "question": q, "inside": inside, **row})
                print(f"{name} {i:2d} {row['mode']:18} {row['pages'][:3]} | {q}", flush=True)
            if name != "user30":
                summary.append(f"{name} grounded: {sum(r['mode'] in TEXTBOOK for r in rows)}/{len(rows)}")
        elif name == "regression":
            for group, q, history, allowed, extra in REGRESSION:
                r, row = ask(q, history)
                problem = check(r, allowed, extra)
                rows.append({"group": group, "question": q[:80], "ok": problem is None, "problem": problem, **row})
                print(f"{'OK  ' if problem is None else 'FAIL'} [{group:9}] {row['mode']:18} | {q[:40]}", flush=True)
                if problem:
                    print(f"      {problem}: {r['answer'][:160]!r}")
            summary.append(f"regression: {sum(r['ok'] for r in rows)}/{len(rows)}")
        elif name == "followup":
            opening_cache = {}
            for opening, q, allowed, extra in FOLLOWUPS:
                if opening not in opening_cache:
                    opening_cache[opening] = ask(opening)[0]["answer"]
                history = [{"role": "user", "content": opening}, {"role": "assistant", "content": opening_cache[opening]}]
                r, row = ask(q, history)
                problem = check(r, allowed, extra)
                rows.append({"opening": opening, "question": q, "ok": problem is None, "problem": problem, **row})
                print(f"{'OK  ' if problem is None else 'FAIL'} {row['mode']:18} {row['pages'][:3]} | {opening} → {q}", flush=True)
                if problem:
                    print(f"      {problem}: {r['answer'][:160]!r}")
            summary.append(f"followup: {sum(r['ok'] for r in rows)}/{len(rows)}")
        else:
            raise SystemExit(f"unknown set {name!r}; choose from {ALL_SETS}")
        json.dump(out, out_path.open("w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("\n" + "\n".join(summary))
    print(f"saved {out_path}")


if __name__ == "__main__":
    main()
