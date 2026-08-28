"""The study-status script's interpretation layer, tested without a server.

`summarize()` is where the script decides what counts as a problem, and the
judgement it is most likely to get wrong is the mid-study scheme rename: every
configured scheme reporting zero items while annotations exist. That shape is
also what a perfectly healthy single-annotator study looks like, so the test
pins both directions.
"""

import importlib.util
import os

import pytest

from skillpack import script_path

_spec = importlib.util.spec_from_file_location(
    "study_status", script_path("study_status.py"))
study_status = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(study_status)


def _payload(*, annotations=3, schemas=None, annotators=None, **extra):
    data = {
        "url": "http://localhost:8000",
        "errors": {},
        "overview": {"overview": {
            "total_items": 3, "items_with_annotations": 3,
            "total_annotations": annotations, "total_users": 1,
            "completed_users": 1, "completion_percentage": 100.0}},
        "annotators": {"annotators": annotators or []},
        "agreement": {"schemas": schemas if schemas is not None else {}},
    }
    data.update(extra)
    return data


class TestProgress:
    def test_reads_the_overview_block(self):
        summary = study_status.summarize(_payload())
        assert summary["items"] == 3
        assert summary["annotations"] == 3
        assert summary["percent_complete"] == 100.0

    def test_missing_overview_is_not_a_crash(self):
        """An unreachable route records an error; it must not take the rest out."""
        summary = study_status.summarize(
            {"errors": {"overview": "HTTP 403"}, "agreement": {}})
        assert summary["items"] is None
        assert any("overview" in p for p in summary["problems"])


class TestAgreementShapes:
    IAA = {"polarity": {"kind": "nominal", "annotation_type": "radio",
                        "metrics": {"n_items": 0, "alpha_nominal": None}}}
    LEGACY = {"by_schema": {"polarity": {"items_count": 0,
                                         "error": "No items with 2+ annotators"}}}

    def test_reads_the_nested_iaa_shape(self):
        summary = study_status.summarize(_payload(schemas=self.IAA))
        assert summary["agreement"]["polarity"]["items"] == 0
        assert summary["agreement"]["polarity"]["kind"] == "nominal"

    def test_reads_the_flat_agreement_shape(self):
        """/admin/api/agreement nests differently; both routes must work."""
        data = _payload()
        data["agreement"] = self.LEGACY
        summary = study_status.summarize(data)
        assert summary["agreement"]["polarity"]["error"]

    def test_every_scheme_silent_with_annotations_is_flagged(self):
        summary = study_status.summarize(_payload(schemas=self.IAA))
        assert any("reports 0 items" in p for p in summary["problems"])

    def test_not_flagged_when_no_annotations_exist_yet(self):
        summary = study_status.summarize(_payload(annotations=0, schemas=self.IAA))
        assert summary["problems"] == []

    def test_not_flagged_when_one_scheme_has_data(self):
        schemas = dict(self.IAA)
        schemas["confidence"] = {"kind": "ordinal",
                                 "metrics": {"n_items": 12, "alpha_ordinal": 0.7}}
        summary = study_status.summarize(_payload(schemas=schemas))
        assert not any("reports 0 items" in p for p in summary["problems"])

    def test_counts_are_not_reported_as_metrics(self):
        """n_items and n_annotators are the denominators, not the agreement."""
        schemas = {"c": {"kind": "ordinal",
                         "metrics": {"n_items": 12, "n_annotators": 3,
                                     "alpha_ordinal": 0.71}}}
        summary = study_status.summarize(_payload(schemas=schemas))
        assert summary["agreement"]["c"]["metrics"] == {"alpha_ordinal": 0.71}


class TestAnnotators:
    ROW = {"user_id": "alice", "total_annotations": 7, "max_assignments": 20,
           "remaining_assignments": 13, "average_seconds_per_annotation": 31.5,
           "phase": "annotation", "last_activity": "2026-08-22T20:00:00",
           "suspicious_level": "none"}

    def test_uses_the_field_names_the_route_actually_returns(self):
        summary = study_status.summarize(_payload(annotators=[self.ROW]))
        row = summary["annotators_detail"][0]
        assert row["user"] == "alice"
        assert row["annotated"] == 7
        assert row["assigned"] == 20

    @pytest.mark.parametrize("level", ["high", "medium"])
    def test_flags_the_dashboard_s_own_suspicion_verdict(self, level):
        row = dict(self.ROW, suspicious_level=level, suspicious_score=0.9)
        summary = study_status.summarize(_payload(annotators=[row]))
        assert any("flagged " + level in p for p in summary["problems"])

    def test_an_ordinary_annotator_is_not_flagged(self):
        summary = study_status.summarize(_payload(annotators=[self.ROW]))
        assert summary["problems"] == []


class TestOtherProblems:
    def test_stale_assignments(self):
        data = _payload(stale={"stale_assignments": [{"instance_id": "i1"}]})
        assert any("reclaim timeout" in p
                   for p in study_status.summarize(data)["problems"])

    def test_quality_control_off_is_reported_but_is_not_a_problem(self):
        data = _payload(quality_control={"enabled": False})
        summary = study_status.summarize(data)
        assert summary["quality_control"] == "not configured"
        assert summary["problems"] == []


class TestRender:
    def test_renders_without_a_server(self):
        text = study_status.render(study_status.summarize(_payload()))
        assert "items have annotations" in text

    def test_says_so_when_there_is_nothing_wrong(self):
        text = study_status.render(study_status.summarize(_payload(annotations=0)))
        assert "Nothing to report." in text
