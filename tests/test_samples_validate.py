"""Every YAML and JSON sample in the pack goes through the real validator.

The hand-written half of the pack is prose an agent copies. `test_skill_sync`
checks that the *identifiers* in it are real -- that `attention_checks.frequency`
is a key and `bws` is a type -- which catches an invented name but not a sample
that is well-formed and wrong. A `min_accuracy` that should be `min_threshold`
passes every identifier check and every `--strict` run (validation stops two
levels down) and does nothing at all in a study.

So the samples are extracted and executed here: YAML fragments are spliced into a
minimal working config and validated, and the side-file samples are pushed
through the loaders that read them at boot. The pack's own advice is that a
config which validates has not been checked; the same applies to its examples.
"""

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

import pytest
import yaml

from skillpack import AGENTS_MD, SKILL_DIR, has_potato_repo, potato_repo_path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACK = Path(SKILL_DIR)

#: Generated from the registries; drift is caught by `--check`, not here.
GENERATED = {"annotation-types.md", "config-keys.md", "config-keys-nested.md"}

#: Blocks that are deliberately wrong: the pack shows them as the mistake being
#: described. Matched as whole words, not as substrings.
#:
#: `key_binding` was matched as a bare substring and so also matched
#: `sequential_key_binding`, which is a real key (`bws.py:74` reads it). The
#: only block it hit was the 2964-byte worked-example config -- the pack's
#: largest and most-copied sample -- which was therefore skipped by this guard
#: entirely, and had a key Potato ignores sitting in it.
KNOWN_BAD_ON_PURPOSE = (
    r"\bkey_binding\b",                              # the typo'd form of key_value
    r"with top-level annotation_schemes present",     # shown as the conflict itself
)


#: Sub-keys a sample names that Potato does not read, where the sample is a
#: mirror of a file in the Potato repo and so cannot be fixed here. Keyed by
#: (file, block index) -> the substring of the warning. Asserted to still fire,
#: so a fix upstream makes this stale entry fail rather than rot.
#:
#: worked-example.md block 0 mirrors examples/advanced/full-study-skeleton/
#: config.yaml, whose line 79 is `failure_handling: {action: warn}`.
#: `failure_handling` reads warn_threshold / warn_message / block_threshold /
#: block_message and nothing else (quality_control.py:375), so `action` is
#: dropped and the thresholds fall back to 2 and 5.
MIRRORS_AN_UPSTREAM_BUG = {
    ("worked-example.md", 0): "attention_checks.failure_handling: 'action'",
}


def _shown_as_a_mistake(body: str) -> bool:
    """Is this block one the prose displays as the error being described?

    Whole-word, because a substring test cannot tell `key_binding` from
    `sequential_key_binding` and silently excused the worked example for
    months.
    """
    return any(re.search(pattern, body) for pattern in KNOWN_BAD_ON_PURPOSE)


def _hand_written():
    files = [PACK / "SKILL.md", Path(AGENTS_MD)]
    files += [p for p in sorted((PACK / "references").glob("*.md"))
              if p.name not in GENERATED]
    return files


def _blocks(path: Path, language: str):
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r"```" + language + r"\n(.*?)```", re.S)
    return [(path.name, index, match)
            for index, match in enumerate(pattern.findall(text))]


def _yaml_samples():
    out = []
    for path in _hand_written():
        out.extend(_blocks(path, "yaml"))
    return out


def _json_samples():
    out = []
    for path in _hand_written():
        out.extend(_blocks(path, "json"))
        out.extend(_blocks(path, "jsonl"))
    return out


def _host_config(work_dir: str) -> dict:
    """The smallest config that validates, for a fragment to be spliced into."""
    data_path = os.path.join(work_dir, "items.json")
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump([{"id": "i1", "text": "An item.", "body": "An item.",
                    "title": "A title."}], f)
    return {
        "annotation_task_name": "sample check",
        "task_dir": ".",
        "output_annotation_dir": "annotation_output/",
        "data_files": ["items.json"],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "annotation_schemes": [
            {"annotation_type": "radio", "name": "q",
             "description": "A question?", "labels": ["Yes", "No"]},
        ],
    }



#: Extensions a config names when it points at a side file.
_SIDE_FILE_SUFFIXES = (".json", ".jsonl", ".csv", ".tsv", ".txt", ".html")


def _stub_side_files(work_dir: str, node, _seen=None) -> None:
    """Create a plausible empty file for every relative path a config names.

    A sample naming `data/attention.json` is partial, not wrong -- the pack does
    not ship the side files. But a missing file is a *fatal* validation error,
    and validation stops there, so filtering the error out afterwards (which
    this test did) still leaves everything below it unread. Stubbing the paths
    is what lets the run get to the keys the sample is actually demonstrating.
    """
    if isinstance(node, dict):
        for value in node.values():
            _stub_side_files(work_dir, value)
        return
    if isinstance(node, list):
        for value in node:
            _stub_side_files(work_dir, value)
        return
    if not isinstance(node, str):
        return
    if os.path.isabs(node) or not node.lower().endswith(_SIDE_FILE_SUFFIXES):
        return
    if ".." in node.split("/"):
        return
    target = os.path.join(work_dir, node)
    if os.path.exists(target):
        return
    os.makedirs(os.path.dirname(target) or work_dir, exist_ok=True)
    if node.lower().endswith(".jsonl"):
        body = '{"id": "p1", "text": "A page."}\n'
    elif node.lower().endswith(".json"):
        body = ('[{"id": "s1", "text": "An item.", "body": "An item.", '
                '"title": "A title."}]')
    elif node.lower().endswith((".csv", ".tsv")):
        sep = "," if node.lower().endswith(".csv") else "\t"
        body = sep.join(["id", "text"]) + "\n" + sep.join(["s1", "An item."]) + "\n"
    else:
        body = "sample\n"
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(body)


def _has_elision(value) -> bool:
    """True if the sample uses a bare `...` to stand in for omitted content."""
    if value is Ellipsis:
        return True
    if isinstance(value, dict):
        return any(_has_elision(v) for v in value.values()) or \
               any(_has_elision(k) for k in value)
    if isinstance(value, list):
        return any(_has_elision(v) for v in value)
    return False


def _scheme_fields() -> set:
    from potato.server_utils.schemas.registry import schema_registry
    fields = set()
    for schema in schema_registry.list_schemas():
        fields |= set(schema["required_fields"]) | set(schema["optional_fields"])
    return fields


def _splice(host: dict, sample) -> str:
    """Merge a sample into the host config. Returns why it was skipped, or ''.

    Samples in the pack are written at whatever level the surrounding prose is
    discussing -- a whole config, a scheme, a list of labels, the inside of
    `phases`. Each is put back where it belongs rather than skipped, because a
    fragment is exactly where a wrong key hides.
    """
    from potato.server_utils.config_module import KNOWN_CONFIG_KEYS

    if isinstance(sample, list):
        if all(isinstance(entry, dict) and "annotation_type" in entry
               for entry in sample):
            host["annotation_schemes"] = sample
            return ""
        return "a list that is not annotation schemes"
    if not isinstance(sample, dict):
        return "not a mapping"
    if "annotation_type" in sample:
        host["annotation_schemes"] = [sample]
        return ""

    keys = set(sample)
    if keys and not (keys & set(KNOWN_CONFIG_KEYS)):
        if keys <= _scheme_fields():
            host["annotation_schemes"][0].update(sample)
            return ""
        # A block written as the inside of one config block, e.g. the `order:`
        # and per-phase entries that belong under `phases:`.
        parents = [
            name for name, allowed in KNOWN_CONFIG_KEYS.items()
            if isinstance(allowed, (set, dict)) and keys <= set(allowed)
        ]
        if len(parents) == 1:
            host[parents[0]] = sample
            return ""
        return f"a fragment of an unidentifiable block: {sorted(keys)}"

    host.update(sample)
    return ""


@pytest.mark.parametrize("name,index,body", _yaml_samples(),
                         ids=lambda v: str(v)[:40])
def test_every_yaml_sample_validates(name, index, body):
    if _shown_as_a_mistake(body):
        pytest.skip("shown as the mistake, not as advice")

    try:
        sample = yaml.safe_load(body)
    except yaml.YAMLError as exc:
        pytest.fail(f"{name} block {index} is not valid YAML: {exc}")

    if sample is None:
        pytest.skip("empty block")

    first_line = next((line for line in body.splitlines() if line.strip()), "")
    if first_line.startswith((" ", "\t")):
        pytest.skip("an indented fragment of a larger block")

    work_dir = tempfile.mkdtemp(prefix="pack-sample-")
    try:
        host = _host_config(work_dir)
        skip = _splice(host, sample)
        if skip:
            pytest.skip(skip)

        config_path = os.path.join(work_dir, "config.yaml")
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(host, f, sort_keys=False)

        # Validation stops at the first error, so one missing side file left
        # every key below it unchecked -- which is how
        # `failure_handling: {action: warn}` sat in the worked example, and in
        # this file's own attention-check sample, without either being flagged.
        # Stub every path the sample names so the run reaches the rest.
        _stub_side_files(work_dir, host)

        from potato.validate_cli import validate_config_file

        cwd = os.getcwd()
        os.chdir(work_dir)
        try:
            report = validate_config_file("config.yaml")
        finally:
            os.chdir(cwd)

        assert not report.unknown_keys, (
            f"{name} block {index} uses keys Potato does not recognise: "
            f"{report.unknown_keys}. An unrecognised key is silently ignored, "
            f"so a reader who copies this gets no feature and no warning.")

        # `unknown_keys` only reaches the top level. A key inside a block --
        # `attention_checks.failure_handling.action`, say -- comes back as a
        # warning instead, and this test used to ignore those, so a sample
        # could name a sub-key Potato reads nothing from and still pass.
        # Only the "not recognized" class is asserted on: the other warnings a
        # spliced fragment produces (a `rooms.schema` naming a scheme the
        # surrounding prose defines, a `phases.order` listing phases whose
        # blocks are shown separately) are artefacts of the splice, not of the
        # sample.
        ignored_subkeys = [w for w in report.other_warnings
                           if "not recognized" in w and "will be ignored" in w]
        expected_bad = MIRRORS_AN_UPSTREAM_BUG.get((name, index))
        if expected_bad is not None:
            # The block is a byte-for-byte mirror of a file in Potato, checked
            # by TestTheWorkedExampleIsTheExample. Diverging to fix the key
            # here would break that guard, so the fix belongs upstream and this
            # asserts the bug is STILL THERE -- when Potato fixes it, this
            # fails and the exemption comes out.
            assert any(expected_bad in w for w in ignored_subkeys), (
                f"{name} block {index} no longer produces {expected_bad!r}. "
                f"If Potato fixed it, drop the MIRRORS_AN_UPSTREAM_BUG entry "
                f"and re-sync the block with the file it mirrors.")
            ignored_subkeys = [w for w in ignored_subkeys
                               if expected_bad not in w]

        assert not ignored_subkeys, (
            f"{name} block {index} names a sub-key Potato does not read:\n  "
            + "\n  ".join(ignored_subkeys))

        if _has_elision(sample):
            # `...` stands in for content the prose is not about. The key check
            # above still applies; the value checks below cannot.
            return

        # Side files the sample names are not shipped with the pack, so a
        # missing-file error is the sample being partial, not being wrong.
        real_errors = [e for e in report.errors
                       if "not found" not in e.lower()
                       and "no such file" not in e.lower()]
        assert not real_errors, (
            f"{name} block {index} does not validate:\n  "
            + "\n  ".join(real_errors))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.parametrize("name,index,body", _json_samples(),
                         ids=lambda v: str(v)[:40])
def test_every_json_sample_parses(name, index, body):
    """A side-file sample that does not parse cannot have been run."""
    stripped = body.strip()
    if not stripped:
        pytest.skip("empty block")
    if stripped.startswith("{") and "\n{" in stripped and not stripped.startswith("{\n"):
        for line_number, line in enumerate(stripped.splitlines()):
            if line.strip():
                json.loads(line)         # JSONL: every line stands alone
        return
    try:
        json.loads(stripped)
    except json.JSONDecodeError:
        for line in stripped.splitlines():
            if line.strip():
                json.loads(line)


class TestSideFileSamplesLoad:
    """The three formats documented nowhere else, pushed through their loaders.

    Each of these has a required-field list that the boot log reports badly or
    not at all, which is why the pack documents them. If the documented sample
    stops satisfying the loader, the pack is teaching a format that produces
    `Loaded 0` and a study running with the feature off.
    """

    def _sample_from(self, filename: str, marker: str):
        text = (PACK / "references" / filename).read_text(encoding="utf-8")
        for block in re.findall(r"```json\n(.*?)```", text, re.S):
            if marker in block:
                return json.loads(block)
        pytest.fail(f"no sample containing {marker!r} in {filename}")

    def test_the_training_sample_has_what_the_loader_requires(self):
        sample = self._sample_from("quality-control.md", "correct_answers")
        assert isinstance(sample, dict), "training data must be an object"
        instances = sample.get("training_instances")
        assert instances, "training data needs a training_instances key"
        for instance in instances:
            missing = {"id", "text", "correct_answers"} - set(instance)
            assert not missing, (
                f"the documented training sample is missing {missing}; the "
                f"loader reports this as 'missing required fields' without "
                f"naming the field")

    def test_the_attention_sample_has_what_the_loader_requires(self):
        sample = self._sample_from("quality-control.md", "expected_answer")
        assert isinstance(sample, list), "attention checks are a JSON array"
        for item in sample:
            missing = {"id", "expected_answer"} - set(item)
            assert not missing, (
                f"the documented attention-check sample is missing {missing}; "
                f"the server logs one warning and loads zero items")

    def test_the_gold_sample_has_what_the_loader_requires(self):
        sample = self._sample_from("quality-control.md", "gold_label")
        assert isinstance(sample, list)
        for item in sample:
            assert "gold_label" in item


class TestTheWorkedExampleIsTheExample:
    """`worked-example.md` must be the example project, character for character.

    The page used to describe a project that existed only in the session that
    wrote it. It drew a tree of three page files and supplied one, and claimed
    "it validates under --strict and boots clean" -- true of the original, false
    of anything a reader could reconstruct from the page. Copying it produced a
    study that booted with two phases silently dropped, which is precisely the
    failure the rest of the pack teaches you to look for.

    Now the files live in Potato's own `examples/advanced/full-study-skeleton/`,
    where the example CI validates them, and this test holds the page to them.
    That directory is not in the wheel, so this needs a Potato checkout.
    """

    EXAMPLE = Path(potato_repo_path("examples", "advanced", "full-study-skeleton"))

    @pytest.fixture(autouse=True)
    def _needs_potato_checkout(self):
        if not has_potato_repo():
            pytest.skip("no Potato checkout; set POTATO_REPO")

    def _doc_blocks(self):
        text = (PACK / "references" / "worked-example.md").read_text(encoding="utf-8")
        blocks = {}
        for heading, body in re.findall(
                r"^## (\S+\.\S+)\n(.*?)(?=^## |\Z)", text, re.S | re.M):
            match = re.search(r"```[a-z]*\n(.*?)```", body, re.S)
            if match:
                blocks[heading] = match.group(1)
        return blocks

    def test_every_file_in_the_tree_is_shown(self):
        shown = set(self._doc_blocks())
        on_disk = {
            str(path.relative_to(self.EXAMPLE))
            for path in self.EXAMPLE.rglob("*")
            if path.is_file()
        }
        assert on_disk <= shown, (
            f"the example has files the page does not show: {sorted(on_disk - shown)}. "
            f"A reader copying the page gets a project that is missing them, and "
            f"a missing phase file is dropped at boot with one ERROR line.")

    @pytest.mark.parametrize("relative", [
        "config.yaml", "data/items.json", "data/training.json",
        "data/attention.json", "pages/consent.jsonl", "pages/instructions.jsonl",
        "pages/poststudy.jsonl", "static/study.css",
    ])
    def test_the_block_matches_the_file(self, relative):
        blocks = self._doc_blocks()
        assert relative in blocks, f"worked-example.md does not show {relative}"
        on_disk = (self.EXAMPLE / relative).read_text(encoding="utf-8")
        assert blocks[relative].strip() == on_disk.strip(), (
            f"the {relative} block in worked-example.md has drifted from "
            f"examples/advanced/full-study-skeleton/{relative}. The file is the "
            f"one that gets validated in CI; make the page match it.")
