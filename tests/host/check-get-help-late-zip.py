#!/usr/bin/env python3
"""Get Help: the log zip survives Madeira closing and goes on the next open (late-zip).

Source checks:
1. GetHelpUpload.send claims the request id, then saves <id>.json in Application Support/
   get-help-pending/ BEFORE it waits for the game or zips; the made zip is moved there as <id>.zip.
2. After the upload, a final answer (2xx, 404, any other 4xx) deletes both files; no answer,
   a time-out or a 5xx keeps them and logs "upload kept for next open".
3. MadeiraApp starts the resend; it runs once, in the background, a few seconds after launch,
   needs the key, sends at most 3 one at a time, makes a missing zip from the saved fields,
   deletes old or unreadable ones, and never sends an id that is already uploading.

With swiftc (--require-swift makes it required), GetHelp.swift is compiled with a test main
and run: safe ids and file names, the 7-day age check, which answers are final, the saved
fields round-trip, and the launch plan (oldest first, at most 3, the rest deleted).
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
app = root / 'app/Madeira'
core = (app / 'GetHelp.swift').read_text()
view = (app / 'GetHelpView.swift').read_text()
main_app = (app / 'MadeiraApp.swift').read_text()
failures = []


def check(cond, what):
    print(('PASS: ' if cond else 'FAIL: ') + what)
    if not cond:
        failures.append(what)


def body(src, start, end):
    i = src.find(start)
    if i < 0:
        return ''
    j = src.find(end, i + len(start))
    return src[i:j if j > 0 else len(src)]


send = body(view, 'static func send(requestID: String, title: String', 'static func upload(zip:')
# 1. Saved before waiting or zipping.
check('static let folderName = "get-help-pending"' in core and '.applicationSupportDirectory' in body(view, 'static var pendingFolder', '}\n\n'),
      'the pending folder is Application Support/get-help-pending')
check('guard GetHelpCore.Late.safeID(requestID), claim(requestID) else { return }' in send, 'send claims the id first')
i_save, i_wait, i_make = send.find('savePending(pending)'), send.find('while LogTrail.isRunning(title)'), send.find('make(title:')
check(0 <= i_save < i_wait < i_make, 'the .json is written before any waiting or zipping')
check('let zip = made.map { keepZip($0, requestID) }' in send and 'GetHelpCore.Late.zipName(id)' in view
      and 'moveItem(at: made, to: target)' in view, 'the made zip is moved into the pending folder as <id>.zip')
for field in ['requestID', 'title', 'windowsPath', 'report', 'gameText', 'device', 'created']:
    check(f'var {field}: ' in body(core, 'struct Pending: Codable', '}'), f'the saved fields include {field}')

# 2. After the upload.
check('settle(requestID, status: status)' in send and 'removeItem(at: zip)' not in send, 'send leaves deleting to settle (no delete before the answer)')
settle = body(view, 'private static func settle(', 'static func resendLate')
check('case .done:' in settle and 'removePending(id)' in settle and 'case .keep:' in settle
      and '"[get-help] upload kept for next open"' in settle and 'release(id)' in settle, 'final answers delete, others keep and log it')
check('(200..<300).contains(status) || (400..<500).contains(status)' in core and 'status > 0 else { return .keep }' in core,
      '2xx and 4xx are final, no answer is not')
check('"x-request-id"' in view and '"x-madeira-key"' in view and 'appendingPathComponent("upload")' in view, 'the same POST /upload with key and request id')

# 3. On the next open.
check('GetHelpUpload.resendLate()' in main_app and main_app.find('LogTrail.install()') < main_app.find('GetHelpUpload.resendLate()'),
      'MadeiraApp starts the resend after the log trail')
check('private static let resendOnce: Void = {' in view and 'guard GetHelp.enabled, GetHelp.key != nil else { return }' in view,
      'once per run, only with the key (and Get Help on)')
check('DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + GetHelpCore.Late.startDelay)' in view
      and 'static let startDelay: TimeInterval = 5' in core, 'in the background, 5 seconds after launch')
late = body(view, 'private static func resendLateNow()', '    }\n}')
check('if claimed(id) || items[id] != nil { continue }' in late and 'guard claim(id) else { continue }' in late,
      'an id already uploading is never sent twice')
check('if zip == nil {' in late and 'zip = make(title: pending.title' in late, 'no zip (closed while waiting or zipping): made now from the saved fields')
check('finished.wait()' in late and 'DispatchSemaphore(value: 0)' in late, 'one at a time')
check('static let perLaunch = 3' in core and 'Array(send.prefix(perLaunch))' in core, 'at most 3 per launch')
check('for id in plan.delete {' in late and 'removePending(id)' in late, 'old or unreadable ones are deleted')
check('"[get-help] resent late zip \\(GetHelpCore.Late.short(id)): HTTP \\(status)' in late, 'the resend is logged with the short id and the HTTP code')
check('nonisolated(unsafe) private static var inFlight = Set<String>()' in view and 'inFlightLock.lock()' in view, 'the in-flight set is behind a lock')

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
typealias L = GetHelpCore.Late

let id = "6f1c2b9e-0000-4000-8000-000000000000"
expect(L.safeID(id) && !L.safeID("") && !L.safeID("../x") && !L.safeID("a/b") && !L.safeID("a.json") && !L.safeID(String(repeating: "a", count: 81)),
       "only letters, digits and - make a request id")
expect(L.jsonName(id) == id + ".json" && L.zipName(id) == id + ".zip", "<id>.json and <id>.zip")
expect(L.id(fromFileName: id + ".json") == id && L.id(fromFileName: id + ".zip") == id, "a pending file's id from its name")
expect(L.id(fromFileName: ".DS_Store") == nil && L.id(fromFileName: id + ".zip.tmp") == nil && L.id(fromFileName: "a b.json") == nil, "other files are not ours")
expect(L.short(id) == "6f1c2b9e", "the short id is its first 8")

let now = Date(timeIntervalSince1970: 2_000_000_000)
expect(L.fresh(now.addingTimeInterval(-60), now: now), "a minute old: send")
expect(L.fresh(now.addingTimeInterval(-6.9 * 86400), now: now), "6.9 days old: send")
expect(!L.fresh(now.addingTimeInterval(-7 * 86400), now: now), "7 days old: too old")
expect(!L.fresh(now.addingTimeInterval(3 * 86400), now: now), "3 days ahead of the clock: not trusted")

for s in [200, 201, 204, 299] { expect(L.verdict(status: s) == .done, "HTTP \(s): arrived") }
for s in [400, 401, 404, 413, 499] { expect(L.verdict(status: s) == .done, "HTTP \(s): final") }
for s in [0, 500, 502, 503, 599] { expect(L.verdict(status: s) == .keep, "HTTP \(s): keep for next open") }
expect(L.verdict(status: nil) == .keep, "no answer: keep")

let p = GetHelpCore.Pending(requestID: id, title: "Pizza Tower", windowsPath: "C:\\Games\\PT.exe", report: "## report\né ✓",
                            gameText: nil, device: "iPad\nMadeira x", created: now)
expect(L.encode(p).flatMap(L.decode) == p, "the saved fields round-trip (no game config)")
var q = p; q.gameText = "pool = 256"
expect(L.encode(q).flatMap(L.decode) == q, "the saved fields round-trip (with the game config)")
expect(L.decode(Data("not json".utf8)) == nil, "an unreadable file: nil")
var evil = p; evil.requestID = "../../x"
expect(L.encode(evil).flatMap(L.decode) == nil, "a saved id that is not safe: nil")

func make(_ n: Int, ageDays: Double) -> GetHelpCore.Pending {
    var x = p; x.requestID = "id-\(n)"; x.created = now.addingTimeInterval(-ageDays * 86400); return x
}
var items: [String: GetHelpCore.Pending?] = [:]
for (n, age) in [(1, 0.5), (2, 3.0), (3, 0.1), (4, 6.0), (5, 1.0)] { items["id-\(n)"] = .some(make(n, ageDays: age)) }
items["id-old"] = .some({ var x = make(0, ageDays: 8); x.requestID = "id-old"; return x }())
items["id-broken"] = .some(nil)
items["id-other"] = .some(make(9, ageDays: 1))   // its .json says another id
let plan = L.plan(items, now: now)
expect(plan.send.map(\.requestID) == ["id-4", "id-2", "id-5"], "at most 3, oldest first (\(plan.send.map(\.requestID)))")
expect(plan.delete == ["id-broken", "id-old", "id-other"], "too old, unreadable or mismatched: deleted (\(plan.delete))")
expect(L.plan([:], now: now).send.isEmpty, "nothing pending: nothing sent")

print(bad == 0 ? "ALL SWIFT CHECKS PASS" : "\(bad) SWIFT CHECK(S) FAILED")
exit(bad == 0 ? 0 : 1)
'''
    with tempfile.TemporaryDirectory() as tmp:
        main = Path(tmp) / 'main.swift'
        main.write_text(test)
        exe = Path(tmp) / 'get-help-late-zip-check'
        build = subprocess.run([swiftc, '-O', str(app / 'GetHelp.swift'), str(main), '-o', str(exe)],
                               capture_output=True, text=True)
        check(build.returncode == 0, 'GetHelp.swift compiles with swiftc' + ('' if build.returncode == 0 else '\n' + build.stderr[-3000:]))
        if build.returncode == 0:
            run = subprocess.run([str(exe)], capture_output=True, text=True)
            print(run.stdout, end='')
            check(run.returncode == 0, 'the Swift checks pass' + ('' if run.returncode == 0 else '\n' + run.stderr[-2000:]))

print(f'\n{len(failures)} failure(s)' if failures else '\nall checks pass')
sys.exit(1 if failures else 0)
