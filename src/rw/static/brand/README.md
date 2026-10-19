# RollbackWitness — Retained record

The code returns. The record remains.

The primary mark combines a counterclockwise return arrow with an upright retained record. The record is independent of the arrow, expressing the product's central hazard: rolling back code leaves newer data behind. It avoids a shield or an automatic-success checkmark.

## Start here

Open `/static/brand/index.html` while the local app is running. The gallery contains three directions, the recommended identity, a workspace application preview, evidence-state illustrations, icons, colors, and downloads. The preview's example is a visual application, not a runtime result.

`rollbackwitness-brand-kit.zip` contains the complete distributable set, including this guide and generation prompts. `brand-preview.png` is a gallery screenshot when present.

## Files and uses

| Files | Use |
| --- | --- |
| `mark-primary.svg`, `mark-dark.svg` | Transparent two-color marks for light/dark surfaces |
| `mark-mono.svg`, `mark-white.svg` | One-color applications; use the white mark on dark backgrounds |
| `wordmark-light.svg`, `wordmark-dark.svg`, `wordmark-mono.svg` | Horizontal lockups |
| `app-icon.svg`, `app-icon-512.png`, `app-icon-192.png` | Square application avatars |
| `favicon.svg`, `favicon-16.png`, `favicon-32.png`, `favicon.ico` | Small optical variant: remove record rules to preserve its silhouette |
| `apple-touch-icon.png` | 180px touch icon |
| `concept-witness-loop.svg`, `concept-evidence-path.svg` | Alternative logo directions, not additional primary identities |
| `state-investigate.svg` | Neutral reader/record investigation illustration |
| `state-blocked.svg`, `state-needs-evidence.svg`, `state-bounded-pass.svg` | Evidence-state illustrations; choose only from actual application state |
| `icon-*.svg` | Ten 24px line icons; 1.65px stroke matches the existing UI |
| `evidence-pattern.svg` | Quiet graph-path background for covers and explanatory surfaces |
| `cover.svg`, `cover.png` | 1200 × 630 project/README/demo cover |
| `retained-state-illustration.png` | 1536 × 1024 transparent AI-generated editorial illustration |
| `logo-directions.png` | AI-generated exploration sheet, not the canonical logo master |
| `tokens.json` | Current UI colors and usage values |

SVGs are the editable masters. Wordmark and cover SVGs use live text with the existing Inter / Segoe UI / Arial stack; their exact metrics depend on available fonts. The supplied PNGs are fixed-render exports for sharing. No third-party font binaries are bundled.

## Use with the current interface

- Keep the existing cool canvas `#f7f8fa`, white panels, charcoal `#20232b`, and blue `#1683f8`.
- Use the app tile at the existing 27px sidebar size. The favicon has a separate 16px optical variant.
- Leave clear space around the standalone mark at least as wide as its central record. Prefer 24px or larger; use the favicon variant below that size.
- Use the signature 3D illustration on introductory or cover surfaces. Keep dense evidence screens quiet; their line art is more legible.
- Red `#c44d5d`, amber `#b17b23`, and green `#168767` retain their existing evidence meanings. They are not alternate logo colors.
- A green illustration must never appear before the checker establishes the corresponding state. Bounded pass covers modeled byte/shape readability only.
- Native SVGs contain no scripts, external resources, raster embeddings, or remote fonts.

## Provenance and rebuild

The concept sheet and signature illustration were generated with the built-in ImageGen tool. Their complete prompts are in `generation-prompts.json`. These are illustrative assets, not evidence of a successful rollback or a security guarantee. No third-party logo or stock asset was incorporated; trademark clearance has not been performed.

The canonical SVGs, tokens, and cover were authored as native vector/code assets. Rebuild those files with:

```text
python scripts/build_brand_assets.py
```

This command preserves the ImageGen PNGs and gallery sources. PNG icon/cover exports are rasterizations of the SVG masters. The application uses the sidebar mark, favicon/touch-icon links, introductory illustration, evidence-state art, and a current-color SVG icon sprite. Workflow logic, explanations, and verdict wording are unchanged.

For optional raster exports, make `sharp` available on Node's module path and run `node scripts/export_brand_assets.mjs`. Then run `python scripts/package_brand_assets.py` to rebuild the ICO and ZIP. These are asset-build tools, not application runtime dependencies.
