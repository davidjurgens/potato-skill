# Writing the guidelines

The config has a validator, a schema and four generators behind it. The text an
annotator reads has none of that, and it is where most of the disagreement in a
finished dataset comes from. A label set that looks obvious in a config review
splits three ways in a pilot, and the split is nearly always the guidelines
rather than the annotators.

The guidelines are not an accessory to the annotation scheme; in the standard
account they are *part* of it. Finlayson and Erjavec define a scheme as "a
linguistic theory, a derived model of a phenomenon of interest, a specification
that defines the actual physical format of the annotation, and the guidelines
that explain to an annotator how to apply the specification to linguistic
artifacts" — and open with the flat statement that "creating linguistic
annotations requires more than just a reliable annotation scheme", because "even
the most carefully designed scheme will not answer a number of practical
questions about how to actually create the annotations."

This is also one of the few places in study design where the effect on your
numbers has been measured. Bayerl and Paul's meta-analysis of 96 annotation
studies and 346 agreement indices found seven factors that consistently move
reported agreement, and three of them are decisions made here: the number of
categories in the coding scheme, whether annotators received training, and the
intensity of that training.

Potato ships a worked model of everything below:
`examples/advanced/long-guidelines/` — a politeness task with an instructions
phase, a banner, and a full codebook document. Read `media/codebook.html` before
writing your own.

## The four surfaces

| Surface | Read | Holds |
|---|---|---|
| `instructions` phase (`file:` an `.html` or `.jsonl`) | Once, before the first item | The teaching material. As long as it needs to be |
| `annotation_instructions` | On every annotation page, collapsible, open by default | The reminder. The rules that settle most items, in a few lines |
| `annotation_codebook_url` | On demand, a Codebook button in the nav bar, new tab | The authoritative document, when it wants a page of its own |
| `description` per scheme | Beside the question itself | One line. The question as an annotator would ask it |

The phase teaches, the banner reminds, the button holds the document, the
description labels the question. Putting the codebook in the banner is the
common mistake: it is expanded by default and sits above the item, so a long one
pushes the questions below the fold on every single item of the study.

`annotation_codebook_url` takes any URL. Serve the document out of
`media_directory` and it ships with the project rather than depending on a
Google Doc that someone will later move.

## What a definition has to do

The test for a label definition is not "does this describe the concept" but
"can two people who disagree use this to find out who is right". Those are
different documents.

*Impolite: messages that are rude or disrespectful* describes the concept and
settles nothing. It hands the annotator the same judgment they already had.

The structure to copy is MacQueen et al.'s, developed at the CDC for team-based
coding and now the standard codebook format in qualitative research. Their
codebook entry has **six components: "the code, a brief definition, a full
definition, guidelines for when to use the code, guidelines for when not to use
the code, and examples."** The paper's stated purpose is
"how specific codebook features can improve intercoder agreement among multiple
researchers."

Two of those six are the ones that do the work, and they have names worth
knowing. The when-to-use and when-not-to-use guidelines are the **inclusion
criteria** and **exclusion criteria**. The exclusion half arrived in that
literature as a section per code titled "Differentiating (blank) from Other
Processes" — its whole job is to separate a label from the ones it gets confused
with.

In a Potato config that becomes:

1. **The label**, as it appears in `labels:`.
2. **The one-line rule**, phrased as something you can check. This is what goes
   in the banner and, condensed further, in the scheme `description`.
3. **The full definition** — inclusion criteria. What counts, concretely, in the
   forms it takes in *this* data.
4. **Exclusion criteria.** What does not count, especially the things that look
   like it, and **the nearest neighbour**: the label it will actually be
   confused with, and the difference.
5. **Examples**, below.

Four and five are the ones people skip and the ones that pay. Most confusion is
between two specific labels rather than spread evenly, and the pair is
predictable before the pilot: your two most similar labels.

## Tie-break rules

The highest-value paragraph in any guideline document is the list of rules that
resolve the cases where two labels both look right. Written before the pilot
they are guesses; written after, they come from the actual disagreements and
each one measurably shrinks the spread.

The example codebook states four, and states why each exists:

> **Rule 2 — Terse is not impolite.** This is the single largest source of
> disagreement in this task: it accounted for 38% of the adjudicated conflicts
> in round 1. A bare imperative with no pressure cue ("Send me the slides before
> the meeting.") is Neutral.

Number them. Annotators refer to them by number in adjudication, and a numbered
rule can be cited in the paper.

## Examples have to include the hard ones

Three kinds, and a set with only the first is worse than none, because it
teaches annotators the task is easy:

- a clear positive
- a clear negative, ideally one that superficially resembles the positive
- **a borderline case, with the ruling and the reason**

Take them from the data being annotated, and cite the item id. An invented
example is an example of your idea of the task. A real one is evidence, and when
someone challenges the ruling later you can both look at the same item.

## Edge cases already ruled on

A table, appended to as the study runs. Two columns: the case, the ruling.

| Case | Ruling |
|---|---|
| Message is only a link, or only a file | Neutral. There is no politeness work either way |
| Message quotes someone else being rude | Rate the writer's own words, not the quotation |
| Message is in a language you do not read fluently | Skip it. A guess is indistinguishable from a judgment in the exported data |

This table is the single most useful thing you can hand a second annotator, and
it is free: every entry is a question somebody already asked.

## Deliberate scope exclusions

> **Rule 4 — Ignore formatting and typos.** All-caps, missing punctuation and
> spelling errors are not politeness signals here. This is a deliberate scope
> decision, not an oversight.

Annotators route around what looks like an omission, silently and
inconsistently. One clause stops that.

## The unclear contract

If the label set has an "unclear" or "none of these" option — and it nearly
always should — the guidelines have to say what it means, or annotators will
each pick their own reading. It is one of:

- **the item genuinely does not decide** (a real finding, keep it), or
- **I cannot tell from what I was shown** (a data or context problem), or
- **I do not know enough to judge** (a skip; a guess here is worse than nothing)

They are different things and they want different handling downstream. Pick one
per option and say so. If two of them matter, that is two options.

## Length

Nobody reads a 4,000-word banner. They will read a 4,000-word codebook once, at
the start, if the banner gives them the ten lines that cover most items and the
codebook is one click away.

A rough division that works: the scheme `description` is one line, the banner is
under 200 words, and the codebook is however long the construct needs.

## Versions and change logs

Guidelines that change mid-study split the data: items annotated before and
after are annotated under different instructions, and nothing in the output
records which. Put a version number and a change log at the bottom of the
codebook.

> 2.3 — added rule 6 (emoji are tone-neutral) and the autoreply edge case.

If a change is big enough to alter past labels, say so in the handover and treat
the earlier items as a separate round rather than quietly mixing them.

## Iterating from the pilot

The pilot is what produces real guidelines. Three annotators, 50–100 items, then
read the disagreements one at a time.

This loop has a name. Pustejovsky and Stubbs's **MATTER** cycle — Model,
Annotate, Train, Test, Evaluate, Revise — contains a subcycle, **MAMA**
(Model-Annotate-Model-Annotate), which exists precisely to iterate between the
model and pilot annotations "to increase the quality of the annotation scheme
before investing the full amount of time and energy annotating the complete
corpus." Writing guidelines once and launching skips it.

**Treat every disagreement as a guideline defect until you have shown it is
not.** The alternatives — the annotator was careless, the item is genuinely
ambiguous — are real but rarer, and both are cheap to check afterwards. Working
that way turns a disagreement list into a tie-break rule list.

Two Potato surfaces feed this loop:

- `training` items carry an `explanation` shown with the mark. It is the one
  place in a study where you can correct a misreading before it reaches 500
  items — write it, and write it as the reason rather than the answer. Training
  is one of the factors Bayerl and Paul found moves agreement, along with how
  intensive it is, so this is not a nicety.
- `/admin/iaa` gives agreement per scheme. A scheme far below the others is
  usually one label pair, and the pair names the rule you are missing.

Budget for the definitions changing after the pilot. They usually do.

## Anti-patterns

- **Defining a label with a synonym of itself.** "Toxic: content that is toxic."
- **"Use your best judgment."** It is what the annotator was already doing; it
  is what you were supposed to replace.
- **Examples that are all easy.** They set the expectation that hesitation means
  the annotator is doing it wrong.
- **A taxonomy with no residual category.** See `designing-a-task.md`.
- **Rules that contradict the label set.** If the guideline says "when torn,
  choose Neutral" and there is no Neutral, one of the two is wrong.
- **The codebook only in the banner.** It pushes the questions below the fold on
  every item.
- **Guidelines written after the config.** The label set is a claim about the
  construct; writing the definitions is how you find out the claim is wrong,
  and it is much cheaper before the data file is built.

## Before you hand it over

- [ ] Every label has a rule, what counts, what does not, and its nearest neighbour
- [ ] The two most confusable labels have a stated tie-break
- [ ] At least one borderline worked example per label, cited by item id
- [ ] The "unclear" option says which of the three things it means
- [ ] Every deliberate scope exclusion is marked as deliberate
- [ ] The banner is short enough that the first question is above the fold
- [ ] A version number and a change log
- [ ] Someone who was not in the design conversation labelled ten items with it

The last one is the only real test. Everything above it is how to pass it.

## What to ask the researcher

Label definitions are usually **theirs**, not yours: they carry the construct
the paper is about, and getting them wrong invalidates the study rather than
costing a re-render.

Ask for their existing definitions before writing any — a codebook from a
previous round, the paper the scheme comes from, or an annotation manual. If
they have one, use their wording and their examples.

If they have none, draft the four parts per label from what they told you, mark
every definition as a draft, and put the borderline cases you could not settle
at the top of `QUESTIONS.md`. Say plainly that these are the sentences that
decide what the dataset means.

`potato-showcase` is the other place to look: 281 of its 440 designs carry
written instructions, most drawn from a published annotation scheme. See
`finding-a-design.md`.

If the annotators are a paid crowd rather than trained coders, Sabou et al.'s
best-practice guidelines for crowdsourced corpus annotation are the thing to
read alongside this file — the constraints are different when the reader is
anonymous, unbriefed and paid per item.

## Sources

- MacQueen, McLellan, Kay and Milstein, "Codebook Development for Team-Based
  Qualitative Analysis", *Cultural Anthropology Methods* 10(2):31–36, 1998. The
  six-component codebook entry, and inclusion/exclusion criteria.
  <https://qualquant.org/wp-content/uploads/text/MacQueen%20et%20al%201998.pdf>
- Bayerl and Paul, "What Determines Inter-Coder Agreement in Manual Annotations?
  A Meta-Analytic Investigation", *Computational Linguistics* 37(4):699–725,
  2011. <https://aclanthology.org/J11-4004/>
- Finlayson and Erjavec, "Overview of Annotation Creation: Processes & Tools",
  in Pustejovsky and Ide (eds), *Handbook of Linguistic Annotation*, Springer,
  2016. <https://arxiv.org/abs/1602.05753>
- Pustejovsky and Stubbs, *Natural Language Annotation for Machine Learning*,
  O'Reilly. The MATTER and MAMA cycles.
- Sabou, Bontcheva, Derczynski and Scharl, "Corpus Annotation through
  Crowdsourcing: Towards Best Practice Guidelines", *LREC 2014*, 859–866.
  <https://aclanthology.org/L14-1412/>
