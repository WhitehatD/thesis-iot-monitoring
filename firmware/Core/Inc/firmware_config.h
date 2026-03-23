/**
 * @file    firmware_config.h
 * @brief   Central compile-time configuration for the IoT monitoring firmware
 * @author  Alexandru-Ionut Cioc
 * @date    2026
 *
 * All tuneable parameters in one place. Edit this file to match your
 * deployment environment (Wi-Fi network, server IP, MQTT broker, etc.).
 *
 */

#ifndef __FIRMWARE_CONFIG_H
#define __FIRMWARE_CONFIG_H

/* ═══════════════════════════════════════════════════════════════════════════
 *  Wi-Fi Configuration
 * ═══════════════════════════════════════════════════════════════════════════ */
#define WIFI_SSID                   "A I 2.4"
#define WIFI_PASSWORD               "alex1234"
#define WIFI_CONNECT_RETRIES        3
#define WIFI_CONNECT_TIMEOUT_MS     10000

/* ═══════════════════════════════════════════════════════════════════════════
 *  Server Configuration (FastAPI backend)
 * ═══════════════════════════════════════════════════════════════════════════ */
#define SERVER_HOST                 "89.167.11.147"
#define SERVER_PORT                 8000
#define SERVER_UPLOAD_PATH          "/api/upload"
#define SERVER_UPLOAD_URL           "http://" SERVER_HOST ":" "8000" SERVER_UPLOAD_PATH
#define SERVER_TIME_PATH            "/api/time"
#define HTTP_RESPONSE_TIMEOUT_MS   15000

/* ═══════════════════════════════════════════════════════════════════════════
 *  MQTT Broker Configuration
 * ═══════════════════════════════════════════════════════════════════════════ */
#define MQTT_BROKER_HOST            SERVER_HOST
#define MQTT_BROKER_PORT            1883
#define MQTT_CLIENT_ID              "stm32-iot-cam-01"
#define MQTT_KEEPALIVE_SECONDS      60
#define MQTT_CONNECT_TIMEOUT_MS     10000
#define MQTT_RECV_TIMEOUT_MS        1000

/* ═══════════════════════════════════════════════════════════════════════════
 *  SRAM Budget & Safety Limits
 *
 *  Enterprise practice: hard compile-time ceiling prevents any configuration
 *  change from silently exceeding physical RAM.
 * ═══════════════════════════════════════════════════════════════════════════ */
#define SRAM_TOTAL_BYTES            (768 * 1024)      /* 786,432 bytes — STM32U585AI */
#define RAM_SAFETY_MARGIN_BYTES     (64  * 1024)      /* 65,536 — reserved for stack, heap, BSS, WiFi driver */
#define CAMERA_FRAME_BUFFER_MAX     (SRAM_TOTAL_BYTES - RAM_SAFETY_MARGIN_BYTES)

/* ═══════════════════════════════════════════════════════════════════════════
 *  Camera Configuration
 * ═══════════════════════════════════════════════════════════════════════════ */
#define CAMERA_DEFAULT_RESOLUTION   CAMERA_RES_VGA    /* 640×480 */
#define CAMERA_CAPTURE_TIMEOUT_MS   5000

/*
 * Frame buffer size:
 *   VGA (640×480) RGB565  = 614,400 bytes
 *   QVGA (320×240) RGB565 = 153,600 bytes
 *   VGA JPEG               ≈ 30–80 KB (compressed)
 *
 * Currently using CAMERA_PF_RGB565 at VGA resolution.
 * STM32U585AI has 768 KB SRAM — this buffer fits comfortably.
 */
#define CAMERA_FRAME_BUFFER_SIZE    (640 * 480 * 2)  /* 614,400 bytes — VGA RGB565 */

/* ── Fast-Capture Tuning ──────────────────────────────── */
#define CAMERA_WARMUP_FRAMES        3                 /* Frames to discard for AEC convergence */
#define CAMERA_AEC_SETTLE_TIMEOUT_MS 1500             /* Max wait for AEC register convergence */
#define CAMERA_VTS_DEFAULT          0x07D0            /* VTS=2000 lines → ~12fps (83ms/frame) */
#define CAMERA_INTER_FRAME_DELAY_MS 10                /* Brief ISP settle between snapshots */

/* ── Diagnostics ──────────────────────────────────────── */
#define CAMERA_DIAG_ENABLED         0                 /* 1 = verbose hex dump + pixel scan */
#define STACK_WATERMARK_ENABLED     1                 /* 1 = fill stack with canary + periodic check */

/* ═══════════════════════════════════════════════════════════════════════════
 *  Scheduler Configuration
 * ═══════════════════════════════════════════════════════════════════════════ */
#define SCHEDULER_MAX_TASKS         32     /* Must match MAX_SCHEDULED_TASKS */
#define SCHEDULER_MQTT_POLL_MS      500    /* MQTT poll interval while waiting for schedule */
#define SCHEDULER_MQTT_WAIT_TOTAL_S 300    /* Max seconds to wait for initial schedule (5 min) */
#define SCHEDULE_JSON_MAX           2048   /* Max schedule JSON size (bytes) — shared with main.c */

/* ═══════════════════════════════════════════════════════════════════════════
 *  Debug UART Configuration (ST-Link VCP on USART1)
 * ═══════════════════════════════════════════════════════════════════════════ */
#define DEBUG_UART_INSTANCE         USART1
#define DEBUG_UART_BAUDRATE         115200
#define DEBUG_LOG_ENABLED           1      /* Set to 0 to disable all logging */

/* ═══════════════════════════════════════════════════════════════════════════
 *  Low Power Configuration
 * ═══════════════════════════════════════════════════════════════════════════ */
#define LOW_POWER_MODE_ENABLED      1      /* 1 = STOP2 between tasks, 0 = active wait */
#define DEEP_SLEEP_ON_COMPLETE      1      /* 1 = Standby after all tasks done */

/* ═══════════════════════════════════════════════════════════════════════════
 *  Upload Optimization
 * ═══════════════════════════════════════════════════════════════════════════ */
#define HTTP_UPLOAD_CHUNK_SIZE      8192   /* 8KB chunks with SPI yield between sends */
#define HTTP_UPLOAD_MAX_RETRIES     2      /* Retry full POST on socket connect failure */
#define HTTP_UPLOAD_RETRY_DELAY_MS  500    /* Delay between retries */

/* ═══════════════════════════════════════════════════════════════════════════
 *  OTA (Over-The-Air) Firmware Update
 *
 *  Enterprise OTA using STM32U585 dual-bank flash.
 *  Board polls the server for new versions and auto-flashes if available.
 * ═══════════════════════════════════════════════════════════════════════════ */
#define FW_VERSION                  "0.2"          /* Current firmware version string */
#define OTA_CHECK_INTERVAL_MS       (30 * 60 * 1000)  /* Check every 30 minutes */
#define OTA_DOWNLOAD_CHUNK_SIZE     8192           /* 8KB download chunks */
#define OTA_MAX_FW_SIZE             (896 * 1024)   /* 896KB max — leave room for vector table */
#define OTA_VERSION_PATH            "/api/firmware/version"
#define OTA_DOWNLOAD_PATH           "/api/firmware/download"

#endif /* __FIRMWARE_CONFIG_H */
