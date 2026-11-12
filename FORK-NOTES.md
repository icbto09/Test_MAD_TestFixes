# Madeira test build notes

This repository is the source of **Madeira Test 12 (Nov 11)** (branch `test/test12`,
commit 4e4f784) with a few fixes added, built on GitHub's own macOS runners.
Madeira is GPL-3.0-or-later with the Madeira Converter Exception; see `LICENSE`,
`LICENSE-EXCEPTION.md`, `LICENSES/` and `THIRD-PARTY-NOTICES.md`.

Earlier state of this repository: Madeira Test 8 (Nov 10), branch `test/test8-check`,
commit e0463a5.

## How it differs from the Test 12 source bundle

Layout:
- `FEX`, `wine`, `dxmt` and `madeira-dock` are ordinary folders (the trees the Test 12 IPA was
  built from, including its local changes), not submodules: Test 12's Madeira, FEX and wine
  commits are not on the public repositories. `.gitmodules` is removed and the build no longer
  runs `git submodule update` for them.
- The bundle's Linux (WSL) build-script changes are reverted to the macOS originals:
  `build/gnutls-ios/build.sh`, `build/luajit-x64/build.sh`, `build/wineserver/build.sh`,
  `tools/build/build-runtime-component.sh`, `tools/build/build-wine.sh`,
  `tools/build/runtime-components.py`. The one in `build/win32u-unix/build.sh` is kept
  (an `rm -f` of the old archive, harmless on macOS).

Build:
- `.github/workflows/build.yml`: `runs-on: macos-26` and a "Select newest Xcode" step in place
  of the Madeira team's `xcode-27` machine, on all seven jobs.
- `tools/build/build-shader-headers.sh`: asks the Metal compiler which form of
  `__metal_atomic_fetch_add_explicit` it accepts (GitHub's Xcode 26.6 defines the flag macro
  but takes four arguments). Test 12 went back to an `#ifdef` on the macro, which picks the
  wrong form there, so this fork keeps the probe.

Fixes:
- `build/wineserver/request_ios.c`: LiveContainer. When binding the wineserver master socket
  is refused, retry once in the server directory, then carry on without it (ported from BCD
  0.1.630). The app half of this fix is already in Test 12.
- `build/moltenvk-ios/0001-madeira-evict-pipeline-states.patch`,
  `0002-madeira-drop-shader-libraries.patch` and
  `0003-madeira-null-pipeline-bind.patch`, applied to MoltenVK v1.4.2 by a loop in
  `build/moltenvk-ios/build.sh`. 0001 and 0002 are off unless
  `MADEIRA_MVK_EVICT_PIPELINES=1` / `MADEIRA_MVK_DROP_SHADER_LIBRARIES=1` is set (Detroit:
  Become Human's shader compile). 0003 is always on: a game that binds the null handle of a
  pipeline whose compile failed no longer crashes MoltenVK; those draws are skipped.
- `app/Madeira/WineProcessBridge.m`: in a Wine desktop session (not ARM64EC) the Vulkan setup
  removes the `system32` links for `vulkan-1.dll` and `winevulkan.dll`, so an x64 game loads
  the real pair from `sysx64` instead of the ARM64EC farm's stand-in. Without this, a desktop
  launch after another session reports no Vulkan graphics card until the launch mode is
  switched to Directly and back.
- `madeira-d3d12/src/pe/madeira_d3d12.c`: an optional per-call log of the `ID3D12Device`
  methods, off unless `MADEIRA_D3D12_CALL_LOG` is set (1 = failures and each method's first
  call, 2 = every call). For tracing a game's Direct3D 12 setup.

Not in this build: the Get Help key (private), so Get Help does not work. There is no
`en.lproj` in the bundle, so English is not offered in the language picker.

## Prebuilt files

The Test 12 source bundle leaves out the built files that the Madeira repository keeps in git.
They are restored here so the tree has the shape the build expects:
- `app/Madeira/arm64ec-windows/`, `app/Madeira/aarch64-windows/` and
  `app/Madeira/vulkan/arm64ec-windows/{vulkan-1,winevulkan}.dll` come from the Test 12
  (Nov 11) IPA, so they match this source. Left out: `dockhost.exe`, `dock-notices.txt`
  (built by the dock component) and the `*.source` build stamp. The file names in the two
  runtime folders select which Wine modules the build compiles
  (`build/windows-runtime/targets.py`).
- `app/Madeira/d3d12/libmetalirconverter.dylib` comes from the public Madeira repository
  (8b52c18). The build pins its SHA-256 (`build/madeira-d3d12/deps.sh`); the copy inside an
  IPA has been re-signed and no longer matches.
- The diagnostic test programs under `tests/`, the test shaders in `madeira-d3d12/shaders/`
  and `build/tftrace/tftrace-x64.dll` come from the public Madeira repository (8b52c18).
- Not restored: `app/Madeira/lib{gmp,gnutls,hogweed,nettle}.a` and `app/libdxmt_unix.a`.
  The build compiles these.
