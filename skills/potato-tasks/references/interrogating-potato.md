# Using the tools as oracles

Roughly forty config blocks take an object and document nothing about its
contents, including `training`, `phases`, `surveyflow`, `quality_control` and
`adjudication`. Guessing key names one at a time is slow, and a wrong guess is
usually silent rather than loud. Every side-file format in this pack was
recovered with the four methods below.

Do this in a scratch directory with a two-item data file, not in the real
project: booting writes `project.sqlite`, `layouts/` and `annotation_output/`.

## 1. The validator enumerates recognized sub-keys

One level down, and no further. Put a batch of candidate names in the block and
run `--strict`. Everything it *rejects* is definitely wrong, and it suggests near
misses:

```
Unrecognized config key 'training.show_answers'. Did you mean: 'feedback'?
Unrecognized config key 'training.passing_score'. Did you mean: 'passing_criteria'?
```

**An ignored key proves nothing on its own.** Validation descends two levels, so
`training.feedback` is checked and `training.feedback.anything` is not. A
plausible-looking sub-sub-key passes `--strict` and does nothing — that is how a
wrong `gold_standards.accuracy.min_accuracy` survived into an earlier draft of
this pack. At depth three or more, fall back to the key documentation
(`config-keys-nested.md`, `get_key_doc`) and to method 3.

Warnings are also suppressed while there are hard errors, so fix the errors first
or you will think the block is clean.

## 2. Type errors name the shape

`training.feedback must be a dictionary`,
`gold_standards.mode must be one of: training, mixed, separate`. Feed it the
wrong type on purpose. This is the fastest way to learn whether a key wants a
scalar, a list or a dict, and several blocks accept only the dict form despite
being documented as either.

## 3. The boot log on a bad side file

How much it tells you depends on the loader. Gold standards says
`missing gold_label`; training says `missing required fields` and dumps the
instance without naming anything.

When the message is unhelpful, delta-debug it. Put ~40 plausible keys on one
item, confirm it loads, then drop half, boot, and keep the half that still works.
Six boots gets you a minimal set.

```bash
python .claude/skills/potato-tasks/scripts/boot_and_check.py config.yaml -p 8123 --json
```

reports the `Loaded N` counts as data, which makes that loop scriptable rather
than a grep each time.

## 4. Errors that enumerate valid values

`Unknown phase: x`, `annotation_type must be one of: …`,
`display type X does not support span annotation`. Provoke them deliberately —
an invalid value is a cheap way to get the complete valid set, and it is
current by construction where a doc page may not be.

## Ask the package directly

Before any of the above, the registries answer most questions without a server:

```python
from potato.server_utils.config_key_docs import get_key_doc
from potato.server_utils.schema_examples import example_scheme_for
from potato.server_utils.examples_manifest import search_examples

get_key_doc("attention_checks.frequency")
example_scheme_for("bws")
search_examples(annotation_type="span", display_type="image")
```

These read the same tables the server enforces, so they cannot be out of date
with the running code the way a doc page can.
