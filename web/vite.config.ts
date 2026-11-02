import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Note: vitest runs with its defaults (explicit imports in test files,
// node environment). No `test` key here: importing defineConfig from
// "vitest/config" pulls vitest's bundled vite types and clashes with the
// installed vite's types under tsc -b.
export default defineConfig({
  plugins: [react()],
});
