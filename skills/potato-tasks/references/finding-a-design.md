# Starting from a published design

Three sources of prior art, and they cover different things. Reaching for the
wrong one wastes an hour.

| Source | What it gives | What it does not |
|---|---|---|
| `examples/` in Potato, 214 of them | One scheme or display type demonstrated cleanly | Question wording worth copying; a whole study |
| **potato-showcase**, 440 designs | Real label sets, real question wording, written instructions, the paper each came from | Any workflow at all |
| `worked-example.md` | The whole study: consent, instructions, training, checks, survey | Anything about your construct |

The usual route on a new task is showcase for the questions, worked example for
the workflow, `examples/` when one scheme is behaving oddly.

## The showcase

<https://github.com/davidjurgens/potato-showcase> — 440 annotation task designs,
most built from a published paper or dataset. Each is a folder with
`config.yaml`, `metadata.json` (title, paper, dataset, tags, complexity) and
`sample-data.json`.

Two things make it worth checking before writing a scheme from a field list:

- **The wording is not invented.** A label set a paper used and reported
  agreement on has survived a pilot. Yours has not.
- **281 of the 440 carry written `annotation_instructions`** — the part of a
  study this pack otherwise leaves you to write from nothing. See
  `writing-guidelines.md` for what to do with them.

And the limit, which is sharp: **no design in the showcase has a `phases` block,
a consent page, a training round or a post-study survey.** Zero. They are task
designs, not studies. Take the questions from there and the study around them
from `worked-example.md`.

## Searching it

```bash
python .claude/skills/potato-tasks/scripts/find_design.py --type span --category text
python .claude/skills/potato-tasks/scripts/find_design.py --query "dialogue safety" --with-instructions
python .claude/skills/potato-tasks/scripts/find_design.py --show text/education/mathdial-tutoring-dialogue
```

Filters: `--type` (repeatable, all must be present), `--display-type`,
`--category`, `--complexity`, `--with-instructions`, `--with-paper`, `--query`.
`--json` for the raw records. `--show <id>` prints the metadata and the whole
config.

The script reads `showcase.manifest.json`, which is built by
`scripts/generate_manifest.py` in the showcase repo. It looks for a clone in the
obvious places and in `$POTATO_SHOWCASE`, and falls back to downloading the
manifest from GitHub. Pass `--showcase <dir|path|url>` to be explicit.

If you have a clone but no manifest, build it once:

```bash
cd path/to/potato-showcase && python3 scripts/generate_manifest.py
```

`--show` prints the config only from a local clone; without one it prints the
GitHub URL.

## Taking a design without inheriting its mistakes

Copy the folder, then go through this:

- **Re-read every label against your data.** The taxonomy was built for their
  corpus. A category with nothing in yours is worse than no category — it
  attracts arbitrary answers.
- **Check for a residual option.** Published schemes often assume trained
  annotators and a discussion round, so some have no "unclear".
- **Instructions are a starting draft, not the researcher's guidelines.** They
  are what the showcase design's author wrote, sometimes condensed from the paper. Name
  the source in `DESIGN.md`, and put the real definitions past the researcher.
- **Cite it.** `metadata.json` carries `paperReference`, `paperUrl` and a BibTeX
  `citation`. If the scheme came from a paper, the study using it says so.
- **The config is the truth, not the metadata.** `metadata.annotationTypes` is
  hand-maintained and six designs disagree with their own config. The manifest
  records both; `annotation_types_in_config` is the one that runs.
- **Add the workflow.** No consent, no instructions phase, no training,
  no checks. That is all yours.
