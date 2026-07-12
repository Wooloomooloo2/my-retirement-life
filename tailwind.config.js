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
    // The app renders with data-theme="light" only. The vendored CDN build
    // shipped all 32 DaisyUI themes (2.9 MB) to serve this one.
    themes: ['light'],
    logs: false,
  },
};
