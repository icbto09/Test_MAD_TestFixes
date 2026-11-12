#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 125hz
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""The stores' game sections (app/Madeira/SteamGames.swift, NewLook.swift), on the host.

One UI (Nov 10): the old sectioned library page (Steam, the store sections, Other games, the store
tabs, Group by and the zoomable grid) went with the old look. Each store's own section is now the
content of that store's page on the Stores tab, and the games you added are the Other games page.
Source checks: every store's page shows its section; Other games (Add a Game File, the empty text,
the grid); the Steam section (sign-in card, downloading on top, Not installed, the installed games
folded under it, its texts); pull to refresh; the log line.
The rules behind the groups and the sort are compiled and run by check-steam-games.py.
"""
from pathlib import Path
import re, sys

root = Path(__file__).resolve().parents[2]
app = root / 'app/Madeira'
failures = 0


def require(condition, label):
    global failures
    print(('PASS: ' if condition else 'FAIL: ') + label)
    if not condition:
        failures += 1


def between(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


library = (app / 'Library.swift').read_text()
games = (app / 'SteamGames.swift').read_text()
look = (app / 'NewLook.swift').read_text()
steam_docs = (root / 'docs/STEAM_LIBRARY.md').read_text()

view = between(library, 'struct LibraryView: View {', 'struct ExecutableBrowser: View {')
store_page = between(look, 'struct NewLookStorePage: View {', 'struct NewLookOverlays: ViewModifier {')
section = between(games, 'struct SteamGamesSection: View {', 'struct SteamSignInCard: View {')
body = between(section, '    var body: some View {', '    private func cell(')

# ------------------------------------------------------------------ a store's page
content = between(store_page, '@ViewBuilder private var content: some View {', '    /// Other games: the games you added')
require('case .steam: SteamGamesSection(search: "", layout: "cards", width: width, part: .all, open: open)' in content
        and all(f'case .{case}: {name}GamesSection(search: "", layout: "cards", width: width, open: open)' in content
                for case, name in (('epic', 'Epic'), ('gog', 'GOG'), ('itch', 'Itch'), ('ea', 'EA')))
        and 'case .other: otherGames' in content,
        "a store's page shows that store's own section; Other games has its own list")
require('NewLookScrollPage(refresh: { await SteamGamesSection.refresh() }) { width in\n                NewLookStorePage(store: store,' in library
        and 'NewLookScrollPage(refresh: { await SteamGamesSection.refresh() }, top: lookTop[.library, default: 0])' in library,
        "pull down on the Library and on a store's page refreshes the stores")

# ------------------------------------------------------------------ Other games
others = between(store_page, '    private var otherGames: some View {', '\n}\n')
require('NewLookSheetButton(id: "og-add", title: L("Add a Game File"), symbol: "plus", filled: true, action: add)' in others,
        'Other games: Add a Game File opens the executable browser')
require('"Copy a game\'s folder into Madeira › wine › drive_c with the Files app, then tap Add a Game File and choose its .exe."' in others
        and others.index('if games.isEmpty {') < others.index('LazyVGrid('), 'Other games: the empty text, else the grid of covers')
require('readyGames.all.filter { $0.id.hasPrefix(NewLookStore.other.prefix) }' in others
        and '.padItem("og-" + game.id, cornerRadius: 16, grid: "other") { open(game.entry) }' in others,
        "Other games: the games you added, each opening its page; the controller's highlight walks the grid")
added = between(look, '@MainActor static func added() -> [LibraryEntry] {', '\n    }\n')
require('entry.desktop != true' in added and 'entry.steamAppID == nil' in added and 'entry.listedInLibrary' in added,
        'Other games: the games you added (no store game, no desktop)')

# ------------------------------------------------------------------ Steam and Not installed
require('LibrarySectionHeader(title: "Steam", count: installed.count,' in body, 'Steam: the title with the installed count')
require('if steam.refreshing { ProgressView().accessibilityLabel("Refreshing Steam library") }' in body,
        'Steam: a progress indicator while the library refreshes')
require('@AppStorage("madeiraSteamShowUninstalled") private var showUninstalled = true' in section
        and '@AppStorage("madeiraNewLookSteamShowInstalled") private var showInstalled = false' in section,
        'Steam: remembered states (Not installed open, the installed games folded away at first)')
require('static var collapsible: Bool { false }' in section, "a store's page always shows its games: the titles do not collapse")
order = [body.index('LibrarySectionHeader(title: "Steam"'), body.index('SteamSignInCard { showSignIn = true }'),
         body.index('LibraryCells(items: top, layout: layout, width: width)'),
         body.index('"Pull down to load your Steam library."'), body.index('Text("Not installed").font(.headline)'),
         body.index('LibraryCells(items: groups.notInstalled, layout: layout, width: width)')]
require(order == sorted(order), 'Steam order: title, sign-in, downloading, empty text, Not installed')
require('let fold = part == .all' in body and 'let top = fold ? groups.downloading : groups.downloading + installed' in body,
        "Steam's page: what is downloading on top, the installed games folded below (the Library tab has them)")
require('"No Windows games were found in this Steam library."' in body, 'Steam: empty-library text')
require('} else if signedIn && !steam.refreshing && groups.notInstalled.isEmpty && installed.isEmpty && search.isEmpty {' in body,
        'Steam: the empty text only when signed in, loaded, nothing owned to install and no search')
require('if part != .installed && signedIn && !groups.notInstalled.isEmpty {' in body and 'if showUninstalled {' in body
        and '.accessibilityValue(showUninstalled ? "Shown" : "Hidden")' in body,
        'Not installed: signed in, folds on its own')
require('let items = SteamGamesRules.items(installed: model.games, owned: owned, search: search)' in body and
        'SteamGamesRules.groups(items, downloading: Set(steam.downloads.keys))' in body and
        'SteamGamesRules.sorted(groups.installed, by: sort, recorded: recorded)' in body,
        'Steam: the groups and the order of the installed games')
card = between(games, 'struct SteamSignInCard: View {', '// MARK: - Artwork')
require('"Sign in to Steam"' in card and '"See your Steam games here and install them without leaving Madeira."' in card,
        'the sign-in card')
require('SteamGamesSection.shown' in view and '[library-sections] native-steam=' in view, 'log line [library-sections]')
require(re.search(r'\[library-sections\][^"]*\\\((?!SteamOwnedLibrary\.enabled|SteamGamesSection\.)', view) is None,
        'the log line has flags only')

# ------------------------------------------------------------------ docs
require('Pull down' in steam_docs, 'docs/STEAM_LIBRARY.md: pull down to refresh')

if failures:
    print(f'check-library-sections: {failures} FAILED')
    sys.exit(1)
print('check-library-sections: PASS')
