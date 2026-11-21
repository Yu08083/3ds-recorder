#ifndef REC_CTRPF_DISPLAY_H
#define REC_CTRPF_DISPLAY_H

#include <stdbool.h>
#include <stdint.h>

static inline bool ctrpf_display_layout(int sc, uint32_t fmt, uint32_t stride, uint32_t size)
{
    if ((sc != 0 && sc != 1) || (fmt & 7u) != 2u || stride != 480u)
        return false;
    if (sc == 0 && (fmt & 0x60u) != 0x40u)
        return false;
    return size == (sc == 0 ? 400u : 320u) * 480u;
}

static inline uint32_t ctrpf_display_buffer(int sc, unsigned index)
{
    const uint32_t first = 0x06000000u;
    const uint32_t top = 400u * 480u;
    const uint32_t bottom = 320u * 480u;
    return sc == 0 ? first + index * top : first + 2u * top + index * bottom;
}

#endif
