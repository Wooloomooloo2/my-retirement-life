# ADR-022: Frontend build step and design system

**Date:** 2026-07-12
**Status:** Accepted
**Amends:** [ADR-003](ADR-003-frontend-stack.md) (frontend stack)

---

## Context

ADR-003 chose HTMX + Tailwind + DaisyUI and deliberately deferred the CSS build step:

> *"Tailwind via CDN includes the full utility class set; for production optimisation, a build step with PurgeCSS would reduce file size — deferred to a future release."*

That deferral is now the root of most of the front end's remaining rough edges. A design review of the 16 templates (~7,100 lines) found the shell, the onboarding flow, the scenario save-state indicator, and the confidence banner to be sound and worth preserving. The problems are all in the **presentation layer beneath** them:

**1. The app ships a development-mode CSS pipeline.** `base.html` loads `tailwind.play.min.js` (407 KB) — the Tailwind **Play CDN**, which compiles CSS *in the browser at runtime* on every page load. The bundle warns about itself on the console (*"should not be used in production. To use Tailwind CSS in production, install it as a PostCSS plugin…"*) — installing it as a build-time plugin is exactly what this ADR does, so the warning and its cause are removed together rather than suppressed. Beside it sits `daisyui.full.min.css` at **2.9 MB**, containing all **32** DaisyUI themes when the app uses exactly one. Both are vendored locally, so there is no network fetch — the cost is a ~3.3 MB parse plus a runtime JIT pass before first styled paint. The user sees unstyled HTML, then a reflow. In a pywebview desktop window that flash is the difference between "a web page in a window" and "an application".

**2. The app does not look like its own brand.** `data-theme="light"` yields DaisyUI's stock indigo-violet (`#570df8`) as `primary` — so every button, nav highlight and avatar is default DaisyUI. `docs/MRL_WEBSITE_BRIEF.md` positions MRL around a **sunset-orange** accent in a teal/gold family, and the hex logo is gold. The product reads as templated because it is.

**3. Chart colour is ad-hoc.** 18 distinct hardcoded hex values across 5 chart templates, including `#4F46E5`, `#6366F1`, `#534AB7` and `#2563EB` — four near-identical indigos that are accidents, not a scale. There is no shared palette, so a "cash" series is not reliably the same blue on the Dashboard as on Projection, and no colour is theme-derived.

**4. Chart setup is duplicated five times.** Each large page carries its own inline Chart.js `<script>`. The session-15 disappearing-★ bug is the proof: one conceptual defect that had to be fixed in five places, in five different shapes.

**5. Figures do not align.** Every money value is `{:,.0f}` in a proportional font, so digits do not line up in the Projection and Budget tables. Currency formatting is also re-implemented inline in every template, including a hand-rolled negative branch using U+2212 in the dashboard hero — so nothing guarantees `-£5` and `−£5` don't both appear.

**6. No dark mode.** `data-theme` is hardcoded to `light`, yet the app already *ships* DaisyUI's dark CSS in the 2.9 MB bundle.

**7. Minor layout hygiene.** No `max-w` on the content column (cards stretch on a wide monitor); `grid-cols-3` has no responsive breakpoint (cards squash rather than reflow in a narrow window); and three permanently-greyed "Coming soon" nav items (Housing, Health, Lifestyle) occupy the sidebar on every page.

Items 2–6 are all *blocked on, or made trivial by,* item 1. A build step is the enabler, not merely an optimisation.

### The tension with ADR-003

ADR-003's headline benefit was **"No Node.js, npm, or JavaScript build toolchain required."** Any real Tailwind build reintroduces one. This is the central trade-off of this ADR and is faced directly below.

### Options considered

| Option | Notes |
|--------|-------|
| **Do nothing** | Keeps ADR-003's zero-toolchain purity. But the FOUC, the 3.3 MB parse, the stock theme, and the un-themeable charts all persist, and items 2–6 stay blocked. Rejected — the deferral has stopped being free. |
| **Strip the 31 unused themes from `daisyui.full.min.css` by hand/script** | Cheap; cuts ~2.9 MB to a few hundred KB. But the Play CDN **still JITs at runtime**, so the flash — the actual user-visible defect — remains. Rejected as a half-measure that fixes bytes, not the problem. |
| **Tailwind standalone CLI binary** | The official single-file executable needs no Node *runtime*. But it cannot load third-party PostCSS plugins, and DaisyUI (v4) is exactly that — so this means dropping DaisyUI and hand-writing the component layer. Rejected: DaisyUI is doing real work here. |
| **Migrate to Tailwind 4 + DaisyUI 5** | DaisyUI 5 is distributed as plain CSS, which loosens the toolchain requirement. But it is a major version bump of both libraries across all 16 templates — a large, high-regression change bundled into what should be a plumbing fix. Rejected *for now*; revisit once this ADR has landed. |
| **Node + npm at dev time only; commit the built CSS** | ✅ **Chosen.** Reintroduces a toolchain, but only for the person editing templates — see below. |

---

## Decision

**Adopt a dev-time-only Tailwind/DaisyUI build, then use the theme layer it unlocks to unify colour, typography and charts.**

### On the toolchain trade-off

Node/npm becomes a **development dependency, not a runtime or packaging one**:

- The build's output (`src/static/css/app.css`) is **committed to the repo**. Anyone who clones and runs `python main.py` needs no Node, no npm, no `node_modules`.
- **ADR-002 (packaging) is untouched** — PyInstaller bundles a static `.css` exactly as it bundles today's vendored `.css`. No JS bundle enters the packaging story.
- **ADR-004 (portability) is untouched** — the artifact is platform-neutral text.
- Node is needed only to *regenerate* the CSS after a template gains a new utility class, and the person doing that is Claude, not Mark.

So ADR-003's real goal — *the user and the packaging pipeline never meet a JS toolchain* — survives intact. What changes is that the **developer** now has one, which ADR-003 itself anticipated as the eventual price of production optimisation.

### Regression posture

Colour, typography and chart rendering touch every page, so the work is sequenced so that **each commit has an explicit correctness oracle**, and the riskiest change is the one with the *strictest* oracle:

- **Commit 1 must produce pixel-identical output.** Any visual difference is a bug, not a feature. That is the strongest gate available, and it is applied to the change most likely to break things (class purging).
- **Every later commit is developed against the real build pipeline**, so no work is done on the Play CDN only to discover afterwards that the build purges it.
- **Colour is centralised (commit 3) before it is changed (commits 4–5)**, so re-theming is a token edit, not a five-template sweep.

**Verification harness** (reused from session 12, already proven on this codebase): bootstrap an isolated store under a temp `DATA_DIR`, restore `sample-data/demo-backup-alex-sterling.json`, serve `uvicorn` on a non-default port, and drive **headless Edge** (`--headless=new --screenshot --window-size=1440,H --force-device-scale-factor=2`) across the 9 routes captured in `MRL_screenshots/`. Capture before, capture after, compare. This never touches the live data graph.

---

## The five commits

Each is independently shippable, independently revertable, and leaves the app in a good state. Stopping after any one of them is a valid outcome.

### Commit 1 — Real CSS build, zero visual change

*The enabler. Highest regression risk, strictest gate.*

- Add `package.json` (devDependencies: `tailwindcss` ^3, `daisyui` ^4) and `tailwind.config.js`.
- Content glob: `src/templates/**/*.html` — this covers both markup **and** the inline `<script>` blocks, which is where every JS-built class string lives.
- Configure **only the `light` theme**, so the generated CSS is a strict subset of what renders today.
- Build to `src/static/css/app.css`; wire it into `base.html`; delete `tailwind.play.min.js` and `daisyui.full.min.css`.
- Add `tools/build_css.*` (a thin wrapper over `npx tailwindcss -i … -o …`) and document it in the README.

**Purge risk — assessed, not assumed.** A survey of all 16 templates found **no class name is constructed dynamically**: every JS assignment is a complete literal (`row.className = 'segment-row border border-base-200 rounded-md p-2 mb-2'`), and **no class names are built in Python at all**. Even the one concatenation (`drawdown_strategy.html:410`) draws from a literal map defined in the same file. So the content glob sees everything and the safelist should be **empty** — but this must be *confirmed by the screenshot diff*, not trusted.

**Gate:** all routes pixel-identical to the pre-commit capture. Expected: ~3.3 MB → ~30–50 KB, and the flash gone.
**Rollback:** revert one commit; the vendored CDN files return.

> **Implementation notes (landed 2026-07-12).** Built and verified against **11** routes (the 9 in `MRL_screenshots/` plus `/scenarios` and `/import`). Pinned to the exact versions the CDN was serving — **Tailwind 3.4.17, DaisyUI 4.12.24** — so the output reproduces current rendering rather than silently upgrading.
>
> - **Actual size: 3.3 MB → 103 KB** (not the 30–50 KB estimated above — DaisyUI emits its component layer more broadly than pure utility purging implies). Still a 97% reduction, and the runtime compile is gone.
> - **The purge-risk assessment held.** The safelist is empty and nothing was lost, exactly as the dynamic-class survey predicted.
> - **The real regression was cascade order, which the survey did not predict.** The Play CDN injected its `<style>` at runtime, landing at the *end* of `<head>` — so Tailwind's utilities had always won same-specificity ties against `tabler-icons.min.css`. A `<link>` in the natural place (first) silently handed those ties to Tabler, whose `line-height: 1` on `.ti` then beat `text-base`'s `1.5rem`, changing every icon's box height and shifting all sidebar rows by an accumulating offset. Caught only by the pixel diff. **`app.css` must remain the last stylesheet in `<head>`** — commented in `base.html` accordingly. *This is the vindication of the pixel-identical gate: the defect was invisible in review and would have shipped.*
> - **Harness noise floor:** `/projection` shows a ~0.38% diff on **any** two runs, including a control capture of identical code, because the Monte Carlo band is drawn from unseeded sampling. Confirmed as nondeterminism, not a regression — the diff is confined to the P10/P50/P90 lines. Every other route is byte-identical, zero differing pixels.
> - `tools/vendor_assets.py` no longer downloads Tailwind/DaisyUI — left as-is, the next run would have resurrected the Play CDN.
> - Packaging needed no change: `MyRetirementLife.spec` already bundles all of `src/static`, so `app.css` is picked up as ADR-002 predicted.

### Commit 2 — Presentation primitives

*Small, deliberate, no shared abstractions required. Safe to land while charts are still untouched.*

- A single Jinja `money` filter (plus `money_signed` for the negative case), replacing the inline `base_currency_symbol() ~ "{:,.0f}".format(…)` pattern everywhere — one place to change, one canonical minus sign.
- `tabular-nums` on every figure and table cell. Cheapest large win in the review: digits align, columns read as a financial application rather than a web form.
- Content column gets `max-w-7xl mx-auto`; `grid-cols-3` gains responsive breakpoints.
- Retire the three dead "Coming soon" nav items from the sidebar.

**Gate:** every rendered figure is numerically identical pre/post (the filter must not change rounding or sign); layout diffs are intentional and reviewed.

### Commit 3 — Shared chart module and unified palette

*Centralises colour so commits 4 and 5 are token edits.*

- New `src/static/js/mrl-charts.js`: the categorical palette, semantic series colours (cash / investment / assets / tax), base Chart.js options, the tooltip formatter, and the **retirement-★ marker helper**.
- Refactor the 5 chart templates onto it. The four accidental indigos collapse to one deliberate scale — this is a *visible, intended* colour change.
- Colours are read from CSS custom properties, not hardcoded, so they follow the theme.

**Gate:** all 5 charts render; the ★ marker still appears on every one (the session-15 fix must survive the refactor — this is the specific regression to watch); stacked totals still equal the engine figures. Add the new `.js` to the commit-1 content glob.

### Commit 4 — MRL brand theme

*Now a token change, because of 1 and 3.*

- Define a custom `mrl` DaisyUI theme in `tailwind.config.js` — sunset-orange primary, gold accent, per `docs/MRL_WEBSITE_BRIEF.md`.
- Flip `data-theme="light"` → `data-theme="mrl"`.

That is the whole commit. Every button, nav highlight, avatar and chart series re-tints from the token definition. The largest visual change in the ADR and the smallest diff.

**Gate:** contrast check on the new primary (buttons, the `text-primary` checklist state, the confidence banner tints must all stay legible).
**Rollback:** one file.

### Commit 5 — Dark mode

*Last, because it is the honest test of whether 1, 3 and 4 actually decoupled colour from markup.*

- Add an `mrl-dark` theme; a header toggle persisting to `localStorage`; respect `prefers-color-scheme` on first run.
- Charts retheme via the CSS custom properties introduced in commit 3.

If this commit is easy, the preceding ones were done correctly. If it requires touching chart templates again, commit 3 left colour hardcoded somewhere — and that is worth knowing.

**Gate:** all 9 routes legible in both themes; charts, the confidence banner and the unfunded-row `bg-error/10` highlight all still read correctly on a dark background. Also unblocks the dark-mode screenshots already noted in the CLAUDE_CONTEXT backlog.

> **Implementation notes (landed 2026-07-12).** The decoupling held: dark mode is a `[data-theme='mrl-dark']` token block plus a second DaisyUI theme, and **no chart template was edited for the theme itself**. Brand and dark values both come from `docs/MRL_WEBSITE_BRIEF.md`, which already specified a full dark column — so neither theme is a guess.
>
> But the commit found two things the earlier ones got wrong, which is exactly what it was sequenced to do:
> - **Colour that isn't in the palette isn't themeable.** Commit 3's sweep matched quoted hex, so it missed colours written as `rgba()` — a whole second layer, including the entire Projection cashflow series (mandatory/discretionary/loans/life events/income/receipts) and every gridline and axis label. Chart chrome is painted to `<canvas>` and cannot inherit `text-base-content`, so without its own tokens it stays black-on-black in dark mode. Fixed in commits 4–5; the only literals left in JS are neutral `rgba(0,0,0,…)` tooltips.
> - **A contrast regression, caught by the pixel diff.** `Chart.defaults.color` drives tick *and legend* text (Chart.js default `#666`), but it was pointed at the faint axis-*title* token (`rgba(0,0,0,0.4)` ≈ `#999` on white) — dropping every chart legend to roughly 2.8:1. Two different jobs had been given one token. Split into `--mrl-chart-label` (must hold contrast) and `--mrl-chart-title` (deliberately faint).
>
> **Script order in `<head>` is load-bearing** and now carries a comment: the theme is applied by an inline, synchronous, pre-paint script (anything deferred would let light paint first and flip — reintroducing the very flash commit 1 removed), and `mrl-charts.js` must load **after** `app.css`, because it reads the palette via `getComputedStyle` and a script following a stylesheet link waits for it. Loaded earlier, every chart silently gets the fallback colours.
>
> **The toggle reloads the page.** CSS re-tints instantly, but charts are painted to canvas and hold the colours they were built with. Rebuilding them in place would need a re-init hook in all five chart templates; a reload is one line and always correct. The cost is losing un-submitted form input — which is why the control is a small header icon, not a button next to Save.
>
> **Harness note:** the `/projection` diff is normally ~0.3% (the unseeded Monte Carlo band), but occasionally jumps to ~5% — when the random band shifts the y-axis maximum, the tick-label width changes and the whole plot area moves. Confirmed benign by a control capture of identical code. Any future pixel gate on this page needs that in mind, or it should seed the simulation.

---

## Consequences

**Positive**
- First styled paint is immediate; the FOUC is gone. ~3.3 MB of runtime-compiled CSS/JS becomes a ~30–50 KB static file.
- The product looks like MRL rather than like DaisyUI's default theme.
- Colour lives in one place, so theming, dark mode, and any future accessibility work are token edits rather than template sweeps.
- Chart behaviour is defined once — the next star-marker-class bug is one fix, not five.
- Dark mode ships from CSS the app was already downloading.

**Trade-offs accepted**
- **A dev-time Node/npm toolchain**, against ADR-003's explicit goal. Mitigated by committing the artifact: the app, the user, and PyInstaller never see Node. This is the cost ADR-003 itself forecast.
- Contributors editing templates must rebuild the CSS after adding a *new* utility class. A stale `app.css` shows up as an unstyled element — cheap to spot, but it is a new failure mode that did not exist with the Play CDN.
- Commits 3 and 4 change chart and UI colours **on purpose**. Existing screenshots in `MRL_screenshots/` and any website assets derived from them will need recapturing.

**Explicitly out of scope**
- The Tailwind 4 / DaisyUI 5 migration (revisit after this lands).
- Any change to the projection engine, the ontology, routes, or persistence. **This ADR is presentation-layer only** — no `.ttl` change, no `tools/reload_ontology.py` run, no export-schema bump.
- The dashboard redesign and physical-asset/sell-asset work, which are tracked separately.
