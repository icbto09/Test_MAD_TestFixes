# Madeira's FEX patches

Changes to FEX that Madeira needs and that live in this repository, not in
the FEX submodule's repository. `apply.sh` applies them, in file-name order,
to the FEX working tree before `build/fex-arm64ec/build.sh` and
`build/fex-wow64/build.sh` build `xtajit64.dll` and `xtajit.dll`; it skips a
patch that is already applied, and `apply.sh --revert` takes them out. The
FEX submodule pin does not change.

These patches are for Madeira only and are not to be sent to FEX-Emu.

| Patch | What it fixes |
|---|---|
| `0001-windows-ios-smc-traps-per-16k-host-page.patch` | Self-modifying-code write traps per 16 KB iOS host page, both modules (The Escapists 2, Project Zomboid) |
| `0002-windows-skip-own-memory-notifications-during-invalidation.patch` | FEX's own frees during a code invalidation no longer re-enter the invalidation and deadlock on CodeBufferListLock, both modules (.NET games: Stardew Valley, Slay the Spire 2) |
| `0003-windows-skip-own-code-flushes-under-the-invalidation-lock.patch` | FEX's own code flushes while it holds the code invalidation lock no longer wait for ThreadCreationMutex, which deadlocked against a write fault on another thread, ARM64EC module (PvZ Fusion with MelonLoader: black screen) |

A patch must apply on the current FEX pin. When the pin moves, rebase the
patches onto it (or drop a patch the new pin already covers).
