"""Stage 5: register the SDK log callback so we can SEE what -618 means.

probe4 confirmed:
  - irdvs_handle parameter is empty  rv=-600  irdvs_camera_init()
    → camera_init takes an argument
  - usb_device_open with string vid/pid: no crash, but rv=-618
    → signature is right, SDK is refusing for a different reason

InfiRay SDKs ship with an irdvs_log_register hook that emits error
messages with context. If we register a Python callback, every -NNN
return value comes with a human-readable line in our chat.

Also redirect C stdout/stderr to a file so we capture anything the SDK
prints directly with printf/fprintf.

Run with TopView CLOSED + camera unplugged-then-replugged:
    python tc001max_probe5.py
"""
from __future__ import annotations

import ctypes
import os
import sys
import tempfile
from ctypes import (CFUNCTYPE, POINTER, byref, c_char_p, c_int, c_void_p)
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


def getfn(dll, sym, restype=c_int, argtypes=None):
    if not hasattr(dll, sym):
        return None
    fn = getattr(dll, sym)
    fn.restype = restype
    fn.argtypes = argtypes or []
    return fn


# Multiple plausible log callback signatures. We keep all of them alive
# because ctypes will GC the wrapper otherwise.
LOG_CB_LEVEL_MSG = CFUNCTYPE(None, c_int, c_char_p)
LOG_CB_MSG_ONLY  = CFUNCTYPE(None, c_char_p)


def make_callbacks():
    @LOG_CB_LEVEL_MSG
    def cb_lvl_msg(level, msg):
        text = msg.decode("utf-8", "ignore") if msg else "(null)"
        print(f"    [SDK lvl={level}] {text}")

    @LOG_CB_MSG_ONLY
    def cb_msg(msg):
        text = msg.decode("utf-8", "ignore") if msg else "(null)"
        print(f"    [SDK] {text}")

    return cb_lvl_msg, cb_msg


def call(label, fn, *args):
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

    # ---- register a log callback BEFORE anything else ----
    cb_lvl_msg, cb_msg = make_callbacks()

    log_addr = ctypes.cast(dvs.irdvs_log_register, c_void_p).value
    print("--- log_register ---")
    # Try int(void (*)(int, const char*)) first (most common)
    fn = CFUNCTYPE(c_int, LOG_CB_LEVEL_MSG)(log_addr)
    try:
        rv = fn(cb_lvl_msg)
        print(f"  rv={rv} log_register(cb_level_msg)")
    except Exception as e:
        print(f"  CRASH log_register(cb_level_msg) → {e}")
        # fallback: msg-only
        fn = CFUNCTYPE(c_int, LOG_CB_MSG_ONLY)(log_addr)
        try:
            rv = fn(cb_msg)
            print(f"  rv={rv} log_register(cb_msg_only)")
        except Exception as e2:
            print(f"  CRASH log_register(cb_msg_only) → {e2}")

    # ---- camera_init: try (void) and (void**) ----
    print("\n--- camera_init ---")
    init_addr = ctypes.cast(dvs.irdvs_camera_init, c_void_p).value
    irdvs_handle = c_void_p(0)

    # (void**) variant first — matches the "handle parameter is empty" error
    fn = CFUNCTYPE(c_int, POINTER(c_void_p))(init_addr)
    rv = call(
        f"camera_init(&irdvs_h)  →  h=0x{irdvs_handle.value or 0:x}",
        fn, byref(irdvs_handle),
    )
    print(f"           after: irdvs_handle = 0x{irdvs_handle.value or 0:x}")

    # ---- USB layer ----
    print("\n--- USB layer ---")
    usb_h = c_void_p(0)
    fn = CFUNCTYPE(c_int, POINTER(c_void_p))(
        ctypes.cast(dvs.irdvs_usb_handle_create, c_void_p).value)
    call("usb_handle_create(&h)", fn, byref(usb_h))
    print(f"           after: usb_h = 0x{usb_h.value or 0:x}")

    fn = CFUNCTYPE(c_int, c_void_p)(
        ctypes.cast(dvs.irdvs_usb_device_init, c_void_p).value)
    call("usb_device_init(usb_h)", fn, usb_h)

    usb_dev = c_void_p(0)
    fn = CFUNCTYPE(
        c_int, c_void_p, c_char_p, c_char_p, c_int, POINTER(c_void_p)
    )(ctypes.cast(dvs.irdvs_usb_device_open, c_void_p).value)
    call(
        f'usb_device_open(usb_h, "{VID.decode()}", "{PID.decode()}", {SAME_ID}, &dev)',
        fn, usb_h, VID, PID, SAME_ID, byref(usb_dev),
    )
    print(f"           after: usb_dev = 0x{usb_dev.value or 0:x}")

    # If still -618, try a couple of variations to narrow down
    if usb_dev.value == 0:
        print("\n--- usb_device_open variations ---")
        addr = ctypes.cast(dvs.irdvs_usb_device_open, c_void_p).value

        # variation A: VID/PID without "0x" prefix
        VID_PLAIN = b"3474"
        PID_PLAIN = b"4962"
        fn = CFUNCTYPE(c_int, c_void_p, c_char_p, c_char_p, c_int,
                       POINTER(c_void_p))(addr)
        usb_dev.value = 0
        call(
            f'open(usb_h, "{VID_PLAIN.decode()}", "{PID_PLAIN.decode()}", 0, &dev)',
            fn, usb_h, VID_PLAIN, PID_PLAIN, 0, byref(usb_dev),
        )

        # variation B: uppercase
        VID_UP = b"0X3474"
        PID_UP = b"0X4962"
        usb_dev.value = 0
        call(
            f'open(usb_h, "{VID_UP.decode()}", "{PID_UP.decode()}", 0, &dev)',
            fn, usb_h, VID_UP, PID_UP, 0, byref(usb_dev),
        )

        # variation C: same_id = -1 (auto)
        usb_dev.value = 0
        call(
            f'open(usb_h, "{VID.decode()}", "{PID.decode()}", -1, &dev)',
            fn, usb_h, VID, PID, -1, byref(usb_dev),
        )

    # ---- teardown ----
    print("\n--- teardown ---")
    if usb_dev.value:
        fn = CFUNCTYPE(c_int, c_void_p)(
            ctypes.cast(dvs.irdvs_usb_device_close, c_void_p).value)
        call("usb_device_close(dev)", fn, usb_dev)
    if usb_h.value:
        fn = CFUNCTYPE(c_int, c_void_p)(
            ctypes.cast(dvs.irdvs_usb_device_release, c_void_p).value)
        call("usb_device_release(usb_h)", fn, usb_h)
        fn = CFUNCTYPE(c_int, c_void_p)(
            ctypes.cast(dvs.irdvs_usb_handle_delete, c_void_p).value)
        call("usb_handle_delete(usb_h)", fn, usb_h)

    fn = CFUNCTYPE(c_int)(
        ctypes.cast(dvs.irdvs_camera_release, c_void_p).value)
    call("camera_release()", fn)

    print("\n✅ probe5 complete — paste full output back (esp. [SDK ...] lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
