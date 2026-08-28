"""
Drift guard for the "Potato has N of these" claims in the skill.

These numbers rot silently. Every wave that registers a schema, a display type
or a config key makes them wrong, and nothing fails. In Potato's own docs that
produced four different answers to "how many annotation types are there?" at
once. The skill states twelve counts of its own, and before this guard existed
`SKILL.md` claimed 41 undocumented blocks against a generated reference that
listed 26.

A wrong count is worse than a vague one here. `SKILL.md` is the file an
authoring agent loads first, and a wrong count sends it looking for keys that do
not exist, or stops it looking for ones that do.

Each case below pins one sentence in one file to the registry that decides it.
When Potato adds a schema and this fails, update the prose -- that is the point.
"""

import re

import pytest

from skillpack import pack_path


def _counts():
    """The authoritative numbers, read from Potato rather than restated."""
    from potato.server_utils.config_key_docs import iter_key_docs
    from potato.server_utils.config_module import KNOWN_CONFIG_KEYS
    from potato.server_utils.displays.registry import display_registry
    from potato.server_utils.examples_manifest import load_manifest
    from potato.server_utils.schemas.registry import schema_registry

    key_docs = dict(iter_key_docs())
    top_docs = {p: d for p, d in key_docs.items() if "." not in p}
    sub_docs = {p: d for p, d in key_docs.items() if "." in p}
    parents = {p.split(".", 1)[0] for p in sub_docs}

    # The blocks `validate --strict` cannot check inside, computed the same way
    # scripts/generate_references.py computes the list it prints.
    unchecked = [
        name for name, allowed in KNOWN_CONFIG_KEYS.items()
        if allowed is None and not name.startswith("_")
        and (name in parents
             or (top_docs.get(name) is not None
                 and top_docs[name].type in ("object", "array")))
    ]

    return {
        "annotation_types": len(schema_registry.get_supported_types()),
        "display_types": len(display_registry.get_supported_types()),
        "documented_top_keys": len(top_docs),
        "documented_sub_keys": len(sub_docs),
        "unchecked_blocks": len(unchecked),
        "examples": load_manifest()["count"],
    }


@pytest.fixture(scope="module")
def counts():
    return _counts()


# (pack-relative path, regex with one capture group, which count it must equal)
CLAIMS = [
    ("SKILL.md", r"the (\d+) display types", "display_types"),
    ("SKILL.md", r"ships (\d+) example projects", "examples"),
    ("SKILL.md",
     r"There are (\d+)\. `references/annotation-types.md`", "annotation_types"),
    ("SKILL.md",
     r"lists the (\d+) documented \*\*top-level\*\* keys", "documented_top_keys"),
    ("SKILL.md",
     r"lists the (\d+) documented \*\*sub-keys\*\*", "documented_sub_keys"),
    ("SKILL.md",
     r"lists the (\d+) blocks whose sub-keys", "unchecked_blocks"),
    ("SKILL.md",
     r"\| `config-keys.md` \| (\d+) top-level keys", "documented_top_keys"),
    ("SKILL.md",
     r"\| `config-keys-nested.md` \| (\d+) sub-keys", "documented_sub_keys"),

    ("AGENTS.md", r"There are (\d+) example projects", "examples"),
    ("AGENTS.md", r"There are (\d+) of them", "annotation_types"),

    ("references/building-the-ui.md",
     r"### The (\d+) display types", "display_types"),
    ("references/worked-example.md", r"ships (\d+) examples", "examples"),
    ("references/designing-a-task.md", r"(\d+) types", "annotation_types"),
]


@pytest.mark.parametrize("rel_path,pattern,key", CLAIMS)
def test_doc_count_matches_registry(rel_path, pattern, key, counts):
    with open(pack_path(rel_path), encoding="utf-8") as f:
        text = f.read()

    match = re.search(pattern, text, re.M)
    assert match, (
        f"{rel_path}: no text matched {pattern!r}. Either the sentence was "
        f"reworded (update this test) or the claim was dropped."
    )

    claimed = int(match.group(1))
    assert claimed == counts[key], (
        f"{rel_path} claims {claimed} {key.replace('_', ' ')}, but the registry "
        f"has {counts[key]}. Update the prose in {rel_path}."
    )
