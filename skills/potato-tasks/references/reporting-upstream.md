# Reporting a bug or asking for a feature

When a task will not do what the researcher needs, the answer is one of three
things, and only the third belongs on GitHub as a feature request.

| What it is | How you know | What to do |
|---|---|---|
| A config mistake | `--strict` fails, or the boot log says `Loaded 0 <something>` | `troubleshooting.md`. Fix it yourself |
| A bug in Potato | It does something other than what it documents | File a bug |
| A gap | It does exactly what it documents, and that is not enough | File a feature request |

The order matters. The first is by far the most common, it is the only one you
can fix in the next minute, and a bug report that turns out to be a typo costs
a maintainer more than it costs you.

## Before you call it a bug

Three checks, none of which take long.

**Run `potato validate config.yaml --strict`.** A misspelled key inside a block
Potato treats as opaque is accepted, ignored, and never mentioned again, so the
feature it was meant to configure simply does not happen. Without `--strict`
that is a warning you will not read. This is the single most common cause of
"the config is right and nothing happens".

**Read the boot log.** `Loaded 0 training items`, `Loaded 0 attention checks`
and their siblings mean the side file was found and rejected, usually for a
missing required field. The count is the diagnosis.

**Check what you measured, not what you inferred.** A rendered page tells you
what an annotator sees and not what survives; `user_state.json` tells you what
survives and not what they saw. Where the claim spans both — "the answer is not
being saved" does — look at both before writing it down. Reading four strings
out of a served page is not the same as four things having rendered, because
the page also carries the JavaScript that would have rendered them.

## Before you ask for a feature

Say what the closest existing thing is and why it does not fit. That sentence
is what a maintainer acts on, and writing it is also how you find out the
feature already exists, which happens often enough to be worth the two minutes.

- `annotation-types.md` has every annotation type with its fields.
- `config-keys.md` and `config-keys-nested.md` have every documented key.
- `modalities.md` and `agent-traces.md` route a medium or a trace shape to the
  display and scheme that handle it.
- `find_design.py --query "<what you are doing>"` searches published designs.
- With the MCP server connected, `describe_annotation_type` and
  `describe_display_type` answer the same question against the live registry.

A request that names the type it tried, quotes the field list, and says which
field is missing is a different document from one that says Potato cannot do
dialogue.

## The helper

`scripts/report_issue.py` assembles the report. It collects the things every
report needs and a reporter never has to hand, and it will not file anything on
its own.

```bash
python .claude/skills/potato-tasks/scripts/report_issue.py bug \
    --title "Waveform never generates for media_directory audio" \
    --observed "every POST to /api/waveform/generate returns use_client_fallback: true" \
    --expected "a cached waveform, as audio_annotation documents" \
    --repro "potato start config.yaml -p 8000, open an item, watch the network tab" \
    --config config.yaml --log server.log --data data/items.json
```

```bash
python .claude/skills/potato-tasks/scripts/report_issue.py feature \
    --title "Per-utterance audio in a dialogue display" \
    --goal "annotate a voice-agent call where each turn is its own recording" \
    --tried "audio_dialogue and speech_transcript both resolve one file per item" \
    --needed "turn entries that each carry their own audio url"
```

It writes `potato-issue-<kind>.md`, prints the body, and prints a GitHub URL
with the title and body already filled in. What it adds on top of what you
typed:

- **The version, asked of Potato rather than reconstructed.** If the installed
  Potato answers `potato --version`, that output goes into the report verbatim.
  Nothing outside Potato can work the answer out reliably: on one machine on
  2026-09-09 the installed metadata said 2.7.0 while the source said 2.8.2,
  because dist-info is only rewritten on install; the same call answered 2.8.2
  from inside the Potato repository, where a local `potato_annotation.egg-info`
  shadows the site-packages record; and `potato.__version__` was absent from
  every other directory, because a stale `site-packages/potato/` holding only
  `templates/` made `potato` resolve as a namespace package while each submodule
  still imported fine. Releases up to 2.7 have no `--version` -- it exits 2 with
  an argparse usage block -- and the helper then falls back to the metadata
  version plus the commit, which pip records for an editable install, and says
  in the report that the number may lag the source.
- **Whether the config passes `--strict`**, with the output. This is the check
  above, done for you and shown to the reader.
- **The data by shape** — field names and value types of the first record, with
  a count. Never the values, because those are someone's corpus.
- **A duplicate search.** GitHub's issue search ANDs bare terms, so the obvious
  query matches nothing however many duplicates exist; the helper ORs the
  distinctive words and ranks what comes back by how much of your title each
  result shares. It says so when the search could not run, which is not the
  same answer as finding nothing.

## Redaction

Configs hold `secret_key`, `ai_support.ai_config.api_key`, crowd credentials
and annotator email addresses, and log tails hold bearer tokens. The helper
removes them before anything is written: any value under a key named like a
secret, anything shaped like an API key or a token, email addresses, and the
home directory out of every path. It then prints what it removed and how often,
because a redactor you cannot audit is worse than no redactor.

It does **not** remove things that are not secrets but might still be yours:
endpoint hostnames, task and file names, label vocabularies, item ids, and any
prose you typed into `--observed`. Read the body before it goes anywhere. That
is what the printed copy and the report file are for.

## Filing it

Two paths, and both of them need the person whose study it is to say yes first.

**By hand.** Open the prefilled URL. Nothing needs installing and the person
sees the form before anything is public.

**With `gh`.** Add `--submit --confirm`. Both flags are required, and the helper
refuses to file a body still holding a `_(fill this in)_` placeholder.

```bash
python .claude/skills/potato-tasks/scripts/report_issue.py bug \
    --title "..." --observed "..." --expected "..." --repro "..." \
    --config config.yaml --submit --confirm
```

It files under whichever account `gh` is logged in as, on a public repository,
and it cannot be withdrawn. Show the body and get an answer before passing
`--confirm`. `--label` needs write access on the repository, which a reporter
usually does not have; the kind is in the title as `[bug]` or `[feature]`
either way.

## What I have and have not verified

Run against Potato 2.7.0 on 2026-09-09, with `gh` 2.85.0:

- Redaction, on a config carrying `secret_key`, an `api_key`, an authorized-user
  list of email addresses, a bearer token in the log, and absolute paths under
  the home directory. None of the five appears in the report.
- Both version branches. Against a Potato that answers `potato --version`, the
  report carries that output unchanged. Against one that does not -- a stub on
  `PATH` exiting 2 with a usage block, which is what 2.7 and earlier do -- the
  fallback gives the metadata version, the commit from pip's editable record,
  and a line saying the number can lag the source.
- The duplicate search, both ways. A title sharing three words with an existing
  issue returned it; four titles with no duplicate returned nothing rather than
  filler. Rate-limited and offline both report themselves.
- Both refusals: `--submit` without `--confirm`, and `--submit` on a body with
  placeholders. Each exits 2 and files nothing.
- The URL falls back to the bare `/issues/new` when the body is too long to
  carry in a query string.

**Not verified: the `gh issue create` call itself**, because verifying it means
filing a real issue on a public repository. The flags it passes are the ones
`gh issue create --help` documents, and the body goes through `--body-file`
rather than an argument. Treat the first real `--submit` as the test.
