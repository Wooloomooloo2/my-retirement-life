# My Retirement Life — Website Content Brief

**Purpose:** a self-contained brief for building the marketing + docs website for **My Retirement Life (MRL)** — for the publisher's site and, in future, the Mac App Store, Microsoft Store, and Steam listings. Everything the site needs is here; you do **not** need the app's source or its ADRs. Distilled from the product as of 2026-06-22.

**Publisher & domain:** the app is published by **Garelochsoft** (`https://garelochsoft.com`). Garelochsoft is the umbrella brand for two sibling apps — **My Financial Life (MFL)** and **My Retirement Life (MRL)** — that share one visual identity. The existing Garelochsoft site was built first as the **MFL** product site with flat routes (`/buy`, `/download`, `/docs/...`). Now that a second product exists, the site should move to **product-scoped routes** (see §3) so MFL and MRL can each have their own marketing, docs, pricing, and store links without colliding.

**Status of the product:** the desktop app runs on **macOS** today (native window, signed-ready `.dmg`); **Windows** packaging is a near-term follow-on (the app code is already platform-agnostic). It is feature-rich and brand-finished. The website is the launch enabler: its Privacy + Terms URLs are a hard prerequisite for the storefront and for the App/Microsoft/Steam listings.

---

## 1. What the product is (positioning)

**My Retirement Life (MRL)** is a **local-first desktop retirement-planning app** for macOS (Windows coming). It takes your current financial reality — pensions, ISAs, savings, investments, property, income, and spending — and **projects it forward through retirement, drawdown, and tax**, year by year, to show whether your money lasts. All data is stored **on your own device**, never on a server.

**One-paragraph pitch:**
> Will your money last? My Retirement Life takes everything you have today — pensions, savings, investments, property and income — and projects it forward through retirement, year by year, accounting for drawdown order, tax, inflation and the big one-off events of life. See the year your plan comes under strain, test "what if I retire two years earlier," and know where you stand. It runs on your own Mac, keeps your data private, and you buy it once.

**Primary tagline:**
> Your money's future — projected, stress-tested, and private. On your own device.

**Sister product:** **My Financial Life (MFL)** tracks your money *today* — accounts, transactions, investments and budgets. The clean split: **MFL = your money today → MRL = your money's future.** They're sold as a bundle (see §9).

---

## 2. Audience

- People **5–20 years from retirement** (and the recently retired) who want a serious, private tool to answer "am I on track, and will it last?" — not a glossy fund-provider calculator that harvests their data to sell them products.
- DIY planners who manage their own pensions/ISAs/SIPPs and want to model **drawdown order and tax**, not just a single growth number.
- **Cross-border / multi-currency** households (e.g. UK + US pensions and accounts) — the app is jurisdiction-neutral and multi-currency throughout.
- People who've outgrown spreadsheets: they want the rigour (per-account drawdown, tax layers, Monte Carlo) without building and maintaining the formulas themselves.
- Technically comfortable but **not** developers; a careful, privacy-minded planner.

**Tone:** trustworthy, calm, precise, quietly premium. This is money and the future — reassuring and rigorous, never breathless or fear-mongering. Privacy and "not advice, but real numbers you control" are stated plainly.

---

## 3. Routes & site structure

MRL does **not** hardcode storefront/docs URLs in the app today (the only in-app outbound links are the **Garelochsoft** publisher logo → `https://garelochsoft.com` and a GitHub link). That gives the site freedom to choose a clean structure. **Recommendation: product-scope the routes** now that there are two products:

| Route | Purpose |
|---|---|
| `https://garelochsoft.com/` | Garelochsoft home — routes to both products |
| `https://garelochsoft.com/my-retirement-life` | MRL marketing home |
| `https://garelochsoft.com/my-retirement-life/buy` | MRL purchase / pricing |
| `https://garelochsoft.com/my-retirement-life/download` | macOS `.dmg` (Windows when ready) |
| `https://garelochsoft.com/my-retirement-life/docs/getting-started` | MRL onboarding docs |
| `https://garelochsoft.com/privacy`, `/terms`, `/support` | Shared, or product-scoped if legal prefers |

Whatever structure is chosen, **once MRL's in-app Help links are wired (a small future change), they must point at these exact URLs** — so agree them before the app's Help menu ships, and keep them stable thereafter. (MFL already hardcodes flat `/buy`, `/download`, `/docs/getting-started`; if both products live on one site, redirect or scope carefully so neither breaks.)

---

## 4. Site map & per-page content

A static site is plenty. Suggested pages (under the MRL scope):

1. **MRL Home** — hero (tagline + the projection/dashboard screenshot + Download/Buy CTAs), the local-first/privacy story, the "will it last?" value prop, a feature showcase (§6), the multi-currency + tax + Monte Carlo highlights, the MFL+MRL bundle teaser, footer with all links.
2. **Features** *(optional; can fold into Home)* — the full grouped feature list with screenshots.
3. **Download** — signed macOS `.dmg`, system requirements (macOS 11+; **Windows 10/11 — coming**), "what's new" link. Until builds are signed/notarised this can say "coming at launch."
4. **Pricing / Buy** — one-time price, what's included (everything), the 30-day free trial, the bundle option, the Buy button (Merchant-of-Record checkout — §7), refund policy link.
5. **Privacy** — see §8 (load-bearing; needs legal review).
6. **Terms / EULA** — includes the **"not financial or tax advice"** disclaimer (§8) — especially important for a projection tool.
7. **Support** — a monitored contact address + FAQ + docs link (doubles as the data-protection contact).
8. **Docs / Getting Started** — onboarding: install, set your profile (date of birth, target retirement age, life expectancy, base currency, jurisdiction), add accounts and pensions, set drawdown order and tax treatments, enter income and budget, add life events, read the projection. Markdown-driven.
9. **About** *(optional)* — the story, the privacy ethos, the two-app family.

---

## 5. The roadmap framing — don't overpromise

MRL **runs and sells now on macOS** with **manual data entry** plus **full backup/restore (JSON) and named scenarios**. Be precise about what's live vs. coming:

- ✅ **Live now:** the full deterministic projection, Monte Carlo simulation, per-account drawdown strategy, tax modelling, emergency fund, budgets with life-stage segments, physical assets + net worth, multi-currency with live FX, scenarios, and backup/restore — on **macOS**.
- 🟡 **Coming — Windows build.** The app is platform-agnostic; a Windows installer is a near-term follow-on. Say "Windows coming," don't imply it's downloadable yet.
- 🟡 **Coming — import from My Financial Life.** A user-initiated, file-based hand-off so your *today* picture in MFL seeds your *future* plan in MRL. Present the **combined story** and the bundle, but don't claim live two-way sync.
- 🟡 **Coming — store channels.** Mac App Store, Microsoft Store, and Steam are later channels; launch is **direct download** first. (Note: sandboxed store builds may constrain local-file backup/restore UX — flag for the store-listing work, don't surface to buyers.)

Stick to "projects and stress-tests your plan from the figures and assumptions you enter." Never imply guaranteed outcomes, live market data trading, or regulated advice.

---

## 6. Messaging kit — value props & features

**Three pillars (lead with these):**
1. **Will it last? — answered.** A year-by-year projection to life expectancy that models drawdown order, tax, inflation, contributions and one-off life events — then **flags the first year your plan comes under strain**, including money that's locked in accounts you can't access yet.
2. **Private by design.** Your entire financial picture lives on your device, full stop. No account to create, no cloud, no data harvesting, no product cross-sell.
3. **Buy it once.** One-time purchase, everything included, no subscription. Your version keeps working forever.

**Feature list (grouped — use for the showcase):**

- **Retirement projection** — a deterministic, year-by-year forecast of every account to life expectancy, with a clear **"on track / under strain"** verdict, the balance at retirement, and the year (if any) the money runs out. Includes a **"spending unfunded" signal** that catches the subtle trap of a plan that looks healthy on paper but can't actually fund spending because the money is locked in a pension you can't draw yet.
- **Monte Carlo simulation** — runs hundreds of market scenarios to show the **range** of outcomes (optimistic / median / pessimistic bands) and a success rate, so you see sequence-of-returns risk, not just a single smooth line. Conservative / Moderate / Aggressive volatility profiles.
- **Drawdown strategy** — a live sandbox to set the **order** accounts are drawn (Waterfall or Proportional), each account's **tax treatment**, and access rules (minimum age, mandatory/RMD-style withdrawals), then recompute instantly and see the effect on tax and longevity before you commit.
- **Tax modelling** — a jurisdiction-neutral, two-layer model: a residence-level personal allowance + marginal rate, plus per-account tax treatments (tax-free / ISA, tax-free-lump-sum/PCLS spreading, gains-only, and pre-tax pension withdrawals). A tax-shield summary shows your combined annual shield.
- **Accounts & assets** — cash (current, savings, ISA, fixed-term), investments (stocks & shares, pensions, workplace pensions, bonds, funds), and physical assets (property, vehicles, collectibles) with appreciation/depreciation and planned sales. A **net-worth-over-time** view stacks them all.
- **Income & contributions** — model salary, rental, state/workplace/private pensions and more, each with its own start/end year, growth, currency, and the account it's paid into. Workplace-pension contributions capture the **employee + employer split** and salary-sacrifice/payroll treatment.
- **Budgets that follow your life** — user-defined categories and **life-stage segments**: groceries that step up when the kids arrive and down when they leave, a mortgage that ends, travel that pauses for a few years. Real-terms and with-inflation views; category and per-line breakdowns.
- **Life events** — windfalls, inheritances, big one-off expenditures, property transactions and relocations, each landing in the right year and the right account.
- **Emergency fund** — designate a cash buffer (months-of-spending), and the engine fills it first in good years and draws it first in bad ones.
- **Multi-currency** — true multi-currency accounts, income and budget lines, with live daily FX rates (one outbound lookup, base-currency only) or manual rates. UK + US (and more) in one plan.
- **Scenarios & safety** — save, load and switch between named planning scenarios ("retire at 60 vs 63"), full one-click JSON backup/restore, and a year-by-year cashflow table you can export to CSV.

**Micro-copy / proof points:**
- "Not a single growth number — a year-by-year plan, stress-tested."
- "See the first year your plan comes under strain — before it does."
- "Model drawdown order and tax, not just 'assume 5% a year.'"
- "Your whole plan, on your device. No account. No cloud. No catch."
- "One price. Every feature. Yours to keep."

---

## 7. Pricing & licensing (mirror MFL — keep precise)

- **One-time perpetual purchase**, target **~£25–45 / $30–50** (owner sets the final number). **Everything is included** — projection, Monte Carlo, drawdown, tax, multi-currency, scenarios. No subscription, no tiers, no add-ons.
- **Major versions (2.0) are a separate paid upgrade**; a 1.x licence works on every 1.x release forever.
- **Free trial:** a **30-day, full-feature** trial; buying a key removes the gentle expiry nag. The site just needs to say "try free for 30 days."
- **Licence delivery:** an offline signed licence key emailed after purchase; the buyer pastes it into the app. The Buy flow must deliver the key and offer a "retrieve my key / re-download" path.
- **Payments:** use a **Merchant-of-Record** (Paddle / Lemon Squeezy / FastSpring) so VAT/sales-tax is handled — the Buy button is their hosted checkout, and they email the key. (Avoid Stripe-alone for the storefront — it leaves you holding cross-border tax.)
- **Store channels:** Mac App Store / Microsoft Store / Steam each take their own cut and have their own licensing — these are **separate SKUs/listings** from the direct-download MoR sale; reconcile the pricing story when those channels go live.
- **Bundle SKU:** an MFL + MRL combined price alongside standalone MRL (both one-time, everything-included). Define the bundle discount when both are sellable.

---

## 8. Privacy & legal (load-bearing — needs a solicitor/template review)

Stable Privacy + Terms URLs are a launch prerequisite (the MoR checkout and every store listing require them). Treat as launch-critical.

**Privacy Policy must cover:**
- The headline: **all financial and personal data is stored locally on the user's device** — a genuine selling point, stated plainly. There is no user account and no server-side storage.
- What the **website** itself collects (analytics/cookies, if any — keep minimal and privacy-friendly).
- The app's only outbound network call: **live foreign-exchange rates** (currency codes only — no financial data — from a public FX endpoint). Name the provider.
- The **MFL → MRL import** data flow (user-initiated, file-based) once it ships: what crosses, and that the user initiates it. With the bundle, decide one combined policy vs. two linked ones.
- A **data-protection contact email** (can be the support address).
- UK GDPR + EU GDPR alignment; retention; user rights.

**Terms / EULA must cover:**
- Licence grant (one-time, perpetual, per §7).
- **"Not financial, investment, tax, or pension advice"** — this is the load-bearing disclaimer for a projection tool. Projections are **illustrations based on the user's own inputs and assumptions**, not predictions or guarantees; the user is responsible for their decisions and should consult a regulated adviser. State this plainly on the site (footer + a line near the projection screenshots), not only in the EULA.
- Disclaimers, liability limits, refund policy.

**Jurisdiction:** working assumption is a **UK Ltd** company (owner UK-resident, selling UK/EU) — confirm with an accountant; this affects the legal entity named in the docs.

> ⚠️ Use real legal review for Privacy + Terms — it's financial-planning software and these are regulator-facing, store-facing URLs. The website author should leave clearly-marked placeholders, not invent legal text. The "not advice" framing in particular should be reviewed.

---

## 9. The MFL + MRL bundle story

- **My Financial Life (MFL)** is the sister app: it tracks your money **today** — accounts, transactions, investments, budgets, net worth. **MRL** takes that reality and **projects it forward** through retirement, drawdown and tax. Messaging split: **MFL = today → MRL = the future.**
- Marketed as a **combined offering / bundle** (one-time, everything-included, with a bundle discount vs. buying separately).
- The technical integration (a user-initiated, file-based **import from MFL into MRL**) is a **fast-follow** — at launch the site tells the *combined story* and offers the bundle, but should not claim live two-way sync.
- **Fallback:** if only one app is sellable at a given moment, ship its site standalone with an "works alongside [the other] (coming)" section, and switch the bundle on when both ship.

---

## 10. Brand kit

**Logos / icons (assets live in the MRL app repo at `src/static/img/`):**
- **My Retirement Life** product icon — a hexagonal badge: a gold "R" with a **sunset and a sailboat** on a deep petrol-teal field. Master/derived files: `mrl-icon.png` (512), `favicon.png` (64), `apple-touch-icon.png` (180). Use for the MRL product logo/favicon. *(A high-res `.icns`/`.ico` set for store listings is a small follow-on; ask if needed.)*
- **Garelochsoft** company logo — a teal + gold badge (loch/mountain landscape with a golden path to an anchor, "GARELOCHSOFT" in gold): `garelochsoft.png`. Use for company footer / about / publisher attribution.
- **My Financial Life** badge — the matching hexagon with a gold "M", a coin and an up-arrow — for the bundle section.

The **teal + gold palette is the company-wide brand** shared by Garelochsoft, MFL and MRL, so the family feels like one. **MRL's signature accent is the sunset orange** — use it to distinguish MRL surfaces (hero accents, the "future" half of the bundle graphic) the way MFL leans on plain teal.

**Colour palette** (matches the shared family tokens; align the site so app and site feel like one product):

| Role | Light | Dark | Notes |
|---|---|---|---|
| Brand accent (teal) | `#1f6e78` | `#39a0aa` | primary buttons, links, highlights |
| Accent hover | `#185860` | `#2f8893` | |
| Brand gold | `#c9a23a` | `#dcbb55` | sparingly — accents/rules, **not** body text on white |
| **MRL sunset (signature)** | `#e08a3c` | `#e8a25c` | MRL-only accent — hero highlights, the "future" motif |
| Canvas / background | `#f8fafc` | `#0f172a` | |
| Surface / cards | `#ffffff` | `#1e293b` | |
| Text | `#0f172a` | `#f1f5f9` | |
| Muted text | `#64748b` | `#94a3b8` | |
| Border | `#e2e8f0` | `#334155` | |
| Positive (on track) | `#16a34a` | `#22c55e` | green = plan healthy |
| Negative (shortfall) | `#dc2626` | `#f87171` | red = runs out / unfunded |

**Typography feel:** clean, modern sans-serif (the app uses the system UI font — Inter / system-ui is a good web match). Calm, generous spacing, big legible numbers. Serious finance product — avoid playful display fonts.

**Voice:** plain, confident, specific. Short sentences. Lead with the benefit ("will it last?"), back it with the concrete feature (per-account drawdown, tax layers, Monte Carlo). Reassuring, never alarmist; rigorous, never jargon-heavy.

---

## 11. Screenshots to capture (from the polished app)

A clean, light-theme set has already been generated from the brand-finished build using the public demo dataset **"Alex Sterling"** (a fictional 54-year-old UK planner retiring at 62 — a healthy, on-track plan). The files are in the app repo at **`screenshots/`** (high-res, 2×):

| File | Page | Why it's a good shot |
|---|---|---|
| `01-dashboard.png` | Dashboard | **Hero.** Net worth now/at-retirement/at-life-expectancy + the net-worth-over-time chart. |
| `02-projection.png` | Projection | "On track" verdict, Monte Carlo success rate, the stacked projection chart + the P10/P50/P90 band. |
| `03-drawdown-strategy.png` | Drawdown strategy | Accounts in draw order with tax-treatment + access-age chips, the withdrawals chart, tax/longevity outlook. |
| `04-accounts.png` | Accounts | Cash + investments + physical assets, FX-aware totals. |
| `05-income.png` | Income | Salary, rental, state pension with routing and growth. |
| `06-budget.png` | Budget | The category chart **stepping down at retirement**, multi-stage lines, contributions. |
| `07-life-events.png` | Life events | Kitchen reno + inheritance on the timeline. |
| `08-profile.png` | Profile | The planning profile (DOB, retirement age, life expectancy). |
| `09-settings.png` | Settings | Backup/restore + the About card with publisher attribution. |

For variety, a **dark-mode** set and a cropped **"spending unfunded" red-state** shot (to illustrate the strain-detection story) can be generated on request. The website author should treat screenshots as supplied assets and **not** fabricate UI that differs from the real app.

---

## 12. Tech & hosting recommendation

- **Static site** — no backend. **Astro** (great for marketing + markdown docs, and matches the existing Garelochsoft/MFL site stack), Eleventy, or Hugo; markdown for `/docs`.
- **Host:** Netlify / Cloudflare Pages with the `garelochsoft.com` domain and auto-deploy on push. Reuse the existing site repo/host; add the MRL-scoped routes.
- **Commerce:** embed the Merchant-of-Record checkout (Paddle/Lemon Squeezy/FastSpring) on the MRL `/buy` route — hosted checkout or a small JS overlay; no server code. Store-channel listings (App Store/Microsoft/Steam) are managed in their own consoles.
- **Analytics:** privacy-friendly (Plausible/Fathom/none) to match the product ethos — and disclose in `/privacy`.

---

## 13. SEO / meta basics

- Title/description per page; OpenGraph + Twitter cards using the MRL icon + the dashboard/projection hero screenshot.
- Keywords lean: "retirement planning app," "private pension drawdown calculator," "will my money last retirement," "Monte Carlo retirement simulation," "local-first retirement planner Mac," "drawdown and tax projection."
- Favicon from `src/static/img/favicon.png`. Sitemap + robots.txt. Distinct MRL and MFL meta so the two products rank independently.

---

## 14. What the owner still must supply (not the website author's call)

- The **final price** and the **bundle discount**.
- Confirmation of the **route structure** (product-scoped vs. flat) and DNS already pointed at the host (✅ `garelochsoft.com`).
- The **Merchant-of-Record account** + checkout link/keys for MRL `/buy`; and decisions on **store channels** (App Store / Microsoft Store / Steam) and their separate listings.
- **Legal-reviewed** Privacy + Terms text (including the "not advice" disclaimer); the site ships placeholders until then. Legal entity = **Garelochsoft** (confirm registered form — UK Ltd assumed).
- The **contact / support / help email** (also the data-protection contact).
- Whether **MFL** is sellable alongside MRL at launch (drives bundle-vs-standalone framing).
- Sign-off on the **macOS-only at launch** message and the **Windows "coming"** wording (and timing for the store-channel listings).

---

*End of brief. Further detail — exact feature wording, more screenshots, a copy pass, or a dark-mode/red-state image set — can be produced from the app repo's `CLAUDE_CONTEXT.md` and the polished build, but this document is intended to be sufficient on its own.*
