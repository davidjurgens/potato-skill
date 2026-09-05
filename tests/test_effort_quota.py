"""The effort script's quota arithmetic, pinned to Potato's own resolver.

`estimate_effort.py` divides the judgements by one annotator's cap to say how
many annotators a study needs. That number decides how many people someone
recruits, so a stale reading of the cap is expensive rather than cosmetic: the
script read only `max_annotations_per_user` for a long time, and reported "1
annotator at a quota of 24" for a study whose every annotator was capped at 5.

Potato resolves the cap in `UserStateManager._resolve_user_quota`, which takes
the first of `per_annotator_quota.by_user`, `.by_user_role` (via `user_roles`),
`.default`, then `max_annotations_per_user`. The script reimplements that order
because it has no server to ask. Two implementations of one rule is exactly the
shape that drifts, so these tests run both and compare, rather than asserting
the numbers the script happens to produce today. If Potato reorders the chain or
adds a level, this fails on the next run instead of quietly costing someone four
annotators.

`_resolve_user_quota` is private, and that is the point: it is the function that
actually runs, so pinning to the public wrapper would test a different thing.
"""

import importlib.util
import logging

import pytest

from skillpack import script_path

_spec = importlib.util.spec_from_file_location(
    "estimate_effort", script_path("estimate_effort.py"))
estimate_effort = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(estimate_effort)

pytest.importorskip("potato", reason="needs a Potato checkout on the path")


# An annotator the config names nowhere: no `by_user` entry and no role. This is
# the annotator the script's headline count is about, since a crowd study's
# workers are not enumerated in the config.
UNNAMED = "someone-not-in-the-config"

N_ITEMS = 24

# Each case is the quota half of a config. The comment names the branch of
# _resolve_user_quota it is meant to reach; between them they cover all four,
# which is the point -- with one branch exercised, any ordering passes.
CASES = {
    "nothing set": {},
    # branch 4: the legacy global, no per_annotator_quota at all
    "global only": {"max_annotations_per_user": 20},
    # branch 3: default present, and it must displace the global
    "default displaces the global": {
        "max_annotations_per_user": 20,
        "per_annotator_quota": {"default": 5},
    },
    "default alone": {"per_annotator_quota": {"default": 5}},
    # branches 1 and 2 exist for named annotators; the unnamed one still lands
    # on default, and the script must not let an override leak into the headline
    "overrides present, unnamed annotator": {
        "max_annotations_per_user": 20,
        "per_annotator_quota": {
            "default": 5,
            "by_user": {"alice": 3},
            "by_user_role": {"expert": 7},
        },
        "user_roles": {"alice": "expert", "bob": "expert", "carol": "novice"},
    },
    "overrides but no default": {
        "max_annotations_per_user": 20,
        "per_annotator_quota": {
            "by_user": {"alice": 3},
            "by_user_role": {"expert": 7},
        },
        "user_roles": {"alice": "expert"},
    },
    "zero is a real quota, not an absent one": {
        "per_annotator_quota": {"default": 0},
        "max_annotations_per_user": 20,
    },
}


def _potato_says(config, user_id=UNNAMED):
    """What the running server would give this annotator."""
    from potato.user_state_management import UserStateManager

    logging.disable(logging.CRITICAL)
    try:
        manager = UserStateManager(dict(config))
        # The server sets the legacy global at boot rather than in the
        # constructor, so a test that skipped this would never reach branch 4.
        manager.set_max_annotations_per_user(
            config.get("max_annotations_per_user", -1))
        return manager._resolve_user_quota(user_id)
    finally:
        logging.disable(logging.NOTSET)


@pytest.fixture
def corpus(tmp_path):
    """A real data file, because estimate() counts items by reading one."""
    import json

    path = tmp_path / "data.json"
    with path.open("w") as handle:
        for i in range(1, N_ITEMS + 1):
            handle.write(json.dumps(
                {"id": str(i), "text": f"Item number {i} for quota testing."}) + "\n")
    return tmp_path


def _run(config, corpus_dir):
    config = dict(config)
    config.setdefault("data_files", ["data.json"])
    return estimate_effort.estimate(
        config, str(corpus_dir), wpm=240, rate=0.0)


class TestAgreesWithPotato:
    @pytest.mark.parametrize("name", sorted(CASES))
    def test_unnamed_annotator_cap_matches(self, name, corpus):
        config = CASES[name]
        n_items = N_ITEMS
        potato = _potato_says(config)
        script = _run(config, corpus)["quota_per_annotator"]

        # -1 is Potato's "unlimited"; the script reports the item count, which
        # is the same study and the more useful number to divide by.
        if potato < 0:
            assert script == n_items, (
                f"{name}: Potato leaves the cap unlimited, so the script should "
                f"fall back to the {n_items} items loaded, got {script}")
        else:
            assert script == potato, (
                f"{name}: Potato serves this annotator {potato} items, the "
                f"script estimates from {script}")

    def test_named_overrides_reach_their_own_branches(self):
        """The fixture is only honest if the overrides actually bite."""
        config = CASES["overrides present, unnamed annotator"]
        assert _potato_says(config, "alice") == 3, "by_user branch unreachable"
        assert _potato_says(config, "bob") == 7, "by_user_role branch unreachable"
        assert _potato_says(config, "carol") == 5, "role without an entry"
        assert _potato_says(config, UNNAMED) == 5, "default branch unreachable"


class TestAnnotatorCount:
    def test_a_quota_below_the_corpus_needs_more_annotators(self, corpus):
        config = {"per_annotator_quota": {"default": 5}}
        result = _run(config, corpus)
        assert result["annotators_needed"] == 5, (
            "24 judgements at 5 items each is 5 annotators; this is the number "
            "someone recruits from")

    def test_the_dead_global_does_not_inflate_the_quota(self, corpus):
        """The regression that prompted this file."""
        with_global = {"max_annotations_per_user": 20,
                       "per_annotator_quota": {"default": 5}}
        without = {"per_annotator_quota": {"default": 5}}
        assert _run(with_global, corpus) == _run(without, corpus), (
            "max_annotations_per_user is never read once default is set, so it "
            "must not change the estimate either")

    def test_named_quotas_are_reported_not_averaged(self, corpus):
        config = CASES["overrides present, unnamed annotator"]
        result = _run(config, corpus)
        assert result["quota_per_annotator"] == 5
        assert result["named_quotas"] == {
            "by_user.alice": 3, "by_user_role.expert": 7}
