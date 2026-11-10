#!/usr/bin/env python3
"""[x64-ntdll-file] / x64-system32-files: x64 programs that read a system32 DLL from disk get the x64-stub (arm64ec) file.

StarCraft's ClientSdk.dll opens C:\\windows\\system32\\ntdll.dll (anti-hook), reads it into its own
RWX page and calls the Nt* exports as x64 syscall stubs. A native-ARM64 session's system32\\ntdll.dll
is the plain aarch64 build (ARM64 stubs: "mov x8,#id ... blr x16"), so FEX ran ARM64 bytes as x86
(c0000005, "ClientSdk.dll failed to initialize"). C:\\windows\\sysx64 is the arm64ec farm, whose ntdll
exports are x64 stubs. An open (FILE_OPEN) of system32\\ntdll.dll / win32u.dll from an x64/EC process is
answered out of sysx64 (wine/dlls/ntdll/unix/file.c, NtCreateFile).

x64-system32-files widens that to any single file name under system32 ending .dll/.drv/.ocx (not .exe: CreateProcess
opens the image through the same call and a system32 .exe is native ARM64 on Windows ARM), only when opened without
write/delete access, and answers NtQueryAttributesFile / NtQueryFullAttributesFile from the same file.

Checks, without a Wine run:
  - the helper block is under WINE_IOS and the switch is exactly "0" (compiled and run, stub getenv);
  - the matcher (compiled against stub types) redirects system32\\<name>.dll/.drv/.ocx, any case, keeps the caller's
    spelling, and nothing else (.exe, .sys, no extension, subdirs, syswow64, sysx64, other roots, over-long names, ".dll");
  - NtCreateFile only redirects for FILE_OPEN, no RootDirectory, no write/delete access, ios_is_arm64ec_cur() (not i386 /
    not native aarch64), falls back to the original name when the sysx64 file is missing, logs through the deduplicating
    logger, and the redirect locals live at function scope (new_attr.ObjectName points at them until the call ends);
  - both attribute queries go through ios_x64_attr_names(), which falls back to the caller's name and frees the failed lookup;
  - the log is once per distinct file (compiled and run);
  - the prefix farm that backs it really links sysx64 to arm64ec-windows (WineProcessBridge.m).
Needs python3 and a C compiler.
"""
from pathlib import Path
import os, re, subprocess, sys, tempfile

root = Path(__file__).resolve().parents[2]
src = (root / 'wine/dlls/ntdll/unix/file.c').read_text()
bridge = (root / 'app/Madeira/WineProcessBridge.m').read_text()

# --- the helper block ---------------------------------------------------------
start = src.index('/* x64-ntdll-file: x64 programs that read system DLLs from disk')
begin = src.rindex('#ifdef WINE_IOS', 0, start)
end = src.index('#endif /* WINE_IOS */', start)
block = src[begin:end]
assert 'MADEIRA_X64_NTDLL_FILE' in block
assert 'e[0] == \'0\' && !e[1]' in block, 'switch is exactly "0"'
assert src.index('NtCreateFile   (NTDLL.@)') > end, 'helpers sit before NtCreateFile'
assert src.index('NtQueryFullAttributesFile   (NTDLL.@)') > end

# --- the NtCreateFile call site ------------------------------------------------
fn = src[src.index('NTSTATUS WINAPI NtCreateFile('):]
fn = fn[:fn.index('\n}\n')]
for need in ('!attr->RootDirectory', 'disposition == FILE_OPEN', '!(access & IOS_X64_WRITE_ACCESS)',
             'ios_x64_ntdll_file_enabled()', 'ios_x64_ntdll_redirect( attr->ObjectName, x64_buf, &x64_name )',
             'ios_is_arm64ec_cur()', 'ios_x64_ntdll_log( 0, attr->ObjectName, &x64_name )', 'new_attr = *attr;',
             'if (!x64_redirected)'):
    assert need in fn, need
assert fn.index('#ifdef WINE_IOS') < fn.index('ios_x64_ntdll_redirect(') < fn.index('get_nt_and_unix_names')
call = fn[fn.index('ios_x64_ntdll_redirect('):]
assert call.index('free( unix_name );') < call.index('new_attr = *attr;'), 'fallback frees the failed lookup first'
# the redirect's locals must outlive the else block that uses them: declared before TRACE( at function scope
assert fn.index('UNICODE_STRING x64_name;') < fn.index('TRACE(') and fn.index('BOOL x64_redirected') < fn.index('TRACE(')
assert fn.count('UNICODE_STRING x64_name;') == 1

# --- the attribute queries -----------------------------------------------------
for name in ('NtQueryFullAttributesFile', 'NtQueryAttributesFile'):
    q = src[src.index('NTSTATUS WINAPI %s(' % name):]
    q = q[:q.index('\n}\n')]
    assert 'ios_x64_attr_names( attr, &new_attr, &nt_name, &unix_name )' in q, name
    assert '#else\n    if (!(status = get_nt_and_unix_names( &new_attr, &nt_name, &unix_name, FILE_OPEN, TRUE )))' in q, name
helper = block[block.index('static NTSTATUS ios_x64_attr_names('):]
for need in ('!attr->RootDirectory', 'ios_x64_ntdll_file_enabled()', 'ios_is_arm64ec_cur()',
             'new_attr->ObjectName = attr->ObjectName;', 'free( *unix_name );', 'ios_x64_ntdll_log( 1,'):
    assert need in helper, need
assert helper.index('free( *unix_name );') < helper.rindex('return get_nt_and_unix_names')

# --- compile the helpers against stub types and exercise them ------------------
prog = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int BOOL; typedef unsigned short WCHAR; typedef unsigned short USHORT; typedef int NTSTATUS;
#define TRUE 1
#define FALSE 0
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define FILE_WRITE_DATA 2
#define FILE_APPEND_DATA 4
#define FILE_WRITE_EA 0x10
#define FILE_WRITE_ATTRIBUTES 0x100
#define DELETE 0x10000
#define WRITE_DAC 0x40000
#define WRITE_OWNER 0x80000
#define GENERIC_WRITE 0x40000000
#define GENERIC_ALL 0x10000000
#define FILE_OPEN 1
typedef struct { USHORT Length, MaximumLength; WCHAR *Buffer; } UNICODE_STRING;
typedef struct { void *RootDirectory; UNICODE_STRING *ObjectName; } OBJECT_ATTRIBUTES;
static const char *g_env;
static char *stub_getenv(const char *n) { return (char *)g_env; }
#define getenv stub_getenv
static int g_logs;
static char g_last[300];
static int stub_dprintf(int fd, const char *f, ...) { g_logs++; strncpy(g_last, f, sizeof(g_last) - 1); return 0; }
#define dprintf stub_dprintf
static int g_arm64ec = 1, g_have_sysx64 = 1, g_names_calls;
static int ios_is_arm64ec_cur(void) { return g_arm64ec; }
static NTSTATUS get_nt_and_unix_names( OBJECT_ATTRIBUTES *a, UNICODE_STRING *nt, char **unix_name, int disp, int rp )
{
    g_names_calls++;
    *unix_name = malloc( 4 ); nt->Buffer = malloc( 4 );
    if (a->ObjectName->Buffer[18] == 'x' && !g_have_sysx64) return -1;   /* the sysx64 name, farm file absent */
    return 0;
}
''' + block.replace('#ifdef WINE_IOS', '').replace('extern int ios_is_arm64ec_cur(void);', '') + r'''
static UNICODE_STRING mk(const char *name, WCHAR *in) {
    size_t n = strlen(name), i; UNICODE_STRING u;
    for (i = 0; i < n; i++) in[i] = (unsigned char)name[i];
    u.Buffer = in; u.Length = n * 2; u.MaximumLength = u.Length + 2; return u;
}
static int run(const char *name, char *out) {
    WCHAR in[300], buf[IOS_X64_BUF_CHARS]; UNICODE_STRING u = mk(name, in), o; size_t i;
    memset(buf, 0x55, sizeof(buf));
    if (!ios_x64_ntdll_redirect(&u, buf, &o)) return 0;
    if (o.Length / 2 >= IOS_X64_BUF_CHARS) { puts("overflow"); exit(99); }
    for (i = 0; i < o.Length / 2; i++) out[i] = (char)o.Buffer[i];
    out[i] = 0; return 1;
}
#define EXPECT(n, name, want) do { if (!run(name, out) || strcmp(out, want)) { printf("case %d: %s -> %s\n", n, name, out); return n; } } while (0)
#define REFUSE(n, name) do { if (run(name, out)) { printf("case %d: %s redirected to %s\n", n, name, out); return n; } } while (0)
int main(void) {
    char out[300];
    g_env = NULL; if (!ios_x64_ntdll_file_enabled()) return 1;
    EXPECT(2, "\\??\\C:\\windows\\system32\\ntdll.dll", "\\??\\C:\\windows\\sysx64\\ntdll.dll");
    EXPECT(3, "\\??\\c:\\Windows\\System32\\WIN32U.DLL", "\\??\\C:\\windows\\sysx64\\WIN32U.DLL");
    EXPECT(4, "\\??\\C:\\windows\\system32\\kernel32.dll", "\\??\\C:\\windows\\sysx64\\kernel32.dll");
    EXPECT(5, "\\??\\C:\\windows\\system32\\Kernelbase.DLL", "\\??\\C:\\windows\\sysx64\\Kernelbase.DLL");
    EXPECT(6, "\\??\\C:\\windows\\system32\\crypt32.dll", "\\??\\C:\\windows\\sysx64\\crypt32.dll");
    EXPECT(7, "\\??\\C:\\windows\\system32\\winmm.drv", "\\??\\C:\\windows\\sysx64\\winmm.drv");
    EXPECT(8, "\\??\\C:\\windows\\system32\\mscomctl.ocx", "\\??\\C:\\windows\\sysx64\\mscomctl.ocx");
    EXPECT(9, "\\??\\C:\\windows\\system32\\a.dll", "\\??\\C:\\windows\\sysx64\\a.dll");
    REFUSE(10, "\\??\\C:\\windows\\system32\\cmd.exe");
    REFUSE(11, "\\??\\C:\\windows\\system32\\drivers\\ntdll.sys");
    REFUSE(12, "\\??\\C:\\windows\\system32\\ntdll");
    REFUSE(13, "\\??\\C:\\windows\\system32\\ntdll.dll.bak");
    REFUSE(14, "\\??\\C:\\windows\\system32\\drivers\\ntdll.dll");
    REFUSE(15, "\\??\\C:\\windows\\system32\\drivers\\etc\\x.dll");
    REFUSE(16, "\\??\\C:\\windows\\system32\\.dll");
    REFUSE(17, "\\??\\C:\\windows\\system32\\");
    REFUSE(18, "\\??\\C:\\windows\\system32\\dll");
    REFUSE(19, "\\??\\C:\\windows\\syswow64\\ntdll.dll");
    REFUSE(20, "\\??\\C:\\windows\\sysx64\\ntdll.dll");
    REFUSE(21, "\\??\\C:\\other\\system32\\ntdll.dll");
    REFUSE(22, "\\??\\D:\\windows\\system32\\ntdll.dll");
    REFUSE(23, "\\??\\C:\\windows\\system32\\a:b.dll");
    REFUSE(24, "\\??\\C:\\windows\\system32\\sub/x.dll");
    {   /* longest accepted name is 64 characters, 65 is refused */
        char nm[200], f64[80], f65[80];
        memset(f64, 'a', 60); strcpy(f64 + 60, ".dll");
        memset(f65, 'a', 61); strcpy(f65 + 61, ".dll");
        sprintf(nm, "\\??\\C:\\windows\\system32\\%s", f64);
        if (!run(nm, out)) return 25;
        sprintf(nm, "\\??\\C:\\windows\\system32\\%s", f65);
        if (run(nm, out)) return 26;
    }
    /* write/delete access is excluded at the call site: the mask must name every write-ish bit */
    if (!(IOS_X64_WRITE_ACCESS & GENERIC_WRITE) || !(IOS_X64_WRITE_ACCESS & DELETE) || !(IOS_X64_WRITE_ACCESS & FILE_WRITE_DATA)) return 27;
    if (IOS_X64_WRITE_ACCESS & 0x80000000u) return 28;   /* GENERIC_READ stays allowed */
    /* attribute-query names: redirected, falls back when sysx64 file is missing, off for i386/aarch64 and with the switch */
    {
        WCHAR in[300]; UNICODE_STRING u = mk("\\??\\C:\\windows\\system32\\kernel32.dll", in), nt;
        OBJECT_ATTRIBUTES a = { NULL, &u }, na = a; char *un;
        g_names_calls = 0; g_arm64ec = 1; g_have_sysx64 = 1; g_logs = 0;
        if (ios_x64_attr_names(&a, &na, &nt, &un) != 0 || g_names_calls != 1 || na.ObjectName != &u || g_logs != 1) return 30;
        g_logs = 0; ios_x64_attr_names(&a, &na, &nt, &un);
        if (g_logs != 0) return 31;                         /* same file again: no second log line */
        g_names_calls = 0; g_have_sysx64 = 0;
        if (ios_x64_attr_names(&a, &na, &nt, &un) != 0 || g_names_calls != 2) return 32;   /* retried with the caller's name */
        g_names_calls = 0; g_have_sysx64 = 1; g_arm64ec = 0;
        if (ios_x64_attr_names(&a, &na, &nt, &un) != 0 || g_names_calls != 1) return 33;   /* i386 / aarch64: plain lookup */
        g_arm64ec = 1; a.RootDirectory = (void *)1; g_names_calls = 0;
        ios_x64_attr_names(&a, &na, &nt, &un);
        if (g_names_calls != 1) return 34;                  /* RootDirectory: never redirected */
    }
    /* the log: once per distinct file, capped at 128 */
    {
        char nm[200]; WCHAR in[300], bf[IOS_X64_BUF_CHARS]; UNICODE_STRING u, o; int k, before;
        g_logs = 0;
        for (k = 0; k < 300; k++) {
            sprintf(nm, "\\??\\C:\\windows\\system32\\f%d.dll", k);
            u = mk(nm, in);
            if (!ios_x64_ntdll_redirect(&u, bf, &o)) return 40;
            ios_x64_ntdll_log(0, &u, &o);
            ios_x64_ntdll_log(0, &u, &o);
        }
        before = g_logs;
        if (before < 100 || before > 128) { printf("log lines %d\n", before); return 41; }
    }
    puts("ok"); return 0;
}
'''
with tempfile.TemporaryDirectory() as d:
    c = Path(d, 't.c'); c.write_text(prog)
    exe = Path(d, 't')
    subprocess.run([os.environ.get('CC', 'cc'), '-Wall', '-Werror', '-Wno-unused-function', '-o', str(exe), str(c)], check=True)
    r = subprocess.run([str(exe)], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip().endswith('ok'), ('matcher test failed', r.returncode, r.stdout)
    # the switch: only "0" turns it off
    for val, want in (('0', 0), ('1', 1), ('', 1), ('00', 1), (None, 1)):
        c2 = Path(d, 's.c')
        c2.write_text(prog.split('static UNICODE_STRING mk(')[0] + 'int main(void){ g_env = %s; return ios_x64_ntdll_file_enabled() == %d ? 0 : 1; }'
                      % ('NULL' if val is None else '"%s"' % val, want))
        subprocess.run([os.environ.get('CC', 'cc'), '-w', '-o', str(Path(d, 's')), str(c2)], check=True)
        assert subprocess.run([str(Path(d, 's'))]).returncode == 0, ('switch', val)

# --- the farm behind it -------------------------------------------------------
assert re.search(r'\{ "sysx64",\s+"arm64ec-windows" \}', bridge), 'sysx64 farm links the arm64ec bundle dir'

print('check-x64-ntdll-file: ok')
