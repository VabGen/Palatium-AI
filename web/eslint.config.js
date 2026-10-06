// web/eslint.config.js
//
// Flat config. Two deliberate choices, both documented in rule 084:
//
//  1. ESLint 10, not 9. `eslint-plugin-react` and `eslint-plugin-jsx-a11y` still cap their
//     peer at `^9` and ESLint 9 is end-of-life, so the React rules come from
//     `@eslint-react/eslint-plugin` (eslint peer `*`, actively maintained) and the hooks
//     rules from `eslint-plugin-react-hooks` (peer includes `^10`). Forcing ESLint 10 past a
//     `^9` peer with `--legacy-peer-deps` would install a plugin that never claimed to work.
//  2. `react-hooks` rules are *enabled*, not merely imported: `exhaustive-deps` is the
//     static half of the "effects always clean up" requirement (080/084), and the previous
//     config listed the plugin without turning any of its rules on.
//
// Static a11y roles/aria linting is the one gap: `eslint-plugin-jsx-a11y` is incompatible
// with ESLint 10 (recorded as a ratchet item in 084). Runtime a11y is covered by axe in the
// Playwright suite, which is the stricter of the two for contrast and focus order anyway.
import js from '@eslint/js';
import eslintReact from '@eslint-react/eslint-plugin';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

const tsFiles = ['**/*.{ts,tsx}'];

export default tseslint.config(
  {
    // Build outputs and generated manifests are not sources; `custom-elements.json` is
    // produced by `npm run cem` and checked by `cem:check` (drift gate), not linted.
    ignores: [
      'dist/',
      'dist-widget/',
      'node_modules/',
      'playwright-report/',
      'test-results/',
      '.shots/',
      'custom-elements.json',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{js,mjs,ts,tsx}'],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
      // A widget lives inside someone else's page: a stray `console.log` leaks into the
      // host's console. Degraded-path reporting (`warn`/`error`) stays allowed, so the
      // rule catches leftovers rather than honest diagnostics.
      'no-console': ['error', { allow: ['warn', 'error'] }],
    },
  },
  {
    // Node CLI scripts: stdout *is* the interface (`widget-release.mjs` prints the SRI
    // manifest a release is verified against), so the browser-oriented rule does not apply.
    files: ['scripts/**/*.mjs'],
    rules: { 'no-console': 'off' },
  },
  {
    files: tsFiles,
    plugins: {
      ...eslintReact.configs.recommended.plugins,
      ...reactHooks.configs.flat.recommended.plugins,
    },
    settings: eslintReact.configs.recommended.settings,
    rules: {
      ...eslintReact.configs.recommended.rules,
      ...reactHooks.configs.flat.recommended.rules,
    },
  },
  {
    // Render-only module: blocks, rows, cells and bars all come from one server document,
    // are rendered once and are never reordered client-side, so the index *is* a stable
    // identity here. The rule stays on everywhere else, where it catches keys on lists the
    // user can reorder — silencing it globally would be the real mistake (050: fix the
    // tool's scope, not the correct code).
    files: ['src/components/BlockRenderer.tsx'],
    rules: { '@eslint-react/no-array-index-key': 'off' },
  }
);
