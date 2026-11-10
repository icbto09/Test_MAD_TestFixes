#!/usr/bin/env python3
"""fex-allocwatch-tls: AllocWatch::Clear() must not touch implicit TLS in the ARM64EC module (xtajit64.dll).

StarCraft crashed in FEXCore::Utils::AllocWatch::Clear(), called after every DFE pass: CurrentThreadId() used
`static thread_local char Anchor`, which the ARM64EC compiler turns into `ldr x, [x18, #0x58]`
(TEB->ThreadLocalStoragePointer). On a thread started by a client SDK that pointer was NULL, so the read of
0x8 faulted. The WOW64 module already read TPIDRRO_EL0 instead.

Two source changes, both checked here by reading FEX/FEXCore/Source/Utils/AllocWatch.cpp:
  A. Clear() sets the disarm flag and returns before CurrentThreadId() when no watch is live.
  B. The TPIDRRO_EL0 branch of CurrentThreadId() is no longer excluded for ARCHITECTURE_arm64ec.
The compiled result (no [x18, #0x58] in AllocWatch::Clear) is checked separately with llvm-objdump; this is the
source check. Needs python3. FEX_ALLOCWATCH_SRC overrides the file path (a checkout without the FEX submodule).
"""
from pathlib import Path
import os, re, sys

root = Path(__file__).resolve().parents[2]
path = Path(os.environ.get('FEX_ALLOCWATCH_SRC') or root / 'FEX/FEXCore/Source/Utils/AllocWatch.cpp')
if not path.exists():
    sys.exit(f'FAIL: {path} not found (FEX submodule not checked out? set FEX_ALLOCWATCH_SRC)')
src = path.read_text()

# B: CurrentThreadId() picks the TPIDRRO_EL0 path on ARM64EC too.
m = re.search(r'uint64_t CurrentThreadId\(\) \{(.*?)\n  \}\n', src, re.S)
assert m, 'CurrentThreadId() not found'
body = m.group(1)
cond = re.search(r'^#if (.*)$', body, re.M)
assert cond, 'CurrentThreadId() has no #if'
assert 'FEX_IOS_HOST' in cond.group(1) and '_WIN32' in cond.group(1), cond.group(1)
assert 'arm64ec' not in cond.group(1), 'ARM64EC is still excluded from the TPIDRRO_EL0 path: ' + cond.group(1)
assert 'mrs %0, TPIDRRO_EL0' in body, 'TPIDRRO_EL0 read missing'
assert 'static thread_local char Anchor' in body.split('#else', 1)[1], 'non-Windows fallback must remain'
assert body.index('mrs %0, TPIDRRO_EL0') < body.index('#else'), 'TPIDRRO_EL0 must be the iOS-host branch'

# A: Clear() returns early before the thread lookup and the slot scan.
m = re.search(r'\nvoid Clear\(\) \{\n(.*?)\n\}\n', src, re.S)
assert m, 'Clear() not found'
clear = m.group(1)
early = re.search(r'if \(!LiveWatches\.load\(std::memory_order_relaxed\)\) \{\s*FEX_AllocWatch_Armed = 0;\s*return;\s*\}', clear)
assert early, 'Clear() lacks the early return when LiveWatches == 0'
assert early.start() < clear.index('CurrentThreadId()'), 'the early return must come before CurrentThreadId()'
assert early.start() < clear.index('for (auto& E : WatchTable)'), 'the early return must come before the slot scan'

# Behaviour otherwise unchanged: the per-thread retire and the final disarm are still there.
assert 'E.Owner == Self' in clear and 'LiveWatches.fetch_sub(Removed' in clear
assert clear.rstrip().endswith('FEX_AllocWatch_Armed = 0;\n  }'), 'final disarm-when-nothing-watched kept'

print('PASS: Clear() returns early with no live watch, and ARM64EC reads TPIDRRO_EL0 in CurrentThreadId()')
