#!/usr/bin/env python3
"""Settings shows the installed Madeira and the free space. Read from the sources.

One UI (Nov 10): the old Settings status line (LibraryStatus, LibraryInfoLine) went with the old look,
and its switch env.MADEIRA_LIBRARY_INFO with it. The Settings tab's list (NewLookSettingsList) has a
Free space row with the other status rows and a Version row (BuildStamp.text, text you can copy).
"""
from pathlib import Path
import json, sys

root = Path(__file__).resolve().parents[2]
lib = (root / "app/Madeira/Library.swift").read_text(encoding="utf-8")
look = (root / "app/Madeira/NewLook.swift").read_text(encoding="utf-8")
cat = (root / "app/Madeira/ConfigCatalog.generated.swift").read_text(encoding="utf-8")
strings = json.loads((root / "app/Madeira/Localizable.xcstrings").read_text(encoding="utf-8"))["strings"]
ok = True


def check(what, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + what)
    ok &= bool(cond)


start = look.index("struct NewLookSettingsList: View {")
view = look[start:look.index("\n}\n", start)]
check("the old status line is gone", "LibraryInfoLine" not in lib + look and "struct LibraryStatus" not in lib)
check("Settings has a Free space row, read once when the list appears",
      'LabeledContent(L("Free space"), value: free.map { ByteCountFormatter.string(fromByteCount: $0, countStyle: .file) }' in view
      and "volumeAvailableCapacityForImportantUsage" in view and ".task {" in view)
check("Settings has a Version row with the build, in text you can copy",
      'LabeledContent(L("Version")) { Text(BuildStamp.text).textSelection(.enabled) }' in view)
check("the removed switch is read nowhere", "MADEIRA_LIBRARY_INFO" not in lib + look)
for key in ("Free space", "Version"):
    check(f'"{key}" is in the string catalog', key in strings)

print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
