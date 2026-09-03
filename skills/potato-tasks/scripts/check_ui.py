#!/usr/bin/env python3
"""
Check what a running Potato task actually looks like, page by page.

    python check_ui.py --url http://localhost:8000 --config config.yaml
    python check_ui.py --url http://localhost:8000 --config config.yaml --shots ui/
    python check_ui.py --url http://localhost:8000 --config config.yaml --json
    python check_ui.py --config config.yaml --phase poststudy      # one phase page

`walk_task.py` proves the machinery works -- that answers reach the server. This
proves the interface is usable -- that every scheme a config declares actually
appears, that an annotator does not have to scroll past three screens to find the
Next button, that an image widget has a bitmap in it, and that two schemes are not
fighting over the same keyboard shortcut.

Those are the failures `potato validate` and `potato preview --screenshot` cannot
see. Validation never opens a scheme entry. The screenshot is 1280x900 of a page
that is often much taller, so a question below the fold is invisible to it in the
literal sense, and a canvas that never loaded looks exactly like one that did.

What it reports per page:

  * schemes declared in the config that are not detectable in the DOM
  * schemes, and the Next button, that sit below the fold
  * how many screens tall the page is
  * image, canvas, video and audio widgets that came up empty
  * choice widgets whose candidate list rendered empty behind live buttons
  * schemes writing to a hidden input that nothing collects, so the answer looks
    stored on the page and never reaches `user_state.json`
  * anything wider than the viewport, which makes the page scroll sideways
  * console errors and failed requests, minus Potato's known phase-page noise

Detection of a rendered scheme relies on the `data-schema-name` marker on the
form Potato generates. Most scheme types emit it and some do not, so a scheme
reported as undetected is a prompt to look at the screenshot rather than a
finding on its own. Everything else here is measured from the live layout.

Walking from the landing page reaches whatever the first `--max-steps` pages
are, which on a real corpus is all annotation and never the survey at the end.
`--phase poststudy` measures that page directly instead: it boots a throwaway
debug server from the config and lands on the phase route, the same way
`potato preview --phase` does. `--phase` and `--url` are separate modes -- one
walks the running task, the other measures one page of a fresh one.

Exits non-zero when it found something worth looking at.

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

#: Anything taller than this many viewports is a page an annotator scrolls
#: through for every single item, which is where per-item time goes.
TALL_PAGE_SCREENS = 2.5


def _fresh_user() -> str:
    tag = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"uicheck-{tag}@example.com"


def _load_config(path: str) -> dict:
    import yaml
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _declared_schemes(config: dict) -> list:
    """Every scheme the config declares, top-level and inside any phase.

    Phase-level `annotation_schemes` replace the top-level list rather than
    adding to it, so a task can legitimately declare a name that never appears
    on the annotation page. Both are collected and the page each was found under
    is kept, so the report can say where to look.
    """
    out = []
    for scheme in config.get("annotation_schemes") or []:
        if isinstance(scheme, dict) and scheme.get("name"):
            out.append({"name": scheme["name"],
                        "type": scheme.get("annotation_type"),
                        "where": "annotation_schemes"})
    phases = config.get("phases") or {}
    if isinstance(phases, dict):
        for phase_name, phase in phases.items():
            if not isinstance(phase, dict):
                continue
            for scheme in phase.get("annotation_schemes") or []:
                if isinstance(scheme, dict) and scheme.get("name"):
                    out.append({"name": scheme["name"],
                                "type": scheme.get("annotation_type"),
                                "where": f"phases.{phase_name}"})
    return out


def _keybinding_conflicts(config: dict) -> list:
    """Two schemes claiming the same shortcut. Only the first one works.

    Nothing reports this at boot: the config validates, the page renders, and
    the second scheme's key is simply dead. `potato preview` prints it, which is
    the only other place it surfaces.
    """
    claimed: dict = {}
    for scheme in config.get("annotation_schemes") or []:
        if not isinstance(scheme, dict):
            continue
        name = scheme.get("name")
        for label in scheme.get("labels") or []:
            if isinstance(label, dict) and label.get("key_value"):
                claimed.setdefault(str(label["key_value"]), []).append(
                    f"{name}:{label.get('name', label.get('label', '?'))}")
    return [{"key": key, "claimed_by": owners}
            for key, owners in sorted(claimed.items()) if len(owners) > 1]


#: Measured in the page rather than inferred from the screenshot. Returns
#: geometry for every annotation form, the advance button, and every media
#: widget that can come up empty.
INSPECT_JS = r"""
() => {
  const vh = window.innerHeight;
  const docEl = document.documentElement;
  // `.annotation-form` rather than `form.annotation-form`: `coreference` and
  // `span_link` render a `div` carrying that class and an `id` but no
  // `data-schema-name`, so a form-tag selector missed both and reported them as
  // declared-but-not-detected on every page of a task where they were working.
  const forms = [...document.querySelectorAll(
      '.annotation-form, [data-schema-name]')].map(el => {
    const r = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return {
      name: el.getAttribute('data-schema-name') || el.id || null,
      type: el.getAttribute('data-annotation-type') || null,
      top: Math.round(r.top + window.scrollY),
      height: Math.round(r.height),
      hidden: style.display === 'none' || style.visibility === 'hidden'
              || r.width === 0 && r.height === 0,
    };
  });

  let advance = null;
  for (const sel of ['#next-btn', 'input[type=submit]']) {
    const el = document.querySelector(sel);
    if (el) { const r = el.getBoundingClientRect();
              advance = {selector: sel, top: Math.round(r.top + window.scrollY)};
              break; }
  }
  if (!advance) {
    for (const el of document.querySelectorAll('button')) {
      if (/next|submit|continue/i.test(el.textContent || '')) {
        const r = el.getBoundingClientRect();
        advance = {selector: 'button:' + el.textContent.trim().slice(0, 20),
                   top: Math.round(r.top + window.scrollY)};
        break;
      }
    }
  }

  const images = [...document.querySelectorAll('img')]
    .filter(el => el.offsetParent !== null)
    .map(el => ({src: (el.currentSrc || el.src || '').slice(-90),
                 empty: !el.complete || el.naturalWidth === 0}));

  // Every canvas widget stacks layers in one container, and most of the layers
  // are blank when the widget is working. Fabric puts the bitmap on
  // `.lower-canvas` and leaves `.upper-canvas` empty until a shape is drawn;
  // Peaks.js stacks five unclassed Konva layers per waveform and paints one of
  // them. Measuring layers one at a time reported "2 canvas widgets painted
  // nothing" on a healthy image task and "4" on a healthy audio task, and no
  // class filter fixes the second, because Konva's layers carry no class at
  // all. Group by container instead: one painted layer is a painted widget.
  const stacks = new Map();
  [...document.querySelectorAll('canvas')]
    .filter(el => el.offsetParent !== null)
    .forEach(el => {
      const box = el.parentElement || el;
      if (!stacks.has(box)) stacks.set(box, []);
      stacks.get(box).push(el);
    });
  const canvases = [...stacks.entries()].map(([box, layers]) => {
    let blank = true, read = 0;
    for (const el of layers) {
      try {
        const ctx = el.getContext('2d');
        if (ctx && el.width && el.height) {
          read++;
          const data = ctx.getImageData(0, 0, el.width, el.height).data;
          if (data.some(v => v !== 0)) { blank = false; break; }
        }
      } catch (e) { blank = null; break; }   // tainted by a cross-origin bitmap
    }
    if (blank === true && !read) blank = null;
    return {id: box.id || (typeof box.className === 'string'
                           ? box.className.trim().split(/\s+/)[0] : null) || null,
            layers: layers.length, blank};
  });

  // A geometry scheme has no way to get a bitmap except the `<img>` that
  // `instance_display` renders, so one of these on a page with no visible image
  // is broken whatever the pixels say. This is the check that catches a training
  // page, where `instance_display` is not rendered at all: there is no `<img>`,
  // the widget paints its own error text onto the canvas, and both the blank
  // test and the `.error` test below come back clean.
  const geometry_schemes = [...document.querySelectorAll(
      '.image-annotation-container[data-schema], form.image-annotation[data-schema-name]')]
    .map(el => el.getAttribute('data-schema')
               || el.getAttribute('data-schema-name') || 'unnamed');

  // Blank pixels are also the wrong test for a failed load: Potato paints
  // "Failed to load image" onto the canvas, so a scheme pointed at a URL that
  // 404s reads as painted. This is the widget's own error state, and it is the
  // only reliable signal that the bitmap never arrived.
  const canvas_errors = [...document.querySelectorAll(
      '.image-annotation-container.error, .annotation-canvas-container.error')]
    .map(el => el.getAttribute('data-schema') || el.id || 'unnamed');

  // The tile widgets have their own version of a blank canvas: `bws`, `pairwise`,
  // `ranking`, `conjoint` and the rest render their candidates into a container
  // the server fills, and when the data behind it is missing the container comes
  // up empty while the buttons still say A, B, C, D. Nothing else notices -- the
  // scheme is detected, the form has height, `--strict` passes -- so an annotator
  // is asked to choose between four blanks. `bws` reaches this state by simply
  // having no `bws_config`, which is the normal way to write the config wrong.
  const empty_choices = [...document.querySelectorAll(
      '[class*="items-display"], [class*="items-list"], [class*="-items"], '
      + '[class*="-candidates"], [class*="-profiles"]')]
    .filter(el => el.offsetParent !== null
                  && !(el.innerText || '').trim()
                  && !el.querySelector('img, canvas, video, audio, input, select')
                  // An empty drop target is where the answer goes, not a missing
                  // candidate list: `card_sort` opens with every group empty and
                  // all its cards in the source column.
                  && !el.hasAttribute('ondrop') && !el.hasAttribute('ondragover')
                  && !el.closest('[data-annotation-type="card_sort"]'))
    .map(el => {
      const form = el.closest('form.annotation-form, [data-schema-name]');
      return (form && form.getAttribute('data-schema-name'))
             || (typeof el.className === 'string'
                 ? el.className.trim().split(/\s+/)[0] : 'unnamed');
    });

  // A widget whose answers nothing collects. Every scheme that answers through a
  // hidden input has to mark it `annotation-input`, because that is the class
  // syncAnnotationsFromDOM reads; a hidden `<scheme>:::<field>` input without it
  // is written by the widget, shown back to the annotator, and never sent. The
  // page looks completely normal, and `user_state.json` stays empty for that
  // scheme however long the study runs. `tree_annotation` is in this state on
  // 2.8.2-10: its two inputs sit outside any form and carry no class at all.
  // Four schemes are exempt because they persist through their own endpoints
  // into their own stores -- `instance_id_to_span_to_value`,
  // `..._to_link_to_value`, `..._to_event_to_value` -- and their hidden input is
  // a mirror rather than the thing that is read.
  const SIDE_STORED = ['span', 'coreference', 'span_link', 'event_annotation',
                       'multi_document_event'];
  const uncollected = [...document.querySelectorAll('input[type="hidden"]')]
    .filter(el => (el.name || '').includes(':::')
                  && !el.classList.contains('annotation-input'))
    .map(el => {
      const form = el.closest('.annotation-form, [data-schema-name]');
      const type = form ? (form.getAttribute('data-annotation-type') || '') : '';
      if (SIDE_STORED.includes(type)) return null;
      return (form && (form.getAttribute('data-schema-name') || form.id))
             || (el.name || '').split(':::')[0];
    })
    .filter(Boolean);

  const media = [...document.querySelectorAll('video, audio')].map(el => ({
    tag: el.tagName.toLowerCase(),
    src: (el.currentSrc || el.getAttribute('src') || '').slice(-90),
    empty: !(el.currentSrc || el.getAttribute('src')),
  }));

  const wide = [...document.querySelectorAll('body *')]
    .filter(el => el.getBoundingClientRect().width > docEl.clientWidth + 4)
    .slice(0, 5)
    .map(el => (el.tagName.toLowerCase()
                + (el.id ? '#' + el.id : '')
                + (el.className && typeof el.className === 'string'
                   ? '.' + el.className.trim().split(/\s+/)[0] : '')));

  return {
    viewport_height: vh,
    page_height: Math.round(docEl.scrollHeight),
    // `#instance_id` is on every page including the phase pages; only the
    // annotation page fills in its value. Same test walk_task.py uses.
    is_annotation_page: !!(document.querySelector('#instance_id') || {}).value,
    overflows_sideways: docEl.scrollWidth > docEl.clientWidth + 4,
    wide_elements: [...new Set(wide)],
    forms, advance, images, canvases, canvas_errors, geometry_schemes,
    empty_choices, uncollected, media,
  };
}
"""


def _settle(page) -> None:
    """Potato re-renders in place, so there is often no navigation to wait for:
    `networkidle` returns immediately while the page is still being replaced."""
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(1200)


def _advance(page) -> bool:
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


def _answer_visible(page) -> None:
    """Answer enough to move on. Unlike walk_task this is not the point -- it is
    only how the checker reaches the next page."""
    seen = {el.get_attribute("name")
            for el in page.query_selector_all("input:checked")}
    for element in page.query_selector_all("input[type=radio], input[type=checkbox]"):
        name = element.get_attribute("name") or ""
        if name in seen or name.startswith("span_label:::"):
            continue
        if not element.is_visible():
            continue
        seen.add(name)
        try:
            element.check(force=True)
        except Exception:
            pass
    for selector in ("textarea", "input[type=text]"):
        for element in page.query_selector_all(selector):
            name = element.get_attribute("name") or ""
            if name in ("email", "pass") or not element.is_visible():
                continue
            if (element.input_value() or "").strip():
                continue
            try:
                element.fill("Checked by check_ui.py.")
            except Exception:
                pass


def _is_finished(page) -> bool:
    body = (page.inner_text("body") or "").lower()
    return any(phrase in body for phrase in
               ("thank you", "you are done", "study complete", "no more instances"))


def _page_problems(measured: dict, declared: list) -> list:
    """Turn one page's measurements into things a person should act on."""
    problems = []
    viewport = measured["viewport_height"] or 1
    height = measured["page_height"]

    rendered = {form["name"] for form in measured["forms"] if form["name"]}
    # Only on the annotation page. A `consent` or `instructions` phase renders
    # its own schemes from a page file and none of the top-level ones, so
    # comparing there reports every scheme in the config as missing.
    if declared and measured.get("is_annotation_page"):
        missing = [s["name"] for s in declared
                   if s["name"] not in rendered and s["where"] == "annotation_schemes"]
        if missing:
            problems.append(
                f"declared but not detected: {', '.join(missing)}. Either the "
                f"scheme did not render, it is behind display_logic that the "
                f"initial state does not satisfy, or its type does not emit the "
                f"marker this checks. Look at the screenshot.")

    below = [f"{form['name'] or form['type'] or '?'} (at {form['top']}px)"
             for form in measured["forms"]
             if not form["hidden"] and form["top"] > viewport]
    if below:
        cost = ("The annotator scrolls to find these on every item."
                if measured.get("is_annotation_page")
                else "The annotator has to scroll to find these.")
        problems.append(
            f"below the fold at {viewport}px: {', '.join(below)}. {cost}")

    advance = measured.get("advance")
    if advance and advance["top"] > viewport:
        problems.append(
            f"the advance button is at {advance['top']}px, below a {viewport}px "
            f"viewport. Nothing tells an annotator it is there.")

    if height > viewport * TALL_PAGE_SCREENS:
        fix = ("Consider `instance_display.layout` to put short questions side "
               "by side." if measured.get("is_annotation_page")
               else "Split it across two pages, or pick a shorter instrument.")
        problems.append(
            f"the page is {height / viewport:.1f} screens tall. {fix}")

    if measured["overflows_sideways"]:
        problems.append(
            f"the page scrolls sideways. Widest: "
            f"{', '.join(measured['wide_elements']) or 'unknown'}.")

    empty_images = [img["src"] for img in measured["images"] if img["empty"]]
    if empty_images:
        problems.append(
            f"{len(empty_images)} image(s) rendered empty: "
            f"{', '.join(empty_images[:3])}. Check `media_directory` and the "
            f"scheme's own source field.")

    blank_choices = sorted(set(measured.get("empty_choices") or []))
    if blank_choices:
        problems.append(
            f"{', '.join(blank_choices)} renders its choices into an empty "
            f"container: the buttons are there and there is nothing on them. "
            f"For `bws` this is almost always a missing top-level `bws_config`, "
            f"which is what generates the tuples -- the scheme does not read "
            f"candidates off the item. For the others, the field named by "
            f"`items_key` is missing from the data.")

    uncollected = sorted(set(measured.get("uncollected") or []))
    if uncollected:
        problems.append(
            f"{', '.join(uncollected)} writes its answer to a hidden input that "
            f"carries no `annotation-input` class, so nothing collects it. The "
            f"widget will look like it works and `user_state.json` will hold "
            f"nothing for this scheme. Drive it once and read the file before "
            f"you use it in a study.")

    geometry = sorted(set(measured.get("geometry_schemes") or []))
    if geometry and not [img for img in measured["images"] if not img["empty"]]:
        problems.append(
            f"{', '.join(geometry)} is a geometry scheme on a page with no "
            f"image on it. The canvas takes its bitmap from the `<img>` that "
            f"`instance_display` renders, so there is nothing for it to draw. "
            f"On a phase page -- training included -- that is expected and "
            f"unfixable: phase pages do not render `instance_display`. On an "
            f"annotation page it means the display field is missing or its key "
            f"does not match the scheme's `source_field`.")

    failed = measured.get("canvas_errors") or []
    if failed:
        problems.append(
            f"the image never loaded into {', '.join(sorted(set(failed)))}. The "
            f"canvas takes its bitmap from the `<img>` that instance_display "
            f"renders, so on a phase page -- training included -- there is no "
            f"display field to take it from and the widget falls back to the "
            f"item text. The console error names the URL it asked for.")

    blank = [c for c in measured["canvases"] if c["blank"] is True]
    if blank and not failed:
        problems.append(
            f"{len(blank)} canvas widget(s) painted nothing: "
            f"{', '.join(sorted(c['id'] or 'unnamed' for c in blank))}. On a "
            f"geometry scheme this is usually a missing `instance_display` "
            f"field, since the canvas takes its bitmap from the `<img>` that "
            f"renders. On a waveform it is usually the audio: check the "
            f"`<audio>` source resolved and the file decodes in Chromium.")

    empty_media = [m["tag"] for m in measured["media"] if m["empty"]]
    if empty_media:
        problems.append(
            f"{len(empty_media)} {'/'.join(sorted(set(empty_media)))} element(s) "
            f"have no source resolved.")

    return problems


def _record(report: dict, page, measured: dict, declared: list,
            shots: str | None, step: int, label: str | None = None) -> None:
    """One page's measurements, appended to the report. Shared by both modes."""
    if shots:
        os.makedirs(shots, exist_ok=True)
        name = label or f"{step:02d}"
        page.screenshot(path=os.path.join(shots, f"{name}.png"), full_page=True)

    report["pages"].append({
        "step": step,
        "label": label,
        "title": (page.title() or "")[:80],
        "page_height": measured["page_height"],
        "screens": round(measured["page_height"]
                         / (measured["viewport_height"] or 1), 1),
        "schemes_detected": sorted(
            {f["name"] for f in measured["forms"] if f["name"]}),
        "problems": _page_problems(measured, declared),
    })


def check_phases(phases: list, config_path: str, shots: str | None) -> dict:
    """Measure named phase pages directly, one throwaway server each.

    Walking from the landing page cannot reach a phase that sits after
    annotation: the annotator only gets there once the assignment is finished,
    which on a real corpus is hundreds of pages away. Potato already solves this
    for its own screenshots -- `potato start --debug --debug-phase X` parks a
    user in phase X -- so this borrows the same two helpers rather than
    reimplementing them.

    `prestudy` is not on the list. It is a phase the *server* has and the
    preview route table does not, and it comes before annotation anyway, so a
    plain `--url` walk reaches it.
    """
    from playwright.sync_api import sync_playwright

    try:
        from potato.preview_render import (
            PHASE_ROUTES, PHASES, find_free_port, start_server, stop_server,
        )
    except ImportError:
        print("--phase needs Potato importable in this environment:\n"
              "  pip install potato-annotation", file=sys.stderr)
        raise SystemExit(2)

    unknown = [p for p in phases if p not in PHASES]
    if unknown:
        raise SystemExit(
            f"--phase must be one of {', '.join(PHASES)}; got "
            f"{', '.join(unknown)}. `prestudy` is not renderable this way -- "
            f"it precedes annotation, so walk it with --url instead.")

    config = _load_config(config_path)
    declared = _declared_schemes(config)
    console: list = []
    where = ["start"]

    report = {
        "url": f"(debug servers from {config_path})",
        "user": "debug_user",
        "viewport": {"width": 1280, "height": 900},
        "declared_schemes": len(declared),
        "keybinding_conflicts": _keybinding_conflicts(config),
        "pages": [],
        "console_errors": console,
        "problems": [],
    }

    def note_error(text: str):
        if "Failed to load resource" in text:
            return
        if not any(noise in text for noise in KNOWN_NOISE):
            console.append(f"[{where[0]}] {text[:200]}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.on("console",
                lambda m: note_error(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: note_error(str(e)))

        for step, phase in enumerate(phases):
            where[0] = phase
            port = find_free_port()
            proc = start_server(config_path, port, phase=phase)
            if proc is None:
                report["problems"].append(
                    f"{phase}: the server did not start. Run "
                    f"`potato validate --strict {config_path}` and read the "
                    f"boot log -- a phase that fails to load is dropped rather "
                    f"than fatal, so this can be the phase itself.")
                continue
            try:
                page.goto(f"http://127.0.0.1:{port}{PHASE_ROUTES[phase]}")
                _settle(page)
                try:
                    measured = page.evaluate(INSPECT_JS)
                except Exception as exc:
                    report["problems"].append(
                        f"{phase}: could not measure ({exc})")
                    continue
                _record(report, page, measured, declared, shots, step,
                        label=phase)
            finally:
                stop_server(proc)

    if report["keybinding_conflicts"]:
        report["problems"].append(
            f"{len(report['keybinding_conflicts'])} keyboard shortcut(s) claimed "
            f"by more than one label. Only the first works; the rest are dead "
            f"with no warning anywhere.")
    report["pages_with_problems"] = sum(
        1 for p in report["pages"] if p["problems"])
    return report


def check(url: str, config_path: str | None, shots: str | None,
          max_steps: int) -> dict:
    from playwright.sync_api import sync_playwright

    config = _load_config(config_path) if config_path else {}
    declared = _declared_schemes(config) if config else []
    user = _fresh_user()
    console: list = []
    where = ["register"]

    report = {
        "url": url,
        "user": user,
        "viewport": {"width": 1280, "height": 900},
        "declared_schemes": len(declared),
        "keybinding_conflicts": _keybinding_conflicts(config) if config else [],
        "pages": [],
        "console_errors": console,
        "problems": [],
    }

    def note_error(text: str):
        if "Failed to load resource" in text:
            return
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
        # 1280x900 on purpose: the size `potato preview --screenshot` uses, so
        # "below the fold" here means below the fold there.
        page = browser.new_context(
            viewport={"width": 1280, "height": 900}).new_page()
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
                element.fill("uicheck-pw")
        button = page.query_selector("form[action='/register'] button[type=submit]")
        if button:
            button.click()
            _settle(page)

        for step in range(max_steps):
            where[0] = f"page{step}"
            page.wait_for_timeout(400)

            try:
                measured = page.evaluate(INSPECT_JS)
            except Exception as exc:
                report["problems"].append(f"page {step}: could not measure ({exc})")
                break

            _record(report, page, measured, declared, shots, step)

            if _is_finished(page):
                break
            _answer_visible(page)
            page.wait_for_timeout(300)
            if not _advance(page):
                break

    if report["keybinding_conflicts"]:
        report["problems"].append(
            f"{len(report['keybinding_conflicts'])} keyboard shortcut(s) claimed "
            f"by more than one label. Only the first works; the rest are dead "
            f"with no warning anywhere.")
    report["pages_with_problems"] = sum(
        1 for p in report["pages"] if p["problems"])
    return report


def _collapse(pages: list) -> list:
    """Group consecutive pages whose measurements and findings are the same."""
    groups: list = []
    for page in pages:
        key = (page["label"], page["screens"],
               tuple(page["schemes_detected"]), tuple(page["problems"]))
        if groups and groups[-1][0] == key:
            groups[-1][1].append(page)
        else:
            groups.append((key, [page]))
    return [members for _, members in groups]


def render(report: dict) -> str:
    lines = [f"UI check of {report['url']}",
             f"  viewport {report['viewport']['width']}x{report['viewport']['height']}"
             f", {len(report['pages'])} page(s) reached"
             f", {report['declared_schemes']} scheme(s) declared", ""]

    for conflict in report["keybinding_conflicts"]:
        lines.append(f"KEYBINDING  '{conflict['key']}' claimed by "
                     f"{', '.join(conflict['claimed_by'])}")
    if report["keybinding_conflicts"]:
        lines.append("")

    # Consecutive pages that measured identically get one stanza. A walk over a
    # real corpus is a dozen annotation pages with the same layout and the same
    # finding, and printing it a dozen times buries the page that differs.
    for group in _collapse(report["pages"]):
        first, last = group[0], group[-1]
        span = (f"page {first['step']:2d}" if len(group) == 1
                else f"pages {first['step']}-{last['step']}")
        where = first["label"] or first["title"] or "(untitled)"
        lines.append(f"{span}  {where}  [{first['screens']} screens]"
                     + ("" if len(group) == 1 else f"  x{len(group)}, identical"))
        if first["schemes_detected"]:
            lines.append(f"    schemes: {', '.join(first['schemes_detected'])}")
        for problem in first["problems"]:
            lines.append(f"    - {problem}")
        if not first["problems"]:
            lines.append("    ok")
        lines.append("")

    for problem in report["problems"]:
        lines.append(f"PROBLEM  {problem}")
    if report["console_errors"]:
        lines.append("")
        lines.append(f"{len(report['console_errors'])} console error(s):")
        lines += [f"    {e}" for e in report["console_errors"][:15]]

    total = report["pages_with_problems"]
    lines.append("")
    lines.append(f"{total} of {len(report['pages'])} page(s) have something to look at."
                 if total else "Nothing to report on any page reached.")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8000",
                        help="a task that is already running")
    parser.add_argument("--config", default=None,
                        help="config.yaml, so declared schemes and keybindings "
                             "can be compared against what rendered")
    parser.add_argument("--shots", default=None,
                        help="directory for one full-page PNG per page")
    parser.add_argument("--max-steps", type=int, default=12,
                        help="how many pages to walk forward from the landing "
                             "page (default 12). Raise it to reach a phase that "
                             "sits behind a long assignment, or use --phase")
    parser.add_argument("--phase", action="append", metavar="NAME",
                        help="measure this phase page directly instead of "
                             "walking, on a throwaway debug server. Repeatable. "
                             "Needs --config. One of consent, instructions, "
                             "training, annotation, poststudy")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    if args.phase and not args.config:
        parser.error("--phase needs --config: the throwaway server is booted "
                     "from it.")

    try:
        if args.phase:
            report = check_phases(args.phase, args.config, args.shots)
        else:
            report = check(args.url, args.config, args.shots, args.max_steps)
    except Exception as exc:                      # noqa: BLE001
        if "playwright" in str(exc).lower() or isinstance(exc, ImportError):
            print("Playwright is needed for this check:\n"
                  "  pip install 'potato-annotation[preview]'\n"
                  "  playwright install chromium", file=sys.stderr)
            return 2
        raise

    print(json.dumps(report, indent=2) if args.as_json else render(report))
    return 1 if (report["pages_with_problems"] or report["problems"]) else 0


if __name__ == "__main__":
    sys.exit(main())
