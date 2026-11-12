#!/usr/bin/env python3
"""A controller in Madeira's own menus (app/Madeira/PadHighlight.swift), on the host.

One UI (Nov 10): the old blue ring (MenuPad.swift) went with the old look; the one controller
highlight is PadHighlight (also checked by check-new-look.py and check-pad-coverage.py).
Source checks: LibraryController sends the commands (L1/R1 as previous/next, L2/R2 as
pageUp/pageDown, View as search), repeats a held direction, logs each controller once, and
GamepadInput hands it the triggers and the name; every store's covers, sign-in card and game
sheet take the highlight; the system's own focus never gets the pad; a touch hides the highlight.
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


pad = (app / 'PadHighlight.swift').read_text()
library = (app / 'Library.swift').read_text()
gamepad = (app / 'GamepadInput.swift').read_text()
project = (root / 'app/Madeira.xcodeproj/project.pbxproj').read_text()

require('MenuPad.swift' not in project and not (app / 'MenuPad.swift').exists() and 'MenuPad.' not in library,
        'the old ring is gone: MenuPad.swift is not in the app target')
require(project.count('/* PadHighlight.swift in Sources */') == 2 and project.count('/* PadHighlight.swift */') == 3,
        'PadHighlight.swift is in the app target')

controller = library[library.index('final class LibraryController'):library.index('enum FrontendChoice')]
for mask, name in [('0x100', 'previous'), ('0x200', 'next'), ('0x10000', 'pageUp'), ('0x20000', 'pageDown'), ('0x20', 'search'),
                   ('0x1000', 'accept'), ('0x2000', 'back'), ('0x10', 'menu'), ('0x8000', 'add')]:
    require(f'({mask}, "{name}")' in controller, f'{name} is sent for {mask}')
require('if lt > 128 { buttons |= 0x10000 }; if rt > 128 { buttons |= 0x20000 }' in controller, 'the triggers count past half way')
require('repeatAt = now.addingTimeInterval(0.35)' in controller and 'pressed |= direction; repeatAt = now.addingTimeInterval(0.1)' in controller,
        'a held direction repeats after 0.35 s, then every 0.1 s')
require('fputs("[menu-pad] connected \\(newName)\\n", stderr)' in controller and '!named.contains(name)' in controller,
        'each controller is logged once by name')
require('lt: state.left_trigger, rt: state.right_trigger' in gamepad and 'name: pad.controller?.vendorName' in gamepad,
        'GamepadInput hands over the triggers and the controller\'s name')
require('if !own, buttons & 0x30 == 0x30, pressed & 0x30 != 0 { command = "menu" }' in controller,
        'in a game only Back+Start reaches Madeira; the game keeps the pad')
require('MainActor.assumeIsolated { self?.handle(command) }' in pad, "every command goes to the highlight's one handler")

for store, key in [('Steam', 'steam'), ('Epic', 'epic'), ('GOG', 'gog'), ('Itch', 'itch'), ('EA', 'ea')]:
    text = (app / f'{store}Games.swift').read_text()
    require(f'.libraryCardButtonStyle(grid: !list, pad: "{key}:\\(item.id)")' in text, f'{store}: covers take the highlight')
    require(f'.padItem("signin:{key}"' in text, f'{store}: the sign-in card takes the highlight')
    require('.padSheet { primaryPress(item)?() }' in text and 'private func primaryPress(' in text,
            f'{store}: A and B on the game sheet')
    require('withTransaction(instant) { showUninstalled.toggle() }' in text, f'{store}: Show uninstalled at once')
require('if let pad, PadHighlight.enabled { buttonStyle(PadCardStyle(id: pad, grid: grid)) }' in library, 'the card style wraps the old one')

require('window.addGestureRecognizer(PadTouchWatch { PadHighlight.shared.hide() })' in pad and 'cancelsTouchesInView = false' in pad
        and 'state = .failed' in pad, 'a touch hides the highlight without taking the touch')
require('GamepadEventClaim.install(on: window)' in pad
        and '.modifier(ClaimGamepadEvents())' in pad[pad.index('struct PadSheet'):]
        and library.count('.modifier(ClaimGamepadEvents())') >= 2,
        'the system\'s own focus never gets the pad (window, game page, browser and store sheets claim it)')
require('list.allowsFocus = false; list.selectionFollowsFocus = false' in pad and 'func padNoSystemFocus()' in pad,
        'the lists take no system focus')
detail = library[library.index('struct LibraryDetail: View'):library.index("struct BCDGameValues")]
require(detail.count('.padNoSystemFocus()') >= 2, "the game's page and its pages take no system focus")

# The game's page: A on Play plays, A on a row opens it, the FPS row steps (PadHighlight items).
page = library[library.index('// MARK: - New look game page'):library.index('// MARK: - New look: the starting screen')]
require('.padItem("gp-play", capsule: true) { start() }' in page
        and '.padItem("gp-fps", cornerRadius: 12, inset: -6) { entry.fpsMode = FPSChoice.next(after: entry.fpsMode) }' in page
        and 'static func next(after current: Int)' in library, 'A plays only on Play; A steps the FPS limit')
require('.padLayer("game", start: lookReturn ?? "gp-play", back: { lookBack() }, play: { start() }, page: true)' in detail,
        "the game's page is a layer of its tab: B goes back, X is Play")
require('case epic, ea' in detail and 'case .epic:' in detail and 'entry.epicAppName != nil ? [.epic]' in detail, 'Epic and EA have pages')

print('check-menu-pad: ' + ('FAIL' if failures else 'PASS'))
sys.exit(1 if failures else 0)
