---
name: TraceLens
description: The visualization-tool canon played straight — white paper, hairlines, one blue, and every value in mono.
colors:
  canvas: "#fbfaf8"
  panel: "#ffffff"
  panel-2: "#f6f5f2"
  sunken: "#f2f1ed"
  line: "#e4e2dc"
  line-strong: "#cfccc3"
  ink: "#1a1a17"
  ink-2: "#55534c"
  ink-3: "#6b6860"
  accent: "#1b57e0"
  accent-ink: "#16409f"
  accent-wash: "#eef2fe"
  ok: "#0f7b3e"
  ok-wash: "#eaf5ee"
  warn: "#8a5a00"
  warn-wash: "#fbf2e0"
  stop: "#bd2b1c"
  stop-wash: "#fdeceb"
typography:
  display:
    fontFamily: "Pretendard Variable, Pretendard, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(2.1rem, 4vw, 3.2rem)"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.032em"
  headline:
    fontFamily: "Pretendard Variable, Pretendard, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(1.4rem, 2.2vw, 1.85rem)"
    fontWeight: 700
    lineHeight: 1.18
    letterSpacing: "-0.022em"
  title:
    fontFamily: "Pretendard Variable, Pretendard, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.05rem"
    fontWeight: 700
    lineHeight: 1.18
    letterSpacing: "-0.012em"
  lede:
    fontFamily: "Pretendard Variable, Pretendard, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(1.02rem, 1.25vw, 1.14rem)"
    fontWeight: 400
    lineHeight: 1.65
    letterSpacing: "normal"
  body:
    fontFamily: "Pretendard Variable, Pretendard, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.62
    letterSpacing: "normal"
    fontFeature: "\"cv03\", \"cv04\""
  md:
    fontFamily: "Pretendard Variable, Pretendard, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.94rem"
    fontWeight: 600
    lineHeight: 1.62
  sm:
    fontFamily: "Pretendard Variable, Pretendard, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.6
  xs:
    fontFamily: "Pretendard Variable, Pretendard, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.8rem"
    fontWeight: 400
    lineHeight: 1.55
  2xs:
    fontFamily: "Pretendard Variable, Pretendard, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.72rem"
    fontWeight: 700
    lineHeight: 1.6
    letterSpacing: "0.07em"
  label:
    fontFamily: "Pretendard Variable, Pretendard, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.7rem"
    fontWeight: 700
    lineHeight: 1.6
    letterSpacing: "0.09em"
  mono:
    fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, Consolas, monospace"
    fontSize: "0.855em"
    fontWeight: 400
    letterSpacing: "-0.01em"
    fontFeature: "liga 0"
  num:
    fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, Consolas, monospace"
    fontSize: "0.86rem"
    fontWeight: 400
    letterSpacing: "-0.01em"
    fontVariation: "tabular-nums"
  d-lg:
    fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, Consolas, monospace"
    fontSize: "13px"
    fontWeight: 600
  d-md:
    fontFamily: "Pretendard Variable, Pretendard, ui-sans-serif, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 700
    letterSpacing: "0.05em"
  d-sm:
    fontFamily: "Pretendard Variable, Pretendard, ui-sans-serif, system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 600
  d-xs:
    fontFamily: "Pretendard Variable, Pretendard, ui-sans-serif, system-ui, sans-serif"
    fontSize: "10px"
    fontWeight: 700
    letterSpacing: "0.09em"
rounded:
  xs: "4px"
  sm: "6px"
  md: "8px"
  pill: "999px"
spacing:
  stack: "16px"
  row: "18px"
  panel: "clamp(16px, 2vw, 22px)"
  gutter: "clamp(20px, 4vw, 44px)"
  section: "clamp(48px, 6vw, 84px)"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
    padding: "0 16px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.accent-ink}"
    textColor: "#ffffff"
  button-primary-lg:
    backgroundColor: "{colors.accent}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
    padding: "0 22px"
    height: "46px"
  button-primary-sm:
    backgroundColor: "{colors.accent}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
    padding: "0 10px"
    height: "30px"
  button-quiet:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0 16px"
    height: "40px"
  button-quiet-hover:
    backgroundColor: "{colors.panel-2}"
    textColor: "{colors.ink}"
  panel:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "{spacing.panel}"
  panel-bar:
    backgroundColor: "{colors.panel-2}"
    textColor: "{colors.ink-3}"
    padding: "9px 14px"
  tag-ok:
    backgroundColor: "{colors.ok-wash}"
    textColor: "{colors.ok}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
  tag-info:
    backgroundColor: "{colors.accent-wash}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
  tag-warn:
    backgroundColor: "{colors.warn-wash}"
    textColor: "{colors.warn}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
  tag-stop:
    backgroundColor: "{colors.stop-wash}"
    textColor: "{colors.stop}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
  navlink:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.sm}"
    padding: "6px 10px"
  navlink-active:
    backgroundColor: "{colors.panel-2}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "6px 10px"
  table-head:
    backgroundColor: "{colors.panel-2}"
    textColor: "{colors.ink-3}"
    padding: "10px 16px"
  input-number:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    typography: "{typography.num}"
    rounded: "{rounded.sm}"
    padding: "0 10px"
    height: "34px"
    width: "104px"
  switch-off:
    backgroundColor: "{colors.sunken}"
    rounded: "{rounded.pill}"
    height: "24px"
    width: "40px"
  switch-on:
    backgroundColor: "{colors.accent}"
    rounded: "{rounded.pill}"
    height: "24px"
    width: "40px"
  codeline-current:
    backgroundColor: "{colors.accent-wash}"
    textColor: "{colors.ink}"
    padding: "3px 14px 3px 0"
---

# Design System: TraceLens

## Overview

**Creative North Star: "The Working Diagram"**

TraceLens does one thing: it runs Python for real and draws what happened. So the site does not advertise the tool — it is a working instance of it. The landing page's hero is not a screenshot or a loop of a screen recording; it is `src/ui/TraceDiagram.tsx`, which pushes a recorded trace through the product's actual pipeline (`buildSnapshots → buildScreenplay → expandScreenplay → usePlayback`) and renders whatever comes out. Every value on that page came out of a real run. That is the whole aesthetic argument, and every other decision falls out of it: if the diagram is the protagonist, the chrome must recede.

The world is the visualization-tool category canon taken at full fidelity, played straight — **Observable · Excalidraw · Python Tutor** is the binding craft bar (PRODUCT.md, Brand Commitments). This was chosen over an invented world on purpose. A paper-white canvas (#FBFAF8) with white panels floating on 1px warm-grey hairlines, one technical blue that means structure and action and nothing else, monospace for anything a machine produced, and no gradient, tilt, glow, texture, or illustration anywhere. The system is quiet by construction so that the one moving thing on the screen — a highlighted line, an arrow from two names into one list — is unmistakably the thing you are meant to look at.

Two rejections are load-bearing and confirmed. First, the near-black neon dev-tool hero: refused, because a learner arriving with code they do not understand should not also have to decode the interface. Second, the invented illustrated world — a cut-paper poster direction was built and rejected outright; nothing from it survives, and it must not be reintroduced. The register is deliberately unaveraged: built at a density a developer will trust, but the first screen and every term in it are written for a learner.

**Scope: the whole product.** This system covers every surface the user can reach — the marketing and support routes at `/`, `/about`, `/help`, `/settings` and the 404, *and* the workbench at `/app`. There is no longer a second visual system in this repo. The dark-neon prototype is gone: `src/App.css` and `src/stage.css` have been deleted, and with them the last `#080b10` ground, the last cyan radial gradient, and the last Inter literal in running code.

The system is declared once, on `.tl` in `src/ui/ui.css`, and consumed in two layers. `src/ui/ui.css` carries the tokens plus the reading-surface components; `src/ui/app.css` carries the workbench regions and **defines no tokens of its own** — not a colour, not a type step, not a radius. It is a consumer, and that is the test for any future layer: if a new stylesheet needs to declare a token, either the token belongs on `.tl` or the design has drifted.

The two surfaces differ in *register*, not in vocabulary. The site is a Read surface, so it gets air, measure caps, and a 1160px shell. The workbench is an Operate surface, so the task outranks expression: a 100svh shell that does not scroll, 12px gutters between regions, and the editor and stage taking all the room the chrome can spare. Same paper, same hairlines, same one blue, same mono-for-values — arranged for a different job.

`html[data-surface]` survives as a **route-kind flag, and nothing more**. No CSS is keyed on it at all — not a colour, not a layout, not a scroll behaviour. It is resolved before first paint from `location.pathname` and kept in sync by the router, so a script can ask which kind of route is showing, and future route-kind logic has somewhere to hang. But the stylesheets do not read it, which is the strongest form the guarantee can take: the two surfaces cannot diverge on appearance through this attribute, because there is no rule for a future edit to extend.

**Dead but present.** Two files remain in the tree and are imported by nothing: `src/PixiStage.tsx` (a deliberately held asset per the planning document) and `src/tracing.ts` (marked for disposal). They are not a live boundary and no rule here accommodates them; they are simply not in the running app. `PixiStage.tsx` still contains an `Inter` font literal, which is the single finding the house detector reports across `src/` and `index.html` — a dead-code finding, not a system one. Anything revived from either file gets migrated onto these tokens first.

**Key Characteristics:**
- Paper-white canvas, white panels, 1px hairlines — depth by tonal step, not by shadow
- One accent (#1B57E0); green/amber/red exist only to carry the four support verdicts
- Pretendard Variable for all prose and UI (Korean + Latin); JetBrains Mono for every value
- Korean never breaks mid-word (`word-break: keep-all`)
- Motion is 120–160ms on one easing curve, and switchable off from two independent sources
- The product's own diagram is the hero, driven by the real pipeline over a real trace
- One system across both surfaces: a Read register for the site, an Operate register for the workbench, no second vocabulary

## Colors

A warm near-white paper with warm greys for ink and rules, one saturated technical blue, and three verdict colours that are rationed to a single job.

### Primary
- **Technical Blue** (`accent`): the only accent in the system. It marks *structure* — the current line's 2px left rule and `accent-wash` fill in the code column, the reference arrow and its marker head in the state diagram, the focused name box's stroke, the focus ring — and *action*: primary buttons, links, the switched-on toggle. Measured 5.77:1 on the canvas and 6.02:1 on white; white text on it is 6.02:1.
- **Deep Blue** (`accent-ink`): the pressed/hover state of the accent and the accent's *text* form when it has to sit inside a wash. White on it is 9.26:1; on `accent-wash` it reads 8.27:1. Used for the diagram's annotation line, the info tag's label, the numbered pipeline chips.
- **Blue Wash** (`accent-wash`): the ground under anything the accent has selected — current code line, focused name box, info tag, pipeline step number. Never a page background, never a section band.

### Secondary — the verdict triad
These three exist to carry the four support-matrix verdicts on `/help` and their echo on the landing page. They are not a general status palette.
- **Run Green** (`ok`) on **Green Wash** (`ok-wash`): 완전 지원 — code that plays with a purpose-built picture. 4.79:1 on its wash.
- **Caution Amber** (`warn`) on **Amber Wash** (`warn-wash`): 제한 재생 — code that plays only as far as the cap. 5.33:1 on its wash.
- **Refusal Red** (`stop`) on **Red Wash** (`stop-wash`): 범위 밖 — code blocked before it runs. 5.21:1 on its wash.
- The fourth verdict, 기본 지원 (table-only rendering), is carried by the **info** tag in `accent-ink` / `accent-wash` — it is a statement about what the product *does*, not a warning, so it borrows the structural blue rather than adding a fifth hue.

### Neutral
- **Paper** (`canvas`): the ground, unconditionally. It is declared on `:root` in `src/index.css` — together with `ink` as the document text colour and Pretendard as the document face — and `html`, `body` and `#root` take `background: inherit`. There is no route, no attribute and no media state under which the document is any other colour, so overscroll, the pre-mount frame, and the gap under a short page are all paper on every surface. **The ground is not themed, it is the floor.** A single unconditional declaration is what makes the flash impossible; a conditional one is what made it possible before.
- **Card White** (`panel`): every panel, table body, name box in the diagram, and quiet button. The only pure white in the system.
- **Rail Grey** (`panel-2`): panel title bars, table headers, nav hover and current-page state, the demo's footer bar, default tag ground. The one tonal step between white and paper.
- **Sunken Grey** (`sunken`): recessed grounds — inline `<code>`, the `stdout` readout, the off state of switches and segmented controls.
- **Hairline** (`line`): every separator and panel border in the system. It is deliberately faint (1.24:1 on canvas) because it separates surfaces rather than defining controls.
- **Strong Hairline** (`line-strong`): the darker rule for things that must read as *controls* — quiet button, number input, switch track, tag outlines, diagram box strokes. Measured 1.61:1 on white and 1.54:1 on canvas; see the named rule below, this is the system's remaining contrast debt.
- **Ink** (`ink`): headings, table first-column keys, values, current code line. 16.72:1 on canvas.
- **Ink Two** (`ink-2`): all body prose, ledes, table cells, resting nav links, code text. 7.38:1 on canvas.
- **Ink Three** (`ink-3`): the recessive tier — notes, uppercase labels, table headers, line numbers, field help, the diagram's axis labels and index numerals, the step counter. Measured 5.33:1 on canvas, 5.56:1 on white, 5.10:1 on `panel-2`, and 4.92:1 on `sunken` — it clears AA on every ground it is used against, including at its smallest sizes. It is recessive by intent, not by under-contrast.

### Named Rules
**The One Blue Rule.** #1B57E0 is the only accent. It says exactly two things — *this is the structure you should be looking at* and *this is the thing you can press*. If a screen contains a blue that means a third thing, one of them is wrong.

**The Verdict Colour Rule.** Green, amber and red are spent entirely on the four support verdicts (완전 지원 / 기본 지원 / 제한 재생 / 범위 밖). They may not be borrowed for success toasts, chart series, hover states, diffs, emphasis, or build status. The rule holds with no exception anywhere in the build: the `/about` slice-status chips used to run green and blue and are now the neutral tag, because "Slice 1 완주" is a project fact, not a judgement about the user's code. A product whose voice is "we tell you what we can't do" cannot afford to spend its refusal red — or its approval green — on anything else. If a new state needs a colour, it gets the neutral tag or the accent.

**The Drawn-State Rule.** Inside a drawing — the landing diagram and all four workbench stage views — colour carries exactly one distinction, and it is *is this the thing happening right now*. Three assignments, no fourth: an element at rest is `panel` fill on a `line-strong` stroke; the active or focused element is `accent-wash` fill on an `accent` stroke, with its text stepping to `accent-ink`; a container that holds other elements is `sunken` on `line`. The earlier grammar gave each primitive its own hue — cyan for defaults, pink for active, green for objects — which meant the colour told you which view you were looking at rather than what had just changed. That is backwards, and it is gone. A variable box, a stack frame, a list cell and a graph node now highlight identically, so a learner learns one visual signal instead of four.

**The Wash-and-Ink Pair Rule.** Every semantic colour ships as a pair: a saturated ink for the glyph and a near-white wash for its ground. Use them together or not at all — never a saturated fill on the canvas, never a wash without its ink on top.

**The Three Inks Rule.** Text has exactly three tiers — `ink` for what a heading or a value says, `ink-2` for prose, `ink-3` for the recessive layer — and all three clear AA on every ground in the system. A fourth, lighter grey is not available: if something needs to recede further than `ink-3`, it needs less prominence, not less contrast.

**The Hairline-Is-Not-A-Boundary Rule.** `line` (1.24:1 on canvas) and `line-strong` (1.61:1 on white) both sit below the 3:1 minimum for non-text boundaries. This is recorded debt, not a licence: a hairline may separate surfaces, but it may never be the *only* thing marking a control's edge or state. Every control that leans on one also carries a ground step (quiet button, switch track, segmented trough) or the accent (focus ring, switched-on state). Darken these two before adding any control that would depend on the rule alone.

## Typography

**Display Font:** Pretendard Variable (with Pretendard, `ui-sans-serif`, `system-ui`, `sans-serif`)
**Body Font:** Pretendard Variable — the same face; there is no display/body split
**Label/Mono Font:** JetBrains Mono (with `ui-monospace`, `SFMono-Regular`, Consolas, `monospace`)

Both faces load from CDN in `index.html` — Pretendard from jsDelivr, JetBrains Mono from Google Fonts at weights 400/500/700.

**Character:** One neutral, high-legibility Korean-Latin face doing all the talking, and one monospace face doing all the *showing*. Pretendard was chosen because Korean and Latin sit on the same rhythm without a fallback seam — this is a Korean-language product and its 한글 must not look like a substitution. Headings are set tight (−0.022em to −0.032em, 1.1–1.18 leading) and balanced (`text-wrap: balance`); prose runs long and calm at 1.62. Pretendard's `cv03`/`cv04` alternates are on at the root, which straightens the Latin `l` and `1` so they do not read as mono's neighbours.

### Hierarchy

The ramp is a closed set of tokens, not a set of observed values. Nine named steps are declared on `.tl`, and every `font-size` across both stylesheets resolves to one of them or to one of the four `--d-*` drawing steps. Four literals remain in total: the 16px base on `.tl` itself, which the rem steps are measured from, and the three fluid `clamp()` roles that scale with the viewport.

**Fluid roles** — sized by viewport, not by step:
- **Display** (700, `clamp(2.1rem, 4vw, 3.2rem)`, 1.1, −0.032em): one per route, top of page. Hard-broken by hand in the hero so the two lines of the thesis land as two lines.
- **Headline** (700, `clamp(1.4rem, 2.2vw, 1.85rem)`, 1.18, −0.022em): section openers. Always paired with a body paragraph inside a 62ch head block.
- **Lede** (400, `clamp(1.02rem, 1.25vw, 1.14rem)`, 1.65, `ink-2`, max 58ch): the one paragraph under a display heading.

**Stepped roles** — the nine tokens, largest first, with what each one is for:
- **Title** (`--t-title`, 1.05rem, 700, −0.012em): definition-row terms, pipeline steps, panel bar headings, settings group titles. In the pipeline it is additionally set in mono, because the four names (`Tracer`, `Digest`, `Director`, `Player`) are module identifiers, not words.
- **Body** (`--t-body`, 1rem, `ink-2`, max 68ch): all prose; also the brand wordmark and the large button, the two places chrome should read at reading size.
- **Medium** (`--t-md`, 0.94rem, 600): the name of a setting — one notch under prose because it is a label for a control, not a sentence.
- **Small** (`--t-sm`, 0.875rem): the workhorse secondary step — notes, nav links, the default button, the demo caption, all table body text, the skip link.
- **Extra small** (`--t-xs`, 0.8rem): dense controls and dense data — small buttons, tags, segmented buttons, the step counter, field help, and the code lines in the demo.
- **Double extra small** (`--t-2xs`, 0.72rem, 700, 0.07em): the smallest text allowed — table headers, code line numbers, the pipeline number badge. Nothing may be set smaller.
- **Label** (`--t-label`, 0.7rem, 700, 0.09em, uppercase, `ink-3`): panel-bar titles only — the machine-side naming of a region. Not an editorial device. It sits below `--t-2xs` because uppercase tracked caps read larger than their point size.
- **Mono inline** (`--t-mono`, 0.855em of its parent, ligatures off, −0.01em): every inline value. As `code.tl-mono` it additionally takes a sunken ground, a hairline border and a 6px radius, and never wraps. Being an `em`, it stays proportional to whatever step it sits inside.
- **Numeral** (`--t-num`, 0.86rem, `tabular-nums`, `ink`): step counters, measured results, the number field — anything that changes in place.

**The drawing sub-scale.** SVG text is the one sanctioned exception to the rem ramp, and it is now a single four-step scale declared on `.tl` alongside the type ramp — **`--d-xs` 10px, `--d-sm` 11px, `--d-md` 12px, `--d-lg` 13px** — shared by every drawing surface in the product.

The exception exists because a rem inside a `viewBox` is scaled twice: once by the root font size, then again by the transform that fits the drawing to its container. The label drifts off the shape it names, which is the one thing a labelled diagram must never do. Px is the correct unit inside a viewBox, and a px scale is only safe *because* it is inside one — these four steps have no authority outside an SVG.

Both drawings map onto it by role, not by coincidence:
- **`--d-lg` (13px)** — the thing being named: variable names and cell values in the landing diagram, stack-frame names and object values on the workbench stage. It is the only step that ever carries data.
- **`--d-md` (12px)** — a drawing's own title, on the stage where several views need to announce themselves.
- **`--d-sm` (11px)** — annotation and type hints: the aliasing note, the stage's type labels.
- **`--d-xs` (10px)** — the smallest marks that are not data: axis labels and index numerals.

The unification cost one value: the landing diagram's annotation was 11.5px and is now 11px. Half a pixel bought a scale two components can share, which is the right trade — a sub-scale with a step used once is not a scale, it is a leftover.

### Named Rules
**The Nine Steps Rule.** Every `font-size` in the product is a token: one of the nine `--t-*` steps, one of the four `--d-*` steps inside an SVG `viewBox`, or one of the three fluid `clamp()` roles. The only literal left in either stylesheet is `font-size: 16px` on `.tl`, which is the base the rem steps are measured from. A new literal size is not a design decision, it is drift — the site stylesheet reached 16 distinct literal sizes across 29 declarations before this ramp was imposed, and the collapse cost nothing visible.

**The Mono-Means-Data Rule.** JetBrains Mono is a claim, not a style: anything set in it came out of a real run or is a real identifier — a value, a variable name, a line number, a step count, a measured result, a `stdout` line, a module name. Prose never takes mono, and a number the run did not produce never takes it. The rule holds without exception across the build: the footer tagline, the one place prose had borrowed the face, is now set in Pretendard like every other sentence.

**The Keep-All Rule.** The `.tl` root sets `word-break: keep-all` with `overflow-wrap: anywhere`. Korean must never break mid-word — a 어절 breaks at its boundary or not at all — while a long Latin identifier may break anywhere rather than push the layout wide. Any new scroll container or narrow column inherits this; do not override it locally.

**The Measure Rule.** Prose is capped everywhere, by role: 68ch default, 58ch lede, 62ch section head and honesty aside, 54ch footer note, 52ch settings field help, 36ch footer tagline. A paragraph without a cap is a bug.

## Layout

One shell, one gutter, one column of thought. `.tl-shell` is 1160px max, centred, with a fluid gutter of `clamp(20px, 4vw, 44px)` that is shared by the nav and footer so the brand mark, the headline and the footer text all sit on the same left edge at every width.

Vertical rhythm is coarse and regular: sections are `clamp(48px, 6vw, 84px)` of padding-block, each opened by a 1px top hairline. There are no coloured bands, no alternating backgrounds, no full-bleed sections. The page reads as one continuous sheet ruled into parts. Inside a section, the default stack step is 16px; row-based lists carry a bottom hairline per row over 16–18px of padding-block (16px for definition and settings rows, 18px for pipeline steps).

Two families of repeating structure, and they behave differently on purpose. **Pipeline steps** are an auto-fitting grid at `minmax(230px, 1fr)` — four peer stages that may sit side by side because none is read before another. **Definition rows** are a single full-width column: each row is itself a two-column grid (term at `0.42fr`, definition at `1fr`) closed by a hairline that spans the whole measure. A term and its definition read as one horizontal line down a shared left edge, which is what a definition list is for; the earlier side-by-side card grid broke that scan and is gone.

Three intentional asymmetric splits exist: the demo panel at `0.82fr / 1.18fr` (code narrower than diagram — the diagram is the protagonist), the prose-plus-panel split at `1.05fr / 0.95fr`, and the definition row's `0.42fr / 1fr`.

The nav is a 56px sticky bar with a translucent canvas ground (`color-mix(in srgb, var(--canvas) 88%, transparent)`) and `backdrop-filter: saturate(1.4) blur(10px)`, closed by a bottom hairline. The brand sits left with `margin-right: auto`, the route links centre-right, and the primary action (`실행하기`) is the last element.

**Responsive.** Two breakpoints, both content-driven:
- **≤900px** — the demo's code/diagram split collapses to one column and the code pane's right border becomes a bottom border; the prose/panel split collapses.
- **≤720px** — the nav stops being sticky, wraps to auto height, and the link row moves to a third full-width row with horizontal overflow; settings fields go single-column with the control left-aligned under its label; definition rows drop their term column so the term sits above its definition.

Wide content never widens the page: tables live inside `.tl-scroll`, a bordered, rounded, `overflow-x: auto` container with sticky headers.

**The workbench inverts the model.** Where the site is a scrolling sheet capped at 1160px, `/app` is a `100svh` flex shell that does not scroll at all: `.tl-app` is `overflow: hidden`, and scrolling happens inside the regions that need it — the console, the inspector, the editor — never at the document. The work area is a two-column grid at `0.88fr / 1.12fr`, stage side wider than editor side for the same reason the landing demo is: the drawing is the thing being read. Gutters shrink from the site's fluid `clamp()` to a flat 12px between regions, because on an Operate surface every pixel of air is a pixel not showing the trace. The one thing the two share exactly is the horizontal gutter — `.tl-work` uses `--gutter`, so the workbench's outer edges line up with the site's.

The workbench's height is managed entirely by `.tl-app` itself — `100svh` with `overflow: hidden` — and not by anything keyed on the route. `src/index.css` briefly carried a `html[data-surface="app"]` block for this and it was deleted once it turned out to restate the document default: `body` already declares `overflow-y: auto`, and `overflow: visible` on the root element computes to `auto` by spec. Worth recording as a habit rather than an incident — dead CSS was removed everywhere else in this migration, and a no-op kept because it marks where something might go later is the same drift wearing a better name.

**At ≤1000px the workbench stops pretending to be an application.** The columns stack, `.tl-app` releases its fixed height and its `overflow: hidden`, and the page becomes a normal scrolling document; the editor takes a fixed 320px and the stage a 300px minimum so neither collapses. A viewport-filling two-pane layout below that width produces two unusably short panes, and a scrolling page with two usable ones is the better trade. Note this is the workbench's own breakpoint — the site's are 900px and 720px — because it is set by the point at which two panes stop fitting, not by a device class.

### Named Rules
**The One Sheet Rule.** On reading surfaces, sections are separated by a 1px hairline and vertical air — never by a background colour change, a card, or a full-bleed band. There is exactly one page ground.

**The Register Rule.** Read surfaces get air, measure caps and a centred shell; Operate surfaces get a viewport-filling shell, flat 12px gutters, and internal scroll. Same tokens, same components, different budget for space. Deciding which one a new surface is comes before laying it out — the failure mode is a workbench that scrolls like a page, or a page that traps its content in panes.

**The Delete-It Rule.** A rule that does nothing gets removed, not commented, not kept as a placeholder. This migration deleted `App.css`, `stage.css`, the unused `.tl-roles` block, the duplicate `.tl[data-still]` rule, and a `html[data-surface="app"]` block that only restated the document default. Each was individually harmless; together they are the exact material a design system rots into, because the next reader cannot tell an inert rule from a load-bearing one and edits around both. If something is being kept for a future need, the future need can add it back in one line — and it will add it back knowing what it is for.

**The Fluid-Between-Two-Stops Rule.** Sizes that scale use `clamp()` between a phone value and a desktop value; the two media queries exist only for structural collapses (multi-column → single column) that `clamp()` cannot express.

## Elevation & Depth

The system is flat. Depth is carried by a four-step tonal ladder — `sunken` → `canvas` → `panel-2` → `panel` — and by 1px hairlines, not by shadow. A panel reads as raised because it is pure white on warm paper with a rule around it, which is exactly how Observable and Python Tutor separate a result from its page.

Exactly one element casts a real shadow: the landing page's trace panel. It is the product, it is the only thing on the page that moves, and lifting it a millimetre off the sheet is the one place elevation earns its keep. Everything else that looks lifted (the switch knob, the pressed segment) uses a 1–2px contact shadow to sell a physical control, not to rank surfaces.

### Shadow Vocabulary
- **Panel lift** (`box-shadow: 0 1px 2px rgba(26,26,23,0.05), 0 4px 12px rgba(26,26,23,0.05)`): the trace panel on `/`. Nothing else.
- **Knob contact** (`box-shadow: 0 1px 2px rgba(26,26,23,0.25)`): the switch knob only.
- **Segment contact** (`box-shadow: 0 1px 2px rgba(26,26,23,0.1)`): the pressed segment in a segmented control only.
- **Press inset** (`box-shadow: inset 0 1px 2px color-mix(in srgb, var(--ink) 24%, transparent)`): the primary button's `:active`. The button darkens *and* sinks; the quiet button only darkens. The shade is mixed from `ink` rather than from literal black, so the press reads as the page's own darkest ink pressed into the surface and would follow the palette if `ink` ever moved. The three remaining `rgba(26,26,23,…)` shadows are the same warm ink expressed literally.

### Named Rules
**The One Shadow Rule.** One element in the system casts an ambient shadow, and it is the trace panel. If a new surface needs to feel separated, give it white ground on paper and a hairline — reaching for a shadow means the tonal ladder was skipped.

## Shapes

Rectilinear and calm. Four radii, all tokenised, and no fifth: `--r` **8px** for containers (panel, table scroller, code block, the demo's focus ring), `--r-sm` **6px** for controls (buttons, nav links, inputs, inline code, skip link), `--r-xs` **4px** for the small things nested *inside* a control (the global focus ring, segmented buttons, the pipeline number badge), and `--r-pill` **999px** for tags and the switch track. The one literal left is `border-radius: 50%` on the two circular knobs — a circle is a shape, not a step on a radius scale.

Borders do the work that shadow does not. Every container is a 1px `line` rule; every control is a 1px `line-strong` rule. Boxes are never borderless-on-white — a white panel without its hairline disappears into the page.

The state diagram carries the one deliberate exception. Variable name boxes are 6px-rounded rectangles (they are *labels*), while list cells are drawn with **square corners and shared edges** so a sequence reads as contiguous memory rather than as a row of chips. Index numerals sit outside the cell, below it, in `ink-3` mono at 10px. The reference arrow is a single cubic bezier at 1.5px with a solid triangular marker head, drawn in the accent — no dashes, no curves-for-decoration.

The brand mark is the tool's own idea drawn at 20px: two 7×9 rounded rects in `currentColor` at 1.6px stroke (two live cells) plus a 2px accent vertical rule (the cursor pointing at one moment in the run). It is a real drawing, not a glyph from an icon set.

### Named Rules
**The Four Radii Rule.** 8px container, 6px control, 4px nested-in-control, 999px tag — `--r`, `--r-sm`, `--r-xs`, `--r-pill`. A literal radius is a mistake unless it is a circle (`50%`) or a diagram primitive earning its geometry, as the square list cell does.

**The Hairline-Always Rule.** Every panel, table, scroller, input and quiet button carries a visible 1px border. Nothing floats on white without a rule.

## Components

### Buttons
- **Shape:** softly rounded (6px), fixed heights, never full-width.
- **Primary:** blue ground, white label, 600 weight, 40px tall with 16px side padding; `--lg` at 46px / 22px for hero actions; `--sm` at 30px / 10px for the nav action and inline controls.
- **Hover / Active:** ground deepens to `accent-ink` over 120ms; active adds the press inset. No lift, no scale, no glow.
- **Quiet:** white ground, `line-strong` border, ink label — the secondary of every pair (`어떻게 동작하나`, `기본값으로 되돌리기`, the demo's play/pause). On hover the ground steps to `panel-2` and the border darkens to `ink-3`.
- **Disabled:** 45% opacity, `not-allowed`. No separate colour.
- Buttons and links share one class family, so a `<Link>` styled `tl-btn` is visually identical to a `<button>` — actions look like actions regardless of element.

### Tags
- **Style:** pill (999px), 2px/8px, 0.75rem at 600, with a 6px dot in `currentColor` before the text — so the verdict's colour appears twice, as dot and as label, and survives being read at a glance.
- **Variants:** `ok` / `info` / `warn` / `stop` carry the four support verdicts; the unmodified base (grey ground, `ink-2`) is a neutral state chip. Border colour is mixed from the semantic hue into the hairline (`color-mix(in srgb, var(--ok) 30%, var(--line))`) so the outline tints without shouting.
- **State:** tags are read-only status. On `/help` the same tag markup is also used as anchor links to the four verdict sections — the hue is the wayfinding.

### Panel
- **Corner Style:** 8px.
- **Background:** white on paper; the optional title bar is `panel-2` with a bottom hairline and top corners matched to the panel.
- **Shadow Strategy:** none, except the trace panel (see Elevation).
- **Border:** 1px `line`, always.
- **Internal Padding:** `clamp(16px, 2vw, 22px)`; the title bar is a tighter 9px/14px so it reads as chrome.

**The No-Nesting Rule.** A panel never contains another panel. Inside a panel, separation is by hairline row, not by a second card.

**Second mode: the panel as a column.** On the workbench the same `.tl-panel` is used as a flex column of hairline-separated regions — `.tl-col.tl-panel`. The left column runs bar → editor → console; the right runs bar → stage → narration → transport → inspector. Each region carries a `border-top: 1px solid var(--line)` and, where it is chrome rather than content, a `panel-2` ground; the content regions (editor, stage) take `flex: 1` and the chrome regions size to their content. Region grounds alternate white for content and `panel-2` for chrome, which is what makes five stacked regions legible without a single nested border.

This is the No-Nesting Rule under real load, and it holds: an application shell with five stacked regions and still no container inside a container. It is the answer whenever a dense surface seems to need cards — stack hairline regions in one panel instead. The column mode also brings its own overflow discipline: every level from `.tl-app` down carries `min-height: 0` and `overflow: hidden`, because a flex child defaults to `min-height: auto` and one missing declaration lets a long console push the whole shell past the viewport.

### Tables
- **Style:** data-ink first — no zebra striping, no vertical rules, no outer border of its own (the `.tl-scroll` wrapper supplies it). Rows are separated by hairlines; the last row's border is removed.
- **Header:** sticky, `panel-2` ground, 0.72rem uppercase at 0.07em in `ink-3`, left-aligned, never wrapping.
- **Cells:** 12px/16px, `ink-2`, top-aligned. The first column is the key and takes `ink` at 600.
- **Hover:** the whole row steps to `panel-2`.
- **Numbers:** any measured value takes `tl-num` — mono, tabular, `ink` — so a column of results aligns on its digits.

### Skip link
- **Character:** invisible until it matters, then unmistakable.
- **Style:** absolutely positioned at `left: -9999px` at rest — offscreen but still in the tab order and still announced. On `:focus` it lands at the page gutter, 10px from the top, as a solid accent chip with white text at Small (0.875rem, 600) on a 6px radius, above everything at `z-index: 60`.
- **Target:** `#tl-main`, a wrapper with `tabIndex={-1}` and `outline: none` on focus — programmatically focusable so the skip actually moves the caret, but it never draws a ring of its own, since the destination is a region rather than a control.
- Rendered by the page shell, so every site route has it as the first focusable element.

### Definition rows
- **Character:** the workhorse of `/` and `/help` — a term and the sentence that earns it, on one line.
- **Structure:** a single full-width column of rows; each row is a two-column grid (term `0.42fr` / definition `1fr`) with a `clamp(24px, 4vw, 56px)` column gap and 16px padding-block. The list carries a top hairline; each row carries a bottom hairline that spans the full measure, so the rules read as one continuous ruling rather than as card edges.
- **Type:** term in Title (1.05rem, 700, `ink`), definition in Body (`ink-2`), no margin on the paragraph — the grid owns the spacing.
- **Mobile (≤720px):** the term column collapses and the term sits above its definition, hairlines unchanged.

### Inputs and settings controls
- **Number field:** 104×34px, white ground, `line-strong` border, 6px radius, mono tabular value. Focus swaps the border to the accent (on top of the global focus ring).
- **Number field, commit-on-blur:** the field holds the in-progress text as a draft string and commits the parsed number on blur or Enter, never per keystroke. Clamping mid-type is a real bug in a range like 1,000–500,000 — the first digit of `1000` is `1`, which a per-keystroke clamp snaps to the minimum and the user can never finish the number. A non-finite draft reverts to the last committed value rather than writing garbage. Any future field with a numeric range inherits this pattern.
- **Switch:** 40×24px pill, `sunken` ground with a `line-strong` track; on, the track becomes solid accent and the 18px white knob translates 16px over 160ms. Built as a `<button role="switch" aria-checked>`, never a bare checkbox.
- **Switch, disabled:** 50% opacity and `not-allowed`, used when a setting cannot apply — the AI-director toggle when the build ships without an API key. The state is shown, not hidden: a control that is off *because it cannot be on* still tells the user it exists. (Buttons disable at 45%; the two values differ by 5% in the build and could reasonably be unified.)

**The Commit-On-Blur Rule.** A numeric field holds the in-progress text as a draft string and commits the parsed number on blur or Enter, never per keystroke. Clamping mid-type is a real bug in a range like 1,000–500,000: the first digit of `1000` is `1`, which a per-keystroke clamp snaps to the minimum, and the user can never finish the number. A non-finite draft reverts to the last committed value.
- **Segmented control:** a 2px-padded `sunken` trough with a `line-strong` border; the pressed segment lifts to white with a contact shadow. Uses `aria-pressed`, tabular numerals for the speed values (`1×`, `1.5×`…).
- **Field row:** label + help text on the left, control right-aligned, 16px padding-block, hairline between rows, first row unruled. Help text is capped at 52ch.

### Navigation
- **Style:** 56px sticky bar, translucent paper with a blur, bottom hairline.
- **Links:** 0.875rem at 500 in `ink-2`; hover fills `panel-2` and darkens to `ink`; the current route is `aria-current="page"` and takes the same fill at 600 weight. There is no underline and no indicator bar — the fill *is* the state.
- **Mobile (≤720px):** the bar unsticks and the link row wraps to its own full-width scrollable line, keeping the brand and the primary action on the first row.

### The code editor
- **Character:** a third-party surface that must not look third-party.
- **Theme:** Monaco runs a theme named `tracelens`, defined in `src/App.tsx` from the token values rather than left on a vendor default: white ground, `ink` foreground, accent cursor, an accent-derived selection, hairline widget borders, and hairline-toned scrollbar sliders. Line numbers recede and their active state steps up to `ink-2`.
- **Syntax colours come from the existing palette, not from a syntax scheme.** Keyword takes `accent-ink`, string takes `ok`, number takes `stop`, comment takes a muted warm grey. The product already assigns meaning to those three hues, so a Python keyword and a support verdict never collide on screen — they are never on screen together.
- **Current line:** decorated by the app rather than by Monaco's default — an `accent-wash` band with a 3px accent glyph in the gutter, matching the landing demo's current-line treatment exactly. The same event reads the same way whether the user is watching the marketing page or their own code.

**The Vendor Surface Rule.** Any third-party UI that renders inside the product — editor, chart library, map, embedded viewer — is themed from these tokens before it ships. A vendor default is a second design system arriving through the back door, and it will not match on ground, on ink, or on accent. If the vendor cannot be themed, that is an argument against the vendor.

### Workbench regions
- **Run bar:** the panel bar in its action mode — primary run button, state tags, and a right-aligned `--t-2xs` hint pushed over by `margin-left: auto`.
- **Console:** capped at 152px, `panel-2` ground, mono at `--t-xs`, `white-space: pre-wrap` with `word-break: break-all` so a long traceback wraps instead of scrolling sideways. Empty state recedes to `ink-3` rather than collapsing, so the region does not appear and disappear as the user runs code.
- **Stage:** white ground, `flex: 1`, minimum 220px. Its empty state is a centred `ink-3` sentence at Small that tells the user what to do, not that something is missing.
- **Narration bar:** `panel-2`, `ink-2` at Small, minimum 44px so the transport below it never jumps as captions change length. It honours the product's caption-size setting through `data-size`, stepping to `--t-xs` or `--t-body`. The chapter tag reuses the info tag exactly.
- **Transport:** a chapter progress strip of pill segments over a `sunken` track, plus a 32px square control cluster. The play control takes the accent; everything else is quiet. Speed options reuse the segmented control at `--t-2xs`.
- **Inspector:** `panel-2`, capped at 190px with its own scroll, a `--t-label` heading, and a two-column mono table whose key column recedes to `ink-3` at 30% width.
- **Issue banners:** the verdict palette doing its job in the app — `block` takes `stop` on `stop-wash`, `warn` takes `warn` on `warn-wash`, both with the `color-mix` outline the tags use. These are the same four verdicts the `/help` matrix documents, arriving at the moment they apply.
- **Loading overlay:** an 88% `panel` scrim with a 2px blur over the stage, a 22px spinner whose top border is the accent, and a Small `ink-2` label. It covers the stage only — the editor stays live while Python loads.

### TraceDiagram — the signature component
The landing hero, and the reason the system looks the way it does. It is a `<figure>` containing a single panel with three registers:

1. **Title bar** — a `tl-label` region name, a `실제 트레이스` green tag, and a right-aligned `n / total` step counter in mono.
2. **Body** — a two-column split. Left: the source lines, each a 34px right-aligned mono line number plus the code, with the currently-executing line marked by a 2px accent left rule, an `accent-wash` ground, and a step from `ink-2` to `ink` on the text. Right: an SVG state diagram (`viewBox 0 0 520 H`, height computed from the live locals count) with variable name boxes on a 40px row pitch at x=8 and the referenced object's cells at x=252 on an 84×44 cell grid; when a name is in the current step's focus set, its box swaps to `accent-wash` / accent stroke / `accent-ink` text, and it *transitions* there — 200ms on fill and stroke for the box, 200ms on fill for the label — so the eye is carried from the old focus to the new one instead of being asked to spot a jump cut. A bezier arrow runs from each referencing name to the object, and when two names point at one object, an `accent-ink` annotation says so in Korean. Below the SVG, a sunken `stdout` readout appears only when the run has produced output.
3. **Foot bar** — a small quiet play/pause button and the step's narration in an `aria-live="polite"` caption.

Behaviour that is part of the design: it autoplays on mount, then re-loops 2.6s after reaching the end; under `still` it jumps straight to the final frame and stays there. A figcaption under the panel states plainly that the values came from a real execution.

**It is also a transport control, so it is operable from the keyboard.** The `<figure>` carries `tabIndex={0}` and `role="group"` with an `aria-label` that names its own key bindings, and takes a focus ring of its own — 2px accent at 3px offset on the 8px container radius, wrapping the whole panel rather than any one child. Space or Enter toggles play, Left and Right arrows step scene by scene, Home returns to the start. The figcaption spells the bindings out in a trailing `ink-3` span rather than hiding them in an attribute, because a keyboard affordance nobody can see is not an affordance. Any future element that plays on its own inherits this: focusable, self-describing, and driveable without the mouse.

**The Real-Pipeline Rule.** Any surface that demonstrates the product renders from a real trace through the real pipeline. No mocked frames, no hand-authored "example" state, no video. The product's first principle is that the screen does not lie about the code; a fake demo would break it on the marketing page before a user ever reaches the tool.

**The No-Empty-Frame Rule.** A view that has nothing to draw must not be drawn. `src/components/Stage.tsx` asks each chosen primitive whether the current snapshot actually contains what it needs — a sequence needs a non-empty list, an object graph needs a reachable object, a call stack needs frames — and falls back to the variables view when the answer is no. The Director picks what is worth showing, but it can be wrong about a given scene, and the renderer is the last place that can catch it. This is the planning document's §7 guarantee (실패해도 빈 화면은 없다) enforced where it is actually visible: an empty stage reads to a learner as *the tool broke*, never as *this scene had no list*. Every new stage primitive ships with its own `canRender` predicate, and the terminal fallback is always the view that can draw anything.

### Motion
Not a component, but a system-wide behaviour with one shape: **120–200ms on `cubic-bezier(0.2, 0, 0, 1)`**, and only on properties that indicate state — background, fill, stroke, border-colour, text-decoration-colour, box-shadow, and the switch knob's transform. Nothing animates on load, nothing animates on scroll, and nothing eases longer than 200ms.

**The Graded Duration Rule.** Duration is graded by how much the change means, not by taste. **120ms** is chrome acknowledging a pointer (nav fill, button ground, segment). **140ms** is a control settling (link underline, switch track). **160ms** is the reading surface moving (the current code line's highlight, the knob's travel). **200ms** — the ceiling — belongs to one thing: the state diagram's name boxes changing fill and stroke as focus moves between variables. That is the single transition a user is meant to *watch* rather than merely register, so it gets the longest curve in the system, and nothing else may claim it.

**Motion reduction is document-wide.** There is exactly one CSS rule that does the flattening — `html[data-still="true"] *` in `src/index.css` — and it zeroes animation and transition duration, pins `animation-iteration-count` to 1, and forces `scroll-behavior: auto` for every element on the page, both surfaces included. The site stylesheet used to carry a duplicate `.tl[data-still="true"]` block; it was deleted, because two rules doing the same job is two places to forget. `@media (prefers-reduced-motion: reduce)` remains in the site stylesheet as the no-JS floor.

Two inputs feed the one flag, and either alone switches it on: the OS `prefers-reduced-motion` preference, read in JS, and the product's own 모션 줄이기 setting. They are folded into a single `still` boolean which is written to `document.documentElement`. `still` is additionally threaded into `TraceDiagram` as a prop, so the trace holds on its final frame rather than flickering through its steps at zero duration — reduced motion should mean *see the result*, not *see the same animation instantly*.

**The Transform-Only Rule.** Animate `transform` and `opacity`, never a layout property. The chapter progress strip makes the case: its segments thicken on hover via `scaleY(1.6)` against a `transform-origin: center`, and each segment's fill advances via `scaleX` from `transform-origin: left center` — not `height` and not `width`. Both used to animate the layout property directly, which puts every frame through layout and paint on a bar that updates continuously during playback. A transform is composited, so the transport stays smooth while the trace plays. The one animation in the system that is not a state transition — the loading spinner's `rotate(360deg)` — is also a transform.

**The JS-Tween Rule.** A CSS override cannot stop a JavaScript tween: GSAP writes inline styles frame by frame and `transition-duration: 0.001ms` never touches it. So any JS-driven animation must read `document.documentElement.dataset.still` itself and zero its own duration — as `src/components/views/SequenceView.tsx` does, starting its cells at their final scale and opacity with `duration: 0` when the flag is set. The CSS rule is a floor, not a guarantee; anything that animates outside CSS is responsible for its own compliance.

## Do's and Don'ts

### Do:
- **Do** build every new surface out of the four existing primitives — panel, hairline row, tag, table — before inventing a fifth.
- **Do** separate surfaces with a 1px `line` rule and a step on the tonal ladder (`sunken` → `canvas` → `panel-2` → `panel`). That is the whole depth model.
- **Do** set every value, identifier, count, and measured result in JetBrains Mono with `tabular-nums`, and everything a human wrote in Pretendard.
- **Do** cap prose at its measure token (68ch body, 58ch lede, 62ch head, 52ch field help) and let Korean break only at 어절 boundaries.
- **Do** give every interactive element the global focus treatment (2px accent outline, 2px offset, `--r-xs` radius) and reach it through `:focus-visible`, not `:focus`. A skip link is the exception that uses plain `:focus`, because it must reveal itself however focus arrived.
- **Do** take every `font-size` from the nine `--t-*` steps (or a `--d-*` step inside an SVG `viewBox`), and every radius from the four `--r*` tokens.
- **Do** make anything that plays on its own keyboard-operable and self-describing: focusable, `role="group"` with an `aria-label` naming its keys, space/arrows/Home wired up, and the bindings written visibly in the caption.
- **Do** have JS-driven animation read `document.documentElement.dataset.still` and zero its own duration. CSS cannot reach a GSAP tween.
- **Do** honour motion reduction from every source — `prefers-reduced-motion` and the product's 모션 줄이기 setting, both of which land on `html[data-still="true"]` — and pass `still` down to anything that plays on its own so it holds its final frame rather than animating instantly.
- **Do** commit a numeric field's value on blur or Enter, holding the in-progress text as a draft. Clamping per keystroke makes any multi-digit minimum untypeable.
- **Do** pair every semantic colour with its wash, and put the semantic hue on the outline too via `color-mix` into the hairline.
- **Do** render product demonstrations from a real trace through the real pipeline.
- **Do** state a route's scope and limits on the page itself; the honesty asides in `ink-3` under the scope tables are part of the visual system, not filler.
- **Do** theme any third-party UI from these tokens before it ships — editor, chart, map, embedded viewer. A vendor default is a second design system arriving through the back door.
- **Do** decide whether a new surface is Read or Operate before laying it out, and give it the matching space budget.
- **Do** stack hairline regions inside one panel when a dense surface seems to need cards. Five regions in one panel is the proven pattern; a nested container is not.
- **Do** give every stage primitive a `canRender` predicate and fall back to the view that can draw anything. An empty stage reads as a broken tool.
- **Do** animate `transform` and `opacity` only.

### Don't:
- **Don't** declare a token outside `.tl` in `src/ui/ui.css`. `src/ui/app.css` consumes the system and defines nothing; any new layer does the same. A stylesheet that needs its own colour, type step, or radius is telling you either that the token belongs on `.tl` or that the design has drifted — resolve which, don't add a second source.
- **Don't** revive anything from `src/PixiStage.tsx` or `src/tracing.ts` without migrating it onto these tokens first. They are dead code, not a second system with rights; the `Inter` literal inside `PixiStage.tsx` is a leftover, not a precedent.
- **Don't** add a second accent hue, and don't spend green, amber, or red on anything but the four support verdicts.
- **Don't** nest a panel inside a panel, or wrap a table in a card — the `.tl-scroll` container is already the container.
- **Don't** reach for a shadow to express hierarchy. One ambient shadow exists in this system and it is already spent.
- **Don't** introduce gradients, glows, tilts, textures, or decorative illustration.
- **Don't** write a literal `font-size` or `border-radius` anywhere in the product. A tenth type step or a fifth radius is drift, not a decision — the only sanctioned literals are the 16px base on `.tl`, the three fluid `clamp()` roles, and `50%` on a circle. Inside an SVG `viewBox`, take a `--d-*` step.
- **Don't** use a `--d-*` step outside an SVG `viewBox`. The px scale is safe only because the viewBox transform is what sizes it; loose on the page it ignores the user's font-size preference.
- **Don't** key any CSS off `html[data-surface]`. No stylesheet reads it today and that is the point — it is a route-kind flag for scripts, not a theme switch, and the first rule that hangs an appearance on it is the first step back toward two worlds.
- **Don't** keep a rule that does nothing. Delete dead CSS rather than leaving it as a placeholder; the next reader cannot tell an inert rule from a load-bearing one.
- **Don't** duplicate the reduced-motion rule into a component or a route stylesheet. `html[data-still="true"] *` in `src/index.css` is the single source; a second copy is a second place to forget.
- **Don't** tint a shadow with literal black. Mix it from `ink` so it stays the page's own warm dark.
- **Don't** animate a layout property — `height`, `width`, `top`, `margin`. Use `transform`; the progress strip scales, it does not resize.
- **Don't** give a drawing primitive its own hue. Inside a stage or diagram, colour means *active*, not *which view this is*.
- **Don't** render a view that has nothing to draw. Fall back rather than showing an empty frame.
- **Don't** let a flex region omit `min-height: 0`. One missing declaration lets a long console push the whole workbench shell past the viewport.
- **Don't** place an uppercase tracked label above a headline as an editorial eyebrow. `tl-label` names a *region* — a panel bar, a diagram axis — and has no other use.
- **Don't** set prose in mono or a value in the proportional face. The face is the evidence claim.
- **Don't** animate longer than 200ms, add a second easing curve, or animate anything on scroll or on page load — and don't spend the 200ms step on anything but the state diagram's focus change.
- **Don't** add a fourth, lighter grey below `ink-3`. All three ink tiers clear AA on every ground; something that must recede further needs less prominence, not less contrast.
- **Don't** let a hairline be the only thing marking a control's edge or state. `line` (1.24:1) and `line-strong` (1.61:1) are both under the 3:1 non-text minimum and are recorded debt — pair them with a ground step or the accent until they are darkened.
- **Don't** resurrect the rejected cut-paper poster world in any form — its palette, its textures, its collage devices, or its type pairing. It was built, reviewed, and deleted.
