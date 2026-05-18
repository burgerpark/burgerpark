"""Direct TC001 Max camera probe (no TopView).

TC001 Max identifies on USB as VID=0x3474 PID=0x4962 — the InfiRay
"OMNI" family in TopView's stream_win_OMNI.conf. We talk to it through
the four DLLs that ship inside TopView's dll/dll_c001max/ folder:

  libircam.dll      — high-level handle wrappers
  libircmd.dll      — control + radiometric (basic_point_temp_info_get, …)
  libirdvs.dll      — camera enumeration + USB video streaming
  libirparse.dll    — frame split + format conversion (ac020_frame_data_cut)

Stage-1 goal: load every DLL, resolve every function we need, and call
the cheapest ones (version, init, list). If this all comes back OK we
can move on to opening the stream and pulling frames.

Run on the Windows PC (with TC001 Max plugged in, TopView CLOSED):
    python tc001max_probe.py

The script auto-discovers the TopView install path; pass it explicitly
if it's somewhere unusual:
    python tc001max_probe.py "C:\\Program Files\\TOPDON\\TopView"
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import (POINTER, byref, c_char, c_char_p, c_int, c_uint,
                    c_uint16, c_uint32, c_void_p, c_size_t, Structure)
from pathlib import Path


DEFAULT_TOPVIEW = Path(r"C:\Program Files\TOPDON\TopView")

# DLL load order (each DLL's imports must already be loadable when it loads)
DLL_LOAD_ORDER = [
    # support libs that live at the install root
    ("pthreadVC2.dll", "root"),
    # the camera-family DLLs are under dll/dll_c001max/
    ("libirparse.dll", "c001max"),
    ("libircmd.dll",   "c001max"),
    ("libirdvs.dll",   "c001max"),
    ("libircam.dll",   "c001max"),
]


def find_dlls(root: Path) -> dict[str, Path]:
    """Locate each DLL on disk and return name → absolute path."""
    out: dict[str, Path] = {}
    sub = root / "dll" / "dll_c001max"
    for name, where in DLL_LOAD_ORDER:
        if where == "c001max":
            cand = sub / name
        else:
            cand = root / name
            # pthreadVC2.dll sometimes sits next to the camera DLLs too
            if not cand.exists():
                cand = sub / name
        if not cand.exists():
            # last resort: scan the whole tree
            matches = list(root.rglob(name))
            if matches:
                cand = matches[0]
        if not cand.exists():
            raise FileNotFoundError(f"can't find {name} under {root}")
        out[name] = cand
    return out


def load_dlls(paths: dict[str, Path]) -> dict[str, ctypes.CDLL]:
    """Load DLLs in dependency order, adding their folders to the search path."""
    folders = {p.parent for p in paths.values()}
    if hasattr(os, "add_dll_directory"):
        for f in folders:
            try:
                os.add_dll_directory(str(f))
            except OSError as e:
                print(f"  warn: add_dll_directory({f}): {e}")

    # Also point Windows at the install root so any extra deps resolve
    install_root = next(iter(paths.values())).parent.parent.parent
    if install_root.exists() and hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(str(install_root))
        except OSError:
            pass

    loaded: dict[str, ctypes.CDLL] = {}
    for name, _ in DLL_LOAD_ORDER:
        p = paths[name]
        print(f"  loading  {p}")
        try:
            loaded[name] = ctypes.CDLL(str(p))
        except OSError as e:
            raise RuntimeError(f"LoadLibrary failed for {p}\n  {e}") from e
    return loaded


def need_func(dll: ctypes.CDLL, name: str,
              restype=c_int, argtypes=None) -> ctypes._FuncPointer | None:
    """GetProcAddress wrapper that won't crash if the symbol's missing."""
    try:
        fn = getattr(dll, name)
    except AttributeError:
        return None
    fn.restype = restype
    fn.argtypes = argtypes or []
    return fn


# Provisional signatures based on InfiRay's typical SDK style:
#   int func(void)                           — for *_init, *_release
#   int func(int*)                           — for *_version_number
#   int func(void**)                         — anything that returns a handle
#   int func(void*)                          — anything that consumes a handle
# We will tighten these as soon as we see them succeed/fail at runtime.

def stage_1(dlls: dict[str, ctypes.CDLL]) -> None:
    print("\n=== stage 1: version + log register ===")
    cmd = dlls["libircmd.dll"]
    dvs = dlls["libirdvs.dll"]
    cam = dlls["libircam.dll"]
    parse = dlls["libirparse.dll"]

    for dll, name, sym in [
        (cmd,   "libircmd",   "ircmd_version_number"),
        (dvs,   "libirdvs",   "irdvs_log_register"),
        (cam,   "libircam",   "ircam_version_number"),
        (parse, "libirparse", "irparse_version"),
    ]:
        # try int (*)(void)  → return integer version code
        fn = need_func(dll, sym, restype=c_int, argtypes=[])
        if fn is None:
            print(f"  ! {name}::{sym} not exported")
            continue
        try:
            rv = fn()
            print(f"  ok {name}::{sym}() → {rv}")
        except Exception as e:
            print(f"  ! {name}::{sym} crashed: {e}")


def stage_2_enumerate(dlls: dict[str, ctypes.CDLL]) -> None:
    """Try to list connected cameras via libirdvs."""
    print("\n=== stage 2: camera init + list ===")
    dvs = dlls["libirdvs.dll"]

    init = need_func(dvs, "irdvs_camera_init", restype=c_int, argtypes=[])
    if init is None:
        print("  ! irdvs_camera_init not found")
        return

    rv = init()
    print(f"  irdvs_camera_init() → {rv}")

    # Most InfiRay enumerate functions look like:
    #   int irdvs_camera_list(DeviceInfo *out_buf, int *io_count)
    # We pass a fat buffer (16 entries × 256 bytes) and an int*.
    cam_list = need_func(
        dvs, "irdvs_camera_list",
        restype=c_int,
        argtypes=[c_void_p, POINTER(c_int)],
    )
    if cam_list is None:
        print("  ! irdvs_camera_list not found")
        return
    buf = (c_char * (16 * 256))()
    count = c_int(16)
    try:
        rv = cam_list(buf, byref(count))
        print(f"  irdvs_camera_list(buf,&count=16) → rv={rv}  count={count.value}")
        if 0 < count.value <= 16:
            # try to print any readable ASCII fields
            data = bytes(buf)
            head = data[: count.value * 256][:512]
            print(f"  first 512 bytes (printable runs):")
            run = []
            for b in head:
                if 32 <= b < 127:
                    run.append(chr(b))
                else:
                    if len(run) >= 4:
                        print(f"    {''.join(run)}")
                    run = []
    except Exception as e:
        print(f"  ! irdvs_camera_list crashed: {e}")

    release = need_func(dvs, "irdvs_camera_release", restype=c_int, argtypes=[])
    if release is not None:
        rv = release()
        print(f"  irdvs_camera_release() → {rv}")


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TOPVIEW
    if not root.exists():
        print(f"❌ TopView root not found: {root}")
        print("   pass an explicit path as the first argument")
        return 1
    print(f"TopView root: {root}")

    print("\n=== resolving DLL paths ===")
    try:
        paths = find_dlls(root)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return 1
    for n, p in paths.items():
        print(f"  {n:18s}  {p}")

    print("\n=== loading DLLs ===")
    try:
        dlls = load_dlls(paths)
    except RuntimeError as e:
        print(f"❌ {e}")
        return 1

    stage_1(dlls)
    stage_2_enumerate(dlls)

    print("\n✅ probe complete — capture this whole output and send it back")
    return 0


if __name__ == "__main__":
    sys.exit(main())
