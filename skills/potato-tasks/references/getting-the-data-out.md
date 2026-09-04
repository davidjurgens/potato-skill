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

31 formats are registered. `GET /admin/api/export/formats` lists them with
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
| To open it in NVivo, MAXQDA or ATLAS.ti | `qdpx` |
| Agent or coding-agent evaluation data | `agent_eval`, `coding_eval` |
| Preference pairs and SFT targets from corrections | `trajectory_correction` |
| Per-frame embodied episode labels | `episode_jsonl` |
| How the text was typed, or how the boxes were drawn | `keystrokes`, `annotation_telemetry` |
| The single resolved label per item, after adjudication | `adjudication` |
| It published | `huggingface` (see `publish` in `modes-and-subsystems.md`) |

The vision and linguistics formats are the reason to ask early: a researcher who
says "we'll train a detector on this" wants `coco` or `yolo`, and a task designed
without that in mind can produce geometry that does not survive the conversion.

## The CSV columns

Columns are derived from what was **stored** rather than from what the config
declares. One row per annotator per item, with a column per scheme-and-*label*:

```
instance_id,user_id,sentiment.Negative,sentiment.Positive,severity.Moderate,issues.Price
r03,alice@x.com,Negative,,Moderate,Price
r02,alice@x.com,,Positive,,
```

That is one column per label an annotator actually chose, not one column per
scheme. A three-label `radio` becomes three sparse columns and there is no
`sentiment` column anywhere in the file, so the first thing anyone does with a
Potato CSV is coalesce them. Warn whoever receives it: a researcher who opens
it expecting one column per question reads the file as broken. Driven on
six schemes and three annotators, 23 rows came out as 17 columns.

Three consequences:

- A scheme nobody answered has no column, so an empty export is evidence about
  the annotations rather than about the exporter.
- A label nobody chose has no column either, so the column set is not stable
  across two runs of the same study.
- After a scheme is renamed mid-study, the columns carry the **old** name, and
  keep carrying it. See `after-annotators-start.md`.

Spans arrive as one `<scheme>._spans` column holding a JSON array of
`{schema, name, title, start, end, id, target_field, text}` objects — the
offsets and the words they cover, sliced server-side, so the two cannot
disagree:

```
[{"schema": "evidence", "name": "Evidence", "start": 23, "end": 39,
  "target_field": "body", "text": "price I expected"}]
```

**The item is not in the export.** csv, tsv and jsonl carry `instance_id`,
`user_id` and the answers, and nothing else: not the annotated text, not the
image URL, not the fields you never displayed. Verified on a study whose items
carried `body`, `photo`, `sku` and `batch`. None of the four appears in any of
the three. Whoever gets the CSV has labels keyed by `instance_id` and has to
join back to the data file to find out what was labelled, so hand over the data
file with it. `parquet` is the exception.

### The parquet export

`parquet` writes **several** files rather than one, and reshapes the
annotations:

| | `csv` / `tsv` / `jsonl` | `parquet` |
|---|---|---|
| Files | `annotations.<ext>` | `annotations.parquet`, `items.parquet`, `spans.parquet` |
| The items | absent | `items.parquet`, every field, displayed or not |
| A `radio` scheme | one sparse column per label used | one column holding the chosen label |
| A `multiselect` | one column per label used | one list column |
| Spans | JSON blob in `<scheme>._spans` | `spans.parquet`, one row per span |

Both families add a `phase_responses` file when `export_include_phase_data` is
on, so a parquet handover is four files against csv's two.

So the "keep a condition label out of the annotator's view without losing it"
trick works, but only through `parquet` or by joining the data file back on
`instance_id`.

**Open the file before you hand it over.** A composite widget is one scheme
holding several answers, and the column it produces depends on how the widget
stored them. Both families agree, and the shape is worth knowing before the
analyst asks:

| Scheme | Stored as | Columns |
|---|---|---|
| `multirate`, `constant_sum`, `soft_label` | one entry per row or option | `reasons.Population`, `reasons.Intervention`, … |
| `hierarchical_multiselect` | one entry, comma-joined | `topics.selected_labels` holding `Annotation,People,Experts` |
| `ranking` | one entry, comma-joined in rank order | `priority.rank_order` holding `Cost,Agreement,Accuracy` |
| `image_annotation` and the other geometry types | one entry, a JSON blob | `uibox._data` |

The joined ones need splitting before anything can be counted. The hierarchical
list also carries every ancestor of each leaf an annotator ticked, so a count of
`Annotation` includes everyone who chose something inside it.

```python
import pandas as pd
print(pd.read_parquet("annotations.parquet").head())
```

`head()` on the file you are about to send is the check. It costs a minute and
it is the last point at which a column carrying the wrong thing is still cheap
to fix.

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

**They arrive as a second file, not as extra columns.** Turning the key on adds
`phase_responses.csv` (or `.jsonl`) beside `annotations.csv`, long-format, one
row per answer:

```
user_id,phase,page,sequence,schema,label_name,value
alice@x.com,consent,consent,0,consent_agree,I agree,I agree
alice@x.com,poststudy,poststudy,0,task_clarity,4,4
alice@x.com,poststudy,poststudy,1,comments,text_box,alice poststudy comment
```

"Here is the CSV" is two files once this is on, and the second one is the one
carrying the demographics. Name that file explicitly when you hand the study
over; a filename nobody was told about is one that gets left behind.

The admin API's response tells you which way it went: `num_phase_responses` and
`num_phase_responses_excluded` are both in `stats`, and one of them is always
zero.

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
