"""The price helper, and whether Potato's compiled table still holds.

`model_prices.py` exists because `potato/ai/cost.py` prices a run by longest
substring: a model the table does not list is priced from whatever family row
its name happens to contain, and `ai_budget.cap_usd` then refuses or permits
work on that number. The helper asks a live catalogue at the moment it runs.

Two different things are tested here, and they fail for different reasons.

The offline tests pin the helper's own judgement against a fixture catalogue.
They are the ones that must never depend on the network, because they are what
stops the helper reproducing the bug it reports: an id resolved by anything
looser than an exact match, a `:free` variant answering for the model it is
named after, or "there was no feed" reported as "the feed does not list this".

The live test is the drift guard, and it is why this repository already runs a
weekly cron. It fetches the catalogue and checks the rows Potato ships against
it. A price that moves makes this repository wrong without anything being
pushed here. It skips rather than fails when the fetch does not come back: an
outage is not evidence about a price, and a guard that reddens on someone
else's downtime gets switched off.
"""

import importlib.util

import pytest

from skillpack import script_path

_spec = importlib.util.spec_from_file_location(
    "model_prices", script_path("model_prices.py"))
model_prices = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(model_prices)


def _row(identifier, prompt, completion, **extra):
    pricing = {"prompt": str(prompt), "completion": str(completion)}
    pricing.update(extra)
    return {"id": identifier, "pricing": pricing}


# Small on purpose, and every row earns its place by being a shape that has
# actually caused a wrong price somewhere.
CATALOGUE = {"data": [
    _row("openai/gpt-4o", 0.0000025, 0.00001),
    _row("openai/gpt-4.1", 0.000002, 0.000008),
    _row("openai/gpt-4.1-nano", 0.0000001, 0.0000004),
    # A free variant of a paid model. Priced at zero, and must never answer.
    _row("openai/gpt-4.1-nano:free", 0, 0),
    # The catalogue spells a minor version with a dot; Anthropic's API spells
    # it with a hyphen and adds a dated suffix.
    _row("anthropic/claude-haiku-4.5", 0.000001, 0.000005),
    # Tiered: one flat pair is an approximation for this model, and the report
    # has to say so rather than quoting the base tier as the price.
    _row("google/gemini-2.5-pro", 0.00000125, 0.00001,
         overrides=[{"min_prompt_tokens": 200000, "prompt": "0.0000025"}]),
]}


@pytest.fixture
def index():
    return model_prices._index(CATALOGUE)


class TestResolvingAName:
    def test_an_exact_id_resolves(self, index):
        row, matched = model_prices.live_price("gpt-4o", index)
        assert matched == "openai/gpt-4o"

    def test_a_vendor_qualified_name_resolves(self, index):
        _, matched = model_prices.live_price("openai/gpt-4o", index)
        assert matched == "openai/gpt-4o"

    def test_a_dated_snapshot_resolves_to_its_model(self, index):
        """`claude-haiku-4-5-20251001` is claude-haiku-4.5, spelled twice."""
        _, matched = model_prices.live_price("claude-haiku-4-5-20251001", index)
        assert matched == "anthropic/claude-haiku-4.5"

    def test_a_variant_is_not_priced_as_its_parent(self, index):
        """The bug being reported, committed by the reporter.

        `gpt-4.1-nano` contains `gpt-4.1`, which is how Potato prices it at 20
        times its real rate. Nothing here may resolve by containment.
        """
        _, matched = model_prices.live_price("gpt-4.1-nano", index)
        assert matched == "openai/gpt-4.1-nano"

    def test_an_unknown_name_resolves_to_nothing(self, index):
        row, matched = model_prices.live_price("gpt-4.1-turbo-preview", index)
        assert row is None and matched is None, (
            "a name the catalogue does not hold must return nothing, not the "
            "nearest thing: a suggestion that becomes a price is the whole bug")

    def test_free_variants_never_enter_the_index(self, index):
        assert not any(":" in key for key in index), (
            "22 rows in the real catalogue are priced at zero; one of them "
            "answering for a paid model reports a run as costing nothing")
        # approx, because the feed quotes a per-token price as a string and
        # 1e-07 * 1e6 is not exactly 0.1 in binary floating point.
        assert model_prices._per_million(
            index["openai/gpt-4.1-nano"])["input"] == pytest.approx(0.1)


class TestTheReport:
    def test_a_tiered_price_says_so(self, index):
        assert model_prices._per_million(index["google/gemini-2.5-pro"])["tiered"]

    def test_no_feed_is_not_the_same_as_not_listed(self):
        """The measurement error this helper must not make.

        With no catalogue at all, every model is absent from it. Saying so as
        "not in the live catalogue" is a claim about the model, drawn from a
        lookup that never ran.
        """
        without = model_prices.review("gpt-4o", "", {}, have_catalogue=False)
        assert without["live_checked"] is False
        assert "no live prices" in without["verdict"]

        # The case that makes the flag more than a restatement of `not index`:
        # the feed answered and listed nothing usable. A lookup ran, so this
        # model really is unlisted, and the report must not blame the network.
        answered_empty = model_prices.review("gpt-4o", "", {},
                                             have_catalogue=True)
        assert answered_empty["live_checked"] is True
        assert "no live prices" not in answered_empty["verdict"]

        listed = model_prices.review(
            "gpt-4.1-turbo-preview", "", model_prices._index(CATALOGUE))
        assert listed["live_checked"] is True
        assert "no live prices" not in listed["verdict"]

    def test_a_gap_is_never_rounded_to_no_gap(self):
        """`{ratio:.0f}x` prints "1x" for a 25% difference."""
        assert model_prices._gap(20) == "20x the live rate"
        assert "25%" in model_prices._gap(1.25)
        assert "20%" in model_prices._gap(0.8)
        assert "1x" not in model_prices._gap(1.25)


class TestReadingAConfig:
    def test_it_finds_a_model_under_any_subsystem(self, tmp_path):
        config = {
            "ai_support": {"endpoint_type": "openai",
                           "ai_config": {"model": "gpt-4.1-nano"}},
            "llm_active_learning": {"endpoint_type": "anthropic",
                                    "ai_config": {"model": "claude-opus-5"}},
        }
        found = model_prices.models_in_config(config, str(tmp_path))
        assert {(f["model"], f["endpoint_type"]) for f in found} == {
            ("gpt-4.1-nano", "openai"), ("claude-opus-5", "anthropic")}

    def test_it_follows_ai_config_file(self, tmp_path):
        """The split the pack recommends puts the model in the second file."""
        sidecar = tmp_path / "keys.yaml"
        sidecar.write_text("endpoint_type: openai_vision\nmodel: gpt-5\n")
        found = model_prices.models_in_config(
            {"ai_support": {"ai_config_file": "keys.yaml"}}, str(tmp_path))
        assert [(f["model"], f["endpoint_type"]) for f in found] == [
            ("gpt-5", "openai_vision")]

    def test_a_missing_sidecar_is_reported_not_ignored(self, tmp_path):
        found = model_prices.models_in_config(
            {"ai_support": {"ai_config_file": "gone.yaml"}}, str(tmp_path))
        assert found and found[0].get("missing"), (
            "a model named only in a file that is not there must be visible "
            "as unchecked, not read as 'no model configured'")


potato_cost = pytest.importorskip(
    "potato.ai.cost", reason="needs Potato installed")


def _drift(table, index):
    """`(rows checked, rows that disagree)` for a price table against a feed.

    Extracted so the control below can run the same comparison over a table
    that is deliberately wrong. A control that asserts `x != 2x` instead tests
    arithmetic, and passes just as happily when the comparison is broken.
    """
    checked, wrong = [], []
    for prefix, (want_in, want_out) in table.items():
        row, _ = model_prices.live_price(prefix, index)
        if row is None:
            # A family alias like `claude-opus`, or a retired model. Those are
            # the rows that cause the mispricing, and no live source can
            # confirm them -- they are not model names anywhere.
            continue
        rates = model_prices._per_million(row)
        checked.append(prefix)
        if (abs(rates["input"] - want_in) > 1e-9
                or abs(rates["output"] - want_out) > 1e-9):
            wrong.append(f"{prefix}: table ({want_in}, {want_out}) against "
                         f"live ({rates['input']}, {rates['output']})")
    return checked, wrong


class TestPotatoStillAgreesWithTheWorld:
    """The drift guard. A price moves and this repository is wrong."""

    @pytest.fixture(scope="class")
    def live(self):
        try:
            return model_prices.fetch_catalogue(timeout=30)
        except Exception as exc:
            pytest.skip(f"no live catalogue ({exc}); an outage is not evidence")

    def test_every_confirmable_row_still_matches(self, live):
        index = model_prices._index(live)
        checked, wrong = _drift(potato_cost.PRICE_TABLE, index)
        assert len(checked) >= 5, (
            f"only {len(checked)} of Potato's rows resolved to a real model "
            f"id; if that number falls the guard has stopped checking anything")
        assert not wrong, (
            "Potato's compiled price table has drifted from the live "
            "catalogue:\n  " + "\n  ".join(wrong)
            + f"\n(as_of {potato_cost.PRICES_AS_OF})")

    def test_the_comparison_would_notice(self, live):
        """The control. A guard nobody has seen fail proves nothing.

        The same comparison over the same feed, with every price doubled. If
        this reports no drift, the test above is asserting nothing.
        """
        index = model_prices._index(live)
        doubled = {k: (v[0] * 2, v[1] * 2)
                   for k, v in potato_cost.PRICE_TABLE.items()}
        checked, wrong = _drift(doubled, index)
        assert checked, "nothing resolved, so the control proves nothing either"
        assert len(wrong) == len(checked), (
            "a table with every price doubled must disagree on every row it "
            "can check; the comparison is not comparing")

    def test_a_model_priced_from_another_row_is_visible(self, live):
        """`price_matched_exactly` is how a caller finds out, so it has to."""
        exact = getattr(potato_cost, "price_matched_exactly", None)
        if exact is None:
            pytest.skip("this Potato predates the check")
        assert exact("gpt-4o") is True
        assert exact("gpt-4.1-nano") is False, (
            "gpt-4.1-nano is priced from the gpt-4.1 row and nothing says so")
