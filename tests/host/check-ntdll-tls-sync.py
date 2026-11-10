#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 ft7t8drgwf-wq
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""The ARM64EC ntdll.dll in the bundle must carry the loader's TLS index sync.

Wine 694442e4 ("ntdll ARM64EC: sync the TLS index into the iOS JIT copy")
writes each DLL's TLS slot into the JIT-pool copy that iOS executes. An
ntdll.dll without it leaves every DLL's index at 0, so a DLL with TLS that is
loaded later reads the main program's TLS block. In 0.2.0 that is DXMT's x64
d3d9.dll: Valve's client loads it inside dockhost.exe right after sign-in,
it crashes, and the starting screen waits forever for the license.

The fix prints "[tls-jit-sync]" from alloc_tls_slot, so the string is in any
ntdll.dll built with it. This checks the copy in app/Madeira (what a build
that does not rebuild the runtime ships) and, given a path, a built bundle's.
"""
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
MARKER = b"[tls-jit-sync]"
paths = [Path(p) for p in sys.argv[1:]] or [root / "app/Madeira/arm64ec-windows/ntdll.dll"]
source = root / "wine/dlls/ntdll/loader.c"
if source.is_file() and MARKER.decode() not in source.read_text(errors="replace"):
    print("SKIP: the wine pin has no TLS index sync")
    sys.exit(0)
failed = False
for path in paths:
    if MARKER not in path.read_bytes():
        print(f"FAIL: {path} has no TLS index sync (wine 694442e4); rebuild it with build/wine-pe/build-ntdll.sh")
        failed = True
    else:
        print(f"ok   {path.name}: TLS index sync present")
sys.exit(1 if failed else 0)
