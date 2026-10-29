# Running a behavioural experiment

A researcher from psychology or psycholinguistics asks for things an annotation
study never needs: half the participants get feedback and half do not, minors
are turned away at the screener, the three blocks are counterbalanced, and the
judgment has a two-second deadline. Potato has a block for each of these, all
new in 2.12.0. Everything below comes from booting studies that used them,
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
| "mouse trajectories", "cursor tracking" | `extensions: [mouse-tracking]` on the jsPsych phase |
| "check they are wearing headphones" | a `type: headphone_check` phase |
| "send them to oTree / Empirica / a Qualtrics survey and bring them back" | a `type: external` phase |
| "self-paced reading", "moving window", "a maze task" | `trial_timing.presentation` |
| "fill in the blank", "a C-test", "score their answers against a key" | the `cloze` annotation type |
| "a LexTALE vocabulary test" | a `lextale` block on a radio scheme |
| "a list experiment", "randomized response", "crosswise" | `list_experiment`, `randomized_response` |
| "pay a bonus by their choices", "Holt and Laury", "BDM", "incentive-compatible beliefs" | `price_list`, `bdm`, `belief_elicitation` and `incentives:` |

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
- **`balance_on: completed` counts finishers and people still working.** From
  2.13.1 a participant counts toward their cell once they finish, or while
  they were assigned or last active within `conditions.in_progress_minutes`
  (default 60). Someone who has gone quiet for longer stops counting, so their
  slot is refilled. Twelve participants who arrived together split 6/6.
  `in_progress_minutes: 0` counts finishers only, which is what 2.13.0 and
  earlier did. Then a burst all see the same counts, and the same twelve split
  7/5 by the tie-break draw. Last activity is not saved, so after a restart
  only the assignment time counts.
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

`{condition.<factor>}` in item text, question wording or an option label is
replaced, HTML-escaped, by the participant's level, so a vignette can read
"The city council proposes ..." in one cell and "A neighbourhood association
proposes ..." in another. The data file keeps the placeholder and so do the
exports; join on the condition columns to recover the wording. A factor the
participant has no level for is left as typed, so a misspelt placeholder shows
on the page. In a custom layout, an element carrying
`data-condition-only="factor=level"` is removed for everyone outside that
level on the server: a control participant's page did not contain the
sensitive statement of a list experiment (below).

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

A list item can also be a group, `all`, `any` or `not`, nested up to 8
levels, in page rules and in `display_logic`:

```yaml
display_logic:
  show_when:
    - schema: age
      operator: gte
      value: 18
    - any:
        - {schema: country, operator: equals, value: US}
        - not: {schema: region, operator: empty}
```

`count_gt`, `count_lt` and `count_equals` count the options selected on a
multiselect or ranking question. In a browser run, a question with
`count_gt 1` stayed hidden with one box ticked and appeared with two.

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
- `trial_timing.presentation` turns the trial into self-paced reading:
  `mode: moving_window` (also `centered`, `cumulative`, `maze`), `field` for
  the item text, `region_separator` (for example `"|"`), `advance_key`, and
  `question_field` for a comprehension question that follows the sentence.
  Each region's reading time is recorded, and the CSV and TSV exports write
  `regions.csv` beside `trials.csv`, one row per region:
  `user_id,instance_id,region,text,rt_ms,correct,side,errors,trial_outcome,onset_epoch_ms`.
  An item with an empty question ends with outcome `completed` and no label.
  `correct`, `side` and `errors` belong to `maze`. I ran only `moving_window`.
- Each item is its own page. A task that needs frame-level presentation,
  sound onsets or logic on every trial belongs in a jsPsych phase.

## Runtime phases: jsPsych, headphone check, external task

A runtime phase is a page that runs a task instead of asking questions. There
are three kinds, `jspsych`, `headphone_check` and `external`. All sit in the
prestudy or poststudy slot, take `show_when`, `exit_when` and `counterbalance`
like any phase page, and cannot be skipped: the server refuses the phase form
and the annotation page's Next until the task's data is stored. Their data
goes in `project.sqlite` (table `runtime_runs`), not in `user_state.json`.
Their URLs are `/runtime/<page>/...`, with `/api/runtime/trial` and
`/api/runtime/finish` for the data.

### jsPsych

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

`extensions: [mouse-tracking]` on the phase loads jsPsych's mouse-tracking
extension (1.2.0). A trial turns it on itself:

```yaml
  mouse:
    type: jspsych
    timeline: tasks/mouse.js
    plugins: [html-button-response]
    extensions: [mouse-tracking]
```

```javascript
extensions: [{type: jsPsychExtensionMouseTracking, params: {targets: ['#stim']}}]
```

In a driven run the trial row carried `mouse_tracking_data` (a list of
`{x, y, t, event}` samples) and `mouse_tracking_targets` (the bounding box of
`#stim`). WebGazer is not shipped.

### Headphone check

```yaml
phases:
  order: [headphones, annotation]
  headphones:
    type: headphone_check
    test: huggins          # huggins | antiphase | both
    trials: 6
    pass_threshold: 5
    on_fail: screen_out    # screen_out | continue
```

The server makes the sounds, chooses each trial's answer and scores the
choices; a target posted by the browser is ignored. The page answers
`<page>_passed` (`yes` or `no`) and `<page>_correct` (a count), which later
pages can test. With the default `on_fail: screen_out`, a failing participant
is ended with `message`. To decide what happens yourself, use
`on_fail: continue` and a rule:

```yaml
phases:
  order: [headphones, annotation]
  headphones:
    type: headphone_check
    on_fail: continue
    exit_when:
      show_when:
        - {schema: headphones_passed, operator: equals, value: "no"}
      message: This study needs headphones. Thank you for your time.
```

A participant who answered six sounds at random got `headphones_passed: no`,
saw that message, and appears in `participants.csv` with `screened_out` 1 and
`screened_out_page` `headphones`. One who chose the server's target on each
trial passed and moved on. Passing is not proof of headphones: a guess is right
one time in three per trial.

### External task

```yaml
phases:
  order: [game, annotation]
  game:
    type: external
    url: "https://otree.example.org/room/pg/?who={participant}&back={return_url}"
    return_params: [payoff]
    return_secret: "a private string of 16 or more characters"
```

`url` takes `{participant}`, `{return_url}`, `{run_id}` and
`{condition.<factor>}`, and must be `https://` (`http` is allowed for
`localhost`, `127.0.0.1` and `[::1]`). The other system sends the participant
back to `{return_url}` with the values listed in `return_params` appended; the
page then answers `<page>_returned` and `<page>_<param>`. **Without
`return_secret` the returned values are self-reported,** since the participant
can read and edit the link. With it, the other system adds `sig`, the hex
HMAC-SHA256 of `<run id>&<param>=<value>...` (parameters sorted by name, names
and values percent-encoded with `quote(x, safe="")`), keyed with the secret. In
a driven run a return with no `sig` and one with a `sig` for a different value
both got 409, and the correctly signed return stored `payoff` 4.50. A hosted
survey that builds its redirect in the participant's browser cannot keep the
secret, so signing does not help there.

### Exporting runs

```bash
python -m potato.export --config config.yaml --format runtime --output ./export/
```

writes, for each kind the study used, `<kind>_runs.csv`, `<kind>_trials.csv`
and each run's raw JSON under `<kind>_raw/<user>/` (kinds: `jspsych`,
`headphone_check`, `external`). `<kind>_interaction.csv` appears only when blur,
focus or fullscreen events were logged. `--format jspsych` writes the jsPsych
files only. Headphone trials carry `target`, `correct` and `scored` (false for
an answer the server did not count); external runs carry the returned
parameters in `params`. The CSV export's `participants.csv` has `runtime_runs`
and `runtime_answers` columns; the latter holds `headphones_passed` and the
like.

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

## LexTALE

```yaml
annotation_schemes:
  - annotation_type: radio
    name: lexicality
    description: Is this an existing English word?
    labels: ["yes", "no"]
    lextale:
      answer_field: is_word
      word: "yes"
      nonword: "no"
```

Each item is `{"id": "v1", "text": "lantern", "is_word": "yes"}`. The answer
field is not sent to the page. Potato ships no LexTALE item lists; use the
published ones under their authors' terms. `--format lextale` writes
`lextale.csv`, one row per participant: `words`, `words_correct`, `nonwords`,
`nonwords_correct`, the two percentages, `lextale_score` (their mean) and
`unanswered_items`. The score exists only after the export, so it cannot route
a participant inside the study. To screen on it, export after the test and
invite the qualifying participants to the next study.

## Survey experiments

`list_experiment` and `randomized_response` work on survey pages and on
annotation items. The list experiment needs the factor it treats on:

```yaml
conditions:
  factors:
    list_group: [control, treatment]
```

```json
[
  {"name": "lists", "annotation_type": "list_experiment",
   "description": "How many of these have you done in the last year?",
   "items": ["Gone to a live music concert", "Bought a book in a shop",
             "Volunteered for a local group"],
   "sensitive_item": "Driven a car after drinking alcohol",
   "treatment": {"factor": "list_group", "level": "treatment"}},
  {"name": "tax", "annotation_type": "randomized_response",
   "method": "forced_response",
   "description": "This question uses a private random rule.",
   "question": "Have you left income off a tax return on purpose?"},
  {"name": "copying", "annotation_type": "randomized_response",
   "method": "crosswise",
   "description": "Read both statements. Do not say which is true.",
   "question": "I have copied someone else's work.",
   "nonsensitive_statement": "My mother was born in January, February or March.",
   "nonsensitive_prevalence": 0.25}
]
```

The sensitive statement is removed on the server for the control level. In a
driven run the control participant's page did not contain it and the treatment
participant's did. A `crosswise` prevalence within 0.05 of 0.5 is refused.
`--format survey_experiments` writes `survey_experiments.csv`, one row per
scheme: `design`, `estimate`, `se`, `ci95_low`, `ci95_high`, `n`, and for a list
experiment the group sizes, means and `excluded` (answers that were not a whole
number from 0 to the length of the list the participant saw). Estimates are not
clipped to 0 to 1: with 7 participants one list-experiment estimate came out
negative, which means the sample is too small, not that the behaviour is rare.

## Incentivized elicitation

`price_list` (a `preset` of `holt_laury` or `time_preference`, or your own
`rows`), `bdm` (a bid between `min` and `max`) and `belief_elicitation`
(`mode: point` or `bins`) collect the answers. An `incentives:` block says how
each is paid:

```yaml
annotation_schemes:
  - annotation_type: belief_elicitation
    name: forecast
    description: How likely is it that this happens?
    mode: point
  - annotation_type: price_list
    name: risk
    description: Choose one option in each row.
    preset: holt_laury
  - annotation_type: bdm
    name: voucher
    description: The most you would pay for a $3.00 voucher.
    min: 0
    max: 5
incentives:
  enabled: true
  currency: USD
  seed: "a private string, kept out of the repository"
  pay: one_random_item
  max_bonus: 6.00
  rules:
    - {scheme: forecast, method: bsr, prize: 2.00, outcome_field: outcome}
    - {scheme: risk, method: mpl_random_row}
    - scheme: voucher
      method: bdm
      endowment: 5.00
      item_value: 3.00
      draw: {min: 0, max: 5, step: 0.25}
```

Nothing is drawn while the participant answers. The draws are made when you run
the export, for participants who finished, from `incentives.seed` plus the user
id and rule name, and every draw is written out. The same answers and seed give
the same draws. `outcome_field` is stripped from the item data sent to the
page, so a belief question's outcome can sit in the data file; a report with no
outcome is not paid. Put price lists and bids on a phase page and set
`export_include_phase_data: true`, or the exports leave them out.

```bash
python -m potato.export --config config.yaml --format incentives --output ./bonuses/
```

writes `bonuses.csv` (per decision: `rule`, `method`, `draws` as JSON, `payoff`,
`paid`, `note`, and the participant's `total` and `capped`) and
`bonuses_prolific.csv`, lines of `<prolific id>,<amount>` with no header. In a
run of 6 finished participants it wrote 5 lines totalling 14.00; the sixth was
owed nothing, and one total was capped from 7.00 to 6.00. Participants need a
Prolific id, from `login: {type: url_direct, url_argument: PROLIFIC_PID}` or
`crowdsourcing: {provider: prolific}`, or they are left out with a warning.
Replace the example seed `CHANGE-ME-this-example-seed-is-public` before paying
anyone; `potato validate` warns while it is there.

### Paying through the admin API

With `admin_api_key` set and a Prolific token configured:

```bash
# dry run: sends nothing
curl -H "X-API-Key: $KEY" http://localhost:8000/admin/api/crowd/incentive_bonuses
# pay: expected_total must equal the dry run's prolific_total
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
     -d '{"pay": true, "expected_total": "14.00", "study_id": "<id>"}' \
     http://localhost:8000/admin/api/crowd/incentive_bonuses
```

The dry run returned each participant's total, `prolific_rows`,
`prolific_total`, `unpaid_total` and `already_paid`. A POST whose
`expected_total` differed from the current total got 409 with the current
figure, so an answer that changed between dry run and payment cannot slip
through. Potato's documentation adds three behaviours I did not run: each paid
batch is recorded in `incentive_payments.json`; a batch containing anyone
already paid gets 409 unless it sets `"repeat": true`; and `"skip_paid": true`
pays only the unpaid, with `expected_total` set to `unpaid_total`. The payment
to Prolific itself is unverified: I did not call Prolific.

## The flow record and `participants.csv`

`user_state.json` holds a `flow_record` per participant:

```json
{"conditions": {"arm": "b"}, "condition_cell": 1, "condition_ordinal": 4,
 "page_orders": {"group_0": ["block1", "block3", "block2"]},
 "skipped_pages": [{"phase": "prestudy", "page": "smoke_followup", "at": 1792717612.0}],
 "question_orders": {"debrief": ["d3", "d2", "d1", "comments"]},
 "runtimes": {"headphones": {"kind": "headphone_check", "attempts": 1, "status": "complete"}}}
```

With `conditions` set, `--format csv` writes `participants.csv`, one row per
participant, even when nobody has labelled an item yet:

```
user_id,condition_arm,condition_ordinal,cell_ordinal,latin_ordinal,final_phase,screened_out,screened_out_page,skipped_pages,page_orders,question_orders,runtime_runs,runtime_answers
```

That file is where the screen-outs are. `annotations.csv` does not mark them, so
join on `user_id` before analysis. Survey answers need
`export_include_phase_data: true` as usual (`getting-the-data-out.md`).

## What has and has not been checked

Checked against Potato 2.12.0 (commit 5b1ec643), with the default file storage,
in headless Chromium. On 2.12.0 I ran: a headphone check (failed at random and
screened out through an `exit_when` rule, then passed by answering the server's
targets), an `external` page with a signed return (unsigned and wrong-value
returns got 409), a jsPsych page with `mouse-tracking`, the `runtime` and
`jspsych` exports and the `participants.csv` header; a list experiment, a
crosswise and a forced-response question with the `survey_experiments` export;
a belief question, a Holt & Laury list and a BDM bid with the `incentives`
export and the admin dry run and its mismatched-total 409; `moving_window`
reading with `regions.csv`; a LexTALE scheme with the `lextale` export; nested
`any`/`not` groups and `count_gt` in `display_logic`; and `{condition.<factor>}`
placeholders. Earlier rounds, on the development tree after 2.11.1: `balanced`
and `round_robin` assignment, `balance_on: completed`, the `max_per_cell`
overflow warning, a restart, `group_by_condition`, `show_when` and `exit_when`
on answers and conditions, `latin_square` over three pages,
`randomize_questions` with `pin_last`, `trial_timing` with keys and timeouts,
`cloze` with `text` and with `answer_field`, and the jsPsych Stroop example from
`examples/advanced/jspsych-stroop/`.

Not run: a real payment to Prolific, and the `repeat`, `skip_paid` and
already-paid 409 behaviour of the payout route; `presentation` modes `centered`,
`cumulative` and `maze`; the `antiphase` and `both` headphone tests and
`on_fail: screen_out` on its own; `count_lt`; `random` assignment, weighted
`cells`, `exit_when` with Prolific or SONA (Potato's documentation says the
participant gets the platform's screen-out outcome rather than the completion
code), `counterbalance` with `method: random`, `extra_scripts` with a plugin
Potato does not ship, `time_preference` price lists, `bins` belief reports, and
any of it on the MySQL backend.
