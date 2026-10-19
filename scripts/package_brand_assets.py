"""Package the brand kit after native generation and optional PNG export."""
from pathlib import Path
import struct
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "src/rw/static/brand"


def main() -> None:
    images = [(size, (BRAND / f"favicon-{size}.png").read_bytes()) for size in (16, 32)]
    offset = 6 + 16 * len(images)
    directory, payload = bytearray(), bytearray()
    for size, data in images:
        directory.extend(struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(data), offset))
        payload.extend(data)
        offset += len(data)
    (BRAND / "favicon.ico").write_bytes(struct.pack("<HHH", 0, 1, len(images)) + directory + payload)
    archive = BRAND / "rollbackwitness-brand-kit.zip"
    files = sorted(p for p in BRAND.iterdir() if p.is_file() and p.suffix != ".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for path in files:
            output.write(path, f"rollbackwitness-brand-kit/{path.name}")
        for script in ("build_brand_assets.py", "export_brand_assets.mjs", "package_brand_assets.py"):
            output.write(ROOT / "scripts" / script, f"scripts/{script}")
    with zipfile.ZipFile(archive) as output:
        assert output.testzip() is None
        print(f"{len(output.namelist())} files; {archive.stat().st_size:,} bytes; archive verified")


if __name__ == "__main__":
    main()
