#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""build/fex-patches/0003 [flush-own-lock], from Test 8 Get Help logs (PvZ Fusion with MelonLoader,
2026-11-10): the game froze 24 s and 100 s in. One thread write-owned CodeInvalidationMutex (taken in
LockCodeInvalidationUnlessHeld) and waited for ThreadCreationMutex (xtajit64.dll+0x42c848); the other
held ThreadCreationMutex (ResetToConsistentStateImpl's write-fault path) and waited for
CodeInvalidationMutex.

The way in: a block delinker inside LookupCache::InvalidateRange flushes FEX's own code with
NtFlushInstructionCache (JIT.cpp IOSFlushOneInstr); wine's EC wrapper calls
BTCpu64FlushInstructionCache, which took ThreadCreationMutex. With the patch, a flush from a thread
that holds the code invalidation lock (write, or a shared emission hold) returns before either lock.
Off: env.MADEIRA_FLUSH_OWN_LOCK = 0.

Checks the patch text, the path it is about (JIT.cpp and wine's EC wrapper), that it applies on the
FEX checkout after 0001 and 0002 (or is applied), and that the shipped xtajit64.dll was built with it.
"""
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / 'build/fex-patches/0003-windows-skip-own-code-flushes-under-the-invalidation-lock.patch'
failures = 0


def check(cond, text):
    global failures
    print(('PASS: ' if cond else 'FAIL: ') + text)
    if not cond:
        failures += 1


def added_body(text, head):
    """The added lines of one function in the patch, from its head to its closing brace."""
    lines = [l[1:] for l in text.splitlines() if l.startswith(('+', ' ')) and not l.startswith('+++')]
    src = '\n'.join(lines) + '\n'
    i = src.find(head)
    if i < 0:
        return ''
    return src[i:src.find('\n}\n', i) + 3]


check(PATCH.exists(), 'patch 0003 is in build/fex-patches')
text = PATCH.read_text(encoding='utf-8', errors='replace') if PATCH.exists() else ''
guard = added_body(text, 'static bool IosFlushUnderOwnLock() {')
check('IosHeldExclusiveByThisThread()' in guard and 'IosEmissionLocksHeldBySelf()' in guard,
      'the guard looks at a write hold and at a shared emission hold')
check(guard != '' and 'ThreadCreationMutex' not in guard and 'InvalidateAlignedInterval' not in guard and 'LogMan' not in guard,
      'the guard takes no lock, invalidates nothing and logs nothing')
check('+    const char* V = getenv("MADEIRA_FLUSH_OWN_LOCK");' in text, 'off switch env.MADEIRA_FLUSH_OWN_LOCK = 0')
for name in ('void FlushInstructionCacheHeavy(const void* Address, SIZE_T Size) {',
             'void BTCpu64FlushInstructionCache(const void* Address, SIZE_T Size) {'):
    b = added_body(text, name)
    g = b.find('if (IosFlushUnderOwnLock()) {')
    t = b.find('std::scoped_lock Lock(ThreadCreationMutex);')
    check(g > 0 and t > g, name.split('(')[0][5:] + ': the guard comes before ThreadCreationMutex')
check('[flush-own-lock]' in text, 'marker [flush-own-lock] in the patch')

# The path the patch is about still exists.
jit = (ROOT / 'FEX/FEXCore/Source/Interface/Core/JIT/JIT.cpp')
if jit.exists():
    check('NtFlushInstructionCache(reinterpret_cast<void*>(~0ull), RXAddr, 4);' in jit.read_text(encoding='utf-8', errors='replace'),
          "JIT.cpp's delinker flush goes through NtFlushInstructionCache")
ec = ROOT / 'wine/dlls/ntdll/signal_arm64ec.c'
if ec.exists():
    src = ec.read_text(encoding='utf-8', errors='replace')
    i = src.find('NTSTATUS SYSCALL_API NtFlushInstructionCache(')
    check(i >= 0 and 'pBTCpu64FlushInstructionCache( addr, size );' in src[i:i + 600],
          "wine's EC NtFlushInstructionCache calls BTCpu64FlushInstructionCache")

fex = ROOT / 'FEX'
mod = fex / 'Source/Windows/ARM64EC/Module.cpp'
if mod.exists():
    if 'IosFlushUnderOwnLock' in mod.read_text(encoding='utf-8', errors='replace'):
        rev = subprocess.run(['git', '-C', str(fex), 'apply', '--reverse', '--check', str(PATCH)], capture_output=True)
        check(rev.returncode == 0, 'the FEX working tree has patch 0003 applied as written')
    else:
        print('SKIP: patch 0003 not applied to this FEX checkout (build/fex-patches/apply.sh applies 0001, 0002, 0003)')
else:
    print('SKIP: the FEX submodule is not checked out here')

dll = ROOT / 'app/Madeira/arm64ec-windows/xtajit64.dll'
if dll.exists():
    check(b'MADEIRA_FLUSH_OWN_LOCK' in dll.read_bytes(), f'{dll.relative_to(ROOT)} was built with patch 0003 (rebuild FEX ARM64EC)')

if failures:
    print(f'check-flush-own-lock: {failures} failure(s)')
    sys.exit(1)
print('check-flush-own-lock: OK')
