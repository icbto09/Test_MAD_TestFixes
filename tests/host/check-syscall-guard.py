#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""[syscall-guard] a guard page hit inside a system call's own __TRY (NtReadVirtualMemory's memmove over the process's
own memory) is declined by the Mach exception thread, so bus_handler's [syscall-fault] fails the call, instead of a
guest exception being pushed onto the kernel stack ("Exception frame is not in stack limits", exit 31; The Binding of
Isaac: Rebirth on Test 8) (build/ntdll-unix/signal_arm64_ios.c).

Static anchors only: the switch, the guard-only scope, the guest-pc test matching the gate, the jmp_buf read through
mach_vm_read_overwrite, the call site between the page machinery and `goto dispatch`, and the capped log line.
"""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
src = (ROOT / 'build/ntdll-unix/signal_arm64_ios.c').read_text(encoding='utf-8', errors='replace')
failures = 0

def check(cond, text):
    global failures
    print(('PASS: ' if cond else 'FAIL: ') + text)
    if not cond: failures += 1

start = src.find('static int ios_mach_guard_in_syscall_try(')
check(start >= 0, 'the helper exists')
helper = src[start:]
helper = helper[:helper.index('\n}\n')] if start >= 0 else ''
check(start >= 0 and start < src.find('static int ios_mach_deliver_guest_exception_inner('),
      'the helper is defined before the Mach delivery function that calls it')
check('getenv( "MADEIRA_GUARD_SYSCALL_FAULT" );' in helper and "enabled = !(e && e[0] == '0');" in helper
      and 'if (!enabled) return 0;' in helper,
      'on unless MADEIRA_GUARD_SYSCALL_FAULT=0')
check('if (st != STATUS_GUARD_PAGE_VIOLATION) return 0;' in helper,
      'only a guard-page violation is declined; STACK_OVERFLOW and the rest dispatch as before')

gate_terms = ['(rxb && pc >= rxb && pc < rxb + ', 'ios_jit_low_contains( (uintptr_t)pc )',
              'pc < 0x100000000ULL', '(pc >= 0x7000000000ULL && pc < 0x7400000000ULL)']
check(all(t in helper for t in gate_terms), 'guest-side pcs (pool, pool-low, below 4 GB, guest VA band) are never declined')
inner = src[src.index('static int ios_mach_deliver_guest_exception_inner('):]
gate = inner[inner.index('/* only claim faults in plausibly GUEST-side execution:'):]
gate = gate[:gate.index('return 0;')]
check(all(t in gate for t in gate_terms[1:]), 'the helper\'s guest test still matches the gate after the page machinery')

check('td = (struct ntdll_thread_data *)&((TEB *)teb_addr)->GdiTebBatch;' in helper
      and re.search(r'mach_vm_read_overwrite\( mach_task_self\(\), \(mach_vm_address_t\)\(uintptr_t\)&td->jmp_buf, sizeof\(jb\),', helper)
      and '|| got != sizeof(jb) || !jb)' in helper,
      'the faulting thread\'s jmp_buf is read without touching its memory directly; no __TRY means no decline')
check('"[syscall-guard] a guard page at 0x%llx was hit inside a system call with a __TRY' in helper and 'said < 16' in helper,
      'one capped [syscall-guard] line per hit, 16 at most')

site = re.search(r'st = ios_virtual_handle_fault_for_thread\( &rec, teb \);.*?if \(st != STATUS_ACCESS_VIOLATION\)\s*\{\s*'
                 r'/\*[^*]*\*/\s*if \(ios_mach_guard_in_syscall_try\( pc, rxb, ios_jit_pool_size_global, \(uintptr_t\)teb, st, fault_addr \)\)\s*'
                 r'return 0;\s*goto dispatch;\s*\}', inner, re.S)
check(site is not None, 'the call sits between the page machinery and `goto dispatch`, and declines with return 0')
check('if (st != STATUS_ACCESS_VIOLATION) goto dispatch;' not in src, 'the old unconditional guard dispatch is gone')

bsd = src[src.index('static int ios_bus_syscall_fault('):]
bsd = bsd[:bsd.index('\n}\n')]
check('ntdll_get_thread_data()->jmp_buf' in bsd and 'handle_syscall_fault( ctx, rec )' in bsd,
      'the BSD side that takes the declined fault still returns to the __EXCEPT block')

print('\n%s' % ('All checks passed.' if not failures else '%d check(s) FAILED.' % failures))
sys.exit(1 if failures else 0)
