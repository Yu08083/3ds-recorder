import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "sysmod/source/main.c").read_text(encoding="utf-8")


def fragment(start, end):
    begin = source.index(start)
    return source[begin:source.index(end, begin)]


pre = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "codec.h"
#include "convert.h"
#include "ctrpf_display.h"
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
typedef int Handle, Result;
typedef struct { unsigned flags; } DmaConfig;
enum { WIDTH = 400, HEIGHT = 240, PIXELS = WIDTH * HEIGHT, MAX_SLOTS = 1 };
static u64 clockUs, g_recStartTick, g_appSwapUs;
static u32 regs[2][64], g_torn[2], g_throttled, g_bottomKeep=1, g_ringSize=1024;
static bool g_paced, g_replay, g_appSwapSeen;
static struct {bool top,bottom; u32 bottomFps,fps;} g_cfg = {true,true,0,30};
#define REG32(offset) regs[(offset) >> 8][((offset) & 255) >> 2]
#define PDC_VA(sc) ((sc) << 8)
#define Ticks() clockUs
#define TicksToUs64(x) (x)
#define RingFill() 0u
#define PaceUpdate(now,fill) ((void)0)
#define PaceTake(sc) true
#define BusySlots(sc) 0u
#define IsVram(addr) false
#define Log(...) ((void)0)
#define Drop(...) ((void)0)
#define R_FAILED(rc) ((rc)<0)
#define R_SUCCEEDED(rc) ((rc)>=0)
#define Bpp(fmt) ((fmt & 7u)==FB_RGBA8 ? 4u : (fmt & 7u)==FB_BGR8 ? 3u : 2u)
static u16 surfaces[3][2][PIXELS], copies[2][PIXELS], prev[2][PIXELS], decoded[2][PIXELS];
static u8 payload[PIXELS * 3];
static u32 frames[2], attempts[2], blocked, g_dmaMaxRunning, opens, closes, g_appPid, g_appBase;
static bool g_recording = true;
static int g_dmaStartRc;
static const u32 g_arenaCap[2] = {sizeof(copies[0]), sizeof(copies[1])}, g_slotCount[2]={1,1};
#define DmasRunning() blocked
#define EnsureSlots(sc,size) true

#define CUR_PROCESS_HANDLE 1
#define VRAM_PA 0x18000000u
#define VRAM_SIZE 0x600000u
#define VRAM_VA 0x1f000000u
#define SYSCLOCK_ARM11 1000000u
static u32 badPage, noPage, reads, readable=1;
static bool FindApp(void) {g_appPid=33;return true;}
static Result svcOpenProcess(Handle *h,u32 pid) {assert(pid==33);*h=11;opens++;return 0;}
static Result svcCloseHandle(Handle h) {assert(h==11);closes++;return 0;}
static void dmaConfigInitDefault(DmaConfig *cfg){cfg->flags=0;}
static u32 gameAddr(int sc){return sc ? 0x21800000u : 0x21000000u;}
static const u32 fixtureVa[2][2] = {{0x06000000u,0x0602ee00u},{0x0605dc00u,0x06083400u}};
static u32 surfaceAddr(int sc, unsigned bank){
    if(!bank)return gameAddr(sc);
    if(bank>2)return 0x2a000000u;
    return 0x26800000u+fixtureVa[sc][bank-1]-0x06000000u;
}
static Result svcControlProcess(Handle app,u32 op,uintptr_t dest,u32 va){
    assert(app==11 && op==4 && va>=0x06000000u && va<0x060a8c00u);
    reads++;
    if(va==noPage)return -1;
    *(u32*)dest=0x26800000u+va-0x06000000u+(va==badPage ? 4096u : 0u);
    return 0;
}
static bool RangeReadable(Handle app,u32 va,u32 size){
    assert(app==11);
    for(int sc=0;sc<2;sc++)
        if(size==(sc ? 320u : 400u)*480u && (va==gameAddr(sc)-0x0c000000u ||
           va==fixtureVa[sc][0] || va==fixtureVa[sc][1]))return readable;
    return false;
}
static Result svcStartInterProcessDma(Handle *h,Handle dstProc,uintptr_t dst,Handle srcProc,
                                      u32 va,u32 size,DmaConfig *cfg){
    assert(dstProc==1 && srcProc==11 && cfg->flags==0);
    for(int sc=0;sc<2;sc++)for(unsigned bank=0;bank<3;bank++){
        if(va != (bank ? fixtureVa[sc][bank-1] : gameAddr(sc)-0x0c000000u))continue;
        assert(size==(sc ? 320u : 400u)*480u);
        attempts[sc]++;
        memcpy((void*)dst,surfaces[bank][sc],size);
        *h=1;
        return 0;
    }
    abort();
}
"""

worker = r"""
static Slot g_slots[2];
static void finishDma(void){
    for(int sc=0;sc<2;sc++){
        Slot *slot=&g_slots[sc];
        if(!slot->state) continue;
        u32 cols=sc ? 320u : 400u;
        int key = frames[sc] == 0;
        size_t n=codec_xr32_encode_strided(prev[sc],slot->buf,cols,HEIGHT,slot->stride,1,key,payload);
        assert(codec_xr32_decode(payload,n,decoded[sc],cols*HEIGHT,key)==0);
        frames[sc]++;
        slot->state=0;
    }
}
#define LightEvent_Signal(event) finishDma()
"""

cases = r"""
static void selectSurface(u32 bank, u32 flag) {
    for(int sc=0;sc<2;sc++){
        u32 base=PDC_VA(sc);
        u32 sel=bank&1u;
        REG32(base+0x68+sel*4u)=surfaceAddr(sc,bank);
        REG32(base+0x70)=(sc ? 0u : 0x40u)|FB_RGB565|flag;
        REG32(base+0x78)=sel;
        REG32(base+0x90)=480;
    }
}
static void poll(u32 us){clockUs=us; PollScreens();}
static void picture(int bank){
    for(int sc=0;sc<2;sc++)
        assert(!memcmp(decoded[sc],surfaces[bank][sc],(sc ? 320u : 400u)*480u));
}
static void checkRejectedScreens(void) {
    assert(!ctrpf_display_layout(-1,2,480,320*480));
    assert(!ctrpf_display_layout(2,2,480,320*480));
    assert(!ctrpf_display_layout(0,2,480,400*480));
    assert(!ctrpf_display_layout(0,0x42,481,400*480));
    assert(!ctrpf_display_layout(0,0x42,480,400*480-1));
    selectSurface(1,0);
    u32 sent=attempts[0]+attempts[1];
    Handle h=0;
    for(int sc=0;sc<2;sc++) for(unsigned i=0;i<2;i++){
        selectSurface(i+1,0);
        const u32 va=fixtureVa[sc][i], pa=surfaceAddr(sc,i+1);
        assert(ctrpf_display_buffer(sc,i)==va);
        const u32 fmt=sc ? 2u : 0x42u, size=(sc ? 320u : 400u)*480u, base=PDC_VA(sc);
        badPage=(va & ~0xfffu)+0x2000u;
        assert(R_FAILED(StartFrameDma(&h,(u8*)copies[sc],sc,pa,fmt,480,size)));
        badPage=0;noPage=(va+size-1u)&~0xfffu;
        assert(R_FAILED(StartFrameDma(&h,(u8*)copies[sc],sc,pa,fmt,480,size)));
        noPage=0;readable=0;
        assert(R_FAILED(StartFrameDma(&h,(u8*)copies[sc],sc,pa,fmt,480,size)));
        readable=1;
        REG32(base+0x70)=0;
        assert(R_FAILED(StartFrameDma(&h,(u8*)copies[sc],sc,pa,fmt,480,size)));
        REG32(base+0x70)=fmt;
        REG32(base+0x68+(REG32(base+0x78)&1u)*4u)=surfaceAddr(sc,3);
        assert(R_FAILED(StartFrameDma(&h,(u8*)copies[sc],sc,pa,fmt,480,size)));
        assert(R_FAILED(StartFrameDma(&h,(u8*)copies[sc],sc,surfaceAddr(!sc,i+1),fmt,480,size)));
    }
    assert(attempts[0]+attempts[1]==sent && opens==closes);
}
int main(void){
    for(int sc=0;sc<2;sc++){
        g_slots[sc].buf=(u8 *)copies[sc];
        for(int x=0;x<(sc ? 320 : 400);x++) for(int y=0;y<HEIGHT;y++){
            int k=x*HEIGHT+y;
            surfaces[0][sc][k]=(u16)(x*11+y*3+sc);
            surfaces[1][sc][k]=(x>15 && x<270 && y>40 && y<90) ? 0xfff0 : 0x1001;
            surfaces[2][sc][k]=(x>15 && x<270 && y>90 && y<140) ? 0xfff0 : 0x1001;
        }
    }
    selectSurface(0,0x100);poll(1000000);picture(0);
    selectSurface(1,0);poll(1034000);poll(1200000);picture(0);
    blocked=DMA_MAX_RUNNING;poll(1235000);picture(0);
    blocked=0;poll(1270000);picture(1);
    poll(1500000);assert(frames[0]==2 && frames[1]==2);
    selectSurface(2,0);poll(1534000);picture(2);
    selectSurface(0,0x100);poll(1568000);poll(1769000);picture(0);
    selectSurface(3,0);poll(1810000);poll(2011000);
    u32 before=opens;
    for(u32 t=2020000;t<2500000;t+=2000)poll(t);
    assert(before==opens);picture(0);
    selectSurface(1,0);poll(2600000);picture(1);
    selectSurface(1,0x100);poll(2620000);poll(2830000);
    assert(frames[0]==6 && frames[1]==6);
    checkRejectedScreens();
    puts("Game -> menu -> selection -> game: both CTRPF buffers on both screens decoded; stale, unmapped and discontinuous displays rejected");
}
"""

defines = ("POLL_REC_US", "POLL_EARLY_US", "STATIC_GAP_US", "THROTTLE_PCT", "THROTTLE_HARD_PCT",
           "BOTTOM_MIN_GAP_US", "TORN_US", "MODE_SETTLE_US", "VBLANK_US", "LATE_AFTER_US",
           "LATE_BEFORE_US", "FAST_SWAP_US", "DMA_MAX_RUNNING")
parts = ["#include <stdlib.h>",pre]
for name in defines:
    parts.append(re.search(r"^#define " + name + r"\s+\w+", source, re.M)[0])
slot_end = source.index("} Slot;") + len("} Slot;")
dma = fragment("static bool StartCtrpfDisplayDma", "static u32 Bpp")
dma = dma.replace("(u32)&pixelPa", "(uintptr_t)&pixelPa").replace("(u32)dst", "(uintptr_t)dst")
dma = dma.replace("*(const volatile u32 *)0x1FF80040", "0x04000000u")
parts.extend([source[source.rindex("typedef struct", 0, slot_end):slot_end], worker, dma,
              fragment("typedef enum { FRAME_QUEUED", "static bool IsVram"),
              "static u64 g_lastPollUs;", fragment("static u32 PollScreens(void)", "/* C420 from"), cases])
with tempfile.TemporaryDirectory() as temp:
    c = Path(temp) / "display.c"
    exe = c.with_suffix(".exe" if os.name == "nt" else "")
    c.write_text("\n".join(parts), encoding="utf-8")
    cc = shlex.split(os.environ["CC"]) if os.environ.get("CC") else [shutil.which("cc") or shutil.which("gcc")]
    subprocess.run([*cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2",
                    "-I", str(ROOT / "codec/include"), "-I", str(ROOT / "sysmod/source"),
                    str(c), str(ROOT / "codec/source/codec.c"),
                    "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
