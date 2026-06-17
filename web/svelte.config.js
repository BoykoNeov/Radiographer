import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

export default {
  // Svelte 5 + TypeScript via Vite's preprocessor.
  preprocess: vitePreprocess(),
};
