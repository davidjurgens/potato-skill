#!/usr/bin/env python3
"""
Boot a Potato config and report what the startup log says about it.

    python boot_and_check.py config.yaml -p 8000
    python boot_and_check.py config.yaml -p 8000 --json
    python boot_and_check.py config.yaml -p 8000 --keep   # leave it running

`potato validate` reads the config. This reads what the *server* made of it,
which is the only place several classes of failure appear:

  * a phase named in `order` whose page file is missing -- one ERROR line, and
    the study runs without that phase
  * `attention_checks.enabled: true` with a malformed items file -- one warning,
    `Loaded 0 attention check items`, and quality control is off for the whole
    study
  * a scheme generator that threw -- the page renders a heading with no inputs

Exit status is 0 only when the server answered and nothing above fired.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

#: Features that log a count at boot, and the key that turns each one on.
COUNTED_FEATURES = [
    ("training", "training instances", r"Loaded (\d+) training instances"),
    ("attention_checks", "attention check items", r"Loaded (\d+) attention check items"),
    ("gold_standards", "gold standard items", r"Loaded (\d+) gold standard items"),
]


def _enabled_features(config_path: str) -> set:
    try:
        import yaml
    except ImportError:
        return set()
    try:
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except Exception:
        return set()
    on = set()
    for key, _label, _pattern in COUNTED_FEATURES:
        block = config.get(key)
        if isinstance(block, dict) and block.get("enabled"):
            on.add(key)
    return on


def _wait_for_http(port: int, timeout: float, proc) -> int | None:
    """Poll until the server answers. Returns the status code, or None."""
    deadline = time.time() + timeout
    url = f"http://localhost:{port}/"
    while time.time() < deadline:
        if proc.poll() is not None:
            return None
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code           # a 4xx/5xx still means it is up
        except Exception:
            time.sleep(1)
    return None


def analyse(log_text: str, enabled: set) -> dict:
    """Turn a startup log into findings. Pure, so it is testable without a boot."""
    findings = []

    for line in log_text.splitlines():
        if "Failed to load phase" in line:
            findings.append({"kind": "phase_dropped", "detail": line.strip()})
        elif "Traceback" in line:
            findings.append({"kind": "traceback", "detail": line.strip()})
        elif "[ERROR]" in line and "Failed to load phase" not in line:
            findings.append({"kind": "error", "detail": line.strip()})

    counts = {}
    for key, label, pattern in COUNTED_FEATURES:
        match = re.search(pattern, log_text)
        counts[key] = int(match.group(1)) if match else None
        if key in enabled:
            if counts[key] is None:
                findings.append({
                    "kind": "configured_but_silent",
                    "detail": f"{key}.enabled is true but the log never reported "
                              f"{label}. The feature did not initialise.",
                })
            elif counts[key] == 0:
                findings.append({
                    "kind": "configured_but_empty",
                    "detail": f"{key}.enabled is true and the log says "
                              f"Loaded 0 {label}. The study will run with it off.",
                })

    return {"findings": findings, "counts": counts}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("config")
    parser.add_argument("-p", "--port", type=int, default=8000)
    parser.add_argument("--timeout", type=float, default=120.0,
                        help="Seconds to wait for the first 200 (default: 120)")
    parser.add_argument("--log", default=None, help="Where to write the server log")
    parser.add_argument("--keep", action="store_true",
                        help="Leave the server running after reporting")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    config_path = os.path.abspath(args.config)
    if not os.path.isfile(config_path):
        print(f"No such config: {config_path}", file=sys.stderr)
        return 2

    work_dir = os.path.dirname(config_path) or "."
    log_path = os.path.abspath(args.log or os.path.join(work_dir, "server.log"))

    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            ["potato", "start", os.path.basename(config_path), "-p", str(args.port)],
            cwd=work_dir, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    status = _wait_for_http(args.port, args.timeout, proc)
    time.sleep(1)                                  # let the last lines flush
    with open(log_path, encoding="utf-8") as f:
        log_text = f.read()

    result = analyse(log_text, _enabled_features(config_path))
    result["http_status"] = status
    result["log"] = log_path
    result["url"] = f"http://localhost:{args.port}/"
    result["pid"] = proc.pid

    if status is None:
        result["findings"].insert(0, {
            "kind": "no_response",
            "detail": f"The server never answered on port {args.port}. "
                      f"The log is at {log_path}.",
        })

    if not args.keep:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
        result["pid"] = None

    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"HTTP {status}  {result['url']}")
        for key, count in result["counts"].items():
            if count is not None:
                print(f"  loaded {count:>4}  {key}")
        if result["findings"]:
            print("\nProblems:")
            for finding in result["findings"]:
                print(f"  [{finding['kind']}] {finding['detail']}")
        else:
            print("\nNothing in the log to report.")
        if args.keep and result["pid"]:
            print(f"\nStill running as pid {result['pid']}. Stop it with:"
                  f"\n  kill -- -{result['pid']}")

    return 0 if (status and not result["findings"]) else 1


if __name__ == "__main__":
    sys.exit(main())
