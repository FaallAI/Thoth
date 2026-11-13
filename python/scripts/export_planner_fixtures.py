"""Export the planner trial's held-out drafts as test fixtures (planner stage 1, 2026-11-13).

The trial lived outside the repository (throwaway scripts and the operator's judging page). This
script is the record of how `tests/fixtures/planner/*.json` were made from it:

    python scripts/export_planner_fixtures.py <trial-dir> <out-dir>

Only ids, timings, speech text, phrases, the model's v3 answers and the operator's blind picks are
kept: no pictures, no storage locations, no secrets.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DOCS = ("641b43a8", "b410cf36", "194f5305", "3a20bf9f")
MODEL = "qwen__qwen3.7-flash"


def _answers(path: Path) -> dict[str, dict]:
    answer = json.loads(path.read_text(encoding="utf-8"))["answer"] or {"phrases": []}
    return {a["id"]: a for a in answer["phrases"]}


def export(trial: Path, out: Path) -> None:
    judged = {}
    for f in (trial / "judgments-r3" / "judgments").glob("*_r3.json"):
        j = json.loads(f.read_text(encoding="utf-8"))
        judged[(j["doc"], j["phrase"])] = j
    out.mkdir(parents=True, exist_ok=True)
    for doc in DOCS:
        folder = next((trial / "trial").glob(f"edoc_{doc}*"))
        t = json.loads((folder / "trial.json").read_text(encoding="utf-8"))
        handles = {s["source"]: s.get("handle") for s in t["sources"]}
        v3 = _answers(folder / "results" / f"{MODEL}__v3a.json")
        v2 = _answers(folder / "results" / f"{MODEL}__v2pre.json")
        blind = {}
        for p in t["phrases"]:
            j = judged[(t["document_id"], p["id"])]
            pre = v2.get(p["id"]) or {}
            picks = [] if pre.get("fit") == "none" else pre.get("picks") or []
            blind[p["id"]] = {
                "own": j.get("own") or [],
                "model_ok": j.get("model_ok"),
                "v2_pick": picks[0] if picks else None,
            }
        fixture = {
            "document": doc,
            "shots": [
                {
                    "shot": s["shot"],
                    "source": "main" if s["source"] == "MAIN" else "footage",
                    "asset_id": s["asset_id"],
                    "start": s["start"],
                    "end": s["end"],
                    "said": s.get("said") or "",
                    "handle": handles.get(s["source"]),
                }
                for s in t["shots"]
            ],
            "cards": [{"card": c["shot"], "kind": c["kind"], "asset_id": c["asset_id"]} for c in t["cards"]],
            "phrases": [
                {k: p[k] for k in ("id", "beat", "text", "start", "end")} for p in t["phrases"]
            ],
            "answer_v3": {
                pid: {"base": a.get("base") or [], "overlay": a.get("overlay") or []}
                for pid, a in v3.items()
            },
            "blind": blind,
        }
        (out / f"{doc}.json").write_text(json.dumps(fixture, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(doc, len(fixture["phrases"]), "phrases")


if __name__ == "__main__":
    export(Path(sys.argv[1]), Path(sys.argv[2]))
