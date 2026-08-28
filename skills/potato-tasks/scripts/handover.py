#!/usr/bin/env python3
"""
Clear the accounts you made while checking a task, and write the handover note.

    python handover.py config.yaml --url http://localhost:8000 --port 8000
    python handover.py config.yaml --dry-run

Every account created while testing is a real annotator. It holds assignments,
its answers count toward agreement, and on a task with a per-item annotator
target it can satisfy that target with answers nobody meant. Wiping
`annotation_output/` is the fix, and it has to happen with the server stopped:
item and user state are already in memory, so a wipe while it runs resets
nothing and the next annotator to arrive gets the completion page.

This deletes annotator data. It refuses to run without `--confirm`, and it
refuses while something is answering on `--port`.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import sys
from datetime import date

#: Written by the server into task_dir; deleting it makes the next boot mint a
#: new one, which is what you want before handing the URL to someone else.
ADMIN_KEY_FILE = "admin_api_key.txt"

RUNNING_TEMPLATE = """\
# {task_name}

Running at {url}

## Starting and stopping it

```bash
cd {task_dir}
nohup potato start {config} -p {port} > server.log 2>&1 &

# stop it
pkill -f "potato start {config} -p {port}"
```

Boot takes 10-20 seconds. It is ready when `curl -s -o /dev/null -w '%{{http_code}}' \\
{url}` prints 200. Startup messages go to `server.log`.

## The admin pages

`{url}/admin` is the dashboard and opens in a browser. The JSON APIs underneath
it -- agreement, quality control, exports -- need a key, which the server writes
into `{task_dir}/{admin_key_file}` on its first boot:

```bash
curl -H "X-API-Key: $(cat {admin_key_file})" {url}/admin/iaa
```

`/admin/iaa` is the agreement report. It names the metric it chose for each
question and how many items the annotators overlapped on.

## Where the data is

`{output_dir}` -- one directory per annotator, rewritten by the server as people
work. Read it, copy it, back it up; do not edit it in place.

## Accounts

{accounts}

## Before you publish anything

Stop the server, take a copy of `{output_dir}`, and keep it somewhere the server
cannot rewrite.

_Handover written {today}._
"""


def _port_is_answering(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _load(config_path: str) -> dict:
    import yaml
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("config")
    parser.add_argument("--url", default=None,
                        help="The URL the researcher will open (default: from --port)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--keep", default="",
                        help="Comma-separated accounts to leave in place")
    parser.add_argument("--confirm", action="store_true",
                        help="Actually delete. Without this, nothing is removed")
    parser.add_argument("--dry-run", action="store_true",
                        help="List what would be deleted and exit")
    parser.add_argument("--no-note", action="store_true",
                        help="Skip writing RUNNING.md")
    args = parser.parse_args(argv)

    config_path = os.path.abspath(args.config)
    if not os.path.isfile(config_path):
        print(f"No such config: {config_path}", file=sys.stderr)
        return 2

    task_dir = os.path.dirname(config_path) or "."
    config = _load(config_path)
    output_dir = os.path.join(task_dir,
                              config.get("output_annotation_dir", "annotation_output/"))
    keep = {name.strip() for name in args.keep.split(",") if name.strip()}

    accounts = []
    if os.path.isdir(output_dir):
        accounts = sorted(
            name for name in os.listdir(output_dir)
            if os.path.isdir(os.path.join(output_dir, name))
        )
    doomed = [name for name in accounts if name not in keep]

    targets = [os.path.join(output_dir, name) for name in doomed]
    for name in ("project.sqlite", "project.sqlite-wal", "project.sqlite-shm",
                 "layouts", ADMIN_KEY_FILE):
        path = os.path.join(task_dir, name)
        if os.path.exists(path):
            targets.append(path)

    print(f"Task directory: {task_dir}")
    print(f"Annotator directories found: {len(accounts)}")
    for name in accounts:
        print(f"  {'keep  ' if name in keep else 'delete'}  {name}")
    print(f"\n{len(targets)} paths would be removed:")
    for path in targets:
        print(f"  {os.path.relpath(path, task_dir)}")

    if args.dry_run:
        return 0

    if not args.confirm:
        print("\nNothing deleted. Re-run with --confirm once the list above is right.")
        return 1

    if _port_is_answering(args.port):
        print(f"\nSomething is listening on port {args.port}. Stop the server "
              f"first -- wiping while it runs resets nothing, because item and "
              f"user state are already in memory.", file=sys.stderr)
        return 1

    for path in targets:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    print(f"\nRemoved {len(targets)} paths.")

    if not args.no_note:
        url = args.url or f"http://localhost:{args.port}"
        note_path = os.path.join(task_dir, "RUNNING.md")
        if keep:
            accounts_text = ("These accounts were left in place: "
                             + ", ".join(f"`{name}`" for name in sorted(keep))
                             + ". Remove them before the real annotators start, "
                               "or their answers will count.")
        else:
            accounts_text = ("Every test account was removed. Annotators register "
                             "themselves from the landing page.")
        with open(note_path, "w", encoding="utf-8") as f:
            f.write(RUNNING_TEMPLATE.format(
                task_name=config.get("annotation_task_name", "Annotation task"),
                url=url, port=args.port, config=os.path.basename(config_path),
                task_dir=task_dir,
                output_dir=os.path.relpath(output_dir, task_dir),
                admin_key_file=ADMIN_KEY_FILE,
                accounts=accounts_text, today=date.today().isoformat(),
            ))
        print(f"Wrote {note_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
