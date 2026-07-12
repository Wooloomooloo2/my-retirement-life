/**
 * Tailwind + DaisyUI build config (ADR-022, commit 1).
 *
 * Replaces the Tailwind Play CDN, which compiled CSS in the browser on every
 * page load. Dev-time only: the output (src/static/css/app.css) is committed,
 * so running or packaging the app never needs Node.
 *
 * Content glob note: the templates hold BOTH markup and the inline <script>
 * blocks, and every class name in those scripts is a complete literal (e.g.
 * `row.className = 'btn btn-xs btn-ghost'`). No class name is assembled from
 * fragments in JS, and none are built in Python. The scanner therefore sees
 * every class the app can use, and no safelist is required.
 */
module.exports = {
  content: [
    './src/templates/**/*.html',
    './src/static/js/**/*.js',
  ],
  theme: {
    extend: {},
  },
  plugins: [require('daisyui')],
  daisyui: {
    /*
     * The MRL brand theme (ADR-022 commit 4).
     *
     * Until now the app rendered on DaisyUI's stock `light` theme, whose primary
     * is an indigo-violet (#570df8) that appears nowhere in MRL's branding — so
     * every button, nav highlight and avatar was a DaisyUI default. These tokens
     * come from docs/MRL_WEBSITE_BRIEF.md, so the app and the marketing site are
     * one product:
     *
     *   primary   teal    #1f6e78  the company-wide Garelochsoft brand accent
     *   secondary gold    #c9a23a  used sparingly — rules and accents
     *   accent    sunset  #e08a3c  MRL's SIGNATURE colour (MFL leans on plain teal)
     *
     * Semantic colours are the brief's own: positive #16a34a, negative #dc2626.
     */
    themes: [
      {
        mrl: {
          primary:            '#1f6e78',
          'primary-content':  '#ffffff',
          secondary:          '#c9a23a',
          'secondary-content':'#0f172a',
          accent:             '#e08a3c',
          'accent-content':   '#0f172a',
          neutral:            '#0f172a',
          'neutral-content':  '#f1f5f9',
          'base-100':         '#ffffff',   // cards / surfaces
          'base-200':         '#f8fafc',   // page canvas
          'base-300':         '#e2e8f0',   // borders
          'base-content':     '#0f172a',
          info:               '#0ea5e9',
          success:            '#16a34a',
          'success-content':  '#ffffff',
          warning:            '#d97706',
          'warning-content':  '#ffffff',
          error:              '#dc2626',
          'error-content':    '#ffffff',
        },
      },
    ],
    logs: false,
  },
};
