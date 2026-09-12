# Running a task and proving it runs

`potato validate` tells you the server will start. `potato preview --screenshot`
tells you the first 900 pixels of one page did not throw. Neither tells you an
annotator can get from the login screen to the end of the study, and most of what
breaks a task lives in that gap.

This file covers the three things the rest of the pack does not: how to get a
server up and leave it up, how to read what it says while booting, and how to
drive it like an annotator.

## Boot it early

The startup log is the real validator. It is the only place that reports:

- whether each phase assembled, or was skipped
- how many training, attention-check and gold items actually loaded
- which subsystems initialized
- exceptions from side files that `validate` never opens

Run it as soon as the config parses, well before the interface is finished.
Every undocumented file format in this pack was recovered from these lines.

```bash
grep -E "ERROR|Traceback|Loaded [0-9]+|phase|missing required" server.log
```

## Backgrounding it

`potato start` never returns. In a non-interactive session, run it detached and
poll for readiness. Never in the foreground, and never behind a bare `sleep`.

```bash
cd /path/to/project                     # must be the directory task_dir resolves to
nohup potato start config.yaml -p 8421 > server.log 2>&1 &

until curl -s -o /dev/null http://localhost:8421/; do sleep 2; done
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8421/    # 200
```

Boot takes 10–20 seconds on a small task. The readiness lines in the log are
`Serving Flask app 'potato.flask_server'` and `Running on …`. There is no
`/health` endpoint on a plain `potato start`; a 200 on `/` is the check.

For a throwaway boot — you want the log, not a server — start it, wait for the
readiness line or the process to die, then kill the process group:

```python
import subprocess, os, signal, time
p = subprocess.Popen(["potato", "start", "config.yaml", "-p", "8951"], cwd=PROJ,
                     stdout=open("/tmp/boot.log", "wb"), stderr=subprocess.STDOUT,
                     start_new_session=True)
t0 = time.time()
while time.time() - t0 < 120:
    time.sleep(0.5)
    s = open("/tmp/boot.log", "rb").read().decode("utf8", "replace")
    if "Running on" in s or "Serving Flask" in s or p.poll() is not None:
        break
os.killpg(os.getpgid(p.pid), signal.SIGKILL); p.wait()
```

`start_new_session=True` plus `killpg` matters: the server spawns children and a
plain `kill` leaves the port held.

Stop a named server with `pkill -f "potato start config.yaml -p 8421"` and
confirm with `lsof -nP -iTCP:8421 -sTCP:LISTEN`.

## Running the server writes to the project directory

| Path | What it is | Safe to delete? |
|---|---|---|
| `annotation_output/` | Annotations, per-user state, exports | Yes, **while stopped**. It is the data. |
| `annotation_output/<user>/user_state.json` | One annotator's assignment, answers, spans, training state | Never edit by hand |
| `project.sqlite` (+ `-wal`, `-shm`) | Codebook, cases, memos, search index | Yes, while stopped; it reseeds |
| `layouts/task_layout_*.html` | Generated form HTML, cached by config hash | **Delete after editing schemes** if the page looks stale |
| `server.log` | Whatever you redirected | Yes |

Wiping `annotation_output/` **while the server runs** does not reset anything:
item and user state are already in memory, and the next annotator to arrive gets
the completion page with zero items. If a fresh task suddenly says "Thank You!"
to a new account, this is why. Stop the server, wipe, start it again.

Two consequences worth knowing before you verify a config you are still editing:

- The first boot **seeds** `project.sqlite` from the config. For a codebook task
  the labels in your config become the project codebook, and later config edits
  do not change it until `potato codebook config.yaml` re-syncs.
- Test annotators you create while checking the task are real annotators. They
  hold assignments and their answers count toward agreement. Wipe
  `annotation_output/` and restart before handing the task over, and say in the
  handover which accounts you left behind.

## Known console noise

Potato logs these on every phase page (consent, instructions, training,
post-study), because a phase page has no instance and the span layer asks for one
anyway:

```
GET /api/current_instance  404
[SpanManager] Error fetching current instance ID: Failed to fetch current instance: 404
[SpanManager] Failed to get server instance ID during initialization
ERROR potato.flask_server: Error getting instance text: 'null'
```

The 404 is the endpoint's own guard: it refuses to hand back an instance outside
the annotation phase, which is right, and the span layer asks anyway. On the
annotation page the same call returns 200.

Before Potato 2.8.2 a `POST /api/track_annotation_change 400` joined this list,
once per answer given on a phase page, and the behavioural trail for survey and
training pages was lost. The three tracking endpoints now agree: a missing
instance id becomes the `__phase_page__` sentinel. That 400 in your log dates the
checkout.

They appear on a task that is working correctly, and they have a consequence:
**`potato preview --phase consent --screenshot` exits 1 on a healthy task**,
while `--screenshot` on the annotation page exits 0 and says "rendered cleanly".
Same config, both fine. Judge the PNG and the error list rather than `$?`. Filter them out before treating console errors as signal,
and do not spend time chasing them.

Real errors worth reacting to, seen from the client:

| Client symptom | Meaning |
|---|---|
| `[NAV] Navigation failed: 400` | The server refused the save. Read the response body — it is JSON with `unsatisfied_schemas` |
| `POST /annotate 400 {"status":"validation_error"}` | A required scheme is unanswered; a required span produces this with no inline message |
| A scheme renders with no inputs under the heading | Generator failed for that scheme; the startup log names it |
| A scheme is missing entirely | Same cause. `Invalid label format: True` in the log means a YAML boolean got into `labels` — see `building-the-ui.md` |

### Widgets that open a native dialog

Eight files in Potato call `alert()`, and `error_span` is the one you will meet
first: saving an error span without a severity pops "Please select a severity
level." Playwright dismisses dialogs automatically, so under automation this
reads as a button that did nothing — no error, no console line, no change on the
page. If a widget silently refuses to accept input, check for an `alert()` in
its schema module before assuming the widget is broken.

Register a handler if you want to see them:

```python
page.on("dialog", lambda d: (print("DIALOG:", d.message), d.dismiss()))
```

## The admin surfaces

They are not linked from the annotation page, and the JSON APIs are not open.

```bash
cat admin_api_key.txt      # generated into task_dir at first boot; the log says so
curl -H "X-API-Key: $(cat admin_api_key.txt)" localhost:8000/admin/iaa
```

| Route | Auth | What it gives |
|---|---|---|
| `/admin` | none — serves HTML | The dashboard |
| `/admin/iaa` | `X-API-Key` | Agreement per scheme: inferred `kind`, the metrics that follow, `n_overlap_items` |
| `/admin/api/agreement` | `X-API-Key` | Also agreement. Reported broken on a geometry task (`calculate_krippendorffs_alpha() got an unexpected keyword argument 'experiment_col'`); worked on a plain radio/likert task. Prefer `/admin/iaa` |
| `/admin/api/quality_control` | `X-API-Key` | Attention-check and gold-standard pass rates per user |

Without the header every JSON route returns `403 {"error":"Admin access
required"}`, which reads like a broken build if you do not know the key exists.
The key is 43 characters, regenerated only if the file is deleted, and settable
yourself with `admin_api_key` in the config.

## Driving it like an annotator

A static render cannot show you a conditional question, a drawn span, a restored
answer, or whether the workflow reaches its own last page. If a browser tool is
available, use it against a running server. Playwright ships with the
`[preview]` extra that `--screenshot` needs, so it is normally already installed.

This is a working driver. It registers, walks the phases, screenshots each page
**full height**, and reports console errors tagged by the phase they came from.

```python
import sys
from playwright.sync_api import sync_playwright

BASE, SHOTS = "http://localhost:8421", "shots"
errors, phase = [], ["boot"]

def shot(page, tag):
    page.wait_for_timeout(800)
    page.screenshot(path=f"{SHOTS}/{tag}.png", full_page=True)   # full_page, not the viewport

def pick(page, name, value):                                     # click an input by name+value
    page.evaluate("""([n,v])=>{const e=document.querySelector(`input[name="${n}"][value="${v}"]`);
                    if(!e) throw new Error('missing '+n+'='+v); e.click();}""", [name, value])

with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_context(viewport={"width": 1280, "height": 900}).new_page()
    page.on("console", lambda m: errors.append(f"[{phase[0]}] {m.text[:150]}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"[{phase[0]}] {e}"))

    page.goto(BASE)
    page.evaluate("switchTab('register')")                       # login page has login/register tabs
    # NB: use a fresh username each run. A duplicate registration navigates to
    # /register, which has no switchTab(), so a re-run throws
    # "Cannot read properties of null (reading 'classList')" and leaves you
    # logged out on the sign-in page rather than on the task.
    for i in page.query_selector_all("form[action='/register'] input"):
        n = i.get_attribute("name")
        if n == "email": i.fill("checker@example.com")
        elif n == "pass": i.fill("pw12345")
    page.click("form[action='/register'] button[type=submit]")
    page.wait_for_load_state("networkidle")

    phase[0] = "consent"; shot(page, "10-consent")
    pick(page, "consent_agree", "I agree to take part")
    page.click("button:has-text('Next')"); page.wait_for_load_state("networkidle")
    ...
```

Selectors that are stable and worth knowing:

| Selector | What it is |
|---|---|
| `#instance_id` | Hidden input holding the current item id. The cheapest proof you moved |
| `#next-btn` | Next. There is **no** `#prev-btn` on the first item; Previous appears from item 2 |
| `#go_to` + `#go-to-btn` | Jump to instance number N. Use this to navigate back |
| `input[name='<scheme>'][value='<label>']` | Radio / likert option. `value` is the raw label, not the humanized one |
| `input[name='span_label:::<scheme>'][value='<label>']` | Span label chip; it is a **checkbox** — `.check(force=True)` |
| `[name='<scheme>:::text_box']` | Free-text scheme. **Not** `textarea[...]` — a `text` scheme is an `<input>` unless `multiline: true` |
| `#span-overlays` | Present only on an ordinary text task. Its children are the drawn spans, and its presence is how you tell the two shapes apart |
| `#text-content` | The span anchor on an ordinary text task — but it exists on a span-target task too, hidden. Check the overlay first |
| `.span-target-field .text-content` | The per-field anchor once `instance_display` names span-target fields. Overlays sit inside it, as `.span-overlays-field > *` |
| `form.annotation-form` | One per scheme; counting these counts the questions on the page |

### Drawing a span

Spans are drawn as overlays over the text rather than by wrapping it, so "did a
`<mark>` appear" is the wrong check. Count the overlay container's children, in
whichever of the two shapes the task renders.

An ordinary text task renders one `div#text-content` holding the item text, with
`div#span-overlays` inside it. A task whose `instance_display` names span-target
fields renders one `div#text-content-<field>.text-content` per field, each with a
`div#span-overlays-<field>.span-overlays-field` inside it.

**Do not tell the two apart by asking whether `#text-content` exists.** It exists
on both. On a span-target task it is a `0×0` hidden div holding `text_key`,
carried along beside the real per-field anchors, and Playwright refuses to scroll
to it — `scroll_into_view_if_needed` times out with "element is not visible"
after thirty seconds, which reads as a hung browser rather than a wrong selector.
Anchor on the overlay container instead, which exists in one shape each:

```python
anchor = ".text-content" if page.locator(".span-overlays-field").count() else "#text-content"
```

```python
page.locator("input[name='span_label:::sentence_type'][value='Factual reporting']").first.check(force=True)
page.locator(anchor).first.scroll_into_view_if_needed()
page.mouse.wheel(0, -160)          # clear the sticky navbar, or the drag starts on it
box = page.evaluate("""(sel)=>{
    const c=document.querySelector(sel);
    const w=document.createTreeWalker(c, NodeFilter.SHOW_TEXT);
    let n=w.nextNode();
    while (n && n.textContent.trim().length < 25) n=w.nextNode();   // skip turn numbers and speaker chips
    const t=n.textContent, stop=t.indexOf('.');
    const r=document.createRange(); r.setStart(n,0); r.setEnd(n, stop>0?stop+1:40);
    const q=[...r.getClientRects()], a=q[0], z=q[q.length-1];
    return {x1:a.left+2, y1:a.top+a.height/2, x2:z.right-2, y2:z.top+z.height/2};}""", anchor)
page.mouse.move(box["x1"], box["y1"]); page.mouse.down()
for k in range(1, 11):
    page.mouse.move(box["x1"] + (box["x2"]-box["x1"])*k/10, box["y1"], steps=2)
page.mouse.up()
```

The `mouse.wheel` line is not optional. `scroll_into_view_if_needed` puts the
text at y≈22, underneath the sticky navbar, and the drag then selects the header
instead of the article. That looks like "spans are broken" and is not.

The length filter in the tree walker is there for the same reason. A `dialogue`
span target starts with the turn number and the speaker name as their own text
nodes, so the first node the walker reaches is `[1]` — five pixels wide, and a
drag across it selects nothing.

**This generalizes to every synthetic drag, spans and canvases alike.**
`page.mouse` works in viewport coordinates, so a target below the fold or under
the navbar receives nothing:

1. `scrollIntoView({block: 'center'})` on the target element,
2. **re-read** `getBoundingClientRect()` after the scroll,
3. drag,
4. **count the result** — `#span-overlays > *` for spans (`.span-overlays-field
   > *` per field on a span-target task), the canvas's own "Annotations: N"
   readout for geometry.

A drag that misses produces zero annotations, zero exceptions, zero console
output and zero network traffic. It is indistinguishable from the feature being
broken, and step 4 is the only thing that tells them apart.

### The four checks worth automating

1. **Conditional schemes appear.** Read the ancestor chain for
   `display:none`, not just the element:

   ```python
   page.evaluate("""s=>{let p=document.querySelector(s), hidden=false;
      while(p){ const cs=getComputedStyle(p);
                if(cs.display==='none'||cs.visibility==='hidden'){hidden=true;break;} p=p.parentElement; }
      return hidden;}""", "textarea[name='misleading_why:::text_box']")
   ```

   A conditional input has a non-zero bounding box while hidden, so width and
   height prove nothing.

2. **Answers survive navigation.** Answer, `#next-btn`, then `#go_to` + `Go` back.
   Check the visual state — `input[name=x]:checked`, textarea `.value`, overlay
   count — not hidden inputs. **Never test this with `driver.refresh()`**:
   browsers restore form state across a refresh on their own, so a refresh-based
   check passes even when the server stored nothing.

3. **The workflow reaches its last page.** Answer every item and confirm the
   post-study page renders. This is where per-annotator quota bugs surface.

4. **The server really stored it.** Read
   `annotation_output/<user>/user_state.json`:

   ```python
   d = json.load(open(f"annotation_output/{user}/user_state.json"))
   d["instance_id_ordering"]              # what they were assigned, in order
   d["instance_id_to_label_to_value"]     # answers per item
   d["instance_id_to_span_to_value"]      # spans with start/end offsets
   d["training_state"]["passed"]
   d["phase_to_page_to_label_to_value"]   # consent and survey answers
   d["max_assignments"]                   # the quota that was actually applied
   ```

   This is the difference between "the widget is on the page" and "the answer is
   in the file", and it is the claim a researcher cares about.

## What to say in the handover

Distinguish what you established from what you assumed. A useful report reads:

> Rendered at 1280 wide, full height: consent, instructions, a training question
> with feedback, the annotation page, and the post-study survey (`shots/`).
> Walked one annotator end to end: training marked 3/3, all six items plus two
> attention checks annotated, answers and span offsets present in
> `user_state.json`. Conditional follow-ups verified by driving the gate answer;
> persistence verified by navigating away and back, not by refresh.
>
> Not checked: two annotators at once, the agreement pages with real overlap, and
> whether an attention-check failure surfaces anywhere an admin would see it.

The second paragraph is what makes the first one worth reading.

Leave the server running only if that was asked for, and if you do, write down
the URL, the port, the pid, how to stop it and how to start it again. A running
server nobody can restart is a one-shot demo.
