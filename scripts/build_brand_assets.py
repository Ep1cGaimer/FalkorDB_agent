"""Rebuild the native RollbackWitness brand assets (stdlib only).

The two ImageGen PNGs are authored separately and deliberately preserved.
Run from any directory: python scripts/build_brand_assets.py
"""
from __future__ import annotations

import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src/rw/static/brand"
BLUE, INK, CANVAS, LINE = "#1683f8", "#20232b", "#f7f8fa", "#eceef2"
RED, GREEN, AMBER = "#c44d5d", "#168767", "#b17b23"


def svg(body: str, width: int = 64, height: int = 64, title: str = "RollbackWitness") -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">'
            f'<title>{escape(title)}</title>{body}</svg>\n')


def write(name: str, content: str) -> None:
    (OUT / name).write_text(content, encoding="utf-8", newline="\n")


def mark(arrow: str = BLUE, record: str = INK, micro: bool = False) -> str:
    # The arrow returns; the upright record is independent of the return path.
    return (f'<g fill="none" stroke="{arrow}" stroke-width="6.5" stroke-linecap="round" '
            'stroke-linejoin="round"><path d="M12 34a22 22 0 1 0 22-22H18"/>'
            '<path d="m26 4-9 8 9 8"/></g>'
            f'<path fill="{record}" fill-rule="evenodd" d="M29 26h10a3 3 0 0 1 3 3v14a3 3 0 0 1-3 3H29a3 3 0 0 1-3-3V29a3 3 0 0 1 3-3Z'
            + ("" if micro else 'M31 32h6a1 1 0 0 1 0 2h-6a1 1 0 0 1 0-2ZM31 38h3a1 1 0 0 1 0 2h-3a1 1 0 0 1 0-2Z')
            + '"/>')


def wordmark(arrow=BLUE, record=INK, text=INK) -> str:
    return svg(f'<g transform="translate(0 2)">{mark(arrow, record)}</g>'
               f'<text x="79" y="46" fill="{text}" font-family="Inter, Segoe UI, Arial, sans-serif" '
               'font-size="34" font-weight="600" letter-spacing="-1.25">RollbackWitness</text>',
               360, 70)


def spot(state: str) -> str:
    color = {"investigate": BLUE, "blocked": RED, "needs-evidence": AMBER, "bounded-pass": GREEN}[state]
    bg = {"investigate": "#eff6ff", "blocked": "#fff3f4", "needs-evidence": "#fff8e9", "bounded-pass": "#edf9f3"}[state]
    gap = state == "needs-evidence"
    wire = ('<path d="M79 76h30m22 0h30" stroke-dasharray="4 5"/>' if gap
            else '<path d="M79 76h82"/>')
    detail = {
        "investigate": '<circle cx="120" cy="76" r="15" fill="#fff"/><circle cx="120" cy="76" r="7" fill="none"/><path d="m125 81 6 6"/>',
        "blocked": '<circle cx="120" cy="76" r="13" fill="#fff"/><path d="m115 71 10 10m0-10-10 10"/>',
        "needs-evidence": '<circle cx="120" cy="76" r="12" fill="#fff" stroke-dasharray="2 5"/><path d="M120 70v7m0 5h.01"/>',
        "bounded-pass": '<circle cx="120" cy="76" r="13" fill="#fff"/><path d="m114 76 4 4 8-8"/>',
    }[state]
    return svg(f'<rect x="25" y="26" width="190" height="100" rx="45" fill="{bg}"/>'
               f'<g fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
               + wire + '<rect x="39" y="53" width="40" height="46" rx="7" fill="#fff"/>'
               '<path d="m55 65-6 7 6 7m9-14 6 7-6 7M49 88h20"/>'
               '<rect x="161" y="52" width="38" height="48" rx="6" fill="#fff"/>'
               '<path d="M170 65h20m-20 9h20m-20 9h12"/>' + detail + '</g>'
               '<g fill="#cdd7e4"><circle cx="28" cy="42" r="2"/><circle cx="211" cy="110" r="2"/></g>',
               240, 152, f"{state.replace('-', ' ')}: reader and retained record")


ICONS = {
    "release": '<path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5"/>',
    "reader": '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m9 9-3 3 3 3m6-6 3 3-3 3"/>',
    "record": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6Zm0 0v6h6M8 13h8m-8 4h5"/>',
    "store": '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 4 16 4 16 0V6M4 12c0 4 16 4 16 0"/>',
    "probe": '<path d="M3 12h4l3-7 4 14 3-7h4M4 4v2m16-2v2M4 18v2m16-2v2"/>',
    "receipt": '<path d="M5 3h14v18l-3-2-4 2-4-2-3 2V3Zm4 5h6m-6 4h6m-6 4h3"/>',
    "evidence-path": '<circle cx="5" cy="6" r="2.5"/><circle cx="19" cy="18" r="2.5"/><path d="M7.5 6H15a4 4 0 0 1 0 8H9a4 4 0 0 0 0 8h3m0-4h4.5"/>',
    "snapshot": '<path d="M8 4H4v4m12-4h4v4M4 16v4h4m12-4v4h-4"/><rect x="8" y="8" width="8" height="8" rx="1.5"/>',
    "approval": '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V2h6v2M8 13l3 3 5-6"/>',
    "rollback": '<path d="M5 11a8 8 0 1 0 8-8H6m4-3L6 3l4 4"/><rect x="10" y="9" width="6" height="7" rx="1"/>',
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    write("mark-primary.svg", svg(mark()))
    write("mark-dark.svg", svg(mark(BLUE, "#fff")))
    write("mark-mono.svg", svg(mark(INK, INK)))
    write("mark-white.svg", svg(mark("#fff", "#fff")))
    write("wordmark-light.svg", wordmark())
    write("wordmark-dark.svg", wordmark(record="#fff", text="#fff"))
    write("wordmark-mono.svg", wordmark(arrow=INK))
    write("app-icon.svg", svg(f'<rect width="64" height="64" rx="18" fill="{BLUE}"/>'
          f'<g transform="translate(7 7) scale(.78)">{mark("#fff", "#fff")}</g>'))
    write("favicon.svg", svg(f'<rect width="64" height="64" rx="18" fill="{BLUE}"/>'
          f'<g transform="translate(7 7) scale(.78)">{mark("#fff", "#fff", micro=True)}</g>'))
    write("concept-witness-loop.svg", svg('<g fill="none" stroke="#1683f8" stroke-width="6.5" '
          'stroke-linecap="round" stroke-linejoin="round"><path d="M12 34a22 22 0 1 0 22-22H18"/>'
          '<path d="m26 4-9 8 9 8"/></g><circle cx="34" cy="34" r="8" fill="#20232b"/>'))
    write("concept-evidence-path.svg", svg('<g fill="none" stroke="#1683f8" stroke-width="6.5" '
          'stroke-linecap="round" stroke-linejoin="round"><path d="M19 17h22a10 10 0 0 1 10 10v20"/>'
          '<path d="m26 8-11 9 11 9"/></g><path d="M17 47h34" stroke="#b6c8dc" stroke-width="5"/>'
          '<circle cx="17" cy="47" r="7" fill="#20232b"/><circle cx="51" cy="47" r="7" fill="#1683f8"/>'))
    for name in ("investigate", "blocked", "needs-evidence", "bounded-pass"):
        write(f"state-{name}.svg", spot(name))
    for name, paths in ICONS.items():
        write(f"icon-{name}.svg", svg('<g fill="none" stroke="#616874" stroke-width="1.65" '
              'stroke-linecap="round" stroke-linejoin="round">' + paths + '</g>', 24, 24, name.replace("-", " ")))
    write("icons.svg", '<svg xmlns="http://www.w3.org/2000/svg"><defs>' + ''.join(
        f'<symbol id="{name}" viewBox="0 0 24 24">{paths}</symbol>' for name, paths in ICONS.items()
    ) + '</defs></svg>\n')
    # A neutral path texture, with no compatibility implication.
    write("evidence-pattern.svg", svg('<defs><pattern id="dots" width="20" height="20" patternUnits="userSpaceOnUse">'
          '<circle cx="2" cy="2" r=".85" fill="#dce2eb"/></pattern></defs><rect width="600" height="240" fill="#fbfcfe"/>'
          '<rect width="600" height="240" fill="url(#dots)"/><path d="M60 160h100a40 40 0 0 0 40-40V80a40 40 0 0 1 40-40h100a40 40 0 0 1 40 40v80a40 40 0 0 0 40 40h80" '
          'fill="none" stroke="#c5dcf7" stroke-width="2"/><g fill="#fff" stroke="#1683f8" stroke-width="2">'
          '<circle cx="60" cy="160" r="6"/><circle cx="290" cy="40" r="6"/><circle cx="540" cy="200" r="6"/></g>', 600, 240, "Connected evidence path texture"))
    # Self-contained vector cover; no remote resources, runtime claims or fabricated metrics.
    cover = f'<rect width="1200" height="630" fill="{CANVAS}"/><path d="M780 0v630" stroke="{LINE}"/>'
    cover += f'<g transform="translate(64 52) scale(.9)">{mark()}</g>'
    cover += '<g fill="#20232b" font-family="Inter, Segoe UI, Arial, sans-serif"><text x="136" y="94" font-size="30" font-weight="600" letter-spacing="-1">RollbackWitness</text>'
    cover += '<text x="66" y="254" font-size="65" font-weight="600" letter-spacing="-2.5">Code goes back.</text><text x="66" y="333" font-size="65" font-weight="600" letter-spacing="-2.5">Data stays.</text>'
    cover += '<text x="69" y="403" font-size="23" fill="#616874">Check the readers. Follow the evidence.</text><text x="69" y="561" font-size="17" fill="#616874">Retained-state rollback investigation</text></g>'
    cover += f'<circle cx="975" cy="305" r="146" fill="#eff6ff"/><g transform="translate(839 167) scale(4.2)">{mark()}</g>'
    write("cover.svg", svg(cover, 1200, 630, "RollbackWitness — Code goes back. Data stays."))
    write("tokens.json", json.dumps({"name": "RollbackWitness / Retained record", "colors": {
        "blue": BLUE, "ink": INK, "canvas": CANVAS, "surface": "#ffffff", "line": LINE,
        "subtle": "#616874", "blocked": RED, "needsEvidence": AMBER, "boundedPass": GREEN},
        "fontFamily": "Inter, Segoe UI, system-ui, sans-serif", "iconStroke": 1.65,
        "clearSpace": "At least the width of the central record on every side",
        "minimumMarkSize": 24, "faviconOpticalSize": 16}, indent=2) + "\n")
    print(f"Native brand assets written to {OUT}")


if __name__ == "__main__":
    main()
