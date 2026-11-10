#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""build/fex-patches/0002: a code invalidation that frees FEX's own memory (call-ret stack reset,
lookup-cache pages, a released code buffer) must not re-enter the invalidation through Wine's memory
notifications on the same thread: that took CodeBufferListLock twice and parked the thread for good
(.NET games: Stardew Valley, Slay the Spire 2 on 0.2.0; [inval-nested] "invalidate" from
InvalidateAlignedInterval, then [fexlock] STUCK with the owner waiting on CTX+0x530).

Checks the patch text (the mark in InvalidateIntervalInternalLocked and the three skips), that it
applies on the FEX checkout after 0001 (or is applied), and that both shipped emulator modules were
built with it (their [inval-own-mem] log string).
"""
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / 'build/fex-patches/0002-windows-skip-own-memory-notifications-during-invalidation.patch'
failures = 0

def check(cond, text):
    global failures
    print(('PASS: ' if cond else 'FAIL: ') + text)
    if not cond: failures += 1

check(PATCH.exists(), 'patch 0002 is in build/fex-patches')
text = PATCH.read_text(encoding='utf-8', errors='replace') if PATCH.exists() else ''
check('+  } Scope {InvalidatingThread};' in text,
      'InvalidateIntervalInternalLocked marks this thread as invalidating for its whole body')
check(text.count('+  if (InsideOwnInvalidation()) {') == 3,
      'HandleMemoryProtectionNotification, InvalidateContainingSection and InvalidateAlignedInterval skip own-memory notifications')
check('return Thread && Thread == OwnedSharedMutex::Self();' in text,
      'the skip is for the invalidating thread only; other threads\' notifications go through')
check('+  ReportOwnInvalidationSkips();' in text, 'skips are reported from HandleImageMap, outside the locks')

fex = ROOT / 'FEX'
if (fex / 'Source/Windows/Common/InvalidationTracker.cpp').exists():
    tracker = (fex / 'Source/Windows/Common/InvalidationTracker.cpp').read_text(encoding='utf-8', errors='replace')
    if 'InsideOwnInvalidation()' in tracker:
        rev = subprocess.run(['git', '-C', str(fex), 'apply', '--reverse', '--check', str(PATCH)], capture_output=True)
        check(rev.returncode == 0, 'the FEX working tree has patch 0002 applied as written')
    else:
        print('SKIP: patch 0002 not applied to this FEX checkout (build/fex-patches/apply.sh applies 0001 then 0002)')
else:
    print('SKIP: the FEX submodule is not checked out here')

for rel in ('app/Madeira/arm64ec-windows/xtajit64.dll', 'app/Madeira/aarch64-windows/xtajit.dll'):
    data = (ROOT / rel).read_bytes()
    check(b'[inval-own-mem]' in data, f'{rel} was built with patch 0002')

if failures:
    print(f'check-fex-own-free-skip: {failures} failure(s)')
    sys.exit(1)
print('check-fex-own-free-skip: OK')
