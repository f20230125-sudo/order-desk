"""Score the extractor (and, once written, the check engine) against the synthetic ground truth.

    python -m synth.generate      # documents + ground truth
    python -m eval.run_eval       # writes eval/results.json and prints a summary

Extraction is scored field by field and line by line. A line counts as right only if every scored value
on it is right. Layouts used while writing the extractor are reported apart from the held-out layout L5.
"""

import json
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from backend.extract.detect import extract

ROOT = Path(__file__).resolve().parent.parent
TRUTH = ROOT / "synth" / "ground_truth.json"
DOCS = ROOT / "synth" / "out"
RESULTS = ROOT / "eval" / "results.json"
HELD_OUT = {"L5"}
LINE_KEYS = ("part_number", "qty", "unit_price", "serials", "substitutes_part")


def _norm(v):
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, list):
        return [str(x) for x in v]
    return None if v is None else str(v)


def score_document(truth: dict, got: dict) -> dict:
    fields_total = fields_right = 0
    wrong_fields = []
    for name, expected in truth["fields"].items():
        fields_total += 1
        found = _norm(got["fields"].get(name, {}).get("value"))
        if found == _norm(expected) or (isinstance(expected, bool) and found == str(expected)):
            fields_right += 1
        else:
            wrong_fields.append({"field": name, "expected": expected, "found": found})
    lines_total = len(truth["lines"])
    lines_right = 0
    wrong_lines = []
    for k, t_line in enumerate(truth["lines"]):
        g_line = got["lines"][k] if k < len(got["lines"]) else {}
        bad = []
        for key in LINE_KEYS:
            if key not in t_line and key != "substitutes_part":
                continue
            expected = t_line.get(key)
            found = _norm(g_line.get(key, {}).get("value")) if isinstance(g_line.get(key), dict) else None
            if key == "unit_price" and expected is not None:
                expected = f"{Decimal(expected):.2f}"
            if _norm(expected) != found and not (expected is None and found is None):
                bad.append({"value": key, "expected": expected, "found": found})
        if bad:
            wrong_lines.append({"line": k + 1, "problems": bad})
        else:
            lines_right += 1
    extra_lines = max(0, len(got["lines"]) - lines_total)
    return {
        "fields_total": fields_total,
        "fields_right": fields_right,
        "lines_total": lines_total,
        "lines_right": lines_right,
        "extra_lines": extra_lines,
        "wrong_fields": wrong_fields,
        "wrong_lines": wrong_lines,
    }


def evaluate_extraction(truth: dict) -> dict:
    groups: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    failures = []
    for name, t in truth["documents"].items():
        _mime, got = extract((DOCS / name).read_bytes())
        s = score_document(t, got)
        kind_ok = got["kind"] == t["kind"]
        key = f"{t['kind']}/{t['layout']}"
        g = groups[key]
        g["documents"] += 1
        g["kind_right"] += int(kind_ok)
        for k in ("fields_total", "fields_right", "lines_total", "lines_right", "extra_lines"):
            g[k] += s[k]
        perfect = (
            kind_ok
            and s["fields_right"] == s["fields_total"]
            and s["lines_right"] == s["lines_total"]
            and not s["extra_lines"]
        )
        g["documents_perfect"] += int(perfect)
        if not perfect:
            failures.append(
                {
                    "document": name,
                    "kind_found": got["kind"],
                    **{k: s[k] for k in ("wrong_fields", "wrong_lines", "extra_lines")},
                }
            )

    def roll(keys):
        agg = defaultdict(int)
        for k in keys:
            for m, v in groups[k].items():
                agg[m] += v
        return _rates(agg)

    dev = [k for k in groups if k.split("/")[1] not in HELD_OUT]
    held = [k for k in groups if k.split("/")[1] in HELD_OUT]
    return {
        "by_layout": {k: _rates(v) for k, v in sorted(groups.items())},
        "development_layouts": roll(dev),
        "held_out_layout": roll(held),
        "failures": failures,
    }


def _rates(g: dict) -> dict:
    out = dict(g)
    out["field_accuracy"] = round(g["fields_right"] / g["fields_total"], 4) if g["fields_total"] else None
    out["line_accuracy"] = round(g["lines_right"] / g["lines_total"], 4) if g["lines_total"] else None
    out["document_accuracy"] = round(g["documents_perfect"] / g["documents"], 4) if g["documents"] else None
    return out


def main() -> None:
    truth = json.loads(TRUTH.read_text(encoding="utf-8"))
    results = {"extraction": evaluate_extraction(truth)}
    try:
        from eval.engine_eval import evaluate_engine

        results["check_engine"] = evaluate_engine(truth)
    except ImportError:
        pass
    RESULTS.write_text(json.dumps(results, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    ex = results["extraction"]
    for name in ("development_layouts", "held_out_layout"):
        r = ex[name]
        print(
            f"{name:22s} documents {r['documents']:3d}  fields {r['field_accuracy']:.1%}  "
            f"lines {r['line_accuracy']:.1%}  fully right {r['document_accuracy']:.1%}"
        )
    for k, r in ex["by_layout"].items():
        print(
            f"  {k:28s} n={r['documents']:3d}  fields {r['field_accuracy']:.1%}  lines {r['line_accuracy']:.1%}"
        )
    if "check_engine" in results:
        ce = results["check_engine"]
        print(
            f"check engine: precision {ce['precision']:.1%}  recall {ce['recall']:.1%}  "
            f"({ce['true_positives']} found, {ce['false_positives']} false alarms, {ce['missed']} missed)"
        )
    if "--failures" in sys.argv:
        for f in ex["failures"][:25]:
            print(json.dumps(f, default=str))


if __name__ == "__main__":
    main()
