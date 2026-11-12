// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright 2026 ft7t8drgwf-wq
// Madeira Converter Exception: see LICENSE-EXCEPTION.md
//
//  madeira-crash-reports: Madeira's crashes, freezes and own errors go to the team by
//  themselves (Cameron, Nov 10). What is sent and why no crash handler is installed is in
//  CrashReportsCore.swift; this file is the part that talks to iOS.
//
//  - MetricKit hands over iOS's own crash and hang reports, usually the next time Madeira
//    opens. Each is turned into text, scrubbed (PrivacyScrub) and sent to the Get Help
//    server's POST /crash with the build's key (GetHelp.key); the server passes it to Sentry.
//  - At each start the previous run's log (madeira-log.prev.txt) is read once: the end of
//    its log trail is kept beside the reports (the newest four runs), and its [ERR] lines
//    are sent, each at most once a day.
//  - A report that could not be sent waits in Application Support/CrashReports for the next
//    start, for at most a week.
//
//  Settings › Logs › Send crash reports turns all of it off. A test copy
//  (com.willfaust.madeora.test) also shows two rows that try it.
//

import Foundation
import SwiftUI
import UIKit
import MetricKit
import MachO

enum CrashReports {
    static let onKey = "crash-reports-on"
    private static let seenKey = "crash-reports-seen"
    private static let sentKey = "crash-reports-errors-sent"

    /// Settings › Logs › Send crash reports: on unless the player turned it off.
    static var on: Bool {
        get { UserDefaults.standard.object(forKey: onKey) as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: onKey) }
    }

    private static let queue = DispatchQueue(label: "madeira.crash-reports", qos: .utility)
    private static let subscriber = CrashReportsSubscriber()
    private static var subscribed = false
    private static var scanned = false
    private static let started = Date()
    /// This copy of Madeira and this device, read once on the main thread.
    private static var info = CrashReportsCore.Details(kind: "", appVersion: "", build: "", bundle: "", device: "", os: "")

    private static var folder: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        return base.appendingPathComponent("CrashReports", isDirectory: true)
    }

    // MARK: Start and stop

    /// From the app's first appearance (MadeiraApp), after LogTrail.install().
    @MainActor static func start() {
        guard on, GetHelp.key != nil, !subscribed else { return }
        subscribed = true
        _ = started
        info.appVersion = BuildStamp.text
        info.build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "?"
        info.bundle = Bundle.main.bundleIdentifier ?? "?"
        info.device = CompatReport.device
        info.os = "\(UIDevice.current.systemName) \(UIDevice.current.systemVersion)"
        MXMetricManager.shared.add(subscriber)
        // Reports iOS handed over while nothing was listening (an earlier copy of Madeira).
        let past = MXMetricManager.shared.pastDiagnosticPayloads
        // A few seconds in, so the start of Madeira is not slowed by reading a log.
        queue.asyncAfter(deadline: .now() + 4) {
            resendPending()
            if !scanned { scanPreviousRun() }
            handle(past)
        }
    }

    /// The switch went off: nothing more is read or sent, and what was kept is deleted.
    @MainActor static func stop() {
        guard subscribed else { return }
        subscribed = false
        MXMetricManager.shared.remove(subscriber)
        queue.async { try? FileManager.default.removeItem(at: folder) }
    }

    fileprivate static func received(_ payloads: [MXDiagnosticPayload]) {
        queue.async { handle(payloads) }
    }

    // MARK: iOS's reports

    private static func handle(_ payloads: [MXDiagnosticPayload]) {
        guard on, !payloads.isEmpty else { return }
        if !scanned { scanPreviousRun() }
        var seen = UserDefaults.standard.stringArray(forKey: seenKey) ?? []
        // At most five reports from one hand-over, so an old backlog cannot flood the server.
        var budget = 5
        for payload in payloads {
            let id = CrashReportsCore.hash(payload.jsonRepresentation())
            if seen.contains(id) { continue }
            seen.append(id)
            let from = stamp(payload.timeStampBegin), to = stamp(payload.timeStampEnd)
            for crash in payload.crashDiagnostics ?? [] where budget > 0 {
                budget -= 1
                var d = details("crash", crash, from: from, to: to)
                d.exceptionType = crash.exceptionType?.intValue
                d.exceptionCode = crash.exceptionCode?.intValue
                d.signal = crash.signal?.intValue
                d.termination = crash.terminationReason
                d.memoryRegion = crash.virtualMemoryRegionInfo
                if #available(iOS 17.0, *), let reason = crash.exceptionReason {
                    d.objcName = reason.exceptionName
                    d.objcMessage = PrivacyScrub.text(reason.composedMessage)
                }
                send(d, tree: crash.callStackTree.jsonRepresentation(), at: payload.timeStampEnd)
            }
            for hang in payload.hangDiagnostics ?? [] where budget > 0 {
                let seconds = hang.hangDuration.converted(to: .seconds).value
                guard seconds >= CrashReportsCore.minHangSeconds else { continue }
                budget -= 1
                var d = details("hang", hang, from: from, to: to)
                d.hangSeconds = seconds
                send(d, tree: hang.callStackTree.jsonRepresentation(), at: payload.timeStampEnd)
            }
        }
        UserDefaults.standard.set(Array(seen.suffix(40)), forKey: seenKey)
    }

    private static func details(_ kind: String, _ diagnostic: MXDiagnostic, from: String, to: String) -> CrashReportsCore.Details {
        var d = info
        d.kind = kind
        d.reportBuild = diagnostic.metaData.applicationBuildVersion
        d.from = from
        d.to = to
        return d
    }

    private static func send(_ d: CrashReportsCore.Details, tree: Data, at date: Date) {
        let stacks = CrashReportsCore.stacks(tree)
        let app = Bundle.main.executableURL?.lastPathComponent ?? "Madeira"
        // A frame's name is looked up in the running copy, so only for a report about this build.
        let sameBuild = d.reportBuild.isEmpty || d.reportBuild == d.build
        let trail = tail(near: date)
        let text = CrashReportsCore.report(d, stacks: stacks, symbol: { sameBuild ? symbol($0, app: app) : nil },
                                           tail: trail.lines, tailNote: trail.note)
        let frames = CrashReportsCore.blamed(stacks)?.frames ?? []
        post(CrashReportsCore.Request(kind: d.kind, app_version: d.appVersion, build: d.build, bundle: d.bundle,
                                      device: d.device, os: d.os, title: CrashReportsCore.title(d),
                                      group: CrashReportsCore.group(frames, app: app),
                                      game: CrashReportsCore.game(in: trail.lines),
                                      report: PrivacyScrub.text(text), errors: nil))
    }

    // MARK: A frame's name

    private static var cachedBase: UInt?
    /// Where Madeira's own binary is loaded in this run.
    private static func imageBase(_ app: String) -> UInt? {
        if let cachedBase { return cachedBase }
        for i in 0..<_dyld_image_count() {
            guard let name = _dyld_get_image_name(i), String(cString: name).hasSuffix("/" + app),
                  let header = _dyld_get_image_header(i) else { continue }
            cachedBase = UInt(bitPattern: header)
            return cachedBase
        }
        return nil
    }

    /// The nearest symbol below a frame of Madeira's own binary ("name + bytes"), from the
    /// running copy's symbol table. nil for other binaries.
    private static func symbol(_ frame: CrashReportsCore.Frame, app: String) -> String? {
        guard frame.binary == app, let base = imageBase(app) else { return nil }
        let address = base &+ UInt(truncatingIfNeeded: frame.offset)
        var found = Dl_info()
        guard dladdr(UnsafeRawPointer(bitPattern: address), &found) != 0, let name = found.dli_sname else { return nil }
        let start = UInt(bitPattern: found.dli_saddr)
        return String(cString: name) + (address >= start ? " + \(address - start)" : "")
    }

    // MARK: The log trail

    private static func stamp(_ date: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return f.string(from: date)
    }

    private static func tailFiles() -> [URL] {
        ((try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? [])
            .filter { $0.lastPathComponent.hasPrefix("tail-") }
    }

    /// The trail of the run a report is about: this run's log so far when the report is
    /// from this run (a hang is handed over at once), else the kept trail whose run ended
    /// nearest to the report's time. The note says which, and how far apart the times are.
    private static func tail(near date: Date) -> (lines: [String], note: String) {
        if date > started {
            let log = LogStore.shared.logURL
            let size = ((try? FileManager.default.attributesOfItem(atPath: log.path))?[.size] as? NSNumber)?.uint64Value ?? 0
            let window: UInt64 = 2 << 20
            var scanner = CrashReportsCore.Scanner()
            LogLines.forEach(in: log, fromByte: size > window ? size - window : 0) { scanner.see($0) }
            return (scanner.tail.map { PrivacyScrub.line($0) }, "from this run, up to the report")
        }
        var best: (url: URL, gap: Double, ended: Date)?
        for file in tailFiles() {
            let name = file.deletingPathExtension().lastPathComponent
            guard let seconds = Double(name.dropFirst("tail-".count)) else { continue }
            let ended = Date(timeIntervalSince1970: seconds)
            let gap = abs(ended.timeIntervalSince(date))
            if let current = best, current.gap <= gap { continue }
            best = (file, gap, ended)
        }
        guard let best, let text = try? String(contentsOf: best.url, encoding: .utf8) else {
            return ([], "none was kept for that run")
        }
        let lines = text.split(separator: "\n").map { String($0) }
        return (lines, "from the run whose log ended \(stamp(best.ended)) UTC, \(Int(best.gap)) s from the report's time")
    }

    /// Once per start: the previous run's log gives the end of its trail (kept for a crash
    /// report about that run) and the errors Madeira wrote in it.
    private static func scanPreviousRun() {
        scanned = true
        let fm = FileManager.default
        // LogStore's first use moves the last run's log to madeira-log.prev.txt.
        let previous = LogStore.shared.logURL.deletingLastPathComponent().appendingPathComponent("madeira-log.prev.txt")
        guard let ended = (try? fm.attributesOfItem(atPath: previous.path))?[.modificationDate] as? Date else { return }
        try? fm.createDirectory(at: folder, withIntermediateDirectories: true)
        let target = folder.appendingPathComponent("tail-\(Int(ended.timeIntervalSince1970)).txt")
        // The same run again (nothing was played in between): it was read at an earlier start.
        guard !fm.fileExists(atPath: target.path) else { return }
        var scanner = CrashReportsCore.Scanner()
        LogLines.forEach(in: previous) { scanner.see($0) }
        let tail = scanner.tail.map { PrivacyScrub.line($0) }
        try? tail.joined(separator: "\n").write(to: target, atomically: true, encoding: .utf8)
        for old in tailFiles().sorted(by: { $0.lastPathComponent > $1.lastPathComponent }).dropFirst(4) {
            try? fm.removeItem(at: old)
        }

        let errors = scanner.errors.map { CrashReportsCore.ErrorItem(text: PrivacyScrub.line($0.text), count: $0.count) }
        let record = UserDefaults.standard.dictionary(forKey: sentKey) as? [String: String] ?? [:]
        let picked = CrashReportsCore.fresh(errors, sent: record, today: String(stamp(Date()).prefix(10)))
        UserDefaults.standard.set(picked.sent, forKey: sentKey)
        guard !picked.send.isEmpty else { return }
        var d = info
        d.kind = "errors"
        let text = CrashReportsCore.errorsReport(d, errors: errors, sending: picked.send, tail: tail,
                                                 tailNote: "from the run whose log ended \(stamp(ended)) UTC")
        post(CrashReportsCore.Request(kind: "errors", app_version: d.appVersion, build: d.build, bundle: d.bundle,
                                      device: d.device, os: d.os, title: "", group: "", game: nil,
                                      report: text, errors: picked.send))
    }

    // MARK: Sending

    private static func post(_ request: CrashReportsCore.Request) {
        guard let key = GetHelp.key else { return }
        let body = CrashReportsCore.body(request)
        guard !body.isEmpty else { return }
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let file = folder.appendingPathComponent("pending-\(UUID().uuidString).json")
        try? body.write(to: file, options: .atomic)
        upload(body, key: key, file: file, what: request.kind)
    }

    private static func upload(_ body: Data, key: String, file: URL, what: String) {
        URLSession.shared.dataTask(with: GetHelpCore.urlRequest("crash", key: key, body: body)) { _, response, error in
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            let keep = CrashReportsCore.keepForLater(status: status, failed: error != nil)
            if !keep { try? FileManager.default.removeItem(at: file) }
            LogStore.shared.log("[crash-reports] \(what) report: "
                                + (keep ? "not sent (HTTP \(status)), kept for the next start" : "HTTP \(status)"))
        }.resume()
    }

    /// Reports an earlier start could not send: up to five now, none older than a week.
    private static func resendPending() {
        guard let key = GetHelp.key else { return }
        let fm = FileManager.default
        let files = ((try? fm.contentsOfDirectory(at: folder, includingPropertiesForKeys: [.contentModificationDateKey])) ?? [])
            .filter { $0.lastPathComponent.hasPrefix("pending-") }
        var sent = 0
        for file in files {
            let written = (try? file.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate ?? Date()
            let age = Date().timeIntervalSince(written)
            if age > 7 * 86400 { try? fm.removeItem(at: file); continue }
            // One written a moment ago is still on its way.
            guard age > 60, sent < 5, let body = try? Data(contentsOf: file) else { continue }
            sent += 1
            upload(body, key: key, file: file, what: "kept")
        }
    }

    // MARK: Trying it (test copies)

    /// Ends Madeira with an uncaught exception, the way the Mods folder crash did.
    static func crashNow() {
        LogStore.shared.log("[crash-test] Crash Madeira now was tapped: Madeira ends here on purpose")
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            NSException(name: .internalInconsistencyException,
                        reason: "Crash Madeira now (a test of the crash reports)", userInfo: nil).raise()
        }
    }

    /// One [ERR] line; it is sent at the next start.
    static func testError() {
        LogStore.shared.log("[crash-test] a test error, written from Settings", level: .error)
    }
}

final class CrashReportsSubscriber: NSObject, MXMetricManagerSubscriber {
    func didReceive(_ payloads: [MXDiagnosticPayload]) {
        CrashReports.received(payloads)
    }
}

/// Settings › Logs: the switch, and on a test copy two rows that try it.
struct CrashReportsSection: View {
    @AppStorage(CrashReports.onKey) private var on = true
    @State private var ask = false
    @State private var wrote = false

    var body: some View {
        Section {
            Toggle("Send crash reports", isOn: $on)
                .onChange(of: on) { _, now in
                    if now { CrashReports.start() } else { CrashReports.stop() }
                }
            if DebugLogging.available {
                Button { ask = true } label: { Text(verbatim: "Crash Madeira now (test copy only)") }
                    .confirmationDialog(Text(verbatim: "Madeira will close. Open it again and the crash report is sent."),
                                        isPresented: $ask, titleVisibility: .visible) {
                        Button(role: .destructive) { CrashReports.crashNow() } label: { Text(verbatim: "Crash now") }
                    }
                Button { CrashReports.testError(); wrote = true } label: {
                    Text(verbatim: wrote ? "Test error written. It is sent at the next start." : "Write a test error (test copy only)")
                }
            }
        } footer: {
            Text("When Madeira crashes, freezes or logs an error, a short report goes to Sentry the next time it opens, with all personal details taken out.")
        }
    }
}
