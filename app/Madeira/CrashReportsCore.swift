// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright 2026 ft7t8drgwf-wq
// Madeira Converter Exception: see LICENSE-EXCEPTION.md
//
//  madeira-crash-reports: what Madeira sends by itself after a crash, a freeze or an
//  error of its own, so the team hears about it without anyone pressing Get Help
//  (Cameron, Nov 10: Test 8 crashed on Mods > Choose a Folder and nothing reached Sentry).
//  Foundation only, so the host check (tests/host/check-crash-reports.py) compiles this
//  file with swiftc on Linux. The part that talks to iOS is CrashReports.swift.
//
//  No crash handler is installed. Wine's iOS layer owns the task's exception ports and
//  the SIGSEGV, SIGBUS, SIGILL, SIGTRAP and SIGABRT handlers while a game runs
//  (build/ntdll-unix/signal_arm64_ios.c), and a second owner would be a risk to games.
//  iOS writes the crash report itself, outside the app, and hands it over through
//  MetricKit the next time Madeira opens. This file turns that report into text.
//
//  Three kinds, all to POST /crash on the Get Help server, which passes them to Sentry:
//    crash   MetricKit's crash report: the reason and the crashed thread's frames
//    hang    MetricKit's hang report: the main thread did not answer for a few seconds
//    errors  the [ERR] lines Madeira wrote in its previous run, each once a day
//  Each carries the last lines of Madeira's log trail ([screen] [tap] [app] [step]
//  [game-start] [game-end] and its own [ERR] lines), scrubbed by PrivacyScrub. Nothing
//  else from the log, no madeira.cfg, no game config and no install id.
//
//  POST /crash  {kind, app_version, build, bundle, device, os, title, group, game, report, errors}
//               -> {ok, sent}
//

import Foundation

enum CrashReportsCore {
    /// The report text is cut to this many UTF-16 units (the server takes 64 KB).
    static let maxReport = 48_000
    /// Different errors sent from one run; the rest are only listed in the report.
    static let maxErrors = 5
    /// Lines of the log trail kept from the end of a run.
    static let tailLines = 150
    /// A hang shorter than this is not sent.
    static let minHangSeconds = 3.0

    // MARK: MetricKit's call stack tree

    struct Frame: Equatable {
        var binary: String
        var offset: UInt64
        var samples: Int
    }

    struct Stack: Equatable {
        /// The thread iOS blames (the crashed one).
        var attributed: Bool
        var frames: [Frame]
    }

    private static func number(_ any: Any?) -> UInt64 {
        if let n = any as? NSNumber { return n.uint64Value }
        if let s = any as? String { return UInt64(s) ?? 0 }
        return 0
    }

    private static func walk(_ node: [String: Any], into frames: inout [Frame]) {
        var node = node
        // A frame's callers (or callees) hang under it; where the tree branches, the branch
        // that was sampled most is followed.
        while frames.count < 400 {
            frames.append(Frame(binary: (node["binaryName"] as? String) ?? "?",
                                offset: number(node["offsetIntoBinaryTextSegment"]),
                                samples: Int(truncatingIfNeeded: number(node["sampleCount"]))))
            let subs = (node["subFrames"] as? [[String: Any]]) ?? []
            guard let next = subs.max(by: { number($0["sampleCount"]) < number($1["sampleCount"]) }) else { return }
            node = next
        }
    }

    /// The threads in MXCallStackTree.jsonRepresentation(), each as a flat list of frames in
    /// the order MetricKit gives them. Unknown or missing fields give fewer frames, never a failure.
    static func stacks(_ data: Data) -> [Stack] {
        guard let top = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return [] }
        let tree = (top["callStackTree"] as? [String: Any]) ?? top
        let list = (tree["callStacks"] as? [[String: Any]]) ?? []
        var out: [Stack] = []
        for stack in list {
            let roots = (stack["callStackRootFrames"] as? [[String: Any]]) ?? []
            guard let root = roots.max(by: { number($0["sampleCount"]) < number($1["sampleCount"]) }) else { continue }
            var frames: [Frame] = []
            walk(root, into: &frames)
            let attributed = (stack["threadAttributed"] as? Bool) ?? (number(stack["threadAttributed"]) != 0)
            out.append(Stack(attributed: attributed, frames: frames))
        }
        return out
    }

    /// The thread to show first: the one iOS blames, else the first.
    static func blamed(_ stacks: [Stack]) -> Stack? {
        stacks.first(where: { $0.attributed }) ?? stacks.first
    }

    /// What Sentry groups by: Madeira's own frames at both ends of the thread (MetricKit
    /// does not promise which end is the crash), or the thread's ends when none is Madeira's.
    static func group(_ frames: [Frame], app: String) -> String {
        let own = frames.filter { $0.binary == app }
        let pick = own.isEmpty ? frames : own
        let ends = pick.count <= 4 ? pick : Array(pick.prefix(2)) + Array(pick.suffix(2))
        return ends.map { "\($0.binary)+\(String($0.offset, radix: 16))" }.joined(separator: " ")
    }

    // MARK: Names

    static func exceptionName(_ type: Int) -> String {
        let names = [1: "EXC_BAD_ACCESS", 2: "EXC_BAD_INSTRUCTION", 3: "EXC_ARITHMETIC", 4: "EXC_EMULATION",
                     5: "EXC_SOFTWARE", 6: "EXC_BREAKPOINT", 7: "EXC_SYSCALL", 8: "EXC_MACH_SYSCALL",
                     9: "EXC_RPC_ALERT", 10: "EXC_CRASH", 11: "EXC_RESOURCE", 12: "EXC_GUARD", 13: "EXC_CORPSE_NOTIFY"]
        return names[type] ?? "exception \(type)"
    }

    static func signalName(_ signal: Int) -> String {
        let names = [1: "SIGHUP", 2: "SIGINT", 3: "SIGQUIT", 4: "SIGILL", 5: "SIGTRAP", 6: "SIGABRT", 8: "SIGFPE",
                     9: "SIGKILL", 10: "SIGBUS", 11: "SIGSEGV", 12: "SIGSYS", 13: "SIGPIPE", 14: "SIGALRM", 15: "SIGTERM"]
        return names[signal] ?? "signal \(signal)"
    }

    // MARK: The report

    /// What iOS said about one crash or hang, and which Madeira this is.
    struct Details: Equatable {
        var kind: String              // "crash" or "hang"
        var appVersion: String        // the build's own stamp (BuildStamp.text)
        var build: String
        var bundle: String
        var device: String
        var os: String
        /// The build the report is about (MetricKit's own record); it can be an older one.
        var reportBuild: String = ""
        var from: String = ""
        var to: String = ""
        var exceptionType: Int? = nil
        var exceptionCode: Int? = nil
        var signal: Int? = nil
        var termination: String? = nil
        var memoryRegion: String? = nil
        var objcName: String? = nil
        var objcMessage: String? = nil
        var hangSeconds: Double? = nil
    }

    /// A few words for the Sentry title.
    static func title(_ d: Details) -> String {
        if d.kind == "hang" { return "no answer for \(Int((d.hangSeconds ?? 0).rounded())) s" }
        if let name = d.objcName, !name.isEmpty {
            let words = (d.objcMessage ?? "").replacingOccurrences(of: "\n", with: " ")
            return words.isEmpty ? name : name + ": " + String(words.prefix(100))
        }
        var parts: [String] = []
        if let type = d.exceptionType { parts.append(exceptionName(type)) }
        if let signal = d.signal { parts.append(signalName(signal)) }
        return parts.isEmpty ? "no reason given" : parts.joined(separator: " ")
    }

    private static func head(_ d: Details, _ first: String) -> [String] {
        var lines = [first,
                     "App: \(d.appVersion), build \(d.build) (\(d.bundle))",
                     "Device: \(d.device), \(d.os)"]
        if !d.reportBuild.isEmpty, d.reportBuild != d.build {
            lines.append("The report is about build \(d.reportBuild), an earlier copy of Madeira: the names beside the frames are left out.")
        }
        if !d.from.isEmpty || !d.to.isEmpty { lines.append("iOS made the report between \(d.from) and \(d.to) (UTC)") }
        return lines
    }

    private static func frameLines(_ frames: [Frame], limit: Int, symbol: (Frame) -> String?) -> [String] {
        var lines: [String] = []
        for (i, frame) in frames.prefix(limit).enumerated() {
            var line = "  \(i) \(frame.binary) +0x\(String(frame.offset, radix: 16))"
            if let name = symbol(frame), !name.isEmpty { line += "  " + name }
            lines.append(line)
        }
        if frames.count > limit { lines.append("  ... \(frames.count - limit) more") }
        return lines
    }

    /// The text for a crash or a hang. `symbol` names a frame of this same build (nil for
    /// the rest); `tail` is the log trail from the run it happened in, `tailNote` says which run.
    static func report(_ d: Details, stacks: [Stack], symbol: (Frame) -> String?, tail: [String], tailNote: String) -> String {
        var lines = head(d, d.kind == "hang" ? "Madeira froze (sent by itself, from iOS's own hang report)"
                                             : "Madeira crashed (sent by itself, from iOS's own crash report)")
        lines.append("")
        if d.kind == "hang" {
            lines.append("The main thread did not answer for \(String(format: "%.1f", d.hangSeconds ?? 0)) seconds.")
        } else {
            if let name = d.objcName, !name.isEmpty { lines.append("Exception: \(name): \(d.objcMessage ?? "")") }
            var reason: [String] = []
            if let type = d.exceptionType { reason.append("type \(type) (\(exceptionName(type)))") }
            if let code = d.exceptionCode { reason.append("code \(code)") }
            if let signal = d.signal { reason.append("signal \(signal) (\(signalName(signal)))") }
            if !reason.isEmpty { lines.append("Reason: " + reason.joined(separator: ", ")) }
            if let words = d.termination, !words.isEmpty { lines.append("iOS's words: \(words)") }
            if let region = d.memoryRegion, !region.isEmpty { lines.append("Memory: \(region)") }
        }
        lines.append("")
        if let main = blamed(stacks) {
            lines.append((d.kind == "hang" ? "The thread that did not answer" : "The crashed thread")
                         + " (\(main.frames.count) frames, in the order iOS gives them):")
            lines += frameLines(main.frames, limit: 60, symbol: symbol)
            if main.frames.prefix(60).contains(where: { symbol($0) != nil }) {
                lines.append("  (A name beside a frame is the nearest symbol below it in the running copy of Madeira.)")
            }
            let others = stacks.filter { $0 != main }
            if !others.isEmpty {
                lines.append("")
                lines.append("Other threads: \(others.count). The first frames of up to 8 of them:")
                for (i, other) in others.prefix(8).enumerated() {
                    lines.append(" thread \(i + 1):")
                    lines += frameLines(other.frames, limit: 6, symbol: symbol)
                }
            }
        } else {
            lines.append("iOS gave no call stack.")
        }
        lines.append("")
        lines += trailBlock(tail, note: tailNote)
        return lines.joined(separator: "\n") + "\n"
    }

    private static func trailBlock(_ tail: [String], note: String) -> [String] {
        guard !tail.isEmpty else { return ["Madeira's log trail: " + note] }
        return ["Madeira's log trail, \(note) (\(tail.count) lines, personal details taken out):"] + tail
    }

    /// The text for the errors of one run.
    static func errorsReport(_ d: Details, errors: [ErrorItem], sending: [ErrorItem], tail: [String], tailNote: String) -> String {
        var lines = head(d, "Errors Madeira wrote in its log (sent by itself at the next start)")
        lines.append("")
        lines.append("\(errors.count) different error\(errors.count == 1 ? "" : "s") in that run. Sent now (each at most once a day): \(sending.count).")
        for item in errors.prefix(30) {
            lines.append("  \(item.count)x  \(item.text)")
        }
        if errors.count > 30 { lines.append("  ... \(errors.count - 30) more") }
        lines.append("")
        lines += trailBlock(tail, note: tailNote)
        return lines.joined(separator: "\n") + "\n"
    }

    // MARK: Reading a run's log

    struct ErrorItem: Codable, Equatable {
        var text: String
        var count: Int
    }

    /// The lines kept as the trail (beside every [ERR] line).
    static let trailTags = ["[screen]", "[tap]", "[pad]", "[focus]", "[app]", "[step]", "[game-start]", "[game-end]",
                            "[last-run]", "[thermal]", "[crash-test]"]

    /// "[13:12:20.701] [ERR] words" -> ("ERR", "words"); nil for a line Madeira did not write itself.
    static func parse(_ line: String) -> (level: String, message: String)? {
        let u = line.utf8
        guard u.count > 18, u.first == 0x5B else { return nil }
        let bytes = Array(u.prefix(24))
        guard bytes[1] >= 0x30, bytes[1] <= 0x39, bytes[13] == 0x5D, bytes[14] == 0x20, bytes[15] == 0x5B else { return nil }
        guard let close = bytes[16...].firstIndex(of: 0x5D), close > 16 else { return nil }
        let level = String(decoding: bytes[16..<close], as: UTF8.self)
        let message = String(decoding: u.dropFirst(close + 2), as: UTF8.self)
        return (level, message)
    }

    /// The same error with other numbers in it is the same error. What was going on
    /// ("(during: ...)", LogTrail) is not part of it.
    static func key(_ message: String) -> String {
        var text = message
        if let cut = text.range(of: " (during: ") { text = String(text[..<cut.lowerBound]) }
        var out = ""
        var inNumber = false
        for c in text.unicodeScalars {
            let digit = c.value >= 0x30 && c.value <= 0x39
            if digit {
                if !inNumber { out.unicodeScalars.append("#") }
                inNumber = true
            } else {
                inNumber = false
                out.unicodeScalars.append(c)
            }
            if out.unicodeScalars.count >= 200 { break }
        }
        return out
    }

    /// One pass over a run's log: its errors, counted, and the end of its trail.
    struct Scanner {
        private(set) var order: [String] = []
        private(set) var found: [String: ErrorItem] = [:]
        private(set) var kept: [String] = []

        mutating func see(_ line: String) {
            guard let (level, message) = CrashReportsCore.parse(line) else { return }
            let isError = level == "ERR"
            guard isError || CrashReportsCore.trailTags.contains(where: { message.contains($0) }) else { return }
            kept.append(line.count > 600 ? String(line.prefix(600)) + "…" : line)
            if kept.count > CrashReportsCore.tailLines * 2 { kept.removeFirst(kept.count - CrashReportsCore.tailLines) }
            // Its own lines are never an error to send, or one failed send would report the next.
            guard isError, !message.hasPrefix("[crash-reports]") else { return }
            let key = CrashReportsCore.key(message)
            if var item = found[key] {
                item.count += 1
                found[key] = item
            } else if order.count < 200 {
                order.append(key)
                found[key] = ErrorItem(text: message.count > 400 ? String(message.prefix(400)) + "…" : message, count: 1)
            }
        }

        /// In the order they first appeared.
        var errors: [ErrorItem] { order.compactMap { found[$0] } }
        var tail: [String] { Array(kept.suffix(CrashReportsCore.tailLines)) }
    }

    /// The game that was running at the end of a trail: the last [game-start] with no
    /// [game-end] after it. The title ends at the first ": " (a title with one is cut short).
    static func game(in tail: [String]) -> String? {
        var title: String?
        for line in tail {
            if let start = line.range(of: "[game-start] ") {
                var name = String(line[start.upperBound...])
                if let end = name.range(of: ": ") { name = String(name[..<end.lowerBound]) }
                if name.hasSuffix(" (Madeira Dock)") { name = String(name.dropLast(" (Madeira Dock)".count)) }
                title = String(name.prefix(100))
            } else if line.contains("[game-end] ") {
                title = nil
            }
        }
        return title
    }

    // MARK: Once a day

    static func hash(_ bytes: some Sequence<UInt8>) -> String {
        var h: UInt64 = 0xcbf2_9ce4_8422_2325
        for b in bytes {
            h ^= UInt64(b)
            h = h &* 0x0000_0100_0000_01b3
        }
        return String(h, radix: 16)
    }

    /// The errors not sent yet today, at most `maxErrors`, and the record to keep
    /// (error hash -> day; other days' entries are dropped).
    static func fresh(_ errors: [ErrorItem], sent: [String: String], today: String) -> (send: [ErrorItem], sent: [String: String]) {
        var record = sent.filter { $0.value == today }
        var send: [ErrorItem] = []
        for item in errors {
            guard send.count < maxErrors else { break }
            let id = hash(key(item.text).utf8)
            if record[id] != nil { continue }
            record[id] = today
            send.append(item)
        }
        return (send, record)
    }

    // MARK: The request

    struct Request: Codable, Equatable {
        var kind: String
        var app_version: String
        var build: String
        var bundle: String
        var device: String
        var os: String
        /// A few words for the title, and what to group by (both empty for errors).
        var title: String
        var group: String
        /// The game running at the end of the trail, if one was.
        var game: String?
        var report: String
        var errors: [ErrorItem]?
    }

    static func body(_ request: Request) -> Data {
        var r = request
        r.report = GetHelpCore.clip(r.report, max: maxReport)
        r.title = String(r.title.prefix(160))
        r.group = String(r.group.prefix(300))
        r.app_version = String(r.app_version.prefix(40))
        if let game = r.game { r.game = String(game.prefix(100)) }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return (try? encoder.encode(r)) ?? Data()
    }

    /// Kept for the next start: only when the server was not reached or failed by itself.
    /// A refusal (a limit, a bad request, a wrong key) is final.
    static func keepForLater(status: Int, failed: Bool) -> Bool {
        failed || status == 0 || status >= 500
    }
}
