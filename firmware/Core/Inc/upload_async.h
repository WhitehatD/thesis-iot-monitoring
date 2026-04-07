/**
 * @file    upload_async.h
 * @brief   Non-blocking HTTP Image Upload — Cooperative State Machine
 * @author  Alexandru-Ionut Cioc
 * @date    2026
 *
 * Breaks the blocking WiFi_HttpPostImage into a cooperative state machine
 * that sends chunks in the main loop, yielding between iterations for
 * MQTT processing, watchdog refresh, and new command handling.
 *
 * Architecture (cooperative scheduling / run-to-completion):
 *   Main loop calls Upload_Poll() each iteration.
 *   Each call sends up to UPLOAD_CHUNK_PER_POLL bytes (~16KB),
 *   then returns immediately. Total upload time is the same,
 *   but the system remains responsive throughout.
 *
 * References:
 *   - Dunkels et al., "Protothreads" (SenSys 2006)
 *   - Samek, "Practical UML Statecharts in C/C++" (2009)
 */

#ifndef __UPLOAD_ASYNC_H
#define __UPLOAD_ASYNC_H

#include <stdint.h>

/* ── Upload States ─────────────────────────────────── */

typedef enum {
    UPLOAD_IDLE = 0,       /* No upload in progress */
    UPLOAD_CONNECTING,     /* Opening TCP socket to server */
    UPLOAD_SEND_HEADER,    /* Sending HTTP + multipart headers */
    UPLOAD_SEND_DATA,      /* Sending image data in chunks */
    UPLOAD_SEND_FOOTER,    /* Sending multipart footer */
    UPLOAD_RECV_RESPONSE,  /* Waiting for HTTP response */
    UPLOAD_COMPLETE,       /* Upload finished successfully */
    UPLOAD_FAILED,         /* Upload failed (socket error, timeout) */
} UploadState_t;

/* ── Upload Context ────────────────────────────────── */

typedef struct {
    UploadState_t state;
    int32_t       sock;            /* TCP socket handle */
    uint32_t      task_id;         /* Task ID for status reporting */
    uint8_t      *data;            /* Pointer to image buffer (not owned) */
    uint32_t      data_len;        /* Total image size in bytes */
    uint32_t      offset;          /* Current send offset within data phase */
    uint32_t      start_tick;      /* HAL_GetTick at upload start */
    uint8_t       retries;         /* Current retry count */

    /* Pre-built wire-format segments */
    char          http_header[512];
    int           http_header_len;
    char          part_header[256];
    int           part_header_len;
    char          part_footer[64];
    int           part_footer_len;
    int           segment_offset;  /* Progress within current segment send */
} UploadCtx_t;

/**
 * @brief  Start a non-blocking image upload.
 *
 * Prepares the HTTP request and transitions to UPLOAD_CONNECTING.
 * Call Upload_Poll() repeatedly from the main loop to drive progress.
 *
 * @param  ctx: Upload context (caller-owned, must persist until complete).
 * @param  task_id: Task ID for the image.
 * @param  data: Pointer to RGB565 image data.
 * @param  data_len: Image data length in bytes.
 * @retval 0 on success (state → UPLOAD_CONNECTING), -1 if busy.
 */
int Upload_Start(UploadCtx_t *ctx, uint32_t task_id,
                 uint8_t *data, uint32_t data_len);

/**
 * @brief  Drive one iteration of the upload state machine.
 *
 * Sends up to UPLOAD_CHUNK_PER_POLL bytes, then returns.
 * Call this every main loop iteration when Upload_IsBusy() is true.
 *
 * @param  ctx: Upload context.
 * @retval Current state after this iteration.
 */
UploadState_t Upload_Poll(UploadCtx_t *ctx);

/**
 * @brief  Check if an upload is in progress.
 * @retval 1 if busy (CONNECTING..RECV_RESPONSE), 0 if idle/complete/failed.
 */
int Upload_IsBusy(const UploadCtx_t *ctx);

/**
 * @brief  Abort an in-progress upload and close the socket.
 */
void Upload_Abort(UploadCtx_t *ctx);

#endif /* __UPLOAD_ASYNC_H */
