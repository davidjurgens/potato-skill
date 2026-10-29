# When they already have something

The brief is not always "here is a corpus, build me a task". Often the
researcher arrives with work already done: annotations from another tool, a
questionnaire built in Qualtrics, a PCIbex experiment, a folder of interview
transcripts, a conversation corpus, a HuggingFace dataset. Potato converts all
of these, and building a config by hand around data that one of these commands
would have shaped correctly is the most avoidable way to lose an afternoon.

Ask what they have before you ask what they want to label.

## Annotations from another tool

```bash
potato import --list-formats
potato import -i instances_val.json -f coco -o ./project --image-url-prefix /media
```

47 formats, which `--list-formats` prints in four groups, the last being seven
survey formats. Image and video: `coco`, `cvat`, `labelme`, `labelbox`,
`pascal_voc`, `via`, `darwin`, `cityscapes`, `kitti`, `kitti_tracking`, `mot`,
`davis`, `openimages`, `webdataset`, `yolo` and `huggingface`, which also takes a
HuggingFace Hub id through `--hf-dataset`. Text: `brat`, `conll`, `doccano`,
`prodigy`, `qdpx` and `tei`. Whole projects, which bring questions, annotators
and suggestions along with the items: `label_studio`, `argilla`, `zooniverse`,
`ibex`, `textgrid`, `eaf`, `flextext`, `toolbox`, `megadetector`,
`coco_camera_traps`, `birdnet`, `raven`, `audacity_labels`, `iiif`,
`web_annotation` and `page_xml`. The seven survey formats have their own
section below. What comes out is a runnable project: `config.yaml`, a data file
and the annotations, rather than a converted file you still have to wrap.

The decision that matters is what the imported annotations *are*:

| | Without `--seed-user` | With `--seed-user NAME` |
|---|---|---|
| The annotations become | Pre-annotations | NAME's saved work |
| An annotator sees | A starting point they can correct | Nothing; the item is already done |
| Stored before someone saves | No | Yes |

Pre-annotation is what a correction pass wants: existing boxes shown as a
starting point, a human fixing them, the human's version stored.
`--seed-user` **fabricates an annotator** and exists so import→export can be
checked without opening every item by hand. Do not use it to load a gold set
you intend real people to re-annotate. The items will read as finished.

Two flags that lose information, both worth naming to the researcher rather
than choosing quietly:

- `--rle-as-polygon` traces RLE masks into editable polygons. Holes are dropped
  and the contour will not re-rasterize to the source mask.
- `--extract-media DIR` is required for WebDataset shards. Without it the images
  stay inside the `.tar`, no web server can read them, and the canvas is blank.

Label Studio and Argilla projects come in whole: the labeling interface (or the
Argilla settings) becomes the annotation schemes, model predictions or
suggestions become pre-annotations, and each person's answers become their
saved work only with `--keep-annotators`. Unlike `--seed-user` this fabricates
nobody, because the answers belong to real annotators; the project is
passwordless afterwards so they can log in by name, so set `require_password:
true` before deploying it.

```bash
potato import -i export.json --ls-config label_config.xml -o ./project --keep-annotators
potato import -i my_dataset/ -f argilla -o ./project --keep-annotators
```

Pass the Label Studio labeling config with `--ls-config`. Without it the
questions are rebuilt from the answers and any option nobody chose is lost. An
Argilla `to_disk` folder does not record whether a response was submitted,
discarded or a draft, so all of them import and the import warns; a `to_hub`
dataset keeps the status.

`kitti_tracking` takes the tracking benchmark's split folder (`label_02/`,
`velodyne/`, `calib/`) and writes one point-cloud sequence per item, with each
tracked object as a track. A sequence without a calibration file is skipped,
since a box placed without one would sit in the wrong frame.

## Questionnaires from a survey tool

```bash
potato import -i screener.qsf -o my-study/
potato import -i exit_survey.lss --into my-study/config.yaml \
    --survey-slot poststudy --prefix exit_
```

| `-f` | Source |
|---|---|
| `qualtrics` | Qualtrics `.qsf` (Export Survey) |
| `surveyjs` | SurveyJS JSON |
| `limesurvey` | LimeSurvey `.lss` |
| `xlsform` | XLSForm `.xlsx` (ODK, KoboToolbox, Ona, SurveyCTO) |
| `redcap` | REDCap data dictionary `.csv` |
| `beiwe` | Beiwe survey JSON or a study settings export |
| `network_canvas` | Network Canvas `.netcanvas` or its `protocol.json`, as `ego_network` |

`-o DIR` writes a new project: one JSON file per page under `surveys/`, listed
in `phases.order` ahead of an `annotation` phase that holds a placeholder
question and three placeholder items. Replace those with the real task.
`--into CONFIG` adds the pages to an existing project instead, and **writes a
merged copy next to the config** (`config.with-<survey>.yaml`, or
`config.with-<survey>-<prefix>.yaml`). The original is not touched. Start the
server on the copy, then move it over the original when you are satisfied. The
copy drops the original's comments, and sets `export_include_phase_data: true`
when the original did not set it, so survey answers land in the export; they
can hold personal data.

- `--survey-slot` is `prestudy` (the default) or `poststudy`.
- `--prefix` renames every imported question and page. The import stops with an
  error when a question name already exists in the config, which is the usual
  reason to pass it. Importing the same file with the same prefix twice is
  refused while the first import's pages, report or copy exist.
- `--survey-language` picks the language of a multilingual LimeSurvey or
  XLSForm.

What the logic becomes: show/hide rules turn into nested `display_logic` on
questions and `show_when` on pages. Choice answers are stored as the option
text, so a translated rule compares against the text ("Yes") and not the
source's code. A Qualtrics randomizer that shows all its blocks becomes
`phases.counterbalance`; one that picks one embedded-data assignment becomes a
between-subjects factor under `conditions`; End of Survey branches become
`exit_when` on a page.

Everything the importer could not translate is listed in `IMPORT_REPORT.md`
beside the config, and the first ten are printed. A rule that translates only
in part is **dropped whole and the question stays visible**, so a respondent
can see a question the source would have hidden. Read the report before
treating the logic as faithful. One REDCap trap: the first field of a data
dictionary is the record ID, which the importer leaves out, so branching that
tests it is reported and not translated.

## Experiments from Ibex or PCIbex

```bash
potato import -i my_experiment/ -o my-study/
```

Point it at the folder holding `data_includes/` and `chunk_includes/`. A PCIbex
`Template` over a CSV becomes one item per row. A `Group` or `List` column (or
classic `["condition", N]` labels) becomes a between-subjects `list` condition,
with `batch_assignment.group_by_condition: list` and one data file per list
under `data/`. `Sequence` ordering, practice items, `Form` and `Html` screens
and custom JavaScript are not carried over and are listed in `IMPORT_REPORT.md`.

## Linguistic fieldwork and annotation files

`flextext` (FLEx interlinear texts) and `toolbox` (Toolbox/Shoebox standard
format markers) become an `interlinear_gloss` scheme, one item per phrase.
`textgrid` (Praat) and `eaf` (ELAN) become a `tiered_annotation` scheme, one
item per file, with the intervals as pre-annotations and the audio or video
copied in when a file of the same name sits beside it. Without one the import
warns and the item has no media. `potato transcripts` below also reads these two
formats; use `potato import` when you want the tiers kept as a scheme and
`potato transcripts` when you want speaker turns.

## Digital humanities and citizen science

- `iiif`: a Presentation 3 manifest (2.x best effort), as a file or an
  `http(s)` URL. One item per canvas, shown for `image_annotation`.
  `--iiif-size` asks each image at a given Image API size.
- `web_annotation`: W3C Web Annotation JSON-LD (Annotorious, Mirador,
  Hypothesis). Text annotations need the annotated texts, which are found
  beside the file or in the folder named by `--texts`; they arrive as span
  pre-annotations.
- `page_xml`: Transkribus, eScriptorium and OCR-D transcriptions as a
  `text_edit` line-correction task, one item per line. `--page-xml-mode
  regions` makes one item per region instead.
- `tei`: TEI P5 text with paragraphs as items and inline names (`persName`,
  `placeName`) as span pre-annotations. `--tei-unit` picks `p`, `div`, `s` or
  `l` as the item.
- `zooniverse`: point `-i` at the folder holding the workflow export and the
  classification export (the subject export is optional). The workflow's
  tasks become schemes. Pass `--keep-annotators` to keep each volunteer's
  answers; volunteers who were not logged in become `anon_<id>`, one per
  address. One workflow version is imported (the latest major version the
  classifications use, or `--workflow-id` and `--workflow-version`).
  Survey tasks and sub-task questions on drawn marks are left out and counted.

## Camera traps and bioacoustics

```bash
potato import -i detections.json -o ./traps --image-url-prefix /media
potato import -i selections.txt -o ./calls
```

- `megadetector`: batch output JSON. Detections below `--md-threshold` (0.2)
  are left out.
- `coco_camera_traps`: COCO with `seq_id`, `location` and `datetime`. For
  either of these two, `--sequences` makes one item per `seq_id`, shown as a
  gallery.
- `raven`: selection tables; `audacity_labels`: label tracks, time or
  spectral; `birdnet`: BirdNET-Analyzer output. All three become
  `spectrogram_annotation` boxes. `--min-confidence` cuts Raven and BirdNET
  rows (BirdNET defaults to 0.1) and `--label-column` chooses the column that
  names the box. Potato reads BirdNET's output and runs no model.

Detections arrive as pre-annotations. The images and recordings are not copied
for you: put them in `media/` and pass `--image-url-prefix /media`, or
`--image-dir`, or the import warns and the items show no media.

## Local files stay inside the input folder

An import will not copy or read a local file from outside the folder it was
given. An absolute path, a `file://` URI, a `../` path and a symlink that leads
out are each skipped with a warning and counted under "left out", so an import
cannot publish an unrelated file through `media/`. `--image-dir` and `--texts`
folders are allowed. The failure to expect: a PAGE XML or Web Annotation file
that names `/home/me/scans/p1.png` imports, with items that have no image.
Move the files into the input folder or pass the folder that holds them.

## Without `-f`

The format is detected, in this order: the survey importers, then the
whole-project formats, then the text formats, then the image and video
formats (directory layouts are recognised by marker files such as `data.yaml`,
`label_02/` or `seqinfo.ini`). An `http(s)` input goes to `iiif`. A COCO file
whose images carry `seq_id` imports as `coco_camera_traps`, and a tab-separated
`.txt` shaped like a Raven or Audacity table goes to those importers. The first
line the import prints names the format it chose ("... from Raven selection
tables"). Pass `-f` when that is not the format you expected, which happens
most with a bare `.json`, `.xml` or `.txt`, and always in a script, so the
detection cannot change under it.

## Transcripts and subtitles

```bash
potato transcripts interviews/*.vtt -o data/interviews.json --dry-run
potato transcripts interviews/ -r -o data/interviews.json \
    --media-dir audio/ --emit-config
```

Reads Whisper, WhisperX and whisper.cpp JSON and TSV, SRT, WebVTT, SubStation
Alpha, TTML, YouTube `json3`/`srv`, AWS Transcribe, Deepgram, AssemblyAI,
Rev.ai, CTM, Praat TextGrid and ELAN EAF. Speaker labels and timings survive
the conversion, which is what `audio_dialogue`, `speech_transcript` and
`tiered_annotation` bind to.

`--dry-run` reports the detected format and turn count per file and writes
nothing. Run it first — a subtitle file that parses to one turn is usually a
format guess gone wrong. `--emit-config` prints a config fragment for the file
it just wrote, which is the fastest correct starting point for the item keys.
`--media-dir` pairs each transcript with an audio or video file by basename, so
per-turn playback works without you writing the paths.

## Conversation corpora

```bash
potato convokit --list-corpora
potato convokit reddit-corpus-small -o data/threads.json --unit conversation \
    --context-mode ancestors --sample 200 --emit-config
```

`--unit` is the unit-of-annotation decision from `designing-a-task.md`, made at
conversion time: `conversation` gives one item per thread, `utterance` one item
per turn. It is the choice that is expensive to reverse, so confirm it rather
than take the default. `--context-window`/`--context-after`/`--context-mode`
decide how much surrounding conversation an utterance-level item carries, and
`--sample`/`--seed` cut a reproducible subset before you have committed to
anything.

## Four questions before importing

1. **Which tool wrote them?** Match it against `--list-formats` before writing
   any conversion yourself. The format list now includes survey tools, PCIbex,
   FLEx, Raven and Zooniverse, so check it for work that is not annotation too.
2. **Are these being corrected, or are they done?** That is the pre-annotation
   versus `--seed-user` question above, and it changes what the annotator sees.
3. **Where are the images or audio?** The import writes URLs. Files served by
   Potato go under `<task_dir>/media` with `--image-url-prefix /media`;
   everything else needs the absolute URL they are already hosted at.
4. **Is this the label set they want to keep?** An import reproduces the source
   scheme faithfully. Categories they meant to retire come across with the rest.

## What has and has not been checked

Checked against Potato 2.12.0: each importer below was run on a small input
built for the purpose (a few lines or rows each), the output was read
(`config.yaml`, the data file, `IMPORT_REPORT.md` where one is written), and the
resulting project was started and answered HTTP 200 on its login page. That
covers `surveyjs`, `xlsform`, `redcap`, `limesurvey`, `beiwe`, `qualtrics`,
`network_canvas`, `ibex`, `flextext`, `toolbox`, `textgrid`, `eaf`, `iiif` (a
file and a URL served from localhost), `web_annotation`, `page_xml`, `tei`,
`megadetector`, `coco_camera_traps`, `raven`, `audacity_labels`, `birdnet`,
`kitti_tracking`, `label_studio` and `argilla` (a `to_disk` folder). The
`--into`, `--prefix`, `--survey-slot` and containment behaviour were run with
the files named above.

Not checked, or checked only on a fixture that ships with Potato's tests
rather than one built here:

- `limesurvey` and `beiwe`, `qualtrics` (the counterbalance, `conditions` and
  `exit_when` output) and `zooniverse` used Potato's synthetic test fixtures,
  because a faithful input is long. No real Qualtrics, LimeSurvey or
  Zooniverse export was imported.
- The auto-detection order is read from the code and spot-checked on the
  inputs above, not tested against every ambiguous file.
- Argilla `to_hub` and `--hf-dataset`, `.xls` XLSForms, `.netcanvas` archives,
  IIIF 2.x manifests and `--iiif-size` against a live image server were not run.
- A project that starts can still render wrongly; no imported page was opened
  in a browser.
- The older formats in the first table (`coco`, `cvat`, `yolo` and the rest)
  were not re-run for this revision.
