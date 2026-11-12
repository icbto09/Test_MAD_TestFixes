#!/usr/bin/env python3
"""Madeira's one UI (NewLook.swift + PadHighlight.swift), on the host.

Cameron, Nov 9: the approved mock-up built into the app behind one switch. Nov 10 ("i don't want a
toggle to flip i just want our new ui ux to be the structure and ui"): the switch and the old look
are gone, and the screens are Apple's own parts (the Apple rulebook, reference/apple-design-rulebook.md):
Apple's tab bar, a page stack in every tab, Apple's grouped lists, buttons, colors and popups. The
one custom part is the controller's highlight (PadHighlight), because an iPhone gives a controller
no focus.

Source checks only (no Swift compiler here); the PC's typecheck and the build compile it.
"""
from pathlib import Path
import json, re, struct, sys

root = Path(__file__).resolve().parents[2]
app = root / 'app/Madeira'
failures = 0


def check(condition, label):
    global failures
    print(('PASS: ' if condition else 'FAIL: ') + label)
    if not condition:
        failures += 1


look = (app / 'NewLook.swift').read_text(encoding='utf-8')
pad = (app / 'PadHighlight.swift').read_text(encoding='utf-8')
library = (app / 'Library.swift').read_text(encoding='utf-8')
pages = (app / 'SettingsPages.swift').read_text(encoding='utf-8')
project = (root / 'app/Madeira.xcodeproj/project.pbxproj').read_text(encoding='utf-8')
catalog = json.loads((app / 'Localizable.xcstrings').read_text(encoding='utf-8'))['strings']

# 1. In the app.
for ident, name in [('A1F00A01', 'NewLook.swift'), ('A1F00A02', 'PadHighlight.swift')]:
    check(project.count(f'{ident} /* {name} in Sources */') == 2 and project.count(f'A2{ident[2:]} /* {name} */') == 3,
          f'{name} is in the app target')
check(project.count('B1F00A03 /* MadeiraIsland.png in Resources */') == 2 and project.count('B2F00A03 /* MadeiraIsland.png */') == 3,
      'the island picture is copied into the app')
png = (app / 'MadeiraIsland.png').read_bytes()
check(png[:8] == b'\x89PNG\r\n\x1a\n' and struct.unpack('>II', png[16:24]) == (2000, 1000) and png[25] == 6,
      'the island is the 2000x1000 cut-out with transparency (Cameron: "that\'s perfect")')
check('Bundle.main.url(forResource: "MadeiraIsland", withExtension: "png")' in look, 'the background loads it by that name')
check('LibrarySidebar' not in project and not (app / 'LibrarySidebar.swift').exists(), "Wave 8's store sidebar is gone")
check('struct SettingsSplit' not in pages and 'SettingsSplit(' not in library, "and its iPad Settings split")

# 2. One UI: no switch, no old look.
app_swift = ''.join(f.read_text(encoding='utf-8') for f in sorted(app.glob('*.swift')) if f.name != 'ConfigCatalog.generated.swift')
check('MADEIRA_NEW_LOOK"' not in app_swift and 'NewLook.enabled' not in app_swift and 'NewLook.allowed' not in app_swift
      and 'Toggle("New look"' not in app_swift, 'no New look switch anywhere (no toggle, no env.MADEIRA_NEW_LOOK)')
check('var body: some View {\n        // Apple\'s tab bar with a page stack in every tab (newLookBody, below).\n        newLookBody\n' in library,
      'the library is the tab view, with no other layout behind it')
for gone in ['MenuPad.swift', 'GlassSkin.swift', 'LibraryGridPage.swift', 'LibraryGridLevels.swift']:
    check(not (app / gone).exists() and gone not in project, f'{gone} is gone from the app and the Xcode project')
check('LiquidMetalSetting' not in app_swift and 'MADEIRA_LIQUID_METAL' not in app_swift and 'MADEIRA_LIBRARY_AMBIENT' not in app_swift,
      'liquid metal and the ambient glow are gone')
check('static var enabled: Bool { MadeiraConfig.flag("MADEIRA_NEW_LOOK_PAD") }' in pad,
      "the controller's highlight is on; env.MADEIRA_NEW_LOOK_PAD = 0 turns it off")

# 3. The controller (Cameron's map).
controller = library[library.index('final class LibraryController'):library.index('enum FrontendChoice')]
check('(0x4000, "play")' in controller, 'X is sent as play')
handle = pad[pad.index('    func handle(_ command: String) {'):pad.index('    // MARK: Touch')]
check('case "accept":' in handle and 'action.send((focus, .press))' in handle, 'A selects')
check('case "back":\n            if let back = top.back { back() } else if layers.count == 1 { rootBack?() }' in handle, 'B: back, cancel or stop, whatever the layer says')
check('case "play":' in handle and 'item.play { action.send((focus, .play)) }' in handle and 'else { top.play?() }' in handle,
      'X: play or install the highlighted game, or the page\'s game')
check('case "add", "search":\n            if onTabPage { search?() }' in handle, 'Y: search (from a tab, or a page pushed in it)')
check('case "previous", "next":' in handle and 'if onTabPage { tabs?(command == "next" ? 1 : -1) }' in handle, 'LB/RB: tabs')
check('case "pageUp", "pageDown":' in handle and 'jump(down: command == "pageDown")' in handle, 'LT/RT: a page up or down')
check('case "menu":' in handle and 'item.menu { show(); action.send((focus, .menu)) }' in handle, 'Menu: the game\'s options')
check('if moves.contains(command), show() { return }' in handle, 'the first press only shows the highlight')
check('!model.menu else { return }' in handle and 'model.current == nil || model.startingScreen' in handle,
      'in a session only the starting screen is Madeira\'s, never under the Session menu')
check('window.addGestureRecognizer(PadTouchWatch { PadHighlight.shared.hide() })' in pad, 'touch hides the highlight')
check('GamepadEventClaim.install(on: window)' in pad, "iOS's own focus never gets the pad")
pop = pad[pad.index('    func pop(_ name: String'):pad.index('    /// A tab became the root page')]
check('layers.remove(at: i)' in pop and 'guard wasTop else {' in pop and 'returnTo' in pop
      and "if let back, items[back]?.layer == top.name { move(to: back, scroll: true) }" in pop,
      'Back restores the highlight; closing a layer under another leaves the top one alone (unless its row is on top again)')

# 4. Sheets trap focus and start on the safe choice.
check('.padLayer("options"' not in library + look
      and 'Button { open(game.entry) } label: { Label("Game Page", systemImage: "info.circle") }' in look,
      "a cover's options are Apple's own context menu (touch and hold); the controller's Menu opens the game's page")
check('.padLayer("sheet", back: { dismiss() }, accept: accept)' in pad, 'store sheets: B closes, A installs or opens')
check('if shown { Color.clear.frame(width: 0, height: 0).padLayer("popup", back: close) }' in look,
      "while one of Apple's popups is up, B closes it and nothing behind it takes the controller")
check('if command == "accept", let accept = top.accept, !items.values.contains(where: { $0.layer == top.name })' in handle,
      'A on a sheet with nothing to highlight runs its own action')
check('.padLayer("get-help", back: nil)' in (app / 'GetHelpView.swift').read_text(encoding='utf-8'), 'Get Help keeps its own A and B')
check(".filter { $0.value.layer == layer" in pad and "items[$0]?.layer == top.name" in pad, 'the highlight never leaves the top layer')

# 5. The Library and the game page.
check('LibraryReadyGame.all(search: "")' in look and 'static func all(search: String) -> [LibraryReadyGame]' in look,
      'the Library lists every installed game, last played first')
check('struct NewLookTabBar' not in look and 'case library, stores, downloads, settings, search' in look,
      "tabs: Library, Stores, Downloads, Settings and Search, on Apple's tab bar only (the game page has no copy of it)")
check('lookOpenGame(entry)' in library and 'case .game(let id, let tab, let depth):' in library
      and 'fullScreenCover(item: $selected' not in library,
      "the game page is pushed inside its tab like any iPhone page (system Back, swipe, tab bar stays)")
check("withTransaction(instant) { path.wrappedValue.append(route) }" in library and 'autoPlayIfAsked()' in library
      and 'DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { start() }' not in library,
      'X on a cover: the page opens without the slide and Play starts once it is laid out (no timer)')
detail = library[library.index('extension LibraryDetail {'):library.index('// MARK: - New look: the starting screen')]
play_style = look[look.index('struct LookPlayStyle'):look.index('struct LookArtButtonStyle')]
check(detail.count('LookPlayStyle(') == 1 and 'content.buttonStyle(.borderedProminent).buttonBorderShape(.capsule).controlSize(.large)' in play_style
      and 'filled: true' not in detail and '.borderedProminent' not in detail
      and '"gp-play"' in detail, "Play is the only filled button on the game page, and it is Apple's prominent button")
check('.buttonStyle(.glassProminent)' in play_style and 'overArt, !reduceTransparency' in play_style,
      'glass only over cover art (the banner), and never with Reduce Transparency on')
helpers = detail[detail.index('@ViewBuilder private var lookHelp'):]
check(helpers.index('"gp-help"') < helpers.index('"gp-uninstall"'), 'Uninstall at the bottom')
check('.padLayer("game", start: lookReturn ?? "gp-play"' in library and 'lookReturn = "gp-page-\\(page)"' in library,
      'the game page starts on Play; back from one of its pages, on that page\'s row')

# 6. The starting screen.
start = library[library.index('// MARK: - New look: the starting screen'):]
check('NewLookBackground()' in library and 'newLookLaunch(entry, geometry: geo)' in library and 'launchView(entry, geometry: geo)' not in library,
      'the island behind it (the one place it stays: the pages are on the system background); no older screen behind a switch')
check('.newLookPageBackground()' in look and 'Color(uiColor: grouped ? .systemGroupedBackground : .systemBackground)' in look,
      "the tabs' pages sit on Apple's system background")
for step in ['L("Get ready")', 'L("First-time setup")', 'L("Start Steam")', 'L("Open %@")']:
    check(step in start, f'step tile {step}')
check('fields["launch-client-error"] == "0"' in start, "Steam's step is done once the Dock says the launch was accepted")
check('"ln-stop"' in start and '"ln-help"' in start and 'GetHelpCenter.shared.openOnStartScreen(entry, error: dockStart.failure)' in start,
      'Stop, and Get Help first once the Dock stopped')
check('model.closeForPoolRestart()' in start and 'JITPoolAuto.startHeadline' in start, '"Not enough memory" with Close Madeira (jit-pool-notice-now)')
check('pad.move(toAny:' in start and 'B never stops by itself' in start, 'B moves to Stop; only A on Stop stops')
check('.onChange(of: model.startingScreen) { _, starting in' in library
      and 'LibraryController.shared.configure(enabled: model.enabled, ownsInput: starting)' in library,
      'the starting screen takes the controller until the game shows')
check("ownsInput: open || model.startingScreen)" in library, 'closing the Session menu on it keeps it')

# 6b. Stage 2: Stores, a store's page, its icon, and the Downloads tab's buttons.
steamgames = (app / 'SteamGames.swift').read_text(encoding='utf-8')
# 0045 (Cameron, Nov 9: "Switch to Apple's own tab bar"): a page stack per tab.
check('TabView(selection: lookSelection)' in library and library.count('NavigationStack(path: $') >= 5
      and library.count('.navigationDestination(for: NewLookRoute.self) { lookRoute($0) }') == 5,
      "Apple's tab bar: every tab has its own page stack")
check('Tab(value: NewLookTab.search, role: .search)' in library, "iOS 18: Search is the system's search tab")
check('ContentNavigation(stack: !(library.enabled && library.current == nil))' in (app / 'ContentView.swift').read_text(encoding='utf-8'),
      'the new-look library is not inside a second NavigationStack (it breaks Back)')
check('NewLookStoresPage(top: lookTop[.stores, default: 0],' in library and 'open: { storesPath.append(NewLookRoute.store($0)) }' in library
      and 'case .store(let store):' in library,
      'the Stores tab: the list of stores; a store\'s page is pushed inside the tab')
check('desktop: { selected = model.entries.first(where: { $0.desktop == true }) ?? .desktopEntry }' in library
      and 'NewLookLinkRow(id: "st-desktop", title: L("Windows Desktop")' in look,
      'the Stores tab ends with Windows Desktop (the old library\'s Desktop button)')
check('// The store sections as before, until the Stores redesign (stage 2).' not in library, 'the old store sections are gone from the Stores tab')
check('if new == lookTab { lookReselect(new) } else { lookTab = new }' in library
      and 'if !path.wrappedValue.isEmpty { path.wrappedValue = NavigationPath(); return }' in library and 'lookTop[item, default: 0] += 1' in library,
      'tapping the open tab goes back to its first page, then to the top')
for store, section in [('steam', 'SteamGamesSection('), ('epic', 'EpicGamesSection('), ('gog', 'GOGGamesSection('),
                       ('itch', 'ItchGamesSection('), ('ea', 'EAGamesSection(')]:
    check(f'case .{store}: {section}' in look, f'the {store} page is the store\'s own section')
check('.padLayer("store", back: { dismiss() }, page: true)' in look and '"sp-back"' not in look,
      "B on a store's page goes back a page (the system Back button; no home-made one)")
check('static var collapsible: Bool { false }' in steamgames, "a store's page never hides its games under a folded title")
check('if let pad, PadHighlight.enabled { buttonStyle(PadCardStyle(id: pad, grid: grid)) }' in library
      and '.padItem(id, cornerRadius: grid ? 16 : 12, press: configuration.trigger)' in pad,
      "the highlight reaches a store's game cards (A = a tap)")
check('.padItem("signin:steam", cornerRadius: 16, press: signIn)' in steamgames, 'and the sign-in cards')
for f, store in [('SteamGames', 'steam'), ('EpicGames', 'epic'), ('GOGGames', 'gog'), ('ItchGames', 'itch'), ('EAGames', 'ea')]:
    check(f'.padItem("{store}-not-installed"' in (app / f'{f}.swift').read_text(encoding='utf-8'), f'and {store}\'s Not installed')
check('store-icon-\\(store.rawValue).png' in look and 'kCGImageSourceThumbnailMaxPixelSize: 1024' in look
      and 'width: 256, height: 256' in look, "a store's own icon: the middle square of any picture, 256 x 256, in madeira-art")
check('.confirmationDialog(String(format: L("%@ icon"), store.name),' in look
      and 'Button(L("Choose from Photos")) { icons.target = store; icons.photos = true }' in look
      and 'Button(L("Choose from Files")) { icons.target = store; icons.files = true }' in look
      and 'Button(L("Cancel"), role: .cancel) {}' in look and '.padLayer("icon"' not in look
      and '.photosPicker(isPresented: $icons.photos' in look and '.fileImporter(isPresented: $icons.files' in look,
      "the pencil: Apple's action sheet with Photos, Files, Reset Icon and Cancel")
check('if icons.has(store) { Button(L("Reset Icon"), role: .destructive) { icons.reset(store) } }' in look,
      'Reset Icon only when the store has its own icon')
dl = look[look.index('// MARK: - Downloads'):look.index('// MARK: - Stores')]
for store, pause, resume, remove in [
        ('steam', 'SteamOwnedLibrary.shared.pause(id)', 'SteamOwnedLibrary.shared.install(id)',
         'SteamOwnedLibrary.shared.cancelInstall(id, installed: SteamGamesModel.shared.games.contains { $0.id == id })'),
        ('epic', 'EpicLibrary.shared.pause(row.key)', 'EpicLibrary.shared.install(row.key)', 'EpicLibrary.shared.cancel(row.key)'),
        ('gog', 'GOGLibrary.shared.pause(row.key)', 'GOGLibrary.shared.install(row.key)', 'GOGLibrary.shared.cancel(row.key)'),
        ('itch', 'ItchLibrary.shared.pause(id)', 'ItchLibrary.shared.install(id)', 'ItchLibrary.shared.cancel(id)'),
        ('ea', 'EALibrary.shared.pause(row.key)', 'EALibrary.shared.install(row.key)', 'EALibrary.shared.cancel(row.key)')]:
    check(pause in dl and resume in dl and remove in dl, f'Downloads: Pause, Resume and Remove call {store}\'s own')
check('L("Try Again")' in dl and 'L("Resume")' in dl and 'L("Pause")' in dl, 'Downloads: Try Again after a failure, Resume when paused, else Pause')
check('downloads.confirm = row' in dl and 'Button(L("Remove"), role: .destructive) { downloads.remove(row) }' in dl
      and 'Button(L("Cancel"), role: .cancel) {}' in dl and '.padLayer("remove"' not in dl
      and 'NewLookPopupLayer(shown: downloads.confirm != nil) { downloads.confirm = nil }' in dl,
      "Remove asks first, in Apple's action sheet: Remove is marked destructive and Cancel is there")
check('NewLookListPage(' in dl and 'ProgressView(value:' in dl, "Downloads is Apple's grouped list with Apple's progress bar")
check('.modifier(NewLookOverlays())' in library, "the icon's Photos and Files pickers sit over every tab")

# 6c. Stage 3: Settings and Search.
pages_src = pages
check('NewLookSettingsList(top: lookTop[.settings, default: 0], enableJIT: enableJIT,\n'
      '                                        open: { settingsPath.append(NewLookRoute.settings($0)) })' in library,
      "the Settings tab is Apple's grouped list of pages")
check('SettingsPagesList(startDock: startDock).scrollContentBackground(.hidden)' not in library, 'the old Settings list is gone from the new look')
check('case .settings(let page):\n            SettingsPageView(page: page, startDock: startDock)' in library,
      'a Settings page is the same page as before, pushed inside its tab (the tab bar stays)')
check('.modifier(NewLookSettingsChrome())' in pages_src and '.padLayer("settings-page", back: { dismiss() }, page: true)' in look,
      'a Settings page: B goes back')
check('NewLookLinkRow(id: "set-" + page.key, title: L(page.title), action: { open(page) }) {\n'
      '                                NewLookBadge(symbol: page.symbol, color: page.color)' in look
      and '.padItem(id, cornerRadius: 12, inset: -6, press: action)' in look,
      "Settings rows: the page's coloured icon, a chevron, and the highlight")
check("let banner = picked.isEmpty ? all.first.flatMap { $0.played != nil ? $0 : nil } : nil" in look
      and "grid(banner.map { top in games.filter { $0.id != top.id } } ?? games)" in look,
      "the Library's top card is the game played last, and that game is not in the grid below it (no game twice)")
check("case let (a?, b?): return max(a, b)" in look and "$0.played != $1.played" in look
      and "SteamOwnedLibrary.shared.$playtime.map { $0.mapValues(\\.lastPlayed) }" in look,
      "last played = the later of Madeira's own start time and Steam's own record; the order follows both")
owned_lib = (app / 'SteamOwnedLibrary.swift').read_text(encoding='utf-8')
check('@Published private(set) var libraryUnreachable: Date?' in owned_lib
      and 'libraryUnreachable = Date()' in owned_lib and 'libraryUnreachable = nil' in owned_lib,
      "Steam: a failed request for the account's games is remembered until one works again")
notice = look[look.index('struct NewLookSearchSteamNotice'):look.index('struct NewLookStoreGameArt')]
check('if steamDown { NewLookSearchSteamNotice() }' in look and '&& !steamDown' in look
      and 'L("Steam Can\'t Be Reached")' in notice and 'L("Try Again")' in notice
      and '.padItem("search-steam-retry"' in notice and 'refreshLibrary(interactive: false)' in notice,
      "Search says when Steam can't be reached, in place, with Try Again (not an alert; the controller reaches it)")
save_entry = library[library.index('    func save(_ entry: LibraryEntry, metadata: Bool = false) {'):library.index('    func remove(_ id: UUID) {')]
check('if let stored = next[i].lastPlayed, stored > (entry.lastPlayed ?? .distantPast) {' in save_entry
      and 'entry.lastPlayed = stored' in save_entry
      and save_entry.index('entry.lastPlayed = stored') < save_entry.index('next[i] = entry'),
      'saving an older copy of a game never takes its last-played time back (the Library is last played first)')
open_game = library[library.index('    private func lookOpenGame(_ entry: LibraryEntry) {'):]
open_game = open_game[:open_game.index('\n    }\n')]
check('if var stored = model.entries.first(where: { $0.id == entry.id }) {' in open_game
      and 'stored.relativePath = entry.relativePath' in open_game
      and open_game.index('entry = stored') < open_game.index('lookGames[entry.id] = entry'),
      "a game's page opens with the stored entry, not a list's older copy (its settings are not saved back stale)")
check('[library] played: \\(entry.title) stamped; stored=' in library and '[new-look] library order: first=' in look,
      'log lines: a start stamps the last-played time, and which game the Library puts first')
link_row = look[look.index('struct NewLookLinkRow'):look.index('extension NewLookLinkRow')]
check('Text(title).foregroundStyle(Color.primary)' in link_row and 'foregroundStyle(Color.secondary)' in link_row
      and 'foregroundStyle(.primary)' not in link_row and 'foregroundStyle(.secondary)' not in link_row
      and 'foregroundStyle(.tertiary)' not in link_row,
      "a row that opens a page: label-colour title and grey details, not levels of the button's blue tint")
settings_list = look[look.index('struct NewLookSettingsList'):look.index('struct NewLookSettingsChrome')]
check('LabeledContent(L("JIT"), value: L("On")).id("set-status")' in settings_list
      and '.padItem("status", cornerRadius: 12, inset: -6) { starter.start(enableJIT) }' in settings_list
      and 'LabeledContent(L("Memory+"), value: memory ? L("On") : L("Off"))' in settings_list,
      'Settings: JIT and Memory+ are rows that say On or Off in words; JIT off is the Enable JIT button')
check('LabeledContent(L("Version")) { Text(BuildStamp.text).textSelection(.enabled) }' in settings_list,
      'Settings ends with the version, in text you can copy')
srch = look[look.index('@MainActor enum NewLookSearch'):look.index('// MARK: - Settings')]
for rules in ['SteamGamesRules.items(', 'EpicGamesRules.items(', 'GOGGamesRules.items(', 'ItchGamesRules.items(', 'EAGamesRules.items(']:
    check(rules in srch, f'Search: {rules[:-7]} games you have not installed')
check('where item.installed == nil && item.owned != nil' in srch, 'Search: only owned games that are not installed')
check('L("Installed")' in srch and 'L("In your stores")' in srch and 'L("Stores")' in srch and 'L("Settings")' in srch,
      'Search: Installed, In your stores, Stores, Settings')
check('sheets.epicGame = .init(id: game.key)' in srch and 'sheets.steamGame = .init(id: id)' in srch
      and '@Published var steamGame: Game<Int>?' in library and '.onReceive(LibraryStoreSheets.shared.$steamGame)' in steamgames,
      "Search: a store game opens its store's page and its own sheet")
check('setting: { searchPath.append(NewLookRoute.settings($0)) }' in library and 'store: { searchPath.append(NewLookRoute.store($0)) }' in library,
      'Search: a store or a Settings page opens inside the Search tab')
check('storeGame: { game in lookPendingGame = game; searchPath.append(NewLookRoute.store(game.store)) }' in library
      and '.task { shown() }' in look and 'asyncAfter' not in srch,
      "Search: a store game's sheet opens once its store's page is up (no timer)")

# 6d. Cameron's Test 2 findings (Nov 9).
check('if let back = top.back { back() } else if layers.count == 1 { rootBack?() }' in pad
      and 'if lookTab == .search { lookPick(lookBefore) }' in library and 'if new == .search { lookBefore = old }' in library,
      'B on Search goes back to the tab it came from')
check('.scrollDismissesKeyboard(.immediately)' in look, 'Search: a drag puts the keyboard away')
check('.searchable(text: $lookSearch, placement: .navigationBarDrawer(displayMode: .always)' in library and 'content.searchFocused(field)' in look and '"search-field"' in look,
      "Search: Apple's own field; the controller puts the keyboard up from a button")
check('ContentUnavailableView.search(text: query)' in look and look.count('ContentUnavailableView {') == 2 and 'NewLookTypeButton' not in look,
      "Apple's empty screens: no results, nothing downloading, nothing installed")
check('.navigationBarTitleDisplayMode(.large)' in library[library.index('struct NewLookTabRoot'):],
      "every tab: Apple's large title")
check('guard pressed.0 == id, last.visible else { return }' in pad and 'if owner == nil || items[id]?.owner == owner' in pad
      and 'PadHighlight.shared.pop(name, token: token)' in pad,
      "a hidden tab's items and pages never take the controller from the open tab")
check('if command == "accept" || command == "menu", onGhost {' in pad and 'UIScreen.main' not in pad.replace('?? UIScreen.main.bounds.size', ''),
      'A on an item that is gone puts the highlight somewhere real first; the window, not the screen, is measured')
check('ForEach(games, id: \\.padID)' in look and 'var padID: String { "g-" + id }' in look
      and 'grids.first(where: { $0.value.ids.contains(focus) })?.key' in pad,
      'Library: the page scrolls with the highlight down the covers')
pill = look[look.index('struct NewLookStatusPill'):]
pill = pill[:pill.index('\n}\n')]
starter = look[look.index('final class NewLookJITStart'):]
starter = starter[:starter.index('\n}\n')]
check('.padItem("status", capsule: true) { starter.start(enableJIT) }' in pill and pill.count('.padItem(') == 1
      and '.disabled(starting)' in pill and 'guard !LibraryJITState.shared.enabled, !starting else { return }' in starter and 'pill(L("Memory+")' in pill,
      'JIT on is not selectable; JIT off starts JIT once (busy while starting); Memory+ is shown, never selectable')
check('symbol: memory ? "checkmark.circle.fill" : "minus.circle.fill"' in pill and 'Circle().fill' not in pill,
      'the pills tell on from off by the shape of a symbol, not by color alone (Apple rulebook 4.2)')
check('struct NewLookStatusTiles' not in look, 'the status tiles are gone (Settings has rows)')
check('.padLayer("game-\\(page)", back: { lookBack() }, page: true)' in library and '.padScrollFollow(reader)\n        .padLayer("game-' in library,
      'game pages: their own layer, following the highlight')
for item in ['gd-resolution', 'gd-aspect', 'gd-metalfx', 'gd-framegen', 'gc-mode', 'gc-opacity', 'gc-size', 'gl-start', 'gl-services',
             'gx-x87', 'gx-large', 'gx-avx', 'gx-cpus', 'gx-gpu', 'gx-vcrt', 'gx-japanese', 'gx-suspend', 'gb-find', 'ga-live', 'ga-reset']:
    check(f'.padItem("{item}"' in library, f'game pages: {item} on the controller')
check('lookReturn = "gp-page-\\(page)"\n        stack.push(page)' in library and 'stack.back()' in library,
      "game pages are pushed on the tab's own page stack and slide in and out like any iPhone page")
check('let loading = all.isEmpty && MadeiraDock.enabled && !ready.steamScanned' in look and '.onAppear { Self.load() }' in look
      and 'SteamGamesModel.shared.$scanned.removeDuplicates()' in look and 'let scanned = SteamGamesModel.shared.scanned' in look
      and 'SteamGamesModel.shared.refresh()' in look and 'if !self.scanned { self.scanned = true }' in steamgames,
      'first open: Loading your games, never "Nothing installed yet" before the stores are read')
# 0050: smoothness (ux-review-0044 #6, #7, #8).
games_cls = look[look.index('@MainActor final class NewLookGames'):look.index('// MARK: - Starting screen\n')]
check('.receive(on: DispatchQueue.main)' in games_cls and 'let games = LibraryReadyGame.all(search: "")' in games_cls
      and look.count('LibraryReadyGame.all(') == 1 and 'ready.matching(query)' in look,
      'the ready-game list is worked out once per change, not in each page body (review #7)')
check('try? await Task.sleep(for: .seconds(8))' in look and 'id: "lib-retry"' in look
      and '[new-look] library: loading again after a slow read' in look,
      'Loading your games has a time limit and Try again (review #8)')
check(look.count('guard let row = current(row, "') == 3 and 'Date().timeIntervalSince(last.at) < 0.6' in look
      and 'is no longer in the list' in look and 'Remove popup closed' in look,
      'Downloads buttons act on the row as it is now, once per press (review #6)')
check('NewLook.coverWidth(coverWidth * Double(pinch ?? 1), wide: wide)' in look and '.onChanged { value in pinch = value.magnification }' in look
      and '[new-look] cover size' in look and 'Picker("Cover size", selection: Binding(get: { NewLook.coverStep(coverWidth) }' in pages,
      'cover size: a live pinch, or Settings › Appearance › Cover size')
check('if pinch == nil, Date().timeIntervalSince(pinchEnded) > 0.4 { open(game.entry) }' in look, 'a pinch never opens the cover under it')
check('func detail(_ row: Row) -> String?' in look and 'L("about %@ left")' in look and 'downloads.detail(row)' in look,
      'Downloads: "1.2 GB of 13 GB · about 5 min left"')
check('Capsule().strokeBorder(Color.accentColor, lineWidth: 3)' in pad and 'NewLookColor' not in pad + look + library,
      'a capsule item\'s highlight is a capsule, in the app\'s accent color (no colors of our own)')
check('if let back, items[back] == nil { move(to: back, scroll: false); pending = back; return }' in pad
      and 'if id == pending { pending = nil;' in pad and 'register(id, .init(frame: last.frame,' in pad,
      'back from a game\'s page: the highlight returns to its row at once (no touch needed)')
check('.padScrollFollow(reader, toTop: ["gp-play"])' in library and '.id("pad-top")' in library,
      'the highlight on Play scrolls the game page all the way up')
check('!focus.hasPrefix("tab-") { remembered[page] = focus }' in pad and 'private func settle(layer: String, page: String?, at: Int)' in pad,
      'back from Search (or any tab change): the highlight starts on the page, never stuck on a tab button')

# 0041 (Cameron, Nov 9: "make sure things line up", "use all of Apple's stuff", follow the original mock-up).
check('RoundedRectangle(cornerRadius: max(0, cornerRadius - inset), style: .continuous)' in pad and '.padding(inset)' in pad
      and 'var inset: CGFloat = -4' in pad, 'the highlight is concentric with what it is on (around it, on it, or inside a card row)')
check(look.count('.padItem(id, cornerRadius: 12, inset: -6') >= 1 and library.count('cornerRadius: 12, inset: -6') >= 5,
      "rows in Apple's lists: the highlight sits just inside the row's rounded cell")
check('content.glassEffect(.regular, in: Capsule())' in look and 'accessibilityReduceTransparency' in look
      and '.listStyle(.insetGrouped)' in look and '.listStyle(.insetGrouped)' in library,
      "glass only on what floats (the controller's hints; the bars are Apple's own); the pages are Apple's grouped lists")
check('("Games", [.displayGraphics, .memory, .pointer, .runtimes])' in pages and 'static let newLookGroups' not in pages,
      'Settings: short groups, games first (one list of groups, no second copy)')
check('Section {\n                    nowRow(now)' in look.replace('\r', '') or 'nowRow(now)' in look, 'Downloads: the running one first, under Now')
check('static func steps(_ row: NewLookDownloads.Row) -> [NewLookStep]' in look and 'NewLookStepTile(step: $0, plain: true)' in look
      and look.count('phase: d.progress.phase.rawValue') == 5, "Downloads: the running one shows its store's real steps")
check('var blurb: String' in library and 'NewLookLinkRow(id: "gp-page-\\(item)", title: L(item.title), note: item.blurb, value: summary(item),' in library,
      'game page: a line under each row saying what it does')
check('struct NewLookBanner' in look and 'let banner = picked.isEmpty ? all.first.flatMap { $0.played != nil ? $0 : nil } : nil' in look
      and '"banner-play"' in look and '"banner-open"' in look and 'LibraryArtwork(entry: game.entry, backdrop: true)' in look,
      'Library: the last-played game in a banner on top (Play, Game page), then the grid')
check('button.sfSymbolsName' in look and '.GCControllerDidBecomeCurrent' in look, 'button hints use the controller in hand\'s own symbols')
check('.system(size:' not in look[look.index('struct NewLookHints'):look.index('// MARK: - Downloads')],
      'hints: text styles, not fixed sizes')

# 7. Words in all six languages.
langs = ['de', 'es', 'ko', 'pt-BR', 'ru', 'zh-Hans']
words = ['Library', 'Stores', 'Downloads', 'Settings', 'Search', 'Stop', 'Get ready', 'First-time setup',
         'Start Steam', 'Starting %@', 'Open %@', 'Waiting for its window…', 'While playing', 'Uninstall %@', 'Go to Stores',
         '%@ of %@ signed in', '%@ installed · %@ in your library', 'Sign in to see your games', 'Change Icon', 'Reset Icon',
         'Choose from Photos', 'Choose from Files', 'Remove %@ from Downloads?', 'Pause', 'Resume', 'Try Again', 'Remove', 'Cancel',
         'Games, stores and settings', 'In your stores', 'Nothing downloading', 'Games you install from a store show up here.',
         'Type a Name', 'Add a Game', 'Add a Game File', 'Game Page', "Steam's game list is taking a while.", 'Getting games', 'Steam and Dock',
         'Cover size', 'Small', 'Medium', 'Large', 'Loading your games…', '%@ of %@', 'about %@ left',
         'Now', 'Needs attention', 'Free space', 'Games ready', 'Step %@ of %@', 'Check files', 'Download files',
         'Finish installing', 'In progress · %@%%', 'How the game starts.', 'Buttons on the screen while you play.',
         'Download speed %@ %@', 'MB/s', 'KB/s']
missing = [w for w in words if not all(catalog.get(w, {}).get('localizations', {}).get(l, {}).get('stringUnit', {}).get('value') for l in langs)]
check(not missing, 'the words are translated' + (f' (missing: {missing})' if missing else ''))
# Written Nov 10 for the Apple pass (translated the same day by Claude, not yet read by a native speaker).
fresh = ['All Stores', 'Windows Desktop', 'Run installers and other Windows programs.', 'Store', 'Store Icon Not Changed',
         "The size of the Library's covers, and the touch buttons in games.",
         "Memory+ lets games use more of this device's memory. It depends on how this copy of Madeira was signed."]
check(all(len(catalog.get(w, {}).get('localizations', {})) == 6 for w in fresh), "the Apple pass's new words are in the string catalog, in six languages")

# 0052: Test 6 fixes (lag after many tab switches; Pause looked stuck).
item = pad[pad.index('struct PadItem'):pad.index('struct PadLayerModifier')]
check('@ObservedObject' not in item and '.map { [id] focus, shown in shown && focus == id }.removeDuplicates()) { on = $0 }' in item,
      'each highlight item redraws only when its own highlight changes (not on every move or tab switch)')
check('func isPaused(_ row: Row) -> Bool { flipped[row.id] ?? row.paused }' in look and 'downloads.isPaused(row)' in look
      and 'downloads.shownState(row)' in look and 'stateWatch = Publishers.MergeMany' in look,
      'Downloads: Pause and Resume show at once; store state changes show without waiting for the timer')

# 0053: Test 6 controller (LB/RB stuck over a pushed page; one stick push moved 2-3 rows).
check('private var onTabPage: Bool { layers.dropFirst().allSatisfy(\\.page) }' in pad
      and 'if onTabPage { tabs?(command == "next" ? 1 : -1) }' in pad and 'if onTabPage { search?() }' in pad
      and '.padLayer("store", back: { dismiss() }, page: true)' in look and '.padLayer("settings-page", back: { dismiss() }, page: true)' in look
      and '.padLayer("game", start: lookReturn ?? "gp-play", back: { lookBack() }, play: { start() }, page: true)' in library
      and '.padLayer("popup", back: close)' in look and 'page: true' not in look[look.index('struct NewLookPopupLayer'):look.index('// MARK: - Library')],
      'LB/RB and Y change tabs over a page pushed in a tab, never under a popup')
check('Int32(value) * sign > (held & mask != 0 ? 10000 : 16000)' in library, 'the stick has an in/out gap (no flicker moving two rows)')

# 0055: Search's not-installed store games show the game's picture.
check('NewLookStoreGameArt(game: game).frame(width: 46, height: 69)' in look
      and 'LibraryCachedArtwork(source: LibraryCoverCache.Source.steam(appID), glyph: nil)' in look
      and 'LibraryCoverCache.Source.store(game.store.rawValue, game.key, game.cover)' in look,
      'Search: a not-installed store game shows its own cover, not the store icon')

# 0056: the Now card shows the download speed at the bottom right, in larger text.
page_body = look.split('struct NewLookDownloadsPage: View {')[1].split('private static func rowID(')[0]
rows_list = look.split('    private func row(_ row: NewLookDownloads.Row) -> some View {')[1].split('private func buttons(')[0]
speed_fn = look.split('func speed(_ row: Row)')[1].split('// MARK: Actions')[0]
check('buttons(now, speed: true)' in page_body and 'speed: true' not in rows_list
      and 'if speed, let now = downloads.speed(row) { NewLookDownloadSpeed(number: now.number, unit: now.unit) }' in look,
      'Downloads: the speed is on the running download only, at the trailing end of the Pause and Remove row')
check('guard row.active, !row.failed, !isPaused(row), let rate = rates[row.id], rate > 1024 else { return nil }' in speed_fn
      and 'L("MB/s")' in speed_fn and 'L("KB/s")' in speed_fn,
      'Downloads: no speed while paused, failed or before it is known; MB/s, KB/s under 1 MB/s')
speed_view = look.split('struct NewLookDownloadSpeed: View {')[1].split('\n}\n')[0]
check('Text(number).font(.title2.bold()).monospacedDigit()' in speed_view and '.lineLimit(1).minimumScaleFactor(0.6)' in speed_view
      and '.accessibilityElement(children: .ignore)' in speed_view and 'padItem' not in speed_view and 'Button' not in speed_view,
      'Downloads: the speed is larger text, read out as one item, never a button or a highlight stop')

# 0057: store pages list the games to install first; the installed ones fold away under them.
steam_src = (app / 'SteamGames.swift').read_text(encoding='utf-8')
check('let fold = part == .all' in steam_src
      and 'let top = fold ? groups.downloading : groups.downloading + installed' in steam_src
      and steam_src.index('Text("Not installed").font(.headline)') < steam_src.index('NewLookInstalledHeader(id: "steam-installed"')
      and '@AppStorage("madeiraNewLookSteamShowInstalled") private var showInstalled = false' in steam_src,
      'Steam store page: downloading, then Not installed, then Installed (closed at first)')
for name, var, key in [('EpicGames', 'epic', 'Epic'), ('GOGGames', 'gog', 'GOG'), ('ItchGames', 'itch', 'Itch'), ('EAGames', 'ea', 'EA')]:
    src = (app / (name + '.swift')).read_text(encoding='utf-8')
    check(f'let top = mine.filter {{ {var}.downloads[$0.id] != nil }}' in src
          and f'let folded = mine.filter {{ {var}.downloads[$0.id] == nil }}' in src
          and src.index('Text("Not installed").font(.headline)') < src.index(f'NewLookInstalledHeader(id: "{var}-installed"')
          and f'@AppStorage("madeiraNewLook{key}ShowInstalled") private var showInstalled = false' in src
          and 'others.isEmpty && folded.isEmpty && search.isEmpty' in src,
          f'{name}: games to install first, installed folded (closed at first)')
fold_view = look.split('struct NewLookInstalledHeader: View {')[1].split('\n}\n')[0]
check('.padItem(id, cornerRadius: 16) { toggle(open) }' in fold_view and 'if let open {' in fold_view
      and '.accessibilityAddTraits(.isHeader)' in fold_view and '[new-look] store page: Installed' in fold_view,
      'Installed title: a button with the highlight when it folds, plain text when it is the only group')

# 8. Markers.
check('[pad-highlight] on' in pad and '[pad-highlight] layer \\(name) opened' in pad, 'log lines (markers)')
check('[new-look] downloads: remove' in look and '[new-look] store icon: ' in look, 'log lines for Remove and a store icon (markers)')

print('check-new-look: ' + ('FAIL' if failures else 'PASS'))
sys.exit(1 if failures else 0)
