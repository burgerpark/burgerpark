"""Stage 2: try several plausible signatures for the camera list / open functions.

The first probe got irdvs_camera_init()=0 (good) but irdvs_camera_list with
our guessed signature returned 10 (InfiRay's typical "parameter error").

This script sweeps the common variants:

  v1: int func(void)                              — returns count
  v2: int func(int* count_out)                    — pointer-out count
  v3: int func(void* buf, int* count_inout)       — our original guess
  v4: int func(int* count_out, void** array_out)  — count + array
  v5: int func(int max_count, void* buf, int* real_count)

For each variant it prints (rv, count) so we can see which one InfiRay
actually expects. It also tries the parallel libirdvs_usb_device_* path,
which may be how TopView actually enumerates the camera.

Run (TopView must be CLOSED so the camera handle is free):
    python tc001max_probe2.py
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import (POINTER, byref, c_char, c_int, c_int32, c_uint, c_uint32,
                    c_uint64, c_void_p, c_size_t)
from pathlib import Path


DEFAULT_TOPVIEW = Path(r"C:\Program Files\TOPDON\TopView")
TC001MAX_VID = 0x3474
TC001MAX_PID = 0x4962

DLL_LOAD_ORDER = [
    ("pthreadVC2.dll", "root"),
    ("libirparse.dll", "c001max"),
    ("libircmd.dll",   "c001max"),
    ("libirdvs.dll",   "c001max"),
    ("libircam.dll",   "c001max"),
]


def find_and_load(root: Path) -> dict[str, ctypes.CDLL]:
    sub = root / "dll" / "dll_c001max"
    paths: dict[str, Path] = {}
    for name, where in DLL_LOAD_ORDER:
        cand = (sub / name) if where == "c001max" else (root / name)
        if not cand.exists():
            ms = list(root.rglob(name))
            if ms: cand = ms[0]
        if not cand.exists():
            raise FileNotFoundError(name)
        paths[name] = cand

    if hasattr(os, "add_dll_directory"):
        for p in {x.parent for x in paths.values()}:
            try: os.add_dll_directory(str(p))
            except OSError: pass
        try: os.add_dll_directory(str(root))
        except OSError: pass

    dlls: dict[str, ctypes.CDLL] = {}
    for name, _ in DLL_LOAD_ORDER:
        dlls[name] = ctypes.CDLL(str(paths[name]))
    return dlls


def attempt(label: str, fn_factory):
    """Run a callable that returns (rv, debug_str); print result, swallow errors."""
    try:
        rv, dbg = fn_factory()
        marker = "ok" if rv == 0 else f"rv={rv}"
        print(f"  [{marker:>8s}] {label:40s} {dbg}")
        return rv, dbg
    except Exception as e:
        print(f"  [   crash] {label:40s} {type(e).__name__}: {e}")
        return None, None


def sweep_list_signatures(dvs: ctypes.CDLL) -> None:
    """Try multiple plausible signatures for irdvs_camera_list."""
    print("\n=== signature sweep for irdvs_camera_list ===")

    sym = "irdvs_camera_list"
    if not hasattr(dvs, sym):
        print(f"  symbol {sym} missing")
        return

    base_addr = ctypes.cast(getattr(dvs, sym), c_void_p).value
    print(f"  symbol addr = 0x{base_addr:016x}")

    def v1_void_to_int():
        f = ctypes.CFUNCTYPE(c_int)(base_addr)
        rv = f()
        return rv, f"v1 int(void) → {rv}"

    def v2_intp_to_int():
        cnt = c_int(0)
        f = ctypes.CFUNCTYPE(c_int, POINTER(c_int))(base_addr)
        rv = f(byref(cnt))
        return rv, f"v2 int(int* count_out) → rv={rv} count={cnt.value}"

    def v3_buf_intp():
        buf = (c_char * 4096)()
        cnt = c_int(16)
        f = ctypes.CFUNCTYPE(c_int, c_void_p, POINTER(c_int))(base_addr)
        rv = f(buf, byref(cnt))
        return rv, f"v3 int(buf, int* count) → rv={rv} count={cnt.value}"

    def v4_intp_voidpp():
        cnt = c_int(0)
        arr = c_void_p(0)
        f = ctypes.CFUNCTYPE(c_int, POINTER(c_int), POINTER(c_void_p))(base_addr)
        rv = f(byref(cnt), byref(arr))
        return rv, f"v4 int(int* cnt, void** arr) → rv={rv} count={cnt.value} arr=0x{arr.value or 0:x}"

    def v5_max_buf_realcnt():
        buf = (c_char * 4096)()
        real = c_int(0)
        f = ctypes.CFUNCTYPE(c_int, c_int, c_void_p, POINTER(c_int))(base_addr)
        rv = f(16, buf, byref(real))
        return rv, f"v5 int(max=16, buf, int* real) → rv={rv} real={real.value}"

    def v6_voidp_to_int():
        buf = (c_char * 4096)()
        f = ctypes.CFUNCTYPE(c_int, c_void_p)(base_addr)
        rv = f(buf)
        return rv, f"v6 int(void* buf) → rv={rv}"

    for fac in (v1_void_to_int, v2_intp_to_int, v3_buf_intp,
                v4_intp_voidpp, v5_max_buf_realcnt, v6_voidp_to_int):
        attempt(sym, fac)


def sweep_usb_device(dvs: ctypes.CDLL) -> None:
    """Probe the lower-level USB device path."""
    print("\n=== sweep irdvs_usb_device_init/open ===")

    if hasattr(dvs, "irdvs_usb_device_init"):
        base = ctypes.cast(dvs.irdvs_usb_device_init, c_void_p).value

        def init_void():
            f = ctypes.CFUNCTYPE(c_int)(base)
            return f(), "v1 int(void)"

        def init_intp():
            cnt = c_int(0)
            f = ctypes.CFUNCTYPE(c_int, POINTER(c_int))(base)
            rv = f(byref(cnt))
            return rv, f"v2 int(int* cnt) cnt={cnt.value}"

        for fac in (init_void, init_intp):
            attempt("irdvs_usb_device_init", fac)
    else:
        print("  irdvs_usb_device_init missing")

    if hasattr(dvs, "irdvs_usb_device_open"):
        base = ctypes.cast(dvs.irdvs_usb_device_open, c_void_p).value

        # InfiRay style: int open(uint16_t vid, uint16_t pid, int same_id, void** handle_out)
        def open_vid_pid():
            h = c_void_p(0)
            f = ctypes.CFUNCTYPE(c_int, c_uint, c_uint, c_int, POINTER(c_void_p))(base)
            rv = f(TC001MAX_VID, TC001MAX_PID, 0, byref(h))
            return rv, f"v1 int(vid={hex(TC001MAX_VID)}, pid={hex(TC001MAX_PID)}, same=0, &h) h=0x{h.value or 0:x}"

        def open_index():
            h = c_void_p(0)
            f = ctypes.CFUNCTYPE(c_int, c_int, POINTER(c_void_p))(base)
            rv = f(0, byref(h))
            return rv, f"v2 int(idx=0, &h) h=0x{h.value or 0:x}"

        for fac in (open_vid_pid, open_index):
            attempt("irdvs_usb_device_open", fac)
    else:
        print("  irdvs_usb_device_open missing")


def sweep_handle_create(dvs: ctypes.CDLL) -> None:
    print("\n=== sweep irdvs_camera_handle_create ===")
    if not hasattr(dvs, "irdvs_camera_handle_create"):
        print("  missing")
        return
    base = ctypes.cast(dvs.irdvs_camera_handle_create, c_void_p).value

    def v1_handle_out():
        h = c_void_p(0)
        f = ctypes.CFUNCTYPE(c_int, POINTER(c_void_p))(base)
        rv = f(byref(h))
        return rv, f"v1 int(void** h_out) h=0x{h.value or 0:x}"

    def v2_vid_pid_handle():
        h = c_void_p(0)
        f = ctypes.CFUNCTYPE(c_int, c_uint, c_uint, c_int, POINTER(c_void_p))(base)
        rv = f(TC001MAX_VID, TC001MAX_PID, 0, byref(h))
        return rv, f"v2 int(vid,pid,same,&h) h=0x{h.value or 0:x}"

    for fac in (v1_handle_out, v2_vid_pid_handle):
        attempt("irdvs_camera_handle_create", fac)


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TOPVIEW
    if not root.exists():
        print(f"❌ TopView root not found: {root}")
        return 1
    print(f"TopView root: {root}")

    try:
        dlls = find_and_load(root)
    except Exception as e:
        print(f"❌ load failed: {e}")
        return 1
    print("DLLs loaded.")

    dvs = dlls["libirdvs.dll"]

    init = dvs.irdvs_camera_init
    init.restype = c_int; init.argtypes = []
    rv = init()
    print(f"\nirdvs_camera_init() → {rv}")
    if rv != 0:
        print("  ! init failed; aborting")
        return 1

    sweep_list_signatures(dvs)
    sweep_usb_device(dvs)
    sweep_handle_create(dvs)

    release = dvs.irdvs_camera_release
    release.restype = c_int; release.argtypes = []
    rv = release()
    print(f"\nirdvs_camera_release() → {rv}")
    print("\n✅ sweep complete — paste the full output back")
    return 0


if __name__ == "__main__":
    sys.exit(main())
