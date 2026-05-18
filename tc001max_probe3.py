"""Stage 3: open the USB device first, then create a camera handle on top.

v2 crashed on the second call because we corrupted the SDK state. The
InfiRay export list strongly suggests a two-layer handle model:

  USB layer:    irdvs_usb_handle_create / _device_init / _device_open
  Camera layer: irdvs_camera_handle_create_with_exist_instance (uses USB inst)

So this script tries that ladder, one call at a time. Each call uses
ctypes' CFUNCTYPE so we can pick the signature per attempt. We stop the
moment any call crashes — that itself is a signal.

Run with TopView CLOSED:
    python tc001max_probe3.py
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import (POINTER, byref, c_int, c_uint, c_uint16, c_void_p)
from pathlib import Path


DEFAULT_TOPVIEW = Path(r"C:\Program Files\TOPDON\TopView")
VID = 0x3474
PID = 0x4962
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


def try_call(label: str, fn, *args):
    """Call fn(*args) wrapped in a guard. If the process dies here we'll see
    no further output, which itself tells us the signature is wrong."""
    try:
        rv = fn(*args)
        print(f"  rv={rv:<8} {label}")
        return rv
    except Exception as e:
        print(f"  CRASH    {label}  →  {type(e).__name__}: {e}")
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

    # --- camera_init (already known to return 0) -----------------
    init_addr = get_addr(dvs, "irdvs_camera_init")
    init = ctypes.CFUNCTYPE(c_int)(init_addr)
    try_call("irdvs_camera_init()", init)

    # --- USB layer ladder ----------------------------------------
    print("\n--- USB layer ---")

    # 1) irdvs_usb_handle_create — guess: int(void** out_handle)
    addr = get_addr(dvs, "irdvs_usb_handle_create")
    usb_handle = c_void_p(0)
    if addr is not None:
        fn = ctypes.CFUNCTYPE(c_int, POINTER(c_void_p))(addr)
        try_call(f"usb_handle_create(&h) → h=0x{usb_handle.value or 0:x}",
                 fn, byref(usb_handle))
        print(f"           after: usb_handle = 0x{usb_handle.value or 0:x}")
    else:
        print("  usb_handle_create missing")

    # 2) irdvs_usb_device_init — guess: int(void* usb_handle)
    addr = get_addr(dvs, "irdvs_usb_device_init")
    if addr is not None and usb_handle.value:
        fn = ctypes.CFUNCTYPE(c_int, c_void_p)(addr)
        try_call("usb_device_init(usb_handle)", fn, usb_handle)
    elif addr is not None:
        # try the void-version
        fn = ctypes.CFUNCTYPE(c_int)(addr)
        try_call("usb_device_init(void)", fn)
    else:
        print("  usb_device_init missing")

    # 3) irdvs_usb_device_open — guess: int(void* usb_h, uint16 vid, uint16 pid,
    #                                       int same_id, void** out_dev)
    addr = get_addr(dvs, "irdvs_usb_device_open")
    usb_dev = c_void_p(0)
    if addr is not None and usb_handle.value:
        fn = ctypes.CFUNCTYPE(
            c_int, c_void_p, c_uint16, c_uint16, c_int, POINTER(c_void_p)
        )(addr)
        try_call(
            f"usb_device_open(usb_h, vid={hex(VID)}, pid={hex(PID)}, "
            f"same={SAME_ID}, &dev)",
            fn, usb_handle, VID, PID, SAME_ID, byref(usb_dev),
        )
        print(f"           after: usb_dev = 0x{usb_dev.value or 0:x}")
    else:
        print("  usb_device_open missing or no usb_handle")

    # --- Camera layer --------------------------------------------
    print("\n--- Camera layer ---")
    cam = c_void_p(0)

    # irdvs_camera_handle_create_with_exist_instance(usb_dev, &cam)
    addr = get_addr(dvs, "irdvs_camera_handle_create_with_exist_instance")
    if addr is not None and (usb_dev.value or usb_handle.value):
        ref = usb_dev if usb_dev.value else usb_handle
        fn = ctypes.CFUNCTYPE(c_int, c_void_p, POINTER(c_void_p))(addr)
        try_call(
            f"camera_handle_create_with_exist_instance(0x{ref.value or 0:x}, &cam)",
            fn, ref, byref(cam),
        )
        print(f"           after: cam = 0x{cam.value or 0:x}")
    else:
        # fallback: irdvs_camera_handle_create(&cam)
        addr = get_addr(dvs, "irdvs_camera_handle_create")
        if addr is not None:
            fn = ctypes.CFUNCTYPE(c_int, POINTER(c_void_p))(addr)
            try_call("camera_handle_create(&cam)", fn, byref(cam))
            print(f"           after: cam = 0x{cam.value or 0:x}")
        else:
            print("  camera_handle_create missing")

    # --- teardown ------------------------------------------------
    print("\n--- teardown ---")
    if cam.value:
        addr = get_addr(dvs, "irdvs_camera_handle_delete")
        if addr is not None:
            fn = ctypes.CFUNCTYPE(c_int, c_void_p)(addr)
            try_call("camera_handle_delete(cam)", fn, cam)

    if usb_dev.value:
        addr = get_addr(dvs, "irdvs_usb_device_close")
        if addr is not None:
            fn = ctypes.CFUNCTYPE(c_int, c_void_p)(addr)
            try_call("usb_device_close(dev)", fn, usb_dev)

    if usb_handle.value:
        addr = get_addr(dvs, "irdvs_usb_handle_delete")
        if addr is not None:
            fn = ctypes.CFUNCTYPE(c_int, c_void_p)(addr)
            try_call("usb_handle_delete(h)", fn, usb_handle)

    addr = get_addr(dvs, "irdvs_camera_release")
    fn = ctypes.CFUNCTYPE(c_int)(addr)
    try_call("camera_release()", fn)

    print("\n✅ probe3 complete — paste the full output back")
    return 0


if __name__ == "__main__":
    sys.exit(main())
