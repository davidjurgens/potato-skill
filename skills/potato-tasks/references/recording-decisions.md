# Recording the decisions

A config records what the task *is*. It does not record why the unit of
annotation is the sentence rather than the document, why three annotators, or
which of those choices you made up because the brief did not say. The researcher needs
that to write a methods section, and the next person to touch the task needs it
to know what is safe to change.

Write `DESIGN.md` next to the config, and keep it to what a config cannot say:

```markdown
# Design record

**Unit of annotation.** One forum post. Threads were the alternative; posts won
because the research question is about individual claims.

**Questions.** Category (4 options, `Unclear` included so annotators are not
forced), severity (3-point ordinal, so agreement is scored as ordinal), and a
free-text follow-up shown only when the category is `Unclear`.

**Annotators per item.** 3, to get a chance-corrected agreement figure. 12 items
each, which is the whole corpus, so every annotator sees everything.

**Quality control.** Two practice items with model answers, one attention check.
No gold standards: annotators are known colleagues, not paid strangers.

**Assumed, not confirmed:** the severity scale is 3-point; the researcher said
"low/medium/high" in passing and never confirmed the wording. Ask before launch.
The consent text is a placeholder and must be replaced with the approved wording.

**Reconsider first:** the 4-way category. If agreement on it comes back below
about 0.5, the labels are the problem, not the annotators.
```

Keep the assumptions separate and explicit. That paragraph is what makes the
document worth opening — a design record that reads as if every choice was
deliberate hides the ones that were not, and those are the ones that need
checking.

`QUESTIONS.md` is the other half: things you could not decide at all. Both, next
to the config, alongside something that runs.

## Estimating effort

The first thing a researcher asks about a design is what it costs, and the
config already contains most of the answer:

```bash
python .claude/skills/potato-tasks/scripts/estimate_effort.py config.yaml --rate 15
```

It reads the item count, the schemes, `num_annotators_per_item`,
`max_annotations_per_user` and the quality-control files, and reports how many
annotators are needed, how long each one is doing, total hours, and a cost if you
give it a rate. It prints its assumptions with the number; reading speed and
per-question times move the total most, so change those and re-run rather than
quoting one figure.

This is the cheapest place to catch a design that cannot be afforded. Three
annotators on 5,000 items with a span scheme is around 200 hours of annotation,
and it is much better to find that before the instructions are written.

## The assumptions in the estimate

`estimate_effort.py` prints its assumptions with the number. Three of them are
worth arguing with before quoting a figure to anyone:

- **Reading speed.** The default is 240 words a minute, which is about right for
  skimming familiar prose and much too fast for a legal clause or a transcript.
  `--wpm 120` on hard material can double the total.
- **Per-question times.** They come from a table inside the script: 4s for a
  radio, 45s for a span, 90s for a segmentation mask. They are order-of-magnitude
  right and no better. If the task is unusual, time yourself on five items and
  edit the table.
- **Nothing for the instructions page, and no breaks.** A real annotator reads
  the instructions once, gets slower, and stops. Treat the number as the floor.

The parts it does get exactly right, because they are in the config: the item
count, the number of judgements, how many annotators the quota implies, and how
many extra items each person sees because of training and quality control.
