# Designing an annotation task

A config is the last step. Before writing one, seven things have to be decided,
and a researcher's description usually settles three or four of them. The rest
you either infer from context or ask about — see `asking-the-experimenter.md`
for which is which.

1. What one annotator sees at a time (the unit)
2. What they are being asked (the questions)
3. How they answer (the response format)
4. How many people answer each item
5. What order items arrive in
6. How you find out whether the answers are any good
7. What happens before and after the annotation itself

## 1. The unit

Whatever you put in one row of the data file is what one annotator judges at
once, and it is the hardest thing to change later. A comment, a sentence, a
whole thread, a document, an image, one agent trace.

Pick the smallest unit that still carries enough context to answer the
question. "Is this reply rude?" needs the message it replies to; if the unit
is a bare reply, annotators invent the missing context and disagree about
inventions rather than about rudeness.

Where the judgment is about a *part* of the unit, do not split the unit — use a
span scheme and let annotators mark the part. Splitting a paragraph into
sentences to ask "which sentence is the claim" throws away the reason a reader
could tell.

## 2. The questions

One scheme per judgment. Two judgments in one question ("is it rude and is it
sarcastic?") produce answers you cannot separate afterwards.

Order them the way a person would think: the gating question first, details
after. Use `display_logic` so follow-ups appear only when they apply — an
annotator who said "no anecdote" should not be looking at "highlight the
anecdote". See `building-the-ui.md`.

Keep the count low. Every extra question is paid for on every item.

## 3. The response format

This is the decision that most often gets made badly, because the natural
phrasing of a request rarely names a format.

| What they asked for | Type | Notes |
|---|---|---|
| yes/no, or pick one from a list | `radio` | Add `key_value` per label; it is the difference between 8 seconds an item and 3 |
| pick any that apply | `multiselect` | If they meant "pick one", it is `radio` — do not make them choose from checkboxes |
| rate 1–5, agree/disagree | `likert` | Give every point a label, not just the ends |
| how sure are they | `confidence` | Set `target_schema` to the scheme it qualifies, so the rating is attached to a specific judgment rather than floating |
| mark the part of the text that… | `span` | Works as-is on `text_key`. Only needs `span_target` once you define `instance_display`, to say which field is the anchor |
| which of these two is better | `pairwise` or `bws` | `bws` if there are 4+ candidates per item; it is far more efficient per judgment |
| put these in order | `ranking` | Expensive above ~7 items |
| free text, a reason, a correction | `text` / `text_edit` | `text_edit` when they are correcting something that already exists. **`text` is a one-line `<input>` by default** — set `multiline: true` for anything phrased "in a sentence". No agreement metric applies to either; plan to read them |
| a number, a proportion | `slider` / `number` / `constant_sum` | `constant_sum` when the parts must total something |

### Eleven types the table skips

The table above covers the common asks. Reach past it when the researcher
describes one of these, because each has a purpose-built type and the
hand-assembled version is worse in a way that shows up in the data:

| What they said | Type | Instead of |
|---|---|---|
| "rate every one of these on the same scale" | `multirate` | Ten separate `likert` schemes, which is ten headings and ten scales an annotator reads separately |
| "pick from our taxonomy" (dozens of codes, nested) | `hierarchical_multiselect` | A flat `multiselect` of 200 checkboxes. It renders collapsed with a search box, so the tree stays one screen |
| "a long list, one answer" | `select` | A `radio` with forty options down the page |
| "it isn't one label — it's mostly A, a bit B" | `soft_label` | A forced choice that throws the ambiguity away. Constrained sliders summing to a total, with a live distribution bar |
| "an acceptable range, not a point" | `range_slider` | Two number boxes that can cross |
| "warm/cold, weak/strong, active/passive" | `semantic_differential` | One `likert` per adjective pair. Takes `pairs`, renders the bipolar grid |
| "which package would they choose" | `conjoint` | Hand-built profile comparisons. Give it `attributes`, each with the values it can take, and it generates the profiles |
| "group these however makes sense to you" | `card_sort` | A `multiselect` per item, which loses the grouping |
| "find the answer in the passage" | `extractive_qa` | A `span` plus a separate question field; this takes `question_field` and `passage_field` and handles unanswerable |
| "the same event reported across articles" | `multi_document_event` | Per-document annotation you then have to align. Takes template `slots` |
| "review this diff like a pull request" | `code_review` | A textbox. Inline comments, categories, per-file ratings, a verdict |

These are the eleven types a config reference lists and nothing routes you to.
All eleven have a working example under `examples/`, all render cleanly, and
`search_examples(annotation_type=...)` finds each one.

There are 61 types. `references/annotation-types.md` lists all of them with a
worked example lifted from a config that really runs. Never invent a type name:
`sentiment`, `classification` and `qa` are not types.

**When the label set is meant to be incomplete**, this table is the wrong tool.
A researcher doing thematic analysis, grounded theory or any open coding starts
with a few codes and adds more while reading, and a fixed `labels:` list fights
that the whole way. Potato has a mode for it — `qda_mode`, with a live project
codebook (`codebook: true` on a span scheme), memos on passages, and in-vivo
coding that mints a code from the participant's own words. Reach for that rather
than a `multiselect` you plan to keep editing. The anti-patterns at the end of
this file assume a fixed scheme and do not apply: in open coding, overlapping
codes are the normal case and memos are deliberately uncountable prose.

Agreement across two open-coded passes is not a κ. The codebooks differ, so
compare coverage and code co-occurrence, and expect to reconcile the codebooks
before any number means anything.

**Scale points.** 5 or 7 for a Likert. Even numbers force a side, which is a
design choice and not a default. If the researcher says "1 to 5", give all five
points a written label — bare numbers mean different things to different
annotators and inflate disagreement that has nothing to do with the construct.

Doing that logs `Complex labels detected for <scheme>, using radio layout` and
renders radio buttons rather than a scale widget. That is cosmetic: agreement
keys off `annotation_type`, so a labelled `likert` is still scored as ordinal
(`/admin/iaa` reports `kind: ordinal`). Do not "fix" it by switching the scheme
to `radio`, which is the change that would actually break the metric.

**The schema kind decides the agreement metric**, and you do not get to pick it
separately. Potato classifies each scheme and computes what fits:

| Kind | What it computes |
|---|---|
| nominal (`radio`, `multiselect` capped at 1) | percent agreement, Cohen's κ, Fleiss' κ, α |
| ordinal (`likert`, ordered scales) | linear and quadratic weighted κ, Spearman ρ, ordinal α |
| continuous (`slider`, numbers) | Pearson r, MAE, RMSE, interval α, ICC(2,k) |
| multilabel (`multiselect`) | mean Jaccard, MASI α |
| ranking | Kendall's τ, Spearman footrule |
| span | token-level κ, exact and partial span F1, Krippendorff's αU, γ |
| geometry (boxes, polygons) | matched IoU, detection F1, and chance-corrected σ, ks, detection α |
| free text | nothing |

So a 1–5 rating stored as a `radio` gets scored with a nominal metric, which
treats "1 vs 2" and "1 vs 5" as equally wrong and understates agreement badly.
Storing an ordered judgment in an unordered type is a measurement error, not a
cosmetic one.

## 4. How many annotators

`num_annotators_per_item` is the one that decides it. The other two shape the
edges.

| Key | Meaning |
|---|---|
| `num_annotators_per_item` | The target. Set this one. |
| `min_annotators_per_instance` | The floor before an item counts as done |
| `max_annotations_per_item` | A hard cap; `-1` for unlimited |
| `max_annotations_per_user` | How many dataset items **one annotator** is served. Defaults to all of them |

Setting the first three to the same number is harmless but says you were unsure.

`max_annotations_per_user` is the only key that decides how much one person is
asked to do. Attention checks and gold items are injected on top of it rather
than inside it, so enabling them does not shorten anyone's corpus. See
`assignment-and-agreement.md`.

Defaults worth arguing from: **1** when the labels are near-mechanical or the
data is being used to prototype, and nobody is going to report agreement. **3**
when there is any judgment involved and an agreement number will be reported —
it is the smallest number that lets a majority break a tie. **5+** for genuinely
subjective constructs, or when per-annotator reliability is itself the object of
study.

More annotators on fewer items beats fewer annotators on more items whenever
you do not yet know the labels are learnable. Find that out on 100 items before
spending the budget on 10,000.

## 5. Order

`assignment_strategy` takes: `random`, `fixed_order`, `active_learning`,
`llm_confidence`, `max_diversity`, `least_annotated`, `category_based`,
`diversity_clustering`, `batch`, `priority`, `psychometric`.

`random` is right unless there is a reason. Reasons: `fixed_order` when items
are a narrative and order carries meaning; `least_annotated` when you care most
about finishing every item; `active_learning` or `llm_confidence` when a model
is in the loop and the point is to spend annotator time where it changes
something.

Set `random_seed` if the ordering ever needs to be reproduced.

## 6. Quality control

Add these in order. Each costs annotator time, so stop when the risk is covered.

1. **`require_fully_annotated: true`** — no skipping questions. Nearly always
   right, and free.
2. **Agreement** — comes automatically once `num_annotators_per_item` is above
   1 and items overlap. Nothing to configure; read it on the admin pages.
3. **`gold_standards`** — items with known answers mixed in, with an accuracy
   floor. Use when annotators are paid strangers. Needs an items file and
   somebody to have written the correct answers.
4. **`attention_checks`** — items with an obvious answer, plus
   `attention_checks.min_response_time`. Catches clicking-through, which gold standards catch
   too, but attention checks are cheaper to author.
5. **`training`** — a qualification phase before real items. Use when the label
   scheme takes explaining. It is the only one of these that improves the
   annotations rather than just measuring them.
6. **`adjudication`** — a queue where a third party resolves disagreements. Use
   when you need one final label per item rather than a distribution.

The failure this list is built against: discovering after 10,000 items that one
annotator misread a label definition throughout.

The file formats for training, attention checks and gold standards are in
`quality-control.md`. All three can be enabled, validate clean and load zero
items, so check the count in the startup log rather than the config.

## 7. Before and after

`phases` orders what an annotator walks through: consent, instructions,
training, annotation, and post-study. Those five plus `prestudy` are the only
valid phase types, each non-annotation phase needs a page file, and none of it is
validated — `phases-and-pages.md` has the format. `surveyflow` is the older way
to hang survey pages either side.

**A consent page is not a default.** If the work involves human subjects, the
researcher's institution has wording, and inventing it is not your job. Ask.
When they give you the substance without wording, write plainly what they said,
covering what the study is, how long it takes, and that stopping is allowed
without penalty. Say that it is a draft to be replaced.

Instructions belong in `annotation_instructions`, which takes the text itself,
inline. A filename there renders as that filename. Label definitions live in it,
not only in the `description` of each scheme — the description is a reminder for
someone who has already read the definition.

## Three keys that change the answers

None of these is about appearance, and all three are one line on a `radio`,
`multiselect` or `select` scheme.

```yaml
- annotation_type: radio
  name: stance
  description: What stance does this take?
  labels: [Supports, Opposes, Neither]
  option_randomization: true      # per annotator, to spread order effects
  has_free_response: true         # adds "other, please specify"
```

**`option_randomization`** shuffles the choice order. Whichever option sits
first is picked slightly more often than it should be, and with one fixed order
that bias lands on the same label every time and is indistinguishable from a
real finding.

The shuffle is **seeded from the username and fixed for the whole study**. Alice
sees `Alpha Charlie Delta Echo Bravo` on every item of hers; bob sees a
different order, and the same one on every item of his. That spreads order
effects *across* annotators
rather than within one, which has two consequences: it does nothing at all on a
single-annotator task, and within one person's labels the bias still stands. It
cancels only across the pool.

It applies to `radio`, `multiselect`, `select` and `multirate`. Do not use it
where order carries meaning: a Likert scale reads low-to-high, and shuffling it
is nonsense.

**`has_free_response`** is the actual fix for the "no 'none of these'"
anti-pattern below. It adds a text box labelled "Other (please specify)" — pass
a dict with `instruction` to reword it — so an annotator who thinks none of the
labels fit says what they would have said instead. Read those answers after the
pilot. They are the label set the researcher has not written yet.

**`dynamic_options`** narrows the choices per item. The full label set still
lives in the config; a field on the item — `visible_labels` unless
`dynamic_options_field` names another — lists which of them stay, and the rest
are removed from the page. An item with no such field is not filtered, so the
default is "show everything" rather than "show nothing".

It is the answer to "the options depend on the item", which otherwise gets built
as one enormous label list with instructions telling annotators which parts to
ignore. Note the direction: you cannot introduce an option this way that the
config does not already declare. `radio`, `multiselect` and `select` only.

## Prefilled answers

`pre_annotation` seeds answers into the form; `ai_support` offers a model's
suggestion; `llm_labeling` labels the corpus first. `modes-and-subsystems.md`
routes to all three as features. The design question they raise is separate:
**an annotator shown a suggestion agrees with it more often than one who is
not.**

Prefilling is still worth doing — it is what makes correction passes cheap, and
cheap is often the point. It does change what the numbers mean:

- Agreement between annotators who saw the same suggestion measures agreement
  with the model, not with each other. Say so wherever the number is reported.
- A prefilled answer left untouched is not evidence the annotator considered it.
  If that distinction matters, `annotation_telemetry` records whether they
  interacted at all, and `export_include_annotation_changes` puts the revision
  trail into the export: every answer they moved off, with timestamps.
- Where the point is measuring the model, do not prefill the items you are
  measuring it on. Hold out an unprefilled slice.

Tell the researcher which of these applies before the run, not when they ask why
agreement is 0.95.

## Piloting

Before the full run: three annotators, 50–100 items, then look at the
disagreements. Almost every serious problem shows up there, and almost none of
them show up in a config review. Budget for the label definitions changing
after the pilot, because they usually do.

## Anti-patterns

These assume a fixed label set decided in advance. For open coding, see the note
under "The response format".

- **A single free-text box for a judgment you intend to count.** If it is going
  to become a number, make it a scale.
- **Labels that overlap.** If two labels can both be true, it is a
  `multiselect`, or the labels need rewriting.
- **No "none of these" and no "unclear".** Without them, annotators put
  genuinely unclear items somewhere arbitrary, and that noise is invisible
  afterwards.
- **A scale with unlabelled middle points.** See above.
- **Asking for confidence on everything.** It doubles the questions. Use it
  where you plan to filter on it.
- **Optional questions everywhere.** An optional question is one whose absence
  you cannot interpret.
