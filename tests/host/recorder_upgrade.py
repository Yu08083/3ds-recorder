import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path


def run():
    repo = Path(__file__).resolve().parents[2]
    code = (repo / "app/source/recorder.c").read_text(encoding="utf8")
    header = (repo / "app/source/recorder.h").read_text(encoding="utf8")
    app = (repo / "app/source/app.c").read_text(encoding="utf8")
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "3ds").mkdir()
        (root / "3ds" / "types.h").write_text("#include <stdint.h>\ntypedef uint32_t u32; typedef int32_t s32;")
        source = root / "test.c"
        source.write_text(SETUP + "\n" + re.search(r"^typedef enum \{ MODULE_MISSING.*?} RecStatus;", header, re.M | re.S)[0]
                          + "\n" + MEMORY + code[code.index("static Handle OpenModule"):code.index("bool recorder_take_system_stop")]
                          + code[code.index("static void Status"):code.index("static Result WithPmApp")]
                          + code[code.index("bool recorder_stop(void)"):code.index("/* ------------------------------------------------", code.index("bool recorder_stop(void)"))]
                          + IO + code[code.index("static ModuleFile CompareFile"):code.index("bool recorder_luma_modules_on")]
                          + "\ntypedef struct { RecStatus st; ModuleFile moduleFile; } App;\n"
                          + app[app.index("static bool update_ready"):app.index("void app_init")] + CASES)
        cc = shlex.split(os.environ["CC"]) if os.environ.get("CC") else [shutil.which("cc") or shutil.which("gcc")]
        binary = root / ("test.exe" if os.name == "nt" else "test")
        subprocess.run([*cc, "-std=c11", "-Werror", "-Wall", "-Wno-unused-parameter", "-O2", "-I", str(root), "-I",
                        str(repo / "sysmod/source"), str(source), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], cwd=temp, check=True)


SETUP = r"""
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include "shared.h"
typedef uint64_t u64;
typedef int64_t s64;
typedef uint8_t u8;
typedef int Handle, Result, PageInfo;
typedef struct { u32 base_addr, size, perm, state; } MemInfo;
#define R_SUCCEEDED(x) ((x) >= 0)
#define R_FAILED(x) ((x) < 0)
#define R_SUMMARY(x) (-(x))
#define RS_NOTFOUND 1
#define FS_OPEN_READ 1
#define PATH_ASCII 0
#define g_sd 0
#define fsMakePath(t,p) (p)
#define REC_CXI_FS "/module"
#define REC_LAUNCH_FS "/helper"
#define REC_DIR_FS "/rec"
#define app_log(...) ((void)0)
"""

MEMORY = r"""
static RecShared page, backing, unrelated;
static u32 mapped, legacyAddress;
static bool running;
static unsigned exitCount, unrelatedWrite;
#define MAP_VA ((uintptr_t)&page)
#define CUR_PROCESS_HANDLE 77
#define REC_SHARED_VA 0x00132000u
#define MEMSTATE_FREE 0
#define MEMPERM_READWRITE 3
#define g_mapLock 0
static void LightLock_Lock(int *unused){}
static void LightLock_Unlock(int *unused){}
#undef g_mapLock
static int g_mapLock;
static Result svcGetProcessList(s32 *n, u32 *pids, int cap) {
    pids[0]=1; pids[1]=2; *n=running?2:1; return 0;
}
static Result svcOpenProcess(Handle *h,u32 pid){*h=pid;return 0;}
static Result svcGetProcessInfo(s64 *out, Handle h, u32 id) {
    *out=0;
    if(id==0x10000) memcpy(out,"rec3ds",6);
    else *out=h==2?(s64)REC_TITLE_ID:99;
    return 0;
}
static void svcCloseHandle(Handle h){}
static Result svcQueryMemory(MemInfo *mi, PageInfo *pi, uintptr_t a){mi->state=mapped?1:0;return 0;}
static Result svcQueryProcessMemory(MemInfo *mi, PageInfo *pi, Handle h, u32 va) {
    mi->base_addr=va; mi->state=1; mi->perm=3; mi->size=0x1000;
    if(va<0x0012f000){mi->state=0;mi->size=0x0012f000-va;}
    if(va>=0x00134000){mi->state=0;mi->size=0x04000000-va;}
    return 0;
}
static Result svcMapProcessMemoryEx(Handle dst, uintptr_t va,Handle m,u32 a,u32 s,int flags) {
    if(!running || m!=2 || mapped) return -1;
    mapped=a; page=a==legacyAddress?backing:unrelated; return 0;
}
static Result svcUnmapProcessMemoryEx(Handle h,uintptr_t va,u32 s) {
    if(mapped==legacyAddress) backing=page;
    else if(memcmp(&page,&unrelated,sizeof(page))) unrelatedWrite++;
    mapped=0; return 0;
}
static void svcSleepThread(unsigned delay) {
    if(backing.cmd==REC_CMD_EXIT){running=false;exitCount++;}
}
"""

IO = r"""
static int failRename, failRestore, renameIndex, failIO;
static FILE *writing, *reading;
static const char *local(const char *path) {
    if(!strncmp(path,"sdmc:/",6)) return path+6;
    if(!strncmp(path,"romfs:/",7)) return path+7;
    return path[0]=='/'?path+1:path;
}
static Result FSUSER_OpenFile(Handle *h,int sd,const char *name,int mode,int flags) {
    FILE *f=fopen(local(name),"rb");
    if(!f) return errno==ENOENT?-1:-2;
    fclose(f); *h=1; return 0;
}
static Result FSFILE_Close(Handle h){return 0;}
static Result FSUSER_CreateDirectory(int sd,const char *name,int unused){return 0;}
static Result FSUSER_DeleteFile(int sd,const char *name) {
    return remove(local(name))==0?0:errno==ENOENT?-1:-2;
}
static Result FSUSER_RenameFile(int a,const char *from,int b,const char *to) {
    if(++renameIndex==failRename) return -2;
    if(failRestore && strstr(from,".yu-old")) return -2;
    Handle h;
    if(FSUSER_OpenFile(&h,0,to,1,0)==0) return -2;
    return rename(local(from),local(to));
}
static FILE *openHook(const char *path,const char *mode) {
    if(failIO==5 && strstr(path,"rec3ds-launch.3gx")) {errno=EIO; return NULL;}
    FILE *f=fopen(local(path),mode);
    if(f && !strcmp(mode,"wb")) writing=f;
    if(f && !strcmp(mode,"rb") && !strncmp(path,"romfs:",6)) reading=f;
    return f;
}
static int errorHook(FILE *f) {
    return (f==reading && ((writing && failIO==1) || (renameIndex==4 && failIO==6))) || ferror(f);
}
static size_t writeHook(const void *p,size_t size,size_t count,FILE *f) {
    if(f==writing && failIO==2) return 0;
    return fwrite(p,size,count,f);
}
static int flushHook(FILE *f) {return (f==writing && failIO==3)?EOF:fflush(f);}
static int closeHook(FILE *f) {
    int rc=(f==writing && failIO==4)?EOF:0;
    if(f==writing) writing=NULL;
    if(f==reading) reading=NULL;
    return fclose(f)?EOF:rc;
}
#define fopen openHook
#define ferror errorHook
#define fwrite writeHook
#define fflush flushHook
#define fclose closeHook
"""

CASES = r"""
#undef fopen
#undef fclose
#undef fflush
#undef fwrite
#undef ferror
static void put(const char *path,const char *data) {
    FILE *f=fopen(local(path),"wb");assert(f); size_t n=strlen(data);
    assert(fwrite(data,1,n,f)==n && fclose(f)==0);
}
static bool is(const char *path,const char *s) {
    FILE *f=fopen(local(path),"rb");if(!f)return false;
    char buf[64]={0}; fread(buf,1,sizeof(buf)-1,f);fclose(f);return !strcmp(s,buf);
}
static void reset(void) {
    for(unsigned i=0;i<2;i++){
        remove(local(installFiles[i].staged)); remove(local(installFiles[i].backup));
    }
    put(REC_CXI_FS,"OLD module"); put(REC_LAUNCH_FS,"OLD helper");
    put(installFiles[0].source,"NEW module");put(installFiles[1].source,"NEW helper");
    failIO=0;failRename=0;failRestore=0;renameIndex=0;exitCount=0;
    running=false;mapped=0;memset(&backing,0,sizeof(backing));memset(&unrelated,0,sizeof(unrelated));
    legacyAddress=0x0012f000;g_sharedVa=REC_SHARED_VA;
    backing.magic=REC_SHARED_MAGIC;backing.version=4;backing.state=REC_STATE_IDLE;
}
static void oldPair(void) {assert(is(REC_CXI_FS,"OLD module"));assert(is(REC_LAUNCH_FS,"OLD helper"));}
static void newPair(void) {assert(is(REC_CXI_FS,"NEW module"));assert(is(REC_LAUNCH_FS,"NEW helper"));}
int main(void) {
    const char *step;
    for(int i=1;i<=6;i++) {
        reset();failIO=i;assert(!InstallFiles(&step));oldPair();
        failIO=0;assert(InstallFiles(&step));newPair();
    }
    for(int i=1;i<=4;i++) {
        reset();failRename=i;assert(!InstallFiles(&step));oldPair();
        failRename=0;assert(InstallFiles(&step));newPair();
    }
    reset();failRename=4;failRestore=1;assert(!InstallFiles(&step));
    assert(is(installFiles[0].backup,"OLD module") && is(installFiles[1].backup,"OLD helper"));
    failRestore=failRename=0;assert(InstallFiles(&step));newPair();
    reset(); remove(local(REC_CXI_FS)); remove(local(REC_LAUNCH_FS));
    failRename=2;assert(!InstallFiles(&step));assert(!FilePresent(REC_CXI_FS)&&!FilePresent(REC_LAUNCH_FS));
    failRename=0;assert(InstallFiles(&step));newPair();
    reset();assert(MoveOwned(REC_CXI_FS,installFiles[0].backup));put(REC_CXI_FS,"NEW module");
    assert(MoveOwned(REC_LAUNCH_FS,installFiles[1].backup));failIO=2;assert(!InstallFiles(&step));oldPair();
    failIO=0;assert(InstallFiles(&step));newPair();
    for(int i=0;i<2;i++) {
        reset();running=true;legacyAddress=i?0x00130000u:0x0012f000u;
        unrelated.magic=REC_SHARED_MAGIC;unrelated.version=42;
        RecStatus st; recorder_status(&st);
        assert(st.running&&st.readable&&!st.currentBuild&&g_sharedVa==legacyAddress&&OpenModule()==2);
        App a={st,MODULE_SAME};assert(update_ready(&a));
        assert(InstallFiles(&step)&&exitCount==1&&!running&&!unrelatedWrite);newPair();
    }
    reset();running=true;backing.state=REC_STATE_RECORDING;
    RecStatus st;recorder_status(&st);App a={st,MODULE_SAME};assert(!update_ready(&a));
    assert(!InstallFiles(&step)&&!exitCount&&running);oldPair();
    reset();running=true;backing.version=REC_SHARED_VERSION;backing.buildTag=0;
    assert(!recorder_command(REC_CMD_EXIT)&&!InstallFiles(&step)&&!unrelatedWrite);oldPair();
    reset();running=true;put(REC_CXI_FS,"NEW module");put(REC_LAUNCH_FS,"NEW helper");
    assert(InstallFiles(&step)&&exitCount==1);newPair();
    reset();running=true;backing.version=REC_SHARED_VERSION;backing.buildTag=REC_BUILD_TAG;
    put(REC_CXI_FS,"NEW module");assert(InstallFiles(&step)&&!exitCount&&running);newPair();
    puts("Recorder upgrade: SD write/read/flush/close and rename rollback, interruption, retry, old and current shared pages passed");
    return 0;
}
"""

if __name__ == "__main__":
    run()
