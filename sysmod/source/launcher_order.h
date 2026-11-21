#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#define USER_PARAM_MAGIC 0x53524550u
#define ORDER_RESUME 0x52455331u
#define ORDER_OWNER 0x52454359u

typedef struct {
    uint8_t noFlash, memoryStrategy, persistent, pad;
    uint32_t lowTitleId;
    char path[256];
    uint32_t config[32];
} PluginLoadParams;

typedef struct {
    uint32_t magic;
    PluginLoadParams p;
} RecorderLauncherOrder;

_Static_assert(sizeof(RecorderLauncherOrder) == 396, "Recorder launcher order size");

static inline bool RecorderOwnsOrder(const RecorderLauncherOrder *order)
{
    static const char path[] = "/3ds/recorder/rec3ds-launch.3gx";
    return order->magic == USER_PARAM_MAGIC && order->p.noFlash == 1 && order->p.lowTitleId &&
           order->p.memoryStrategy == 1 && !order->p.persistent && !memcmp(order->p.path, path, sizeof(path));
}
