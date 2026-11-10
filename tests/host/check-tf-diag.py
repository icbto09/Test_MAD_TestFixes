#!/usr/bin/env python3
"""tf-diag: log-only diagnostic for the StarCraft single-step (TF) trap loop, in the ARM64EC module (xtajit64.dll).

StarCraft.exe+0xDE03 HLT -> c0000096, then ~30k single-step traps alternating between +0xAEAE and +0xC74C. Unknown:
does the game set TF again each time, or does FEX/Wine fail to clear TF on resume? FEX/Source/Windows/ARM64EC/Module.cpp
now logs three "[tf-diag]" lines and changes nothing else. This source check needs python3; FEX_MODULE_SRC overrides the
file path (a checkout without the FEX submodule).

Checked here:
  1. the three log strings exist (raise, resume, step-clear) and are emitted through LogMan::Msg::EFmt;
  2. one shared rate limiter: first 64 lines, then every 1000th, each line carrying the running count n;
  3. every log call sits behind that limiter (no unguarded "[tf-diag]" line);
  4. the pre-existing TF clear in RethrowGuestException is untouched (still clears RFLAG_TF_RAW_LOC, still sets Cpsr bit 21 off for SINGLE_STEP).
"""
from pathlib import Path
import os, re, sys

root = Path(__file__).resolve().parents[2]
path = Path(os.environ.get('FEX_MODULE_SRC') or root / 'FEX/Source/Windows/ARM64EC/Module.cpp')
if not path.exists():
    sys.exit(f'FAIL: {path} not found (FEX submodule not checked out? set FEX_MODULE_SRC)')
src = path.read_text()

RAISE = '[tf-diag] raise code={:#x} rip={:#x} ctxTF={} ctxSS={} liveTF={} n={}'
RESUME = '[tf-diag] resume rip={:#x} TF={} n={}'
CLEAR = '[tf-diag] step-clear rip={:#x} n={}'
for s in (RAISE, RESUME, CLEAR):
    assert src.count(s) == 1, f'log text must appear exactly once: {s}'
    assert re.search(r'LogMan::Msg::EFmt\(\s*"' + re.escape(s) + '"', src), f'not logged through LogMan::Msg::EFmt: {s}'

# 2. rate limiter: 64 lines, then every 1000th, shared counter.
m = re.search(r'static uint32_t TfDiagTick\(\) \{(.*?)\n\}', src, re.S)
assert m, 'TfDiagTick() not found'
body = m.group(1)
assert 'TfDiagCount.fetch_add(1' in body, 'running count missing'
assert re.search(r'N <= 64', body) and re.search(r'N % 1000\) == 0', body), 'rate limit must be first 64, then every 1000th'

# 3. every [tf-diag] line is inside an `if (const uint32_t N = TfDiagTick())`.
for s in (RAISE, RESUME, CLEAR):
    i = src.index(s)
    before = src[max(0, i - 400):i]
    assert 'if (const uint32_t N = TfDiagTick())' in before, f'log not behind the rate limiter: {s}'
assert src.count('TfDiagTick()') == 4, 'expected the definition plus three guarded uses'

# 4. behaviour unchanged where the diagnostic hooks in.
rg = src[src.index('static void RethrowGuestException'):]
rg = rg[:rg.index('Context.Pc = KiUserExceptionDispatcher;')]
assert 'EFlags &= ~(1 << FEXCore::X86State::RFLAG_TF_RAW_LOC);' in rg
assert 'Args->Context.Cpsr &= ~(1 << 21); // PSTATE.SS' in rg
assert 'CTX->SetFlagsFromCompactedEFLAGS(Thread, EFlags);' in rg

print('PASS: tf-diag logs raise/resume/step-clear through one rate limiter (64, then every 1000th) and changes no behaviour')
