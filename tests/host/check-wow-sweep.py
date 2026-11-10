#!/usr/bin/env python3
"""Production-source regression for WOW64 syscall parking; no Wine, FEX JIT or guest runs.

On a device, a desktop client's 32-bit processes kept 30 code-buffer generations
(720 MB of the 896 MB pool) alive, because a WOW64 thread blocked in a syscall was never seen
by the code-buffer sweeper. A thread then died at the out-of-pool fault holding FEX's shared
lock and the process hung.

Since FEX-2611 a syscall ends its block: the emitted code branches (br, no return) to the
dispatcher's syscall thunk, which lives in the dispatcher's own buffer, calls
Pointers.SyscallHandlerFunc(Obj, Frame) and then re-dispatches at State.rip. So a thread moved
while blocked needs no return-address redirect; parking only has to tell the sweeper.

Part A checks the source invariants this depends on (no return into a block, the thunk's call
and re-dispatch, park/unpark placement, registration). Part B compiles the production
IosWowPark/IosWowUnpark/IosWowSyscallC against a fake sweeper and nested callbacks.
"""
from pathlib import Path
import re, subprocess, tempfile
root = Path(__file__).resolve().parents[2]
mod = (root / "FEX/Source/Windows/WOW64/Module.cpp").read_text()
cpu = (root / "FEX/FEXCore/Source/Interface/Core/CPUBackend.cpp").read_text()
branch = (root / "FEX/FEXCore/Source/Interface/Core/JIT/BranchOps.cpp").read_text()
opd = (root / "FEX/FEXCore/Source/Interface/Core/OpcodeDispatcher.cpp").read_text()
disp = (root / "FEX/FEXCore/Source/Interface/Core/Dispatcher/Dispatcher.cpp").read_text()
hle = (root / "FEX/FEXCore/include/FEXCore/HLE/SyscallHandler.h").read_text()
def function(source, start):
    a = source.index(start); b = source.index("{", a); depth = 1; c = b + 1
    while depth:
        depth += (source[c] == "{") - (source[c] == "}"); c += 1
    return source[a:c]

# ---- Part A: invariants
syscall_op = function(branch, "DEF_OP(Syscall)")
assert "SpillStaticRegs(" in syscall_op and "Pointers.ThreadDispatchSyscallHandler" in syscall_op \
    and "br(TMP1);" in syscall_op and "blr(" not in syscall_op, "a syscall leaves its block for good (br, no return address)"
assert "Arm64Emitter(ctx, FEXCore::Allocator::VirtualAlloc(MAX_DISPATCHER_CODE_SIZE, true)" in disp, \
    "the dispatcher (and its syscall thunk) is its own buffer, not a code-buffer generation"
thunk = disp[disp.index("ThreadDispatchSyscallHandler = GetCursorAddress<uint64_t>();"):]
thunk = thunk[:thunk.index("(void)b(&LoopTop);") if "(void)b(&LoopTop);" in thunk[:4000] else 4000]
order = ["Pointers.SyscallHandlerObj", "Pointers.SyscallHandlerFunc", "mov(ARMEmitter::Size::i64Bit, ARMEmitter::Reg::r1, STATE.R());",
         "blr(ARMEmitter::Reg::r3);", "FillStaticRegs(", "str(ARMEmitter::XReg::zr, STATE, offsetof(FEXCore::Core::CpuStateFrame, InSyscallInfo));",
         "State.rip", "LoopTop"]
pos = [thunk.index(o) for o in order]
assert pos == sorted(pos), "thunk: x0=Obj, x1=Frame, call, refill, clear InSyscallInfo, re-dispatch at State.rip"
assert "virtual void HandleSyscall(FEXCore::Core::CpuStateFrame* Frame) = 0;" in hle, "handler ABI is (Obj, Frame)"
base = (root / "FEX/FEXCore/Source/Interface/Core/X86Tables/BaseTables.cpp").read_text()
assert "*reinterpret_cast<uint32_t*>(Addr) = 0x2ecd2ecd;" in mod, "the WOW64 bridges are int 0x2e"
assert re.search(r'\{0xCD, 1, X86InstInfo\{"INT",\s+TYPE_INST, [^}]*FLAGS_BLOCK_END', base), "INT ends its block"
intop = function(opd, "void OpDispatchBuilder::INTOp(")
assert re.search(r"SYSCALL_LITERAL = 0x2E;\s*if \(Literal == SYSCALL_LITERAL\) \{[^}]*SyscallOp\(Op, false\);", intop), "int 0x2e is a syscall on WOW64"
sc = function(opd, "void OpDispatchBuilder::SyscallOp(")
assert "offsetof(FEXCore::Core::CPUState, rip)" in sc and "_Syscall();" in sc, "SyscallOp stores RIP before the syscall"
impl = function(mod, "static void HandleSyscallImpl(")
for call in ["WineUnixCall(", "Wow64SystemServiceEx("]:
    i = impl.index(call)
    before, after = impl[:i], impl[i:]
    assert before.rindex("IosWowPark(TD);") > before.rindex("Context::UnlockJITContext(TLS);"), f"park after unlock for {call}"
    assert after.index("IosWowUnpark(TD);") < after.index("Context::LockJITContext(TLS);"), f"unpark before lock for {call}"
assert 'extern "C" void IosWowSyscallC(FEXCore::HLE::SyscallHandler* Obj, FEXCore::Core::CpuStateFrame* Frame)' in mod, "entry matches the thunk ABI"
init = function(mod, "void BTCpuThreadInit()")
assert "IosWowSweepEnabled()" in init and "Pointers.SyscallHandlerFunc = reinterpret_cast<uint64_t>(&IosWowSyscallC)" in init \
    and "IosSweepRegisterThreadEx(Thread, &TD->IosInSim, &TD->IosMigrated)" in init and "TD->IosSweepRegistered = true;" in init, "thread registration"
term = function(mod, "void BTCpuThreadTerm(")
assert term.index("IosSweepUnregisterThread(ThreadState)") < term.index("delete GetFrontendThreadData(ThreadState)"), "unregister before free"
sim = function(mod, 'extern "C" void BTCpuSimulateImpl(')
assert sim.index("IosWowUnpark(") < sim.index("ExecuteThread("), "simulation entry unparks"
assert "case 1:" in cpu and "*Snap[i].Migrated = 1;" in cpu and "IosSweepRegisterThreadEx(Thread, InSimPtr, nullptr);" in cpu, "sweeper flags moves"
print("PASS: syscalls never return into a block, thunk call/re-dispatch, park/unpark placement, registration and sweeper invariants")

# ---- Part B: behaviour of the production parking code
td = mod[mod.index("struct FrontendThreadData {"):mod.index("class WowSyscallHandler;")]
park = mod[mod.index("static bool IosWowSweepEnabled()"):mod.index("// Returns the HOST address of the 32-bit TEB")]
park = park[:park.rindex("#endif")]
entry = function(mod, 'extern "C" void IosWowSyscallC(')
code = r"""
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cassert>
#include <functional>
namespace LogMan::Msg { template <typename... T> void EFmt(const char*, T...) { std::fputs("log\n", stderr); } }
namespace FEXCore::Core {
  struct InternalThreadState { void* FrontendPtr; };
  struct CpuStateFrame { uint64_t rip; };
}
namespace FEXCore::HLE {
  struct SyscallHandler { virtual void HandleSyscall(FEXCore::Core::CpuStateFrame* Frame) = 0; };
}
""" + td + r"""
static FEXCore::Core::InternalThreadState g_thread;
struct TLSStub { FEXCore::Core::InternalThreadState* ThreadState() const { return &g_thread; } };
static TLSStub GetTLS() { return {}; }
static FrontendThreadData* GetFrontendThreadData(FEXCore::Core::InternalThreadState* T) { return static_cast<FrontendThreadData*>(T->FrontendPtr); }
uint64_t IosCodeBufferSweepGate = 0;
""" + park.replace('__asm volatile("yield");', '').replace('extern "C" void IosSweepRegisterThreadEx', 'static void Unused1').replace('extern "C" void IosSweepUnregisterThread', 'static void Unused2').replace('extern "C" uint64_t IosCodeBufferSweepGate;', '') + "\n" + entry + r"""
static void Unused1(FEXCore::Core::InternalThreadState*, volatile uint8_t*, volatile uint8_t*) {}
static void Unused2(FEXCore::Core::InternalThreadState*) {}
// A fake handler: HandleSyscallImpl's park/unpark around the "blocking call", with a sweeper
// that moves the thread whenever it sees it parked, and optional nested callbacks.
struct Handler : FEXCore::HLE::SyscallHandler {
  std::function<void()> Blocking;
  void HandleSyscall(FEXCore::Core::CpuStateFrame* F) override {
    auto* TD = GetFrontendThreadData(&g_thread);
    IosWowPark(TD);
    if (Blocking) Blocking();
    IosWowUnpark(TD);
  }
};
static int sweeps_moved;
static void sweep(FrontendThreadData* TD) {           // IosMaybeSweepCodeBuffers, one target
  IosCodeBufferSweepGate = 1;
  if (TD->IosInSim == 0) { TD->IosMigrated = 1; sweeps_moved++; }
  IosCodeBufferSweepGate = 0;
}
int main(int argc, char** argv) {
  FrontendThreadData TD; g_thread.FrontendPtr = &TD;
  if (argc > 1) setenv("MADEIRA_WOW_SYSCALL_SWEEP", "0", 1);
  TD.IosSweepRegistered = IosWowSweepEnabled();
  FEXCore::Core::CpuStateFrame F {0x401000};
  Handler H;
  if (argc > 1) {
    H.Blocking = [&] { sweep(&TD); };
    IosWowSyscallC(&H, &F);
    assert(sweeps_moved == 0 && TD.IosInSim == 1);
    std::puts("off"); return 0;
  }
  // (a) outermost syscall: parked while blocked, moved, back in simulation after
  H.Blocking = [&] { assert(TD.IosInSim == 0); sweep(&TD); };
  IosWowSyscallC(&H, &F);
  assert(sweeps_moved == 1 && TD.IosInSim == 1 && TD.IosMigrated == 0 && TD.IosSyscallDepth == 0 && !TD.IosSyscallArmed);
  // (b) a callback re-enters simulation (unpark) and makes a nested syscall: never parked
  H.Blocking = [&] {
    sweep(&TD);                                   // moved while blocked
    IosWowUnpark(&TD);                            // BTCpuSimulateImpl entry
    Handler inner; inner.Blocking = [&] { assert(TD.IosInSim == 1); sweep(&TD); };
    IosWowSyscallC(&inner, &F);
    assert(TD.IosSyscallDepth == 1 && TD.IosSyscallArmed);   // outer state restored
  };
  IosWowSyscallC(&H, &F);
  assert(sweeps_moved == 2 && TD.IosInSim == 1 && TD.IosSyscallDepth == 0 && !TD.IosSyscallArmed);
  // (c) a nested call that never returns (long jump) leaves depth behind; the outer restores it
  H.Blocking = [&] { TD.IosSyscallDepth = 7; };
  IosWowSyscallC(&H, &F); assert(TD.IosSyscallDepth == 0);
  H.Blocking = [&] { sweep(&TD); };
  IosWowSyscallC(&H, &F);
  // (d) an unregistered thread is never parked
  TD.IosSweepRegistered = false;
  IosWowSyscallC(&H, &F);
  std::printf("on moved=%d\n", sweeps_moved);
  return 0;
}
"""
with tempfile.TemporaryDirectory() as tmp:
    c = Path(tmp)/"check.cpp"; exe = Path(tmp)/"check"; c.write_text(code)
    subprocess.run(["c++", "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                    "-no-pie", str(c), "-o", str(exe)], check=True)
    on = subprocess.run([str(exe)], check=True, capture_output=True, text=True)
    assert "on moved=3" in on.stdout, on.stdout + on.stderr
    off = subprocess.run([str(exe), "rollback"], check=True, capture_output=True, text=True)
    assert "off" in off.stdout
    print("PASS: only an outermost registered syscall parks; nested and long-jump cases restore state; rollback never parks")
