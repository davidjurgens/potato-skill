# Images, video, audio, dialogue and 3D

Everything here is a display type plus a scheme type plus one or two quirks that
are silent when you get them wrong. The generated reference (`annotation-types.md`)
has the field lists and a worked example for every type; this file is the routing
and the traps.

Agent traces and agent evaluation are their own family — `agent-traces.md`.

## Routing from what they brought

| They have | Display field | Scheme | Watch |
|---|---|---|---|
| Images, one per item | `image` | `image_annotation` | `tools` **and** `labels` are required; the image renders twice |
| Very large images, microscopy, maps | `image` + `viewer`/`tiles` on the scheme | `image_annotation` | Deep zoom drives the transform; never compute it yourself |
| Several images per item | `gallery` | a classification scheme, or `image_annotation` per field | `gallery` cannot be a `span_target` |
| Depth or range data | `depth_map` | classification, or `spatial_annotation` | Windowing and colormap are display options, not data |
| A region and a phrase for it | `image` | `image_annotation` **+** `region_caption` | Without the canvas scheme there is nothing to describe; agreement is over *matched* regions |
| "Did the model point at the right thing" | `image` | `image_annotation` **+** `grounding_eval` | Same pairing; `region_type: point` scores differently from boxes |
| Video, judge the whole clip | `video` | any classification scheme | Nothing special |
| Video, mark moments or objects | *(none needed)* | `video_annotation` | Five modes, and `labels` is required in every one |
| "Find the interval this sentence describes" | *(none needed)* | `temporal_grounding` | Reads `video_key`/`events_key`, **not** `source_field` |
| Audio, judge the whole clip | `audio` | any classification scheme | Nothing special |
| Audio, mark regions | *(none needed)* | `audio_annotation` | Use `mode: label`. The two modes that ask questions per region do not render |
| ASR/TTS output against a reference | *(none needed)* | `speech_transcript` | Its own key names: `audio_key`, `segments_key`, `turns_key` |
| ELAN-style tiers over audio or video | *(none needed)* | `tiered_annotation` | `media_type` defaults to `audio` — set it for video |
| A podcast or interview, turn by turn | `audio_dialogue` | spans, ratings, links | Per-turn playback is built in; it is a span target |
| A chat log or conversation | `dialogue` | anything, often `turn_level` | Span target; threading is a display option |
| A branching conversation | `conversation_tree` | `tree_annotation` | **Not** a span target |
| Several agents talking | `multi_agent_discussion` | `failure_attribution`, ratings | Span target; see `agent-traces.md` |
| Point clouds, LiDAR, 3D scans | the cloud path, **unlabelled** | `spatial_annotation` | It reads the path off the page, not the item; `lod` defaults on, which changes what `max_points` does |
| Robot episodes, teleop logs | *(none needed)* | `episode_annotation` | Four layers; pick the ones you need |

## Where the widget looks for its data

**This is the mistake to design against.** There are at least six conventions,
and picking the wrong one gives you an empty widget with nothing in the log.

| Key | Types that read it |
|---|---|
| `source_field` | `image_annotation`, `video_annotation`, `audio_annotation`, `spatial_annotation`, `episode_annotation`, `tiered_annotation`, `text_edit` |
| `video_key`, `events_key` | `temporal_grounding` |
| `audio_key`, `segments_key`, `turns_key`, `speaker_key`, `text_key` | `speech_transcript`, `voice_interaction`, `tiered_annotation` |
| `screenshot_key`, `steps_key` | `gui_trajectory` |
| `steps_key`, `agent_key` | the multi-agent and trajectory families |
| `image_key`, `rows_key`, `cols_key` | `table_grid` |
| `episode_field` | `episode_annotation` (alongside `source_field`) |
| `items_key` | `pairwise` — the data field holding the list of things to compare |
| `caption_field`, `expressions_field`, `predictions_field` | `grounding_eval` |
| `video_path` | the `video` *scheme*, which is not the `video` display type |
| `target_field` | `span` |
| `source_field` | `error_span` — name the field holding the text to mark, or it falls back to `text_key` |
| *(none — reads the item's `text_key`)* | the rest of the dynamic family: `extractive_qa`, `text_edit`, `card_sort`, `conjoint` |
| `span_schema` | `coreference`, `event_annotation`, `span_link` |

Check before you write it:

```python
from potato.server_utils.schemas.registry import schema_registry
s = schema_registry.get("temporal_grounding")
sorted(set(s.required_fields) | set(s.optional_fields))
```

Two names collide. **`video` is both an annotation type and a display type**,
with different required fields — the scheme wants `video_path`, the display field
wants `key`. It is also the one annotation type with no example config anywhere,
so there is nothing to copy. For anything beyond "play this clip", you want
`video_annotation`.

## Serving the media

Two static roots, and neither of them is `data_files`.

```yaml
media_directory: media        # default; served at /media/<path>
```

- **`/media/...`** ← `media_directory` under the task directory. Reference it
  from your data as `/media/clip_01.mp4`. Path traversal is blocked.
- **`/screenshots/...`** ← a `screenshots/` directory under `task_dir`,
  separate and not configurable. Agent-trace data setting `screenshot_url` to
  `screenshots/step_000.png` is served from here. Miss it and every step image
  404s.

Remote URLs work too, and are the right answer for a corpus you do not want in
the bundle. `potato deploy` ships the whole task directory. A `data:` URI in the
field works as well, and is worth knowing about for a handful of small images
you would rather not ship as files.

A path that leaves `media_directory` fails in one of two ways, and only one of
them tells you. `../outside/far.png` is refused by the traversal check and
logged — `image path traversal blocked: ../outside/far.png` — so the log answers
the question. An absolute filesystem path is not traversal, so it is handed to
the browser as though it were a URL and 404s, with nothing written to the log.
Both paint the same broken-image icon on the page, which is the only signal the
annotator gets. Check the log before concluding the file is missing.

## Images and CV

Both halves or nothing:

```yaml
instance_display:
  fields:
    - {key: image, type: image, label: Screenshot}
annotation_schemes:
  - annotation_type: image_annotation
    name: regions
    description: Draw a box around each problem.
    source_field: image
    tools: [bbox]                # required
    labels: [Broken, Confusing]  # required
```

`source_field` names the data key, but the canvas takes its bitmap from the
`<img>` that `instance_display` renders. No display field, no `<img>`, empty
canvas, and no error. The consequence is that the image renders twice, which is
correct; `building-the-ui.md` has the CSS to hide the display copy.

**`region_caption` and `grounding_eval` are not drawing schemes.** Each owns
what hangs off a region — the description, or the phrase-to-region binding — and
needs an `image_annotation` scheme in the same config to draw on. On their own
they validate, boot clean, and render a widget nobody can use: `region_caption`
shows "Draw a region on the image, then describe it" over a list that stays
empty for the life of the study, and `grounding_eval` lists the phrases with
only *Not present in the image* available, so every answer it can record is
`{"regions":{},"absent":[...]}`. Put the canvas scheme first:

```yaml
- annotation_type: image_annotation
  name: region
  description: Draw a region around each thing you describe.
  source_field: image
  tools: [bbox, polygon]
  labels: [{name: referent, color: '#6e56cf'}]
- annotation_type: region_caption
  name: captions
  description: Describe each region you drew.
```

`min_length` on `region_caption` is dead — it reaches the browser and nothing
reads it, so a three-character caption counts as described. `require_all` warns
once and lets the second Next through. If a short caption is not acceptable,
say so in the instructions and check it in the export.

**The canvas is bigger than the picture.** A 640x420 image sits centred in an
831x600 canvas, so there is a margin around it that still takes a drag. A box
drawn wholly in the margin is discarded silently. A box that *starts* in the
margin is stored with coordinates outside `[0, 1]`, `{"x": -0.046, "y": -0.0007,
...}`, and shown as "at -5%, 0%". Clamp on the way out, or drop boxes with a
negative corner, before anything computes IoU against them.

**Which is also why a practice round cannot show the image.** Phase pages do not
render `instance_display`, so a geometry scheme on a `training` phase has no
`<img>` and paints "Failed to load image" instead. `quality-control.md` has the
detail and the two ways round it. Decide it before writing the training file,
because the config validates and the server boots clean either way.

**Deep zoom.** `viewer` and `tiles` switch to a tiled viewer for images too big
to send whole. The viewer owns the transform and the canvas draws in image
pixels; anything that recomputes the mapping itself will be wrong at every zoom
level but the first.

**Pointing is not grounding with a small box.** `grounding_eval` takes
`region_type` ∈ `box`, `polygon`, `mask`, `point`. The default is `box`. The
scoring is not interchangeable, and the module says why: "A point has no area.
Every IoU against it is 0, so scoring points the way boxes are scored reports
total failure for a model that is pointing perfectly." Points are scored as a
hit rate over regions. If the researcher is evaluating a pointing model, set
`region_type: point` and report the hit rate; do not quote it beside an IoU as
though they were the same number.

`grounding_eval` also distinguishes three states per expression — answered with
a region, answered as *absent*, and not answered — because "no region" otherwise
conflates "there is no referent" with "I did not get to this one", and those
support opposite conclusions about a model that also produced nothing.

## Video

```yaml
- annotation_type: video_annotation
  name: actions
  description: Mark each action and label it.
  source_field: clip
  mode: segment                  # segment | frame | keyframe | tracking | combined
  labels: [Reach, Grasp, Release]
  video_fps: 30
```

`mode` defaults to `segment`. **`labels` is required in all five modes** — the
generator raises without it. (It was declared optional in the registry until
this pack was written, so `--strict` passed a config that could not render; it
is required now.)

`mode: combined` takes the same `segment_schemes` list as the audio widget and
renders it the same way. It was unimplemented before Potato 2.8.2 -- the key
reached the browser and nothing read it -- so check the version before planning a
task around per-segment questions on video. "For each action, rate the quality" has to be a separate scheme
over the whole clip, or a second pass.

`video_fps` is what frame numbers are computed against. Wrong value, wrong frame
indices in the export, and nothing complains.

**`min_segments` is decoration.** It validates as an integer, reaches the
browser as `minSegments`, and is read by nobody: a scheme with `min_segments: 2`
and `required: true` is satisfied by one segment, and Next goes through. On the
video and audio widgets `required` means "the annotator made one mark", not
"the annotator finished". If a study needs two segments per clip, say so in the
instructions and check it in the export — `segments` is a list, so the count is
one `len()` away.

**`temporal_grounding` is a different task and a different config shape.** It
takes `video_key` and `events_key` off the item and scores the annotator's
interval against a predicted one with live IoU. Writing `source_field` there
gets you a player with no video.

`required: true` on it means one keystroke in one box. An item declaring two
events, with a start typed into the first and nothing else, saves
`{"events":{"0":{"start":1.5}}}` and advances: an interval with no end, one
event of two, and the study calls the item done. Check for `end` on every event
before you trust the IoU column.

## Audio and speech

`audio_annotation` renders a Peaks.js waveform. Its `mode` decides what else is
required, and the requirement is conditional so `--strict` cannot see it:

| `mode` | Also required | For |
|---|---|---|
| `label` (default) | `labels` | Mark regions and label them |
| `questions` | `segment_schemes` | Mark regions and answer questions about each |
| `both` | `labels` **and** `segment_schemes` | Both |

**`questions` and `both` need `segment_schemes`**, a list of whole schemes asked
once per region. The validator requires the key for those two modes and checks
each sub-scheme against its own type's rules, so a `likert` in there still needs
`min_label` and `max_label`.

```yaml
- annotation_type: audio_annotation
  name: interruptions
  description: Mark each overlap, then answer for it.
  source_field: clip
  mode: questions
  labels:
    - {name: Clinician cuts in, key_value: '1'}
    - {name: Patient cuts in, key_value: '2'}
  segment_schemes:
    - annotation_type: radio
      name: who_started
      description: Who started talking first at this overlap?
      labels: [Clinician, Patient]
```

The server renders each sub-scheme once into a hidden `<template>` and the client
clones it per region, so any annotation type works inside a region. The clones
carry `data-segment-schema` instead of `schema`, and their ids are suffixed
`__seg_<region id>` -- which is what keeps a region's answer from being read as a
top-level answer for a scheme that does not exist.

Regions land in `instance_id_to_label_to_value` under `<scheme>:::_data`, as a
JSON string of `{id, start_time, end_time, label, annotations}` per region, with
the per-region answers keyed by sub-scheme name inside `annotations`.

Verified on Potato 2.8.2 (`v2.8.2-9-g19ce0041`); on earlier builds the panel said
"Segment annotation questions will appear here" and every region saved an empty
`annotations`. If you inherit an older checkout, put the per-region distinction in
`labels` and ask everything else once for the whole clip.

**Zoom in and zoom out do nothing on either waveform widget.** Both
`audio_annotation` and `video_annotation` call `view.getZoom()`, which the
bundled Peaks build does not have, so the button raises an uncaught
`view.getZoom is not a function` and the view does not move. *Fit* works, since
it is the one of the three that never asks for the current zoom. Plan segment
work at whatever resolution the whole clip gives you, or keep the clips short.

**The gesture is right-click drag, not drag.** A left-drag on the waveform moves
the playhead, so a checker that drags the way it would on a canvas creates
nothing and reports no error. `[` and `]` then Enter is the keyboard route. The
widget's own Help panel says both; nothing else does.

`waveform` defaults on, `spectrogram` defaults off; turning the spectrogram on
is the right call for anything phonetic and costs render time on long files.

`speech_transcript` scores ASR or TTS against an aligned reference, with
per-segment error tags plus a correction. It reads `audio_key`,
`segments_key`, `turns_key`, `speaker_key` and `text_key`.

`tiered_annotation` is the ELAN/Praat shape: named tiers stacked over one
timeline. It requires `source_field` and `tiers`, and **`media_type` defaults to
`audio`** — a video task that forgets to set it gets an audio element and no
picture. Three things about it on 2.8.2-11:

- Its Peaks.js wiring throws on every load (`zoomview.on is not a function`,
  `tiered-annotation.js:1073`) and the failure is swallowed as a console
  warning. Everything after that line in the initialiser is skipped, so
  double-click on the waveform does not seek, clicking the overview does not
  navigate, the initial zoom and auto-scroll are never set, and nothing refits
  on resize. Segment click and drag still work, which is why it looks fine.
- **`transcript_field` labels every seeded turn with the tier's first label.**
  It carries the turn's real `speaker` in a field nothing displays, so a
  two-speaker call arrives as four utterances all labelled "Caller", two of
  which are the agent. The contradiction (`"label":"Caller",
  "speaker":"agent"`) is what persists once the annotator edits anything.
- **There is no gesture to relabel an existing annotation.** The label buttons
  set the label for the *next* one drawn; the keyboard offers play, step,
  Delete and Escape. Correcting a seeded label means deleting it and drawing it
  again. If the labels matter more than the boundaries, seed nothing and let
  annotators draw.

## Dialogue and podcasts

Four displays, and the difference is the shape of the conversation:

| Display | Shape | Span target |
|---|---|---|
| `dialogue` | A flat or reply-threaded log | yes |
| `audio_dialogue` | Interview or podcast turns, each with its own play button | yes |
| `conversation_tree` | Branching, collapsible | no |
| `multi_agent_discussion` | Several agents, colour-coded, filterable | yes |

For per-turn questions rather than one judgment for the whole thing, use
`turn_level: true` on the scheme; for one judgment over a whole session, use
`sessions` and `session_level: true`. Both are in `modes-and-subsystems.md`.

**`list_displays()` under-reports span-target support.** Its
`supports_span_target` flag is true for nine types, but twelve accept
`span_target` — `pdf`, `spreadsheet` and `agent_trace` anchor spans their own way
and are missing from the flag. Ask
`display_registry.get_span_target_capable_types()`, which is what the validator
uses. (The same table under-reported `optional_fields` until 2.8.2-11; it is
accurate now, and `test_doc_counts.py` fails if it drifts again.)

## 3D and embodied

```yaml
- annotation_type: spatial_annotation
  name: objects
  description: Box each object in the scan.
  source_field: cloud
  tools: [cuboid]
  labels: [Vehicle, Pedestrian]
```

`tools` and `labels` are required, as with images.

**The viewer finds the cloud on the page, not in the item.** `source_field`
names the key, and then `pc-viewer.js` looks for a rendered element whose
`data-field-key` matches and reads its *text*. So the cloud path has to be
either the item's `text_key` (what the bundled example does) or a display field
— and that field must have **no `label:`**, because the label ends up in the
same text node and the path is rejected for containing whitespace. All three of
these produce "No point cloud for this item: the "point_cloud" field is empty.
Check item_properties in the config", which is not where the problem is:

```yaml
# dead: the cloud is in the data and nowhere on the page
instance_display: {fields: [{key: notes, type: text, label: Notes}]}

# dead: the label is in the way
instance_display: {fields: [{key: cloud, type: text, label: Cloud}]}

# works: 9,091 points, all loaded
instance_display: {fields: [{key: cloud, type: text}]}
```

Boxes come back in **metres in the sensor frame**, not normalized like image
annotation: `{"center": [35.47, -7.58, -0.90], "size": [15.71, 1.46, 1.70],
"rotation": [0, 0, 0, 1]}`.

**`lod` defaults to `True`**, and that changes the meaning of the neighbouring
keys: under LOD the cloud loads as an octree and `point_budget` /
`max_loaded_nodes` govern what is in memory, while **`max_points` is used only
when `lod: false`**. Setting `max_points` on a default config and expecting a cap
does nothing at all. `mpr` and `slab_thickness` switch to slab views for
medical-style data.

`rollout_evaluation` puts several generated videos on one clock, with
violations, preference and counterfactual layers. It is the one media widget
that already reports its own shortfall ("0 of 3 panels answered, still to do: A,
B, C"), so `required` on it means what it says. Its status line claims "3
rollouts, 0.00 s" whatever the clips are, because the duration is only learned
from the browser after that sentence is written; the clock and frame counter
under the panels are right. Use WebM: the widget says so itself when handed MP4.

`episode_annotation` is the embodied one: synchronized video streams plus
time-series lanes. Its four `layers` (`phases`, `outcome`, `reward`,
`instruction`) are all on by default, and each answers a different question, so name the ones you
want rather than asking annotators for all four on every episode.
`series_shown` picks which sensor lanes to draw; omit it and you get all of them,
which on a real robot log is unreadable.

## Verifying a non-text task

`potato preview --screenshot` is close to useless here. It renders the viewport
of one page, and a canvas that has not loaded its bitmap, a waveform that has not
decoded, and a video that has not buffered all look the same as ones that have.

What actually proves it:

1. **Boot and read the log.** A geometry or media generator that failed renders
   a heading with no inputs, and the startup log names the scheme.
2. **Open it and interact.** Draw one box, drag one segment, play one turn. The
   media pipeline is what breaks, and only a real gesture exercises it.
3. **Read `user_state.json`.** Geometry lands in
   `instance_id_to_span_to_value` and the scheme's `_data` inputs. If the shape
   there is not what you expected, the export will not be either.
4. **Use a format the test browser can play.** The browser tests in this repo
   use WebM fixtures for video; a clip that plays in your desktop player is not
   evidence that headless Chromium will decode it.

`running-a-task.md` has the driver. `scripts/walk_task.py` will answer a
media task's classification questions but cannot draw a box for you.
