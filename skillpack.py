"""
Paths into the packaged skill, and what it holds.

Scanned rather than listed by hand. In Potato's tree the pack was a subpackage
with a manifest tuple, and the tuple could fall out of step with the directory.
Here the directory is the deliverable, so whatever sits in it ships.
"""

import os

ROOT = os.path.dirname(os.path.abspath(__file__))

SKILL_NAME = "potato-tasks"
SKILL_DIR = os.path.join(ROOT, "skills", SKILL_NAME)
REFERENCES_DIR = os.path.join(SKILL_DIR, "references")
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")

SKILL_MD = os.path.join(SKILL_DIR, "SKILL.md")
AGENTS_MD = os.path.join(ROOT, "AGENTS.md")

#: Every `references/` file, generated and hand-written alike.
REFERENCES = tuple(
    sorted(f for f in os.listdir(REFERENCES_DIR) if f.endswith(".md"))
)

#: Executable helpers. They are procedures long enough to get wrong by hand --
#: booting and reading the log, walking the study in a browser, estimating
#: effort, handing a task over, reading the admin API back -- and they are what
#: an agent runs repeatedly, so they are code rather than prose.
SCRIPTS = tuple(sorted(f for f in os.listdir(SCRIPTS_DIR) if f.endswith(".py")))

#: Written by `scripts/generate_references.py` from Potato's registries and the
#: key-doc table, so the field lists an agent reads cannot drift from the ones
#: the server enforces. Everything else in `references/` is hand-written.
GENERATED_REFERENCES = (
    "annotation-types.md",
    "config-keys.md",
    "config-keys-nested.md",
)


def reference_path(name: str) -> str:
    return os.path.join(REFERENCES_DIR, name)


def script_path(name: str) -> str:
    return os.path.join(SCRIPTS_DIR, name)


#: Potato's own checkout. The guards need more than the installed package:
#: `examples/advanced/full-study-skeleton` is the worked example the references
#: copy verbatim, and `potato/flask_server.py` is where commands are dispatched.
#: Neither ships in the wheel. Defaults to a sibling clone; CI sets the variable.
POTATO_REPO = os.environ.get("POTATO_REPO") or os.path.join(
    os.path.dirname(ROOT), "potato"
)


def has_potato_repo() -> bool:
    return os.path.isfile(os.path.join(POTATO_REPO, "potato", "flask_server.py"))


def potato_repo_path(*parts: str) -> str:
    return os.path.join(POTATO_REPO, *parts)


def pack_path(name: str) -> str:
    """Resolve a pack-relative name against the layout a plugin requires.

    `AGENTS.md` sits at the repository root because every agent tool looks for
    it there. Everything else lives under `skills/potato-tasks/`, which is where
    Claude Code looks for a skill.
    """
    if name == "AGENTS.md":
        return AGENTS_MD
    return os.path.join(SKILL_DIR, name)
