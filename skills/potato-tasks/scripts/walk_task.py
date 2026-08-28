#!/usr/bin/env python3
"""
Walk a running Potato task the way an annotator would, and report where it stops.

    python walk_task.py --url http://localhost:8000
    python walk_task.py --url http://localhost:8000 --task-dir . --shots out/

Registers a fresh account, answers whatever each page asks, advances until the
study ends, navigates back to an earlier item to check the answers were stored,
and -- given `--task-dir` -- reads `annotation_output/<user>/user_state.json` to
confirm the server has them rather than the browser.

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


def _answer_as_told(page, answers: dict) -> int:
    """Set exactly the answers given, by scheme name and label value."""
    touched = 0
    for name, value in answers.items():
        selector = f'input[name="{name}"][value="{value}"]'
        locator = page.locator(selector).first
        try:
            if locator.count():
                locator.check(force=True)
                touched += 1
        except Exception:
            pass
    return touched


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
        element.get_attribute("name")
        for element in page.query_selector_all("input:checked")
    }

    seen_groups = set(answered_groups)
    for element in page.query_selector_all("input[type=radio]"):
        name = element.get_attribute("name")
        if not name or name in seen_groups or not element.is_visible():
            continue
        seen_groups.add(name)
        try:
            element.check(force=True)
            touched += 1
        except Exception:
            pass

    for element in page.query_selector_all("input[type=checkbox]"):
        name = element.get_attribute("name") or ""
        if name.startswith("span_label:::") or not element.is_visible():
            continue          # span chips select a label, they do not answer
        if name in seen_groups:
            continue
        seen_groups.add(name)
        try:
            element.check(force=True)
            touched += 1
        except Exception:
            pass

    for selector in ("textarea", "input[type=text]", "input[type=search]"):
        for element in page.query_selector_all(selector):
            name = element.get_attribute("name") or ""
            if not element.is_visible() or name in ("email", "pass"):
                continue
            if (element.input_value() or "").strip():
                continue
            try:
                element.fill(FILL_TEXT)
                touched += 1
            except Exception:
                pass

    return touched


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
            page.wait_for_timeout(400)
            answered += _answer_everything(page)   # conditional schemes just shown
            report["steps"].append({
                "step": step,
                "title": (page.title() or "")[:80],
                "instance_id": instance_id,
                "answered": answered,
            })

            recent = [s["instance_id"] for s in report["steps"][-4:]]
            if len(recent) == 4 and len(set(recent)) == 1 and recent[0]:
                report["problems"].append(
                    f"Stuck on item {recent[0]} for four steps. If this is the "
                    f"practice round, the answer is graded and the walker does "
                    f"not know it -- pass --config so it can read "
                    f"training.data_file. Otherwise the item will not accept an "
                    f"answer.")
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
        if first_instance:
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
        state_path = os.path.join(task_dir, "annotation_output", user, "user_state.json")
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
