# Madeira_Test8: test build notes

This repository is the source of **Madeira Test 8 (Nov 10)** (branch `test/test8-check`,
commit e0463a5) with a few fixes added, built on GitHub's own macOS runners.
Madeira is GPL-3.0-or-later with the Madeira Converter Exception; see `LICENSE`,
`LICENSE-EXCEPTION.md`, `LICENSES/` and `THIRD-PARTY-NOTICES.md`.

## How it differs from the Test 8 source bundle

Layout:
- `FEX`, `wine`, `dxmt` and `madeira-dock` are ordinary folders (the trees the Test 8 IPA was
  built from, including its local changes), not submodules: Test 8's FEX, wine and app commits
  are not on the public repositories. `.gitmodules` is removed and the build no longer runs
  `git submodule update` for them.
- The bundle's Linux (WSL) build-script changes are reverted to the macOS originals:
  `build/gnutls-ios/build.sh`, `build/luajit-x64/build.sh`, `build/wineserver/build.sh`,
  `tools/build/build-runtime-component.sh`, `tools/build/build-wine.sh`,
  `tools/build/runtime-components.py`.

Build:
- `.github/workflows/build.yml`: `runs-on: macos-26` and a "Select newest Xcode" step in place
  of the Madeira team's `xcode-27` machine.
- `tools/build/build-shader-headers.sh`: asks the Metal compiler which form of
  `__metal_atomic_fetch_add_explicit` it accepts (GitHub's Xcode 26.6 defines the flag macro
  but takes four arguments).

Fixes:
- `build/wineserver/request_ios.c`: LiveContainer. When binding the wineserver master socket
  is refused, retry once in the server directory, then carry on without it (ported from BCD
  0.1.630). The app half of this fix is already in Test 8.
- `build/moltenvk-ios/0001-madeira-evict-pipeline-states.patch` and
  `0002-madeira-drop-shader-libraries.patch`, applied by a loop in
  `build/moltenvk-ios/build.sh`. Both are off unless `MADEIRA_MVK_EVICT_PIPELINES=1` /
  `MADEIRA_MVK_DROP_SHADER_LIBRARIES=1` is set (Detroit: Become Human's shader compile).

Not in this build: the Get Help key (private), so Get Help does not work.
