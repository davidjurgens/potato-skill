---
name: potato-tasks
description: Design, build, run, monitor and visually check Potato annotation tasks. Use when turning a research description into an annotation task, creating or editing a Potato config.yaml, choosing an annotation_type or scale, laying out the annotation interface with instance_display, setting up consent/instructions/training/survey phases, adding attention checks or gold standards, deciding how many annotators an item needs, importing existing annotations from COCO/CVAT/Label Studio or transcripts or a ConvoKit corpus, exporting annotations to CSV/COCO/CoNLL/Parquet or any other format, checking how a running study is going or why agreement is empty, changing a task after annotators have started, resetting an annotator's login, leaving a server running for a researcher, or debugging a task that will not start, renders wrong, or silently does nothing.
---

# Potato annotation tasks

A Potato task is one YAML config plus a data file. Building one is three jobs:
deciding what to ask and how, writing it down correctly, and running it until you
have watched a person get from the login screen to the end of the study. The
second job is the one with a validator behind it, which is why it is tempting to
start and stop there. It is the least likely to be where the study breaks.

Read `AGENTS.md` in the project root if it is there — it carries project
conventions on top of this.

## If you were invoked with no task described

Someone typed `/potato-tasks` and there is no brief in the conversation. Do not
start building, and do not open with "what would you like to make?" — a
researcher who has not used Potato cannot answer that usefully.

Ask for one sentence, propose a design from it, then confirm only what you had
to guess. `references/interviewing.md` is the question bank: the opening ask,
the four-line proposal, then two rounds of multiple-choice covering the
modality, the unit, the response format, annotators per item, quality control,
the export target and who gets to log in — then a third round that offers the
seven capability clusters as a menu and drills into only what gets ticked.

Two things it is emphatic about. Ask what **modality** the data is, every time:
it decides the display, the scheme family and the per-family key that says where
the media lives, and getting it wrong is silent. And do not push phases —
`consent`, `training` and `prestudy` are protocol decisions, most tasks want
none of them, and a researcher who needs one knows they need it.

The standing rule to build with stated assumptions rather than wait still holds
— it applies once the interview has something to assume *from*. With nothing at
all in context, asking four structured questions is faster for the researcher
than any guess you could make.


## Installing Potato

Most of this skill drives the `potato` command and imports Potato's registries.
Neither works if the package is not in the environment you are running commands
in.

```bash
potato --version || pip install potato-annotation
```

The browser walk in `scripts/walk_task.py` additionally needs Playwright:
`pip install 'potato-annotation[preview]' && playwright install chromium`.

## The scripts in this skill

Seven of the procedures below are scripts rather than instructions, because they
are long enough to get wrong by hand and they are what you will run repeatedly.
They live beside this file in `scripts/`.

| Script | What it does |
|---|---|
| `boot_and_check.py config.yaml -p 8000` | Boots, waits for a 200, and names every feature that is configured but loaded nothing |
| `walk_task.py --url … --config … --task-dir .` | Registers an annotator, walks the whole study, and checks the answers reached `user_state.json` |
| `estimate_effort.py config.yaml --rate 15` | Items, annotators needed, minutes each, total hours and cost |
| `find_design.py --type span --with-instructions` | Searches 440 published task designs in the Potato Showcase |
| `handover.py config.yaml --confirm` | Removes the accounts you made while testing and writes `RUNNING.md` |
| `check_ui.py --url … --config config.yaml` | Renders every page and reports schemes below the fold, empty media, empty choice tiles, answers nothing collects, keybinding conflicts and schemes that never appeared. `--phase poststudy` measures a page the walk cannot reach |
| `study_status.py --url … --task-dir .` | Progress, per-annotator pace, agreement, and what looks wrong on a **running** study |

Each takes `--help`, and `boot_and_check`, `walk_task`, `check_ui` and
`study_status` take `--json` when you want to act on the result rather than read
it.

## The loop

```bash
potato validate config.yaml --strict               # structure and unknown keys
potato preview config.yaml                         # what the form declares
potato preview config.yaml --screenshot out.png    # render one page, report browser errors
nohup potato start config.yaml -p 8000 > server.log 2>&1 &    # boot it and read the log
```

The first three return promptly. The fourth never returns — background it, poll
`curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/` for a 200, and
read `server.log`.

`potato --help` lists these under **other commands**, below the `start` flags.
Each has its own grammar, so `potato validate --help` and `potato preview --help`
are where their options are.

### Each step catches a different class of failure

| Step | Catches | Blind to |
|---|---|---|
| `validate --strict` | Missing required keys, bad types, unknown keys at 1–2 levels | Side files, phase types, anything inside a scheme entry |
| `preview` | What schemes and keybindings the config declares | Whether any of it renders |
| `preview --screenshot` | Uncaught exceptions, `console.error`, failed requests on **one** page | Everything below 900px, every conditional widget, every other phase |
| **boot + read the log** | Side-file formats, phase assembly, subsystem initialization | What it looks like |
| **drive it in a browser** | The actual study | — |

Skipping the last two is how a task ships that validates, screenshots clean, and
loses its training phase, its attention checks and a third of its items.

## Boot it early

The startup log is the real validator. It is the only thing that reports whether
the parts of the config that `validate` never opens actually worked:

```bash
grep -E "ERROR|Traceback|Loaded [0-9]+|phase|missing required" server.log
```

A healthy boot on a task with training and attention checks says
`Loaded 3 training instances` and `Loaded 2 attention check items`, and says
nothing about phases. Anything else is a feature that is configured and off.

Boot as soon as the config parses — before the interface is finished, before the
instructions are written. `running-a-task.md` has the backgrounding recipe, the
readiness check, the log-line table, and which generated files to delete after an
edit.

## Three silent failure modes

**Enabled is not running.** `attention_checks.enabled: true` with a malformed
items file logs one warning, then `Loaded 0 attention check items`, then runs the
whole study with quality control off. Check the count, not the config.

**`--strict` does not reach everything.** It checks the top level and one level
into most blocks. It does **not** check inside `phases`, `surveyflow`,
`quality_control`, `crowdsourcing`, `publish`, `automatic_assignment`, `ui`,
`ui_config`, or inside any entry of `annotation_schemes` or
`instance_display.fields`. `key_binding` instead of `key_value` validates clean
and does nothing. So does a phase `type:` that does not exist.

**The screenshot is the viewport, not the page.** `--screenshot` writes
1280×900. On a task with an instructions banner, that is the banner and half the
item — none of the questions. Advice to "look at the PNG and check the Next
button is above the fold" cannot be followed with this tool alone. Drive a
browser and screenshot `full_page=True`.

## Find out what they already have

A brief plus a data file is the common case, not the only one. Ask four things
before designing anything, because each has a command behind it and each is
expensive to discover after the config is written:

| Ask | Because |
|---|---|
| What format is the data in, and where is the media? | Transcripts and conversation corpora have their own converters |
| Do you already have annotations? | `potato import` reads fourteen formats and writes a runnable project |
| What has to come out at the end? | Twenty-nine export formats. Check the target one **before** anyone annotates |
| Who runs it after handover, and for how long? | Decides hosting, logins and the allowlist |

```bash
potato import --list-formats                      # coco, cvat, labelme, labelbox, via, …
potato transcripts interviews/ -r --dry-run       # whisper, srt, vtt, textgrid, eaf, …
potato convokit reddit-corpus-small --unit conversation --emit-config
```

`references/importing-existing-work.md` covers all three, including the one
decision that matters most: whether imported annotations are **pre-annotations**
a human corrects, or `--seed-user` work that marks the item done.

## Underspecified briefs

Read `references/asking-the-experimenter.md` before writing the config. Decide it
yourself when being wrong is cheap; ask when it is expensive, irreversible or not
yours — the unit of annotation, the annotator budget, consent wording, and
anything involving identifiable people.

Never wait on an answer. Build with stated assumptions, write the questions into
`QUESTIONS.md` alongside something that runs, and say which assumption you would
revisit first.

## Look for the feature before you build one

Potato has more built in than a config reference makes obvious. The expensive
mistake is not an invented type name — validation catches that. It is
hand-assembling something Potato already does.

`references/modes-and-subsystems.md` is the routing table from what a researcher
said to the block that does it: QDA and codebooks, solo mode, rooms,
adjudication, review workflow, sessions, pocket, active learning, judges,
crowdsourcing, publishing, telemetry. Check it before writing a scheme that
sounds like a workaround.

It opens with **the seven clusters** — material, the answer, unit, people, trust,
model help, output — which is the same map the interview offers as a menu. Run it
against the brief as a checklist: the clusters a brief never mentions are where a
researcher is most likely to be missing something they would want. Raise at most
two of them, and only where they matter; the rest goes in `QUESTIONS.md`.

The cluster researchers miss most reliably is **the answer**. They ask for
`radio` and `likert` and stop, and `soft_label`, `range_slider`,
`semantic_differential`, `constant_sum` and `confidence` never get reached for.

## Designing it

`references/designing-a-task.md` covers the seven decisions behind every task:
the unit, the questions, the response format, annotators per item, item order,
quality control, and the phases either side.

**The routing table covers the common asks and stops.** Eleven types are named
nowhere but the generated reference, so they never get reached for: `multirate`
(ten ratings on one scale, not ten `likert` schemes), `hierarchical_multiselect`
(a taxonomy, collapsed, with search), `select`, `soft_label` (a distribution
rather than a forced choice), `range_slider`, `semantic_differential`,
`conjoint`, `card_sort`, `extractive_qa`, `multi_document_event`, `code_review`.
Each has a working example and a row in `designing-a-task.md`.

Two that are easy to get wrong and expensive to discover late:

- **The response format decides the agreement metric.** Potato picks it from the
  schema kind. A 1–5 rating stored as a `radio` is scored as unordered, so
  "1 vs 2" and "1 vs 5" count the same. That is a measurement error, not a
  cosmetic one. Table in `references/assignment-and-agreement.md`.
- **`num_annotators_per_item` sets the target, `max_annotations_per_user` sets
  what one person actually sees.** Left unset the cap is the item count, so
  everyone is offered the whole corpus. Set it below that and annotators simply
  stop early, with nothing to say why. `automatic_assignment.instance_per_annotator`
  looks like the key for this and is not read at all.

## The design record and the cost

Two files next to the config, neither of which the config can hold:

- **`DESIGN.md`** — the unit of annotation and why, why each response format,
  annotators per item, what quality control is for, and a separate, explicit
  list of the choices you assumed because the brief did not say. That last paragraph is
  what makes the document worth opening.
- **`QUESTIONS.md`** — what you could not decide at all. Never wait on an
  answer; ship something that runs alongside the question.

```bash
python .claude/skills/potato-tasks/scripts/estimate_effort.py config.yaml --rate 15
```

reports how many annotators the design needs, how long each is working, total
hours and a cost. Run it before the instructions get written — it is the cheapest
place to catch a design nobody can afford.

`references/recording-decisions.md` has the `DESIGN.md` template and what moves
the estimate.

## Start from a published design

Before writing a scheme from a field list, look for one somebody already ran:

```bash
python .claude/skills/potato-tasks/scripts/find_design.py --query "stance" --with-instructions
python .claude/skills/potato-tasks/scripts/find_design.py --show text/argumentation-stance/argument-quality
```

The Potato Showcase is 440 annotation task designs, most built from a published
paper, with real label sets and real question wording — and **281 of them carry
written instructions**. None of them has a `phases` block, a consent page or a
training round, so take the questions from there and the study around them from
`worked-example.md`. `references/finding-a-design.md` covers what to change
before reusing one.

## Writing the instructions

The config has a validator behind it. The text an annotator reads does not, and
it is where most of the disagreement in a finished dataset comes from.

`references/writing-guidelines.md` covers the four surfaces annotator-facing
text can live on (the `instructions` phase, the `annotation_instructions`
banner, `annotation_codebook_url`, and the per-scheme `description`), what a
label definition has to contain to settle an argument, tie-break rules, worked
examples including the borderline ones, and iterating the guidelines from the
pilot's disagreements. `examples/advanced/long-guidelines/` is a working model
of all of it.

Two things to get right without reading further:

- **The banner is not the codebook.** `annotation_instructions` sits on every
  page, expanded by default. A long one pushes the questions below the fold on
  every item of the study. Definitions go on the instructions phase.
- **Label definitions are usually the researcher's, not yours.** Ask for their
  codebook or the paper the scheme comes from before writing any. If they have
  none, draft them, mark them as drafts, and say plainly that these are the
  sentences that decide what the dataset means.

## Building the interface

`references/building-the-ui.md` covers `instance_display`, the 24 display types,
`span_target`, keyboard shortcuts, `display_logic`, and the **form layout** —
`layout.grid` puts short questions side by side, `layout.groups` gives them
collapsible headings, and a per-scheme `layout` says how many columns each one
takes. Without a `layout` block every scheme stacks full-width in config order,
which is how a twelve-question task becomes twelve screens. The same file has
what to reach for, in order, when a page is too long.

`references/evaluating-the-ui.md` covers what to do with the rendered page. Read
it before the first screenshot.

Without `instance_display`, Potato renders `text_key` as plain text — right for
text classification, wrong for an image, a PDF, a dialogue or an agent trace.

`references/data-and-access.md` covers the other end: data files and formats,
`item_properties`, `media_directory` for local images and audio, remote and
polled sources, where output lands, and who is allowed to log in.

## Anything that is not text

`references/modalities.md` routes a medium to its display type, its scheme type
and its quirks: images and CV, video, audio and speech, dialogue and podcasts,
point clouds, robot episodes. `references/agent-traces.md` covers the agent
family — about twenty evaluation schemes, eight trace displays and sixty
examples.

Three facts that decide whether a non-text task works at all:

- **Every family has its own key for "where is my data".** `source_field` on
  image, video, audio and 3D schemes; `video_key` on `temporal_grounding`;
  `audio_key` on `speech_transcript`; `steps_key` on the whole agent family;
  `image_key` on `table_grid`. The wrong one gives an empty widget, a clean
  `--strict`, and a silent log.
- **A geometry scheme does not fetch its own media.** The canvas takes its
  bitmap from the `<img>` that `instance_display` renders, so a config without
  the display field comes up blank.
- **`--screenshot` cannot verify any of this.** A canvas that never loaded and
  one that loaded look identical in a PNG. Boot it, draw one box, and read
  `user_state.json`.

## The pages either side of annotation

`references/phases-and-pages.md`. Consent, instructions, training and post-study
surveys are the half of a study that `validate` cannot see at all: `phases` and
`surveyflow` have no documented sub-keys and no validation.

There are exactly six phase types (`consent`, `instructions`,
`training`, `annotation`, `poststudy`, `prestudy`); every non-annotation phase
needs a `file:` pointing at a JSONL of annotation schemes, one per line; prose
goes in a `pure_display` scheme; and a phase named in `order` but not defined is
skipped with a warning.

## Quality control

`references/quality-control.md` has the file formats for training, attention
checks and gold standards, none of which are documented anywhere else:

- training data: an **object** with `training_instances`; each needs `id`,
  `text`, `correct_answers`
- attention items: an array; each needs `id`, `expected_answer`
- gold items: an array; each needs `gold_label`

## Start from something that runs

`references/worked-example.md` is a complete study skeleton — consent,
instructions, a practice round with model answers, attention checks, the
annotation itself and a closing survey — with every side-file format filled in.
It validates under `--strict` and boots clean. Copy it and replace the labels
and prose.

Potato also ships 214 example projects, all checked in CI:

```python
from potato.server_utils.examples_manifest import search_examples
search_examples(annotation_type="span", display_type="image")
search_examples(config_key="gold_standards")
search_examples(query="dialogue")
```

They are the better starting point for one unusual scheme or display type. They
are single-purpose demos, so none of them shows a whole workflow.

## Picking an annotation type

There are 61. `references/annotation-types.md` has all of them with fields and a
worked example lifted from a config that really runs.

```python
from potato.server_utils.schema_examples import example_scheme_for
example_scheme_for("bws")
```

Never invent a type name. `sentiment`, `classification` and `qa` are not types.

## Config keys

`references/config-keys.md` lists the 157 documented **top-level** keys.
`references/config-keys-nested.md` lists the 320 documented **sub-keys** — the
level where features are actually configured, and the level the generated pack
drops. It also lists the 25 blocks whose sub-keys `--strict` does not check at
all, where a typo is silent.

```python
from potato.server_utils.config_key_docs import get_key_doc
get_key_doc("attention_checks.frequency")
```

## Interrogating the software

Roughly forty config blocks take an object and document nothing about its
contents, including `training`, `phases`, `surveyflow`, `quality_control` and
`adjudication`. Guessing key names one at a time is slow, and a wrong guess is
usually silent.

`references/interrogating-potato.md` has the four methods that recovered every
undocumented format in this pack: batch candidate keys through `--strict` and
read what it rejects, provoke type errors to learn the shape, delta-debug a side
file against the boot log, and provoke the errors that enumerate valid values.
It also has the one trap — an *ignored* key proves nothing, because validation
stops two levels down.

## Checking it

**Look at the PNG.** A clean exit means nothing threw, not that the interface is
usable — and `preview --phase consent --screenshot` **exits 1 on a task that is
completely fine**, because Potato's phase pages log four harmless 404s that get
counted as errors. Judge the PNG and the error list, not `$?`. The list is in
`troubleshooting.md`; `scripts/walk_task.py` filters it for you. The preview CLI
also refuses `--phase prestudy`, which the server supports.

**`preview` is the only thing that reports keyboard conflicts.** Two schemes both
declaring `key_value: '1'` validate clean, boot silently, and on the live page
only the first scheme's shortcut works — the second is dead with no warning
anywhere. Take `KEYBINDING CONFLICTS` seriously and confirm by pressing the key
on a running page. Details in `building-the-ui.md`.

`validate` also passes a config full of invented phase types that the server
drops at boot, which is what `boot_and_check.py` is for.

## Then drive it

```bash
python .claude/skills/potato-tasks/scripts/walk_task.py \
    --url http://localhost:8000 --config config.yaml --task-dir .
```

It registers a fresh annotator, answers every page, walks to the end, goes back
to an earlier item, and reads `annotation_output/<user>/user_state.json` to check
the server kept what the page showed. Pass `--config` on a task with a practice
round: training grades the answer, so without the model answers the walk loops on
the first question whose right answer is not the first option.

Four things it is checking, each of which has shipped broken:

1. A conditional scheme appears once its gate is answered. A hidden input still
   has a bounding box, so visibility has to be judged on the ancestor chain.
2. Answers survive **navigating away and back**. Never test this with a refresh:
   browsers restore form state themselves, so the check passes when the server
   stored nothing.
3. The workflow reaches its own last page.
4. The answers are in `user_state.json`, not just on the screen.

It answers generically — first option for everything — so it proves the machinery
works, not that the labels make sense. For a real annotation, spans, or anything
it cannot do, `references/running-a-task.md` has the selectors, the span-drag
recipe including the scroll offset that stops the drag landing on the navbar, and
a driver to adapt.

## Then check the interface itself

`walk_task.py` proves the answers reach the server. It says nothing about whether
a person can find the questions.

```bash
python .claude/skills/potato-tasks/scripts/check_ui.py \
    --url http://localhost:8000 --config config.yaml --shots ui/
```

It measures each page in the live layout rather than judging a PNG, and reports
what `validate` and `--screenshot` both miss:

- **Which schemes and which button are below the fold**, with pixel positions, at
  the same 1280×900 the screenshot uses. It is the check the screenshot section
  above says you cannot make with `--screenshot` alone.
- **How many screens tall each page is.** Over about two and a half, reach for
  `instance_display.layout` before the study starts, not after.
- **Schemes declared and never detected** on the annotation page — a scheme that
  did not render, or a `display_logic` gate the initial state never satisfies.
- **Image, canvas, video and audio widgets that came up empty**, which is the one
  failure a screenshot genuinely cannot distinguish from success.
- **Keyboard shortcuts claimed by two labels.** Only the first works and nothing
  warns you.

A config with a duplicate `key_value` and ten questions on one page passes
`potato validate --strict` with `OK — no issues found`.

The walk starts at the landing page and goes forward, so on a real corpus all
twelve steps are annotation pages and a `poststudy` survey is hundreds of items
out of reach. Measure that page on its own:

```bash
python .claude/skills/potato-tasks/scripts/check_ui.py \
    --config config.yaml --phase poststudy --phase consent
```

That boots a throwaway debug server per phase and lands directly on the phase
route. It takes `consent`, `instructions`, `training`, `annotation` and
`poststudy` — not `prestudy`, which the preview route table does not carry and
which the ordinary walk reaches anyway because it comes first.

## Leaving it running

If the point is a server a researcher can open (see `deploying.md` if it needs to
outlive your session or reach anyone else):

```bash
pkill -f "potato start config.yaml -p 8000"        # wipe with it stopped
python .claude/skills/potato-tasks/scripts/handover.py config.yaml \
    --url http://your-host:8000 --port 8000 --confirm
```

`handover.py` removes the accounts you created while checking — they are real
annotators holding real assignments, and their answers count toward agreement —
and writes `RUNNING.md` with the URL, how to start and stop it, where the admin
key lives and where the data is. Run it with the server **stopped**: item and
user state are already in memory, so a wipe while it runs resets nothing and the
next annotator to arrive gets the completion page.

## Watching a live study

```bash
python .claude/skills/potato-tasks/scripts/study_status.py \
    --url http://localhost:8000 --task-dir .
```

Progress, per-annotator counts and pace, agreement per scheme, attention-check
failures, stale assignments, and anything that looks wrong. It exits non-zero
when it found a problem.

The admin surfaces it reads are not linked from the annotation page and are not
open:

```bash
curl -s -o /dev/null localhost:8000/admin    # the key file appears on first admin request
curl -H "X-API-Key: $(cat admin_api_key.txt)" localhost:8000/admin/iaa
```

`/admin` itself serves HTML without a key. Every admin **JSON API** returns
`403 {"error":"Admin access required"}` without one, which reads like a broken
build if you do not know the key exists. `admin_api_key.txt` is written the
first time an admin route is requested — not at boot, so it is missing if you
look straight after starting the server.

`references/after-annotators-start.md` maps each question a researcher asks to
the route that answers it, and covers reclaiming abandoned assignments,
resetting a login, and adjusting one person's quota.

## Changing a task after annotators start

Adding items, editing prose and adding annotators are all safe. Editing
`annotation_schemes` is not, and nothing errors:

- **Adding a question** collects nothing from anyone who already finished.
  Completion is tracked per item, never per question, so an annotated item is
  never offered again.
- **Renaming one** makes the old answers invisible to every report. The overview
  reads 100% complete, agreement reports zero items for each configured scheme,
  and the CSV export carries columns named after the scheme that is gone,
  because exports are driven by what was stored rather than by the config.

The boot log is the only place this surfaces: `Saved annotations name N
scheme(s) that annotation_schemes no longer defines`. Read it after any scheme
edit on a task with data in it. `after-annotators-start.md` has what to do
instead.

**Accounts do not survive a restart by default.** The default auth backend is
in-memory, so registrations are lost when the server stops while the annotations
stay safe on disk. Set `authentication.user_config_path: user_config.json` on
anything an annotator will come back to — it matters most on `render` and
`huggingface`, which restart containers on their own.

## Getting the data out

There is one storage format — `annotation_output/<user>/user_state.json` — and
twenty-nine export formats. `output_annotation_format` is deprecated: the loader
reads it as `export_annotation_format` and warns. Write the live key.

```yaml
export_annotation_format: [csv]     # on a timer, into annotation_output/exports/csv/
```

```bash
curl -H "X-API-Key: $K" -H "Content-Type: application/json" \
     -X POST -d '{"format":"coco"}' localhost:8000/admin/api/export
```

`references/getting-the-data-out.md` routes a downstream use to its format —
`conll_2003` for NER, `coco`/`yolo` for detection, `parquet` for analysis at
scale, `textgrid`/`eaf` for phonetics, `keystrokes` for writing process. Ask
which one they need **before** the annotating starts; a task designed without a
target format can produce answers that do not survive the conversion.

Two traps: the admin export route writes to the **server's** disk and hands back
paths rather than a download, and a misspelled `export_annotation_format`
validates clean, boots clean, and only warns at runtime after the first save.

## Deploying it

`potato deploy` and `potato share` are in the same **other commands** list.

```bash
potato share config.yaml                              # temporary public HTTPS URL
potato deploy check config.yaml --provider render     # preflight; changes nothing
potato deploy up    config.yaml --provider render     # provision
potato deploy pull  config.yaml --dest ./collected    # get the annotations back
```

`references/deploying.md` covers the five providers, what the bundle ships (the
whole task directory, minus `annotation_output/`), and the preflight — which is
the part worth learning, because it names what the deployment exposes and blocks
on `debug: true`.

Three that decide whether a deployment is safe to hand over:

- **`render` and `huggingface` have ephemeral filesystems.** Annotations are lost
  on restart unless you pass `--hf-token` for a backup Dataset, or `--demo` to
  say the run is disposable.
- **`user_config.allow_all_users` defaults to true**, so anyone with the URL can
  register. Set an allowlist before exposing anything.
- **Pull before you destroy.** `destroy` refuses without a prior successful pull
  unless forced, and that guard is the only thing between a finished study and an
  empty directory.

## Things that go wrong

`references/troubleshooting.md` is the full table. The ones worth memorizing:

| Symptom | Cause |
|---|---|
| A command never returns | `potato start` blocks. Background it |
| A feature does nothing, config is right | Typo'd key in a block `--strict` does not check |
| A phase never appears | Named in `order`, never defined; or invalid `type:` |
| `Loaded 0 <anything>` | Side file is missing a required field |
| `ConfigSecurityError: Path … outside the project directory` | Wrong working directory, or a path escaping `task_dir` |
| A scheme is missing from the screenshot | Behind `display_logic`; the initial render does not satisfy it |
| The item shows a file path, not an image | No `instance_display` |
| Both top-level and phase-level schemes | Phase-level schemes *replace* the top-level list; you cannot have both |
| `400 Required annotation(s) not completed` | A required span scheme; the client cannot check it, so the only feedback is a corner toast |
| Annotations look wrong after a restart | Something hand-edited `output_annotation_dir`. Never do that |
| A codebook holds labels you already changed | The first run seeds `project.sqlite`. `potato codebook config.yaml` re-syncs |

## Reference map

| File | For |
|---|---|
| `worked-example.md` | A complete study skeleton that validates and boots |
| `asking-the-experimenter.md` | What to confirm, what to assume, how to ask |
| `importing-existing-work.md` | Existing annotations, transcripts, conversation corpora |
| `designing-a-task.md` | The seven decisions |
| `finding-a-design.md` | The Potato Showcase, and what to change before reusing a design |
| `writing-guidelines.md` | Label definitions, tie-break rules, the codebook an annotator reads |
| `recording-decisions.md` | `DESIGN.md`, `QUESTIONS.md`, and estimating effort |
| `annotation-types.md` | All 61 types with worked examples *(generated)* |
| `building-the-ui.md` | `instance_display`, display types, spans, shortcuts, `display_logic` |
| `modalities.md` | Images, video, audio, dialogue, 3D — display, scheme and quirks |
| `agent-traces.md` | Trace displays, the agent-evaluation schemes, world-model rollouts |
| `evaluating-the-ui.md` | What to look at in a render, and when to stop |
| `interviewing.md` | The multiple-choice question bank, for when the skill is invoked with no brief |
| `phases-and-pages.md` | Consent, instructions, training, surveys, page files |
| `quality-control.md` | Training, attention checks, gold standards, adjudication, side-file formats |
| `assignment-and-agreement.md` | Quotas, ordering, and which metric each schema kind gets |
| `modes-and-subsystems.md` | The rest of Potato, routed from what the researcher said |
| `interrogating-potato.md` | Recovering an undocumented block from the validator and the boot log |
| `data-and-access.md` | Where items come from, output files, login, serving |
| `getting-the-data-out.md` | The 29 export formats, what the CSV holds, phase data |
| `after-annotators-start.md` | Monitoring a live study, what is safe to change, fixing things |
| `config-keys.md` | 157 top-level keys *(generated)* |
| `config-keys-nested.md` | 320 sub-keys, plus what is undocumented and what is unvalidated |
| `running-a-task.md` | Backgrounding, logs, browser driving, handover |
| `deploying.md` | Sharing, hosting, the preflight, bundles, pulling data back |
| `troubleshooting.md` | Symptom → cause → fix |

## MCP

If the Potato MCP server is connected, prefer its tools:
`list_annotation_types`, `describe_annotation_type`, `list_display_types`,
`list_examples`, `get_example`, `validate_config`, `preview_config`,
`render_task_screenshot`. The last hands back the rendered page as an image with
browser errors attached. It is still one page, and still the viewport.

```bash
potato mcp config --root .
```
