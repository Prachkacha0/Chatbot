"""Run the class question sets against the deployed site.

usage: python tests/eval/run_render.py [--sets eval35,extra6,user30] [--base URL] [--out FILE]

Waits ~7 s between questions to stay under the 10/minute rate limit and
retries on 429. The first request may take ~60 s while Render wakes up.
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from questions import EVAL35, EXTRA6, USER30  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SETS = {
    "eval35": [(q, True) for q in EVAL35],
    "extra6": [(q, True) for q in EXTRA6],
    "user30": USER30,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sets", default=",".join(SETS))
    parser.add_argument("--base", default="https://chatbot-research-yx71.onrender.com")
    parser.add_argument("--out")
    args = parser.parse_args()
    out_path = Path(args.out) if args.out else ROOT / "tests/eval/results" / f"render-{datetime.now():%Y%m%d-%H%M}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    out = {}
    with httpx.Client(timeout=120) as client:
        for name in args.sets.split(","):
            rows = out[name] = []
            for i, (q, inside) in enumerate(SETS[name], 1):
                started = time.time()
                data, status = {}, -1
                for _ in range(3):
                    try:
                        resp = client.post(f"{args.base}/api/chat", json={"message": q, "history": []})
                    except httpx.HTTPError as exc:
                        data = {"answer": f"[client error] {exc}"}
                        time.sleep(10)
                        continue
                    status = resp.status_code
                    if status == 429:
                        time.sleep(30)
                        continue
                    data = resp.json()
                    break
                rows.append({
                    "no": i, "question": q, "inside": inside, "status": status,
                    "seconds": round(time.time() - started, 1), "mode": data.get("mode"),
                    "provider": data.get("provider_used"), "answer": data.get("answer"),
                    "pages": [p.get("page") for p in data.get("passages", []) or []],
                    "web": [w.get("title") for w in data.get("web_sources", []) or []],
                })
                print(f"{name} {i:2d} {status} {rows[-1]['seconds']:5.1f}s {data.get('mode')} | {q}", flush=True)
                json.dump(out, out_path.open("w", encoding="utf-8"), ensure_ascii=False, indent=1)
                time.sleep(max(0, 7 - (time.time() - started)))
    print(f"saved {out_path}")


if __name__ == "__main__":
    main()
