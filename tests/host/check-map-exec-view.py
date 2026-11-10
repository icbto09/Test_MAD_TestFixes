#!/usr/bin/env python3
"""[map-exec-view] An executable view with no ArbitraryUserPointer is told to FEX (Nov 2026).

StarCraft from Battle.net: ClientSdk.dll maps its image section as plain data, protects
it PAGE_EXECUTE_READWRITE, unmaps it, then maps the same section again in pieces, the
.text with prot=0x20. Each map logged "[map-notify] SKIP (no ArbitraryUserPointer)", so
FEX never learned the .text is code, the first decode there was NOEXEC and the process
died with c0000005.

Source checks (wine/dlls/ntdll/signal_arm64ec.c): in notify_map_view_of_section, the
no-ArbitraryUserPointer branch sends the post-protect notification (pNotifyMemoryProtect,
the call an [exec-req] NtProtectVirtualMemory makes) when the view protection has an
execute bit; the log is capped at 16; env.MADEIRA_MAP_EXEC_VIEW = 0 turns it off
(default on); the branch still returns without NotifyMapViewOfSection, and the image
path below it is unchanged.
"""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[2]
src = (root / 'wine/dlls/ntdll/signal_arm64ec.c').read_text()

# The switch: read once, default on, only "0" turns it off.
m = re.search(r'static BOOL ios_map_exec_view_enabled\( void \)\n\{.*?\n\}\n', src, re.S)
assert m, 'ios_map_exec_view_enabled missing'
body = m.group(0)
assert 'L"MADEIRA_MAP_EXEC_VIEW"' in body
assert "buffer[0] == '0') ? 1 : 2;" in body
assert 'return mode == 2;' in body

# The notification lives inside the no-ArbitraryUserPointer branch of the map notify.
m = re.search(r'static void notify_map_view_of_section\(.*?\n\}\n', src, re.S)
assert m, 'notify_map_view_of_section missing'
fn = m.group(0)
a = fn.index('if (!NtCurrentTeb()->Tib.ArbitraryUserPointer)')
b = fn.index('if (NtQuerySection( handle, SectionImageInformation')
branch = fn[a:b]
assert 'PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY' in branch
assert '(protect & (' in branch, 'must test the view protection, not alloc'
assert 'ios_map_exec_view_enabled()' in branch
assert 'pNotifyMemoryProtect( addr, size, protect, TRUE, STATUS_SUCCESS );' in branch
assert 'if (n <= 16)' in branch
assert '[map-exec-view] #%d base=%p size=%p prot=%x' in branch
assert 'pNotifyMapViewOfSection' not in branch, 'the exec view must not take the image-map path'
assert branch.rstrip().endswith('return;\n    }'), 'the branch must still return'

# The image path (ArbitraryUserPointer set) still goes through NotifyMapViewOfSection.
rest = fn[b:]
assert 'status = pNotifyMapViewOfSection( NULL, addr, NULL, size, alloc, protect );' in rest
assert 'pNotifyMemoryProtect' not in rest

# The notification comes after the ArbitraryUserPointer test and only for execute views.
assert branch.index('(protect & (') < branch.index('pNotifyMemoryProtect( addr')

print('check-map-exec-view: ok')
