# Potato annotation tasks

A Claude Code skill for building annotation tasks with
[Potato](https://github.com/davidjurgens/potato), the portable text annotation
tool.

It covers the whole job, not just the YAML: deciding what to ask annotators,
laying out the interface, wiring consent and training phases, adding attention
checks, running the study, watching it while it runs, and getting the
annotations back out.

## Install

```
/plugin marketplace add davidjurgens/potato-skill
/plugin install potato-tasks@potato
```

Potato has to be installed in whatever environment runs the commands, because
the skill's helpers import its registries and drive the `potato` CLI:

```bash
pip install potato-annotation
```

`SKILL.md` opens by checking for it.

## The files

| | |
|---|---|
| `skills/potato-tasks/SKILL.md` | What Claude Code loads when the skill fires |
| `skills/potato-tasks/references/` | 26 reference files, loaded on demand |
| `skills/potato-tasks/scripts/` | Seven helpers an agent runs rather than reconstructs |
| `AGENTS.md` | The same guidance for Codex and Cursor, which read this filename directly |

Three references are generated from Potato's registries by
`scripts/generate_references.py`: `annotation-types.md` (all 61 types, each with
a worked example lifted from a real project), `config-keys.md` and
`config-keys-nested.md`. The rest are hand-written and checked rather than
generated.

The references are also published at
<https://davidjurgens.github.io/potato-skill/>, for anyone who wants to read
them without installing anything.

## Other ways to install it

A skill is a directory, so it travels:

```bash
python scripts/package_skill.py
```

builds `dist/potato-tasks/` and `dist/potato-tasks.zip`. The directory is what
the Claude Agent SDK loads; the zip is what the Claude API accepts as an
uploaded skill. `--install-personal` copies it into `~/.claude/skills/`, making
it available in every project on the machine without a marketplace.

## Working on it

The guards need a Potato checkout, not just the installed package: the worked
example lives in `examples/advanced/full-study-skeleton/`, which is not in the
wheel, and the command-dispatch check reads `potato/flask_server.py`. A sibling
clone is found automatically; anywhere else, set `POTATO_REPO`.

```bash
git clone https://github.com/davidjurgens/potato ../potato
pip install -e ../potato
pip install -r requirements-dev.txt

python scripts/generate_references.py     # rebuild the generated half
pytest
mkdocs build --strict
```

What the tests check:

- The generated references match a fresh build, byte for byte.
- Every annotation type, display type, config key, operator, strategy name and
  command named anywhere in the prose exists. The hand-written references name
  around 140 identifiers, and a plausible wrong one is worse than no
  documentation, because an agent will use it.
- Every YAML sample is spliced into a working config and run through Potato's
  real validator; every JSON sample is pushed through the loader that reads it.
- The worked example boots a real server, and every feature it switches on
  reports a non-zero count in the log.
- The twelve counts stated in prose match the registries.
- The plugin manifests parse and agree with each other.

## Licence

GPL-3.0-or-later, the same as Potato.
