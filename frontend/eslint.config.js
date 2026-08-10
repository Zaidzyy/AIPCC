import js from "@eslint/js";
import globals from "globals";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";

/**
 * `npm run lint` was in package.json from Phase 0 but had no config, so it
 * exited non-zero on every run. The rules that matter here are the react-hooks
 * ones: a missing dependency in a query or effect is the kind of bug that
 * survives review and shows up as stale data.
 */
export default [
  { ignores: ["dist/**", "node_modules/**"] },
  js.configs.recommended,
  {
    files: ["**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        ecmaFeatures: { jsx: true },
        sourceType: "module",
      },
    },
    plugins: {
      react,
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Without this, every component referenced only from JSX reads as an
      // unused variable — `no-unused-vars` does not understand JSX on its own.
      "react/jsx-uses-vars": "error",
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
      "no-unused-vars": ["error", { varsIgnorePattern: "^[A-Z_]" }],
    },
  },
  {
    /**
     * `react-refresh/only-export-components` off for the design system and the
     * auth provider, and nowhere else.
     *
     * The rule protects component state across a hot reload, and it fires here
     * on three things that cannot lose any:
     *   - `export const Dialog = DialogPrimitive.Root` — a re-export of a
     *     third-party component the plugin cannot statically recognise as one;
     *   - `buttonVariants`, a `cva` object;
     *   - `useToast` / `useAuth`, hooks that must live beside the provider
     *     that owns their context.
     *
     * Splitting each context into a third module to satisfy the plugin would
     * add a file per primitive to make a false positive go quiet. It stays on
     * for pages and feature components, where a stray non-component export
     * really does cost state on every save.
     */
    files: [
      "src/components/ui/**/*.jsx",
      "src/context/AuthContext.jsx",
    ],
    rules: {
      "react-refresh/only-export-components": "off",
    },
  },
  {
    // Tests import Vitest's API explicitly, but jsdom globals and the Node
    // globals the setup file touches are not in `globals.browser`.
    files: ["src/**/*.{test,spec}.{js,jsx}", "src/test/**/*.{js,jsx}"],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
  },
  {
    // The Vite config runs in Node, not the browser. It reads
    // `VITE_API_BASE_URL` to build the SPA's `connect-src`, so it needs
    // `process` — which `globals.browser` correctly does not provide.
    files: ["*.config.js"],
    languageOptions: {
      globals: globals.node,
    },
  },
];
