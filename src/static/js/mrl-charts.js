/**
 * mrl-charts.js — shared chart palette and helpers (ADR-022 commit 3).
 *
 * Every chart in the app pulls its colours and its retirement-★ marker from
 * here. Before this module the palettes were copy-pasted verbatim into three
 * templates and the ★ marker was implemented five separate times — which is
 * exactly why the session-15 "disappearing star" bug needed five separate
 * fixes. One definition, one fix.
 *
 * Colours are read from CSS custom properties (see src/styles/app.css), not
 * hardcoded here, so a theme change re-tints the charts with no JS edit.
 */
(function (window) {
    'use strict';

    function cssVar(name, fallback) {
        const v = getComputedStyle(document.documentElement)
            .getPropertyValue(name).trim();
        return v || fallback;
    }

    /** Read the palette from CSS. Called lazily so the stylesheet is parsed. */
    function readPalette() {
        return {
            cash: [
                cssVar('--mrl-cash-1', '#2563EB'),
                cssVar('--mrl-cash-2', '#3B82F6'),
                cssVar('--mrl-cash-3', '#60A5FA'),
                cssVar('--mrl-cash-4', '#93C5FD'),
            ],
            invest: [
                cssVar('--mrl-invest-1', '#059669'),
                cssVar('--mrl-invest-2', '#10B981'),
                cssVar('--mrl-invest-3', '#34D399'),
                cssVar('--mrl-invest-4', '#6EE7B7'),
                cssVar('--mrl-invest-5', '#0D9488'),
                cssVar('--mrl-invest-6', '#0F766E'),
            ],
            asset: [
                cssVar('--mrl-asset-1', '#D97706'),
                cssVar('--mrl-asset-2', '#F59E0B'),
                cssVar('--mrl-asset-3', '#FBBF24'),
                cssVar('--mrl-asset-4', '#FCD34D'),
            ],
        };
    }

    function readColors() {
        return {
            accent:       cssVar('--mrl-accent', '#E08A3C'),
            contribution: cssVar('--mrl-contribution', '#1F6E78'),
            withdrawal:   cssVar('--mrl-withdrawal', '#D97706'),
            tax:          cssVar('--mrl-tax', '#DC2626'),
            growth:       cssVar('--mrl-growth', '#16A34A'),
            // Projection overview cashflow series.
            mandatory:     cssVar('--mrl-spend-mandatory', '#EF4444'),
            discretionary: cssVar('--mrl-spend-discretionary', '#F59E0B'),
            loan:          cssVar('--mrl-loan', '#3B82F6'),
            eventCost:     cssVar('--mrl-event-cost', '#A855F7'),
            eventReceipt:  cssVar('--mrl-event-receipt', '#14B8A6'),
            income:        cssVar('--mrl-income', '#22C55E'),
        };
    }

    /**
     * Append an alpha channel to a #RRGGBB colour: alpha(c, 0.7) -> '#RRGGBBB3'.
     * Chart.js fills were written as rgba() literals; this keeps them
     * token-driven (and therefore themeable) without hand-computed hex suffixes.
     */
    function alpha(hex, a) {
        const c = String(hex).trim().slice(0, 7);   // drop any existing alpha
        const byte = Math.round(Math.max(0, Math.min(1, a)) * 255);
        return c + byte.toString(16).padStart(2, '0').toUpperCase();
    }

    let _palette = null;
    let _colors = null;

    const MRL = {
        get palette() {
            if (!_palette) _palette = readPalette();
            return _palette;
        },
        get color() {
            if (!_colors) _colors = readColors();
            return _colors;
        },

        alpha: alpha,

        /**
         * Colour for an unbounded, user-created series (a budget category or a
         * budget line) by its POSITION in the group list. Cycles once it runs
         * out — eight distinguishable colours is far past the point where a
         * stacked chart is readable anyway.
         *
         * `role` pins the two system groups so they never take a category's
         * colour: contributions are money coming IN (brand teal, matching the
         * investment-detail chart), and "Uncategorised" is deliberately grey so
         * it recedes rather than competing.
         */
        categorical(index, role) {
            if (role === 'contributions') return MRL.color.contribution;
            if (role === 'uncategorised') return cssVar('--mrl-neutral', '#9CA3AF');
            const ramp = [
                cssVar('--mrl-cat-1', '#4F7CAC'), cssVar('--mrl-cat-2', '#C9A23A'),
                cssVar('--mrl-cat-3', '#B4656F'), cssVar('--mrl-cat-4', '#5B8C5A'),
                cssVar('--mrl-cat-5', '#8B6BB1'), cssVar('--mrl-cat-6', '#9C6B4F'),
                cssVar('--mrl-cat-7', '#6B7A8F'), cssVar('--mrl-cat-8', '#A8577E'),
            ];
            return ramp[index % ramp.length];
        },

        /**
         * Chart chrome. Gridlines and axis labels are painted on the canvas, so
         * they cannot inherit `text-base-content` — without these they'd stay
         * black-on-black in dark mode.
         */
        get grid() {
            return cssVar('--mrl-grid', 'rgba(0,0,0,0.04)');
        },
        /** Tick + legend text. Must hold contrast — see the CSS comment. */
        get chartLabel() {
            return cssVar('--mrl-chart-label', '#666666');
        },
        /** Decorative axis captions, deliberately faint. */
        get chartText() {
            return cssVar('--mrl-chart-title', 'rgba(0,0,0,0.4)');
        },

        /** Re-read the palette after a theme change (commit 5 / dark mode). */
        refresh() {
            _palette = null;
            _colors = null;
            MRL.applyChartDefaults();
        },

        /** Chart.js's own defaults (tick labels, legend text) follow the theme. */
        applyChartDefaults() {
            if (typeof Chart === 'undefined') return;
            Chart.defaults.color = MRL.chartLabel;
            Chart.defaults.borderColor = MRL.grid;
        },

        /**
         * Per-point config that renders a ★ on the retirement year of a LINE
         * series, and nothing on any other year.
         *
         * Why not an X-axis tick label: Chart.js `autoSkip` thins ticks by
         * POSITION, not by content, so a ★ appended to the retirement-year tick
         * vanishes whenever that tick doesn't survive the cull (session-15 bug).
         * A real data point can't be skipped.
         *
         * `hoverBase` is the hover radius for non-retirement years — 0 for a
         * marker-only series, 4 where the line already showed hover points.
         */
        starPoints(years, retirementYear, opts) {
            const o = opts || {};
            const hoverBase = o.hoverBase || 0;
            const c = o.color || MRL.color.accent;
            return {
                pointRadius:          years.map(y => (y === retirementYear ? 7 : 0)),
                pointHoverRadius:     years.map(y => (y === retirementYear ? 9 : hoverBase)),
                pointStyle:           years.map(y => (y === retirementYear ? 'star' : 'circle')),
                pointBackgroundColor: c,
                pointBorderColor:     c,
                pointBorderWidth:     years.map(y => (y === retirementYear ? 2 : 1)),
            };
        },

        /**
         * A transparent dataset whose only visible mark is the retirement ★,
         * sitting at the top of a STACKED chart's stack for that year.
         *
         * Stacked charts can't use starPoints() on a real series: the star would
         * sit at that series' segment, not at the stack total. This rides in its
         * own stack group ('_marker') so it adds nothing to the totals, and is
         * filtered out of tooltips and legends by the callers.
         */
        markerDataset(years, retirementYear, totals, opts) {
            const o = opts || {};
            return Object.assign({
                label:       o.label || 'Retirement',
                data:        totals,
                stack:       o.stack || '_marker',
                fill:        false,
                borderColor: 'transparent',
                borderWidth: 0,
                // The budget chart curves less than the balance charts.
                tension:     o.tension === undefined ? 0.3 : o.tension,
                order:       -1,
            }, MRL.starPoints(years, retirementYear, { hoverBase: 0 }), {
                pointBorderWidth: 2,
            });
        },
    };

    window.MRL = MRL;

    // Synchronous, and it must stay that way: the page templates build their
    // charts in inline <script> blocks that run BEFORE DOMContentLoaded, and
    // Chart.defaults has to be set before a chart is constructed. This is safe
    // because base.html loads this file AFTER app.css — a script following a
    // stylesheet link waits for it, so the tokens are parsed by now.
    MRL.applyChartDefaults();
})(window);
