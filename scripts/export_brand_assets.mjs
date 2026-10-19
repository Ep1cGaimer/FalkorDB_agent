// Optional raster exports. Needs sharp on Node's module path; not an app runtime dependency.
// node scripts/export_brand_assets.mjs
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
const require = createRequire(import.meta.url);
const sharp = require("sharp");
const root = fileURLToPath(new URL("../src/rw/static/brand/", import.meta.url));
const exports = [
  ["mark-primary.svg", "mark-primary.png", 1024],
  ["mark-dark.svg", "mark-dark.png", 1024],
  ["mark-mono.svg", "mark-mono.png", 1024],
  ["mark-white.svg", "mark-white.png", 1024],
  ["app-icon.svg", "app-icon-512.png", 512],
  ["app-icon.svg", "app-icon-192.png", 192],
  ["app-icon.svg", "apple-touch-icon.png", 180],
  ["favicon.svg", "favicon-16.png", 16],
  ["favicon.svg", "favicon-32.png", 32],
  ["wordmark-light.svg", "wordmark-light.png", 1440],
  ["wordmark-dark.svg", "wordmark-dark.png", 1440],
  ["wordmark-mono.svg", "wordmark-mono.png", 1440],
  ["cover.svg", "cover.png", 1200],
];
for (const [source, target, width] of exports) {
  await sharp(join(root, source), { density: 288 }).resize({ width }).png().toFile(join(root, target));
  console.log(`${target} (${width}px)`);
}
