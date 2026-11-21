#include <3ds.h>
#include <stdbool.h>
#include "control.h"
#include "control_handler.h"

extern volatile RecShared g_shared;

static Handle g_controlStop;
static Handle g_controlPort;
static Thread g_controlThread;
static bool g_controlExit;

static void ControlMain(void *unused)
{
    (void)unused;
    Handle handles[4] = {g_controlStop, g_controlPort, 0, 0};
    unsigned sessions = 0;
    Handle reply = 0;
    u32 *cmd = getThreadCommandBuffer();
    for (;;) {
        if (!reply)
            cmd[0] = 0xFFFF0000u;
        s32 index = -1;
        Result rc = svcReplyAndReceive(&index, handles, 2 + sessions, reply);
        if ((u32)rc == 0xC920181Au) {
            if (index == -1)
                for (unsigned i = 2; i < 2 + sessions; i++)
                    if (handles[i] == reply) {
                        index = (s32)i;
                        break;
                    }
            if (index < 2 || (unsigned)index >= 2 + sessions)
                break;
            svcCloseHandle(handles[index]);
            handles[index] = handles[1 + sessions];
            handles[1 + sessions] = 0;
            sessions--;
            reply = 0;
            continue;
        }
        reply = 0;
        if (R_FAILED(rc) || index == 0)
            break;
        if (index == 1) {
            Handle session = 0;
            rc = svcAcceptSession(&session, handles[1]);
            if (R_FAILED(rc))
                break;
            if (sessions == 2)
                svcCloseHandle(session);
            else
                handles[2 + sessions++] = session;
        } else if (index >= 2 && (unsigned)index < 2 + sessions) {
            YuRecorder_Handle(cmd, &g_shared, &g_controlExit);
            reply = handles[index];
        } else {
            break;
        }
    }
    for (unsigned i = 1; i < 2 + sessions; i++)
        svcCloseHandle(handles[i]);
}

bool Control_Start(void)
{
    if (g_controlThread)
        return true;
    if (R_FAILED(svcCreateEvent(&g_controlStop, RESET_STICKY)))
        return false;
    Handle client = 0;
    if (R_FAILED(svcCreatePort(&g_controlPort, &client, YU_REC_PORT, 2))) {
        svcCloseHandle(g_controlStop);
        g_controlStop = 0;
        return false;
    }
    svcCloseHandle(client);
    g_controlExit = false;
    g_controlThread = threadCreate(ControlMain, NULL, 0x2000, 0x30, 1, false);
    if (!g_controlThread) {
        svcCloseHandle(g_controlPort);
        svcCloseHandle(g_controlStop);
        g_controlPort = g_controlStop = 0;
        return false;
    }
    return true;
}

void Control_Stop(void)
{
    if (!g_controlThread)
        return;
    svcSignalEvent(g_controlStop);
    if (R_SUCCEEDED(threadJoin(g_controlThread, 1000000000ull))) {
        threadFree(g_controlThread);
        svcCloseHandle(g_controlStop);
        g_controlThread = NULL;
        g_controlPort = g_controlStop = 0;
    }
}
