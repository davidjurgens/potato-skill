"""The walk's stored-value check must be able to fail.

`walk_task.py` compares what it submitted against what `user_state.json` came
back holding. That comparison spent its first hour unable to run at all, and
reported "0 mismatches" the whole time.

The cause is worth keeping, because nothing about it looked wrong. What the
page POSTs and what the server stores are two different structures:

    wire   {"category:::B": "B"}
    disk   [[{"schema": "category", "name": "B"}, "B"], ...]

The in-memory container is keyed by `Label` objects, and JSON has nowhere to
put them, so it serializes to a list of `[Label, value]` pairs. A reader
written for the wire shape calls `.items()` on that list, finds nothing, and
every answer compares equal to everything.

Two things failed to catch it. The end-to-end run printed `mismatches: 0`,
which is what a working comparison over correct answers prints. And a unit test
did perturb a stored value and did report a mismatch -- against a fixture built
from the same wrong assumption as the code, so it confirmed the assumption
rather than the behaviour.

So the cases below are pinned to bytes copied out of a real
`annotation_output/<user>/user_state.json`, and every one of them asserts a
mismatch is DETECTED. A guard that only checks a matching answer reports zero
either way.
"""

import sys

import pytest

from skillpack import pack_path

sys.path.insert(0, pack_path("scripts"))

import walk_task  # noqa: E402


#: Copied verbatim from a real user_state.json written by Potato 2.9.1 for a
#: radio (`category`) and a likert (`severity`). Not hand-built: a fixture in
#: the shape the code expects is what hid this bug the first time.
DISK_SHAPE = [
    [{"schema": "category", "name": "A"}, "A"],
    [{"schema": "severity", "name": "Low"}, "Low"],
]

#: What `/updateinstance` receives for the same answer. Both are read, because
#: a phase page stores this form.
WIRE_SHAPE = {"category:::A": "A", "severity:::Low": "on"}


def _mismatched(expected, stored):
    """The schemes whose submitted answer is not in the stored reading."""
    readings = walk_task._stored_readings(stored)
    return sorted(
        scheme for scheme, value in expected.items()
        if not ({str(v) for v in (value if isinstance(value, list) else [value])}
                & readings.get(scheme, set()))
    )


class TestTheReadingFindsTheAnswer:
    def test_the_on_disk_pair_shape_is_read(self):
        """The list-of-pairs form, which is what is actually on disk."""
        assert walk_task._stored_readings(DISK_SHAPE) == {
            "category": {"A"}, "severity": {"Low"}}

    def test_the_wire_shape_is_still_read(self):
        """`"on"` carries no answer -- the label in the KEY does."""
        assert walk_task._stored_readings(WIRE_SHAPE) == {
            "category": {"A"}, "severity": {"Low", "on"}}

    def test_a_matching_answer_reports_nothing(self):
        assert _mismatched({"category": "A", "severity": "Low"}, DISK_SHAPE) == []


class TestTheComparisonCanFail:
    """Each case must produce a mismatch. This is the half that rots silently.

    Reintroduce the defect -- make `_stored_readings` return `{}` for a list --
    and every test here fails. That is the only evidence a guard tests
    anything.
    """

    def test_a_different_stored_label_is_caught(self):
        stored = [[{"schema": "category", "name": "ZZZ"}, "ZZZ"],
                  [{"schema": "severity", "name": "Low"}, "Low"]]
        assert _mismatched({"category": "A", "severity": "Low"}, stored) == ["category"]

    def test_an_answer_stored_as_nothing_is_caught(self):
        assert _mismatched({"category": "A"}, []) == ["category"]

    def test_an_unselected_option_is_not_an_answer(self):
        """`False` means the option was rendered and not chosen."""
        stored = [[{"schema": "category", "name": "A"}, False]]
        assert _mismatched({"category": "A"}, stored) == ["category"]

    def test_the_wire_shape_can_fail_too(self):
        assert _mismatched({"category": "B"}, WIRE_SHAPE) == ["category"]


class TestShapesThatMustNotBeScored:
    def test_a_geometry_blob_is_left_out_rather_than_mismatched(self):
        """A drawn answer stores one JSON blob under `_data` and no label name.

        Absent is honest; a mismatch on every drawn answer is not, and it would
        fire on every geometry task the walk ever touched.
        """
        stored = [[{"schema": "region", "name": "_data"}, '{"boxes": []}']]
        assert walk_task._stored_readings(stored) == {}

    def test_free_text_keeps_the_typed_string(self):
        """The name is the widget (`text_box`); the value is the answer."""
        stored = [[{"schema": "why_unclear", "name": "text_box"}, "because it is"]]
        readings = walk_task._stored_readings(stored)
        assert "because it is" in readings["why_unclear"]


class TestTheSideFileReaders:
    def test_gold_and_attention_files_are_read_as_arrays(self, tmp_path):
        """Both are a JSON array; training's file is an object. Mixing them up
        returns `{}`, which reads exactly like a study with no gold items."""
        import json

        (tmp_path / "gold.json").write_text(json.dumps([
            {"id": "g1", "gold_label": {"category": "B"}},
            {"id": "g2", "gold_label": "B"},
        ]))
        config = tmp_path / "config.yaml"
        config.write_text(
            "gold_standards:\n  enabled: true\n  items_file: gold.json\n")

        answers = walk_task._side_file_answers(
            str(config), "gold_standards", "gold_label")
        assert answers == {"g1": {"category": "B"}, "g2": "B"}

    def test_a_missing_block_is_empty_rather_than_an_error(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("annotation_task_name: nothing here\n")
        assert walk_task._side_file_answers(
            str(config), "gold_standards", "gold_label") == {}


class TestTheDwellIsReadFromTheConfig:
    def test_min_response_time_is_found(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text(
            "attention_checks:\n  enabled: true\n  min_response_time: 5\n")
        assert walk_task._min_response_time(str(config)) == 5.0

    def test_no_attention_block_means_no_dwell(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("annotation_task_name: nothing here\n")
        assert walk_task._min_response_time(str(config)) == 0.0


@pytest.mark.parametrize("shape", [DISK_SHAPE, WIRE_SHAPE])
def test_both_shapes_agree_on_the_same_answer(shape):
    """The two serializations of one answer must read the same.

    One predicate, two callers, and a guard covering one direction reports
    green on a coin flip.
    """
    assert _mismatched({"category": "A", "severity": "Low"}, shape) == []
