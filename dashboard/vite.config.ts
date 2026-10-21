import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { devProxy, refuseBundledKey } from "./vite.auth.ts";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), refuseBundledKey()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@thoth/remotion-composition": path.resolve(
        __dirname,
        "../packages/remotion-composition/src",
      ),
    },
    // The shared composition lives outside this app, so Remotion and React must
    // still resolve to this app's single copy of each.
    dedupe: ["react", "react-dom", "remotion", "@remotion/media"],
  },
  server: {
    proxy: devProxy(),
  },
});
