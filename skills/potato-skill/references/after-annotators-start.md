# After annotators start

Everything in this pack up to here is about the state before anyone has
answered anything. Once real answers exist the rules change: some edits are
free, one whole class of edit is silently destructive, and the questions the
researcher asks you stop being "does it render" and become "how is it going" and
"can we still change this".

## Safe and unsafe edits

| Change | Effect on work already done |
|---|---|
| Add items to the data file | Safe. Loaded at the next boot, offered to everyone, progress totals grow |
| Edit instructions, descriptions, the banner | Safe. Text only; nothing is keyed to it |
| Add or remove annotators | Safe |
| Change `num_annotators_per_item`, quotas, assignment strategy | Safe, but it changes who gets what next — read `assignment-and-agreement.md` first |
| Add labels to an existing scheme | Structurally safe, **methodologically not**. Everyone who finished chose from the old list |
| Add a new scheme | Collects nothing from anyone who already finished. See below |
| Rename a scheme | Silently discards the old answers from every report. See below |
| Change a scheme's `annotation_type` | Same as a rename, plus the stored values may no longer be the right shape |

The dividing line is that Potato tracks completion **per item**, never per
question. An item that was annotated stays annotated whatever it was annotated
with, so a question added afterwards is never put in front of the people who
already worked through the corpus.

## Renaming a scheme mid-study

Worth spelling out, because nothing errors and three separate surfaces report
three different things.

Given a task where three items were annotated under a scheme called
`sentiment`, and the config is then edited to call it `polarity` and to add a
second scheme `confidence`:

- **The annotator** who returns is shown "Thank You! You have completed the
  annotation task." They never see either question.
- **`/admin/api/overview`** reports `completion_percentage: 100.0`,
  `total_annotations: 3`, one completed user. The study looks finished and
  healthy.
- **`/admin/api/agreement`** reports `polarity: items_count 0` and
  `confidence: items_count 0`. Every configured scheme has nothing.
- **The CSV export** comes out with the column `sentiment.positive`, because
  exports are driven by what was stored rather than by the config.

So the dashboard says done, agreement says empty, and the file says a scheme
name the config does not contain. The boot log names it:

```
WARNING Saved annotations name 1 scheme(s) that annotation_schemes no longer
defines: sentiment (3 answer(s)). Items already annotated stay annotated...
```

That warning is the whole safety net. Read the boot log after any edit to
`annotation_schemes` on a task with data in it.

**If you have to add or rename a question after people have started**, there
are two honest options. Keep the old name and add the new question as a second
scheme, and only later annotators answer it. Or start a fresh
`output_annotation_dir` and re-run, and pay for the items twice. There is no
migration command, and hand-editing `user_state.json` is the one thing this pack
tells you never to do.

## Accounts do not survive a restart by default

The default authentication backend is in-memory. Registrations are never written
anywhere, so when the server stops, every annotator account goes with it — while
their annotations stay safely in `annotation_output/`. The annotator comes back,
cannot log in, re-registers under the same username, and is reattached to their
saved work, which mostly hides the problem until someone picks a different
username and starts the corpus again as a second person.

```yaml
authentication:
  user_config_path: user_config.json   # JSONL, one {username, password} per line
```

With that set, registration writes the account out with a salted hash and login
survives a restart. Set it on anything an annotator will come back to. It
matters most exactly where it is easiest to forget: `render` and `huggingface`
restart containers on their own, so a hosted study without it loses its logins
without anyone touching the server.

## Watching a live study

Every JSON route below needs `X-API-Key`. The key file appears the first time an
admin route is requested, not at boot — if you look for it immediately after
starting the server it will not be there yet.

```bash
curl -s -o /dev/null localhost:8000/admin          # makes the key file exist
K=$(cat admin_api_key.txt)
curl -H "X-API-Key: $K" localhost:8000/admin/api/overview
```

| Question | Route |
|---|---|
| How far along is the study | `/admin/api/overview` |
| Who has done what, and how fast | `/admin/api/annotators` |
| Do they agree | `/admin/iaa` (prefer this), `/admin/api/agreement` |
| Who is failing the attention checks | `/admin/api/quality_control` |
| Is anyone clicking through | `/admin/api/suspicious_activity`, `/admin/annotation-integrity` |
| Who is sitting on work they never finished | `/admin/api/stale_assignments` |
| What is one annotator's state | `/admin/user_state/<user>` |
| What happened to one item | `/admin/item_state/<item_id>` |
| Give me the data | `/admin/api/export`, `/admin/api/data/archive` |

`/admin/api/quality_control` answers `{"enabled": false, "message": "Quality
control not configured"}` rather than erroring when there are no checks, which
is a useful way to confirm from outside that the feature really is off.

## Fixing things while it runs

| Situation | What to do |
|---|---|
| An annotator cannot log in | `POST /admin/reset_password` with `{username, new_password}`, or `POST /admin/create_reset_token` to hand them a link |
| Someone holds items they abandoned | `GET /admin/api/stale_assignments`, then `POST /admin/api/reclaim_instance` with `{instance_id, username}`. Automatic reclaim is off unless `instance_reclaim` is configured |
| One person should do more, or fewer, items | `POST /admin/api/user/<username>/set_instances` with `{max_instances}`; `-1` is unlimited |
| Annotations were corrupted by the pre-2.7.2 single-select bug | `potato repair-annotations config.yaml` — dry run by default, `--apply` to write, and it backs up first |
| Something hand-edited `annotation_output/` | The same command is the only supported repair, and it only knows about that one corruption |

Wiping `annotation_output/` **while the server runs** resets nothing: item and
user state are already in memory, and the next arrival gets the completion page.
Stop, wipe, start.

## What to say at handover

At handover, three facts they cannot work out for themselves:

1. **The admin pages exist and need a key**, and where the key file is. Without
   this every JSON route returns a 403 that reads like a broken build.
2. **The questions are frozen once people start.** If they are unsure about a
   label set, now is when it is free to change and next week it is not.
3. **What restarting costs** — nothing, if `authentication.user_config_path` is
   set; every login, if it is not.
