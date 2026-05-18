"""Recon tool: scan the TopView installation folder for ways to talk to the
TC001 Max directly (without going through the TopView UI).

Run on the Windows PC where TopView is installed:
    pip install pefile
    python analyze_topview.py                       # auto-detect install path
    python analyze_topview.py "C:\\Program Files\\TOPDON\\TopView"   # explicit

Outputs:
    topview_analysis.txt   — human-readable, paste this into the chat
    topview_analysis.json  — machine-readable, attach as a file if huge

What we're hunting for:
    - DLLs that handle USB / UVC / thermal / radiometric pipelines
    - Exported functions we can call from Python via ctypes
    - Strings hinting at the camera protocol (TC001, libusb, vid_/pid_, …)
    - Tech stack hints: .NET, Qt, Electron, Python, native C++ …
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

CANDIDATE_DIRS = [
    Path(r"C:\Program Files\TOPDON\TopView"),
    Path(r"C:\Program Files (x86)\TOPDON\TopView"),
    Path(r"C:\Program Files\Topdon\TopView"),
    Path(r"C:\Program Files (x86)\Topdon\TopView"),
    Path(r"C:\Program Files\TopView"),
    Path(r"C:\Program Files (x86)\TopView"),
    Path.home() / "AppData/Local/Programs/TopView",
    Path.home() / "AppData/Local/Programs/TOPDON/TopView",
    Path.home() / "AppData/Local/TOPDON/TopView",
    Path.home() / "AppData/Roaming/TOPDON/TopView",
]

# Keywords we want to spot in file names + binary strings
HOT_NAMES = [
    "usb", "uvc", "thermal", "camera", "cam", "tc001", "tc_", "ir_",
    "iruvc", "radiometric", "topdon", "libusb", "stream", "frame", "image",
    "device", "tau", "pelco",
]
HOT_STRINGS = [
    "TC001", "TC001 Max", "TC001Max", "libusb", "irlib", "iruvc",
    "Radiometric", "RAW", "GetTemperature", "ReadFrame", "OpenDevice",
    "UVC", "USBDevice", "FrameCallback", "vid_", "pid_", "VID_", "PID_",
    "DeviceIoControl", "SetupAPI", "WinUSB", "VID_3474", "VID_3008",
    "Pseudo", "Colormap", "Iron", "Rainbow", "FFC", "NUC",
]

TECH_HINTS = {
    ".NET / C# / WPF": ["mscorlib", "System.dll", "presentationcore.dll",
                        ".runtimeconfig.json", "WindowsBase.dll"],
    "Qt": ["Qt5", "Qt6", "QtCore", "QtGui", "QtWidgets"],
    "Electron": ["resources/app.asar", "electron.exe",
                 "Chromium", "ffmpeg.dll", "v8_context"],
    "Python (PyInstaller)": ["python3", "pythoncom", "_socket.pyd",
                             "base_library.zip"],
    "MFC / native C++": ["msvcp", "vcruntime", "MFCMSVC"],
}


def find_install() -> Path | None:
    for c in CANDIDATE_DIRS:
        if c.exists():
            return c
    return None


def walk(root: Path):
    """Yield (path, size_bytes) for each regular file under root."""
    for f in root.rglob("*"):
        try:
            if f.is_file():
                yield f, f.stat().st_size
        except OSError:
            continue


def detect_tech_stack(root: Path, all_paths: list[Path]) -> list[str]:
    hits: list[str] = []
    flat = " ".join(str(p).lower() for p in all_paths)
    for tech, markers in TECH_HINTS.items():
        for m in markers:
            if m.lower() in flat:
                hits.append(f"{tech}  (marker: {m})")
                break
    return hits


def pe_info(path: Path) -> dict:
    info: dict = {"size": path.stat().st_size}
    try:
        import pefile
    except ImportError:
        info["pefile"] = "not installed (pip install pefile for full info)"
        return info
    try:
        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories()
        exports = []
        if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
            for e in pe.DIRECTORY_ENTRY_EXPORT.symbols:
                if e.name:
                    exports.append(e.name.decode("utf-8", "ignore"))
        imports = []
        if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
            for imp in pe.DIRECTORY_ENTRY_IMPORT:
                imports.append(imp.dll.decode("utf-8", "ignore"))
        info["exports"] = exports
        info["imports"] = sorted(set(imports))
        info["machine"] = hex(pe.FILE_HEADER.Machine)
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
    return info


def grep_strings(path: Path, terms: list[str], max_hits: int = 50) -> list[str]:
    try:
        data = path.read_bytes()
    except Exception as e:
        return [f"<read error: {e}>"]
    results: set[str] = set()
    for run in re.findall(rb"[\x20-\x7e]{6,}", data):
        s = run.decode("ascii", "ignore")
        sl = s.lower()
        for t in terms:
            if t.lower() in sl:
                results.add(s)
                if len(results) >= max_hits:
                    return sorted(results)
                break
    return sorted(results)


def main() -> int:
    if len(sys.argv) > 1:
        root = Path(sys.argv[1])
    else:
        root = find_install()
        if root is None:
            print("could not find TopView in the usual places.")
            print("re-run with an explicit path, e.g.:")
            print(r'    python analyze_topview.py "C:\Program Files\TOPDON\TopView"')
            return 1
    if not root.exists():
        print(f"path does not exist: {root}")
        return 1

    lines: list[str] = []
    out_json: dict = {"install": str(root)}

    def log(s: str = "") -> None:
        print(s)
        lines.append(s)

    log(f"# TopView install analysis")
    log(f"root: {root}")

    # 1. file tree summary
    files = list(walk(root))
    by_ext: Counter[str] = Counter()
    for f, _ in files:
        by_ext[f.suffix.lower() or "(no ext)"] += 1
    files.sort(key=lambda x: x[1], reverse=True)

    out_json["total_files"] = len(files)
    out_json["by_extension"] = dict(by_ext.most_common(50))
    out_json["top_files"] = [
        {"path": str(f.relative_to(root)), "size": sz} for f, sz in files[:40]
    ]

    log(f"\n## tree summary")
    log(f"total files: {len(files)}")
    log("extensions (top 15):")
    for ext, n in by_ext.most_common(15):
        log(f"  {ext:14s} {n:5d}")

    log("\n## top 30 largest files")
    for f, sz in files[:30]:
        log(f"  {sz:12,} B   {f.relative_to(root)}")

    # 2. tech-stack hints
    stack = detect_tech_stack(root, [f for f, _ in files])
    out_json["tech_stack_hints"] = stack
    log("\n## tech stack hints")
    if stack:
        for s in stack:
            log(f"  - {s}")
    else:
        log("  (no obvious markers — likely plain native C++/Qt)")

    # 3. interesting DLLs/EXEs by name
    bins = [f for f, _ in files if f.suffix.lower() in (".dll", ".exe", ".pyd")]
    interesting = [b for b in bins
                   if any(k in b.name.lower() for k in HOT_NAMES)]
    log(f"\n## DLL/EXE with USB/camera/thermal hints in their name ({len(interesting)} found)")

    dll_details: list[dict] = []
    for b in interesting:
        rel = str(b.relative_to(root))
        info = pe_info(b)
        info["path"] = rel
        info["name"] = b.name
        dll_details.append(info)
        log(f"\n### {rel}  ({info.get('size', 0):,} B)")
        if "machine" in info:
            log(f"  arch: {info['machine']}")
        if "imports" in info and info["imports"]:
            log(f"  imports ({len(info['imports'])}):")
            for imp in info["imports"][:20]:
                log(f"    - {imp}")
            if len(info["imports"]) > 20:
                log(f"    ... and {len(info['imports']) - 20} more")
        if "exports" in info and info["exports"]:
            log(f"  exports ({len(info['exports'])}):")
            for e in info["exports"][:40]:
                log(f"    + {e}")
            if len(info["exports"]) > 40:
                log(f"    ... and {len(info['exports']) - 40} more")
        if "error" in info:
            log(f"  ! {info['error']}")
        if "pefile" in info:
            log(f"  ! {info['pefile']}")

    out_json["interesting_binaries"] = dll_details

    # 4. string hits in all binaries
    log(f"\n## strings matching {len(HOT_STRINGS)} hunting terms (in any DLL/EXE/PYD)")
    string_hits: dict[str, list[str]] = {}
    for b in bins:
        hits = grep_strings(b, HOT_STRINGS, max_hits=30)
        if hits:
            rel = str(b.relative_to(root))
            string_hits[rel] = hits
            log(f"\n### {rel}")
            for s in hits[:25]:
                log(f"    {s}")
            if len(hits) > 25:
                log(f"    ... and {len(hits) - 25} more")
    out_json["string_hits"] = string_hits

    # 5. config / json / xml / ini files (often reveal protocols)
    confs = [(f, sz) for f, sz in files
             if f.suffix.lower() in (".json", ".xml", ".ini", ".config", ".yaml", ".yml")
             and sz < 200_000]
    log(f"\n## config files ({len(confs)})")
    confs_dump: dict[str, str] = {}
    for f, sz in confs[:30]:
        rel = str(f.relative_to(root))
        try:
            txt = f.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            txt = f"<read error: {e}>"
        # truncate big files
        if len(txt) > 6_000:
            txt = txt[:6_000] + "\n... [truncated]"
        confs_dump[rel] = txt
        log(f"\n### {rel}  ({sz} B)")
        for ln in txt.splitlines()[:80]:
            log(f"    {ln}")
    out_json["config_files"] = confs_dump

    # 6. write outputs
    cwd = Path.cwd()
    out_txt = cwd / "topview_analysis.txt"
    out_json_path = cwd / "topview_analysis.json"
    out_txt.write_text("\n".join(lines), encoding="utf-8")
    out_json_path.write_text(json.dumps(out_json, indent=2, ensure_ascii=False),
                             encoding="utf-8")
    print()
    print(f"✅ wrote {out_txt}")
    print(f"✅ wrote {out_json_path}")
    print()
    print("paste topview_analysis.txt into the chat (or attach the .json to a release).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
