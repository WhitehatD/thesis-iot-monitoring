/**
 * @file    app_camera.h
 * @brief   OV5640 Camera Capture Abstraction
 * @author  Alexandru-Ionut Cioc
 * @date    2026
 *
 * Wraps BSP_CAMERA functions for the MB1379 camera module (OV5640 sensor)
 * connected via DCMI interface on the B-U585I-IOT02A Discovery Kit.
 */

#ifndef __APP_CAMERA_H
#define __APP_CAMERA_H

#include <stdint.h>

/* Image resolution presets */
typedef enum {
    CAMERA_RES_QVGA = 0,   /* 320x240  — fast, low bandwidth */
    CAMERA_RES_VGA,         /* 640x480  — default for thesis */
    CAMERA_RES_SVGA,        /* 800x600  */
    CAMERA_RES_XGA,         /* 1024x768 */
} CameraResolution_t;

/* Camera status */
typedef enum {
    CAMERA_OK = 0,
    CAMERA_ERROR_INIT,
    CAMERA_ERROR_CAPTURE,
    CAMERA_ERROR_TIMEOUT,
} CameraStatus_t;

/**
 * @brief  Initialize the OV5640 camera module.
 * @param  resolution: Desired capture resolution.
 * @retval CAMERA_OK on success.
 */
CameraStatus_t Camera_Init(CameraResolution_t resolution);

/**
 * @brief  Check if the camera is already initialized (warm).
 * @retval 1 if initialized, 0 if not.
 */
uint8_t Camera_IsInitialized(void);

/**
 * @brief  Capture a single frame into the provided buffer.
 *         Includes warmup frames for cold-start AEC convergence.
 * @param  buffer: Pointer to destination buffer (must be large enough).
 * @param  buffer_size: Size of the buffer in bytes.
 * @param  captured_size: Output — actual number of bytes captured.
 * @retval CAMERA_OK on success.
 */
CameraStatus_t Camera_CaptureFrame(uint8_t *buffer, uint32_t buffer_size,
                                    uint32_t *captured_size);

/**
 * @brief  Zero-overhead warm capture — single frame, no init, no warmup.
 *         Use when camera is already initialized and AEC has converged.
 *         This is the enterprise fast-path for sub-second captures.
 * @param  buffer: Pointer to destination buffer.
 * @param  buffer_size: Size of the buffer in bytes.
 * @param  captured_size: Output — actual number of bytes captured.
 * @retval CAMERA_OK on success.
 */
CameraStatus_t Camera_WarmCapture(uint8_t *buffer, uint32_t buffer_size,
                                   uint32_t *captured_size);

/**
 * @brief  Deinitialize the camera to save power before entering sleep.
 * @retval CAMERA_OK on success.
 */
CameraStatus_t Camera_DeInit(void);

#endif /* __APP_CAMERA_H */
