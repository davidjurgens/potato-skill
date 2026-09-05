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
    from potato.export.registry import export_registry
    from potato.server_utils.examples_manifest import load_manifest
    from potato.server_utils.schemas.registry import schema_registry

    # The shapes `keyword_highlights_file` accepts, counted by running one
    # representative of each past Potato's own parser and collapsing the
    # header-naming variants ("delimited with a header (keyword, label)") into
    # one family. The claim in `building-the-ui.md` is a number an author uses
    # to decide whether their file will be read at all, and nothing else pins
    # it: the parser is a function, not a registry, so it cannot drift into a
    # count the way the schema registry does -- it drifts silently instead.
    from potato.flask_server import _parse_keyword_highlight_entries

    _kw_fixtures = [
        ("keyword,label,color\nlatch,Defect,#ffcc00\n", "h.csv"),
        ("thing,description\nlatch,Defect\n", "h.csv"),
        ("latch\nridge\n", "h.txt"),
        ('[{"keyword":"latch"}]', "h.json"),
        ('{"keyword":"latch"}\n{"keyword":"ridge"}\n', "h.jsonl"),
        ("- latch\n- ridge\n", "h.yaml"),
    ]
    _kw_shapes = set()
    for _raw, _path in _kw_fixtures:
        _entries, _shape = _parse_keyword_highlight_entries(_raw, _path)
        if _entries:
            _kw_shapes.add(str(_shape).split(" (", 1)[0])

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

    # How many bundled examples declare a `phases` block at all. The interview
    # tells an agent not to push consent/training/prestudy on anyone, and this
    # is the evidence for that advice; if phases become common, the advice
    # should change rather than quietly go stale.
    manifest = load_manifest()
    with_phases = sum(1 for e in manifest["examples"]
                      if "phases" in (e.get("config_keys") or []))

    return {
        "export_formats": len(export_registry.get_supported_formats()),
        "examples_with_phases": with_phases,
        "annotation_types": len(schema_registry.get_supported_types()),
        "display_types": len(display_registry.get_supported_types()),
        "documented_top_keys": len(top_docs),
        "documented_sub_keys": len(sub_docs),
        "unchecked_blocks": len(unchecked),
        "examples": load_manifest()["count"],
        "keyword_shapes": len(_kw_shapes),
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

    ("references/interviewing.md",
     r"(\d+) of the example projects Potato ships use one", "examples_with_phases"),

    # The export-format count went from 29 to 30 unnoticed because nothing
    # pinned it. `getting-the-data-out.md` routes a researcher's request to a
    # format name, so a format that appears without the routing table learning
    # about it is a gap an author cannot see.
    ("references/getting-the-data-out.md",
     r"(\d+) formats are registered", "export_formats"),

    # An author whose file is not one of these shapes gets "Loaded 0 patterns",
    # which reads as an empty file rather than an unrecognised one. The number
    # is how they decide whether to keep debugging their file or their config.
    ("references/building-the-ui.md",
     r"`keyword_highlights_file` reads (\d+) shapes", "keyword_shapes"),

    # The argument for adding no phases by default is this ratio, so both
    # halves of it have to stay true.
    ("references/phases-and-pages.md",
     r"\*\*(\d+) of Potato's \d+ bundled examples declare", "examples_with_phases"),
    ("references/phases-and-pages.md",
     r"\*\*\d+ of Potato's (\d+) bundled examples declare", "examples"),
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


def test_display_registry_reports_every_renderer_option():
    """The registry table must not drift from the renderer classes again.

    Until 2.8.2-11 `DisplayDefinition` repeated each renderer's
    `optional_fields` by hand, and 14 of the 24 entries listed fewer options
    than their renderer accepted -- 44 between them, including the `speaker_key`
    that decides whether `multi_agent_discussion` can read your data at all.
    Only the renderer's copy is merged at render time, so the table was the
    half an author reads and the half that was wrong.

    `building-the-ui.md` now tells authors to look options up in
    `list_displays()`. If this fails, that advice is wrong again.
    """
    from potato.server_utils.displays.registry import display_registry

    drifted = {}
    for entry in display_registry.list_displays():
        registered = display_registry.get(entry["name"])
        renderer = getattr(registered, "renderer", registered)
        declared = set(getattr(type(renderer), "optional_fields", {}) or {})
        missing = declared - set(entry["optional_fields"])
        if missing:
            drifted[entry["name"]] = sorted(missing)

    assert not drifted, (
        "The display registry is under-reporting renderer options again: "
        f"{drifted}. An author reading list_displays() will not find these, so "
        "restore the warning in references/building-the-ui.md."
    )
