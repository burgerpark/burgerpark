"""Dump exports of every DLL under dll_c001max/ (TC001 Max specific libraries).

Run on the Windows PC (pefile already installed):
    python dump_c001max.py
"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(r"C:\Program Files\TOPDON\TopView\dll\dll_c001max")
# also analyze a few that sit at the install root and are likely TC001 Max relevant
EXTRA = [
    Path(r"C:\Program Files\TOPDON\TopView\libiruvc.dll"),
    Path(r"C:\Program Files\TOPDON\TopView\libir_infoparse.dll"),
    Path(r"C:\Program Files\TOPDON\TopView\libircam.dll"),
    Path(r"C:\Program Files\TOPDON\TopView\ARUVCLib.dll"),
]


def main() -> int:
    try:
        import pefile
    except ImportError:
        print("pefile not installed. run: pip install \"pefile<2024.8.26\"")
        return 1

    targets = []
    if TARGET.exists():
        targets.extend(sorted(TARGET.glob("*.dll")))
    for e in EXTRA:
        if e.exists():
            targets.append(e)

    out_lines: list[str] = []

    def log(s: str = "") -> None:
        print(s)
        out_lines.append(s)

    for path in targets:
        log(f"\n{'=' * 70}")
        log(f"{path}")
        log(f"  size: {path.stat().st_size:,} B")
        try:
            pe = pefile.PE(str(path), fast_load=True)
            pe.parse_data_directories()
        except Exception as e:
            log(f"  ! parse error: {e}")
            continue
        log(f"  arch: {hex(pe.FILE_HEADER.Machine)}")

        imports = []
        if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
            for imp in pe.DIRECTORY_ENTRY_IMPORT:
                imports.append(imp.dll.decode("utf-8", "ignore"))
        log(f"  imports ({len(imports)}):")
        for i in imports:
            log(f"    - {i}")

        exports = []
        if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
            for e in pe.DIRECTORY_ENTRY_EXPORT.symbols:
                if e.name:
                    exports.append(e.name.decode("utf-8", "ignore"))
        log(f"  exports ({len(exports)}):")
        for e in exports:
            log(f"    + {e}")

    out = Path.cwd() / "c001max_exports.txt"
    out.write_text("\n".join(out_lines), encoding="utf-8")
    log(f"\n→ saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
