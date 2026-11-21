#ifndef YU_RECORDER_CONTROL_HANDLER_H
#define YU_RECORDER_CONTROL_HANDLER_H

#include <stdbool.h>
#include <stdint.h>
#include "shared.h"
#include "recorder_protocol.h"

static inline void YuRecorder_Handle(uint32_t *cmd, volatile RecShared *shared, bool *exitRequested)
{
    const uint32_t header = cmd[0];
    if (header == YU_REC_STATUS_REQUEST) {
        cmd[0] = YU_REC_STATUS_REPLY;
        cmd[1] = 0;
        cmd[2] = YU_REC_MAGIC;
        cmd[3] = YU_REC_PROTOCOL_VERSION;
        cmd[4] = shared->state;
        cmd[5] = shared->recSeconds;
        cmd[6] = shared->recKb;
        cmd[7] = shared->framesTop;
        cmd[8] = shared->framesBot;
        cmd[9] = shared->dropped;
        cmd[10] = shared->files;
        cmd[11] = (uint32_t)shared->lastError;
        cmd[12] = shared->replayOn;
        return;
    }
    const uint32_t action = cmd[1];
    cmd[0] = ((header >> 16) << 16) | 0x40u;
    cmd[1] = YU_REC_ERROR_INVALID;
    if (header != YU_REC_COMMAND_REQUEST || action < YU_REC_CMD_EXIT || action > YU_REC_CMD_SAVE_CLIP)
        return;
    if (*exitRequested || shared->state == REC_STATE_EXITED) {
        cmd[1] = YU_REC_ERROR_EXITING;
        return;
    }
    const uint32_t state = shared->state;
    const bool idle = state == REC_STATE_IDLE;
    const bool recording = state == REC_STATE_RECORDING;
    const bool replay = state == REC_STATE_REPLAY;
    if ((action == YU_REC_CMD_START && !(idle || replay)) ||
        (action == YU_REC_CMD_STOP && !recording) ||
        (action == YU_REC_CMD_SAVE_CLIP && !replay) ||
        (action == YU_REC_CMD_RELOAD && !(idle || recording || replay))) {
        cmd[1] = YU_REC_ERROR_STATE;
        return;
    }
    uint32_t expected = REC_CMD_NONE;
    if (!__atomic_compare_exchange_n(&shared->cmd, &expected, action, false, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST)) {
        cmd[1] = YU_REC_ERROR_BUSY;
        return;
    }
    if (action == YU_REC_CMD_EXIT)
        *exitRequested = true;
    cmd[1] = 0;
}

#endif
