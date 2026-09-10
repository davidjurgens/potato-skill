#!/usr/bin/env python3
"""
Turn "Potato is broken" or "Potato cannot do this" into a report a maintainer can act on.

    python report_issue.py bug --title "Waveform never generates for media_directory audio" \
        --observed "every POST to /api/waveform/generate returns use_client_fallback" \
        --expected "a cached waveform, as the audio_annotation docs describe" \
        --repro "potato start config.yaml -p 8000, open an item, watch the network tab" \
        --config config.yaml --log server.log

    python report_issue.py feature --title "Per-utterance audio in a dialogue display" \
        --goal "annotate a voice-agent call where each turn is its own recording" \
        --tried "audio_dialogue and speech_transcript; both take one file per item" \
        --needed "a turns_key whose entries each carry their own audio url"

    python report_issue.py bug --title "..." --submit --confirm     # files it with gh

It collects the things every report needs and the reporter never has to hand:
the Potato version, the platform, whether the config passes `--strict`, and the
shape of one data record. It redacts before any of that leaves the machine --
API keys, `secret_key`, crowd credentials, email addresses and the home
directory out of every path -- and prints what it removed, because a redactor
you cannot audit is worse than none. It also searches the repository's open and
closed issues first, since a duplicate costs a maintainer more than silence.

Nothing is filed unless you pass both `--submit` and `--confirm`, and a body
still holding a `_(fill this in)_` placeholder is refused. Without those flags
it writes the report to a file and prints a prefilled GitHub URL, which is the
path for a person who would rather read it before it becomes public.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_REPO = "davidjurgens/potato"

#: A GitHub issue URL carries the whole body in the query string. Long ones are
#: truncated or refused somewhere between the browser and the server, and a
#: silently shortened body is the worst outcome here, so past this the script
#: hands over the bare /issues/new URL and the file to paste from.
URL_BUDGET = 6000

PLACEHOLDER = "_(fill this in)_"

#: Key names whose value never belongs in a public issue. Matched
#: case-insensitively against the part before the colon, at any indentation, so
#: `api_key`, `ai_config.api_key` and a bare `token:` all hit.
SECRET_KEYS = (
    "api_key", "apikey", "secret_key", "secret", "token", "password", "passwd",
    "credential", "credentials", "admin_api_key", "completion_code",
    "access_key", "private_key", "client_secret", "hf_token", "auth",
)

#: Value shapes that are secrets wherever they appear, including inside prose
#: and log lines, where no key name is there to catch them.
SECRET_VALUES = (
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), "<redacted-api-key>"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"), "<redacted-github-token>"),
    (re.compile(r"\bhf_[A-Za-z0-9]{16,}"), "<redacted-hf-token>"),
    (re.compile(r"\bAKIA[0-9A-Z]{12,}"), "<redacted-aws-key>"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}"), "Bearer <redacted>"),
    (re.compile(r"\b[A-Za-z][A-Za-z0-9+.\-]*://[^/\s:@]+:[^/\s@]+@"), "://<redacted-userinfo>@"),
    (re.compile(r"\b[\w.+\-]+@[\w\-]+\.[\w.\-]+\b"), "<redacted-email>"),
)


def _redact(text: str) -> tuple[str, dict[str, int]]:
    """Return the text with secrets removed, and a count per reason.

    The counts are the point. A reporter has to be able to see that the
    redactor fired where they expected and did not eat the line that shows the
    bug, and the only way to offer that without printing the secret is to name
    what was taken and how often.
    """
    removed: dict[str, int] = {}

    def bump(reason: str, n: int = 1) -> None:
        if n:
            removed[reason] = removed.get(reason, 0) + n

    lines = []
    key_pattern = re.compile(
        r"^(?P<lead>\s*-?\s*\"?)(?P<key>[A-Za-z0-9_.\-]+)(?P<mid>\"?\s*[:=]\s*)(?P<value>\S.*)$"
    )
    for line in text.splitlines():
        match = key_pattern.match(line)
        if match:
            key = match.group("key").lower()
            if any(s in key for s in SECRET_KEYS):
                lines.append(
                    f"{match.group('lead')}{match.group('key')}"
                    f"{match.group('mid')}<redacted>"
                )
                bump(f"{match.group('key')}: value removed")
                continue
        lines.append(line)
    text = "\n".join(lines)

    for pattern, replacement in SECRET_VALUES:
        text, n = pattern.subn(replacement, text)
        bump(replacement, n)

    home = os.path.expanduser("~")
    if home and home != "/":
        text, n = re.subn(re.escape(home), "~", text)
        bump("home directory replaced with ~", n)

    return text, {k: v for k, v in removed.items() if k}


def _run(argv: list[str], cwd: str | None = None, timeout: int = 90):
    """Run a command and hand back (ok, combined output). Never raises."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, cwd=cwd)
    except FileNotFoundError:
        return False, f"{argv[0]} is not on PATH"
    except subprocess.TimeoutExpired:
        return False, f"{' '.join(argv)} did not finish in {timeout}s"
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out.strip()


def potato_version() -> str:
    """The version string, plus the commit when Potato is an editable checkout.

    There is no `potato --version`. The distribution metadata is the only
    source, and on its own it is not enough for a bug report: 2.7.0 has covered
    hundreds of commits, so anyone running from a clone needs the SHA. Pip
    records the clone's location in `direct_url.json` (PEP 610) for an editable
    install, which is what makes the SHA reachable without asking.
    """
    try:
        import importlib.metadata as metadata
        dist = metadata.distribution("potato-annotation")
        version = dist.version
    except Exception:
        return ("potato-annotation is not installed in the Python running this "
                "script")
    try:
        direct = json.loads(dist.read_text("direct_url.json") or "{}")
        if direct.get("dir_info", {}).get("editable"):
            url = direct.get("url", "")
            if url.startswith("file://"):
                from urllib.request import url2pathname
                checkout = url2pathname(urllib.parse.urlparse(url).path)
                ok, sha = _run(["git", "-C", checkout, "rev-parse", "HEAD"],
                               timeout=20)
                if ok and re.fullmatch(r"[0-9a-f]{40}", sha.strip()):
                    return f"{version}, editable checkout at {sha.strip()[:12]}"
                return f"{version}, editable checkout (commit unknown)"
    except Exception:
        pass
    return version


def environment() -> dict[str, str]:
    return {
        "potato": potato_version(),
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
    }


def validate(config: str) -> str:
    """What `potato validate --strict` says, which decides whether this is a bug.

    A config that fails `--strict` has a typo'd key, and a typo'd key in a block
    Potato treats as opaque disables a feature silently. That is the common
    cause of "this does nothing" and it is not a defect in Potato.
    """
    ok, out = _run(["potato", "validate", config, "--strict"])
    tail = "\n".join(out.splitlines()[-12:]).strip()
    verdict = "passes `--strict`" if ok else "FAILS `--strict`"
    return f"{verdict}\n\n```\n{tail or '(no output)'}\n```" if tail else verdict


def data_shape(path: str, limit: int = 40) -> str:
    """Key names and value types of the first record. Never the values.

    A maintainer nearly always needs the shape of an item rather than its
    content, and the content is someone's corpus.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            head = handle.read(2_000_000)
    except OSError as exc:
        return f"could not read {os.path.basename(path)}: {exc}"

    record = None
    count = None
    stripped = head.lstrip()
    try:
        if stripped.startswith("["):
            parsed = json.loads(head)
            record, count = (parsed[0] if parsed else None), len(parsed)
        elif stripped.startswith("{"):
            lines = [l for l in head.splitlines() if l.strip()]
            record, count = json.loads(lines[0]), len(lines)
        else:  # csv/tsv: the header line is the shape
            first = head.splitlines()[0] if head.splitlines() else ""
            sep = "\t" if first.count("\t") > first.count(",") else ","
            return ("columns: "
                    + ", ".join(f"`{c.strip()}`" for c in first.split(sep)[:limit]))
    except (ValueError, IndexError) as exc:
        return f"could not parse {os.path.basename(path)}: {exc}"

    if not isinstance(record, dict):
        return f"first record is a {type(record).__name__}, not an object"

    rows = []
    for key, value in list(record.items())[:limit]:
        if isinstance(value, list):
            inner = type(value[0]).__name__ if value else "empty"
            rows.append(f"- `{key}`: list of {inner}, length {len(value)}")
        elif isinstance(value, dict):
            rows.append(f"- `{key}`: object with keys "
                        + ", ".join(f"`{k}`" for k in list(value)[:8]))
        else:
            rows.append(f"- `{key}`: {type(value).__name__}")
    plural = "record" if count == 1 else "records"
    header = (f"{count} {plural}. First record's fields:" if count
              else "First record's fields:")
    return header + "\n" + "\n".join(rows)


def excerpt(path: str, max_lines: int, tail: bool = False) -> str:
    """A capped slice of a file. Redaction happens later, not here.

    The assembled body is redacted once, so the counts the script prints are
    the number of secrets it found rather than the number of passes it made
    over them.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError as exc:
        return f"could not read {os.path.basename(path)}: {exc}"
    clipped = lines[-max_lines:] if tail else lines[:max_lines]
    note = ""
    if len(lines) > max_lines:
        where = "last" if tail else "first"
        note = f"\n({where} {max_lines} of {len(lines)} lines)"
    return "\n".join(clipped) + note


#: Words too common in an issue title to narrow anything down.
SEARCH_STOPWORDS = {
    "the", "a", "an", "is", "are", "not", "no", "does", "do", "for", "with",
    "and", "in", "on", "of", "to", "when", "it", "that", "but", "per", "its",
    "own", "each", "from", "gives", "every", "never", "cannot", "can", "add",
    "support", "bug", "issue", "potato", "error", "fails", "failing", "wrong",
}

#: How many of the title's words an existing issue's title has to share before
#: it is worth a reporter's time. Below this the list fills with unrelated
#: issues, and a duplicate check nobody reads is the same as none.
MATCH_FLOOR = 2


def _search_terms(title: str) -> tuple[list[str], list[str]]:
    """(the terms to query with, every word to score against).

    Identifiers first, then the longest words. `audio_dialogue` narrows the
    search far more than `recording` does, and a config key or a type name is
    the thing two people reporting the same bug are most likely to both name.
    """
    words = [w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", title)
             if w.lower() not in SEARCH_STOPWORDS]
    ranked = sorted(words, key=lambda w: ("_" not in w, -len(w)))
    return ranked[:4], [w.lower() for w in words]


def _github_search(query: str) -> tuple[str, list[dict]]:
    """Ask GitHub's issue search. Returns (status, items).

    Through `gh` when it is logged in, because the unauthenticated search
    endpoint allows ten requests a minute and hands back a 403 when you exceed
    it. The status is returned rather than swallowed: "searched and found
    nothing" and "could not search" look identical on screen otherwise, and
    only one of them is a reason to go ahead and file.
    """
    params = {"q": query, "per_page": 30}
    if shutil.which("gh"):
        authed, _ = _run(["gh", "auth", "status"], timeout=30)
        if authed:
            path = "search/issues?" + urllib.parse.urlencode(params)
            ok, out = _run(["gh", "api", "-H", "Accept: application/vnd.github+json",
                            path], timeout=40)
            if ok:
                try:
                    return "ok", json.loads(out).get("items", [])
                except ValueError:
                    pass
    url = ("https://api.github.com/search/issues?"
           + urllib.parse.urlencode(params))
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json",
                      "User-Agent": "potato-tasks-report-issue"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return "ok", json.load(response).get("items", [])
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            return ("the unauthenticated search allows ten requests a minute "
                    "and this one was refused"), []
        return f"GitHub answered {exc.code}", []
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        return f"could not reach GitHub ({exc})", []


def search_issues(repo: str, title: str, limit: int = 5) -> tuple[str, list[dict]]:
    """Open and closed issues whose titles share words with this one.

    A hint, not a verdict. GitHub's issue search ANDs bare terms, so the
    obvious query -- every word of the title -- matches nothing however many
    duplicates exist; these are ORed and then ranked by how much of the title
    each result actually shares.
    """
    chosen, words = _search_terms(title)
    if not chosen:
        return "the title had no distinctive words to search on", []
    status, items = _github_search(
        f"repo:{repo} is:issue " + " OR ".join(chosen))
    if status != "ok":
        return status, []
    scored = [(sum(w in item["title"].lower() for w in words), item)
              for item in items]
    close = sorted((p for p in scored if p[0] >= MATCH_FLOOR),
                   key=lambda p: -p[0])[:limit]
    return "ok", [{"number": i["number"], "state": i["state"],
                   "title": i["title"], "url": i["html_url"], "shared": s}
                  for s, i in close]


BUG_BODY = """\
## What happened

{observed}

## What I expected

{expected}

## How to reproduce

{repro}

## Does the config validate?

{validation}
{data}{config}{log}
## Environment

- Potato: {potato}
- Python: {python}
- Platform: {platform}
"""

FEATURE_BODY = """\
## What I am trying to annotate

{goal}

## What I tried

{tried}

## What would need to exist

{needed}
{data}{config}
## Environment

- Potato: {potato}
- Python: {python}
- Platform: {platform}
"""


def build(args) -> tuple[str, str, dict[str, int]]:
    """Return (title, body, what the redactor removed)."""
    env = environment()

    config_section = ""
    if args.config:
        config_section = ("\n## Config\n\n```yaml\n"
                          + excerpt(args.config, args.config_lines) + "\n```\n")

    log_section = ""
    if args.log:
        log_section = ("\n## Log\n\n```\n"
                       + excerpt(args.log, args.log_lines, tail=True) + "\n```\n")

    data_section = ""
    if args.data:
        data_section = f"\n## The data, by shape\n\n{data_shape(args.data)}\n"

    common = {
        "data": data_section,
        "config": config_section,
        "validation": validate(args.config) if args.config
                      else PLACEHOLDER + " -- run `potato validate config.yaml --strict`",
        **env,
    }
    if args.kind == "bug":
        body = BUG_BODY.format(
            observed=args.observed or PLACEHOLDER,
            expected=args.expected or PLACEHOLDER,
            repro=args.repro or PLACEHOLDER,
            log=log_section,
            **common,
        )
    else:
        body = FEATURE_BODY.format(
            goal=args.goal or PLACEHOLDER,
            tried=args.tried or PLACEHOLDER,
            needed=args.needed or PLACEHOLDER,
            **common,
        )

    body, removed = _redact(body)
    title = f"[{args.kind}] {args.title}"
    return title, body, removed


def prefilled_url(repo: str, title: str, body: str) -> str:
    """A GitHub new-issue URL, or the bare one when the body will not fit."""
    base = f"https://github.com/{repo}/issues/new"
    full = base + "?" + urllib.parse.urlencode({"title": title, "body": body})
    return full if len(full) <= URL_BUDGET else base


def submit(repo: str, title: str, body: str, labels: list[str]) -> int:
    if not shutil.which("gh"):
        print("gh is not installed, so nothing was filed. Open the URL above "
              "and paste the body from the report file.", file=sys.stderr)
        return 1
    ok, _ = _run(["gh", "auth", "status"], timeout=30)
    if not ok:
        print("gh is installed but not logged in. Run `gh auth login`, or open "
              "the URL above.", file=sys.stderr)
        return 1
    # Through a file rather than an argv value: the body carries a whole config
    # and a log tail, and `--body-file` is what gh documents for that.
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                     encoding="utf-8") as handle:
        handle.write(body)
        body_file = handle.name
    argv = ["gh", "issue", "create", "--repo", repo, "--title", title,
            "--body-file", body_file]
    for label in labels:
        argv += ["--label", label]
    try:
        ok, out = _run(argv, timeout=120)
    finally:
        try:
            os.unlink(body_file)
        except OSError:
            pass
    print(out)
    if not ok:
        print("\nNothing was filed. A label needs write access on the "
              "repository, so try again without --label if that is what it "
              "refused.", file=sys.stderr)
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kind", choices=("bug", "feature"),
                        help="a defect, or something Potato cannot currently do")
    parser.add_argument("--title", required=True,
                        help="one line naming the symptom, not the area")
    parser.add_argument("--repo", default=DEFAULT_REPO,
                        help=f"where to file it (default {DEFAULT_REPO})")

    bug = parser.add_argument_group("bug")
    bug.add_argument("--observed", help="what happened, as measured")
    bug.add_argument("--expected", help="what the docs or the config led you to expect")
    bug.add_argument("--repro", help="the shortest sequence that shows it")

    feature = parser.add_argument_group("feature request")
    feature.add_argument("--goal", help="what you are trying to annotate")
    feature.add_argument("--tried", help="the closest existing type or key, and why it does not fit")
    feature.add_argument("--needed", help="what would have to exist")

    evidence = parser.add_argument_group("evidence")
    evidence.add_argument("--config", help="config to validate and include, redacted")
    evidence.add_argument("--log", help="server log to include the tail of, redacted")
    evidence.add_argument("--data", help="data file to describe by shape, never by content")
    evidence.add_argument("--config-lines", type=int, default=120,
                          help="cap on config lines included (default 120)")
    evidence.add_argument("--log-lines", type=int, default=60,
                          help="cap on log lines included (default 60)")

    delivery = parser.add_argument_group("delivery")
    delivery.add_argument("--out", help="where to write the report "
                          "(default potato-issue-<kind>.md in the working directory)")
    delivery.add_argument("--no-search", action="store_true",
                          help="skip the duplicate search")
    delivery.add_argument("--submit", action="store_true",
                          help="file it with gh; needs --confirm as well")
    delivery.add_argument("--confirm", action="store_true",
                          help="required by --submit. Filing is public and cannot be undone")
    delivery.add_argument("--label", action="append", default=[],
                          help="label to set; needs write access on the repository")
    delivery.add_argument("--json", dest="as_json", action="store_true",
                          help="machine-readable result instead of the report")
    args = parser.parse_args()

    title, body, removed = build(args)
    out = args.out or f"potato-issue-{args.kind}.md"
    try:
        with open(out, "w", encoding="utf-8") as handle:
            handle.write(f"# {title}\n\n{body}")
    except OSError as exc:
        print(f"could not write {out}: {exc}", file=sys.stderr)
        out = ""

    if args.no_search:
        search_status, similar = "skipped", []
    else:
        search_status, similar = search_issues(args.repo, args.title)
    url = prefilled_url(args.repo, title, body)
    holes = body.count(PLACEHOLDER)

    if args.as_json:
        print(json.dumps({
            "title": title, "body": body, "report_file": out,
            "redacted": removed, "search_status": search_status,
            "similar": similar, "url": url, "placeholders": holes,
        }, indent=2))
    else:
        print(f"{title}\n{'=' * len(title)}\n\n{body}")
        if removed:
            print("Redacted before this left the machine:")
            for reason, count in sorted(removed.items()):
                print(f"  - {reason}" + (f" x{count}" if count > 1 else ""))
            print()
        if similar:
            print("Possible duplicates -- read these before filing:")
            for issue in similar:
                print(f"  #{issue['number']} ({issue['state']}) {issue['title']}")
                print(f"    {issue['url']}")
            print()
        elif search_status == "ok":
            print("No existing issue shares two or more words with that title.\n")
        elif search_status != "skipped":
            print(f"The duplicate search did not run: {search_status}. "
                  f"Check {args.repo}/issues by hand before filing.\n")
        if holes:
            one = holes == 1
            print(f"{holes} section{'' if one else 's'} still "
                  f"{'says' if one else 'say'} {PLACEHOLDER}. Fill "
                  f"{'it' if one else 'them'} in before filing.\n")
        if out:
            print(f"Report written to {out}")
        if url.endswith("/issues/new"):
            print(f"To file it by hand: {url}\n"
                  f"The body is too long for a prefilled URL, so paste it from "
                  f"{out or 'the report above'}.")
        else:
            print(f"To file it by hand: {url}")

    if args.submit:
        if holes:
            print(f"\nRefusing to file a report with {holes} unfilled "
                  f"section{'s' if holes != 1 else ''}.", file=sys.stderr)
            return 2
        if not args.confirm:
            print("\n--submit needs --confirm. Filing opens a public issue on "
                  f"{args.repo} under whichever account gh is logged in as, and "
                  "it cannot be withdrawn. Show this body to whoever is asking "
                  "for it first.", file=sys.stderr)
            return 2
        return submit(args.repo, title, body, args.label)
    return 0


if __name__ == "__main__":
    sys.exit(main())
