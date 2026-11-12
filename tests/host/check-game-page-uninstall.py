#!/usr/bin/env python3
"""Uninstall on a Steam game's own page (SteamUninstallSection), not only on its Steam page.
Read from the sources.

1. Game details shows the section for a Steam game, before the always-last setup section,
   and closes the page without saving once the game is uninstalled.
2. Same rule as the Steam page's button: only a game Madeira downloaded (Dock's own library
   folder), not while a download runs; the same question before anything is deleted.
"""
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
lib = (root / "app/Madeira/Library.swift").read_text(encoding="utf-8")
steam = (root / "app/Madeira/SteamGames.swift").read_text(encoding="utf-8")
ok = True


def check(what, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + what)
    ok &= bool(cond)


# (game-actions-advanced) The setup/help/reset actions moved to the game's Advanced page. One UI
# (Nov 10): the game's page is Apple's list (MARK: - New look game page); it decides as
# SteamUninstallSection does, and Uninstall is its last section, on its own.
page = lib[lib.index("// MARK: - New look game page"):]
form = page[page.index("@ViewBuilder private var lookHelp: some View {"):page.index("private func lookLabel(")]
use = 'Button(role: .destructive) { confirmSteamUninstall = true } label: {'
check("the game's page shows it for a Steam game, as its last section",
      use in form and "if steamUninstallable != nil {" in form
      and "SteamInstallPaths.isManaged(library: installed.library)" in lib and "steam.downloads[appID] == nil" in lib
      and 'Button("Share Setup"' not in page and "Section {" not in form[form.index(use):])
check("the game's page asks first, then uninstalls and closes",
      lib.index("isPresented: $confirmSteamUninstall") < lib.index("if let installed = steamUninstallable { steam.uninstall(installed) }")
      < lib.index("leaving = true; closePage()", lib.index("if let installed = steamUninstallable")))
check("the controller's B closes the question (it is Apple's own popup)",
      "NewLookPopupLayer(shown: confirmSteamUninstall) { confirmSteamUninstall = false }" in form)
start = steam.index("struct SteamUninstallSection: View {")
view = steam[start:steam.index("\n}\n", start)]
check("only a game Madeira manages, with no download running",
      "SteamInstallPaths.isManaged(library: $0.library)" in view and "managed, steam.downloads[appID] == nil" in view)
check("asks first, then uninstalls and closes the page",
      'confirmationDialog("Uninstall \\(entry.title)? Its downloaded files are deleted from where it is installed.' in view
      and view.index("steam.uninstall(installed)") < view.index("uninstalled()"))
check("the Steam page keeps its own button", 'Button("Uninstall", role: .destructive) { confirmUninstall = true }' in steam[steam.index("struct SteamEntrySection: View {"):])

print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
