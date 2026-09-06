#!/usr/bin/env python3
"""
What the models in a config actually cost right now, against what Potato thinks.

    python model_prices.py config.yaml
    python model_prices.py --model gpt-4.1-nano
    python model_prices.py config.yaml --json
    python model_prices.py config.yaml --offline

Potato prices a run from a table compiled into `potato/ai/cost.py`, matched by
the longest substring of the model name. That is fine for the models somebody
listed and wrong for everything else: a name the table does not hold is priced
from whatever family row it happens to contain, silently, and
`ai_budget.cap_usd` then refuses or permits runs on that number.

This asks a live source instead, at the moment you run it, so nothing here goes
stale between one study and the next. Prices are quoted per million tokens and
are what OpenRouter publishes for routing that model, which is not necessarily
what your provider will invoice you. Treat every figure as an order of
magnitude for deciding "can this study afford this", never as a quote.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

#: Unauthenticated, and the only network call this script makes.
MODELS_URL = "https://openrouter.ai/api/v1/models"

#: Written after a successful fetch, read only when a later fetch fails. This
#: is a fallback, not a cache with a lifetime: the point of the script is that
#: the number is fresh, so a working network is always preferred to it.
def _cache_path() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "potato-tasks", "model-prices.json")


# A trailing dated snapshot names the same model: "claude-haiku-4-5-20251001"
# is claude-haiku-4.5. Stripping it is safe; guessing past it is not.
_DATED = re.compile(r"-(?:20\d{6}|20\d{2}-\d{2}-\d{2})$")
# Anthropic writes a minor version with a hyphen where the model catalogues
# write a dot. Same model, two spellings, and only one of them resolves.
_MINOR = re.compile(r"-(\d+)-(\d+)$")


def _name_candidates(model: str) -> list:
    """Spellings of one model name, most literal first. Every one of these is
    still looked up by EXACT id: none of them is a fuzzy match."""
    name = (model or "").strip().lower()
    if "/" in name:
        # A vendor-qualified name ("openai/gpt-4o"); the catalogue keys on the
        # same shape, so try it whole before the tail.
        out = [name, name.split("/", 1)[1]]
    else:
        out = [name]
    for form in list(out):
        stripped = _DATED.sub("", form)
        if stripped != form:
            out.append(stripped)
    for form in list(out):
        dotted = _MINOR.sub(lambda m: f"-{m.group(1)}.{m.group(2)}", form)
        if dotted != form:
            out.append(dotted)
    seen, unique = set(), []
    for form in out:
        if form and form not in seen:
            seen.add(form)
            unique.append(form)
    return unique


# ------------------------------------------------------------------ the feed


def fetch_catalogue(timeout: int = 20) -> dict:
    """`{id_tail: row}` from the live feed, plus where it came from."""
    request = urllib.request.Request(
        MODELS_URL, headers={"User-Agent": "potato-tasks/model_prices"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return {"fetched_at": time.time(), "source": MODELS_URL,
            "data": payload.get("data") or []}


def _index(catalogue: dict) -> dict:
    """Model id tail -> row, dropping every `:suffix` variant.

    `:free` and `:batch` ids are priced differently from the model they are
    named after, and 22 rows in the feed are priced at zero. Letting one of
    those answer for a paid model reports a run as costing nothing, which is
    the one wrong answer a spend cap cannot survive.
    """
    index = {}
    for row in catalogue.get("data") or []:
        identifier = (row.get("id") or "").lower()
        if ":" in identifier:
            continue
        index.setdefault(identifier, row)
        index.setdefault(identifier.split("/", 1)[-1], row)
    return index


def live_price(model: str, index: dict) -> tuple:
    """`(row, matched_id)` for an exact match, or `(None, None)`.

    Deliberately no fuzzy fallback. Pricing a model from a name that merely
    looks like it is the failure this script exists to report; committing it
    here would make the report the same shape as the bug.
    """
    for candidate in _name_candidates(model):
        row = index.get(candidate)
        if row is not None:
            return row, row.get("id")
    return None, None


def _per_million(row: dict) -> dict:
    pricing = row.get("pricing") or {}
    def rate(key):
        try:
            return float(pricing.get(key)) * 1_000_000
        except (TypeError, ValueError):
            return None
    return {"input": rate("prompt"), "output": rate("completion"),
            "tiered": bool(pricing.get("overrides"))}


def near_names(model: str, index: dict, limit: int = 5) -> list:
    """Ids sharing a leading word with the query, to put in front of a human.

    Suggestions only. Nothing downstream is allowed to price from these.
    """
    stem = _name_candidates(model)[-1].split("-")[0]
    if len(stem) < 3:
        return []
    hits = sorted({k for k in index if "/" not in k and k.startswith(stem)})
    return hits[:limit]


# ------------------------------------------------- what Potato would charge


def potato_price(model: str, endpoint_type: str) -> dict:
    """Ask the installed Potato what it would charge, and whether it is sure.

    Imports rather than reimplements. Two copies of a matching rule is the
    shape that drifts, and the whole finding here is about a matching rule.
    """
    try:
        from potato.ai import cost
    except Exception as exc:                       # pragma: no cover - env
        return {"available": False, "reason": str(exc)}

    prices = cost.price_for(model, endpoint_type)
    exact = getattr(cost, "price_matched_exactly", None)
    result = {
        "available": True,
        "input": prices[0] if prices else None,
        "output": prices[1] if prices else None,
        "as_of": getattr(cost, "PRICES_AS_OF", "unknown"),
        "local": (endpoint_type or "").lower() in getattr(
            cost, "LOCAL_ENDPOINTS", frozenset()),
        # None where the installed Potato predates the check, which is a
        # different thing from "it matched exactly" and is reported as such.
        "matched_exactly": exact(model, endpoint_type) if exact else None,
    }
    if prices is not None and not result["local"]:
        table = getattr(cost, "PRICE_TABLE", {})
        rows = [p for p in table if p in (model or "").lower()]
        result["matched_row"] = max(rows, key=len) if rows else None
    return result


# ---------------------------------------------------------- reading a config


def _load_yaml(path: str) -> dict:
    import yaml
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def models_in_config(config: dict, base: str) -> list:
    """Every `(model, endpoint_type, where)` the config names.

    Walks for `ai_config` blocks rather than reading one known path, because
    the model lives under whichever subsystem is switched on, and following
    `ai_config_file` too -- the split the pack recommends for keeping API keys
    out of a committed config puts the model name in the second file.
    """
    found, seen = [], set()

    def add(model, endpoint_type, where):
        key = ((model or "").lower(), (endpoint_type or "").lower())
        if model and key not in seen:
            seen.add(key)
            found.append({"model": model, "endpoint_type": endpoint_type or "",
                          "where": where})

    def walk(node, path):
        if not isinstance(node, dict):
            if isinstance(node, list):
                for i, item in enumerate(node):
                    walk(item, f"{path}[{i}]")
            return
        inner = node.get("ai_config")
        if isinstance(inner, dict):
            add(inner.get("model"), node.get("endpoint_type"),
                f"{path}.ai_config" if path else "ai_config")
        sidecar = node.get("ai_config_file")
        if isinstance(sidecar, str):
            full = sidecar if os.path.isabs(sidecar) else os.path.join(base, sidecar)
            if os.path.isfile(full):
                try:
                    merged = _load_yaml(full)
                except Exception:
                    merged = {}
                add(merged.get("model"),
                    merged.get("endpoint_type") or node.get("endpoint_type"),
                    sidecar)
            else:
                found.append({"model": None, "endpoint_type": "",
                              "where": sidecar, "missing": True})
        for key, value in node.items():
            if key != "ai_config":
                walk(value, f"{path}.{key}" if path else str(key))

    walk(config, "")
    return found


# ----------------------------------------------------------------- reporting


def _gap(ratio: float) -> str:
    """How far Potato's price sits from the live one, as a whole clause.

    `{ratio:.0f}x` reads as "1x" for a 25% gap, which states there is no gap at
    all. Below 1.5 the honest unit is a percentage, and the direction has to be
    in the words rather than left to the reader.
    """
    if ratio >= 1.5:
        return f"{ratio:.0f}x the live rate"
    if ratio > 1:
        return f"{(ratio - 1) * 100:.0f}% above the live rate"
    if ratio > 2 / 3:
        return f"{(1 - ratio) * 100:.0f}% below the live rate"
    return f"{1 / ratio:.0f}x under the live rate"


def review(model: str, endpoint_type: str, index: dict,
           have_catalogue: bool = True) -> dict:
    """One model's two prices and what the difference means.

    `have_catalogue` is carried rather than inferred from an empty index.
    "the feed does not list this model" and "there was no feed" are different
    findings, and reporting the second as the first is how a reader concludes
    a model is unlisted when nothing ever asked.
    """
    potato_says = potato_price(model, endpoint_type)
    # A self-hosted model is already correctly priced at zero, so looking it up
    # can only produce noise: a near-name suggestion for a checkpoint nobody is
    # billing for reads as though the zero were a gap to fill.
    if potato_says.get("local"):
        index = {}
    row, matched_id = live_price(model, index) if index else (None, None)
    report = {
        "model": model,
        "endpoint_type": endpoint_type,
        "live": None,
        "live_id": matched_id,
        "live_checked": bool(have_catalogue) and not potato_says.get("local"),
        "potato": potato_says,
        "verdict": "",
        "suggestions": [],
    }
    if row is not None:
        report["live"] = _per_million(row)
    elif index:
        report["suggestions"] = near_names(model, index)

    potato = report["potato"]
    live = report["live"]

    if potato.get("local"):
        report["verdict"] = (
            "self-hosted: Potato prices this at zero, which is right. The "
            "token count still predicts how long the run takes.")
    elif not report["live_checked"]:
        report["verdict"] = (
            "no live prices available, so this is Potato's compiled table "
            "alone -- the thing this script exists to second-guess")
    elif live and potato.get("input") is not None:
        ratio = potato["input"] / live["input"] if live["input"] else None
        if potato.get("matched_exactly") is False:
            report["verdict"] = (
                f"Potato prices this from its `{potato.get('matched_row')}` "
                f"row, not its own")
            if ratio and ratio > 1.05:
                report["verdict"] += (
                    f" -- {_gap(ratio)}, so a cap will refuse runs you can "
                    f"afford")
            elif ratio and ratio < 0.95:
                report["verdict"] += (
                    f" -- {_gap(ratio)}, so a cap will let spend through")
        elif ratio and (ratio > 1.05 or ratio < 0.95):
            report["verdict"] = (
                f"the shipped table has its own row for this and disagrees "
                f"with the live rate ({potato['input']:g} against "
                f"{live['input']:g} in)")
        else:
            report["verdict"] = "the shipped table agrees with the live rate"
    elif live and potato.get("input") is None:
        report["verdict"] = (
            "no price on record in Potato, so it reports tokens and no cost. "
            "The live rate above is what a run would actually cost")
    elif not live and potato.get("input") is not None:
        report["verdict"] = (
            "not in the live catalogue, and Potato prices it anyway from "
            f"`{potato.get('matched_row')}`. Check that row is the same model")
    else:
        report["verdict"] = "priced by neither. A run reports tokens only"
    return report


def _print(reports, catalogue_note, as_of):
    for report in reports:
        print(f"\n{report['model']}"
              + (f"   [{report['endpoint_type']}]" if report["endpoint_type"] else ""))
        live = report["live"]
        if report["potato"].get("local"):
            print("  live      not looked up: this runs on your own hardware")
        elif not report["live_checked"]:
            print("  live      not looked up: no live prices this run")
        elif live and live["input"] is not None:
            tier = "  (tiered above a context threshold)" if live["tiered"] else ""
            print(f"  live     ${live['input']:>8.3f} in / ${live['output']:>8.3f} out "
                  f"per 1M   {report['live_id']}{tier}")
        else:
            print("  live      no exact match in the catalogue")
            if report["suggestions"]:
                print(f"            near names: {', '.join(report['suggestions'])}")
        potato = report["potato"]
        if not potato.get("available"):
            print("  Potato    not importable here, so nothing to compare")
        elif potato.get("input") is None:
            print(f"  Potato    no price on record (table as of {potato['as_of']})")
        else:
            row = potato.get("matched_row")
            via = f"   via the '{row}' row" if row else ""
            print(f"  Potato   ${potato['input']:>8.3f} in / ${potato['output']:>8.3f} out "
                  f"per 1M{via}")
        print(f"  -> {report['verdict']}")
    print(f"\n{catalogue_note}")
    print("Per million tokens. What the catalogue publishes for routing this "
          "model, which is\nnot necessarily what your provider invoices. An "
          "order of magnitude, not a quote.")
    if as_of:
        print(f"Potato's compiled table is dated {as_of}.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("config", nargs="?",
                        help="A task config; every model it names is checked")
    parser.add_argument("--model", action="append", default=[],
                        help="Check this model name instead of reading a config")
    parser.add_argument("--endpoint-type", default="",
                        help="Endpoint type for --model, so a self-hosted one "
                             "is not reported as unpriced")
    parser.add_argument("--offline", action="store_true",
                        help="Skip the network and use the last fetch")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    if not args.config and not args.model:
        parser.error("give a config, or --model NAME")

    targets, base = [], "."
    for name in args.model:
        targets.append({"model": name, "endpoint_type": args.endpoint_type,
                        "where": "--model"})
    if args.config:
        path = os.path.abspath(args.config)
        if not os.path.isfile(path):
            print(f"No such config: {path}", file=sys.stderr)
            return 2
        base = os.path.dirname(path) or "."
        found = models_in_config(_load_yaml(path), base)
        for entry in found:
            if entry.get("missing"):
                print(f"ai_config_file points at {entry['where']}, which is not "
                      f"here. A model named only in that file is not checked.",
                      file=sys.stderr)
            elif entry["model"]:
                targets.append(entry)
        if not targets:
            print("No model is named in this config. Nothing to price.")
            return 0

    catalogue, note = None, ""
    cache = _cache_path()
    if not args.offline:
        try:
            catalogue = fetch_catalogue(args.timeout)
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            with open(cache, "w", encoding="utf-8") as handle:
                json.dump(catalogue, handle)
            note = (f"Prices fetched just now from {MODELS_URL} "
                    f"({len(catalogue['data'])} models).")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            print(f"Could not reach {MODELS_URL}: {exc}", file=sys.stderr)
    if catalogue is None and os.path.isfile(cache):
        try:
            with open(cache, encoding="utf-8") as handle:
                catalogue = json.load(handle)
            hours = (time.time() - catalogue.get("fetched_at", 0)) / 3600
            note = (f"No live fetch. Falling back to the copy cached "
                    f"{hours:.0f} hours ago, which may be stale.")
        except (OSError, ValueError):
            catalogue = None
    if catalogue is None:
        note = ("No live prices and nothing cached, so only Potato's compiled "
                "table is shown below.")

    index = _index(catalogue) if catalogue else {}
    if catalogue is not None and not index:
        # The fetch worked and produced nothing usable, which is not the same
        # as being offline: the feed's shape has probably changed. Saying "no
        # live prices this run" here would send someone to check their network.
        note += ("  The feed answered but listed no usable models, so its "
                 "shape may have changed.")
    reports = [review(t["model"], t.get("endpoint_type", ""), index,
                      have_catalogue=catalogue is not None)
               for t in targets]
    as_of = next((r["potato"].get("as_of") for r in reports
                  if r["potato"].get("available")), "")

    if args.as_json:
        print(json.dumps({"source_note": note, "models": reports}, indent=2))
        return 0
    _print(reports, note, as_of)
    return 0


if __name__ == "__main__":
    sys.exit(main())
