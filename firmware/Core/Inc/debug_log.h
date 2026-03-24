/**
 * @file    debug_log.h
 * @brief   UART Debug Logging with Module Tags and Timestamps
 * @author  Alexandru-Ionut Cioc
 * @date    2026
 *
 * Provides LOG_INFO / LOG_ERROR / LOG_WARN / LOG_DEBUG macros that output
 * timestamped, tagged messages over USART1 (ST-Link VCP).
 *
 * Output format:  [  1234ms] [TAG ] Message text\r\n
 *
 * Can be disabled entirely by setting DEBUG_LOG_ENABLED = 0 in firmware_config.h,
 * which compiles all logging calls to nothing (zero overhead in release builds).
 */

#ifndef __DEBUG_LOG_H
#define __DEBUG_LOG_H

#include "firmware_config.h"

#if DEBUG_LOG_ENABLED

#include <stdio.h>

/**
 * @brief  Initialize USART1 for debug logging output.
 *         Must be called after HAL_Init() and SystemClock_Config().
 */
void Debug_Init(void);

/**
 * @brief  Core print function (use macros below instead).
 * @param  level: "INFO", "WARN", "ERR ", "DBG "
 * @param  tag: Module identifier, e.g. "WIFI", "CAM ", "MQTT"
 * @param  fmt: printf-style format string
 */
void Debug_Print(const char *level, const char *tag, const char *fmt, ...);

#define LOG_LEVEL_ERROR 0
#define LOG_LEVEL_WARN  1
#define LOG_LEVEL_INFO  2
#define LOG_LEVEL_DEBUG 3

#ifndef SYSTEM_LOG_LEVEL
#define SYSTEM_LOG_LEVEL LOG_LEVEL_DEBUG
#endif

/* ── Convenience Macros ────────────────────────────────── */

#if SYSTEM_LOG_LEVEL >= LOG_LEVEL_INFO
#define LOG_INFO(tag, fmt, ...)   Debug_Print("INFO", tag, fmt, ##__VA_ARGS__)
#else
#define LOG_INFO(tag, fmt, ...)   ((void)0)
#endif

#if SYSTEM_LOG_LEVEL >= LOG_LEVEL_WARN
#define LOG_WARN(tag, fmt, ...)   Debug_Print("WARN", tag, fmt, ##__VA_ARGS__)
#else
#define LOG_WARN(tag, fmt, ...)   ((void)0)
#endif

#if SYSTEM_LOG_LEVEL >= LOG_LEVEL_ERROR
#define LOG_ERROR(tag, fmt, ...)  Debug_Print("ERR ", tag, fmt, ##__VA_ARGS__)
#else
#define LOG_ERROR(tag, fmt, ...)  ((void)0)
#endif

#if SYSTEM_LOG_LEVEL >= LOG_LEVEL_DEBUG
#define LOG_DEBUG(tag, fmt, ...)  Debug_Print("DBG ", tag, fmt, ##__VA_ARGS__)
#else
#define LOG_DEBUG(tag, fmt, ...)  ((void)0)
#endif

/* Module tag constants — keep to 4 chars for aligned output */
#define TAG_BOOT  "BOOT"
#define TAG_WIFI  "WIFI"
#define TAG_MQTT  "MQTT"
#define TAG_CAM   "CAM "
#define TAG_SCHED "SCHD"
#define TAG_HTTP  "HTTP"
#define TAG_PWR   "PWR "
#define TAG_OTA   "OTA "

#else  /* DEBUG_LOG_ENABLED == 0 */

#define Debug_Init()                          ((void)0)
#define LOG_INFO(tag, fmt, ...)               ((void)0)
#define LOG_WARN(tag, fmt, ...)               ((void)0)
#define LOG_ERROR(tag, fmt, ...)              ((void)0)
#define LOG_DEBUG(tag, fmt, ...)              ((void)0)

#endif /* DEBUG_LOG_ENABLED */

#endif /* __DEBUG_LOG_H */
