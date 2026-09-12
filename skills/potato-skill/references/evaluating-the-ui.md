# Evaluating and iterating on the interface

A config that validates tells you the server will start. It tells you nothing
about whether a person can do the work. That question only has one answer:
render the page, look at it, and change something.

## The loop

```bash
potato preview config.yaml --screenshot shot-01.png
```

**Before you start: the PNG is 1280x900 of the top of one page, not the whole
page.** Half the checklist below is about things further down. Get a full-height
render by driving a browser against a running server (`running-a-task.md`), and
treat `--screenshot` as the fast smoke test rather than the visual check.

Then, in order:

1. **Read the error lines first.** Uncaught exceptions and `console.error` mean
   part of the interface never initialized. Nothing else you notice matters
   until those are gone — except the three Potato logs on every phase page
   (`/api/current_instance` 404 and two `[SpanManager]` lines), which are
   present on a healthy task.
2. **Look at the PNG.** Not the exit code. A clean exit means nothing threw.
3. **Make one change.**
4. **Re-render to a new filename** — `shot-02.png`, not the same name. You need
   the pair to see what your change did.

Keep going until the checklist below passes. Three or four rounds is normal for
anything with a custom layout.

## What to look for

Work down the list. Each line is a failure that has shipped in a real task.

**The item**

- Is it there at all? A raw file path where an image should be means no
  `instance_display`.
- Is it readable — not clipped, not scrolled off, not one line of a long
  document with no way to see the rest?
- If it is media: does the player have controls, and are they inside the frame?

**The questions**

- Is every scheme present? Count them against the config. A missing one is
  usually behind `display_logic` (see below) or failed to generate.
- Is any of them empty — a heading with no inputs under it?
- Are the labels readable, or truncated with an ellipsis?
- Do radio buttons and checkboxes actually appear? An invisible input control is
  the classic CSS collision, and the label text still renders, so the question
  looks fine at a glance.
- Do tick marks, scale points and their labels line up, or do the labels overlap
  each other at the ends?
- For a grid or matrix scheme: does it use the full width, or is it squeezed
  into a narrow column with horizontal scroll?

**The page**

- Is anything shifted right, overlapping, or overflowing its container?
- Is the Next button visible without scrolling past the fold? An annotator hits
  it several hundred times.
- Does the whole page scroll horizontally? It should not.

**The work itself**

- Count the interactions to complete one item: clicks, scrolls, keystrokes.
  Multiply by the number of items. That number is the study's cost.
- Do the schemes have keyboard shortcuts where they could?
- Is anything ordered so that the annotator has to scroll up and back down?

## The states a screenshot will not show you

The render captures the page as it loads. Four things live outside that, and
each has to be checked another way.

**Conditional schemes.** Anything behind `display_logic` is absent from the
initial render, and its absence proves nothing. Comment out the `display_logic`
block, render, look, put it back. Do this every time — the widget behind the
condition is often the whole point of the task.

**Anything that appears after an interaction.** A span highlight, a drawn box, a
playing video, an expanded section, minting a code, saving a note. Render to
confirm the control is there, then drive it if you have a browser tool.

Without one there is still more evidence than the PNG. Run the server once in
the background and read what it did:

- the startup log says which subsystems initialized and what they loaded —
  codebook labels, detected cases, how many instances got indexed
- `project.sqlite` in the task directory holds the codebook, cases, memos and
  the search index, and can be queried directly
- `annotation_output/<user>/user_state.json` shows what a scripted pass actually
  stored

That distinguishes "the feature is configured and initialized" from "the button
is on the page", which is most of the distance. Say in your handover which of
the two you established.

**Other phases.** `--phase consent`, `--phase instructions`, `--phase training`,
`--phase poststudy`. Only those four plus `annotation`: the preview CLI refuses
`prestudy` even though the server supports it as a phase.

**A phase-page render exits 1 on a healthy task.** Phase pages have no instance,
so the span layer's `/api/current_instance` 404 and two `[SpanManager]` console
errors are always reported, and `--screenshot` counts them. Judge the PNG and the
error list, not `$?`. See `phases-and-pages.md`. Each is a page an annotator sees, and the training phase
renders real schemes, so it can break in ways the annotation page does not.

Only render a phase the task actually has. `--phase X` parks an annotator in
that phase, so if the task never configures one, every route redirects toward a
page that does not exist and the render fails with a redirect loop.
`annotation_instructions` is the banner on the annotation page, not an
instructions phase — a task can have the banner and no phase.

**State across navigation.** Answers are saved and restored on a full page
reload. If you have a browser tool, annotate, click Next, click Previous, and
check the answer is still shown — visually, not just in a hidden input. Do not
test this with a page refresh: browsers restore form state across refresh on
their own, so a refresh-based check passes even when the server never stored
anything.

### Driving more than one annotator

Three things about the browser rather than about Potato, each of which looks
like a Potato bug the first time.

**Log out between annotators.** `/register` and `/auth` are no-ops while a
session exists — the server logs `User already logged in with username: X,
redirecting to annotate` and answers 200, so the second annotator's work lands
under the first one's name and the second user never appears in
`annotation_output/`. Hit `/logout` first, every time.

**Two servers on the same host share one session.** Cookies are not scoped by
port, so logging into the study on 8001 logs you out of the one on 8000. Reach
one of them on 127.0.0.1 and the other by name, and they stay separate.

**CSS transitions do not run in a background tab.** A sidebar or a modal that
slides in will report the class that opens it applied and its transform still
at the closed value, which reads exactly like a broken stylesheet. Settle it before
measuring:

```js
el.getAnimations().forEach(a => a.finish())
```

## Changing the interface

Reach for these in order. Stop at the first one that fixes it.

| Want | Use |
|---|---|
| Fields side by side rather than stacked | `instance_display.layout.direction: horizontal` |
| More or less space between fields | `instance_display.layout.gap` |
| Choices in a row rather than a column | `layout` on the scheme |
| Shortcut hints along one line | `horizontal_key_bindings: true` |
| Standing instructions at the top | `annotation_instructions` |
| Something above every item | `header_file` |
| A logo | `header_logo` |
| Colours, spacing, fonts | `base_css` |
| More room — no navbar, no jump control | `hide_navbar`, `jumping_to_id_disabled` |
| An arrangement none of the above reaches | `task_layout` |

`task_layout` is last for a reason: hand-written form HTML stops tracking
changes to the schema generators, so a scheme that gains a feature later will
not gain it here. Most requests that sound like they need it are
`instance_display.layout` plus scheme order.

With `base_css`, change what you meant to change. A rule that targets a bare
element selector will reach the navbar and the admin pages too.

## Iterating without going in circles

**One change per render.** Two changes and a difference you cannot attribute is
how a session turns into twenty screenshots and no conclusions.

**Keep the screenshots numbered.** They are the record of what you tried.

**Write down what you were fixing.** "shot-03: moved confidence above the span
so the page stops reflowing" beats three unlabelled PNGs.

**Know when to stop.** The interface is done when: no console errors, every
scheme visible and usable, nothing overlapping or clipped, the Next button
reachable without scrolling, and shortcuts on anything that can take them.
Past that you are decorating, and the researcher has opinions you do not have
access to. Hand it over and say what you would change next.

**Running the task writes to the project directory.** The first server start
creates `project.sqlite` and seeds it — for a codebook task, the labels in your
config *become* the project codebook. Change the labels afterwards and the
codebook still holds the old ones until `potato codebook config.yaml` re-syncs.
Worth knowing before you verify a config you are still editing.

**When a change does nothing**, suspect the key before the CSS. Unrecognized
config keys only warn, so a typo is silently ignored and the feature you thought
you enabled is off. Run `potato validate --strict`.

## Reporting what you saw

A handover that says "renders correctly" is not evidence. Say what you checked:

> Rendered at 1280×900. Three schemes present, one behind `display_logic`
> (verified separately by disabling the condition — screenshot `shot-04.png`).
> No console errors. Keyboard shortcuts on the yes/no question. The consent and
> instructions phases render (`shot-05`, `shot-06`).
>
> Not checked: span highlighting behaviour after a drag, and whether answers
> survive navigating away and back — neither is visible in a static render.

The second paragraph is the part that makes the first one worth reading.
