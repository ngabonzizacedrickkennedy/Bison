import { build } from "esbuild";

const shared = {
  bundle: true,
  platform: "node",
  target: "node22",
  external: ["electron"],
  logLevel: "info",
};

await build({
  ...shared,
  entryPoints: ["electron/main.ts"],
  outfile: "dist/main/main.mjs",
  format: "esm",
});

await build({
  ...shared,
  entryPoints: ["electron/preload.ts"],
  outfile: "dist/main/preload.cjs",
  format: "cjs",
});
