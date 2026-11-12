// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md

import SwiftUI
import UIKit
import Combine
import ImageIO
import GameController
import PhotosUI
import UniformTypeIdentifiers

// Madeira's own screens, built from Apple's standard parts (reference/apple-design-rulebook.md):
// Apple's tab bar with a page stack in every tab, large titles, grouped lists for rows, a grid
// for covers, Apple's button styles and system colors. The one custom part is the controller's
// highlight (PadHighlight.swift): an iPhone gives a game controller no focus of its own, so
// Madeira draws one on every screen (Apple rulebook 12.12, 12.31).
//
// Tabs: Library (every installed game, last played first), Stores, Downloads (a % badge
// while something downloads), Settings, and Search. On an iPhone held upright the tab bar
// floats at the bottom; sideways and on iPad it sits at the top.

enum NewLook {
    /// A game whose page opens to start it at once (X on a cover): LibraryDetail reads and clears it.
    @MainActor static var autoPlay: UUID?
    /// The Library's cover width in points on a phone (a pinch sets any width between; Settings
    /// › Appearance › Cover size picks Small, Medium or Large). Wide screens use it × 1.27.
    static let coverWidthKey = "madeiraNewLookCoverWidth"
    /// Settings › Appearance › Zoom haptics: a click as a pinch on the covers crosses a size.
    static let zoomHapticsKey = "madeiraLibraryZoomHaptics"
    /// The shape scale (tests/host/audit-new-look-shapes.py): small badges 10, covers 16, cards 22;
    /// buttons, pills, chips and bars are capsules.
    static let badgeRadius: CGFloat = 8
    /// Sheets and panels that float over the page.
    static let sheetRadius: CGFloat = 28
    static let coverRadius: CGFloat = 16
    static let cardRadius: CGFloat = 22
    static let coverWidths: [Double] = [84, 104, 150]
    static let coverRange: ClosedRange<Double> = 64...230
    /// The narrowest a cover may be; the grid fits as many as it can.
    static func coverWidth(_ stored: Double, wide: Bool) -> CGFloat {
        CGFloat(min(coverRange.upperBound, max(coverRange.lowerBound, stored)) * (wide ? 1.27 : 1))
    }
    /// The Small / Medium / Large nearest a width (Settings).
    static func coverStep(_ stored: Double) -> Int {
        coverWidths.indices.min { abs(coverWidths[$0] - stored) < abs(coverWidths[$1] - stored) } ?? 1
    }
}

// MARK: - Shared parts

/// A group inside a page that is not a list (the game page's notes): Apple's secondary
/// grouped background (Apple rulebook 4.18), no material in the content (5.1).
struct NewLookCard: ViewModifier {
    var radius: CGFloat = 22
    func body(content: Content) -> some View {
        content.background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: radius, style: .continuous))
    }
}

/// The controller's button hints, floating over the page above the tab bar: Apple's Liquid
/// Glass on iOS 26 (the controls layer, Apple rulebook 5.1), a thick material before that,
/// solid with Reduce Transparency.
struct NewLookGlass: ViewModifier {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    func body(content: Content) -> some View {
        if reduceTransparency {
            content
                .background(Color(uiColor: .secondarySystemBackground), in: Capsule())
                .overlay(Capsule().strokeBorder(Color(uiColor: .separator), lineWidth: 0.5))
        } else if #available(iOS 26.0, *) {
            content.glassEffect(.regular, in: Capsule())
        } else {
            content
                .background(.thickMaterial, in: Capsule())
                .overlay(Capsule().strokeBorder(Color(uiColor: .separator), lineWidth: 0.5))
        }
    }
}

extension View {
    func newLookCard(_ radius: CGFloat = 22) -> some View { modifier(NewLookCard(radius: radius)) }
    func newLookGlass() -> some View { modifier(NewLookGlass()) }
    /// What sits behind a page that is not a list: Apple's system background (Apple rulebook
    /// 4.17, 4.19). `grouped`: the page holds groups of rows (the grouped set).
    func newLookPageBackground(grouped: Bool = false) -> some View {
        background(Color(uiColor: grouped ? .systemGroupedBackground : .systemBackground).ignoresSafeArea())
    }
}

// MARK: - Pages

/// A page of covers (the Library, a store's page): its own scroll view on Apple's system
/// background. Each tab and each pushed page has its own, so a tab keeps its place.
/// `refresh`: pull to refresh, only on a page it refreshes something on. `top`: when it
/// changes the page scrolls back to the top (tapping the open tab, as on every iPhone app).
struct NewLookScrollPage<Content: View>: View {
    var refresh: (() async -> Void)? = nil
    var top = 0
    @ViewBuilder var content: (CGFloat) -> Content
    var body: some View {
        GeometryReader { geo in
            let side: CGFloat = geo.size.width >= 700 ? 28 : 16
            let width = min(geo.size.width, 1100) - side * 2
            ScrollViewReader { reader in
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        Color.clear.frame(height: 0).id(Self.topID)
                        content(width)
                    }
                    .padding(.horizontal, side)
                    .padding(.top, 12)
                    .padding(.bottom, 32)
                    .frame(maxWidth: 1100, alignment: .leading)
                    .frame(maxWidth: .infinity)
                }
                .modifier(NewLookRefresh(refresh: refresh))
                .padScrollFollow(reader)
                .onChange(of: top) { _, _ in
                    withAnimation(UIAccessibility.isReduceMotionEnabled ? nil : .default) {
                        reader.scrollTo(Self.topID, anchor: .top)
                    }
                }
            }
        }
        .newLookPageBackground()
    }
    private static var topID: String { "page-top" }
}

/// A page of rows (Stores, Downloads, Settings, Search): Apple's grouped list (Apple rulebook
/// 9.32) on the grouped background the list draws itself (4.17). The controller's highlight
/// scrolls it, and the system's own focus stays off its rows while a controller is connected.
/// `top`: when it changes the list scrolls back to its first row, `topID`.
struct NewLookListPage<Content: View>: View {
    var refresh: (() async -> Void)? = nil
    var top = 0
    var topID: String? = nil
    @ViewBuilder var content: () -> Content
    var body: some View {
        ScrollViewReader { reader in
            List { content() }
                .listStyle(.insetGrouped)
                // Search: dragging the list puts the keyboard away.
                .scrollDismissesKeyboard(.immediately)
                .modifier(NewLookRefresh(refresh: refresh))
                .padScrollFollow(reader)
                .onChange(of: top) { _, _ in
                    guard let topID else { return }
                    withAnimation(UIAccessibility.isReduceMotionEnabled ? nil : .default) {
                        reader.scrollTo(topID, anchor: .top)
                    }
                }
        }
        .padNoSystemFocus()
    }
}

/// Pull to refresh, only where the page has something to refresh.
private struct NewLookRefresh: ViewModifier {
    let refresh: (() async -> Void)?
    @ViewBuilder func body(content: Content) -> some View {
        if let refresh { content.refreshable { await refresh() } } else { content }
    }
}

/// A row that opens a page: Apple's list row, with its picture, its name, a line under it, a
/// value and a chevron (Apple rulebook 9.29: a chevron means "go deeper"). The same row the
/// game's own pages use, so the controller's highlight sits on it the same way.
struct NewLookLinkRow<Leading: View>: View {
    let id: String
    let title: String
    var note: String = ""
    var value: String? = nil
    let action: () -> Void
    @ViewBuilder var leading: () -> Leading
    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                leading()
                // Colors by name, not by level: inside a list's button, .primary and .secondary
                // are levels of the button's tint, so the whole row came out blue. A row that
                // opens a page reads like Settings' own rows: label color, gray details.
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).foregroundStyle(Color.primary)
                    if !note.isEmpty { Text(note).font(.subheadline).foregroundStyle(Color.secondary) }
                }
                Spacer(minLength: 8)
                if let value { Text(value).foregroundStyle(Color.secondary).lineLimit(1) }
                Image(systemName: "chevron.forward").font(.footnote.weight(.semibold)).foregroundStyle(Color(uiColor: .tertiaryLabel))
                    .accessibilityHidden(true)
            }
            .contentShape(Rectangle())
        }
        .padItem(id, cornerRadius: 12, inset: -6, press: action)
    }
}
extension NewLookLinkRow where Leading == EmptyView {
    init(id: String, title: String, note: String = "", value: String? = nil, action: @escaping () -> Void) {
        self.init(id: id, title: title, note: note, value: value, action: action) { EmptyView() }
    }
}

// MARK: - Starting screen background

/// The Madeira island (the banner art from the Madeira repository, text taken out), faded at
/// its cut edges and dimmed so text on it stays readable. Behind the game starting screen
/// only (a game's own loading view may have its own style: Apple rulebook 11.9); every page
/// uses Apple's system backgrounds (4.19, 7.26).
struct NewLookBackground: View {
    static let image: UIImage? = Bundle.main.url(forResource: "MadeiraIsland", withExtension: "png")
        .flatMap { UIImage(contentsOfFile: $0.path) }

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width, h = geo.size.height
            let upright = h > w
            // Where the island sits: over the title on an upright phone, top right otherwise.
            let scale: CGFloat = upright && w < 600 ? 1.05 : max(1.3, w / 860)
            let size = CGSize(width: 600 * scale, height: 300 * scale)
            let origin = upright && w < 600 ? CGPoint(x: -150, y: 58) : CGPoint(x: w * (upright ? 0.22 : 0.38), y: -140)
            ZStack(alignment: .topLeading) {
                Color.black
                if let image = Self.image {
                    Image(uiImage: image).resizable().interpolation(.high)
                        .frame(width: size.width, height: size.height)
                        // Dimmed inside the island's own shape only.
                        .overlay { Color.black.opacity(0.68).mask(Image(uiImage: image).resizable()) }
                        // The cut-off edges fade out: the left, the top and the bottom.
                        .mask(LinearGradient(stops: [.init(color: .clear, location: 0), .init(color: .black, location: 0.3)],
                                             startPoint: .leading, endPoint: .trailing))
                        .mask(LinearGradient(stops: [.init(color: .clear, location: 0), .init(color: .black, location: 0.18),
                                                     .init(color: .black, location: 0.62), .init(color: .clear, location: 0.96)],
                                             startPoint: .top, endPoint: .bottom))
                        .rotationEffect(.degrees(upright && w < 600 ? -8 : -5))
                        .shadow(color: .black.opacity(0.5), radius: 18, y: 18)
                        .offset(x: origin.x, y: origin.y)
                }
            }
            .frame(width: w, height: h, alignment: .topLeading)
            .clipped()
        }
        .ignoresSafeArea()
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

// MARK: - Tabs

enum NewLookTab: Int, CaseIterable {
    case library, stores, downloads, settings, search
    var title: String {
        switch self {
        case .library: return L("Library")
        case .stores: return L("Stores")
        case .downloads: return L("Downloads")
        case .settings: return L("Settings")
        case .search: return L("Search")
        }
    }
    var symbol: String {
        switch self {
        case .library: return "square.grid.2x2"
        case .stores: return "bag"
        case .downloads: return "arrow.down.circle"
        case .settings: return "gearshape"
        case .search: return "magnifyingglass"
        }
    }
    /// LB and RB go round the four tabs (Search is Y).
    func step(_ by: Int) -> NewLookTab {
        let ring: [NewLookTab] = [.library, .stores, .downloads, .settings]
        let index = ring.firstIndex(of: self) ?? 0
        return ring[(index + by + ring.count) % ring.count]
    }
}

/// The buttons the controller has here, under the screen while the highlight shows. Each button
/// is drawn with the controller's own symbol from Game Controller (sfSymbolsName), so a
/// DualSense shows its cross, circle, square and triangle and an Xbox pad its letters (Steam
/// Deck's rule: glyphs match the controller in hand). The words follow the text size.
struct NewLookHints: View {
    let items: [(String, String)]
    @State private var symbols: [String: String] = [:]
    var body: some View {
        HStack(spacing: 6) {
            ForEach(items.indices, id: \.self) { index in
                let (buttons, word) = items[index]
                HStack(spacing: 4) {
                    ForEach(buttons.split(separator: " ").map(String.init), id: \.self) { button in
                        if let symbol = symbols[button] {
                            Image(systemName: symbol).font(.title3.weight(.semibold))
                        } else {
                            Text(verbatim: button).font(.caption2.weight(.heavy))
                                .padding(.horizontal, 6).frame(minWidth: 22, minHeight: 22)
                                .background(Color.primary, in: Capsule())
                                .foregroundStyle(Color(uiColor: .systemBackground))
                        }
                    }
                    Text(word).font(.caption.weight(.semibold)).lineLimit(1).padding(.leading, 2)
                }
                .padding(.horizontal, 4)
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 6)
        .newLookGlass()
        .dynamicTypeSize(...DynamicTypeSize.xxLarge)
        .accessibilityHidden(true)
        .allowsHitTesting(false)
        .onAppear { symbols = Self.symbols() }
        .onReceive(NotificationCenter.default.publisher(for: .GCControllerDidBecomeCurrent)) { _ in symbols = Self.symbols() }
        .onReceive(NotificationCenter.default.publisher(for: .GCControllerDidDisconnect)) { _ in symbols = Self.symbols() }
    }

    /// Our button names to the controller in hand's own symbols ("xmark.circle" on a DualSense's
    /// A). A button the system names nothing for keeps its letters.
    static func symbols() -> [String: String] {
        guard let pad = (GCController.current ?? GCController.controllers().first)?.extendedGamepad else { return [:] }
        let buttons: [String: GCControllerButtonInput] = [
            "A": pad.buttonA, "B": pad.buttonB, "X": pad.buttonX, "Y": pad.buttonY,
            "LB": pad.leftShoulder, "RB": pad.rightShoulder, "LT": pad.leftTrigger, "RT": pad.rightTrigger, "Menu": pad.buttonMenu,
        ]
        var names: [String: String] = [:]
        for (name, button) in buttons {
            if let symbol = button.sfSymbolsName, UIImage(systemName: symbol) != nil { names[name] = symbol }
        }
        return names
    }
}

// MARK: - Downloads

/// Every store's downloads in one list, and the Downloads tab's % badge.
@MainActor final class NewLookDownloads: ObservableObject {
    static let shared = NewLookDownloads()
    struct Row: Identifiable {
        let id: String
        let title: String
        let store: NewLookStore
        /// The store's own id for the game (a Steam or itch.io number as text).
        let key: String
        let fraction: Double
        let done: UInt64
        let total: UInt64
        /// "Downloading", "Waiting", "Paused" or why it failed.
        let state: String
        let failed: Bool
        let active: Bool
        let paused: Bool
        /// The store downloader's own step: preparing, checking or verifying, downloading,
        /// finishing (itch.io: preparing, downloading, unpacking).
        var phase = ""
    }
    @Published private(set) var rows: [Row] = []
    /// "43%" while something downloads, nil otherwise.
    @Published private(set) var badge: String?
    /// The download whose Remove asks first (NewLookDownloadsPage's action sheet).
    @Published var confirm: Row?
    private var timer: Timer?
    /// Bytes a second for each running download, smoothed (for "about 5 min left").
    @Published private(set) var rates: [String: Double] = [:]
    private var samples: [String: (at: Date, done: UInt64)] = [:]

    private init() {
        refresh()
        let timer = Timer(timeInterval: 1, repeats: true) { _ in MainActor.assumeIsolated { NewLookDownloads.shared.refresh() } }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
        // A download that pauses, resumes, waits or fails shows it at once, not at the next tick
        // (Cameron, Test 6: Pause looked stuck for a second). Progress alone still waits for the tick.
        let states: [AnyPublisher<[String: String], Never>] = [
            SteamOwnedLibrary.shared.$downloads.map { Dictionary(uniqueKeysWithValues: $0.map { ("\($0.key)", "\($0.value.state)") }) }.eraseToAnyPublisher(),
            EpicLibrary.shared.$downloads.map { $0.mapValues { "\($0.state)" } }.eraseToAnyPublisher(),
            GOGLibrary.shared.$downloads.map { $0.mapValues { "\($0.state)" } }.eraseToAnyPublisher(),
            ItchLibrary.shared.$downloads.map { Dictionary(uniqueKeysWithValues: $0.map { ("\($0.key)", "\($0.value.state)") }) }.eraseToAnyPublisher(),
            EALibrary.shared.$downloads.map { $0.mapValues { "\($0.state)" } }.eraseToAnyPublisher(),
        ]
        stateWatch = Publishers.MergeMany(states.map { $0.removeDuplicates().map { _ in () }.eraseToAnyPublisher() })
            .receive(on: DispatchQueue.main)
            .sink { MainActor.assumeIsolated { NewLookDownloads.shared.refresh() } }
    }
    private var stateWatch: AnyCancellable?

    /// Pause or Resume just pressed: the row shows its new state at once, until the store's own
    /// state catches up (a running download stops at its next piece: about 1 s, 2 s while it
    /// prepares) or 5 s pass.
    @Published private(set) var flipped: [String: Bool] = [:]
    private var flippedAt: [String: Date] = [:]
    /// The row's Paused state as the screen shows it.
    func isPaused(_ row: Row) -> Bool { flipped[row.id] ?? row.paused }
    /// The row's state as the screen shows it ("Paused" as soon as Pause is pressed).
    func shownState(_ row: Row) -> String {
        guard let paused = flipped[row.id], paused != row.paused else { return row.state }
        return paused ? L("Paused") : L("Waiting")
    }

    private static func row(_ store: NewLookStore, _ key: String, _ title: String, queued: Bool, paused: Bool, failure: String?,
                            fraction: Double, done: UInt64, total: UInt64, phase: String) -> Row {
        let state: String
        if let failure { state = failure } else if paused { state = L("Paused") } else if queued { state = L("Waiting") } else { state = L("Downloading") }
        return Row(id: store.rawValue + ":" + key, title: title, store: store, key: key, fraction: fraction, done: done, total: total,
                   state: state, failed: failure != nil, active: failure == nil && !paused && !queued, paused: paused, phase: phase)
    }

    func refresh() {
        var list: [Row] = []
        let steam = SteamOwnedLibrary.shared
        for (id, d) in steam.downloads {
            var failure: String?; if case .failed(let m) = d.state { failure = m }
            list.append(Self.row(.steam, String(id), steam.game(id)?.name ?? "Steam \(id)", queued: d.state == .queued, paused: d.state == .paused,
                                 failure: failure, fraction: d.progress.fraction, done: d.progress.doneBytes, total: d.progress.totalBytes,
                                 phase: d.progress.phase.rawValue))
        }
        let epic = EpicLibrary.shared
        for (app, d) in epic.downloads {
            var failure: String?; if case .failed(let m) = d.state { failure = m }
            list.append(Self.row(.epic, app, epic.owned.first { $0.appName == app }?.title ?? app, queued: d.state == .queued, paused: d.state == .paused,
                                 failure: failure, fraction: d.progress.fraction, done: d.progress.doneBytes, total: d.progress.totalBytes,
                                 phase: d.progress.phase.rawValue))
        }
        let gog = GOGLibrary.shared
        for (id, d) in gog.downloads {
            var failure: String?; if case .failed(let m) = d.state { failure = m }
            list.append(Self.row(.gog, id, gog.owned.first { $0.id == id }?.title ?? id, queued: d.state == .queued, paused: d.state == .paused,
                                 failure: failure, fraction: d.progress.fraction, done: d.progress.doneBytes, total: d.progress.totalBytes,
                                 phase: d.progress.phase.rawValue))
        }
        let itch = ItchLibrary.shared
        for (id, d) in itch.downloads {
            var failure: String?; if case .failed(let m) = d.state { failure = m }
            let title = (itch.owned.first(where: { $0.id == id }) ?? itch.added.first(where: { $0.id == id }))?.title ?? "itch.io \(id)"
            list.append(Self.row(.itch, String(id), title, queued: d.state == .queued, paused: d.state == .paused,
                                 failure: failure, fraction: d.progress.fraction, done: d.progress.doneBytes, total: d.progress.totalBytes,
                                 phase: d.progress.phase.rawValue))
        }
        let ea = EALibrary.shared
        for (id, d) in ea.downloads {
            var failure: String?; if case .failed(let m) = d.state { failure = m }
            list.append(Self.row(.ea, id, ea.owned.first { $0.id == id }?.title ?? id, queued: d.state == .queued, paused: d.state == .paused,
                                 failure: failure, fraction: d.progress.fraction, done: d.progress.doneBytes, total: d.progress.totalBytes,
                                 phase: d.progress.phase.rawValue))
        }
        list.sort { a, b in
            if a.active != b.active { return a.active }
            return a.title.localizedStandardCompare(b.title) == .orderedAscending
        }
        // The badge: every running or waiting download's bytes together.
        let counted = list.filter { !$0.failed && $0.total > 0 }
        let total = counted.reduce(UInt64(0)) { $0 + $1.total }
        let done = counted.reduce(UInt64(0)) { $0 + min($1.done, $1.total) }
        let badge: String? = list.contains(where: { $0.active }) && total > 0
            ? "\(min(99, Int(Double(done) / Double(total) * 100)))%"
            : (list.contains(where: { $0.failed }) ? "!" : nil)
        let ids = list.map(\.id) + list.map(\.state)
        if ids != rows.map(\.id) + rows.map(\.state) || list.map(\.done) != rows.map(\.done) { rows = list }
        if badge != self.badge { self.badge = badge }
        // A pressed Pause or Resume the store has caught up with (or gave up on) shows the store's state.
        for (id, paused) in flipped {
            let row = list.first { $0.id == id }
            if row == nil || row?.paused == paused || row?.failed == true || Date().timeIntervalSince(flippedAt[id] ?? .distantPast) > 5 {
                flipped[id] = nil; flippedAt[id] = nil
            }
        }
        // A Remove popup for a download that finished or left the list closes by itself.
        if let open = confirm, !list.contains(where: { $0.id == open.id }) {
            LogStore.shared.log("[new-look] downloads: Remove popup closed, \(open.id) left the list")
            confirm = nil
        }
        // Speed: how far each running download got since the last look.
        let now = Date()
        var rates: [String: Double] = [:]
        for row in list where row.active {
            if let last = samples[row.id], row.done >= last.done, now.timeIntervalSince(last.at) >= 0.9 {
                let speed = Double(row.done - last.done) / now.timeIntervalSince(last.at)
                rates[row.id] = self.rates[row.id].map { $0 * 0.7 + speed * 0.3 } ?? speed
                samples[row.id] = (now, row.done)
            } else {
                if samples[row.id] == nil || row.done < samples[row.id]!.done { samples[row.id] = (now, row.done) }
                if let kept = self.rates[row.id] { rates[row.id] = kept }
            }
        }
        samples = samples.filter { id, _ in list.contains { $0.id == id && $0.active } }
        if rates != self.rates { self.rates = rates }
    }

    /// "1.2 GB of 13 GB · about 5 min left" (the time once the speed is known).
    func detail(_ row: Row) -> String? {
        guard row.total > 0, !row.failed else { return nil }
        let done = ByteCountFormatter.string(fromByteCount: Int64(min(row.done, row.total)), countStyle: .file)
        let total = ByteCountFormatter.string(fromByteCount: Int64(row.total), countStyle: .file)
        var text = String(format: L("%@ of %@"), done, total)
        if row.active, let rate = rates[row.id], rate > 1024 {
            let seconds = Double(row.total - min(row.done, row.total)) / rate
            let formatter = DateComponentsFormatter()
            formatter.unitsStyle = .abbreviated
            formatter.allowedUnits = seconds >= 3600 ? [.hour, .minute] : (seconds >= 60 ? [.minute] : [.second])
            formatter.maximumUnitCount = 2
            if let left = formatter.string(from: max(1, seconds)) { text += " · " + String(format: L("about %@ left"), left) }
        }
        return text
    }

    /// The running download's speed for the Now card: ("12.4", "MB/s"), or ("640", "KB/s") under 1 MB/s.
    /// Nothing while it is paused, failed, not downloading or before the speed is known.
    func speed(_ row: Row) -> (number: String, unit: String)? {
        guard row.active, !row.failed, !isPaused(row), let rate = rates[row.id], rate > 1024 else { return nil }
        if rate >= 1_000_000 {
            return ((rate / 1_000_000).formatted(.number.precision(.fractionLength(1))), L("MB/s"))
        }
        return (String(Int((rate / 1000).rounded())), L("KB/s"))
    }

    // MARK: Actions (the same calls as each store's own game sheet)

    /// The last button press on a row, so a quick second tap or A press does not undo the first.
    private var lastPress: (id: String, at: Date)?

    /// The row as the stores have it now, or nil when it is no longer in the list (a Remove popup
    /// left open while the download finished) or the same row was pressed under 0.6 s ago.
    private func current(_ row: Row, _ what: String) -> Row? {
        refresh()
        guard let now = rows.first(where: { $0.id == row.id }) else {
            LogStore.shared.log("[new-look] downloads: \(what) skipped, \(row.id) is no longer in the list")
            return nil
        }
        if let last = lastPress, last.id == row.id, Date().timeIntervalSince(last.at) < 0.6 {
            LogStore.shared.log("[new-look] downloads: \(what) skipped, \(row.id) pressed twice")
            return nil
        }
        lastPress = (row.id, Date())
        return now
    }

    /// Pause a running or waiting download.
    func pause(_ row: Row) {
        guard let row = current(row, "pause") else { return }
        LogStore.shared.log("[new-look] downloads: pause \(row.id)")
        switch row.store {
        case .steam: if let id = Int(row.key) { SteamOwnedLibrary.shared.pause(id) }
        case .epic: EpicLibrary.shared.pause(row.key)
        case .gog: GOGLibrary.shared.pause(row.key)
        case .itch: if let id = Int(row.key) { ItchLibrary.shared.pause(id) }
        case .ea: EALibrary.shared.pause(row.key)
        case .other: break
        }
        flipped[row.id] = true; flippedAt[row.id] = Date()
        refresh()
    }

    /// Resume a paused download, or try a failed one again (it continues where it stopped).
    func resume(_ row: Row) {
        guard let row = current(row, "resume") else { return }
        LogStore.shared.log("[new-look] downloads: resume \(row.id)")
        switch row.store {
        case .steam: if let id = Int(row.key) { SteamOwnedLibrary.shared.install(id) }
        case .epic: EpicLibrary.shared.install(row.key)
        case .gog: GOGLibrary.shared.install(row.key)
        case .itch: if let id = Int(row.key) { ItchLibrary.shared.install(id) }
        case .ea: EALibrary.shared.install(row.key)
        case .other: break
        }
        flipped[row.id] = false; flippedAt[row.id] = Date()
        refresh()
    }

    /// Take a download out of the list. A first install also loses its partial files; an
    /// update or a repair only stops (each store's own cancel).
    func remove(_ row: Row) {
        guard let row = current(row, "remove") else { return }
        LogStore.shared.log("[new-look] downloads: remove \(row.id)")
        switch row.store {
        case .steam:
            if let id = Int(row.key) {
                // Steam needs to be told: a game it lists already is only paused, never deleted.
                SteamOwnedLibrary.shared.cancelInstall(id, installed: SteamGamesModel.shared.games.contains { $0.id == id })
            }
        case .epic: EpicLibrary.shared.cancel(row.key)
        case .gog: GOGLibrary.shared.cancel(row.key)
        case .itch: if let id = Int(row.key) { ItchLibrary.shared.cancel(id) }
        case .ea: EALibrary.shared.cancel(row.key)
        case .other: break
        }
        refresh()
    }
}

/// The Downloads tab, Apple's grouped list: the running download under "Now" with each of its
/// steps; then what failed ("Needs attention") and what waits or is paused ("Waiting"). Pause,
/// Resume (Try Again after a failure) and Remove on each (Apple rulebook 9.51 to 9.58).
struct NewLookDownloadsPage: View {
    @ObservedObject private var downloads = NewLookDownloads.shared
    var top = 0
    let stores: () -> Void
    var body: some View {
        let now = downloads.rows.first(where: \.active)
        let failed = downloads.rows.filter(\.failed)
        let waiting = downloads.rows.filter { !$0.failed && $0.id != now?.id }
        let first = now ?? failed.first ?? waiting.first
        NewLookListPage(top: top, topID: first.map { Self.rowID($0) }) {
            if let now {
                Section {
                    nowRow(now)
                    ForEach(Self.steps(now)) { NewLookStepTile(step: $0, plain: true) }
                    buttons(now, speed: true)
                } header: { Text(L("Now")) }
            }
            if !failed.isEmpty {
                Section { ForEach(failed) { row($0) } } header: { Text(L("Needs attention")) }
            }
            if !waiting.isEmpty {
                Section { ForEach(waiting) { row($0) } } header: { Text(L("Waiting")) }
            }
        }
        .overlay {
            if downloads.rows.isEmpty {
                // Apple's empty screen, with the next step (Apple rulebook 16.16).
                ContentUnavailableView {
                    Label(L("Nothing downloading"), systemImage: "arrow.down.circle")
                } description: {
                    Text("Games you install from a store show up here.")
                } actions: {
                    NewLookSheetButton(id: "dl-stores", title: L("Go to Stores"), symbol: nil, filled: true, action: stores)
                        .frame(maxWidth: 320)
                }
            }
        }
        // Remove asks first, in Apple's action sheet (Apple rulebook 9.58, 10.33): a first install
        // loses what it downloaded so far. Cancel is the safe choice.
        .confirmationDialog(downloads.confirm.map { String(format: L("Remove %@ from Downloads?"), $0.title) } ?? "",
                            isPresented: Binding(get: { downloads.confirm != nil }, set: { if !$0 { downloads.confirm = nil } }),
                            titleVisibility: .visible, presenting: downloads.confirm) { row in
            Button(L("Remove"), role: .destructive) { downloads.remove(row) }
            Button(L("Cancel"), role: .cancel) {}
        } message: { _ in
            Text("A first install also deletes the files downloaded so far. An update or a repair only stops; the game stays.")
        }
        .background { NewLookPopupLayer(shown: downloads.confirm != nil) { downloads.confirm = nil } }
    }

    private static func rowID(_ row: NewLookDownloads.Row) -> String { "dl-row-" + row.id }

    /// The running download: its store, name, step and time left, and how far it is.
    private func nowRow(_ row: NewLookDownloads.Row) -> some View {
        let steps = Self.steps(row)
        let at = steps.firstIndex { $0.state == .active }
        let line = [at.map { String(format: L("Step %@ of %@"), String($0 + 1), String(steps.count)) }, downloads.detail(row)]
            .compactMap { $0 }.joined(separator: " · ")
        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 12) {
                NewLookStoreIcon(store: row.store, size: 44)
                VStack(alignment: .leading, spacing: 2) {
                    Text(row.title).font(.headline)
                    if !line.isEmpty { Text(line).font(.subheadline).monospacedDigit().foregroundStyle(.secondary) }
                }
            }
            if row.total > 0 { ProgressView(value: row.fraction) }
        }
        .accessibilityElement(children: .combine)
        .id(Self.rowID(row))
    }

    /// A row under "Needs attention" or "Waiting".
    private func row(_ row: NewLookDownloads.Row) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline) {
                    Text(row.title).font(.headline)
                    Spacer(minLength: 8)
                    if row.total > 0, !row.failed {
                        Text("\(Int(row.fraction * 100))%").font(.subheadline).monospacedDigit().foregroundStyle(.secondary)
                    }
                }
                if let detail = downloads.detail(row) {
                    Text(detail).font(.subheadline).monospacedDigit().foregroundStyle(.secondary)
                }
                // What went wrong is said in words beside a warning sign, not by color alone (Apple rulebook 4.2).
                if row.failed {
                    Label {
                        Text(row.store.name + " · " + downloads.shownState(row)).font(.subheadline)
                    } icon: {
                        Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.red)
                    }
                } else {
                    Text(row.store.name + " · " + downloads.shownState(row)).font(.subheadline).foregroundStyle(.secondary)
                    ProgressView(value: row.fraction)
                }
            }
            .accessibilityElement(children: .combine)
            buttons(row)
        }
        .id(Self.rowID(row))
    }

    /// Pause or Resume, and Remove. On the Now rows (`speed`) the download speed sits at the trailing end.
    private func buttons(_ row: NewLookDownloads.Row, speed: Bool = false) -> some View {
        HStack(spacing: 12) {
            Group {
                if row.failed {
                    NewLookSmallButton(id: "dl-go-\(row.id)", title: L("Try Again"), symbol: "arrow.clockwise") { downloads.resume(row) }
                } else if downloads.isPaused(row) {
                    NewLookSmallButton(id: "dl-go-\(row.id)", title: L("Resume"), symbol: "arrow.down.circle") { downloads.resume(row) }
                } else {
                    NewLookSmallButton(id: "dl-go-\(row.id)", title: L("Pause"), symbol: "pause.fill") { downloads.pause(row) }
                }
                NewLookSmallButton(id: "dl-remove-\(row.id)", title: L("Remove"), symbol: nil) { downloads.confirm = row }
            }
            .layoutPriority(1)
            Spacer(minLength: 0)
            if speed, let now = downloads.speed(row) { NewLookDownloadSpeed(number: now.number, unit: now.unit) }
        }
    }

    /// The store downloader's steps in their order (each downloader goes preparing, checking,
    /// downloading, finishing; itch.io preparing, downloading, unpacking), the running one with
    /// its percent.
    static func steps(_ row: NewLookDownloads.Row) -> [NewLookStep] {
        let all: [(keys: Set<String>, title: String, symbol: String)] = row.store == .itch
            ? [(["preparing"], L("Get ready"), "hourglass"), (["downloading"], L("Download files"), "arrow.down"),
               (["unpacking"], L("Unpack files"), "shippingbox")]
            : [(["preparing"], L("Get ready"), "hourglass"), (["checking", "verifying"], L("Check files"), "checkmark.shield"),
               (["downloading"], L("Download files"), "arrow.down"), (["finishing"], L("Finish installing"), "folder")]
        let at = all.firstIndex { $0.keys.contains(row.phase) } ?? 0
        return all.enumerated().map { index, step in
            let percent = index == at && row.total > 0 ? String(format: L("In progress · %@%%"), String(Int(row.fraction * 100))) : nil
            return NewLookStep(id: step.title, title: step.title, detail: percent, symbol: step.symbol,
                               state: index < at ? .done : index == at ? .active : .waiting)
        }
    }
}

/// A button in a row (Pause, Remove): Apple's bordered button, 44 points tall (Apple rulebook
/// 9.1). In a list row each bordered button takes its own taps.
struct NewLookSmallButton: View {
    let id: String
    let title: String
    var symbol: String?
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            if let symbol { Label(title, systemImage: symbol) } else { Text(title) }
        }
        .buttonStyle(.bordered).buttonBorderShape(.capsule).controlSize(.large)
        .padItem(id, capsule: true, press: action)
    }
}

/// The Now rows' download speed: a larger number with its unit, read out as one item. Not a button.
struct NewLookDownloadSpeed: View {
    let number: String
    let unit: String
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 4) {
            Text(number).font(.title2.bold()).monospacedDigit()
            Text(unit).font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
        }
        .lineLimit(1).minimumScaleFactor(0.6)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text(String(format: L("Download speed %@ %@"), number, unit)))
    }
}

// MARK: - Stores

/// A store on the Stores tab, and the games you added (Other games).
enum NewLookStore: String, CaseIterable, Identifiable {
    case steam, epic, gog, itch, ea, other
    var id: String { rawValue }
    var name: String {
        switch self {
        case .steam: return "Steam"
        case .epic: return "Epic Games"
        case .gog: return "GOG"
        case .itch: return "itch.io"
        case .ea: return "EA app"
        case .other: return L("Other games")
        }
    }
    /// The letter on its icon until you pick your own picture.
    var letter: String {
        switch self {
        case .steam: return "S"
        case .epic: return "E"
        case .gog: return "G"
        case .itch: return "i"
        case .ea: return "EA"
        case .other: return "+"
        }
    }
    var color: Color {
        switch self {
        case .steam: return Color(red: 0x2f / 255, green: 0x6b / 255, blue: 0xff / 255)
        case .epic: return Color(red: 0x4b / 255, green: 0x4f / 255, blue: 0x5c / 255)
        case .gog: return Color(red: 0x8e / 255, green: 0x44 / 255, blue: 0xe8 / 255)
        case .itch: return Color(red: 0xd9 / 255, green: 0x3a / 255, blue: 0x40 / 255)
        case .ea: return Color(red: 0xd2 / 255, green: 0x4a / 255, blue: 0x22 / 255)
        case .other: return Color(red: 0x5f / 255, green: 0x63 / 255, blue: 0x6e / 255)
        }
    }
    /// The start of its games' ids in LibraryReadyGame.
    var prefix: String { self == .other ? "entry:" : rawValue + ":" }
    /// On in this build and madeira.cfg (each store's own switch).
    @MainActor var enabled: Bool {
        switch self {
        case .steam: return MadeiraDock.enabled
        case .epic: return EpicLibrary.enabled
        case .gog: return GOGLibrary.enabled
        case .itch: return ItchLibrary.enabled
        case .ea: return EALibrary.enabled
        case .other: return true
        }
    }
    /// Signed in (nil for Other games, which has no account).
    @MainActor var signedIn: Bool? {
        switch self {
        case .steam: return SteamOwnedLibrary.enabled && SteamOwnedLibrary.shared.signedIn
        case .epic: return EpicLibrary.shared.signedIn
        case .gog: return GOGLibrary.shared.signedIn
        case .itch: return ItchLibrary.shared.signedIn
        case .ea: return EALibrary.shared.signedIn
        case .other: return nil
        }
    }
    /// How many games the account has (its library as last loaded).
    @MainActor var owned: Int {
        switch self {
        case .steam: return SteamOwnedLibrary.enabled ? SteamOwnedLibrary.shared.owned.count : 0
        case .epic: return EpicLibrary.shared.owned.count
        case .gog: return GOGLibrary.shared.owned.count
        case .itch: return ItchLibrary.shared.owned.count
        case .ea: return EALibrary.shared.owned.count
        case .other: return 0
        }
    }
    @MainActor static var shown: [NewLookStore] { allCases.filter { $0.enabled } }
}

/// The stores' own icons (the pencil on a store's page): a square picture in
/// Documents/madeira-art/store-icon-<store>.png, or the letter on the store's colour.
@MainActor final class NewLookStoreIcons: ObservableObject {
    static let shared = NewLookStoreIcons()
    /// The store the Photos or Files picker was opened for.
    var target: NewLookStore?
    @Published var photos = false
    @Published var files = false
    @Published var error: String?
    @Published private(set) var revision = 0
    private var cache: [NewLookStore: UIImage?] = [:]

    static func url(_ store: NewLookStore) -> URL {
        LibraryModel.documents.appendingPathComponent("madeira-art", isDirectory: true)
            .appendingPathComponent("store-icon-\(store.rawValue).png")
    }

    func image(_ store: NewLookStore) -> UIImage? {
        if let kept = cache[store] { return kept }
        let image = UIImage(contentsOfFile: Self.url(store).path)
        cache[store] = image
        return image
    }

    func has(_ store: NewLookStore) -> Bool { image(store) != nil }

    /// Any picture: the middle square of it, 256 × 256.
    func set(_ store: NewLookStore, data: Data) {
        guard data.count <= 20_000_000 else { error = L("Choose an image smaller than 20 MB."); return }
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
              let picture = CGImageSourceCreateThumbnailAtIndex(source, 0, [kCGImageSourceCreateThumbnailFromImageAlways: true,
                                                                            kCGImageSourceThumbnailMaxPixelSize: 1024,
                                                                            kCGImageSourceCreateThumbnailWithTransform: true] as CFDictionary)
        else { error = L("This image could not be opened."); return }
        let side = min(picture.width, picture.height)
        guard side > 0, let square = picture.cropping(to: CGRect(x: (picture.width - side) / 2, y: (picture.height - side) / 2, width: side, height: side))
        else { error = L("This image could not be opened."); return }
        let format = UIGraphicsImageRendererFormat.default(); format.scale = 1
        let icon = UIGraphicsImageRenderer(size: CGSize(width: 256, height: 256), format: format).image { _ in
            UIImage(cgImage: square).draw(in: CGRect(x: 0, y: 0, width: 256, height: 256))
        }
        do {
            guard let png = icon.pngData() else { throw LibraryError.message(L("This image could not be opened.")) }
            let url = Self.url(store)
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try png.write(to: url, options: .atomic)
            cache[store] = nil
            revision += 1
            LogStore.shared.log("[new-look] store icon: \(store.rawValue) changed")
        } catch { self.error = error.localizedDescription }
    }

    func reset(_ store: NewLookStore) {
        try? FileManager.default.removeItem(at: Self.url(store))
        cache[store] = nil
        revision += 1
        LogStore.shared.log("[new-look] store icon: \(store.rawValue) reset")
    }

    /// A file from the Files app (security-scoped).
    func set(_ store: NewLookStore, file url: URL) {
        let access = url.startAccessingSecurityScopedResource(); defer { if access { url.stopAccessingSecurityScopedResource() } }
        do { set(store, data: try Data(contentsOf: url)) } catch { self.error = error.localizedDescription }
    }
}

/// A store's icon: your picture, or its letter on its colour.
struct NewLookStoreIcon: View {
    let store: NewLookStore
    var size: CGFloat = 30
    @ObservedObject private var icons = NewLookStoreIcons.shared
    var body: some View {
        let shape = RoundedRectangle(cornerRadius: size * 0.27, style: .continuous)
        Group {
            if let image = icons.image(store) {
                Image(uiImage: image).resizable().scaledToFill()
            } else {
                Text(store.letter).font(.system(size: size * (store.letter.count > 1 ? 0.4 : 0.5), weight: .bold, design: .rounded))
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(store.color)
            }
        }
        .frame(width: size, height: size)
        .clipShape(shape)
        .overlay(shape.strokeBorder(Color.white.opacity(0.12), lineWidth: 0.5))
        .id(icons.revision)
        .accessibilityHidden(true)
    }
}

/// The Stores tab, Apple's grouped list: every store, whether you are signed in, and how many
/// of its games are here; then the Windows desktop.
struct NewLookStoresPage: View {
    var top = 0
    let open: (NewLookStore) -> Void
    let desktop: () -> Void
    @ObservedObject private var steam = SteamOwnedLibrary.shared
    @ObservedObject private var epic = EpicLibrary.shared
    @ObservedObject private var gog = GOGLibrary.shared
    @ObservedObject private var itch = ItchLibrary.shared
    @ObservedObject private var ea = EALibrary.shared
    @ObservedObject private var library = LibraryModel.shared
    @ObservedObject private var readyGames = NewLookGames.shared
    var body: some View {
        let stores = NewLookStore.shown
        let accounts = stores.filter { $0.signedIn != nil }
        let signed = accounts.filter { $0.signedIn == true }.count
        let ready = readyGames.all
        NewLookListPage(top: top, topID: stores.first.map { "st-" + $0.rawValue }) {
            Section {
                ForEach(stores) { store in
                    let installed = ready.filter { $0.id.hasPrefix(store.prefix) }.count
                    NewLookLinkRow(id: "st-" + store.rawValue, title: store.name, note: Self.line(store, installed: installed),
                                   value: store.signedIn.map { $0 ? L("Signed in") : L("Not signed in") },
                                   action: { open(store) }) {
                        NewLookStoreIcon(store: store, size: 40)
                    }
                }
            } footer: {
                if !accounts.isEmpty { Text(String(format: L("%@ of %@ signed in"), String(signed), String(accounts.count))) }
            }
            // The Windows desktop: installers and other Windows programs (the old look's Desktop button).
            Section {
                NewLookLinkRow(id: "st-desktop", title: L("Windows Desktop"), note: L("Run installers and other Windows programs."),
                               action: desktop) {
                    NewLookBadge(symbol: "desktopcomputer", color: Color(uiColor: .systemGray))
                }
            }
        }
    }

    /// "3 installed · 120 in your library", "Sign in to see your games", "2 added by you".
    @MainActor static func line(_ store: NewLookStore, installed: Int) -> String {
        guard let signedIn = store.signedIn else {
            return installed > 0 ? String(format: L("%@ added by you"), String(installed)) : L("Add a Windows game you have")
        }
        if !signedIn { return installed > 0 ? String(format: L("%@ installed"), String(installed)) + " · " + L("Sign in to see your games")
                                            : L("Sign in to see your games") }
        let owned = store.owned
        return owned > 0 ? String(format: L("%@ installed · %@ in your library"), String(installed), String(owned))
                         : String(format: L("%@ installed"), String(installed))
    }
}

/// A store page's "Installed" title (0057). The store pages list the games to install first, because the
/// Library tab already has the installed ones; those sit under this title, folded until it is pressed.
/// `open` nil: nothing else is on the page, so the games just show and the title is plain text.
/// Looks like the stores' own "Not installed" title.
struct NewLookInstalledHeader: View {
    let id: String
    let count: Int
    let open: Binding<Bool>?
    var body: some View {
        if let open {
            Button { toggle(open) } label: {
                HStack {
                    words
                    Spacer()
                    Image(systemName: "chevron.right").font(.caption.weight(.semibold))
                        .rotationEffect(.degrees(open.wrappedValue ? 90 : 0)).foregroundStyle(.secondary)
                }.contentShape(Rectangle()).frame(minHeight: 44)
            }.buttonStyle(.plain)
                .accessibilityValue(open.wrappedValue ? "Shown" : "Hidden")
                .padItem(id, cornerRadius: 16) { toggle(open) }
        } else {
            HStack { words; Spacer() }.frame(minHeight: 44).accessibilityElement(children: .combine).accessibilityAddTraits(.isHeader)
        }
    }
    private var words: some View {
        Group {
            Text("Installed").font(.headline)
            Text("\(count)").font(.subheadline).foregroundStyle(.secondary)
        }
    }
    /// At once, like Not installed (Cameron, Nov 7).
    private func toggle(_ open: Binding<Bool>) {
        var instant = Transaction(); instant.disablesAnimations = true
        withTransaction(instant) { open.wrappedValue.toggle() }
        LogStore.shared.log("[new-look] store page: Installed \(open.wrappedValue ? "shown" : "hidden") (\(id))")
    }
}

/// A store's page: its icon (a tap changes it) and whether you are signed in, then the store's
/// own section: sign-in, what is installed or downloading, and Not installed, each opening the
/// store's own sheet. The store's name is the page's large title (Apple rulebook 8.35).
struct NewLookStorePage: View {
    let store: NewLookStore
    let width: CGFloat
    let open: (LibraryEntry) -> Void
    let add: () -> Void
    /// Runs once the page is on screen (opens a game picked in Search).
    var shown: () -> Void = {}
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var steam = SteamOwnedLibrary.shared
    @ObservedObject private var epic = EpicLibrary.shared
    @ObservedObject private var gog = GOGLibrary.shared
    @ObservedObject private var itch = ItchLibrary.shared
    @ObservedObject private var ea = EALibrary.shared
    @ObservedObject private var library = LibraryModel.shared
    @ObservedObject private var readyGames = NewLookGames.shared
    @ObservedObject private var icons = NewLookStoreIcons.shared
    /// Change Icon's choices are up (this page's own, so the same store open in another tab asks nothing).
    @State private var changeIcon = false
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .center, spacing: 12) {
                Button { changeIcon = true } label: {
                    NewLookStoreIcon(store: store, size: 60)
                        .overlay(alignment: .bottomTrailing) {
                            Image(systemName: "pencil.circle.fill").font(.title3)
                                .symbolRenderingMode(.palette).foregroundStyle(.white, Color.accentColor)
                                .offset(x: 6, y: 6)
                        }
                        .padding(6)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(L("Change Icon"))
                .padItem("sp-icon", cornerRadius: 22) { changeIcon = true }
                if let signedIn = store.signedIn {
                    Text(signedIn ? L("Signed in") : L("Not signed in")).font(.subheadline).foregroundStyle(.secondary)
                }
            }
            content
        }
        .padLayer("store", back: { dismiss() }, page: true)
        .task { shown() }
        // Change the icon: Apple's action sheet for the choices about something you just chose
        // to do (Apple rulebook 10.33), then Apple's Photos or Files picker.
        .confirmationDialog(String(format: L("%@ icon"), store.name),
                            isPresented: $changeIcon, titleVisibility: .visible) {
            Button(L("Choose from Photos")) { icons.target = store; icons.photos = true }
            Button(L("Choose from Files")) { icons.target = store; icons.files = true }
            if icons.has(store) { Button(L("Reset Icon"), role: .destructive) { icons.reset(store) } }
            Button(L("Cancel"), role: .cancel) {}
        }
        .background { NewLookPopupLayer(shown: changeIcon) { changeIcon = false } }
    }

    @ViewBuilder private var content: some View {
        switch store {
        case .steam: SteamGamesSection(search: "", layout: "cards", width: width, part: .all, open: open)
        case .epic: EpicGamesSection(search: "", layout: "cards", width: width, open: open)
        case .gog: GOGGamesSection(search: "", layout: "cards", width: width, open: open)
        case .itch: ItchGamesSection(search: "", layout: "cards", width: width, open: open)
        case .ea: EAGamesSection(search: "", layout: "cards", width: width, open: open)
        case .other: otherGames
        }
    }

    /// Other games: the games you added, and Add a game file.
    private var otherGames: some View {
        let games = readyGames.all.filter { $0.id.hasPrefix(NewLookStore.other.prefix) }
        let minimum: CGFloat = width < 600 ? 104 : 132
        let spacing: CGFloat = 12
        let columns = max(2, Int((width + spacing) / (minimum + spacing)))
        let ids = games.map { "og-" + $0.id }
        return VStack(alignment: .leading, spacing: 16) {
            NewLookSheetButton(id: "og-add", title: L("Add a Game File"), symbol: "plus", filled: true, action: add)
                .frame(maxWidth: 360)
            if games.isEmpty {
                Text("Copy a game's folder into Madeira › wine › drive_c with the Files app, then tap Add a Game File and choose its .exe.")
                    .font(.subheadline).foregroundStyle(.secondary)
            } else {
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: spacing, alignment: .top), count: columns),
                          alignment: .leading, spacing: 16) {
                    ForEach(games) { game in
                        Button { open(game.entry) } label: { NewLookCover(game: game) }
                            .buttonStyle(LibraryCardButtonStyle())
                            .padItem("og-" + game.id, cornerRadius: 16, grid: "other") { open(game.entry) }
                    }
                }
                .onAppear { PadHighlight.shared.setGrid("other", ids: ids, columns: columns) }
                .onChange(of: ids) { _, new in PadHighlight.shared.setGrid("other", ids: new, columns: columns) }
                .onChange(of: columns) { _, new in PadHighlight.shared.setGrid("other", ids: ids, columns: new) }
                .onDisappear { PadHighlight.shared.removeGrid("other") }
            }
        }
    }
}

/// Over every tab: the Photos and Files pickers a store's Change Icon opens, and what went
/// wrong with a picture (the choices themselves are Apple's action sheet on the store's page).
struct NewLookOverlays: ViewModifier {
    @ObservedObject private var icons = NewLookStoreIcons.shared
    @State private var picked: PhotosPickerItem?
    func body(content: Content) -> some View {
        content
            .photosPicker(isPresented: $icons.photos, selection: $picked, matching: .images)
            .onChange(of: picked) { _, item in
                guard let item, let store = icons.target else { return }
                picked = nil
                Task { @MainActor in
                    if let data = try? await item.loadTransferable(type: Data.self) { icons.set(store, data: data) }
                    else { icons.error = L("This image could not be opened.") }
                }
            }
            .fileImporter(isPresented: $icons.files, allowedContentTypes: [.image]) { result in
                guard let store = icons.target else { return }
                switch result {
                case .success(let url): icons.set(store, file: url)
                case .failure(let error): icons.error = error.localizedDescription
                }
            }
            .alert(L("Store Icon Not Changed"), isPresented: Binding(get: { icons.error != nil }, set: { if !$0 { icons.error = nil } })) {
                Button(L("OK"), role: .cancel) { icons.error = nil }
            } message: { Text(icons.error ?? "") }
    }
}

/// While one of Apple's own popups is up, the controller's B closes it (Apple rulebook 12.31:
/// B cancels). Its buttons are answered by touch: a note in the Test 8 code says the controller
/// cannot press Apple's popups here (not checked on a device for this rebuild).
struct NewLookPopupLayer: View {
    let shown: Bool
    let close: () -> Void
    var body: some View {
        if shown { Color.clear.frame(width: 0, height: 0).padLayer("popup", back: close) }
    }
}

// MARK: - Library

/// The line under a tab's large title, and what sits beside it. The title itself is Apple's
/// (NewLookTabRoot: it shrinks into the bar as the page scrolls), so `title` is not drawn here.
struct NewLookTitle<Trailing: View>: View {
    let title: String
    var note: String = ""
    @ViewBuilder var trailing: () -> Trailing
    var body: some View {
        if !note.isEmpty || Trailing.self != EmptyView.self {
            // Side by side when both fit on one line; else the pills go under the note.
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .center, spacing: 12) {
                    if !note.isEmpty { Text(note).font(.subheadline).foregroundStyle(.secondary).fixedSize() }
                    Spacer(minLength: 8)
                    trailing()
                }
                VStack(alignment: .leading, spacing: 8) {
                    if !note.isEmpty { Text(note).font(.subheadline).foregroundStyle(.secondary) }
                    trailing()
                }
            }
        }
    }
}
extension NewLookTitle where Trailing == EmptyView {
    init(title: String, note: String = "") { self.init(title: title, note: note) { EmptyView() } }
}

/// Enable JIT from the Library's pill or Settings' row: one start at a time, and a sign that
/// it is starting (Cameron, Test 6: no sign anything happened, three presses started JIT three times).
@MainActor final class NewLookJITStart: ObservableObject {
    static let shared = NewLookJITStart()
    @Published private(set) var starting = false
    private var watch: Task<Void, Never>?

    func start(_ enableJIT: () -> Void) {
        guard !LibraryJITState.shared.enabled, !starting else { return }
        starting = true
        LogStore.shared.log("[new-look] status pill: Enable JIT")
        enableJIT()
        watch?.cancel()
        watch = Task { @MainActor [weak self] in
            // Look at JIT's state again soon after, not at the next 2 s poll. A request that
            // never comes back frees the button again after 15 s (a time limit, not a wait for the screen).
            for step in 0..<30 {
                try? await Task.sleep(for: .milliseconds(500))
                if Task.isCancelled { return }
                if step < 12 { LibraryJITState.shared.refresh() }
                if LibraryJITState.shared.enabled { break }
            }
            self?.starting = false
        }
    }
}

/// Two small pills: JIT (a green dot and "JIT" when on; off, the pill is the Enable JIT button,
/// named for what it does (Apple rulebook 16.18), with a spinner while it starts) and Memory+ (it only shows how things are, as the signed
/// copy of Madeira decides it). Each says its state in words, not by its dot's color alone
/// (Apple rulebook 4.2). Cameron, Test 6: "wherever it says JIT, it should also have the
/// Memory+ thing", and only JIT is selectable.
struct NewLookStatusPill: View {
    let enableJIT: () -> Void
    @ObservedObject private var jit = LibraryJITState.shared
    @ObservedObject private var starter = NewLookJITStart.shared
    @State private var memory: Bool?
    var body: some View {
        let on = jit.enabled
        let starting = starter.starting && !on
        HStack(spacing: 8) {
            if on {
                pill(L("JIT"), symbol: "checkmark.circle.fill", color: .green, busy: false)
                    .accessibilityLabel(L("JIT") + ", " + L("On"))
            } else {
                Button { starter.start(enableJIT) } label: {
                    pill(starting ? L("Enabling JIT…") : L("Enable JIT"), symbol: "bolt.circle.fill", color: .orange, busy: starting)
                        // The pill is 32 points tall; its tap area is 44 (Apple rulebook 9.1).
                        .frame(minHeight: 44).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .disabled(starting)
                .accessibilityValue(L("Off"))
                .padItem("status", capsule: true) { starter.start(enableJIT) }
            }
            // Not a button and never highlighted: Memory+ cannot be turned on from here.
            if let memory {
                pill(L("Memory+"), symbol: memory ? "checkmark.circle.fill" : "minus.circle.fill", color: memory ? .green : .orange, busy: false)
                    .accessibilityLabel(L("Memory+") + ", " + (memory ? L("On") : L("Off")))
            }
        }
        .task { memory = EntitlementStatus.check().increasedMemory }
    }

    /// On and off differ by the symbol's shape as well as its color (Apple rulebook 4.2: never by color alone).
    private func pill(_ text: String, symbol: String, color: Color, busy: Bool) -> some View {
        HStack(spacing: 6) {
            if busy { ProgressView().controlSize(.mini) }
            else { Image(systemName: symbol).font(.footnote.weight(.semibold)).foregroundStyle(color).accessibilityHidden(true) }
            Text(text).font(.subheadline.weight(.semibold)).lineLimit(1).minimumScaleFactor(0.8)
        }
        .padding(.horizontal, 12).frame(minHeight: 32)
        .background(Color(uiColor: .tertiarySystemFill), in: Capsule())
    }
}

/// The Library tab: every installed game from every store and the games you added, last
/// played first, in a grid of covers (Apple rulebook 9.33), with a pop-up button that shows one
/// store's games. Add a Game is the "+" in the bar above (LibraryView.lookStack).
struct NewLookLibraryPage: View {
    let width: CGFloat
    let enableJIT: () -> Void
    let open: (LibraryEntry) -> Void
    let play: (LibraryEntry) -> Void
    let add: () -> Void
    let stores: () -> Void
    /// The ready games, worked out once per change (NewLookGames): a download's progress in any
    /// store no longer redraws this page (ux-review-0044 #7).
    @ObservedObject private var ready = NewLookGames.shared
    @AppStorage("madeiraNewLookStore") private var store = ""
    /// Cover width (a pinch on the covers, or Settings › Appearance › Cover size).
    @AppStorage(NewLook.coverWidthKey) private var coverWidth: Double = 104
    @AppStorage(NewLook.zoomHapticsKey) private var zoomHaptics = true
    /// The pinch in progress: the grid follows the fingers live.
    @State private var pinch: CGFloat?
    /// When a pinch ended: lifting the fingers must not open the cover under them.
    @State private var pinchEnded = Date.distantPast
    /// "Loading your games…" has shown for a while: Try Again shows under it.
    @State private var slowLoad = false
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        let all = ready.all
        // Madeira just opened: Steam's install records are still being read (Cameron, Nov 9: the
        // first screen said "Nothing installed yet" over a library of 23 games).
        let loading = all.isEmpty && MadeiraDock.enabled && !ready.steamScanned
        let storeNames = all.reduce(into: [String]()) { if !$0.contains($1.store) { $0.append($1.store) } }
            .sorted { a, b in a == L("Other games") ? false : b == L("Other games") ? true : a < b }
        let picked = storeNames.contains(store) ? store : ""
        let games = picked.isEmpty ? all : all.filter { $0.store == picked }
        VStack(alignment: .leading, spacing: 16) {
            NewLookTitle(title: L("Library"), note: all.isEmpty ? "" : (games.count == 1 ? L("1 game · last played first") : String(format: L("%@ games · last played first"), String(games.count)))) {
                NewLookStatusPill(enableJIT: enableJIT)
            }
            if loading {
                VStack(spacing: 16) {
                    HStack(spacing: 12) {
                        ProgressView()
                        Text("Loading your games…").foregroundStyle(.secondary)
                    }
                    // A read that never ends must not leave a spinner forever (ux-review-0044 #8):
                    // after a while, say so and offer to read the stores again.
                    if slowLoad {
                        Text("Steam's game list is taking a while.").font(.subheadline).foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                        NewLookSheetButton(id: "lib-retry", title: L("Try Again"), symbol: "arrow.clockwise") {
                            slowLoad = false
                            LogStore.shared.log("[new-look] library: loading again after a slow read")
                            Self.load()
                        }
                        .frame(maxWidth: 320)
                    }
                }
                .frame(maxWidth: .infinity).padding(.vertical, 40)
                // A time limit on the read, not a wait for the screen: it restarts with each try.
                .task(id: slowLoad) {
                    guard !slowLoad else { return }
                    try? await Task.sleep(for: .seconds(8))
                    if !Task.isCancelled { slowLoad = true }
                }
            } else if all.isEmpty {
                // Apple's empty screen, with the next steps (Apple rulebook 16.16).
                ContentUnavailableView {
                    Label(L("Nothing installed yet"), systemImage: "square.grid.2x2")
                } description: {
                    Text("Sign in to a store and install a game, or add a game you copied in.")
                } actions: {
                    NewLookSheetButton(id: "first-stores", title: L("Go to Stores"), symbol: nil, filled: true, action: stores)
                        .frame(maxWidth: 320)
                    NewLookSheetButton(id: "add-game", title: L("Add a Game"), symbol: "plus", action: add)
                        .frame(maxWidth: 320)
                }
                .padding(.vertical, 12)
            } else {
                // The game you played last, big, with Play (Apple Arcade's look; Cameron, Nov 9: banner on
                // top, then the grid). Only under All: one store's games show just the grid. The top
                // card's game is not in the grid below it (Cameron, Nov 11: it showed twice).
                let banner = picked.isEmpty ? all.first.flatMap { $0.played != nil ? $0 : nil } : nil
                if let banner {
                    NewLookBanner(game: banner, wide: width >= 600, play: { play(banner.entry) }, open: { open(banner.entry) })
                }
                if storeNames.count > 1 { storePicker(storeNames, picked: picked) }
                grid(banner.map { top in games.filter { $0.id != top.id } } ?? games)
            }
        }
        // The Library reads every store's installed games when it opens, and again after a game
        // or coming back to Madeira.
        .onAppear { Self.load() }
        .onChange(of: scenePhase) { _, phase in if phase == .active { Self.load() } }
    }

    @MainActor static func load() {
        SteamGamesModel.shared.refresh()
        if SteamOwnedLibrary.enabled { SteamOwnedLibrary.shared.start(); SteamOwnedLibrary.shared.reconcileSession() }
        if EpicLibrary.enabled { EpicLibrary.shared.start(); EpicLibrary.shared.reconcileSession() }
        if GOGLibrary.enabled { GOGLibrary.shared.start(); GOGLibrary.shared.reconcileSession() }
        if ItchLibrary.enabled { ItchLibrary.shared.start(); ItchLibrary.shared.reconcileSession() }
        if EALibrary.enabled { EALibrary.shared.start(); EALibrary.shared.reconcileSession() }
    }

    /// Which store's games show: Apple's pop-up button (Apple rulebook: one of a few options
    /// that are not commands), on the page it filters (11.24). A on it steps to the next store.
    private func storePicker(_ names: [String], picked: String) -> some View {
        Picker(L("Store"), selection: Binding(get: { picked }, set: { store = $0 })) {
            Text(L("All Stores")).tag("")
            ForEach(names, id: \.self) { Text($0).tag($0) }
        }
        .pickerStyle(.menu)
        .frame(minHeight: 44)
        .padItem("lib-store", capsule: true) {
            let all = [""] + names
            store = all[((all.firstIndex(of: picked) ?? 0) + 1) % all.count]
        }
    }

    private func grid(_ games: [LibraryReadyGame]) -> some View {
        let wide = width >= 600
        let minimum = NewLook.coverWidth(coverWidth * Double(pinch ?? 1), wide: wide)
        let spacing: CGFloat = 12
        let columns = max(2, Int((width + spacing) / (minimum + spacing)))
        let ids = games.map(\.padID)
        return LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: spacing, alignment: .top), count: columns),
                         alignment: .leading, spacing: 16) {
            // Identified by the highlight's own ids, so scrolling to a cover not drawn yet works.
            ForEach(games, id: \.padID) { game in
                Button { if pinch == nil, Date().timeIntervalSince(pinchEnded) > 0.4 { open(game.entry) } } label: { NewLookCover(game: game) }
                    .buttonStyle(LibraryCardButtonStyle())
                    // Touch and hold: the same two things a tap and the game's page offer (Apple rulebook 9.19).
                    .contextMenu {
                        Button { play(game.entry) } label: { Label("Play", systemImage: "play.fill") }
                        Button { open(game.entry) } label: { Label("Game Page", systemImage: "info.circle") }
                    }
                    // A opens the game's page, X plays, Menu opens the page too (its settings: Apple rulebook 12.31).
                    .padItem("g-" + game.id, cornerRadius: 16, grid: "library",
                             play: { play(game.entry) }, menu: { open(game.entry) }) { open(game.entry) }
            }
        }
        .onAppear { PadHighlight.shared.setGrid("library", ids: ids, columns: columns) }
        .onChange(of: ids) { _, new in PadHighlight.shared.setGrid("library", ids: new, columns: columns) }
        .onChange(of: columns) { _, new in PadHighlight.shared.setGrid("library", ids: ids, columns: new) }
        .onDisappear { PadHighlight.shared.removeGrid("library") }
        // Pinch: the covers grow or shrink with the fingers, a column at a time, with a click as
        // each one goes (Cameron, Nov 9: steps, too far to pinch, and a cover opened every time).
        // Settings › Appearance › Cover size does the same without a gesture (Apple rulebook 13.2).
        .animation(UIAccessibility.isReduceMotionEnabled ? nil : .spring(response: 0.3, dampingFraction: 0.86), value: columns)
        .sensoryFeedback(.selection, trigger: columns) { _, _ in pinch != nil && zoomHaptics }
        .simultaneousGesture(MagnifyGesture(minimumScaleDelta: 0.02)
            .onChanged { value in pinch = value.magnification }
            .onEnded { value in
                let stored = min(NewLook.coverRange.upperBound, max(NewLook.coverRange.lowerBound, coverWidth * Double(value.magnification)))
                pinch = nil
                pinchEnded = Date()
                coverWidth = stored
                LogStore.shared.log("[new-look] cover size \(Int(stored)) (\(columns) across)")
            })
    }
}

/// The Library's banner: the last-played game's wide art edge to edge in a card, its name and when
/// it was played over a dark fade at the bottom (text over art has its own background: Apple
/// rulebook 9.68), and Play and Game Page as Apple's buttons over it. A game without wide art
/// (not from Steam) shows its cover blurred behind and sharp on the left.
struct NewLookBanner: View {
    let game: LibraryReadyGame
    let wide: Bool
    let play: () -> Void
    let open: () -> Void
    var body: some View {
        let hasHero = game.entry.coverFile == nil && (game.entry.steamID ?? game.entry.steamAppID) != nil
        // Everything sits 16 pt in from the card's edge, so the cover's corners are the card's less 16 (concentric).
        let inset: CGFloat = 16
        ZStack(alignment: .bottomLeading) {
            LibraryArtwork(entry: game.entry, backdrop: true)
                .blur(radius: hasHero ? 0 : 24)
                .overlay {
                    LinearGradient(colors: [.clear, .black.opacity(0.75)], startPoint: .center, endPoint: .bottom)
                }
            HStack(alignment: .bottom, spacing: 16) {
                if !hasHero {
                    LibraryArtwork(entry: game.entry).aspectRatio(2.0 / 3.0, contentMode: .fit)
                        .frame(height: wide ? 168 : 120)
                        .clipShape(RoundedRectangle(cornerRadius: NewLook.cardRadius - inset, style: .continuous))
                        .shadow(color: .black.opacity(0.4), radius: 12, y: 6)
                }
                VStack(alignment: .leading, spacing: 12) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(game.entry.title).font(wide ? .largeTitle.bold() : .title2.bold()).lineLimit(2).minimumScaleFactor(0.7)
                        Text(game.note).font(.subheadline).opacity(0.85).lineLimit(1)
                    }
                    .foregroundStyle(.white)
                    .accessibilityElement(children: .combine)
                    HStack(spacing: 12) {
                        Button(action: play) {
                            Label("Play", systemImage: "play.fill").fontWeight(.semibold).padding(.horizontal, 8)
                        }
                        .modifier(LookPlayStyle(overArt: true))
                        .padItem("banner-play", capsule: true, press: play)
                        Button(action: open) { Text("Game Page").fontWeight(.semibold) }
                            .modifier(LookArtButtonStyle())
                            .environment(\.colorScheme, .dark)
                            .padItem("banner-open", capsule: true, press: open)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(inset)
        }
        .frame(maxWidth: .infinity)
        .frame(height: wide ? 320 : 240)
        .clipShape(RoundedRectangle(cornerRadius: NewLook.cardRadius, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: NewLook.cardRadius, style: .continuous).strokeBorder(Color.white.opacity(0.12), lineWidth: 0.5))
        .shadow(color: .black.opacity(0.3), radius: 14, y: 8)
        .contentShape(RoundedRectangle(cornerRadius: NewLook.cardRadius, style: .continuous))
        .onTapGesture(perform: open)
        .accessibilityElement(children: .contain)
    }
}

/// A cover, the game's name, and its store and when it was played.
struct NewLookCover: View {
    let game: LibraryReadyGame
    @Environment(\.libraryCardPressed) private var pressed
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            LibraryArtwork(entry: game.entry).aspectRatio(2.0 / 3.0, contentMode: .fit)
                .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Color.white.opacity(0.12), lineWidth: 0.5))
                .shadow(color: .black.opacity(0.3), radius: 9, y: 6)
                .scaleEffect(pressed ? 0.95 : 1)
                .animation(.spring(response: 0.3, dampingFraction: 0.7), value: pressed)
            Text(game.entry.title).font(.subheadline.weight(.semibold)).lineLimit(2).foregroundStyle(.primary)
            Text(game.note).font(.footnote).foregroundStyle(.secondary).lineLimit(2)
        }
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityHint(L("Opens the game's page"))
    }
}

/// A full-width button: Apple's bordered button, the prominent one for the screen's main
/// choice (Apple rulebook 9.3: one or two prominent buttons a screen).
struct NewLookSheetButton: View {
    let id: String
    let title: String
    var symbol: String?
    var filled = false
    let action: () -> Void
    var body: some View {
        Group {
            if filled { button.buttonStyle(.borderedProminent) } else { button.buttonStyle(.bordered) }
        }
        .buttonBorderShape(.capsule).controlSize(.large)
        .padItem(id, capsule: true, press: action)
    }
    private var button: some View {
        Button(action: action) {
            Group {
                if let symbol { Label(title, systemImage: symbol) } else { Text(title) }
            }
            .fontWeight(.semibold).frame(maxWidth: .infinity)
        }
    }
}

/// Play's look: Apple's prominent button, a capsule. Over cover art (the Library's banner) on
/// iOS 26 it is Apple's prominent glass (controls over rich content: Apple rulebook 5.5); on a
/// page it is the filled button, because glass stays out of the content (5.1).
struct LookPlayStyle: ViewModifier {
    var overArt = false
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    func body(content: Content) -> some View {
        if #available(iOS 26.0, *), overArt, !reduceTransparency {
            content.buttonStyle(.glassProminent).buttonBorderShape(.capsule).controlSize(.large)
        } else {
            content.buttonStyle(.borderedProminent).buttonBorderShape(.capsule).controlSize(.large)
        }
    }
}

/// A second button over cover art (the banner's Game Page): Apple's glass button on iOS 26,
/// the bordered button before that and with Reduce Transparency.
struct LookArtButtonStyle: ViewModifier {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    func body(content: Content) -> some View {
        if #available(iOS 26.0, *), !reduceTransparency {
            content.buttonStyle(.glass).buttonBorderShape(.capsule).controlSize(.large)
        } else {
            content.buttonStyle(.bordered).buttonBorderShape(.capsule).controlSize(.large).tint(.white)
        }
    }
}

// MARK: - Search

/// What Search finds besides your installed games: a store's games that are not installed,
/// the stores, and the Settings pages.
@MainActor enum NewLookSearch {
    struct StoreGame: Identifiable {
        let store: NewLookStore
        let key: String
        let title: String
        /// The store's own picture of the game (Steam's comes from its app id).
        var cover: URL? = nil
        var id: String { store.rawValue + ":" + key }
    }

    /// Not installed games of every signed-in store whose name matches (at most `limit`).
    static func storeGames(_ query: String, limit: Int = 40) -> [StoreGame] {
        guard !query.isEmpty else { return [] }
        var found: [StoreGame] = []
        if NewLookStore.steam.enabled, SteamOwnedLibrary.enabled, SteamOwnedLibrary.shared.signedIn {
            for item in SteamGamesRules.items(installed: SteamGamesModel.shared.games, owned: SteamOwnedLibrary.shared.owned, search: query)
            where item.installed == nil && item.owned != nil && SteamOwnedLibrary.shared.downloads[item.id] == nil {
                found.append(.init(store: .steam, key: String(item.id), title: item.name))
            }
        }
        if EpicLibrary.enabled, EpicLibrary.shared.signedIn {
            for item in EpicGamesRules.items(EpicLibrary.shared, search: query) where item.installed == nil && item.owned != nil {
                found.append(.init(store: .epic, key: item.id, title: item.title, cover: item.cover))
            }
        }
        if GOGLibrary.enabled, GOGLibrary.shared.signedIn {
            for item in GOGGamesRules.items(GOGLibrary.shared, search: query) where item.installed == nil && item.owned != nil {
                found.append(.init(store: .gog, key: item.id, title: item.title, cover: item.cover))
            }
        }
        if ItchLibrary.enabled, ItchLibrary.shared.signedIn {
            for item in ItchGamesRules.items(ItchLibrary.shared, search: query) where item.installed == nil && item.owned != nil {
                found.append(.init(store: .itch, key: String(item.id), title: item.title, cover: item.cover))
            }
        }
        if EALibrary.enabled, EALibrary.shared.signedIn {
            for item in EAGamesRules.items(EALibrary.shared, search: query) where item.installed == nil && item.owned != nil {
                found.append(.init(store: .ea, key: item.id, title: item.title, cover: item.cover))
            }
        }
        let sorted = found.sorted { $0.title.localizedStandardCompare($1.title) == .orderedAscending }
        return Array(sorted.prefix(limit))
    }

    static func stores(_ query: String) -> [NewLookStore] {
        guard !query.isEmpty else { return [] }
        return NewLookStore.shown.filter { $0.name.localizedCaseInsensitiveContains(query) }
    }

    /// Settings pages by their name or what they are for.
    static func settings(_ query: String) -> [SettingsPages.Page] {
        guard !query.isEmpty else { return [] }
        return SettingsPages.groups.flatMap { $0.1 }.filter { page in
            page.shown && (L(page.title).localizedCaseInsensitiveContains(query) || page.title.localizedCaseInsensitiveContains(query)
                           || page.blurb.localizedCaseInsensitiveContains(query))
        }
    }

    /// Opens a store game's own sheet. The store page calls it from its own .task, so the
    /// section that owns the sheet is already on screen (no timer).
    static func openSheet(_ game: StoreGame) {
        let sheets = LibraryStoreSheets.shared
        switch game.store {
        case .steam: if let id = Int(game.key) { sheets.steamGame = .init(id: id) }
        case .epic: sheets.epicGame = .init(id: game.key)
        case .gog: sheets.gogGame = .init(id: game.key)
        case .itch: if let id = Int(game.key) { sheets.itchGame = .init(id: id) }
        case .ea: sheets.eaGame = .init(id: game.key)
        case .other: break
        }
        LogStore.shared.log("[new-look] search: opened \(game.id)")
    }
}

/// The Search tab, Apple's grouped list: your installed games, the stores' games you have not
/// installed, the stores, and the Settings pages (one place to search everything: Apple rulebook 8.36).
struct NewLookSearchPage: View {
    @Binding var text: String
    var top = 0
    let open: (LibraryEntry) -> Void
    let store: (NewLookStore) -> Void
    let storeGame: (NewLookSearch.StoreGame) -> Void
    let setting: (SettingsPages.Page) -> Void
    @FocusState private var field: Bool
    @ObservedObject private var library = LibraryModel.shared
    @ObservedObject private var ready = NewLookGames.shared
    var body: some View {
        let query = text.trimmingCharacters(in: .whitespaces)
        // Before anything is typed: the games played last, as suggestions (Apple rulebook 8.39).
        let games = query.isEmpty ? Array(ready.all.prefix(6)) : ready.matching(query)
        let others = NewLookSearch.storeGames(query)
        let stores = NewLookSearch.stores(query)
        let pages = NewLookSearch.settings(query)
        let steamDown = !query.isEmpty && NewLookSearchSteamNotice.shows
        let nothing = games.isEmpty && others.isEmpty && stores.isEmpty && pages.isEmpty && !steamDown
        NewLookListPage(top: top, topID: games.first.map { "sr-" + $0.id }) {
            if text.isEmpty { NewLookTypeRow(field: $field) }
            if steamDown { NewLookSearchSteamNotice() }
            if !games.isEmpty {
                Section {
                    ForEach(games) { game in
                        NewLookLinkRow(id: "sr-" + game.id, title: game.entry.title, note: game.note, action: { open(game.entry) }) {
                            LibraryArtwork(entry: game.entry).frame(width: 46, height: 69)
                                .clipShape(RoundedRectangle(cornerRadius: NewLook.badgeRadius, style: .continuous))
                        }
                    }
                } header: { Text(L("Installed")) }
            }
            if !others.isEmpty {
                Section {
                    ForEach(others) { game in
                        NewLookLinkRow(id: "so-" + game.id, title: game.title, note: game.store.name + " · " + L("Not installed"),
                                       action: { storeGame(game) }) {
                            // The game's own picture, as an installed game's row shows its cover
                            // (Cameron, Test 6: these showed the store's icon).
                            NewLookStoreGameArt(game: game).frame(width: 46, height: 69)
                                .clipShape(RoundedRectangle(cornerRadius: NewLook.badgeRadius, style: .continuous))
                        }
                    }
                } header: { Text(L("In your stores")) }
            }
            if !stores.isEmpty {
                Section {
                    ForEach(stores) { item in
                        NewLookLinkRow(id: "ss-" + item.rawValue, title: item.name,
                                       note: item.signedIn.map { $0 ? L("Signed in") : L("Not signed in") } ?? "",
                                       action: { store(item) }) {
                            NewLookStoreIcon(store: item, size: 40)
                        }
                    }
                } header: { Text(L("Stores")) }
            }
            if !pages.isEmpty {
                Section {
                    ForEach(pages, id: \.self) { page in
                        NewLookLinkRow(id: "sp-" + page.key, title: L(page.title), note: page.blurb, action: { setting(page) }) {
                            NewLookBadge(symbol: page.symbol, color: page.color)
                        }
                    }
                } header: { Text(L("Settings")) }
            }
        }
        // Apple's own "no results" screen.
        .overlay { if !query.isEmpty, nothing { ContentUnavailableView.search(text: query) } }
        .modifier(NewLookSearchFocus(field: $field))
        .onAppear {
            // The keyboard comes up at once on an iPhone (a find-fast search tab: Apple rulebook
            // 8.41); on an iPad only with a keyboard attached, so the on-screen one does not
            // cover the page unasked (8.46).
            let waits = UIDevice.current.userInterfaceIdiom == .pad && GCKeyboard.coalesced == nil
            if text.isEmpty, !PadHighlight.shared.shown, !waits { field = true }
        }
        .onDisappear { field = false }
    }
}

/// Search, when Steam could not be asked for the account's games: says so in place, quietly
/// (not an alert: Apple rulebook 10.21, 16.17), says what the results are based on and how to
/// fix it (16.25), with Try Again (16.18). Without it, a Steam game you own but have not
/// installed just does not show, which reads as "you don't own it" (Cameron, Nov 11 2026; the
/// idea is from Madeira's own PR 594, written here from scratch).
struct NewLookSearchSteamNotice: View {
    @ObservedObject private var steam = SteamOwnedLibrary.shared
    /// Steam is on, signed in, and its last request for the account's games failed.
    @MainActor static var shows: Bool {
        NewLookStore.steam.enabled && SteamOwnedLibrary.enabled && SteamOwnedLibrary.shared.signedIn
            && SteamOwnedLibrary.shared.libraryUnreachable != nil
    }
    var body: some View {
        Section {
            Label {
                VStack(alignment: .leading, spacing: 2) {
                    Text(L("Steam Can't Be Reached")).foregroundStyle(Color.primary)
                    Text(detail).font(.subheadline).foregroundStyle(Color.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            } icon: {
                Image(systemName: "wifi.exclamationmark").foregroundStyle(.orange)
            }
            .accessibilityElement(children: .combine)
            Button {
                retry()
            } label: {
                if steam.refreshing {
                    HStack(spacing: 8) { ProgressView(); Text(L("Checking Steam…")) }
                } else {
                    Text(L("Try Again"))
                }
            }
            .disabled(steam.refreshing)
            .padItem("search-steam-retry", cornerRadius: 12, inset: -6) { retry() }
        }
        .onAppear { LogStore.shared.log("[new-look] search: Steam can't be reached notice shown (cached games=\(steam.owned.count))") }
    }
    private var detail: String {
        if let saved = steam.libraryUpdated, !steam.owned.isEmpty {
            return String(format: L("Steam results use the list saved on this device on %@."),
                          saved.formatted(date: .abbreviated, time: .shortened))
        }
        return L("Your Steam games that are not installed can't be searched until Steam can be reached. Check your internet connection.")
    }
    private func retry() {
        guard !steam.refreshing else { return }
        LogStore.shared.log("[new-look] search: Try Again asks Steam for the account's games")
        Task { await SteamOwnedLibrary.shared.refreshLibrary(interactive: false) }
    }
}

/// A not-installed store game's picture in Search: the same cached cover its store's page shows.
/// Without one (the cover cache is off, or the store gave no picture) the store's icon.
struct NewLookStoreGameArt: View {
    let game: NewLookSearch.StoreGame
    var body: some View {
        if LibraryCachedArtwork.enabled, game.store == .steam, let appID = Int(game.key) {
            LibraryCachedArtwork(source: LibraryCoverCache.Source.steam(appID), glyph: nil)
        } else if LibraryCachedArtwork.enabled, let source = LibraryCoverCache.Source.store(game.store.rawValue, game.key, game.cover) {
            LibraryCachedArtwork(source: source, glyph: nil)
        } else {
            NewLookStoreIcon(store: game.store, size: 40)
        }
    }
}

/// Search's "Type a Name" row, only while the controller's highlight shows: the field is Apple's
/// (.searchable on this tab's page, LibraryView.lookStack) and the controller cannot reach it,
/// so the row puts the keyboard up in it (iOS 18: .searchFocused). Its own view, so moving the
/// highlight never redraws the results.
private struct NewLookTypeRow: View {
    var field: FocusState<Bool>.Binding
    @ObservedObject private var pad = PadHighlight.shared
    var body: some View {
        if pad.shown {
            if #available(iOS 18.0, *) {
                Section {
                    Button { field.wrappedValue = true } label: { Label(L("Type a Name"), systemImage: "keyboard") }
                        .padItem("search-field", cornerRadius: 12, inset: -6) { field.wrappedValue = true }
                }
            }
        }
    }
}

/// Ties `field` to the system search field above (iOS 18: .searchFocused). Before iOS 18 the
/// field is focused by a tap only.
private struct NewLookSearchFocus: ViewModifier {
    var field: FocusState<Bool>.Binding
    @ViewBuilder func body(content: Content) -> some View {
        if #available(iOS 18.0, *) { content.searchFocused(field) } else { content }
    }
}

// MARK: - Settings

/// The Settings tab, Apple's grouped list: how things stand (JIT, Memory+, free space, games
/// ready, and Madeira's version), then the Settings pages in their groups, each a row with its
/// coloured icon.
struct NewLookSettingsList: View {
    var top = 0
    let enableJIT: () -> Void
    let open: (SettingsPages.Page) -> Void
    @ObservedObject private var jit = LibraryJITState.shared
    @ObservedObject private var starter = NewLookJITStart.shared
    @ObservedObject private var games = NewLookGames.shared
    @State private var memory: Bool?
    @State private var free: Int64?
    var body: some View {
        NewLookListPage(top: top, topID: jit.enabled ? "set-status" : "status") {
            Section {
                // JIT off: the row is the button that starts it (status sits next to what it
                // describes: Apple rulebook 11.27).
                if jit.enabled {
                    LabeledContent(L("JIT"), value: L("On")).id("set-status")
                } else {
                    Button { starter.start(enableJIT) } label: {
                        HStack {
                            Text(starter.starting ? L("Enabling JIT…") : L("Enable JIT"))
                            Spacer()
                            if starter.starting { ProgressView() }
                        }
                    }
                    .disabled(starter.starting)
                    .padItem("status", cornerRadius: 12, inset: -6) { starter.start(enableJIT) }
                }
                if let memory { LabeledContent(L("Memory+"), value: memory ? L("On") : L("Off")) }
                LabeledContent(L("Free space"), value: free.map { ByteCountFormatter.string(fromByteCount: $0, countStyle: .file) } ?? "–")
                LabeledContent(L("Games ready"), value: String(games.all.count))
            } footer: {
                // Each technical word is said in plain ones (Apple rulebook 16.5).
                Text(L("JIT lets games run fast. Madeira needs it to play.") + " "
                     + L("Memory+ lets games use more of this device's memory. It depends on how this copy of Madeira was signed."))
            }
            ForEach(Array(SettingsPages.groups.enumerated()), id: \.offset) { _, group in
                let pages = group.1.filter(\.shown)
                if !pages.isEmpty {
                    Section {
                        ForEach(pages, id: \.self) { page in
                            NewLookLinkRow(id: "set-" + page.key, title: L(page.title), action: { open(page) }) {
                                NewLookBadge(symbol: page.symbol, color: page.color)
                            }
                        }
                    } header: {
                        if let title = group.0 { Text(L(title)) }
                    }
                }
            }
            Section {
                // Which Madeira is installed (BuildStamp), where a player looks for it and can copy it
                // into a report (Apple rulebook 9.49).
                LabeledContent(L("Version")) { Text(BuildStamp.text).textSelection(.enabled) }
            }
        }
        .task {
            memory = EntitlementStatus.check().increasedMemory
            free = (try? LibraryModel.documents.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey]))?
                .volumeAvailableCapacityForImportantUsage
        }
    }
}

/// A Settings page: B goes back. The page is Apple's grouped form on its own background.
struct NewLookSettingsChrome: ViewModifier {
    @Environment(\.dismiss) private var dismiss
    func body(content: Content) -> some View {
        content.padLayer("settings-page", back: { dismiss() }, page: true)
    }
}

// MARK: - Shared row parts

/// A colored rounded-square icon, as in Apple's Settings. It grows with the text size
/// (Apple rulebook 3.13).
struct NewLookBadge: View {
    let symbol: String
    let color: Color
    @ScaledMetric(relativeTo: .body) private var side: CGFloat = 30
    var body: some View {
        Image(systemName: symbol).font(.system(size: side * 0.5, weight: .semibold)).foregroundStyle(.white)
            .frame(width: side, height: side)
            .background(color, in: RoundedRectangle(cornerRadius: side * 0.27, style: .continuous))
            .accessibilityHidden(true)
    }
}

// MARK: - Installed games

/// Every installed game of every store and the games you added, most recently played first.
struct LibraryReadyGame: Identifiable {
    let id: String
    let entry: LibraryEntry
    let store: String
    /// When it was last played: the later of Madeira's own record (LibraryModel.begin stamps it
    /// at every start) and, for a Steam game, Steam's own (the account's playtime record, which
    /// Valve's client updates when the game runs). The Library's order and its top card follow it
    /// (Cameron, Nov 11: the top card "should be last played"; on Nov 10 it showed a game from
    /// Nov 8 after he had played Borderlands 2).
    var played: Date? = nil
    /// Its id in the Library grid's highlight (and the grid's ForEach, for scrolling to it).
    var padID: String { "g-" + id }

    /// The later of the two records (see `played`).
    static func lastPlayed(_ entry: LibraryEntry, steam: [Int: SteamPlaytime]) -> Date? {
        let own = entry.lastPlayed
        let theirs = entry.steamAppID.flatMap { steam[$0] }.flatMap { $0.lastPlayed > 0 ? Date(timeIntervalSince1970: TimeInterval($0.lastPlayed)) : nil }
        switch (own, theirs) {
        case let (a?, b?): return max(a, b)
        default: return own ?? theirs
        }
    }

    /// "Steam · Played yesterday", "Epic Games · Not played yet".
    var note: String {
        guard let played else { return store + " · " + L("Not played yet") }
        let calendar = Calendar.current
        if calendar.isDateInToday(played) { return store + " · " + L("Played today") }
        if calendar.isDateInYesterday(played) { return store + " · " + L("Played yesterday") }
        return store + " · " + played.formatted(.dateTime.month(.abbreviated).day())
    }

    /// The games you added (Other games): listed in the library and from no store.
    @MainActor static func added() -> [LibraryEntry] {
        LibraryModel.shared.entries.filter { entry in
            entry.desktop != true && entry.listedInLibrary && entry.steamAppID == nil && entry.epicAppName == nil
                && entry.gogProductID == nil && entry.itchGameID == nil && entry.eaOfferID == nil
        }
    }

    @MainActor static func all(search: String) -> [LibraryReadyGame] {
        let library = LibraryModel.shared
        var games: [LibraryReadyGame] = []
        // Steam: every game Steam lists as fully installed, not while it updates.
        if MadeiraDock.enabled {
            for game in SteamGamesModel.shared.games where game.installed && SteamOwnedLibrary.shared.downloads[game.id] == nil {
                games.append(.init(id: "steam:\(game.id)", entry: library.steamEntry(game), store: "Steam"))
            }
        }
        if EpicLibrary.enabled {
            for (app, game) in EpicLibrary.shared.installed where EpicLibrary.shared.downloads[app] == nil {
                games.append(.init(id: "epic:" + app, entry: library.epicEntry(game), store: "Epic Games"))
            }
        }
        if GOGLibrary.enabled {
            for (product, game) in GOGLibrary.shared.installed where GOGLibrary.shared.downloads[product] == nil {
                games.append(.init(id: "gog:" + product, entry: library.gogEntry(game), store: "GOG"))
            }
        }
        if ItchLibrary.enabled {
            for (id, game) in ItchLibrary.shared.installed where ItchLibrary.shared.downloads[id] == nil {
                games.append(.init(id: "itch:\(id)", entry: library.itchEntry(game), store: "itch.io"))
            }
        }
        if EALibrary.enabled {
            for (offer, game) in EALibrary.shared.installed where EALibrary.shared.downloads[offer] == nil {
                games.append(.init(id: "ea:" + offer, entry: library.eaEntry(game), store: "EA app"))
            }
        }
        // The games you added.
        for entry in added() {
            games.append(.init(id: "entry:" + entry.id.uuidString, entry: entry, store: L("Other games")))
        }
        let query = search.trimmingCharacters(in: .whitespaces)
        let steam = SteamOwnedLibrary.shared.playtime
        for i in games.indices { games[i].played = lastPlayed(games[i].entry, steam: steam) }
        return games
            .filter { query.isEmpty || $0.entry.title.localizedCaseInsensitiveContains(query) }
            .sorted {
                if $0.played != $1.played { return ($0.played ?? .distantPast) > ($1.played ?? .distantPast) }
                return $0.entry.title.localizedStandardCompare($1.entry.title) == .orderedAscending
            }
    }
}

/// Every ready game (LibraryReadyGame.all), worked out once when what it is made of changes,
/// not in every page's body on every redraw (ux-review-0044 #7): a download's progress, a
/// keystroke in Search or a move of the highlight no longer rebuilds the list from five stores.
/// The pages read `all` (Search filters it).
@MainActor final class NewLookGames: ObservableObject {
    static let shared = NewLookGames()
    @Published private(set) var all: [LibraryReadyGame] = []
    /// Steam's install records have been read once (SteamGamesModel.scanned).
    @Published private(set) var steamScanned = false
    private var bag = Set<AnyCancellable>()
    private var queued = false

    private init() {
        // What the list is made of. A download's progress changes none of these (only a download
        // starting or ending does), so progress never rebuilds the list.
        var changes: [AnyPublisher<Void, Never>] = [
            LibraryModel.shared.$entries.map { _ in () }.eraseToAnyPublisher(),
            SteamGamesModel.shared.$games.map { $0.filter(\.installed).map(\.id) }.removeDuplicates().map { _ in () }.eraseToAnyPublisher(),
            SteamGamesModel.shared.$scanned.removeDuplicates().map { _ in () }.eraseToAnyPublisher(),
            SteamOwnedLibrary.shared.$downloads.map { Set($0.keys) }.removeDuplicates().map { _ in () }.eraseToAnyPublisher(),
            // Steam's own last-played times (the order follows them too; minutes alone change nothing here).
            SteamOwnedLibrary.shared.$playtime.map { $0.mapValues(\.lastPlayed) }.removeDuplicates().map { _ in () }.eraseToAnyPublisher(),
        ]
        changes.append(EpicLibrary.shared.$installed.map { Set($0.keys) }.removeDuplicates().map { _ in () }.eraseToAnyPublisher())
        changes.append(EpicLibrary.shared.$downloads.map { Set($0.keys) }.removeDuplicates().map { _ in () }.eraseToAnyPublisher())
        changes.append(GOGLibrary.shared.$installed.map { Set($0.keys) }.removeDuplicates().map { _ in () }.eraseToAnyPublisher())
        changes.append(GOGLibrary.shared.$downloads.map { Set($0.keys) }.removeDuplicates().map { _ in () }.eraseToAnyPublisher())
        changes.append(ItchLibrary.shared.$installed.map { Set($0.keys) }.removeDuplicates().map { _ in () }.eraseToAnyPublisher())
        changes.append(ItchLibrary.shared.$downloads.map { Set($0.keys) }.removeDuplicates().map { _ in () }.eraseToAnyPublisher())
        changes.append(EALibrary.shared.$installed.map { Set($0.keys) }.removeDuplicates().map { _ in () }.eraseToAnyPublisher())
        changes.append(EALibrary.shared.$downloads.map { Set($0.keys) }.removeDuplicates().map { _ in () }.eraseToAnyPublisher())
        // LibraryModel and SteamOwnedLibrary are not main-actor classes: hop to the main queue first.
        Publishers.MergeMany(changes)
            .receive(on: DispatchQueue.main)
            .sink { [weak self] in MainActor.assumeIsolated { self?.queue() } }
            .store(in: &bag)
        rebuild()
    }

    /// @Published sends before the value is stored: the list is rebuilt on the main queue's next
    /// turn, once, however many of its parts changed together (not a wait for the screen).
    private func queue() {
        guard !queued else { return }
        queued = true
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.queued = false
            self.rebuild()
        }
    }

    private func rebuild() {
        let games = LibraryReadyGame.all(search: "")
        if games.map(\.id) != all.map(\.id) || games.map(\.played) != all.map(\.played)
            || games.map(\.entry.title) != all.map(\.entry.title) || games.map(\.entry.coverFile) != all.map(\.entry.coverFile) {
            all = games
            // In the log: which game the Library puts first, and when it was played.
            if let first = games.first {
                LogStore.shared.log("[new-look] library order: first=\(first.entry.title) played=\(first.played?.ISO8601Format() ?? "never") (Madeira \(first.entry.lastPlayed?.ISO8601Format() ?? "never")) games=\(games.count)")
            }
        }
        let scanned = SteamGamesModel.shared.scanned
        if scanned != steamScanned { steamScanned = scanned }
    }

    /// The ready games whose name has `query` in it, in the list's order.
    func matching(_ query: String) -> [LibraryReadyGame] {
        let query = query.trimmingCharacters(in: .whitespaces)
        return query.isEmpty ? all : all.filter { $0.entry.title.localizedCaseInsensitiveContains(query) }
    }
}

// MARK: - Starting screen

/// One step of a start on the new look's starting screen (LibraryHUD.newLookLaunch).
struct NewLookStep: Identifiable {
    enum State { case done, active, waiting, failed }
    let id: String
    let title: String
    var detail: String?
    let symbol: String
    var state: State
}

/// A step: its badge, what it is, and done (a tick), running (a spinner), waiting or failed,
/// each also said in words for VoiceOver (Apple rulebook 4.2). On the starting screen it is a
/// tile; `plain` is a row of a list (Downloads).
struct NewLookStepTile: View {
    let step: NewLookStep
    var plain = false
    var body: some View {
        let row = HStack(spacing: 12) {
            NewLookBadge(symbol: step.symbol, color: Color(uiColor: .systemGray))
            VStack(alignment: .leading, spacing: 2) {
                Text(step.title).font(plain ? .body : .body.weight(.semibold))
                if let detail = step.detail, !detail.isEmpty {
                    Text(detail).font(.footnote).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: 8)
            switch step.state {
            case .done:
                Image(systemName: "checkmark.circle.fill").font(.title3).foregroundStyle(.green)
                    .accessibilityLabel(L("Done"))
            case .active:
                ProgressView().accessibilityLabel(L("In progress"))
            case .waiting:
                Image(systemName: "circle").font(.title3).foregroundStyle(.tertiary)
                    .accessibilityLabel(L("Waiting"))
            case .failed:
                Image(systemName: "xmark.circle.fill").font(.title3).foregroundStyle(.red)
                    .accessibilityLabel(L("Stopped"))
            }
        }
        if plain {
            row.accessibilityElement(children: .combine)
        } else {
            row.padding(12)
                .frame(minHeight: 54)
                .background(RoundedRectangle(cornerRadius: NewLook.coverRadius, style: .continuous).fill(fill))
                .accessibilityElement(children: .combine)
        }
    }
    private var fill: Color {
        switch step.state {
        case .active: return Color.accentColor.opacity(0.2)
        case .failed: return Color.red.opacity(0.18)
        default: return Color(uiColor: .tertiarySystemFill)
        }
    }
}
