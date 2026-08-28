# When they already have something

The brief is not always "here is a corpus, build me a task". Often the
researcher arrives with work already done: annotations from another tool, a
folder of interview transcripts, a conversation corpus, a HuggingFace dataset.
Potato converts all three, and building a config by hand around data that one of
these commands would have shaped correctly is the most avoidable way to lose an
afternoon.

Ask what they have before you ask what they want to label.

## Annotations from another tool

```bash
potato import --list-formats
potato import -i instances_val.json -f coco -o ./project --image-url-prefix /media
```

Fourteen formats: `coco`, `cvat`, `labelme`, `labelbox`, `pascal_voc`, `via`,
`darwin`, `cityscapes`, `kitti`, `mot`, `davis`, `openimages`, `huggingface`,
and a HuggingFace Hub id through `--hf-dataset`. The format is auto-detected
when `-f` is omitted. What comes out is a runnable project: `config.yaml`, a
data file and the annotations, rather than a converted file you still have to
wrap.

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
   any conversion yourself.
2. **Are these being corrected, or are they done?** That is the pre-annotation
   versus `--seed-user` question above, and it changes what the annotator sees.
3. **Where are the images or audio?** The import writes URLs. Files served by
   Potato go under `<task_dir>/media` with `--image-url-prefix /media`;
   everything else needs the absolute URL they are already hosted at.
4. **Is this the label set they want to keep?** An import reproduces the source
   scheme faithfully. Categories they meant to retire come across with the rest.
