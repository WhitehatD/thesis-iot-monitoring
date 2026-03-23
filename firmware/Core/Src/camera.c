/**
 * @file    camera.c
 * @brief   OV5640 Camera Capture via BSP DCMI Interface — Optimized
 * @author  Alexandru-Ionut Cioc
 * @date    2026
 *
 * Wraps the BSP_CAMERA functions for the MB1379 camera module (OV5640 sensor)
 * on the B-U585I-IOT02A Discovery Kit.
 *
 * Enterprise optimizations applied:
 *   - Adaptive AEC polling (replaces fixed 2s delay)
 *   - Continuous-mode warm-up (replaces 6× snapshot Start/Stop loop)
 *   - Lower VTS for ~12fps frame rate (83ms/frame vs 330ms)
 *   - PCLK boost for faster pixel throughput
 *   - Compile-time SRAM budget validation
 *   - Diagnostics gated behind CAMERA_DIAG_ENABLED flag
 *
 * Capture flow:
 *   1. Camera_Init() — power up sensor, configure resolution + register tuning
 *   2. Camera_CaptureFrame() — continuous-mode warm-up + final frame capture
 *   3. Camera_DeInit() — power down to save energy before sleep
 */

#include "app_camera.h"
#include "firmware_config.h"
#include "debug_log.h"
#include "main.h"

#include "b_u585i_iot02a_camera.h"
#include "b_u585i_iot02a_bus.h"

#include <string.h>

/* ═══════════════════════════════════════════════════════════════════════════
 *  Compile-Time Safety Gate
 *
 *  Enterprise practice: if anyone changes CAMERA_FRAME_BUFFER_SIZE or
 *  resolution to a value that would overflow SRAM, the build fails
 *  immediately with a clear error rather than silently corrupting RAM.
 * ═══════════════════════════════════════════════════════════════════════════ */

_Static_assert(CAMERA_FRAME_BUFFER_SIZE <= CAMERA_FRAME_BUFFER_MAX,
    "FATAL: CAMERA_FRAME_BUFFER_SIZE exceeds safe SRAM budget! "
    "Reduce resolution or increase RAM_SAFETY_MARGIN_BYTES.");

/* ═══════════════════════════════════════════════════════════════════════════
 *  Module State
 * ═══════════════════════════════════════════════════════════════════════════ */

static volatile uint32_t s_frame_count = 0;   /* Counts frames in continuous mode */
static volatile uint32_t s_frame_size  = 0;
static volatile uint8_t  s_initialized = 0;    /* 1 = camera is warm and ready */

/* Pointer to the active capture buffer (set by Camera_CaptureFrame) */
static uint8_t *s_active_buffer = NULL;

/* ═══════════════════════════════════════════════════════════════════════════
 *  OV5640 I2C Address
 * ═══════════════════════════════════════════════════════════════════════════ */

#define OV5640_I2C_ADDR  0x78

/* ═══════════════════════════════════════════════════════════════════════════
 *  Resolution Mapping
 * ═══════════════════════════════════════════════════════════════════════════ */

/**
 * Map our CameraResolution_t enum to the BSP CAMERA_RES_xxx constants.
 */
static uint32_t _map_resolution(CameraResolution_t res)
{
    switch (res)
    {
        case CAMERA_RES_QVGA:  return CAMERA_R320x240;
        case CAMERA_RES_VGA:   return CAMERA_R640x480;
        case CAMERA_RES_SVGA:  return CAMERA_R800x480;  /* Closest — BSP has no 800x600 */
        case CAMERA_RES_XGA:   return CAMERA_R800x480;  /* Closest — BSP has no 1024x768 */
        default:               return CAMERA_R640x480;
    }
}

/**
 * Return the expected raw frame size for a given resolution (RGB565).
 * In JPEG mode the actual captured size will be much smaller.
 */
static uint32_t _raw_frame_size(CameraResolution_t res)
{
    switch (res)
    {
        case CAMERA_RES_QVGA: return 320 * 240 * 2;
        case CAMERA_RES_VGA:  return 640 * 480 * 2;
        case CAMERA_RES_SVGA: return 800 * 600 * 2;
        case CAMERA_RES_XGA:  return 1024 * 768 * 2;
        default:              return 640 * 480 * 2;
    }
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  AEC Convergence Polling (replaces fixed HAL_Delay)
 *
 *  Enterprise practice: poll the ISP's current exposure level register
 *  rather than blindly waiting. Returns as soon as AEC has settled,
 *  saving 500ms–1.5s in well-lit environments.
 * ═══════════════════════════════════════════════════════════════════════════ */

/**
 * @brief  Wait for OV5640 AEC to converge, with hard timeout.
 *
 * Polls the AEC average luminance register (0x56A1) and compares against
 * the AEC target brightness bands we configured. If we can't read the
 * register, falls back to a fixed delay.
 */
static void _wait_aec_converge(void)
{
    uint32_t start = HAL_GetTick();
    uint8_t  avg_lum;
    int32_t  ret;

    /* Target band from our register writes: stable-in low=0x68, high=0x78 */
    const uint8_t AEC_TARGET_LOW  = 0x50;  /* Allow some tolerance below target */
    const uint8_t AEC_TARGET_HIGH = 0x90;  /* Allow some tolerance above target */

    LOG_DEBUG(TAG_CAM, "Waiting for AEC convergence (timeout=%dms)...",
              CAMERA_AEC_SETTLE_TIMEOUT_MS);

    while ((HAL_GetTick() - start) < (uint32_t)CAMERA_AEC_SETTLE_TIMEOUT_MS)
    {
        /* 0x56A1 = AEC average luminance (ro, updated each frame) */
        ret = BSP_I2C1_ReadReg16(OV5640_I2C_ADDR, 0x56A1, &avg_lum, 1);
        if (ret == 0 && avg_lum >= AEC_TARGET_LOW && avg_lum <= AEC_TARGET_HIGH)
        {
            LOG_INFO(TAG_CAM, "AEC converged in %lums (lum=0x%02X)",
                     (unsigned long)(HAL_GetTick() - start), avg_lum);
            return;
        }

        HAL_Delay(100);  /* Poll every 100ms */
    }

    /* Read final value for diagnostics */
    BSP_I2C1_ReadReg16(OV5640_I2C_ADDR, 0x56A1, &avg_lum, 1);
    LOG_WARN(TAG_CAM, "AEC timeout after %dms (lum=0x%02X — proceeding anyway)",
             CAMERA_AEC_SETTLE_TIMEOUT_MS, avg_lum);
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Initialization
 * ═══════════════════════════════════════════════════════════════════════════ */

CameraStatus_t Camera_Init(CameraResolution_t resolution)
{
    /* ── Double-init guard: skip if already warm ── */
    if (s_initialized)
    {
        LOG_INFO(TAG_CAM, "Camera already initialized (warm) — skipping init");
        return CAMERA_OK;
    }

    LOG_INFO(TAG_CAM, "Initializing OV5640 camera (resolution=%d)...", resolution);

    uint32_t bsp_res = _map_resolution(resolution);

    /*
     * BSP_CAMERA_Init:
     *   Instance = 0
     *   Resolution = bsp_res
     *   PixelFormat = CAMERA_PF_RGB565
     *
     * The BSP handles I2C configuration of the OV5640 + DCMI/DMA setup.
     */
    int32_t ret = BSP_CAMERA_Init(0, bsp_res, CAMERA_PF_RGB565);
    if (ret != BSP_ERROR_NONE)
    {
        LOG_ERROR(TAG_CAM, "BSP_CAMERA_Init failed (err=%ld)", (long)ret);
        return CAMERA_ERROR_INIT;
    }

    /*
     * ── OV5640 Register Overrides ────────────────────────────────────────
     *
     * Strategy: Keep AEC in AUTO mode (let the ISP converge naturally),
     * but raise every ceiling it's allowed to reach + optimize frame rate.
     *
     * OV5640 I2C address = 0x78 (confirmed in b_u585i_iot02a_camera.h).
     */
    uint8_t val;

    /* 1. Raise AEC Gain Ceiling to maximum 64x (default was 15.5x) */
    val = 0x03;
    BSP_I2C1_WriteReg16(OV5640_I2C_ADDR, 0x3A18, &val, 1);
    val = 0xFF;
    BSP_I2C1_WriteReg16(OV5640_I2C_ADDR, 0x3A19, &val, 1);

    /* 2. Raise AEC target brightness registers */
    val = 0x78;  /* Stable-in high (default 0x30) */
    BSP_I2C1_WriteReg16(OV5640_I2C_ADDR, 0x3A0F, &val, 1);
    val = 0x68;  /* Stable-in low  (default 0x28) */
    BSP_I2C1_WriteReg16(OV5640_I2C_ADDR, 0x3A10, &val, 1);
    val = 0xD0;  /* Fast-zone high (default 0x30) */
    BSP_I2C1_WriteReg16(OV5640_I2C_ADDR, 0x3A1B, &val, 1);
    val = 0x78;  /* Fast-zone low  (default 0x26) */
    BSP_I2C1_WriteReg16(OV5640_I2C_ADDR, 0x3A1E, &val, 1);
    val = 0x80;  /* Max gain for stable range (default 0x60) */
    BSP_I2C1_WriteReg16(OV5640_I2C_ADDR, 0x3A11, &val, 1);

    /* 3. Raise max exposure lines for both 50/60Hz bands */
    val = (uint8_t)((CAMERA_VTS_DEFAULT >> 8) & 0xFF);
    BSP_I2C1_WriteReg16(OV5640_I2C_ADDR, 0x3A02, &val, 1);  /* MAX_EXPO 60Hz HIGH */
    val = (uint8_t)(CAMERA_VTS_DEFAULT & 0xFF);
    BSP_I2C1_WriteReg16(OV5640_I2C_ADDR, 0x3A03, &val, 1);  /* MAX_EXPO 60Hz LOW  */
    val = (uint8_t)((CAMERA_VTS_DEFAULT >> 8) & 0xFF);
    BSP_I2C1_WriteReg16(OV5640_I2C_ADDR, 0x3A14, &val, 1);  /* MAX_EXPO 50Hz HIGH */
    val = (uint8_t)(CAMERA_VTS_DEFAULT & 0xFF);
    BSP_I2C1_WriteReg16(OV5640_I2C_ADDR, 0x3A15, &val, 1);  /* MAX_EXPO 50Hz LOW  */

    /* 4. Set VTS (Vertical Total Size) for faster frame rate.
     *    CAMERA_VTS_DEFAULT = 0x07D0 (2000 lines) → ~12fps at VGA.
     *    This is 4× faster than the original 0x1F80 (~3fps). */
    val = (uint8_t)((CAMERA_VTS_DEFAULT >> 8) & 0xFF);
    BSP_I2C1_WriteReg16(OV5640_I2C_ADDR, 0x380E, &val, 1);  /* VTS HIGH */
    val = (uint8_t)(CAMERA_VTS_DEFAULT & 0xFF);
    BSP_I2C1_WriteReg16(OV5640_I2C_ADDR, 0x380F, &val, 1);  /* VTS LOW  */

    /* 5. Ensure AEC stays in AUTO mode (no manual exposure override) */
    val = 0x00;  /* bit 0=0: AEC auto, bit 1=0: AGC auto */
    BSP_I2C1_WriteReg16(OV5640_I2C_ADDR, 0x3503, &val, 1);

    /* 6. Enable AEC night mode frame-rate reduction via AEC_CTRL00 */
    val = 0x7C;
    BSP_I2C1_WriteReg16(OV5640_I2C_ADDR, 0x3A00, &val, 1);

    /* 7. PCLK boost — set PLL pre-divider for higher pixel clock.
     *    Register 0x3824 (PCLK divider): lower value = faster PCLK.
     *    Default from BSP init table is usually 0x04 → set to 0x02 for 2× boost. */
    val = 0x02;
    BSP_I2C1_WriteReg16(OV5640_I2C_ADDR, 0x3824, &val, 1);

    /* ── Adaptive AEC convergence (replaces fixed 2s delay) ── */
    _wait_aec_converge();

    LOG_INFO(TAG_CAM, "Camera initialized OK (raw frame size: %lu bytes, VTS=0x%04X)",
             (unsigned long)_raw_frame_size(resolution),
             (unsigned)CAMERA_VTS_DEFAULT);

    s_initialized = 1;
    return CAMERA_OK;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Query: Is Camera Warm?
 * ═══════════════════════════════════════════════════════════════════════════ */

uint8_t Camera_IsInitialized(void)
{
    return s_initialized;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Single Frame Capture — Continuous-Mode Warm-up
 *
 *  Enterprise optimization: instead of 6× Start/Stop in Snapshot mode
 *  (each with ~50ms overhead), we use Continuous mode and count frame
 *  interrupts. This eliminates per-frame DCMI reinit overhead.
 * ═══════════════════════════════════════════════════════════════════════════ */

CameraStatus_t Camera_CaptureFrame(uint8_t *buffer, uint32_t buffer_size,
                                    uint32_t *captured_size)
{
    LOG_INFO(TAG_CAM, "Starting frame capture (%d warm-up + 1 final)...",
             CAMERA_WARMUP_FRAMES);

    if (buffer == NULL || captured_size == NULL)
    {
        LOG_ERROR(TAG_CAM, "Null buffer or size pointer");
        return CAMERA_ERROR_CAPTURE;
    }

    /* Buffer overflow guard */
    if (buffer_size < CAMERA_FRAME_BUFFER_SIZE)
    {
        LOG_ERROR(TAG_CAM, "Buffer too small (%lu < %lu)",
                  (unsigned long)buffer_size,
                  (unsigned long)CAMERA_FRAME_BUFFER_SIZE);
        return CAMERA_ERROR_CAPTURE;
    }

    const uint32_t TOTAL_FRAMES = CAMERA_WARMUP_FRAMES + 1;  /* warm-up + final */
    int32_t ret;

    /* Reset frame counter */
    s_frame_count = 0;
    s_frame_size  = 0;
    s_active_buffer = buffer;

    /* Start continuous capture — DMA writes directly into caller's buffer.
     * Each frame overwrites the previous one in-place. After TOTAL_FRAMES,
     * the buffer contains the final (well-exposed) frame. */
    ret = BSP_CAMERA_Start(0, buffer, CAMERA_MODE_CONTINUOUS);
    if (ret != BSP_ERROR_NONE)
    {
        LOG_ERROR(TAG_CAM, "BSP_CAMERA_Start (continuous) failed (err=%ld)", (long)ret);
        s_active_buffer = NULL;
        return CAMERA_ERROR_CAPTURE;
    }

    /* Wait for TOTAL_FRAMES frame-complete interrupts */
    uint32_t start_tick = HAL_GetTick();

    /* At VTS=0x07D0 (~12fps), each frame takes ~83ms.
     * Total expected: ~83ms × 4 = ~330ms.
     * Timeout: generous 3s to handle low-light slow-down. */
    const uint32_t CAPTURE_TIMEOUT_MS = 3000;

    while (s_frame_count < TOTAL_FRAMES)
    {
        if ((HAL_GetTick() - start_tick) > CAPTURE_TIMEOUT_MS)
        {
            LOG_ERROR(TAG_CAM, "Capture timeout after %lu ms (got %lu/%lu frames)",
                      (unsigned long)CAPTURE_TIMEOUT_MS,
                      (unsigned long)s_frame_count,
                      (unsigned long)TOTAL_FRAMES);
            BSP_CAMERA_Stop(0);
            s_active_buffer = NULL;
            return CAMERA_ERROR_TIMEOUT;
        }
        /* Yield CPU briefly — 1ms poll granularity */
        HAL_Delay(1);
    }

    /* Stop continuous capture — the buffer now has the final frame */
    BSP_CAMERA_Stop(0);
    s_active_buffer = NULL;

    /* Determine frame size */
    uint32_t copy_size = s_frame_size;
    if (copy_size == 0)
    {
        copy_size = buffer_size;
    }

    if (copy_size > buffer_size)
    {
        LOG_WARN(TAG_CAM, "Frame (%lu) exceeds buffer (%lu), clamping",
                 (unsigned long)copy_size, (unsigned long)buffer_size);
        copy_size = buffer_size;
    }

    /* No memcpy needed — DMA wrote directly into caller's buffer */
    *captured_size = copy_size;

    LOG_INFO(TAG_CAM, "Captured in %lums: %lu bytes (%lu frames)",
             (unsigned long)(HAL_GetTick() - start_tick),
             (unsigned long)copy_size,
             (unsigned long)s_frame_count);

#if CAMERA_DIAG_ENABLED
    /* ── Raw Buffer Diagnostic ──
     * Dump first 32 bytes and count zero vs non-zero pixels
     * to verify the DMA actually transferred real image data. */
    LOG_INFO(TAG_CAM, "RAW[0..31]: %02X %02X %02X %02X %02X %02X %02X %02X "
             "%02X %02X %02X %02X %02X %02X %02X %02X "
             "%02X %02X %02X %02X %02X %02X %02X %02X "
             "%02X %02X %02X %02X %02X %02X %02X %02X",
             buffer[0], buffer[1], buffer[2], buffer[3],
             buffer[4], buffer[5], buffer[6], buffer[7],
             buffer[8], buffer[9], buffer[10], buffer[11],
             buffer[12], buffer[13], buffer[14], buffer[15],
             buffer[16], buffer[17], buffer[18], buffer[19],
             buffer[20], buffer[21], buffer[22], buffer[23],
             buffer[24], buffer[25], buffer[26], buffer[27],
             buffer[28], buffer[29], buffer[30], buffer[31]);

    /* Count zero vs non-zero uint16 pixels in first 1000 pixels */
    uint32_t zero_count = 0, nonzero_count = 0;
    uint16_t *px = (uint16_t *)buffer;
    uint32_t check_pixels = (copy_size / 2 < 1000) ? (copy_size / 2) : 1000;
    for (uint32_t i = 0; i < check_pixels; i++) {
        if (px[i] == 0) zero_count++;
        else nonzero_count++;
    }
    LOG_INFO(TAG_CAM, "Pixel check (first %lu): zero=%lu nonzero=%lu px[0]=0x%04X px[500]=0x%04X",
             (unsigned long)check_pixels,
             (unsigned long)zero_count, (unsigned long)nonzero_count,
             (unsigned)px[0], (unsigned)px[500]);
#endif /* CAMERA_DIAG_ENABLED */

    return CAMERA_OK;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Zero-Overhead Warm Capture — Enterprise Fast Path
 *
 *  Captures exactly 1 frame with zero warmup. The sensor is already
 *  AEC-converged from the persistent init, so the first frame is usable.
 *  Expected latency: ~83ms at VTS=0x07D0 (~12fps).
 * ═══════════════════════════════════════════════════════════════════════════ */

CameraStatus_t Camera_WarmCapture(uint8_t *buffer, uint32_t buffer_size,
                                   uint32_t *captured_size)
{
    uint32_t perf_start = HAL_GetTick();

    LOG_INFO(TAG_CAM, "Warm capture (single frame, zero warmup)...");

    if (buffer == NULL || captured_size == NULL)
    {
        LOG_ERROR(TAG_CAM, "Null buffer or size pointer");
        return CAMERA_ERROR_CAPTURE;
    }

    if (buffer_size < CAMERA_FRAME_BUFFER_SIZE)
    {
        LOG_ERROR(TAG_CAM, "Buffer too small (%lu < %lu)",
                  (unsigned long)buffer_size,
                  (unsigned long)CAMERA_FRAME_BUFFER_SIZE);
        return CAMERA_ERROR_CAPTURE;
    }

    /* Reset frame counter — we only need 1 frame */
    s_frame_count = 0;
    s_frame_size  = 0;
    s_active_buffer = buffer;

    /* Start continuous capture — stop after first frame */
    int32_t ret = BSP_CAMERA_Start(0, buffer, CAMERA_MODE_CONTINUOUS);
    if (ret != BSP_ERROR_NONE)
    {
        LOG_ERROR(TAG_CAM, "BSP_CAMERA_Start failed (err=%ld)", (long)ret);
        s_active_buffer = NULL;
        return CAMERA_ERROR_CAPTURE;
    }

    /* Wait for exactly 1 frame-complete interrupt */
    uint32_t start_tick = HAL_GetTick();
    const uint32_t WARM_TIMEOUT_MS = 1000;  /* 1s generous timeout */

    while (s_frame_count < 1)
    {
        if ((HAL_GetTick() - start_tick) > WARM_TIMEOUT_MS)
        {
            LOG_ERROR(TAG_CAM, "Warm capture timeout after %lums",
                      (unsigned long)WARM_TIMEOUT_MS);
            BSP_CAMERA_Stop(0);
            s_active_buffer = NULL;
            return CAMERA_ERROR_TIMEOUT;
        }
        HAL_Delay(1);
    }

    BSP_CAMERA_Stop(0);
    s_active_buffer = NULL;

    uint32_t copy_size = s_frame_size;
    if (copy_size == 0)
        copy_size = buffer_size;
    if (copy_size > buffer_size)
        copy_size = buffer_size;

    *captured_size = copy_size;

    LOG_INFO(TAG_CAM, "[PERF] Warm capture: %lums, %lu bytes",
             (unsigned long)(HAL_GetTick() - perf_start),
             (unsigned long)copy_size);

    return CAMERA_OK;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  BSP Callbacks (called from ISR context)
 * ═══════════════════════════════════════════════════════════════════════════ */

/**
 * @brief  Frame Event callback — called by BSP when DCMI frame is complete.
 *         This is a weak function in the BSP that we override here.
 *
 *         In continuous mode, this fires once per frame. We count frames
 *         to know when warm-up is done.
 */
void BSP_CAMERA_FrameEventCallback(uint32_t Instance)
{
    (void)Instance;
    s_frame_count++;

    /* Raw RGB565 frame — always use full buffer */
    s_frame_size = CAMERA_FRAME_BUFFER_SIZE;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Shutdown
 * ═══════════════════════════════════════════════════════════════════════════ */

void Camera_DeInit(void)
{
    LOG_INFO(TAG_CAM, "De-initializing camera");
    BSP_CAMERA_Stop(0);
    BSP_CAMERA_DeInit(0);
    s_initialized = 0;
}
