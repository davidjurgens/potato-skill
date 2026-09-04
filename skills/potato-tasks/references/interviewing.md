# Interviewing the researcher

When someone invokes this skill directly — `/potato-tasks`, with or without a
sentence after it — there may be no brief in the conversation to work from. Do
not open with "what would you like to build?", and do not open with a
questionnaire either.

Ask for one sentence, propose a design from it, then confirm only the parts you
had to guess. A researcher who has never seen Potato cannot answer "what
annotation type do you want". They can describe their study in a sentence, and
they can tell you whether the design you read back to them is right.

This file is the question bank for that. When a brief already exists,
`asking-the-experimenter.md` governs instead and most of this is answered.

## Step 1: ask for one sentence

Ask in prose, not with the question tool. Two things:

> In one sentence, what do you want annotated and what do you want to know about
> it? And if you already have the data, point me at the file.

That sentence usually settles the modality, the unit and the question at once.
"Label 2,000 tweets for stance on a policy" leaves only the response format, the
annotator count and the phases genuinely open. Look at the data file if they name
one — the fields in it decide `item_properties`, and a glance is faster than
asking.

## Step 2: propose a design

Before asking anything else, say back what you intend to build:

> Each annotator sees one tweet. They pick one of Agree / Neutral / Disagree /
> Not about the policy, and highlight the phrase that decided it. Three
> annotators per tweet. No consent or training pages unless you want them.

Then ask only about what that proposal guessed at. Reading back a wrong design is
the fastest way to be corrected. A list of eight questions is the slowest.

## How to ask the rest

- **At most four questions per round, two to four options each.** More and people
  stop reading and take the first option.
- **Put what you proposed first and mark it as the recommendation.** An unmarked
  list of four equals implies they are equally good.
- **Never ask what the sentence already answered.** Skip whole questions.
- **Two rounds, an optional third, then build.** Everything still open becomes a
  stated assumption in `DESIGN.md` and a line in `QUESTIONS.md`.

## Round 1: what they are annotating

**1. What kind of data is it?** Ask this even when you think you know. It decides
more than any other answer: the display, the scheme family, and the per-family
key that says where the media lives.

| Answer | Where to go next |
|---|---|
| Text — posts, documents, transcripts as text | Stay here. The default `text` display is right |
| Images | `modalities.md`. Needs `instance_display`, and a geometry scheme reads its bitmap from the rendered image rather than fetching its own |
| Audio or video | `modalities.md`. `speech_transcript` reads `audio_key`, `temporal_grounding` reads `video_key` |
| Conversations, agent traces, PDFs, 3D | `modalities.md`, then `agent-traces.md` for the agent family, which reads `steps_key` |

Getting this wrong is quiet. The wrong key gives an empty widget, a clean
`--strict` and nothing in the log, and a screenshot cannot tell an image that
failed to load from one that loaded.

**2. What does one annotator see at a time?** One item · one document · a whole
conversation · a pair to compare. Decides `item_properties` and the shape of the
data file, which is the expensive thing to change later — it is a data problem
rather than a config problem.

**3. What do you want to know about each item, and how should each part be
answered?** Ask both halves. Someone who says "stance" often wants stance, the
strategies being used, and the phrase that carries it — three judgments on one
item. Step 1's sentence names whichever
they thought of first, so ask for the rest here or they will not come up again.
`designing-a-task.md` has the rules once there is more than one: one scheme per
judgment, ordered the way a person would think about the item, `display_logic`
on the ones that only sometimes apply, and keep the count low.

The response format is then a choice per judgment. It decides the agreement
metric and nothing warns you:

| Offer | Type | Consequence |
|---|---|---|
| Pick one of N | `radio` | Scored as unordered — right for categories, wrong for a scale |
| A rating scale | `likert` | Scored as ordered. "1 vs 2" counts less than "1 vs 5" |
| Pick any that apply | `multiselect` | Set-valued agreement |
| Mark a part of the item | `span` | Spans rather than labels. `error_span` for error analysis |

A 1–5 rating stored as `radio` is a measurement error that survives to
publication. Confirm this one even when it feels obvious.

**4. How many people annotate each item?** One (fastest, no agreement number) ·
two · three (recommended if they want to report agreement) · more. Sets
`num_annotators_per_item`, and it multiplies the budget directly —
`estimate_effort.py` prices it before the instructions get written.

## Round 2: the study around it

**1. Do you want any pages around the annotation?** Offer the list and expect
most people to want none of it.

**A task needs only the annotation itself.** Most do not declare a `phases` block
at all — 7 of the example projects Potato ships use one, and none of them has a
`consent` or `prestudy` phase. This is a multi-select that is allowed to come
back empty, not a menu to talk someone through.

| Offer | Phase | Ask for it only when |
|---|---|---|
| Written instructions | `instructions` | The label definitions are longer than the banner can hold |
| A consent page | `consent` | Their protocol or ethics board requires one |
| A practice round with feedback | `training` | They said the labels are hard, or want agreement measured after practice |
| Questions at the end | `poststudy` | They asked for demographics or feedback |
| Questions before starting | `prestudy` | They are screening or qualifying annotators |

`consent`, `training` and `prestudy` are protocol decisions. A researcher who
needs one knows they need it. Added uninvited they cost the annotator time in
every session and cost you a page file per phase to keep correct.

**Follow-up, only if they picked `poststudy` or `prestudy`: do you want a
standard instrument?** Potato ships a library of 55 validated questionnaires —
`tipi` and `bfi-2` for personality, `panas` for affect, `who-5` and `phq-9` for
wellbeing, `mfq` and `sdo-7` for attitudes, and demographic batteries lifted from
ANES, GSS, ESS and the ACS. Naming one writes the whole questionnaire into the
phase, so this is usually cheaper than the free-text survey they were about to
describe. `phases-and-pages.md` has the mechanics and the full categories.

**2. How do you want to catch inattentive annotators?** Attention checks ·
gold-standard items · the practice round grades itself · nothing, it is a small
trusted pool. "Nothing" is a reasonable answer for a pilot or a lab study. Each
of the others has its own side-file format in `quality-control.md`, and each is
silently off if the file is malformed.

**3. What has to come out at the end?** A spreadsheet · a format for a specific
tool · a training dataset. Potato has an exporter registry with an entry per
format — `csv` for analysis, `conll_2003` for NER, `coco` for detection,
`parquet` at scale. Ask before annotation starts: a task designed without a
target format can collect answers that do not survive the conversion.

**4. Who annotates, and is anything in the data identifiable?** Decides
`user_config.allow_all_users`, whether an allowlist is needed, and whether any of
`deploying.md` applies. Never decide the identifiable half yourself — it gates
consent wording, export settings, and whether a public URL is acceptable at all.

## Round 3: what else they might want

Rounds 1 and 2 cover the study a researcher can describe. This one covers what
they cannot, because they do not know it is there. Do not walk them through the
whole capability surface. Offer a menu, and drill into only what they tick.

Two multi-select questions, four options each. That is eight slots for the seven
clusters in `modes-and-subsystems.md`, which is the map behind this round and
where you go once something is ticked.

**Ask first: is this study worth it?** Skip the round entirely for a pilot, a lab
study, or anything under a few hundred items. Say so out loud rather than
silently omitting it — "none of this is needed for a normal study, but here is
what is available" is the framing that lets someone decline without feeling they
have missed something.

**1. Anything here you want?**

| Offer | Cluster | Drill into |
|---|---|---|
| Answers more precise than a rating scale | The answer | `soft_label`, `range_slider`, `semantic_differential`, `constant_sum`, `confidence` |
| Know which annotators are reliable | Trust | `mace`, `psychometrics`, `agreement_metrics` |
| A model helping out | Model help | `ai_support`, `pre_annotation`, `icl_labeling`, `chat_support`, `active_learning` |
| Different people see different items | People | `batch_assignment` with `scheme_sets`, `category_assignment` |

**2. Anything about the corpus, or what happens afterwards?**

| Offer | Cluster | Drill into |
|---|---|---|
| The corpus is large, or keeps growing | Material | `partial_loading`, `data_sources`, `watch_data_directory` |
| Score whole conversations, or per participant | Unit | `sessions` with `session_level`, `cases` |
| Publish or hand off the dataset | Output | `publish`, `dataset_metadata` |
| Pay annotators on Prolific or MTurk | Output | `crowdsourcing` |

Nothing here is free. Every one of these is a block that turns on with
`enabled: true`, validates clean, and can then load nothing at all. Whatever they
tick, check the boot log afterwards — an advanced feature that is configured and
silently off is worse than one nobody asked for, because everyone believes it is
running.

## When the skill fires implicitly

Most of the time this skill loads because someone described an annotation task,
not because they typed its name. There is no interview then, and asking eight
questions at someone who just handed you a brief is the wrong move.

The clusters still apply — as a checklist you run against the brief rather than
questions you ask:

- Walk the seven clusters in `modes-and-subsystems.md` against what they wrote.
- Build the obvious task, with the defaults, and boot it.
- Raise **at most two** clusters the brief never touched, and only where the
  brief implies they matter. Three annotators and no quality control is worth a
  sentence. A 200-item pilot with no active learning is not.
- Put the rest in `QUESTIONS.md` rather than in the conversation.

The rule is the same in both directions: surface what they would want, and do not
make them shop.

## Build before you confirm

Two rounds is enough to write a config that boots. Write it, boot it, run
`check_ui.py`, and show them a screenshot of the real interface. A researcher who
cannot answer "do you want a `likert` or a `radio`" can answer "is this the
question you meant" in one look.

Record the choices in `DESIGN.md` with the assumptions marked as assumptions, put
what is still open in `QUESTIONS.md`, and say which one you would revisit first.
`recording-decisions.md` has the template.
