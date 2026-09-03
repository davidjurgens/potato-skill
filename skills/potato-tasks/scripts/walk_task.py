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

It is deliberately generic: it picks the first available option for every
question rather than annotating meaningfully. It proves the machinery works,
not that the labels make sense.

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


def _schemes_holding_nothing(page) -> list:
    """Which schemes on this page have no answer in them at all."""
    try:
        return page.evaluate(EMPTY_SCHEMES_JS) or []
    except Exception:
        return []


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
         config_path: str | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    user = _fresh_user()
    console: list = []
    where = ["register"]
    training = _training_answers(config_path) if config_path else {}
    report = {"user": user, "steps": [], "console_errors": console, "problems": [],
              "training_items_known": len(training)}

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
            instance = page.query_selector("#instance_id")
            instance_id = instance.get_attribute("value") if instance else None
            if instance_id and first_instance is None:
                first_instance = instance_id

            if shots:
                os.makedirs(shots, exist_ok=True)
                page.wait_for_timeout(400)
                page.screenshot(path=os.path.join(shots, f"{step:02d}.png"),
                                full_page=True)

            answered = 0
            if instance_id and instance_id in training:
                # The graded answer first: _answer_everything skips groups that
                # already have a selection, so it cannot overwrite it.
                answered += _answer_as_told(page, training[instance_id])
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
                if recent[0] in training:
                    hint = (f"Its model answer is {training[recent[0]]}. The "
                            f"walker submitted that and training still refused "
                            f"it, so the labels in training.data_file do not "
                            f"match the labels in annotation_schemes, or a "
                            f"required scheme on the page has no model answer.")
                elif training:
                    hint = (f"There is no model answer for {recent[0]} in "
                            f"training.data_file. If this is a practice item, "
                            f"add one; the walker cannot guess a graded answer.")
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
                if empty:
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
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    try:
        import playwright  # noqa: F401
    except ImportError:
        print("Playwright is not installed. Install it with:\n"
              "  pip install 'potato-annotation[preview]'\n"
              "  playwright install chromium", file=sys.stderr)
        return 2

    report = walk(args.url, args.task_dir, args.shots, args.max_steps, args.config)

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
