#!/usr/bin/env python3
"""
Estimate how long a Potato task will take and what it will cost.

    python estimate_effort.py config.yaml
    python estimate_effort.py config.yaml --rate 15 --wpm 220 --json

This is the first question a researcher asks and the config file already
contains most of the answer: how many items, how many annotators each one
needs, how many items one person is allowed, and how much reading and clicking
each item involves.

The numbers are estimates from stated assumptions, printed with the estimate so
they can be argued with. Reading speed and per-question times are the two that
move the total most; override them and re-run rather than trusting one figure.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

#: Seconds of deliberation per question, by annotation type, once the item has
#: been read. Reading time is counted separately and only once per item.
SECONDS_PER_SCHEME = {
    "radio": 4, "likert": 5, "select": 5, "number": 5, "slider": 6,
    "multiselect": 9, "multirate": 12, "ranking": 20, "bws": 25,
    "constant_sum": 25, "pairwise": 15, "matrix": 15,
    "text": 25, "textbox": 25, "highlight": 30,
    "span": 45, "span_linking": 60,
    "bbox": 40, "polygon": 70, "keypoint": 40, "segmentation": 90,
    "pure_display": 0,
}
DEFAULT_SECONDS = 10          # an unrecognized type is assumed mid-weight
NAVIGATION_SECONDS = 3        # page load, next, saving


def _load_config(path: str) -> dict:
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _iter_items(config: dict, base: str):
    """Yield each data row, for as many of the configured files as can be read."""
    files = config.get("data_files") or []
    if isinstance(files, str):
        files = [files]
    for name in files:
        path = name if os.path.isabs(name) else os.path.join(base, name)
        if not os.path.isfile(path):
            continue
        if path.endswith((".csv", ".tsv")):
            import csv
            delimiter = "\t" if path.endswith(".tsv") else ","
            with open(path, encoding="utf-8") as f:
                yield from csv.DictReader(f, delimiter=delimiter)
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
        if not text:
            continue
        if text.startswith("["):
            rows = json.loads(text)
            yield from (r for r in rows if isinstance(r, dict))
        else:
            for line in text.splitlines():
                line = line.strip()
                if line:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(row, dict):
                        yield row


def estimate(config: dict, base: str, wpm: int, rate: float) -> dict:
    items = list(_iter_items(config, base))
    n_items = len(items)

    text_key = (config.get("item_properties") or {}).get("text_key", "text")
    words = [len(str(row.get(text_key, "")).split()) for row in items]
    median_words = sorted(words)[len(words) // 2] if words else 0
    reading_seconds = (median_words / wpm) * 60 if wpm else 0

    schemes = config.get("annotation_schemes") or []
    per_scheme = []
    for scheme in schemes:
        kind = scheme.get("annotation_type", "")
        seconds = SECONDS_PER_SCHEME.get(kind, DEFAULT_SECONDS)
        conditional = bool(scheme.get("display_logic"))
        if conditional:
            # It only appears when its gate is satisfied. Half is a guess, and
            # a bad one if the gate is the common answer -- say so in the output.
            seconds = seconds / 2
        per_scheme.append({"name": scheme.get("name", kind), "type": kind,
                           "seconds": seconds, "conditional": conditional})
    answering_seconds = sum(s["seconds"] for s in per_scheme)

    seconds_per_item = reading_seconds + answering_seconds + NAVIGATION_SECONDS

    per_item = config.get("num_annotators_per_item") or 1
    quota = config.get("max_annotations_per_user")
    if not quota or quota < 0:
        quota = n_items or 1

    judgements = n_items * per_item
    annotators = math.ceil(judgements / quota) if quota else 0

    overhead_seconds = 0
    detail = []
    training = config.get("training") or {}
    if isinstance(training, dict) and training.get("enabled"):
        n_training = _count_training(training, base)
        cost = n_training * (seconds_per_item + 15)      # + reading the feedback
        overhead_seconds += cost
        detail.append(f"training: {n_training} practice items per annotator")
    checks = config.get("attention_checks") or {}
    if isinstance(checks, dict) and checks.get("enabled"):
        n_checks = _count_array(checks.get("items_file"), base)
        overhead_seconds += n_checks * seconds_per_item
        detail.append("attention checks: %d extra item%s per annotator"
                      % (n_checks, "" if n_checks == 1 else "s"))
    gold = config.get("gold_standards") or {}
    if isinstance(gold, dict) and gold.get("enabled"):
        n_gold = _count_array(gold.get("items_file"), base)
        overhead_seconds += n_gold * seconds_per_item
        detail.append("gold standards: %d extra item%s per annotator"
                      % (n_gold, "" if n_gold == 1 else "s"))

    annotator_seconds = quota * seconds_per_item + overhead_seconds
    total_seconds = judgements * seconds_per_item + annotators * overhead_seconds

    return {
        "items": n_items,
        "median_words_per_item": median_words,
        "annotators_per_item": per_item,
        "quota_per_annotator": quota,
        "judgements": judgements,
        "annotators_needed": annotators,
        "seconds_per_item": round(seconds_per_item, 1),
        "reading_seconds_per_item": round(reading_seconds, 1),
        "answering_seconds_per_item": answering_seconds,
        "per_scheme": per_scheme,
        "overhead_per_annotator": detail,
        "minutes_per_annotator": round(annotator_seconds / 60, 1),
        "total_hours": round(total_seconds / 3600, 1),
        "cost": round(total_seconds / 3600 * rate, 2) if rate else None,
        "rate": rate,
        "assumptions": [
            f"reading at {wpm} words per minute, once per item",
            f"{NAVIGATION_SECONDS}s of navigation and saving per item",
            "a scheme behind display_logic counted at half, since it only "
            "sometimes appears",
            "per-question times from the table in this script; override by editing it",
            "no time for reading the instructions page, and no breaks",
        ],
    }


def _count_array(path, base) -> int:
    if not path:
        return 0
    full = path if os.path.isabs(path) else os.path.join(base, path)
    if not os.path.isfile(full):
        return 0
    try:
        with open(full, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return 0
    return len(data) if isinstance(data, list) else 0


def _count_training(training: dict, base: str) -> int:
    path = training.get("data_file")
    if not path:
        return 0
    full = path if os.path.isabs(path) else os.path.join(base, path)
    if not os.path.isfile(full):
        return 0
    try:
        with open(full, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return 0
    if isinstance(data, dict):
        return len(data.get("training_instances") or [])
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("config")
    parser.add_argument("--wpm", type=int, default=240,
                        help="Reading speed for the item text (default: 240)")
    parser.add_argument("--rate", type=float, default=0.0,
                        help="Hourly rate, to turn hours into a cost")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    path = os.path.abspath(args.config)
    if not os.path.isfile(path):
        print(f"No such config: {path}", file=sys.stderr)
        return 2

    result = estimate(_load_config(path), os.path.dirname(path) or ".",
                      args.wpm, args.rate)

    if args.as_json:
        print(json.dumps(result, indent=2))
        return 0

    if result["items"] == 0:
        print("No items could be read from data_files. Everything below is "
              "per-item only.\n")

    print(f"{result['items']} items x {result['annotators_per_item']} annotators "
          f"= {result['judgements']} judgements")
    print(f"{result['annotators_needed']} annotators at a quota of "
          f"{result['quota_per_annotator']} items each\n")

    print(f"Per item: {result['seconds_per_item']}s "
          f"({result['reading_seconds_per_item']}s reading "
          f"{result['median_words_per_item']} words, "
          f"{result['answering_seconds_per_item']}s answering, "
          f"{NAVIGATION_SECONDS}s navigating)")
    for scheme in result["per_scheme"]:
        mark = "  (conditional, counted at half)" if scheme["conditional"] else ""
        print(f"    {scheme['seconds']:>5.0f}s  {scheme['name']} "
              f"({scheme['type']}){mark}")
    for line in result["overhead_per_annotator"]:
        print(f"  + {line}")

    print(f"\nAbout {result['minutes_per_annotator']} minutes per annotator, "
          f"{result['total_hours']} hours in total")
    if result["cost"]:
        print(f"About {result['cost']:.2f} at {result['rate']}/hour")

    print("\nAssuming:")
    for line in result["assumptions"]:
        print(f"  - {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
