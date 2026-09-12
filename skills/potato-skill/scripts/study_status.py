#!/usr/bin/env python3
"""
Report on a running Potato study: progress, annotators, agreement, problems.

    python study_status.py --url http://localhost:8000 --task-dir .
    python study_status.py --url https://host --key "$KEY" --json

Answers the question a researcher asks once the task is out of your hands and
into other people's: how far along is it, is anyone stuck, is anyone clicking
through, and do they agree yet. Every number here comes from the admin JSON API,
which needs a key and is not linked from anywhere an annotator can see, so the
alternative is a researcher concluding from the annotation page alone that
nothing is happening.

The key is read from ``<task-dir>/admin_api_key.txt`` unless ``--key`` is given.
That file does not exist until the first admin request, so this script asks for
``/admin`` once before looking for it.

Nothing here writes anything. Reclaiming assignments, resetting passwords and
exporting are deliberately not automated -- see ``after-annotators-start.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

#: Fetched in this order; each is optional, and a task with the feature off
#: answers with a disabled marker rather than an error.
ENDPOINTS = (
    ("overview", "/admin/api/overview"),
    ("annotators", "/admin/api/annotators"),
    ("agreement", "/admin/iaa"),
    ("quality_control", "/admin/api/quality_control"),
    ("suspicious", "/admin/api/suspicious_activity"),
    ("stale", "/admin/api/stale_assignments"),
)


def _get(url: str, key: str | None, timeout: float = 20.0):
    """GET a JSON endpoint. Returns (payload, error_string)."""
    request = urllib.request.Request(url)
    if key:
        request.add_header("X-API-Key", key)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200] if e.fp else ""
        return None, f"HTTP {e.code} {detail}".strip()
    except Exception as e:                       # network, DNS, refused, timeout
        return None, str(e)
    try:
        return json.loads(body), None
    except ValueError:
        return None, "response was not JSON"


def find_key(task_dir: str, url: str) -> tuple[str | None, str | None]:
    """The admin key, poking /admin first so the file exists to be read."""
    path = os.path.join(task_dir, "admin_api_key.txt")
    if not os.path.exists(path):
        _get(url.rstrip("/") + "/admin", None)
    if not os.path.exists(path):
        return None, (
            f"No admin key at {path}. Pass --key, or set admin_api_key in the "
            "config. Without it every JSON route answers 403.")
    with open(path, encoding="utf-8") as f:
        return f.read().strip() or None, None


def collect(url: str, key: str | None) -> dict:
    """Fetch every endpoint. Failures are recorded, never raised."""
    base = url.rstrip("/")
    out: dict = {"url": base, "errors": {}}
    for name, path in ENDPOINTS:
        payload, error = _get(base + path, key)
        if error:
            out["errors"][name] = error
        else:
            out[name] = payload
    return out


def summarize(data: dict) -> dict:
    """Reduce the raw payloads to the findings worth printing.

    Pure, so the interpretation can be tested without a server.
    """
    overview = (data.get("overview") or {}).get("overview") or {}
    summary = {
        "items": overview.get("total_items"),
        "items_with_annotations": overview.get("items_with_annotations"),
        "annotations": overview.get("total_annotations"),
        "annotators": overview.get("total_users"),
        "completed_annotators": overview.get("completed_users"),
        "percent_complete": overview.get("completion_percentage"),
        "annotators_detail": [],
        "problems": [],
        "agreement": {},
    }

    for entry in (data.get("annotators") or {}).get("annotators", []) or []:
        summary["annotators_detail"].append({
            "user": entry.get("user_id"),
            "annotated": entry.get("total_annotations"),
            "assigned": entry.get("max_assignments"),
            "remaining": entry.get("remaining_assignments"),
            "percent": entry.get("completion_percentage"),
            "seconds_per_annotation": entry.get("average_seconds_per_annotation"),
            "last_activity": entry.get("last_activity"),
            "phase": entry.get("phase"),
            "suspicious_level": entry.get("suspicious_level"),
            "training_pass_rate": entry.get("training_pass_rate"),
        })
        # The dashboard's own judgement, rather than a threshold invented here.
        if entry.get("suspicious_level") in ("high", "medium"):
            summary["problems"].append(
                f"{entry.get('user_id')} is flagged {entry['suspicious_level']} "
                f"for pace (score {entry.get('suspicious_score')})")

    # /admin/iaa nests the numbers under schemas[name].metrics; the older
    # /admin/api/agreement puts them flat under by_schema[name]. Accept both so
    # this keeps working against either route.
    agreement = data.get("agreement") or {}
    by_schema = agreement.get("schemas") or agreement.get("by_schema") or {}
    silent_schemes = []
    for name, report in by_schema.items():
        if not isinstance(report, dict):
            continue
        metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else report
        items = metrics.get("n_items")
        if items is None:
            items = report.get("items_count")
        summary["agreement"][name] = {
            "kind": report.get("kind"),
            "items": items,
            "error": report.get("error"),
            "metrics": {k: v for k, v in metrics.items()
                        if isinstance(v, (int, float)) and not k.startswith("n_")},
        }
        if items == 0 or report.get("items_count") == 0:
            silent_schemes.append(name)

    # Every configured scheme reporting zero items, on a study that has
    # annotations, is the shape a mid-study scheme rename leaves behind: the
    # answers are stored under a name no report can see. It is also what a study
    # with one annotator per item looks like, so say both.
    if silent_schemes and len(silent_schemes) == len(by_schema) and summary["annotations"]:
        summary["problems"].append(
            f"{summary['annotations']} annotation(s) exist but every configured "
            f"scheme ({', '.join(sorted(silent_schemes))}) reports 0 items. "
            "Either no item has two annotators yet, or a scheme was renamed "
            "after people started — the boot log says which "
            "(after-annotators-start.md)")

    stale = (data.get("stale") or {}).get("stale_assignments") or []
    if stale:
        summary["problems"].append(
            f"{len(stale)} assignment(s) held past the reclaim timeout")

    suspicious = (data.get("suspicious") or {}).get("suspicious_activity") or []
    if suspicious:
        summary["problems"].append(
            f"{len(suspicious)} annotator(s) flagged for suspicious activity")

    qc = data.get("quality_control") or {}
    if qc.get("enabled") is False:
        summary["quality_control"] = "not configured"
    elif qc:
        summary["quality_control"] = qc

    for name, error in (data.get("errors") or {}).items():
        summary["problems"].append(f"could not read {name}: {error}")

    return summary


def render(summary: dict) -> str:
    lines = []
    percent = summary.get("percent_complete")
    lines.append(
        f"{summary.get('items_with_annotations', '?')}/{summary.get('items', '?')} "
        f"items have annotations"
        + (f" ({percent}% complete)" if percent is not None else ""))
    lines.append(
        f"{summary.get('annotations', '?')} annotations from "
        f"{summary.get('annotators', '?')} annotator(s), "
        f"{summary.get('completed_annotators', '?')} finished")

    if summary["annotators_detail"]:
        lines.append("")
        lines.append("Annotators")
        for entry in summary["annotators_detail"]:
            pace = entry.get("seconds_per_annotation")
            pace_text = f", {pace:.0f}s each" if isinstance(pace, (int, float)) and pace else ""
            assigned = entry.get("assigned")
            of_text = f"/{assigned}" if assigned not in (None, "") else ""
            lines.append(
                f"  {entry['user']}: {entry.get('annotated', '?')}{of_text} annotated"
                f"{pace_text}, phase {entry.get('phase') or '?'}"
                f", last seen {entry.get('last_activity') or 'never'}")

    if summary["agreement"]:
        lines.append("")
        lines.append("Agreement")
        for name, report in summary["agreement"].items():
            if report.get("error"):
                lines.append(f"  {name}: {report['error']}")
                continue
            metrics = ", ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}"
                                for k, v in sorted(report["metrics"].items()))
            lines.append(f"  {name} ({report.get('kind') or 'kind unknown'}): "
                         f"{report.get('items')} item(s) {metrics}")

    if summary.get("quality_control") == "not configured":
        lines.append("")
        lines.append("Quality control: not configured")

    lines.append("")
    if summary["problems"]:
        lines.append("Problems")
        for problem in summary["problems"]:
            lines.append(f"  - {problem}")
    else:
        lines.append("Nothing to report.")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    parser.add_argument("--url", default="http://localhost:8000",
                        help="Base URL of the running server")
    parser.add_argument("--task-dir", default=".",
                        help="Where admin_api_key.txt lives")
    parser.add_argument("--key", default=None,
                        help="Admin API key, overriding the key file")
    parser.add_argument("--json", action="store_true",
                        help="Print the summary as JSON")
    parser.add_argument("--raw", action="store_true",
                        help="Print every payload unreduced, for a route this "
                             "script does not summarize")
    args = parser.parse_args(argv)

    key = args.key
    if not key:
        key, problem = find_key(args.task_dir, args.url)
        if problem:
            print(problem, file=sys.stderr)

    data = collect(args.url, key)
    if args.raw:
        print(json.dumps(data, indent=2, default=str))
        return 0

    summary = summarize(data)
    print(json.dumps(summary, indent=2, default=str) if args.json else render(summary))
    return 1 if summary["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
