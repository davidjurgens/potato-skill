"""A configured field key must reach the page, not just the config.

Every other guard here checks the pack as text. `test_skill_sync.py` checks that
an identifier exists in one of Potato's registries; `test_samples_validate.py`
checks that a config block validates. Neither can tell a key the widget
*consults* from a key it merely *declares* -- a generator can list a key in
`optional_fields` and never read it, and a validator will happily accept it.

That gap is not hypothetical. The "where the widget looks for its data" table in
`modalities.md` claimed four dynamic schemes took no field key and read the
item's `text_key`. All four read their own declared key, and the table
contradicted itself one row up. It validated, every identifier in it existed,
and it was wrong.

So this boots a study whose item carries a different sentinel string under every
documented field key, loads the annotation page in a real browser, and asserts
each sentinel is visible text. A key the widget ignores leaves its sentinel off
the page, which is the failure an author sees as an empty widget with nothing in
the log.

Marked `slow`: it starts a real server and a headless Chromium. Skipped, not
failed, when either is unavailable -- a missing browser is a missing tool, not a
broken pack.

Every result names the Potato commit it ran against, and says so loudly when the
checkout is dirty. That is not bookkeeping. This guard boots the tree it finds,
and that tree is often one somebody is editing right now: a run against
uncommitted work tells you about the working copy and nothing about HEAD. Round
25 is the cautionary tale -- a passing run here was read as disproving a filed
bug, when it was measuring a fix that had landed in the working tree an hour
earlier.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from skillpack import has_potato_repo, potato_repo_path

#: Identity comes from the query string, so the browser never sees a login page.
USER = "guardbot"

#: One case per claim: the annotation type, the config key that names the field,
#: the item field it points at, and the sentinel that must end up on the page.
#: `scheme` is spliced into `annotation_schemes` and `item` into the data file.
#:
#: Keep the sentinels distinct. A shared one cannot tell "this widget rendered
#: it" from "the widget next door did".
CASES = [
    {
        "id": "extractive_qa-question_field",
        "sentinel": "SENTINEL_QUESTION",
        "claim": "modalities.md: extractive_qa reads question_field",
        "scheme": {
            "annotation_type": "extractive_qa",
            "name": "guard_qa",
            "description": "extractive_qa",
            "question_field": "guard_question",
            "passage_field": "guard_passage",
        },
        "item": {"guard_question": "SENTINEL_QUESTION which one failed?"},
    },
    {
        "id": "extractive_qa-passage_field",
        "sentinel": "SENTINEL_PASSAGE",
        "claim": "modalities.md: extractive_qa reads passage_field",
        "scheme": None,  # same scheme as the case above
        "item": {"guard_passage": "SENTINEL_PASSAGE the outlet valve failed."},
    },
    {
        "id": "card_sort-items_field",
        "sentinel": "SENTINEL_CARD",
        "claim": "modalities.md: card_sort reads items_field",
        "scheme": {
            "annotation_type": "card_sort",
            "name": "guard_cards",
            "description": "card_sort",
            "items_field": "guard_cards",
            "groups": ["Keep", "Drop"],
        },
        "item": {"guard_cards": ["SENTINEL_CARD one", "SENTINEL_CARD two"]},
    },
    {
        "id": "conjoint-profiles_field",
        "sentinel": "SENTINEL_PROFILE",
        "claim": "modalities.md: conjoint reads profiles_field",
        "scheme": {
            "annotation_type": "conjoint",
            "name": "guard_conj",
            "description": "conjoint",
            "profiles_field": "guard_profiles",
        },
        "item": {"guard_profiles": [{"Price": "SENTINEL_PROFILE low"},
                                    {"Price": "SENTINEL_PROFILE high"}]},
    },
    {
        "id": "error_span-source_field",
        "sentinel": "SENTINEL_ERRSRC",
        "claim": "modalities.md: error_span reads source_field",
        "scheme": {
            "annotation_type": "error_span",
            "name": "guard_errs",
            "description": "error_span",
            "source_field": "guard_errsrc",
            "error_types": [{"name": "omission"}, {"name": "addition"}],
        },
        "item": {"guard_errsrc": "SENTINEL_ERRSRC the translated line."},
    },
]

#: `pairwise` gets its own boot rather than a slot in CASES, because its items
#: replace the whole item display rather than sitting in a scheme box, and a
#: sentinel shared with a neighbouring widget could not tell which one rendered
#: it. Isolation is also what this case is for. At 5fecc94b `items_key` was dead
#: on a page carrying nothing else: the global it read was only ever assigned by
#: the dynamic-schema populator, which returns early when the page has no dynamic
#: scheme. A co-located page hid that, and so did a run against a checkout where
#: the fix had already landed -- which is why the provenance line exists.
#: Fixed in Potato 0a85a017; this is the regression test.
PAIRWISE_CASE = {
    "id": "pairwise-items_key",
    "sentinel": "SENTINEL_PAIR",
    "claim": "modalities.md: items_key is the data field pairwise compares",
    "scheme": {
        "annotation_type": "pairwise",
        "name": "guard_pair",
        "description": "pairwise",
        "items_key": "guard_pair",
        "labels": ["First", "Second"],
    },
    "item": {"guard_pair": ["SENTINEL_PAIR first", "SENTINEL_PAIR second"]},
}


def _potato_provenance() -> str:
    """Which Potato this ran against, and whether it was somebody's working copy."""
    def git(*args):
        try:
            out = subprocess.run(("git",) + args, cwd=potato_repo_path(),
                                 capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return ""
        return out.stdout.strip() if out.returncode == 0 else ""

    commit = git("rev-parse", "--short", "HEAD") or "unknown"
    subject = git("log", "-1", "--format=%s") or ""
    dirty = git("status", "--porcelain", "--", "potato/")

    line = f"Potato at {commit}" + (f" ({subject})" if subject else "")
    if dirty:
        files = [d.split(maxsplit=1)[-1] for d in dirty.splitlines()]
        line += ("\n  WORKING TREE IS DIRTY -- this result describes the working "
                 "copy, not " + commit + ".\n  Uncommitted under potato/: "
                 + ", ".join(files[:8])
                 + (f", and {len(files) - 8} more" if len(files) > 8 else "")
                 + "\n  Before concluding anything about a filed bug, check "
                   "whether these changes are the fix for it.")
    return line


#: `pairwise` hides the main item display exactly when the rendered text IS the
#: pair, and leaves it alone when `items_key` names a field of its own -- because
#: then `text_key` holds the QUESTION, and hiding it takes the question off the
#: page. Both directions, since a fix for either one alone breaks the other.
#: Each is a whole study rather than a CASE, because they differ in config.
TEXT_HIDING = [
    {
        "id": "items_key-keeps-the-question",
        "claim": "text_key holds the question; items_key names the pair. "
                 "The question must stay on screen.",
        "text_key": "question",
        "extra_config": {},
        "item": {"question": "SENTINEL_QUESTION_STAYS which is better?",
                 "pairs": ["SENTINEL_PAIR left.", "SENTINEL_PAIR right."]},
        "scheme": {"annotation_type": "pairwise", "name": "guard_pair",
                   "description": "pairwise", "items_key": "pairs",
                   "labels": ["First", "Second"]},
        "expect_chrome_shown": True,
        "expect_on_page": ["SENTINEL_QUESTION_STAYS", "SENTINEL_PAIR"],
    },
    {
        "id": "list_as_text-hides-both",
        "claim": "text_key IS the pair, so the display would repeat the "
                 "candidates. Both it and its heading must go.",
        "text_key": "pair",
        "extra_config": {"list_as_text": {"text_list_prefix_type": "alphabet"}},
        "item": {"pair": ["SENTINEL_PAIR left.", "SENTINEL_PAIR right."]},
        "scheme": {"annotation_type": "pairwise", "name": "guard_pair",
                   "description": "pairwise", "labels": ["First", "Second"]},
        "expect_chrome_shown": False,
        "expect_on_page": ["SENTINEL_PAIR"],
    },
]


def _free_port() -> int:
    """Bind the way the server binds, or the probe hands out a busy port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _browser_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as play:
            play.chromium.launch().close()
    except Exception:
        return False
    return True


#: Carried by the item under a key no scheme names. If this reaches the page,
#: something is dumping the raw item and every assertion above it passes
#: vacuously -- a sentinel would show up whether or not any widget read its key.
#: The positive cases only mean something while this one holds.
UNREAD_SENTINEL = "SENTINEL_UNREAD"


def _write_study(work_dir: Path, cases, port: int) -> None:
    """One item carrying every case's fields, one scheme per case."""
    item = {"id": "G1", "text": "SENTINEL_TEXTKEY the default text field.",
            "guard_unread": UNREAD_SENTINEL + " under a key nothing names."}
    for case in cases:
        item.update(case["item"])

    (work_dir / "data").mkdir(parents=True, exist_ok=True)
    (work_dir / "data" / "items.json").write_text(
        json.dumps([item], indent=1), encoding="utf-8")

    config = {
        "annotation_task_name": "Field Key Guard",
        "task_dir": ".",
        "output_annotation_dir": "annotation_output/",
        "port": port,
        "data_files": ["data/items.json"],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "login": {"type": "url_direct", "url_argument": "user"},
        "annotation_schemes": [c["scheme"] for c in cases if c["scheme"]],
        "automatic_assignment": {"on": True, "sampling_strategy": "ordered"},
    }
    (work_dir / "config.yaml").write_text(
        json.dumps(config, indent=1), encoding="utf-8")


def _boot(work_dir: Path, port: int):
    log_path = work_dir / "server.log"
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "potato.flask_server", "start", "config.yaml"],
            cwd=str(work_dir), stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    deadline = time.time() + 180
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        text = log_path.read_text(encoding="utf-8", errors="replace")
        if "Running on" in text or "Serving Flask" in text:
            time.sleep(2)
            return proc, log_path.read_text(encoding="utf-8", errors="replace")
        time.sleep(1)

    text = log_path.read_text(encoding="utf-8", errors="replace")
    _kill(proc)
    pytest.fail("the guard study never reached its readiness line:\n"
                + "\n".join(text.splitlines()[-30:]))


def _kill(proc) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()
    proc.wait(timeout=30)


#: Whether the main item display and its heading are on screen. `pairwise`
#: hides both when the rendered text IS the pair and neither when `items_key`
#: names a field of its own, so the pair is what tells the two apart.
_CHROME_PROBE = """() => {
  const el = document.getElementById('instance-text');
  const h = [...document.querySelectorAll('h5')]
      .filter(x => /Text to Annotate/.test(x.textContent));
  const shown = n => !!n && getComputedStyle(n).display !== 'none';
  return {
    instance_text_shown: shown(el),
    heading_shown: h.some(shown),
    heading_count: h.length,
  };
}"""


def _page_probe(port: int) -> dict:
    """The rendered page, after the client-side schema populators have run."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as play:
        browser = play.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/?user={USER}",
                      wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(1500)
            probe = page.evaluate(_CHROME_PROBE)
            probe["text"] = page.inner_text("body")
            return probe
        finally:
            browser.close()


def _render(tmp_path_factory, cases, label):
    if not has_potato_repo():
        pytest.skip("no Potato checkout; set POTATO_REPO")
    if not _browser_available():
        pytest.skip("no headless Chromium; run `playwright install chromium`")

    work_dir = Path(tmp_path_factory.mktemp(label))
    port = _free_port()
    _write_study(work_dir, cases, port)
    proc, log = _boot(work_dir, port)
    try:
        result = _page_probe(port)
        result.update(log=log, potato=_potato_provenance())
        return result
    finally:
        _kill(proc)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    return _render(tmp_path_factory, CASES, "field_guard")


def _render_text_hiding(tmp_path_factory, case):
    if not has_potato_repo():
        pytest.skip("no Potato checkout; set POTATO_REPO")
    if not _browser_available():
        pytest.skip("no headless Chromium; run `playwright install chromium`")

    work_dir = Path(tmp_path_factory.mktemp("hiding"))
    port = _free_port()
    (work_dir / "data").mkdir(parents=True, exist_ok=True)
    item = dict(case["item"], id="H1")
    (work_dir / "data" / "items.json").write_text(
        json.dumps([item], indent=1), encoding="utf-8")
    config = {
        "annotation_task_name": "Text Hiding Guard",
        "task_dir": ".",
        "output_annotation_dir": "annotation_output/",
        "port": port,
        "data_files": ["data/items.json"],
        "item_properties": {"id_key": "id", "text_key": case["text_key"]},
        "login": {"type": "url_direct", "url_argument": "user"},
        "annotation_schemes": [case["scheme"]],
        "automatic_assignment": {"on": True, "sampling_strategy": "ordered"},
    }
    config.update(case["extra_config"])
    (work_dir / "config.yaml").write_text(
        json.dumps(config, indent=1), encoding="utf-8")

    proc, log = _boot(work_dir, port)
    try:
        result = _page_probe(port)
        result.update(log=log, potato=_potato_provenance())
        return result
    finally:
        _kill(proc)


@pytest.fixture(scope="module")
def rendered_pairwise(tmp_path_factory):
    return _render(tmp_path_factory, [PAIRWISE_CASE], "field_guard_pairwise")


@pytest.mark.slow
class TestConfiguredFieldKeysReachThePage:
    @pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
    def test_the_sentinel_is_on_the_page(self, rendered, case):
        assert case["sentinel"] in rendered["text"], (
            f"{case['claim']}\n\n"
            f"The item carries {case['sentinel']!r} under the key the config "
            f"names, and it is not on the rendered page. Either the widget "
            f"reads a different key than the pack says, or it reads nothing and "
            f"renders empty. Nothing in the log says so.\n\n"
            + rendered["potato"] + "\n\n"
            + "\n".join(rendered["log"].splitlines()[-15:]))

    def test_an_unnamed_field_does_not_reach_the_page(self, rendered):
        """Without this, every assertion above could pass without a widget."""
        assert UNREAD_SENTINEL not in rendered["text"], (
            "the item's `guard_unread` field is on the page, and no scheme "
            "names it. Something renders the raw item, so a sentinel arriving "
            "on screen no longer shows that any widget read the key the config "
            "points at -- the positive cases in this file are vacuous until "
            "this is understood.\n\n" + rendered["potato"])

    def test_nothing_raised_while_rendering(self, rendered):
        errors = [line for line in rendered["log"].splitlines()
                  if "[ERROR]" in line or "Traceback" in line]
        assert not errors, rendered["potato"] + "\n\n" + "\n".join(errors[:10])

    def test_the_run_names_the_potato_it_used(self, rendered):
        """A result that cannot say which tree it measured can mislead anyone."""
        assert "Potato at " in rendered["potato"]
        print("\n" + rendered["potato"])

    def test_pairwise_renders_its_items_key(self, rendered_pairwise):
        assert PAIRWISE_CASE["sentinel"] in rendered_pairwise["text"], (
            PAIRWISE_CASE["claim"] + "\n\n"
            "pairwise rendered its label buttons and no candidates. An "
            "annotator sees a choice with nothing to choose between.\n\n"
            + rendered_pairwise["potato"])


@pytest.mark.slow
@pytest.mark.parametrize("case", TEXT_HIDING, ids=lambda c: c["id"])
class TestPairwiseHidesTheItemDisplayOnlyWhenItRepeatsThePair:
    """Whether the main display goes depends on what `text_key` holds."""

    def test_the_expected_strings_are_on_the_page(self, tmp_path_factory, case):
        rendered = _render_text_hiding(tmp_path_factory, case)
        missing = [s for s in case["expect_on_page"] if s not in rendered["text"]]
        assert not missing, (
            f"{case['claim']}\n\nnot on the page: {missing}\n\n"
            + rendered["potato"])

    def test_the_display_and_its_heading_agree(self, tmp_path_factory, case):
        rendered = _render_text_hiding(tmp_path_factory, case)
        want = case["expect_chrome_shown"]
        assert rendered["instance_text_shown"] is want, (
            f"{case['claim']}\n\n#instance-text shown="
            f"{rendered['instance_text_shown']}, expected {want}.\n\n"
            + rendered["potato"])
        assert rendered["heading_shown"] is want, (
            f"{case['claim']}\n\nThe heading and the container disagree: "
            f"heading shown={rendered['heading_shown']}, container shown="
            f"{rendered['instance_text_shown']}. A heading left standing over a "
            f"hidden container is the round-25 finding-3 defect.\n\n"
            + rendered["potato"])
