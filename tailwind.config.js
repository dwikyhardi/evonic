/**
 * Tailwind config used to pre-build a static CSS bundle that replaces the
 * heavy JIT runtime previously loaded as static/js/tailwindcss.js.
 *
 * Build:
 *   npx -y tailwindcss@3 -c tailwind.config.js -i src/tailwind.css \
 *       -o static/css/tailwind.css --minify
 *
 * The `darkMode: 'class'` setting matches the previous inline runtime
 * config in templates/base.html so the existing `html.dark` toggle keeps
 * working.
 */
module.exports = {
  darkMode: 'class',
  content: [
    './templates/**/*.html',
    './static/js/**/*.js',
    './plugins/**/templates/**/*.html',
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};
