# Creative direction: planning, distinctiveness, generated imagery

Three problems this covers: videos that all look alike, videos that skip design and go straight to
rendering, and visuals that need to be made rather than found.

## 1. Plan first, render second

Planning happens with the user, not at them. Before `brief` runs, interview the user over as many
rounds as the piece needs - audience, platform, length, intent, tone, narration, music, existing
footage, brand, references - then present the **complete plan for approval**: script, full
storyboard (act, intent, spoken line, on-screen text, visual device, duration, handoffs per beat),
visual direction, audio plan, asset list and acceptance checklist. The user's explicit yes is the
gate; before it, nothing is scaffolded, compiled, generated or rendered, and any change the user
asks for means revising the plan and confirming again.

`brief` then produces that complete, editable design document as a file. Nothing renders until it
is complete *and* approved.

```bash
python vs.py brief --script script.txt --out brief.json \
  --platform douyin --tone "冷静专业" --seed 2024
```

It writes `brief.json` (machine) and `brief.md` (readable), containing:

- **goal** — platform, aspect, fps, audience, tone, target duration
- **premise / promise** — what the video claims and what the viewer gets
- **structure** — one internal cue per narration line, each with an act (hook / context / body / proof /
  turn / close), the intent, the spoken line, the *on-screen* phrase (a different thing), the
  template, the visual device, and duration
- **visual_plan** — the resolved layout, motion family and accent for every beat, so the variety is
  visible on paper before it costs render time
- **assets** — one image prompt per beat that needs one, already carrying the film's style clause
- **audio** — voice settings, music mood, ducking, loudness target
- **checklist** — the quality gates for this specific piece

Validate with the same command (`brief` prints issues) or by reading `brief.json`; `compile`
refuses to run while errors remain:

```bash
python vs.py compile brief.json --out project.json
python vs.py plan project.json      # budget: cache hits, frames, estimated minutes, style report
python vs.py run project.json
```

`run` here is the delivery step, not a way to look at options: the approved plan is written once, the
piece is rendered once, and that export is the finished file. Compare directions on paper; `preview`
is only for a specific doubt that paper cannot settle, never a per-beat sweep. If something needs to
change after delivery, revise the plan, re-confirm it with the user, and deliver one new round rather
than rendering the piece again to see what happens.

`compile` maps beats onto the template vocabulary (equivalently: `hook` becomes a title or a big
number, `body` becomes a caption panel or a chart, `turn` becomes a quote card), wires the narration
so durations come from the voice, and picks transitions from the style signature.

### What "complete" means here

`validate` fails on: missing intent, missing on-screen text, placeholder `TODO` text, adjacent beats
sharing the same template *and* device, an unwritten premise or promise. It warns on: a first beat
that is not a hook, fewer than three distinct layouts when there are three or more beats, an
estimated duration more than 25% off target, and over-long subtitle lines.

## 2. Distinctiveness is generated, not hoped for

Every project carries a **style signature** derived from a seed. Same seed, same look; new seed, new
look. It contains:

| Field | Effect |
| --- | --- |
| `colors` | background, surface, border, text, dim, accent, accent2, accent3, chart series |
| `type` | scale and tracking |
| `layouts` | a shuffled order per template (`editorial`, `split`, `center`, `corner`, `fullbleed`, `banner`) |
| `motions` | a shuffled order of entrance families (`rise`, `scale`, `wipe`, `blur`, `slide`, `zoom`) |
| `transitions` | a shuffled order of xfade types used at section breaks |
| `texture` | `none` / `grain` / `dots` / `scanlines` / `grid`, plus an amount |
| `pacing` | `steady` / `build` / `punch` / `wave` / `calm` — scales every entrance and adds breathers |
| `vignette`, `radius`, `rule_style`, `subject_scale` | the small decisions that add up |
| `image_style` | a clause prepended to every generated image so a set matches |

Segments rotate through the layout and motion orders, so **adjacent beats never share a
composition** and accents cycle through the palette's harmony. Palettes are generated in HSL from a
hue family plus a harmony rule, then contrast-checked: text is pushed until it clears 8:1 against
the background and dim text until it clears 4:1.

Inspect or sample a direction without rendering:

```bash
python vs.py style --seed 2024 --swatch style.png      # palette chips + the plan in text
python vs.py style --topic "量子计算入门"                # derive a seed from the topic
python vs.py style --seed 99 --like 2024               # similarity between two directions
python vs.py style --seed 99 --history                 # closest past project
```

Re-roll a project without touching its file:

```bash
python vs.py run project.json --seed 777
```

`plan` prints a distinctiveness verdict:

```json
"style": {
  "seed": 2024, "palette": "violet", "pacing": "punch", "texture": "grain",
  "distinct_layouts": 4, "distinct_motions": 5, "distinct_transitions": 1,
  "adjacent_layout_repeats": 0, "closest_past_project": null, "verdict": "ok"
}
```

`adjacent_layout_repeats` must be 0. Past signatures are recorded in `~/.video-studio/history.json`,
so `closest_past_project` warns when a new piece would look like an old one.

Template-level override, when a cue needs a specific composition:

```jsonc
"data": { "visual": { "layout": "fullbleed", "entrance": "wipe", "density": "minimal",
                      "accent": "#38bdf8" } }
```

## 3. Generated imagery

Any OpenAI-compatible images endpoint works — OpenAI, SiliconFlow, DashScope, Volcengine Ark, or a
domestic aggregator. The key is stored in `~/.video-studio/config.json`, never in the project file,
and is masked in every command's output.

```bash
python vs.py setup --presets                                   # list known providers
python vs.py setup --provider siliconflow --key sk-xxxx \
                   --model Kwai-Kolors/Kolors --size 1024x1024
python vs.py setup --provider custom --base-url https://my-aggregator.example/v1 \
                   --path /images/generations --model my-image-model --key sk-xxxx
python vs.py setup --test test.png                              # prove the key works
```

Environment overrides for CI or one-off runs: `VS_IMAGE_API_KEY`, `VS_IMAGE_BASE_URL`,
`VS_IMAGE_MODEL`, `VS_IMAGE_PATH`, `VS_IMAGE_SIZE`.

Two ways to use it:

```bash
# one image
python vs.py imagegen "a lone figure on a rooftop at dusk" --out assets/hero.png --size 1536x1024
python vs.py imagegen "..." --out hero.png --dry-run      # show the request, send nothing

# everything a project asks for
python vs.py imagegen --from-project project.json --dry-run
python vs.py imagegen --from-project project.json
```

Inside a project, an asset can be a prompt instead of a path:

```jsonc
"assets": { "subject": { "prompt": "a lone figure on a rooftop at dusk",
                         "size": "1536x1024" } }
```

`render` (and `preview`) generate it before the scene loads. Generation is cached by prompt hash, so
re-rendering never pays twice, and the film's `image_style` clause is appended to every prompt so a
set of images reads as one body of work. `brief` already writes these prompts per beat.

Notes that matter in practice: generated images are used as `subject` in any template (the `pixel`
template still converts them to a sprite), the size you ask for should match the aspect you plan to
use, and `--dry-run` is the fast way to confirm a provider is wired up correctly before spending
credits.
