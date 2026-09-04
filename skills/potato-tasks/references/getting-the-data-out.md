# Getting the data out

"Where is my CSV" is the first question after the annotators finish, and the
answer surprises people: there isn't one until you make it. Decide the export
before handover and say so, because the researcher who finds out at the end is
the one who wanted COCO and got a directory of per-annotator JSON.

## Storage and export

Annotations live at `annotation_output/<user>/user_state.json`, one file per
annotator, and that is the only storage format. `output_annotation_format` looks
like it changes that, and never did; it is deprecated now, and the loader reads
it as `export_annotation_format`. Everything else is an export: a derived copy,
produced on a timer or on demand, that you can regenerate and can safely
delete.

Three ways to produce one:

```yaml
export_annotation_format: [csv, jsonl]   # on a timer, while the study runs
auto_export_interval: 60                 # seconds; writes to annotation_output/exports/<fmt>/
```

```bash
# on demand, against a running server
curl -H "X-API-Key: $(cat admin_api_key.txt)" -H "Content-Type: application/json" \
     -X POST -d '{"format":"coco"}' localhost:8000/admin/api/export
```

```bash
potato deploy pull config.yaml --dest ./collected    # from a hosted task
```

The admin route writes to the **server's** disk and hands back the paths — it is
not a download. On a host you cannot reach a shell on, `/admin/api/data/archive`
streams the whole task directory as a gzipped tar instead. `deploying.md` has
that path.

**One scheme keeps its answers somewhere else.** `multi_document_event` writes
the events themselves to `annotation_output/event_registry.json` — one registry
for the whole study, not one file per annotator:

```json
{"events": {"evt_f6ec517d3154": {
   "title": "Payments certificate outage",
   "slot_values": {"service": "Payments API", "cause": "expired certificate"},
   "member_doc_ids": ["r01"],
   "evidence": [{"slot_name": "scope", "doc_id": "r01", "span_start": 0,
                 "span_end": 30, "quoted_text": "Payments API returned 503s for",
                 "created_by": "s4@x.com"}],
   "created_by": "s4@x.com"}}}
```

Two consequences to decide about before you recruit. The per-annotator side is
missing entirely: on 2.8.2-11 the input holding which events a document belongs
to carries no `annotation-input` class, so `user_state.json` stays `{}` for that
scheme and the export has nothing in it. The registry file is the whole dataset.
The registry is also shared. Annotator 2 opens a document and sees annotator 1's
events already attached to it, `member_doc_ids` records no attribution, and
there is no second opinion to compute agreement from. Treat this as one
collaborative pass rather than a replicated one, and back the file up the way
you would back up `user_state.json`.

**A bad format name is silent until it matters.** `export_annotation_format` is
not checked at load, so `[csvv]` validates clean under `--strict`, boots clean,
and produces one runtime warning after the first save — by which point nobody is
reading the log. Check the name against the list below.

## Which format

Twenty-nine are registered. `GET /admin/api/export/formats` lists them with
descriptions against the running server; `potato preview` does not.

| They want | Format |
|---|---|
| A table, one row per annotator-item | `csv`, `tsv`, `jsonl` |
| The same at corpus scale, for pandas or DuckDB | `parquet` |
| To train an NER model | `conll_2003`, `conll_u` |
| To train a detector or segmenter | `coco`, `yolo`, `pascal_voc`, `mask_png` |
| To go back to the tool they came from | `cvat`, `labelme`, `darwin`, `cityscapes`, `kitti` |
| Tracking ground truth | `mot`, `davis` |
| Phonetics or linguistic tiers | `textgrid`, `eaf` |
| A ConvoKit corpus with the labels attached | `convokit` |
| Their qualitative codebook and quotes | `codebook`, `quotation_report` |
| Agent or coding-agent evaluation data | `agent_eval`, `coding_eval` |
| Preference pairs and SFT targets from corrections | `trajectory_correction` |
| Per-frame embodied episode labels | `episode_jsonl` |
| How the text was typed, or how the boxes were drawn | `keystrokes`, `annotation_telemetry` |
| It published | `huggingface` (see `publish` in `modes-and-subsystems.md`) |

The vision and linguistics formats are the reason to ask early: a researcher who
says "we'll train a detector on this" wants `coco` or `yolo`, and a task designed
without that in mind can produce geometry that does not survive the conversion.

## The CSV columns

Columns are derived from what was **stored** rather than from what the config
declares. One row per annotator per item, with a column per scheme-and-label:

```
instance_id,user_id,sentiment.positive
i1,alice,positive
```

Two consequences:

- A scheme nobody answered has no column, so an empty export is evidence about
  the annotations rather than about the exporter.
- After a scheme is renamed mid-study, the columns carry the **old** name, and
  keep carrying it. See `after-annotators-start.md`.

Item fields that were never displayed are still in the data and still exported,
which is how a condition label stays out of the annotator's view without being
lost.

## Consent and survey answers

```yaml
export_include_phase_data: false        # the default
export_include_annotation_changes: false
```

Phase responses — consent, pre-study, post-study surveys — are excluded from
exports unless you turn them on, and they are usually where the demographics and
the free-text sit. That default is doing real work. Turning it on is a decision
to move identifiable answers into a file people will pass around, so make it
deliberately and say so in the handover.

`export_include_annotation_changes` adds the revision trail: every answer an
annotator moved off, with timestamps. Useful for studying how people decide,
much larger, and not what anyone means by "the data".

## Agreement

The export holds answers. Agreement is computed on request, from the admin
API:

```bash
curl -H "X-API-Key: $(cat admin_api_key.txt)" localhost:8000/admin/iaa
```

Per scheme it reports the `kind` it inferred and the metrics that follow from
it. The `kind` is inferred from the schema type, so a rating stored as a `radio`
is scored as unordered — `assignment-and-agreement.md` has the table, and it is
worth checking before quoting a number at anyone.
