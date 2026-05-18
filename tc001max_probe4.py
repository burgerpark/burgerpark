"""Stage 4: open USB device with VID/PID as C strings, then build a camera handle.

probe3 confirmed:
  - usb_handle_create(&h)               : handle gets filled (0x1d4d...)
  - usb_device_init(usb_handle)         : rv=0 ✅
  - usb_device_open(... vid=0x3474 ...)  CRASH reading 0x0000000000003474
                                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                        function dereferenced our uint16
                                        as a pointer → VID/PID are STRINGS

stream_win_OMNI.conf confirms PID/VID are stored as quoted hex strings
("0x4962", "0x3474"). The SDK takes them in the same form.

This script repeats the ladder using c_char_p for VID/PID, then tries
camera handle + open. Each successful step prints non-zero handles, so
we can see how far we get.

Run with TopView CLOSED:
    python tc001max_probe4.py
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import (POINTER, byref, c_char_p, c_int, c_int32, c_void_p)
from pathlib import Path


DEFAULT_TOPVIEW = Path(r"C:\Program Files\TOPDON\TopView")
VID = b"0x3474"
PID = b"0x4962"
SAME_ID = 0

DLL_LOAD_ORDER = [
    ("pthreadVC2.dll", "root"),
    ("libirparse.dll", "c001max"),
    ("libircmd.dll",   "c001max"),
    ("libirdvs.dll",   "c001max"),
    ("libircam.dll",   "c001max"),
]


def find_and_load(root: Path) -> dict[str, ctypes.CDLL]:
    sub = root / "dll" / "dll_c001max"
    paths = {}
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
    dlls = {}
    for name, _ in DLL_LOAD_ORDER:
        dlls[name] = ctypes.CDLL(str(paths[name]))
    return dlls


def get_addr(dll: ctypes.CDLL, sym: str) -> int | None:
    try:
        return ctypes.cast(getattr(dll, sym), c_void_p).value
    except AttributeError:
        return None


def call(label: str, fn, *args):
    try:
        rv = fn(*args)
        print(f"  rv={rv:<12d} {label}")
        return rv
    except Exception as e:
        print(f"  CRASH         {label} → {type(e).__name__}: {e}")
        return None


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TOPVIEW
    if not root.exists():
        print(f"❌ TopView root not found: {root}")
        return 1
    print(f"TopView root: {root}")
    dlls = find_and_load(root)
    print("DLLs loaded.\n")

    dvs = dlls["libirdvs.dll"]

    # --- camera_init ----------------------------------------------
    fn = ctypes.CFUNCTYPE(c_int)(get_addr(dvs, "irdvs_camera_init"))
    call("irdvs_camera_init()", fn)

    # --- USB layer -----------------------------------------------
    print("\n--- USB layer ---")
    usb_h = c_void_p(0)

    fn = ctypes.CFUNCTYPE(c_int, POINTER(c_void_p))(get_addr(dvs, "irdvs_usb_handle_create"))
    call(f"usb_handle_create(&h)  →  h=0x{usb_h.value or 0:x}", fn, byref(usb_h))
    print(f"           after: usb_h = 0x{usb_h.value or 0:x}")

    fn = ctypes.CFUNCTYPE(c_int, c_void_p)(get_addr(dvs, "irdvs_usb_device_init"))
    call("usb_device_init(usb_h)", fn, usb_h)

    # The key fix: VID/PID as STRINGS, not uint16
    usb_dev = c_void_p(0)
    fn = ctypes.CFUNCTYPE(
        c_int, c_void_p, c_char_p, c_char_p, c_int, POINTER(c_void_p)
    )(get_addr(dvs, "irdvs_usb_device_open"))
    call(
        f'usb_device_open(usb_h, vid="{VID.decode()}", pid="{PID.decode()}", '
        f'same={SAME_ID}, &dev)',
        fn, usb_h, VID, PID, SAME_ID, byref(usb_dev),
    )
    print(f"           after: usb_dev = 0x{usb_dev.value or 0:x}")

    # --- Camera layer -----------------------------------------------
    print("\n--- Camera layer ---")
    cam = c_void_p(0)

    if usb_dev.value:
        # try the "_with_exist_instance" first (since we have an instance)
        addr = get_addr(dvs, "irdvs_camera_handle_create_with_exist_instance")
        if addr is not None:
            fn = ctypes.CFUNCTYPE(c_int, c_void_p, POINTER(c_void_p))(addr)
            call(
                f"camera_handle_create_with_exist_instance(usb_dev, &cam)",
                fn, usb_dev, byref(cam),
            )
            print(f"           after: cam = 0x{cam.value or 0:x}")
    else:
        print("  usb_dev still NULL; skipping camera-handle creation")

    # --- try camera_open -----------------------------------------
    if cam.value:
        print("\n--- camera_open ---")
        addr = get_addr(dvs, "irdvs_camera_open")
        if addr is not None:
            # try: int open(void* cam)
            fn1 = ctypes.CFUNCTYPE(c_int, c_void_p)(addr)
            rv = call("camera_open(cam)  v1: int(cam)", fn1, cam)
            if rv != 0:
                # try: int open(void* cam, const char* vid, const char* pid, int same)
                fn2 = ctypes.CFUNCTYPE(c_int, c_void_p, c_char_p, c_char_p, c_int)(addr)
                call("camera_open(cam, vid, pid, same)  v2", fn2, cam, VID, PID, SAME_ID)

    # --- teardown ------------------------------------------------
    print("\n--- teardown ---")
    if cam.value:
        addr = get_addr(dvs, "irdvs_camera_handle_delete")
        if addr is not None:
            fn = ctypes.CFUNCTYPE(c_int, c_void_p)(addr)
            call("camera_handle_delete(cam)", fn, cam)
    if usb_dev.value:
        addr = get_addr(dvs, "irdvs_usb_device_close")
        if addr is not None:
            fn = ctypes.CFUNCTYPE(c_int, c_void_p)(addr)
            call("usb_device_close(dev)", fn, usb_dev)
    if usb_h.value:
        addr = get_addr(dvs, "irdvs_usb_device_release")
        if addr is not None:
            fn = ctypes.CFUNCTYPE(c_int, c_void_p)(addr)
            call("usb_device_release(usb_h)", fn, usb_h)
        addr = get_addr(dvs, "irdvs_usb_handle_delete")
        if addr is not None:
            fn = ctypes.CFUNCTYPE(c_int, c_void_p)(addr)
            call("usb_handle_delete(usb_h)", fn, usb_h)

    fn = ctypes.CFUNCTYPE(c_int)(get_addr(dvs, "irdvs_camera_release"))
    call("camera_release()", fn)

    print("\n✅ probe4 complete — paste full output back")
    return 0


if __name__ == "__main__":
    sys.exit(main())
