#!/usr/bin/env python3
"""Crash reports: Madeira's crashes, freezes and own errors go to the team by themselves (crash-reports).

Source checks:
1. No crash handler: CrashReports.swift subscribes to MetricKit and installs no signal,
   exception-port or uncaught-exception handler (Wine's iOS layer owns those while a game runs).
2. It sends to the Get Help server's POST /crash with the build's key (GetHelp.key), never a
   Sentry key of its own, and every text it sends goes through PrivacyScrub.
3. It reads only madeira-log.prev.txt and this run's log; no config and no install id is sent.
4. Settings > Logs has the "Send crash reports" switch (on unless turned off); the two rows that
   try it show only on the test bundle; MadeiraApp starts it after the log trail.
5. Both files are in the Xcode project and both new texts have all six languages.

With swiftc (--require-swift makes it required), CrashReportsCore.swift is compiled with
GetHelp.swift and a test main and run: MetricKit's call stack tree, the grouping, the log
scan (errors counted, own lines only, the trail's end), once-a-day errors, the game at the
end of a trail, the titles, the report text and the request body.
"""
from pathlib import Path
import json
import re
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
app = root / 'app/Madeira'
core = (app / 'CrashReportsCore.swift').read_text()
ios = (app / 'CrashReports.swift').read_text()
logs = (app / 'LogsView.swift').read_text()
main_app = (app / 'MadeiraApp.swift').read_text()
pbx = (root / 'app/Madeira.xcodeproj/project.pbxproj').read_text()
strings = json.loads((app / 'Localizable.xcstrings').read_text(encoding='utf-8'))['strings']
failures = []


def check(cond, what):
    print(('PASS: ' if cond else 'FAIL: ') + what)
    if not cond:
        failures.append(what)


# The code without its comments: the comments name the handlers this file must not install.
code = '\n'.join(line.split('//')[0] for line in ios.splitlines())
core_code = '\n'.join(line.split('//')[0] for line in core.splitlines())

# 1. No crash handler.
check('MXMetricManager.shared.add(subscriber)' in code and 'MXMetricManagerSubscriber' in code
      and 'func didReceive(_ payloads: [MXDiagnosticPayload])' in code, 'crash and hang reports come from MetricKit')
for bad in ['sigaction', 'signal(', 'NSSetUncaughtExceptionHandler', 'task_set_exception_ports', 'task_swap_exception_ports',
            'thread_set_exception_ports', 'set_terminate']:
    check(bad not in code and bad not in core_code, f'no {bad.rstrip("(")} (Wine owns the crash hooks)')
check('import Sentry' not in ios and 'import Sentry' not in core, 'no Sentry SDK')

# 2. Where it goes, and scrubbed.
check('GetHelpCore.urlRequest("crash", key: key, body: body)' in code and 'guard let key = GetHelp.key else { return }' in code,
      'reports go to the Get Help server\'s /crash with the build\'s key')
check(not re.search(r'sentry\.io|ingest\.', ios + core, re.I), 'no Sentry address or key in the app')
check('report: PrivacyScrub.text(text)' in code and 'PrivacyScrub.text(reason.composedMessage)' in code,
      'a crash or hang report is scrubbed, the exception\'s words too')
check(code.count('scanner.tail.map { PrivacyScrub.line($0) }') == 2
      and 'CrashReportsCore.ErrorItem(text: PrivacyScrub.line($0.text), count: $0.count)' in code,
      'every trail line and every error line is scrubbed')

# 3. What is read and what is not.
check('"madeira-log.prev.txt"' in code and 'LogStore.shared.logURL' in code, 'it reads the previous run\'s log and this run\'s')
check(not re.search(r'installID|install_id|madeira\.cfg|MadeiraConfig|GameProfile', code + core_code),
      'no install id, no madeira.cfg and no game config')
check('static let maxErrors = 5' in core and 'var budget = 5' in code, 'at most five errors a run and five reports a hand-over')
check('if age > 7 * 86400' in code and 'guard age > 60, sent < 5' in code, 'an unsent report waits a week at most, five resent per start')

# 4. The switch and the start.
check('UserDefaults.standard.object(forKey: onKey) as? Bool ?? true' in code and '@AppStorage(CrashReports.onKey) private var on = true' in code,
      'Send crash reports is on unless the player turned it off')
check('guard on, GetHelp.key != nil, !subscribed else { return }' in code and 'guard on, !payloads.isEmpty else { return }' in code,
      'off (or a build without the key): nothing is read or sent')
check('MXMetricManager.shared.remove(subscriber)' in code and 'try? FileManager.default.removeItem(at: folder)' in code,
      'turning it off stops listening and deletes what was kept')
check('Toggle("Send crash reports", isOn: $on)' in ios and 'CrashReportsSection()' in logs, 'the switch is on the Logs page')
gate = ios.index('if DebugLogging.available {')
check(gate < ios.index('Crash Madeira now (test copy only)') and gate < ios.index('Write a test error (test copy only)')
      and ios.count('CrashReports.crashNow()') == 1 and ios.count('CrashReports.testError()') == 1,
      'the rows that try it show only on the test bundle')
trail_at = main_app.index('LogTrail.install()')
check('CrashReports.start()' in main_app and main_app.index('CrashReports.start()') > trail_at, 'MadeiraApp starts it after the log trail')

# 5. Project and languages.
for name in ['CrashReportsCore.swift', 'CrashReports.swift']:
    check(pbx.count(f'/* {name} */') >= 2 and pbx.count(f'/* {name} in Sources */') == 2, f'{name} is in the Xcode project')
langs = {'de', 'es', 'ko', 'pt-BR', 'ru', 'zh-Hans'}
texts = set(re.findall(r'(?:Text|Toggle)\("([^"\\]+)"', ios))
check(len(texts) == 2, f'two translated texts ({len(texts)} found)')
missing = [t for t in sorted(texts) if set(strings.get(t, {}).get('localizations', {})) < langs]
check(not missing, f'every new text has six languages (missing: {missing})')

# Compile and run.
swiftc = shutil.which('swiftc')
if not swiftc:
    print('SKIP: swiftc not found' + (' (required)' if '--require-swift' in sys.argv else ''))
    if '--require-swift' in sys.argv:
        failures.append('swiftc required')
else:
    test = r'''
import Foundation
var bad = 0
func expect(_ c: Bool, _ what: String) { print((c ? "PASS: " : "FAIL: ") + what); if !c { bad += 1 } }

// MetricKit's call stack tree: two threads, the second one blamed, frames nested under each other.
let tree = """
{"callStackTree":{"callStackPerThread":true,"callStacks":[
 {"threadAttributed":false,"callStackRootFrames":[{"binaryUUID":"A","offsetIntoBinaryTextSegment":10,"sampleCount":1,"binaryName":"libsystem_kernel.dylib","address":1}]},
 {"threadAttributed":true,"callStackRootFrames":[{"binaryUUID":"B","offsetIntoBinaryTextSegment":4096,"sampleCount":1,"binaryName":"CoreFoundation","address":2,
   "subFrames":[{"binaryUUID":"C","offsetIntoBinaryTextSegment":255,"sampleCount":1,"binaryName":"Madeira","address":3,
     "subFrames":[{"binaryUUID":"C","offsetIntoBinaryTextSegment":256,"sampleCount":1,"binaryName":"Madeira","address":4}]}]}]}
]}}
"""
let stacks = CrashReportsCore.stacks(Data(tree.utf8))
expect(stacks.count == 2 && !stacks[0].attributed && stacks[1].attributed, "two threads, the second is the blamed one")
let blamed = CrashReportsCore.blamed(stacks)
expect(blamed?.frames.map { $0.binary } == ["CoreFoundation", "Madeira", "Madeira"], "the blamed thread's frames, in MetricKit's order")
expect(blamed?.frames.map { $0.offset } == [4096, 255, 256], "each frame's offset")
expect(CrashReportsCore.group(blamed?.frames ?? [], app: "Madeira") == "Madeira+ff Madeira+100", "grouped by Madeira's own frames")
expect(CrashReportsCore.group(stacks[0].frames, app: "Madeira") == "libsystem_kernel.dylib+a", "no Madeira frame: grouped by the thread's ends")
expect(CrashReportsCore.stacks(Data("not json".utf8)).isEmpty && CrashReportsCore.stacks(Data("{}".utf8)).isEmpty, "a tree that can't be read gives no threads")
let bare = #"{"callStacks":[{"threadAttributed":true,"callStackRootFrames":[{"binaryName":"Madeira","offsetIntoBinaryTextSegment":16,"sampleCount":3,"subFrames":[{"binaryName":"UIKitCore","offsetIntoBinaryTextSegment":1,"sampleCount":1},{"binaryName":"SwiftUI","offsetIntoBinaryTextSegment":2,"sampleCount":2}]}]}]}"#
let hang = CrashReportsCore.stacks(Data(bare.utf8))
expect(hang.first?.frames.map { $0.binary } == ["Madeira", "SwiftUI"], "a bare tree works, and a branch follows the most sampled frame")
var many: [CrashReportsCore.Frame] = []
for i in 0..<10 { many.append(CrashReportsCore.Frame(binary: "Madeira", offset: UInt64(i), samples: 1)) }
expect(CrashReportsCore.group(many, app: "Madeira") == "Madeira+0 Madeira+1 Madeira+8 Madeira+9", "a long thread is grouped by both ends")

// Reading a log.
let parsed = CrashReportsCore.parse("[13:12:20.701] [ERR] words here")
expect(parsed?.level == "ERR" && parsed?.message == "words here", "a line Madeira wrote: its level and words")
expect(CrashReportsCore.parse("0128:err:module:import_dll Library x.dll not found") == nil
       && CrashReportsCore.parse("[time]") == nil && CrashReportsCore.parse("") == nil
       && CrashReportsCore.parse("[iOS] Arm64JIT: something long enough here") == nil, "Wine's and FEX's lines are not Madeira's")
expect(CrashReportsCore.key("JIT test failed with result: 12 (during: Hades, wine 3.2)") == "JIT test failed with result: #"
       && CrashReportsCore.key("app=620 failed") == CrashReportsCore.key("app=1145360 failed"), "the same error with other numbers is the same error")

var scan = CrashReportsCore.Scanner()
let log = [
    "[10:00:00.000] [INFO] Madeira opened",
    "[10:00:01.000] [INFO] [screen] open Library",
    "0128:err:module:import_dll Library x.dll not found",
    "[10:00:02.000] [ERR] app=620 failed: no depot",
    "[10:00:03.000] [ERR] app=730 failed: no depot",
    "[10:00:04.000] [INFO] [game-start] Hades: config none | memory 5000 MB",
    "[10:00:05.000] [ERR] [crash-reports] nothing of the kind",
    "[10:00:06.000] [ERR] Steam is not installed in this prefix. (during: Hades, wine 2.0)",
    "[10:00:07.000] [INFO] [tap] Play on game page: Hades",
]
for line in log { scan.see(line) }
expect(scan.errors == [CrashReportsCore.ErrorItem(text: "app=620 failed: no depot", count: 2),
                       CrashReportsCore.ErrorItem(text: "Steam is not installed in this prefix. (during: Hades, wine 2.0)", count: 1)],
       "errors are counted, in the order they first came; its own lines are not errors to send")
expect(scan.tail.count == 7 && scan.tail.first == log[1] && scan.tail.last == log[8], "the trail keeps the tagged lines and every error, not Wine's lines")
var long = CrashReportsCore.Scanner()
for i in 0..<1000 { long.see("[10:00:00.000] [INFO] [tap] row \(i)") }
expect(long.tail.count == CrashReportsCore.tailLines && long.tail.last == "[10:00:00.000] [INFO] [tap] row 999", "only the end of a long trail is kept")
expect(CrashReportsCore.game(in: scan.tail) == "Hades", "the game running at the end of the trail")
expect(CrashReportsCore.game(in: scan.tail + ["[10:01:00.000] [INFO] [game-end] Hades: the player quit; exit 0"]) == nil, "none after its [game-end]")
expect(CrashReportsCore.game(in: ["[10:00:04.000] [INFO] [game-start] Stardew Valley (Madeira Dock): config"]) == "Stardew Valley", "a Madeira Dock game's title")

// Each error once a day.
let first = CrashReportsCore.fresh(scan.errors, sent: [:], today: "2026-11-10")
expect(first.send.count == 2 && first.sent.count == 2, "both errors go the first time")
let again = CrashReportsCore.fresh(scan.errors, sent: first.sent, today: "2026-11-10")
expect(again.send.isEmpty && again.sent.count == 2, "not again the same day")
let tomorrow = CrashReportsCore.fresh(scan.errors, sent: first.sent, today: "2026-11-11")
expect(tomorrow.send.count == 2 && tomorrow.sent.values.allSatisfy { $0 == "2026-11-11" }, "again the next day, and the old day's record is dropped")
var lots: [CrashReportsCore.ErrorItem] = []
for i in 0..<9 { lots.append(CrashReportsCore.ErrorItem(text: "error \(["a", "b", "c", "d", "e", "f", "g", "h", "i"][i])", count: 1)) }
expect(CrashReportsCore.fresh(lots, sent: [:], today: "d").send.count == CrashReportsCore.maxErrors, "at most five from one run")

// Titles and the report.
var d = CrashReportsCore.Details(kind: "crash", appVersion: "Test 9", build: "47", bundle: "com.willfaust.madeora", device: "iPhone17,1", os: "iOS 27.1")
d.exceptionType = 1; d.exceptionCode = 0; d.signal = 11
expect(CrashReportsCore.title(d) == "EXC_BAD_ACCESS SIGSEGV", "a crash is titled by its exception and signal")
d.objcName = "NSInvalidArgumentException"; d.objcMessage = "folders can't be copied"
expect(CrashReportsCore.title(d) == "NSInvalidArgumentException: folders can't be copied", "an Objective-C exception by its name and words")
d.reportBuild = "46"; d.from = "2026-11-10 09:00:00"; d.to = "2026-11-10 09:00:00"
let text = CrashReportsCore.report(d, stacks: stacks, symbol: { $0.binary == "Madeira" ? "$s7Madeira4ModsV + 12" : nil }, tail: scan.tail, tailNote: "from the run before")
for piece in ["Madeira crashed", "App: Test 9, build 47 (com.willfaust.madeora)", "Device: iPhone17,1, iOS 27.1", "about build 46",
              "Exception: NSInvalidArgumentException: folders can't be copied", "type 1 (EXC_BAD_ACCESS), code 0, signal 11 (SIGSEGV)",
              "The crashed thread (3 frames", "  1 Madeira +0xff  $s7Madeira4ModsV + 12", "  0 CoreFoundation +0x1000\n", "Other threads: 1",
              "nearest symbol", "log trail, from the run before (7 lines", "[tap] Play on game page: Hades"] {
    expect(text.contains(piece), "the crash report has: \(piece.prefix(50))")
}
var h = CrashReportsCore.Details(kind: "hang", appVersion: "Test 9", build: "47", bundle: "b", device: "iPad16,9", os: "iPadOS 27.1")
h.hangSeconds = 4.6
expect(CrashReportsCore.title(h) == "no answer for 5 s", "a hang is titled by how long")
let hangText = CrashReportsCore.report(h, stacks: [], symbol: { _ in nil }, tail: [], tailNote: "none was kept for that run")
expect(hangText.contains("Madeira froze") && hangText.contains("did not answer for 4.6 seconds") && hangText.contains("iOS gave no call stack.")
       && hangText.contains("log trail: none was kept for that run"), "the hang report, with no stack and no trail")
let errorsText = CrashReportsCore.errorsReport(h, errors: scan.errors, sending: first.send, tail: scan.tail, tailNote: "t")
expect(errorsText.contains("2 different errors in that run. Sent now (each at most once a day): 2.") && errorsText.contains("  2x  app=620 failed: no depot"),
       "the errors report lists each error with its count")

// The request.
let request = CrashReportsCore.Request(kind: "crash", app_version: "Test 9", build: "47", bundle: "b", device: "iPhone17,1", os: "iOS 27.1",
                                       title: String(repeating: "t", count: 500), group: "Madeira+ff", game: "Hades",
                                       report: String(repeating: "line of report\n", count: 10_000), errors: nil)
let body = CrashReportsCore.body(request)
let sent = try! JSONDecoder().decode(CrashReportsCore.Request.self, from: body)
expect(sent.report.utf16.count <= CrashReportsCore.maxReport && sent.report.hasPrefix("line of report") && sent.title.count == 160, "the report and the title are cut to fit")
let keys = Set((try! JSONSerialization.jsonObject(with: body) as! [String: Any]).keys)
expect(keys == ["kind", "app_version", "build", "bundle", "device", "os", "title", "group", "game", "report"], "the request holds these fields and no others")
expect(CrashReportsCore.keepForLater(status: 0, failed: true) && CrashReportsCore.keepForLater(status: 503, failed: false)
       && !CrashReportsCore.keepForLater(status: 200, failed: false) && !CrashReportsCore.keepForLater(status: 429, failed: false)
       && !CrashReportsCore.keepForLater(status: 401, failed: false), "kept for later only when the server was not reached or failed")
expect(CrashReportsCore.hash("abc".utf8) == CrashReportsCore.hash(Data("abc".utf8)) && CrashReportsCore.hash("abc".utf8) != CrashReportsCore.hash("abd".utf8), "the hash")

print(bad == 0 ? "ALL SWIFT CHECKS PASS" : "\(bad) SWIFT CHECK(S) FAILED")
exit(bad == 0 ? 0 : 1)
'''
    with tempfile.TemporaryDirectory() as tmp:
        main = Path(tmp) / 'main.swift'
        main.write_text(test)
        exe = Path(tmp) / 'crash-reports-check'
        build = subprocess.run([swiftc, '-O', str(app / 'CrashReportsCore.swift'), str(app / 'GetHelp.swift'), str(main), '-o', str(exe)],
                               capture_output=True, text=True)
        check(build.returncode == 0, 'CrashReportsCore.swift compiles with swiftc' + ('' if build.returncode == 0 else '\n' + build.stderr[-3000:]))
        if build.returncode == 0:
            run = subprocess.run([str(exe)], capture_output=True, text=True)
            print(run.stdout, end='')
            check(run.returncode == 0, 'the Swift checks pass' + ('' if run.returncode == 0 else '\n' + run.stderr[-2000:]))

print(f'\n{len(failures)} failure(s)' if failures else '\nall checks pass')
sys.exit(1 if failures else 0)
