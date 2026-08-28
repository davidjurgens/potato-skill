#!/usr/bin/env python3
"""
Search the Potato Showcase for a design close to the task you are building.

    python find_design.py --type span --category text
    python find_design.py --query "dialogue safety" --with-instructions
    python find_design.py --show text/argumentation-stance/argument-quality

The showcase is 440 annotation task designs, most built from a published paper
or dataset, at https://github.com/davidjurgens/potato-showcase. Each one is a
`config.yaml` with real labels and real question wording, a `metadata.json` with
the paper it came from, and sample data.

Two reasons to look there before writing a config from a field list:

  * **Question wording and label sets.** A scheme that a published paper used
    and reported agreement on beats one invented in a chat window.
  * **Written instructions.** 281 of the 440 carry `annotation_instructions`,
    which is the part of a study this pack otherwise leaves you to write from
    nothing. See `writing-guidelines.md`.

What it will not give you is a whole study: no design in the showcase has a
`phases` block, a consent page or a training round. Take the questions from
there and the workflow from `worked-example.md`.

The index is `showcase.manifest.json`, built by `scripts/generate_manifest.py`
in that repo. This script finds it in a local clone, or downloads it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

MANIFEST_NAME = "showcase.manifest.json"

REMOTE_MANIFEST = (
    "https://raw.githubusercontent.com/davidjurgens/potato-showcase/main/"
    + MANIFEST_NAME
)

#: Where a clone tends to be, relative to wherever this is run.
CANDIDATE_DIRS = (
    os.environ.get("POTATO_SHOWCASE", ""),
    "potato-showcase",
    os.path.join("..", "potato-showcase"),
    os.path.join("..", "..", "potato-showcase"),
    os.path.expanduser(os.path.join("~", "potato-showcase")),
    os.path.expanduser(os.path.join("~", "Documents", "Projects", "potato-showcase")),
)


def locate(explicit: str | None) -> tuple:
    """Return (manifest dict, local clone root or None)."""
    if explicit:
        if explicit.startswith(("http://", "https://")):
            return _fetch(explicit), None
        if os.path.isdir(explicit):
            path = os.path.join(explicit, MANIFEST_NAME)
        else:
            path = explicit
        if not os.path.isfile(path):
            sys.exit(f"No manifest at {path}")
        with open(path, encoding="utf-8") as f:
            return json.load(f), os.path.dirname(os.path.abspath(path))

    for directory in CANDIDATE_DIRS:
        if not directory:
            continue
        path = os.path.join(directory, MANIFEST_NAME)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f), os.path.abspath(directory)

    for directory in CANDIDATE_DIRS:
        if directory and os.path.isdir(directory):
            sys.exit(
                f"Found a showcase clone at {directory} but no {MANIFEST_NAME}.\n"
                f"Build it there:  python3 scripts/generate_manifest.py")

    return _fetch(REMOTE_MANIFEST), None


def _fetch(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        sys.exit(
            f"Could not read the showcase manifest from {url}: {exc}\n"
            f"Clone https://github.com/davidjurgens/potato-showcase and pass "
            f"--showcase <dir>, or set POTATO_SHOWCASE.")


def _haystack(design: dict) -> str:
    parts = [design.get("title") or "", design.get("description") or "",
             design.get("id") or "", design.get("paper_reference") or "",
             " ".join(design.get("tags") or []),
             " ".join(design.get("domain") or []),
             " ".join(design.get("use_case") or []),
             " ".join(design.get("scheme_names") or [])]
    return " ".join(parts).lower()


def search(manifest: dict, args) -> list:
    results = []
    terms = [t.lower() for t in (args.query or "").split()]

    for design in manifest["designs"]:
        types = set(design.get("annotation_types_in_config")
                    or design.get("annotation_types") or [])
        if args.type and not set(args.type) <= types:
            continue
        if args.category and design.get("category") not in args.category:
            continue
        if args.complexity and design.get("complexity") != args.complexity:
            continue
        if args.with_instructions and not design.get("has_instructions"):
            continue
        if args.with_paper and not design.get("paper_url"):
            continue
        if args.display_type and args.display_type not in (
                design.get("display_types") or []):
            continue

        haystack = _haystack(design)
        if terms:
            score = sum(haystack.count(term) for term in terms)
            if not all(term in haystack for term in terms):
                continue
        else:
            score = 0

        # Ties broken toward designs you can actually learn wording from.
        score = (score, design.get("instruction_words", 0),
                 1 if design.get("featured") else 0)
        results.append((score, design))

    results.sort(key=lambda pair: pair[0], reverse=True)
    return [design for _score, design in results][:args.limit]


def show(design_id: str, manifest: dict, root: str | None) -> int:
    match = next((d for d in manifest["designs"] if d["id"] == design_id), None)
    if match is None:
        near = [d["id"] for d in manifest["designs"] if design_id in d["id"]][:8]
        print(f"No design with id {design_id!r}."
              + (f" Did you mean:\n  " + "\n  ".join(near) if near else ""),
              file=sys.stderr)
        return 1

    print(f"# {match['title']}\n")
    print(match.get("description") or "")
    if match.get("paper_reference"):
        print(f"\nPaper:   {match['paper_reference']}  {match.get('paper_url') or ''}")
    if match.get("dataset_url"):
        print(f"Dataset: {match['dataset_url']}")
    print(f"Types:   {', '.join(match.get('annotation_types_in_config') or [])}")
    print(f"Path:    {match['path']}\n")

    if root:
        config_path = os.path.join(root, match["path"], "config.yaml")
        if os.path.isfile(config_path):
            print("--- config.yaml " + "-" * 50)
            with open(config_path, encoding="utf-8") as f:
                print(f.read())
            return 0

    url = (f"https://github.com/davidjurgens/potato-showcase/tree/main/"
           f"{match['path']}")
    print(f"No local clone, so the config is not printed. It is at:\n  {url}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--showcase", default=None,
                        help="Clone directory, manifest path, or URL")
    parser.add_argument("--query", default="", help="Free text to match")
    parser.add_argument("--type", action="append", default=[],
                        help="Require this annotation type (repeatable)")
    parser.add_argument("--display-type", default=None)
    parser.add_argument("--category", action="append", default=[],
                        help="text, semeval, video, image, audio, evaluation, "
                             "preference-learning, agentic, multimodal, templates")
    parser.add_argument("--complexity", default=None,
                        choices=["beginner", "intermediate", "advanced"])
    parser.add_argument("--with-instructions", action="store_true",
                        help="Only designs that carry written instructions")
    parser.add_argument("--with-paper", action="store_true",
                        help="Only designs with a paper URL")
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--show", default=None, metavar="ID",
                        help="Print one design's config and metadata")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    manifest, root = locate(args.showcase)

    if args.show:
        return show(args.show, manifest, root)

    results = search(manifest, args)

    if args.as_json:
        print(json.dumps(results, indent=2))
        return 0 if results else 1

    if not results:
        print("Nothing matched. Loosen the filters, or list what is available:\n"
              f"  types:      {', '.join(sorted(manifest['annotation_types']))}\n"
              f"  categories: {', '.join(sorted(manifest['categories']))}")
        return 1

    print(f"{len(results)} of {manifest['count']} designs\n")
    for design in results:
        types = ", ".join(design.get("annotation_types_in_config") or [])
        print(f"{design['id']}")
        print(f"    {design['title']}")
        print(f"    {types}"
              + (f"  ·  {design['instruction_words']} words of instructions"
                 if design.get("has_instructions") else "  ·  no instructions"))
        if design.get("paper_reference"):
            print(f"    {design['paper_reference']}")
        print()

    print("Read one with:  --show <id>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
