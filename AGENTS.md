# Working on a Potato annotation task

Potato is a web annotation platform. A task is one YAML config plus a data file.
This file tells you how to build one correctly.

## The loop

Do not write a config and hand it over. Run it through these steps first.

```bash
potato validate config.yaml --strict              # structural check
potato preview config.yaml                        # what form did I declare?
potato preview config.yaml --screenshot out.png   # what does it look like, did it break?
```

All three return promptly. `potato start config.yaml -p 8000` runs the task for
a human to click through, but **it does not return** -- it holds the server in
the foreground until killed, and will hang a non-interactive session
indefinitely. The screenshot step already boots a real server and shuts it down,
so nothing in this loop needs it. Background it if you genuinely want one
running.

`potato validate` runs the same checks `potato start` runs at boot, so passing it
means the server will accept the config. Its errors name the alternatives: an
unknown `annotation_type` comes back with the list of valid ones. `--strict`
turns unrecognized keys from a warning into a failure, which is how you catch a
typo that silently disabled a feature.

`--screenshot` is the step that catches what validation cannot. It boots the
task, opens it in a headless browser, and reports every uncaught exception,
`console.error` and failed request. A config can validate cleanly and still
render a broken interface, because most of the annotation UI is built by
JavaScript after the HTML arrives. Exit code is 0 only if the page rendered with
nothing to report.

## Deciding what to build

A config is the last step, and the decisions before it are the ones that are
expensive to reverse: what one annotator sees at a time, what they are asked,
how they answer, how many people answer each item, and how you find out whether
the answers are any good.

When a description leaves those open, decide the cheap ones yourself and confirm
the expensive ones -- the unit of annotation, the annotator budget, consent
wording, and anything involving identifiable people. Build with stated
assumptions rather than waiting on an answer.

Two that are easy to get wrong and expensive to discover late:

- **The response format decides the agreement metric.** Potato picks the metric
  from the schema kind, so a 1--5 rating stored as a `radio` is scored as
  unordered and "1 vs 2" counts the same as "1 vs 5".
- **`num_annotators_per_item` sets the count.** `min_annotators_per_instance` is
  a floor, `max_annotations_per_item` a cap.

The Claude Code skill installed alongside this file has the full versions:
`.claude/skills/potato-tasks/references/designing-a-task.md`,
`asking-the-experimenter.md`, and `building-the-ui.md`.

## Start from a working example

There are 213 example projects. Copying one beats assembling a config from field
lists, and every one of them is checked in CI.

```bash
# Search the catalog
python -c "from potato.server_utils.examples_manifest import search_examples; \
           print([e['dir'] for e in search_examples(annotation_type='span')])"
```

The catalog is also published as JSON at
`potato/schemas/potato-examples.manifest.json`. Each entry records the annotation
types and display types a config uses, the features it switches on, and the
command that runs it.

## The minimum config

Four keys are always required, plus a data source:

```yaml
# yaml-language-server: $schema=https://potatoannotator.readthedocs.io/en/latest/schemas/potato-config.schema.json
annotation_task_name: Sentiment Annotation
task_dir: .
output_annotation_dir: annotation_output/
data_files:
  - data/items.json
item_properties:
  id_key: id
  text_key: text
annotation_schemes:
  - annotation_type: radio
    name: sentiment
    description: How does this text feel?
    labels: [positive, neutral, negative]
```

Keep the first line. It switches on live validation in VS Code, JetBrains, Zed
and Helix, and it tells the next agent where the contract is.

The data file is JSON, JSONL, CSV or TSV. JSON may be an array of objects or one
object per line. Every object needs the fields named by `id_key` and `text_key`.

## Rules that will bite you

**Paths resolve against `task_dir`, and anything resolving outside it is
rejected.** This is a security check, not a convenience. If you see
`ConfigSecurityError: Path ... is outside the project directory`, you are running
from the wrong directory or pointing outside the project.

**`annotation_type` must come from the registry.** There are 61 of them. Do not
guess a plausible-sounding name. `sentiment` and `classification` are not types.

```bash
python -c "from potato.server_utils.schemas.registry import schema_registry; \
           print(schema_registry.get_supported_types())"
```

**Unknown config keys only produce a warning.** A typo'd key is silently ignored
and the feature you thought you enabled is off. Run `potato validate --strict`,
which turns those warnings into a failure.

**Phase-level `annotation_schemes` replace the top-level list.** They do not add
to it. Having both is an error.

**Never hand-edit anything in `output_annotation_dir`.** The server rewrites
those files wholesale.

## Reference

Every key, with its type, default and description, is in
`docs/configuration/config_reference.md`, and the same information machine-readable
is in `potato/schemas/potato-config.schema.json`.

From Python:

```python
from potato.server_utils.config_key_docs import get_key_doc
get_key_doc("attention_checks.frequency")

from potato.server_utils.schema_examples import example_scheme_for
example_scheme_for("bws")   # a scheme from a config that really runs
```

## MCP

If the Potato MCP server is connected, use its tools instead of the shell:
`list_annotation_types`, `describe_annotation_type`, `list_examples`,
`validate_config`, `render_task_screenshot`. Same answers, and
`render_task_screenshot` hands you the rendered page as an image.

```bash
potato mcp config --root .    # prints a client config block
```

## Where to read more

- Configuration reference: `docs/configuration/config_reference.md`
- Every annotation type: `docs/annotation-types/schemas_and_templates.md`
- Full docs in one file: <https://potatoannotator.readthedocs.io/en/latest/llms-full.txt>
- Curated index: <https://potatoannotator.readthedocs.io/en/latest/llms.txt>
