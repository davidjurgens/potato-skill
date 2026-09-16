#!/usr/bin/env python3
"""
Walk a running Potato task the way an annotator would, and report where it stops.

    python walk_task.py --url http://localhost:8000
    python walk_task.py --url http://localhost:8000 --task-dir . --shots out/

Registers a fresh account, answers whatever each page asks, advances until the
study ends, navigates back to an earlier item to check the answers were stored,
and -- given `--task-dir` and `--config` -- reads
`<output_annotation_dir>/<user>/user_state.json` to confirm the server has them
rather than the browser.

Four things it exists to catch, each of which has shipped broken:

  1. a conditional scheme that never appears when its gate is answered
  2. answers that survive a refresh but not navigating away and back
     (browsers restore form state themselves, so a refresh test passes when the
     server stored nothing)
  3. a workflow that cannot reach its own last page
  4. answers that are on the screen and not in `user_state.json`

By default it is deliberately generic: it picks the first available option for
every question rather than annotating meaningfully. That proves the machinery
works, not that the labels make sense. Two flags go further.

`--grade` answers the gold and attention items from the files the config names,
waits out `attention_checks.min_response_time`, and reports the verdict Potato
recorded for each. The verdict is read out of
`<output_annotation_dir>/quality_control_results.json` rather than recomputed
here: Potato already grades geometry at 0.5 IoU, accepts two payload shapes and
both key separators, and a second implementation of that comparison could only
disagree with Potato's own.

It keeps three outcomes apart, because they send you to three different places:

  * graded wrong -- the answer never reached the grader, or the labels in the
    side file are not the labels in `annotation_schemes`
  * too fast -- `min_response_time` refused the answer for arriving quickly,
    whatever it said. That is the walker's speed, not a fault in the task
  * never served -- the walk did not meet the item. Checks are injected on a
    frequency, so a short walk can finish having seen none, and an empty
    results file otherwise reads exactly like a study running with quality
    control switched off

The wait happens BEFORE answering rather than before Next. The clock starts
when `/annotate` renders the item and stops on an `/updateinstance` POST, and
the page posts one as soon as an option is selected, so the graded save has
already happened by the time Next is clicked. Dwelling before Next left a check
recorded at 1.62s against a 5s floor; dwelling before the answer recorded 7.11s
and passed.

`--answers FILE` takes `{instance id: {scheme: label}}` and annotates with those
instead of picking first options. This is the half a script cannot do for
itself: an agent that has read the items and the guidelines supplies real
judgements, and the walk becomes an annotation pass that can catch a label set
nothing fits or an instruction that contradicts it.

Either way the walk compares what it submitted against what `user_state.json`
came back holding. Counting stored instances, which is all it used to do, never
caught a study that kept a different value than the one it was sent.

Radios, checkboxes, selects, numbers, sliders and tiles it drives directly. The
schemes that answer through a hidden JSON input and a row of buttons -- the whole
agent and trace family, `consensus_tracking`, `emergent_behavior` -- get one
click per group of sibling controls, which is enough to fill a page and not
enough to be a meaningful annotation. A span, a drag-and-drop sort and a canvas
region it cannot drive at all; when it stops, it names the schemes it left
holding nothing so you know which ones to open by hand.

Needs Playwright: `pip install potato-annotation[preview] && playwright install chromium`.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import string
import sys
import time

#: Console output every healthy Potato phase page produces, because a phase page
#: has no instance and the span layer asks for one anyway. Not signal.
KNOWN_NOISE = (
    "/api/current_instance",
    "/api/spans/null",
    "/api/track_annotation_change",
    "SpanManager",
    "Error getting instance text",
)

FILL_TEXT = "Checked by walk_task.py."


def _fresh_user() -> str:
    tail = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))
    return f"walkcheck-{tail}"


EMPTY_SCHEMES_JS = """
() => {
  // Schemes with nothing recorded in them: no checked input, no text typed, no
  // option picked, no hidden value. `{}` and `[]` count as nothing, because that
  // is what the composite widgets initialise their hidden input to.
  const out = [];
  for (const form of document.querySelectorAll('.annotation-form, [data-schema-name]')) {
    const name = form.getAttribute('data-schema-name') || form.id || '';
    if (!name) continue;
    const checked = form.querySelector('input:checked');
    const typed = [...form.querySelectorAll('input[type=text], textarea')]
        .some(e => (e.value || '').trim());
    const held = [...form.querySelectorAll('input[type=hidden]')]
        .some(e => (e.value || '').trim() && e.value.trim() !== '{}' && e.value.trim() !== '[]');
    const picked = [...form.querySelectorAll('select')].some(e => (e.value || '').trim());
    if (checked || typed || held || picked) continue;
    out.push({name: name,
              type: form.getAttribute('data-annotation-type') || ''});
  }
  return out;
}
"""


def _schemes_holding_nothing(page):
    """Which schemes on this page have no answer in them at all.

    Returns a list, or None when the probe could not run. The distinction is
    the whole point: this used to return `[]` on any exception, and `[]` is
    what the caller prints "every scheme on the page holds an answer" for. A
    page that had closed, or one where the evaluate threw, produced that
    sentence -- which tells the reader to stop looking at the widgets -- on no
    evidence at all.
    """
    try:
        return page.evaluate(EMPTY_SCHEMES_JS) or []
    except Exception:
        return None


def _output_dir(config_path: str) -> str:
    """Where this config writes `<user>/user_state.json`, relative to task_dir.

    `annotation_output/` is only the convention. A config naming anything else in
    `output_annotation_dir` used to make the walk report "Nothing this walk did
    reached the server" on a task that had stored every answer, which is the one
    problem line nobody should have to disbelieve.
    """
    if not config_path or not os.path.isfile(config_path):
        return "annotation_output"
    try:
        import yaml
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except Exception:
        return "annotation_output"
    return str(config.get("output_annotation_dir") or "annotation_output").rstrip("/")


def _training_answers(config_path: str) -> dict:
    """id -> correct_answers, read from the configured training file.

    Without this a generic walker cannot get past a practice round: training
    grades the answer and keeps the annotator on the item until it is right, so
    picking the first option loops forever on any question whose model answer is
    not the first label.
    """
    if not config_path or not os.path.isfile(config_path):
        return {}
    try:
        import yaml
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except Exception:
        return {}
    training = config.get("training") or {}
    data_file = training.get("data_file") if isinstance(training, dict) else None
    if not data_file:
        return {}
    base = os.path.dirname(os.path.abspath(config_path))
    path = data_file if os.path.isabs(data_file) else os.path.join(base, data_file)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    instances = data.get("training_instances") if isinstance(data, dict) else None
    return {str(item.get("id")): (item.get("correct_answers") or {})
            for item in (instances or []) if item.get("id") is not None}


def _config(config_path: str | None) -> dict:
    """The parsed config, or `{}`."""
    if not config_path or not os.path.isfile(config_path):
        return {}
    try:
        import yaml
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _side_file_answers(config_path: str, block_name: str, answer_key: str) -> dict:
    """`id -> expected answer`, from a quality-control side file.

    `gold_standards.items_file` and `attention_checks.items_file` are both a
    JSON **array**, which is why this cannot be folded into
    `_training_answers` -- training's file is an object with a
    `training_instances` key.

    A gold item may write `gold_label` as a bare string rather than a
    `{scheme: label}` dict. That form names no scheme, so the walker cannot
    drive it; it is returned as-is and only the verdict Potato recorded for it
    can be read.
    """
    block = _config(config_path).get(block_name) or {}
    if not isinstance(block, dict):
        return {}
    data_file = block.get("items_file")
    if not data_file:
        return {}
    base = os.path.dirname(os.path.abspath(config_path))
    path = data_file if os.path.isabs(data_file) else os.path.join(base, data_file)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            items = json.load(f)
    except Exception:
        return {}
    if not isinstance(items, list):
        return {}
    return {str(item.get("id")): item.get(answer_key)
            for item in items
            if isinstance(item, dict)
            and item.get("id") is not None
            and item.get(answer_key) is not None}


def _supplied_answers(answers_path: str | None) -> dict:
    """`{instance_id: {scheme: label}}` an agent wrote, or `{}`.

    This is the half of the walk a script cannot do for itself. Picking the
    first option proves the machinery works; it cannot notice that two labels
    mean the same thing, that the guidelines contradict the label set, or that
    an item has no right answer in it. An agent that has read the items and the
    codebook writes those judgements here and the walker types them in, which
    turns the walk from a smoke test into an annotation pass.

    Values are label strings exactly as they appear in `labels:` -- the stored
    value, not the humanized display form -- and a list ticks one box per
    label, the same shape `training.data_file` uses for `correct_answers`.
    """
    if not answers_path:
        return {}
    if not os.path.isfile(answers_path):
        raise SystemExit(f"No answers file at {answers_path}")
    try:
        with open(answers_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        raise SystemExit(f"Could not read {answers_path}: {exc}")
    if not isinstance(data, dict):
        raise SystemExit(
            f"{answers_path} must be a JSON object mapping instance id to "
            f"{{scheme: label}}, not a {type(data).__name__}.")
    return {str(k): v for k, v in data.items() if isinstance(v, dict)}


def _min_response_time(config_path: str) -> float:
    """`attention_checks.min_response_time`, or 0.

    The walker fills a page in well under a second, and the save route measures
    serve-to-save on the **server** rather than trusting the client's claimed
    time. So on a study setting this, every attention check the walker answers
    is recorded `too_fast` however right the answer was -- a failure belonging
    to the walker rather than to the task. `--grade` waits this long on a
    check instead, which is the only way the recorded verdict means anything.
    """
    block = _config(config_path).get("attention_checks") or {}
    if not isinstance(block, dict):
        return 0.0
    try:
        return float(block.get("min_response_time") or 0)
    except (TypeError, ValueError):
        return 0.0


def _qc_results(task_dir: str, config_path: str, user: str) -> dict:
    """What Potato recorded for this annotator, read rather than recomputed.

    Potato already grades both kinds -- geometry at 0.5 IoU, both wire-key
    separators, and the two payload shapes `/updateinstance` accepts -- and
    writes the verdict to
    `<output_annotation_dir>/quality_control_results.json`. Grading again here
    would be a second implementation of a question that already has an answer,
    and the only thing a disagreement between them could prove is that this
    file is wrong.
    """
    path = os.path.join(task_dir, _output_dir(config_path),
                        "quality_control_results.json")
    if not os.path.isfile(path):
        return {"path": path, "found": False, "gold": [], "attention": []}
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return {"path": path, "found": False, "gold": [], "attention": []}
    return {
        "path": path,
        "found": True,
        "gold": (payload.get("gold_results") or {}).get(user) or [],
        "attention": (payload.get("attention_results") or {}).get(user) or [],
    }


def _grade_report(qc: dict, gold: dict, attention: dict, problems: list) -> dict:
    """Potato's recorded verdicts, per item, with three outcomes kept apart.

    They are kept apart because they send you to three different places:

      * **graded wrong** -- under `--grade` the walker submitted the file's own
        expected answer, so a wrong verdict means the answer never reached the
        grader or the labels in the side file do not match `annotation_schemes`.
      * **too fast** -- `min_response_time` refused the answer for arriving
        quickly, whatever it said. That is the walker's speed rather than a
        fault in the task, and reporting it as a content failure sends someone
        to rewrite a check item that was fine.
      * **never served** -- an item in the file the walk never met. Checks are
        injected on a frequency, so a short walk can finish having seen none,
        and an empty results file then reads exactly like a study running with
        quality control switched off. Those two must never print the same line.
    """
    graded = {"results_file": qc.get("path"), "found": qc.get("found", False),
              "gold": [], "attention": [], "too_fast": [], "never_served": []}
    seen_gold, seen_attention = set(), set()

    for record in qc.get("gold", []):
        seen_gold.add(record.get("item_id"))
        graded["gold"].append({"item_id": record.get("item_id"),
                               "correct": bool(record.get("correct")),
                               "gold_label": record.get("gold_label"),
                               "user_response": record.get("user_response")})
    for record in qc.get("attention", []):
        seen_attention.add(record.get("item_id"))
        entry = {"item_id": record.get("item_id"),
                 "passed": bool(record.get("passed")),
                 "too_fast": bool(record.get("too_fast")),
                 "response_time_seconds": record.get("response_time_seconds"),
                 "expected": record.get("expected"),
                 "actual": record.get("actual")}
        graded["attention"].append(entry)
        if entry["too_fast"]:
            graded["too_fast"].append(entry["item_id"])

    graded["never_served"] = sorted(
        (set(gold) - seen_gold) | (set(attention) - seen_attention))

    wrong_gold = [r["item_id"] for r in graded["gold"] if not r["correct"]]
    wrong_checks = [r["item_id"] for r in graded["attention"]
                    if not r["passed"] and not r["too_fast"]]

    if wrong_gold:
        problems.append(
            f"Gold item(s) graded wrong after the walker submitted the answer "
            f"from gold_standards.items_file: {', '.join(wrong_gold)}. Either "
            f"the answer did not reach the grader, or the labels in that file "
            f"are not the labels in annotation_schemes.")
    if wrong_checks:
        problems.append(
            f"Attention check(s) failed on content rather than speed: "
            f"{', '.join(wrong_checks)}. The walker submitted the file's own "
            f"expected_answer, so the check cannot be passed as written -- "
            f"usually a required scheme the item never tells the annotator to "
            f"answer.")
    if graded["too_fast"]:
        problems.append(
            f"{len(graded['too_fast'])} attention check(s) recorded too_fast. "
            f"That is the walker answering faster than "
            f"attention_checks.min_response_time, not a fault in the task, and "
            f"the verdict on those items says nothing about their content.")
    if (gold or attention) and not qc.get("found"):
        problems.append(
            f"No {qc.get('path')}, but the config declares {len(gold)} gold "
            f"item(s) and {len(attention)} attention check(s). Nothing was "
            f"graded at all. Check the boot log for 'Loaded N gold standard "
            f"items' before believing the study is checking anyone.")
    elif graded["never_served"]:
        problems.append(
            f"Never served during this walk: "
            f"{', '.join(graded['never_served'])}. Those items were not "
            f"graded, so a clean result here is not evidence about them.")
    return graded


def _split_key(key: str):
    """`<scheme>:::<label>` or `<scheme>:<label>` -> `(scheme, label)`, else None.

    `:::` is tried first because a `:::` key also contains a `:`: splitting on
    the first colon turns `stance:::Sincere` into the label `"::Sincere"`,
    which matches nothing and says nothing. Mirrors Potato's own
    `split_annotation_key`; a phase-page answer such as `{"age_consent": "Yes"}`
    names no label and returns None.
    """
    if not isinstance(key, str):
        return None
    if ":::" in key:
        scheme, _, label = key.partition(":::")
        return scheme, label
    if ":" in key:
        scheme, _, label = key.partition(":")
        return scheme, label
    return None


#: Values meaning "the key names the answer" rather than being it. A checked
#: radio posts the browser's own default, `"on"`.
_SELECTED = {"on", "true", "yes", "1", "checked", "selected"}


#: Stored values meaning "this option was not chosen" rather than being an
#: answer. Copied from Potato's `annotation_values.FALSEY`, which is what its
#: own `selected_labels` filters on.
_FALSEY = (False, None, "", "false", "False", 0, "0")


def _stored_readings(stored) -> dict:
    """`scheme -> set of label names that could be its stored answer`.

    **What is on disk is not what went over the wire**, and confusing the two
    is why this function existed for a while without ever running. The page
    posts `{"category:::B": "B"}`; `user_state.json` holds
    `[[{"schema": "category", "name": "B"}, "B"], ...]` -- a list of
    `[Label, value]` pairs, because the in-memory container is keyed by `Label`
    objects and JSON has nowhere to put them. A reader written for the wire
    shape iterates `.items()` on a list, finds nothing, and reports every
    answer as matching.

    Potato's own `annotation_values.group_by_schema` cannot be borrowed here:
    it reads `Label` keys off a live `UserState`, and raises `AttributeError`
    on the list this file actually contains. The pair form below is that same
    regrouping after serialization.

    The **name** carries the answer, not the value -- radio stores
    `{"positive": True}` and likert `{"2": "2"}` -- so a name is collected
    whenever its value is not falsey. The flat `{"<scheme>:::<label>": value}`
    form is still read, because a phase page and a hand-built payload both use
    it.
    """
    readings: dict = {}

    def keep(scheme, name):
        if scheme and name is not None:
            readings.setdefault(str(scheme), set()).add(str(name))

    # The on-disk form: a list of [{"schema": ..., "name": ...}, value] pairs.
    if isinstance(stored, list):
        for pair in stored:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            label, value = pair
            if not isinstance(label, dict):
                continue
            scheme, name = label.get("schema"), label.get("name")
            if value in _FALSEY:
                continue
            # A geometry or temporal scheme stores one JSON blob under `_data`
            # rather than a chosen label, so there is no label name to compare
            # and pretending otherwise reports a mismatch on every drawn
            # answer. Left out: absent is honest, a false mismatch is not.
            if name == "_data":
                continue
            keep(scheme, name)
            # A free-text answer keeps the typed string in the value and a
            # widget name (`text_box`) in the name, so the value is the answer.
            if isinstance(value, str) and value.strip() and value != name:
                keep(scheme, value)
        return readings

    # The wire form, and anything already grouped as {scheme: {name: value}}.
    for key, value in (stored or {}).items():
        parsed = _split_key(key)
        if parsed:
            scheme, name = parsed
            if value not in _FALSEY:
                keep(scheme, name)
            if isinstance(value, str) and value.strip():
                keep(scheme, value)
        elif isinstance(value, dict):
            for name, inner in value.items():
                if inner not in _FALSEY:
                    keep(key, name)
        elif isinstance(value, list):
            for item in value:
                keep(key, item)
        elif value not in _FALSEY:
            keep(key, value)
    return readings


def _group_of(element, name: str) -> str:
    """The set of inputs among which ticking one counts as answering.

    Not the same rule for both input kinds, and getting it wrong dead-ends the
    walk either way.

    A **radio**'s group is its `name` attribute, because that is what makes
    radios mutually exclusive in the browser. Grouping radios by scheme instead
    breaks `multirate`, which renders one radio group per option row and shares
    a scheme across all of them: three rows, one answer, and a required scheme
    that never completes.

    A **checkbox**'s group is its scheme, because a multiselect names every
    option separately as `schema:::label`. Grouping those by name ticks every
    box, which is not "the first option" and cannot pass a graded practice
    question.
    """
    if (element.get_attribute("type") or "") == "radio":
        return name or ""
    return (name or "").split(":::", 1)[0]


def _answer_as_told(page, answers: dict) -> int:
    """Set exactly the answers given, by scheme name and label value.

    Both field namings have to be tried. A radio's option is
    `input[name=schema][value=label]`; a multiselect's is
    `input[name=schema:::label]`, so the radio selector matches nothing on it
    and a training round with a multiselect model answer never gets answered.
    A list value ticks one box per label.
    """
    touched = 0
    for name, value in answers.items():
        for label in (value if isinstance(value, list) else [value]):
            for selector in (f'input[name="{name}"][value="{label}"]',
                             f'input[name="{name}:::{label}"]'):
                locator = page.locator(selector).first
                try:
                    if locator.count():
                        locator.check(force=True)
                        touched += 1
                        break
                except Exception:
                    pass
    return touched


#: Buttons inside an annotation form that do something other than answer it:
#: panel controls, span deletes, tree path resets. Matched against the button's
#: own text, lowercased.
NOT_AN_ANSWER = (
    "clear", "cancel", "delete", "remove", "reset", "undo", "close", "create",
    "add ", "save", "submit", "expand", "collapse", "×", "x",
)

COMPOSITE_CLICK_JS = """
(skipWords) => {
  // One click per group of sibling controls, inside annotation forms only.
  // The trace and multi-agent schemes answer through buttons carrying data
  // attributes and a hidden JSON input, so no radio, checkbox or tile selector
  // finds them: a required `agent_scorecard` or `handoff_review` otherwise
  // dead-ends the walk with the page reporting nothing wrong.
  const forms = document.querySelectorAll(
      '.annotation-form, [data-schema-name], [data-annotation-type]');
  const groups = new Map();
  for (const form of forms) {
    const controls = form.querySelectorAll(
        'button[type=button], [role=button]');
    for (const el of controls) {
      const data = [...el.attributes].filter(a => a.name.startsWith('data-'));
      if (!data.length) continue;                       // plain panel button
      const text = (el.innerText || '').trim().toLowerCase();
      if (skipWords.some(w => text === w.trim() || text.startsWith(w))) continue;
      if (el.disabled) continue;
      const box = el.getBoundingClientRect();
      const isSvg = el.ownerSVGElement || el.tagName.toLowerCase() === 'g';
      if (!isSvg && (box.width === 0 || box.height === 0)) continue;
      const key = el.parentElement;
      if (!groups.has(key)) groups.set(key, el);
    }
  }
  let clicked = 0;
  for (const el of groups.values()) {
    if (el.getAttribute('aria-pressed') === 'true'
        || (el.className || '').toString().includes('active')) continue;
    el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    clicked += 1;
  }
  return clicked;
}
"""


def _answer_composite_widgets(page) -> int:
    """Click one control per group in the button-and-hidden-input schemes.

    `agent_scorecard`, `handoff_review`, `failure_attribution`,
    `consensus_tracking`, `emergent_behavior`, `tool_contention` and
    `agent_interaction_graph` answer by clicking a button that writes to a
    hidden JSON input. They carry no `annotation-input` class on anything
    clickable, so every other pass here walks straight past them and reports
    "0 answered" on a page the annotator can fill in.
    """
    try:
        return int(page.evaluate(COMPOSITE_CLICK_JS, list(NOT_AN_ANSWER)))
    except Exception:
        return 0


def _answer_selects(page) -> int:
    """Choose the first real option in any select still sitting on its placeholder.

    From 2.8.2-10 a `select` opens on a disabled `-- select one --` rather than
    preselecting its first label, which is right, and means a required select now
    blocks the walk until something picks. `failure_attribution` renders two
    selects with no `name` at all, so this cannot key off the name the way the
    text pass does.
    """
    touched = 0
    for element in page.query_selector_all("select"):
        try:
            if not element.is_visible() or (element.input_value() or "").strip():
                continue
            values = element.evaluate(
                "s => [...s.options].filter(o => o.value && !o.disabled)"
                ".map(o => o.value)")
            if not values:
                continue
            element.select_option(values[0])
            touched += 1
        except Exception:
            pass
    return touched


def _click_or_label(page, element) -> bool:
    """Tick an input, or the `<label for=...>` standing in for it. False if neither.

    A styled radio group hides the real input and renders a label the annotator
    clicks. `check(force=True)` on a `display: none` input raises rather than
    ticking it, so the label is the only route.
    """
    if element.is_visible():
        try:
            element.check(force=True)
            return True
        except Exception:
            pass
    element_id = element.get_attribute("id")
    if element_id:
        label = page.query_selector(f'label[for="{element_id}"]')
        if label and label.is_visible():
            try:
                label.click()
                return True
            except Exception:
                pass
    return False


def _middle_value(element) -> str:
    """A value inside the input's own min/max, as a string.

    The midpoint rather than the minimum, because `min` is often 0 and a slider
    left at 0 is indistinguishable from one nobody moved.
    """
    def _num(attr, fallback):
        try:
            return float(element.get_attribute(attr))
        except (TypeError, ValueError):
            return fallback
    low, high = _num("min", 0.0), _num("max", 100.0)
    if high < low:
        low, high = high, low
    value = low + (high - low) / 2
    return str(int(value)) if value == int(value) else f"{value:.2f}"


def _answer_everything(page) -> int:
    """Answer every question visible on the page. Returns how many it touched.

    Radios and checkboxes take their first option, sliders and numbers their
    current value, text boxes a fixed string. Only *visible* inputs -- a scheme
    behind `display_logic` has a bounding box while hidden, so visibility is
    checked on the ancestor chain by Playwright rather than by size.
    """
    touched = 0

    # Already-answered groups are left alone, so this is safe to call twice --
    # which it has to be, because a scheme behind `display_logic` only appears
    # after the question that gates it has been answered.
    answered_groups = {
        _group_of(element, element.get_attribute("name"))
        for element in page.query_selector_all("input:checked")
    }

    seen_groups = set(answered_groups)
    for element in page.query_selector_all("input[type=radio]"):
        name = element.get_attribute("name")
        group = _group_of(element, name)
        if not name or group in seen_groups:
            continue
        # Not `is_visible()`. `semantic_differential` sets its radios to
        # `display: none` and puts a styled `<label for=...>` over each one, so
        # a visibility test skips every option of a scheme an annotator can
        # answer with a click -- and if it is `required`, the walk dead-ends
        # with the walker reporting nothing wrong. Take the label when the input
        # itself cannot be clicked.
        if not _click_or_label(page, element):
            continue
        seen_groups.add(group)
        touched += 1

    for element in page.query_selector_all("input[type=checkbox]"):
        name = element.get_attribute("name") or ""
        group = _group_of(element, name)
        if name.startswith("span_label:::") or not element.is_visible():
            continue          # span chips select a label, they do not answer
        if group in seen_groups:
            continue
        seen_groups.add(group)
        try:
            element.check(force=True)
            touched += 1
        except Exception:
            pass

    # Tile schemes. `pairwise`, `bws`, `ranking` and `triage` answer by clicking a
    # div carrying `data-schema` and `data-value`, with a hidden input behind it,
    # so there is no checkbox or radio for the passes above to find. Without this
    # a required pairwise question dead-ends the walk with no explanation: the
    # page simply does not advance and the server logs nothing.
    for element in page.query_selector_all("[data-schema][data-value]"):
        schema = element.get_attribute("data-schema") or ""
        if not schema or schema in seen_groups or not element.is_visible():
            continue
        classes = element.get_attribute("class") or ""
        if "tool-btn" in classes or "label-btn" in classes:
            continue          # canvas toolbars, not answers
        seen_groups.add(schema)
        try:
            element.click()
            touched += 1
        except Exception:
            pass

    # Numbers and sliders. `constant_sum` renders one number box per label and
    # `vas`/`slider` render a range; both count as answered only when they hold
    # a value, so a required one of either stops the walk otherwise. Nothing here
    # tries to satisfy `constant_sum`'s total, which the widget does not enforce.
    for element in page.query_selector_all(
            "input[type=number].annotation-input, input[type=range].annotation-input"):
        if not element.is_visible():
            continue
        if (element.input_value() or "").strip() and \
                (element.get_attribute("type") or "") == "number":
            continue
        try:
            element.fill(_middle_value(element))
            element.dispatch_event("input")
            element.dispatch_event("change")
            touched += 1
        except Exception:
            pass

    touched += _answer_selects(page)
    touched += _answer_composite_widgets(page)

    for selector in ("textarea", "input[type=text]", "input[type=search]"):
        for element in page.query_selector_all(selector):
            name = element.get_attribute("name") or ""
            if not element.is_visible() or name in ("email", "pass"):
                continue
            # Every input that is an answer is named `<scheme>:::<label>`. An
            # unnamed text box belongs to the widget, not to the annotator --
            # `hierarchical_multiselect` renders `input.hier-search-input` to
            # filter its tree, and typing into it hides every option, so the
            # walk then reported the scheme as one it could not answer.
            if not name:
                continue
            if (element.input_value() or "").strip():
                continue
            try:
                element.fill(FILL_TEXT)
                touched += 1
            except Exception:
                pass

    return touched


def _unanswered_message(page) -> str:
    """What the page says is still unanswered, or "".

    Potato names the blocking questions in `#required-fields-error`, by their
    `description` text, but only after a forward attempt -- which by the time
    this is called has happened four times. Reading it turns "stuck, could be
    anything" into the actual question.
    """
    for selector in ("#required-fields-error", ".required-fields-error"):
        element = page.query_selector(selector)
        if element and element.is_visible():
            text = " ".join((element.inner_text() or "").split())
            if text:
                return text if text.endswith(".") else text + "."
    return ""


def _settle(page) -> None:
    """Wait for a page swap. Potato re-renders in place, so there is often no
    navigation to wait for -- `networkidle` returns immediately and the Next
    button is still being replaced."""
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(1200)


def _advance(page) -> bool:
    """Click whatever moves this page forward. False when nothing does.

    Uses locators rather than element handles: a handle grabbed before the
    re-render detaches mid-click and reports "element is not enabled", which
    reads like a disabled button when the page simply moved on.
    """
    for selector in ("#next-btn", "button:has-text('Next')",
                     "button:has-text('Submit')", "button:has-text('Continue')",
                     "input[type=submit]"):
        locator = page.locator(selector).first
        try:
            if locator.count() == 0 or not locator.is_visible():
                continue
            locator.click(timeout=10000)
        except Exception:
            continue
        _settle(page)
        return True
    return False


def _is_finished(page) -> bool:
    body = (page.inner_text("body") or "").lower()
    return any(phrase in body for phrase in
               ("thank you", "you are done", "study complete", "no more instances"))


def walk(url: str, task_dir: str | None, shots: str | None, max_steps: int,
         config_path: str | None = None, grade: bool = False,
         answers_path: str | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    user = _fresh_user()
    console: list = []
    where = ["register"]
    training = _training_answers(config_path) if config_path else {}

    # Answers the walker can be told rather than guess. Training is always
    # read, because without it a practice round dead-ends the walk. Gold and
    # attention answers are only *driven* under --grade: driving them by
    # default would make every study score 100%, which is a fixture that
    # cannot fail and so measures nothing.
    known: dict = dict(training)
    gold = _side_file_answers(config_path, "gold_standards", "gold_label") \
        if config_path else {}
    attention = _side_file_answers(config_path, "attention_checks",
                                   "expected_answer") if config_path else {}
    supplied = _supplied_answers(answers_path)
    if grade:
        for source in (gold, attention):
            for item_id, value in source.items():
                # A bare-string `gold_label` names no scheme, so it cannot be
                # typed into a form. Its verdict is still read below.
                if isinstance(value, dict):
                    known[item_id] = value
    # An agent's own answers outrank every file: they are the whole point of
    # --answers, and on a gold item they are what is being tested.
    known.update(supplied)

    dwell = _min_response_time(config_path) if (grade and config_path) else 0.0

    report = {"user": user, "steps": [], "console_errors": console, "problems": [],
              "training_items_known": len(training),
              "gold_items_known": len(gold),
              "attention_items_known": len(attention),
              "supplied_answers": len(supplied),
              "graded": bool(grade),
              "dwell_seconds": dwell}

    def note_error(text: str):
        if "Failed to load resource" in text:
            return          # the response hook below records these with a URL
        if not any(noise in text for noise in KNOWN_NOISE):
            console.append(f"[{where[0]}] {text[:200]}")

    def note_response(response):
        if response.status < 400:
            return
        if any(noise in response.url for noise in KNOWN_NOISE):
            return
        console.append(f"[{where[0]}] {response.status} {response.url}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={"width": 1280, "height": 1000}).new_page()
        page.on("console", lambda m: note_error(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: note_error(str(e)))
        page.on("response", note_response)

        page.goto(url)
        _settle(page)
        try:
            page.evaluate("switchTab('register')")
        except Exception:
            report["problems"].append(
                "No register tab on the landing page. If this is a re-run, the "
                "previous account may still be logged in.")
        for element in page.query_selector_all("form[action='/register'] input"):
            name = element.get_attribute("name")
            if name == "email":
                element.fill(user)
            elif name == "pass":
                element.fill("walkcheck-pw")
        button = page.query_selector("form[action='/register'] button[type=submit]")
        if button:
            button.click()
            _settle(page)

        first_instance = None
        for step in range(max_steps):
            where[0] = f"step{step}"
            served = time.monotonic()
            instance = page.query_selector("#instance_id")
            instance_id = instance.get_attribute("value") if instance else None
            if instance_id and first_instance is None:
                first_instance = instance_id

            if shots:
                os.makedirs(shots, exist_ok=True)
                page.wait_for_timeout(400)
                page.screenshot(path=os.path.join(shots, f"{step:02d}.png"),
                                full_page=True)

            # Wait BEFORE answering, not before Next. The clock starts when
            # `/annotate` renders the item and stops on an `/updateinstance`
            # POST, and the page posts one as soon as an option is selected --
            # so on a check the graded save has already happened by the time
            # the Next button is clicked, and a wait placed there cannot move
            # a number that is already recorded. Measured: dwelling before
            # Next left `chk1` at 1.62s against a 5s floor.
            if dwell:
                remaining = (dwell + 0.5) - (time.monotonic() - served)
                if remaining > 0:
                    page.wait_for_timeout(int(remaining * 1000))

            answered = 0
            if instance_id and instance_id in known:
                # The told answer first: _answer_everything skips groups that
                # already have a selection, so it cannot overwrite it.
                answered += _answer_as_told(page, known[instance_id])
            answered += _answer_everything(page)
            # Long enough for a `display_logic` reveal to finish. The container
            # animates its max-height over 300ms and the scheme inside is not
            # clickable until it does, so at 400ms the second pass still saw a
            # hidden question and the walk needed a whole extra step per item.
            page.wait_for_timeout(1000)
            answered += _answer_everything(page)   # conditional schemes just shown
            report["steps"].append({
                "step": step,
                "title": (page.title() or "")[:80],
                "instance_id": instance_id,
                "answered": answered,
            })

            recent = [s["instance_id"] for s in report["steps"][-4:]]
            if len(recent) == 4 and len(set(recent)) == 1 and recent[0]:
                # Which advice depends on whether the model answers were
                # available. Telling someone to pass --config when they already
                # did sends them to a fix they have applied and hides the real
                # one, which is that the answer was submitted and graded wrong.
                if recent[0] in supplied:
                    hint = (f"Its answer came from --answers: "
                            f"{supplied[recent[0]]}. The walker submitted that "
                            f"and the page still would not advance, so either "
                            f"one of those labels is not one the scheme offers, "
                            f"or a required scheme on the page has no answer in "
                            f"the file.")
                elif recent[0] in gold or recent[0] in attention:
                    source = ("gold_standards.items_file" if recent[0] in gold
                              else "attention_checks.items_file")
                    hint = (f"{recent[0]} is a quality-control item from "
                            f"{source}, answered from that file under --grade. "
                            f"A check item has to instruct every required "
                            f"scheme, spans included; when it does not the page "
                            f"refuses to advance and the only feedback is a "
                            f"small toast naming the internal scheme name.")
                elif recent[0] in training:
                    hint = (f"Its model answer is {training[recent[0]]}. The "
                            f"walker submitted that and training still refused "
                            f"it, so the labels in training.data_file do not "
                            f"match the labels in annotation_schemes, or a "
                            f"required scheme on the page has no model answer.")
                elif training:
                    # Rules the graded answer out rather than recommending a
                    # fix for it. This used to read "There is no model answer
                    # for <id> in training.data_file. If this is a practice
                    # item, add one" on any item the walk stalled on, which on
                    # an ordinary item blocked by a required span sends the
                    # reader to add a practice answer for an item that is not
                    # a practice item -- while the real cause was named in the
                    # same paragraph.
                    hint = (f"{recent[0]} is not one of the practice items in "
                            f"training.data_file, so a graded practice answer "
                            f"is not what is blocking it.")
                elif config_path is None:
                    hint = ("If this is the practice round, the answer is "
                            "graded and the walker does not know it -- pass "
                            "--config so it can read training.data_file. "
                            "Otherwise the item will not accept an answer.")
                else:
                    # --config was read and it declares no training, so a
                    # graded answer cannot be what is blocking. Sending
                    # someone back to --config here is the second-worst
                    # outcome after saying nothing: it names a file the task
                    # does not have. What is left is a required scheme the
                    # walker could not fill.
                    hint = ("The config names no training data, so this is "
                            "not a graded answer.")
                empty = _schemes_holding_nothing(page)
                if empty is None:
                    hint += (" The walker could not read the page to see which "
                             "schemes hold an answer, so that question is "
                             "unanswered rather than answered no. Open the item "
                             "and check the widgets by hand.")
                elif empty:
                    named = ", ".join(
                        f"{item['name']}"
                        + (f" ({item['type']})" if item.get("type") else "")
                        for item in empty[:6])
                    hint += (f" Nothing was recorded in: {named}. Those are the "
                             f"widgets the walker could not drive -- a span, a "
                             f"drag-and-drop sort, a canvas region -- so check "
                             f"them by hand.")
                else:
                    hint += (" Every scheme on the page holds an answer, so the "
                             "page is not refusing to advance for want of one. "
                             "On the last item with nothing stored, Potato keeps "
                             "the annotator on it rather than showing the "
                             "finished page.")
                blocking = _unanswered_message(page)
                if blocking:
                    hint = (f"The page says: {blocking} That message is the "
                            f"server's own list of required schemes still "
                            f"unanswered, so start there. " + hint)
                report["problems"].append(
                    f"Stuck on item {recent[0]} for four steps. {hint}")
                report["reached_end"] = False
                break

            if _is_finished(page):
                report["reached_end"] = True
                break

            if not _advance(page):
                report["problems"].append(
                    f"Nothing advanced the page at step {step} "
                    f"(title {page.title()!r}). The workflow stops here.")
                report["reached_end"] = False
                break
        else:
            report["reached_end"] = False
            report["problems"].append(
                f"Still going after {max_steps} steps. Either the task is longer "
                f"than that, or something is looping.")

        # Navigate back to the first item and check the answers came back.
        #
        # Only when the walk actually moved. A walk stuck on item one never left
        # it, so "navigated back and nothing was selected" is a second problem
        # invented out of the first one -- and it points at storage, which is not
        # where the fault is.
        visited = {s["instance_id"] for s in report["steps"] if s["instance_id"]}
        if first_instance and len(visited) > 1:
            where[0] = "revisit"
            go_to = page.query_selector("#go_to")
            if go_to:
                try:
                    go_to.fill("1")
                    page.click("#go-to-btn")
                    _settle(page)
                    checked = page.query_selector_all("input[type=radio]:checked")
                    report["restored_on_revisit"] = len(checked)
                    if not checked:
                        report["problems"].append(
                            "Navigated back to item 1 and nothing was selected. "
                            "Either the answers were never stored or they are not "
                            "being restored into the page.")
                except Exception as exc:
                    report["problems"].append(f"Could not navigate back: {exc}")

        browser.close()

    if task_dir:
        state_path = os.path.join(
            task_dir, _output_dir(config_path), user, "user_state.json")
        report["user_state"] = state_path
        if os.path.isfile(state_path):
            with open(state_path, encoding="utf-8") as f:
                state = json.load(f)
            annotations = state.get("instance_id_to_label_to_value") or {}
            report["stored_instances"] = len(annotations)

            # What was stored, against what was submitted. `stored_instances`
            # counts items and has never compared values, so a study that kept
            # the wrong label passed this check for as long as it has existed.
            # Only items the walker was *told* an answer for can be checked:
            # for the rest it picked the first option and has nothing to
            # compare against.
            mismatches = []
            for item_id, expected in known.items():
                stored = annotations.get(item_id)
                if not isinstance(expected, dict) or not isinstance(stored, dict):
                    continue
                readings = _stored_readings(stored)
                for scheme, value in expected.items():
                    wanted = {str(v) for v in
                              (value if isinstance(value, list) else [value])}
                    got = readings.get(scheme, set())
                    if not (wanted & got):
                        mismatches.append({"instance_id": item_id,
                                           "scheme": scheme,
                                           "submitted": sorted(wanted),
                                           "stored": sorted(got)})
            report["value_mismatches"] = mismatches
            if mismatches:
                named = "; ".join(
                    f"{m['instance_id']}/{m['scheme']} submitted "
                    f"{m['submitted']}, stored {m['stored'] or 'nothing'}"
                    for m in mismatches[:5])
                report["problems"].append(
                    f"{len(mismatches)} answer(s) reached the server as a "
                    f"different value than the one submitted: {named}.")

            if not annotations:
                report["problems"].append(
                    f"{state_path} exists but holds no annotations. The page "
                    f"showed answers the server did not keep.")
        else:
            report["stored_instances"] = 0
            report["problems"].append(
                f"No {state_path}. Nothing this walk did reached the server. "
                f"(State is written when an annotation is submitted, so on a "
                f"task with no annotation phase this is expected.)")

        if grade:
            report["quality_control"] = _grade_report(
                _qc_results(task_dir, config_path or "", user),
                gold, attention, report["problems"])

    if console:
        report["problems"].append(
            f"{len(console)} console error(s) that are not Potato's usual "
            f"phase-page noise.")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--config", default=None,
                        help="Config file, so practice questions can be answered "
                             "from training.data_file")
    parser.add_argument("--task-dir", default=None,
                        help="Project directory, to read annotation_output/")
    parser.add_argument("--shots", default=None,
                        help="Directory for a full-page screenshot of every step")
    parser.add_argument("--max-steps", type=int, default=25)
    parser.add_argument("--grade", action="store_true",
                        help="Answer the gold and attention items from their "
                             "own files, wait out min_response_time, and "
                             "report the verdict Potato recorded for each")
    parser.add_argument("--answers", default=None,
                        help="JSON file of {instance id: {scheme: label}} to "
                             "annotate with, instead of picking first options")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    # --grade reads two things the other modes do not need, and without either
    # it would report a clean run having graded nothing at all.
    if args.grade and not args.task_dir:
        print("--grade reads quality_control_results.json out of the task "
              "directory, so it needs --task-dir as well.", file=sys.stderr)
        return 2
    if args.grade and not args.config:
        print("--grade reads the gold and attention item files named in the "
              "config, so it needs --config as well.", file=sys.stderr)
        return 2

    try:
        import playwright  # noqa: F401
    except ImportError:
        print("Playwright is not installed. Install it with:\n"
              "  pip install 'potato-annotation[preview]'\n"
              "  playwright install chromium", file=sys.stderr)
        return 2

    report = walk(args.url, args.task_dir, args.shots, args.max_steps,
                  args.config, grade=args.grade, answers_path=args.answers)

    if args.as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Walked as {report['user']}, {len(report['steps'])} pages")
        for step in report["steps"]:
            item = f" item {step['instance_id']}" if step["instance_id"] else ""
            print(f"  {step['step']:>2}. {step['title']}{item} "
                  f"({step['answered']} answered)")
        print(f"\nReached the end: {report.get('reached_end')}")
        if "stored_instances" in report:
            print(f"Stored in user_state.json: {report['stored_instances']} instances")
        if "restored_on_revisit" in report:
            print(f"Restored on revisit: {report['restored_on_revisit']} selections")
        if report.get("value_mismatches"):
            print(f"Stored as a different value than submitted: "
                  f"{len(report['value_mismatches'])}")
        qc = report.get("quality_control")
        if qc:
            print(f"\nGraded, from {qc['results_file']}:")
            for record in qc["gold"]:
                print(f"  gold  {record['item_id']}: "
                      f"{'correct' if record['correct'] else 'WRONG'}")
            for record in qc["attention"]:
                if record["too_fast"]:
                    verdict = (f"too fast "
                               f"({record['response_time_seconds']}s) -- "
                               f"the walker's speed, not the item")
                else:
                    verdict = "passed" if record["passed"] else "FAILED"
                print(f"  check {record['item_id']}: {verdict}")
            if qc["never_served"]:
                print(f"  never served, so ungraded: "
                      f"{', '.join(qc['never_served'])}")
            if not qc["gold"] and not qc["attention"]:
                print("  nothing was graded")
        for text in report["console_errors"]:
            print(f"  console: {text}")
        if report["problems"]:
            print("\nProblems:")
            for problem in report["problems"]:
                print(f"  - {problem}")
        else:
            print("\nNothing to report.")

    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
