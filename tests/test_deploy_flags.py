"""
Every command-line flag the deploy prose names has to exist in Potato.

`test_skill_sync.py` checks backticked identifiers in seven files, and its token
pattern cannot see a flag: `--backup` starts with a hyphen. `deploying.md` names
about forty of them, across `potato deploy`'s ten subcommands, `potato share`
and `potato start`, and 2.10 alone added the `--backup` family and target-specific
flags such as `--subnet` and `--cloud`.

The flags are read off the parsers rather than from `--help` text where a
parser is reachable, so a flag that is renamed fails here even if some help
string still mentions the old name. `potato start` builds and parses its parser
in one call (`arg_utils.arguments`), so its flags come from `--help`.
"""

import re
import subprocess
import sys

import pytest

from skillpack import pack_path

FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")


def _parser_flags(parser):
    """Every option string on a parser and, recursively, its subparsers."""
    import argparse

    flags = set()
    for action in parser._actions:
        flags |= {s for s in action.option_strings if s.startswith("--")}
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                flags |= _parser_flags(sub)
    return flags


@pytest.fixture(scope="module")
def cli_flags():
    from potato.deploy.cli import build_parser as deploy_parser
    from potato.deploy.share_cli import build_parser as share_parser

    flags = _parser_flags(deploy_parser()) | _parser_flags(share_parser())
    start_help = subprocess.run(
        [sys.executable, "-m", "potato", "start", "--help"],
        capture_output=True, text=True, timeout=120,
    ).stdout
    flags |= set(FLAG.findall(start_help))
    return flags


def _deploy_prose():
    with open(pack_path("references/deploying.md"), encoding="utf-8") as f:
        reference = f.read()
    with open(pack_path("SKILL.md"), encoding="utf-8") as f:
        skill = f.read()
    # Only SKILL.md's deploy section: the rest of it names `potato start`,
    # `validate` and `preview` flags that other guards already cover.
    section = skill.split("## Deploying it", 1)[1].split("\n## ", 1)[0]
    return {"references/deploying.md": reference, "SKILL.md#deploying-it": section}


def test_the_prose_names_flags_at_all():
    """A regex that stopped matching would pass the real test with nothing."""
    named = set()
    for text in _deploy_prose().values():
        named |= set(FLAG.findall(text))
    assert {"--backup", "--provider", "--dry-run"} <= named, sorted(named)


def test_every_deploy_flag_named_in_prose_exists(cli_flags):
    unknown = []
    for where, text in _deploy_prose().items():
        for flag in sorted(set(FLAG.findall(text))):
            if flag not in cli_flags:
                unknown.append(f"{where}: {flag}")
    assert not unknown, (
        "The deploy prose names flags no Potato parser defines:\n  "
        + "\n  ".join(unknown)
        + f"\n\nKnown flags: {' '.join(sorted(cli_flags))}"
    )
