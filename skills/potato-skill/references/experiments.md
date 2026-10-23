# Running a behavioural experiment

A researcher from psychology or psycholinguistics asks for things an annotation
study never needs: half the participants get feedback and half do not, minors
are turned away at the screener, the three blocks are counterbalanced, and the
judgment has a two-second deadline. Potato has a block for each of these, all
added after 2.11.1. Everything below comes from booting studies that used them,
driving them in a browser and reading what landed on disk; the last section
lists what was not run.

## Which block for which request

| They said | Reach for |
|---|---|
| "half get feedback, half don't", "a 2×2 design", "between-subjects" | `conditions` |
| "each list goes to a different group of people" | `conditions` + `batch_assignment.group_by_condition` |
| "only smokers get the follow-up", "the extra page is for the feedback group" | `show_when` on the phase page |
| "under-18s stop here", "screen out anyone who fails" | `exit_when` on the screener page |
| "counterbalance the blocks", "Latin square" | `phases.counterbalance` |
| "randomise the questionnaire items" | `randomize_questions` on the survey page |
| "a speeded judgment", "reaction times", "a deadline" on items Potato shows | `trial_timing` |
| "my jsPsych task", "a Stroop", frame-accurate timing, audio onsets, code on every trial | a `type: jspsych` phase |
| "fill in the blank", "a C-test", "score their answers against a key" | the `cloze` annotation type |

Option order inside one question is a different setting: the per-scheme
`randomize_order` listed in `annotation-types.md`.

## Conditions

```yaml
conditions:
  factors:
    arm: [control, feedback]
  assignment: balanced        # balanced | random | round_robin
  balance_on: completed       # assigned | completed
  max_per_cell: 40
```

Each factor needs at least two levels, and the cells are the full factorial
unless `cells` lists a subset. A participant is given a cell the first time the
server sees them and keeps it. The cell is stored in `user_state.json`, and a
restart rebuilds the counts from those files. Two participants who arrived after
a restart got arrival numbers 10 and 11, where the last one before it was 9.

Three behaviours to plan around:

- **Every arrival takes an arrival number,** including people who are later
  screened out and people who logged in and went no further. The numbers
  in `condition_ordinal` have gaps; they are not a count of participants.
- **`balance_on: completed` only counts people who have finished.** Anyone
  still mid-study is invisible to it, so a burst of simultaneous arrivals all
  see the same counts, and the cells split by the tie-break draw rather than by
  alternation. Use it to replace dropouts in a trickle of arrivals. With a
  recruitment burst, `assigned` balances better.
- **`max_per_cell` does not close the study.** With every cell full, the next
  participant is still admitted, to the least-filled cell, and the server logs
  (here with a cap of 3) `Every condition cell has reached max_per_cell=3; assigning the least-filled
  cell. Stop recruiting or raise the cap.` Stopping recruitment is the
  researcher's job, on the platform.

Quote level names YAML reads as booleans. `arm: [yes, no]` is refused with
`conditions.factors.arm has a true/false level`.

### Rules that test the condition

Rules address a factor as `condition.<factor>`, in a question's `display_logic`
and in the page rules below:

```yaml
conditions:
  factors:
    arm: [control, feedback]
annotation_schemes:
  - annotation_type: text
    name: feedback_reaction
    description: What did you make of the feedback?
    display_logic:
      show_when:
        - {schema: condition.arm, operator: equals, value: feedback}
    label_requirement:
      required: true
```

A question hidden by its condition is not required. In a two-arm run of this
rule, participants in the excluded arm finished every item without seeing the
box, and those in the other arm had to fill it in. A rule comparing a factor against a level it does not have is
refused, here and in page rules:
`phases.block1.show_when[0] compares 'condition.arm' with 'c', which is not a
level of 'arm' (a, b)`.

To give each condition its own items, name batch groups after the levels of one
factor:

```yaml
conditions:
  factors:
    list: [list_a, list_b]
  assignment: round_robin
assignment_strategy: batch
batch_assignment:
  auto_assign_annotators: true
  group_by_condition: list
  groups:
    - {name: list_a, data_file: data/list_a.jsonl}
    - {name: list_b, data_file: data/list_b.jsonl}
```

Validation checks that `group_by_condition` names a declared factor, that
`auto_assign_annotators` is on, and that the group names are exactly the levels.
List the item files only under `groups` and set `data_files: []`. Naming the
same files in `data_files` as well loads every item twice, and the server stops
with `Duplicate instance ID 'a1'`.

## Page rules: `show_when` and `exit_when`

```yaml
phases:
  order: [consent, screener, smoking_followup, annotation, debrief]
  consent: {type: consent, file: surveys/consent.json}
  screener:
    type: prestudy
    file: surveys/screener.json
    exit_when:
      show_when:
        - {schema: age, operator: lt, value: 18}
      message: This study is for adults only. Thank you for your time.
  smoking_followup:
    type: prestudy
    file: surveys/smoking.json
    show_when:
      - {schema: smoker, operator: equals, value: "Yes"}
  debrief: {type: poststudy, file: surveys/debrief.json}
```

The grammar is the question-level `display_logic` one (`building-the-ui.md`):
a list of `schema` / `operator` / `value` conditions, joined by `logic: all`
(the default) or `logic: any`.

**A page rule reads only survey answers and conditions.** It can test a
question asked on any earlier page in any phase, and any `condition.<factor>`.
It cannot see per-item annotations, so a debrief page cannot depend on how
someone labelled the items. `potato validate` reads the page files and checks
every reference, and the server repeats the check at startup:

```
phases.block1.show_when refers to question 'nope', which no phase page asks. Page rules read survey answers and conditions; per-item annotations are not visible to them
phases.screener.show_when tests 'age', which is asked on this page or later; it can only ever be unanswered when the rule is checked
```

A hidden page is passed over in both directions. Next skips it and Previous does
not land on it, and each skip is written to the participant's `skipped_pages`.
`show_when` on the annotation phase itself is refused: `the annotation phase
cannot be skipped with show_when. Gate the pages around it instead.`

**`exit_when` ends the study for that participant.** It is checked when they
submit the page and can test questions on that same page, which is what a
screener needs. In a run of this design a 17-year-old went from the screener
straight to a page showing the message, and the record says where it happened:

```json
{"screened_out": {"page": "screener", "at": 1792717607.8,
                  "message": "This study is for adults only. Thank you for your time."}}
```

It works on consent, prestudy, instructions and poststudy pages. It is a mapping
with `show_when` inside it; a bare list is refused.

## Order: `counterbalance` and `randomize_questions`

```yaml
phases:
  order: [consent, block1, block2, block3, annotation, debrief]
  consent: {type: consent, file: surveys/consent.json}
  block1: {type: prestudy, file: surveys/b1.json}
  block2: {type: prestudy, file: surveys/b2.json}
  block3: {type: prestudy, file: surveys/b3.json}
  debrief:
    type: poststudy
    file: surveys/debrief.json
    randomize_questions:
      pin_last: [comments]
  counterbalance:
    - pages: [block1, block2, block3]
      method: latin_square    # or random
```

The grouped pages keep the slots they hold in `order`, and each participant gets
their own arrangement of them. Six participants through the study above got six
different orders of the three blocks. Validation refuses a group with fewer than
two pages, a page in two groups, a page no phase defines, and a group mixing
phase types:

```
phases.counterbalance[0].pages mixes phase types (poststudy, prestudy). Pages of different types never sit next to each other in the study, so only pages of one type can be counterbalanced against each other.
```

`randomize_questions: true` shuffles a page's questions per participant, and
`pin_first` / `pin_last` hold named questions at the ends. Every participant
above saw `comments` last and the other three in their own order. A pin naming
a question that is not on the page fails validation with `pin_last names
'nope', which is not a question on that page`.

Both orders are recorded the first time the participant meets them, in
`page_orders` and `question_orders`. **Tabulate `page_orders` against condition
before analysis.** The method name in the config says how orders were drawn,
and only the data says whether each condition got a spread of them.

## Timed trials

`trial_timing` turns each annotation item into a trial: an optional fixation
cross, the item, a response window with an optional deadline, and keys mapped to
labels. The reaction time is measured in the browser.

```yaml
annotation_schemes:
  - annotation_type: radio
    name: decision
    description: Is this a word?
    labels: [word, nonword]
    label_requirement:
      required: true

trial_timing:
  enabled: true
  fixation_ms: 500
  trial_duration_ms: 2000
  iti_ms: 500
  response:
    schema: decision
    keys: {f: word, j: nonword}
```

- **`response.schema` must be a `radio` or `likert` scheme, and it must be the
  only scheme on the page.** The response keys are captured for the whole
  trial, so a second question could not be answered by typing, and a config
  with one is refused: `timed page can hold only its response scheme
  ('decision'); remove or move cz`. Ask follow-up questions on a survey page.
- **A timed-out item has no label.** The main annotation export lists answered
  items only. `trials.csv`, which the CSV and TSV exports write alongside, has
  one row per trial with `outcome` (`response` or `timeout`), `rt_ms`, the key
  and label, the intended and delivered durations, and the server's `flags`. It
  is the complete record of a timed task. A study whose last item times out
  still finishes.
- **A timeout finishes the item for that participant without using up the
  item.** With `max_annotations_per_item: 1`, two participants who timed out on
  every item left the items open, and the next one to answer an item took it.
- Each item is its own page. A task that needs frame-level presentation,
  sound onsets or logic on every trial belongs in a jsPsych phase.

## jsPsych phases

A `type: jspsych` page runs a jsPsych timeline as one page of the study.
Consent, surveys, the annotation phase, recruitment and the export stay in
Potato. Potato ships jsPsych and 15 of its plugins, so the page needs no
CDN.

```yaml
phases:
  order: [consent, stroop, annotation]
  consent: {type: consent, file: surveys/consent.json}
  stroop:
    type: jspsych
    timeline: tasks/stroop.js
    plugins: [instructions, html-keyboard-response]
```

The timeline file sets `window.potatoTimeline`, either to a timeline array or
to a function that receives the jsPsych instance and a `potato` object and
returns one. Both forms ran. Do not call `initJsPsych` or set the experiment's
`on_finish`, because Potato owns both. The `potato` object carries the
participant id, `potato.conditions`, the answers named in `expose_answers`, an
`asset(path)` helper for files in `assets_dir`, and `finish()`, which ends the
task early and saves what was collected. `expose_answers` is checked like a page
rule: a question no page asks, or one asked after the jsPsych page, stops the
server at startup.

What a driven Stroop study showed:

- **The participant cannot leave the page until the run is stored.** A POST of
  the phase form or the annotation page's Next before then gets a 400.
- **Every trial row is stamped.** `potato_user`, `potato_run_id`,
  `potato_attempt` and one `condition_<factor>` column per factor are added to
  what jsPsych recorded.
- **A reload starts the timeline over.** jsPsych cannot resume. With the
  default `save: on_finish`, the trials done before the reload were never sent,
  so they are gone and the run carries on as attempt 1. With
  `save: incremental` each trial is stored as it finishes, and a reload after
  that starts a new attempt.
- **`exit_when` on a jsPsych page is tested after the timeline has run,** so
  the participant's data is already stored when they are screened out. Screen
  on a survey page before the task.
- **Going back to a finished jsPsych page** (with
  `allow_phase_back_navigation` on) shows an "already completed" page, and
  Continue returns to where the participant was. With `allow_rerun: true` it
  runs the task again as attempt 2, and both runs are stored as complete.
- `show_when` on a `condition.<factor>` works on a jsPsych page, and two jsPsych
  pages can share a `counterbalance` group.
- The asset route serves stimuli only: a `.js` or `.html` file in `assets_dir`
  is a 404, and `../` paths are refused. The page is served with a
  Content-Security-Policy limited to the Potato server, and
  `csp.extra_sources` takes `https://` origins only.

Runs are stored in `project.sqlite` in the task directory, not in
`user_state.json`. Export them with the `jspsych` format:

```bash
python -m potato.export --config config.yaml --format jspsych --output ./export/
```

That writes `jspsych_runs.csv` (one row per run, with its status), and
`jspsych_trials.csv` (one row per trial, every column jsPsych recorded), plus
each run's raw JSON under `jspsych_raw/`. `jspsych_interaction.csv` appears only
when jsPsych logged blur, focus or fullscreen events. The CSV export's
`participants.csv` gains a `jspsych_runs` column.

## Cloze

```yaml
annotation_schemes:
  - annotation_type: cloze
    name: proficiency
    description: Fill in each blank with one word.
    text: "The library opens at nine and [[closes|shuts]] at six."
    scoring: case_insensitive
    label_requirement:
      required: true
```

Each `[[...]]` is a blank, and the text inside it is the accepted answer, with
`|` between alternatives. For a different passage per item, use `source_field`
for the item field holding the passage, with blanks written `[[]]`, and
`answer_field` for a field holding a list with one entry per blank. Each entry is
a string (alternatives joined by `|`) or a list of strings. The answer field was
absent from the rendered page, `/api/current_instance`, `/api/instance_data` and
`/api/schemas`.

Each blank is stored as `blank_1`, `blank_2`, ... and the CSV export adds
`<scheme>.blank_<n>_correct`, `<scheme>.score` and `<scheme>.scored_blanks`.

## The flow record and `participants.csv`

`user_state.json` holds a `flow_record` per participant:

```json
{"conditions": {"arm": "b"}, "condition_cell": 1, "condition_ordinal": 4,
 "page_orders": {"group_0": ["block1", "block3", "block2"]},
 "skipped_pages": [{"phase": "prestudy", "page": "smoke_followup", "at": 1792717612.0}],
 "question_orders": {"debrief": ["d3", "d2", "d1", "comments"]}}
```

With `conditions` set, `--format csv` writes `participants.csv`, one row per
participant, even when nobody has labelled an item yet:

```
user_id,condition_arm,condition_ordinal,cell_ordinal,latin_ordinal,final_phase,screened_out,screened_out_page,skipped_pages,page_orders,question_orders,jspsych_runs
```

That file is where the screen-outs are. `annotations.csv` does not mark them, so
join on `user_id` before analysis. Survey answers need
`export_include_phase_data: true` as usual (`getting-the-data-out.md`).

## What has and has not been checked

Checked against the Potato development tree after 2.11.1 (October 2026, before
2.12.0 was tagged), with the default file storage, in headless Chromium:
`balanced` and `round_robin` assignment, `balance_on: completed`, the
`max_per_cell` overflow warning, a restart, `condition.<factor>` in
`display_logic`, `group_by_condition`, `show_when` on an answer and on a
condition, `exit_when` without a crowd platform, `latin_square` over three
pages, `randomize_questions` with `pin_last`, `trial_timing` with keys and
timeouts, `cloze` with `text` and with `answer_field`, and the jsPsych Stroop
example from Potato's `examples/advanced/jspsych-stroop/`, driven to the end.

Not run: `random` assignment, weighted `cells`, `exit_when` with Prolific or
SONA (Potato's documentation says the participant gets the platform's
screen-out outcome rather than the completion code), `counterbalance` with
`method: random`, `extra_scripts` with a plugin Potato does not ship,
and any of it on the MySQL backend.
