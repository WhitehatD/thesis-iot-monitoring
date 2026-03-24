/**
  ******************************************************************************
  * @file    main.c
  * @brief   Autonomous IoT Visual Monitoring — Main Application
  * @author  Alexandru-Ionut Cioc (based on ST MCD template)
  * @date    2026
  *
  * Application flow:
  *   BOOT → Init (HAL, Clock, Cache, UART, RTC, Wi-Fi, Camera, MQTT)
  *   → Subscribe to schedule commands via MQTT
  *   → Poll MQTT until a schedule arrives from the AI planning engine
  *   → For each scheduled task:
  *       1. Set RTC alarm → Enter STOP2 low-power mode
  *       2. Wake on alarm → Capture image with camera
  *       3. Upload image to server via HTTP POST
  *       4. Publish status update via MQTT
  *       5. Repeat until all tasks complete
  *   → Enter deep sleep / wait for next schedule
  ******************************************************************************
  */

/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "firmware_config.h"
#include "debug_log.h"
#include "wifi.h"
#include "app_camera.h"
#include "mqtt_handler.h"
#include "scheduler.h"
#include "ota_update.h"

#include "cJSON.h"
#include <string.h>
#include <stdio.h>

/* ═══════════════════════════════════════════════════════════════════════════
 *  Global Handles (shared with ISR and other modules)
 * ═══════════════════════════════════════════════════════════════════════════ */

RTC_HandleTypeDef hrtc;

/* SEC-07: Independent Watchdog for autonomous recovery */
#if WATCHDOG_ENABLED
static IWDG_HandleTypeDef hiwdg;
#endif

/* ═══════════════════════════════════════════════════════════════════════════
 *  Private Variables
 * ═══════════════════════════════════════════════════════════════════════════ */

/* Image capture buffer — 32-byte aligned for DCMI DMA */
static uint8_t s_image_buffer[CAMERA_FRAME_BUFFER_SIZE] __attribute__((aligned(32)));

/* Active schedule */
static Schedule_t s_schedule;

/* Flag: set when a new schedule is received via MQTT */
static volatile uint8_t s_schedule_received = 0;

/* Flag: set by B3 USER button press (EXTI) for instant capture */
static volatile uint8_t s_button_capture_requested = 0;
static uint32_t s_button_task_id = 10000;  /* Start at high IDs to avoid schedule collision */

/* ── Capture Now (MQTT command) ───────────────────────────── */
static volatile uint8_t  s_capture_now_requested = 0;
static volatile uint32_t s_capture_now_task_id   = 20000;

/* ── Capture Sequence (MQTT command) ──────────────────────── */
#define MAX_SEQUENCE_CAPTURES 16
static volatile uint8_t  s_sequence_requested = 0;
static volatile uint32_t s_sequence_count     = 0;
static uint32_t s_sequence_delays_ms[MAX_SEQUENCE_CAPTURES];  /* ms offset from NOW for each capture */
static uint32_t s_sequence_base_task_id = 30000;

/* ── Sleep mode toggle (MQTT command) ───────────────────── */
static volatile uint8_t s_sleep_enabled = 0;  /* 0 = awake (default), 1 = low power between tasks */

/* ── OTA firmware update (MQTT command) ─────────────────── */
static volatile uint8_t s_ota_requested = 0;

/* Buffer to hold the raw JSON schedule from MQTT callback */
static char s_schedule_json[SCHEDULE_JSON_MAX];

/* ═══════════════════════════════════════════════════════════════════════════
 *  Private Function Prototypes
 * ═══════════════════════════════════════════════════════════════════════════ */

void SystemClock_Config(void);
static void CACHE_Enable(void);
static void RTC_Init(void);
static void LED_SignalError(void);
static void on_command_received(const char *json_str, uint32_t length);
static void _do_button_capture(void);
static void _do_capture_now(void);
static void _do_capture_sequence(void);
static void _do_ota_update(void);

/* SEC-07: Watchdog initialization */
#if WATCHDOG_ENABLED
static void Watchdog_Init(void);
#endif

/* ═══════════════════════════════════════════════════════════════════════════
 *  Stack Watermark — Enterprise RAM Safety
 *
 *  Paints the stack region (top of RAM, grows downward) with canary words.
 *  RAM_CheckStackHighWater() scans from the stack bottom upward to find
 *  the deepest canary-overwrite — that's the peak stack usage.
 *
 *  Memory layout (ARM Cortex-M, stack grows DOWN):
 *    _ebss ──────── end of BSS (heap grows UP from here)
 *    ...heap...
 *    ...free gap...
 *    stack bottom ─ deepest the stack has reached
 *    ...stack...
 *    _estack ────── top of RAM (SP starts here at reset)
 * ═══════════════════════════════════════════════════════════════════════════ */

#if STACK_WATERMARK_ENABLED

/* Linker-defined symbols */
extern uint32_t _estack;   /* Top of stack (highest address, SP at reset) */
extern uint32_t _ebss;     /* End of BSS (heap starts here) */

#define STACK_CANARY_WORD  0xDEADBEEFUL

/* Reserve stack space to paint: from (_estack - STACK_PAINT_SIZE) to _estack.
 * We paint the LOWER portion of the stack region. The stack grows down from
 * _estack, so untouched canaries at the bottom = free stack space. */
#define STACK_PAINT_SIZE   (8 * 1024)  /* Paint 8KB below _estack */

/**
 * @brief  Paint the lower portion of the stack with canary words.
 *         Must be called very early in main(), before deep call chains.
 */
static void RAM_PaintStackCanary(void)
{
    volatile uint32_t *stack_top = (volatile uint32_t *)&_estack;
    volatile uint32_t *paint_start = (volatile uint32_t *)((uint32_t)stack_top - STACK_PAINT_SIZE);

    /* Don't paint into BSS — clamp to _ebss if stack region overlaps */
    volatile uint32_t *bss_end = (volatile uint32_t *)&_ebss;
    if (paint_start < bss_end)
        paint_start = bss_end;

    /* Don't paint over our own current stack frame */
    volatile uint32_t stack_var;
    volatile uint32_t *safe_limit = (volatile uint32_t *)((uint32_t)&stack_var - 256);

    uint32_t painted = 0;
    for (volatile uint32_t *p = paint_start; p < safe_limit && p < stack_top; p++)
    {
        *p = STACK_CANARY_WORD;
        painted++;
    }

    LOG_INFO(TAG_BOOT, "Stack canary: painted %lu words (%lu bytes) below _estack",
             (unsigned long)painted, (unsigned long)(painted * 4));
}

/**
 * @brief  Scan stack region from bottom upward to find peak usage.
 *
 *         ARM stack grows DOWN from _estack. Canaries were placed at the
 *         bottom of the stack region. The first intact canary (scanning up
 *         from paint_start) = boundary of maximum stack depth.
 *
 * @retval Number of bytes used at peak.
 */
static uint32_t RAM_CheckStackHighWater(void)
{
    volatile uint32_t *stack_top = (volatile uint32_t *)&_estack;
    volatile uint32_t *paint_start = (volatile uint32_t *)((uint32_t)stack_top - STACK_PAINT_SIZE);

    volatile uint32_t *bss_end = (volatile uint32_t *)&_ebss;
    if (paint_start < bss_end)
        paint_start = bss_end;

    /* Scan upward from paint_start: find first intact canary */
    volatile uint32_t *p = paint_start;
    while (p < stack_top && *p != STACK_CANARY_WORD)
    {
        p++;
    }

    /* Everything from p to stack_top is free (still has canaries) */
    uint32_t free_bytes = (uint32_t)((uint8_t *)stack_top - (uint8_t *)p);
    uint32_t total_bytes = STACK_PAINT_SIZE;
    uint32_t used_bytes = total_bytes - free_bytes;

    LOG_INFO(TAG_BOOT, "Stack watermark: %lu/%lu bytes used (%lu%% free)",
             (unsigned long)used_bytes,
             (unsigned long)total_bytes,
             (unsigned long)((free_bytes * 100) / total_bytes));

    if (free_bytes < 1024)
    {
        LOG_ERROR(TAG_BOOT, "CRITICAL: Stack nearly exhausted! Only %lu bytes free",
                  (unsigned long)free_bytes);
    }
    else if (free_bytes < 2048)
    {
        LOG_WARN(TAG_BOOT, "WARNING: Stack getting low — %lu bytes free",
                 (unsigned long)free_bytes);
    }

    return used_bytes;
}

#endif /* STACK_WATERMARK_ENABLED */

/* ═══════════════════════════════════════════════════════════════════════════
 *  MQTT Command Callback — Dispatches by "type" field
 *
 *  Expected JSON formats:
 *    {"type":"capture_now"}
 *    {"type":"capture_sequence","delays_ms":[0, 2000, 5000]}
 *    {"type":"schedule","tasks":[...]}   (legacy: no type = schedule)
 * ═══════════════════════════════════════════════════════════════════════════ */

static void on_command_received(const char *json_str, uint32_t length)
{
    if (length >= SCHEDULE_JSON_MAX)
    {
        LOG_ERROR(TAG_MQTT, "Command too large (%lu > %d), dropping",
                  (unsigned long)length, SCHEDULE_JSON_MAX);
        return;
    }

    /* Null-terminate for cJSON */
    char cmd_buf[SCHEDULE_JSON_MAX];
    memcpy(cmd_buf, json_str, length);
    cmd_buf[length] = '\0';

    LOG_INFO(TAG_MQTT, "Command received (%lu bytes)", (unsigned long)length);

    /* Acknowledgement flash */
    BSP_LED_On(LED_GREEN);
    BSP_LED_On(LED_RED);
    HAL_Delay(50);
    BSP_LED_Off(LED_GREEN);
    BSP_LED_Off(LED_RED);

    /* Quick-parse type field with cJSON */
    cJSON *root = cJSON_Parse(cmd_buf);
    if (root == NULL)
    {
        LOG_ERROR(TAG_MQTT, "Command JSON parse error");
        return;
    }

    cJSON *type_obj = cJSON_GetObjectItem(root, "type");
    const char *type_str = (type_obj && cJSON_IsString(type_obj)) ? type_obj->valuestring : NULL;

    /* ── Dispatch by command type ───────────────────── */

    if (type_str != NULL && strcmp(type_str, "capture_now") == 0)
    {
        /* ── Instant capture ── execute in main loop, no scheduler ── */
        s_capture_now_requested = 1;
        s_capture_now_task_id++;
        LOG_INFO(TAG_MQTT, ">> CAPTURE_NOW command (task_id=%lu)",
                 (unsigned long)s_capture_now_task_id);
    }
    else if (type_str != NULL && strcmp(type_str, "capture_sequence") == 0)
    {
        /* ── Timed capture sequence ── array of ms delays from NOW ── */
        cJSON *delays = cJSON_GetObjectItem(root, "delays_ms");
        if (delays == NULL || !cJSON_IsArray(delays))
        {
            LOG_ERROR(TAG_MQTT, "capture_sequence missing 'delays_ms' array");
            cJSON_Delete(root);
            return;
        }

        int count = cJSON_GetArraySize(delays);
        if (count > MAX_SEQUENCE_CAPTURES)
        {
            LOG_WARN(TAG_MQTT, "Sequence has %d items, clamping to %d",
                     count, MAX_SEQUENCE_CAPTURES);
            count = MAX_SEQUENCE_CAPTURES;
        }

        for (int i = 0; i < count; i++)
        {
            cJSON *item = cJSON_GetArrayItem(delays, i);
            s_sequence_delays_ms[i] = (item && cJSON_IsNumber(item))
                                    ? (uint32_t)item->valuedouble : 0;
        }

        s_sequence_count = (uint32_t)count;
        s_sequence_base_task_id += (uint32_t)count;
        s_sequence_requested = 1;

        LOG_INFO(TAG_MQTT, ">> CAPTURE_SEQUENCE command (%d captures)", count);
        for (int i = 0; i < count; i++)
        {
            LOG_DEBUG(TAG_MQTT, "   [%d] delay=%lums", i,
                      (unsigned long)s_sequence_delays_ms[i]);
        }
    }
    else if (type_str != NULL && strcmp(type_str, "sleep_mode") == 0)
    {
        /* ── Sleep mode toggle ── */
        cJSON *enabled_obj = cJSON_GetObjectItem(root, "enabled");
        if (enabled_obj && cJSON_IsBool(enabled_obj))
        {
            s_sleep_enabled = cJSON_IsTrue(enabled_obj) ? 1 : 0;
            LOG_INFO(TAG_MQTT, ">> SLEEP_MODE %s", s_sleep_enabled ? "ENABLED" : "DISABLED");
        }
    }
    else if (type_str != NULL && strcmp(type_str, "delete_schedule") == 0)
    {
        /* ── Delete / clear active schedule ── */
        memset(&s_schedule, 0, sizeof(s_schedule));
        s_schedule_received = 0;
        LOG_INFO(TAG_MQTT, ">> DELETE_SCHEDULE — schedule cleared");
        MQTT_PublishStatus("{\"status\":\"schedule_cleared\"}");
    }
    else if (type_str != NULL && strcmp(type_str, "firmware_update") == 0)
    {
        /* ── OTA firmware update — execute in main loop ── */
        s_ota_requested = 1;
        LOG_INFO(TAG_MQTT, ">> FIRMWARE_UPDATE command received");
        MQTT_PublishStatus("{\"status\":\"ota_update_queued\"}");
    }
    else
    {
        /* ── Schedule (default / legacy) ── parse inline, stay in MQTT loop ── */
        memcpy(s_schedule_json, cmd_buf, length + 1);
        if (Scheduler_ParseJSON(&s_schedule, s_schedule_json) == 0)
        {
            s_schedule_received = 1;
            LOG_INFO(TAG_MQTT, ">> SCHEDULE command — %d tasks loaded", s_schedule.task_count);
            
            char status_msg[128];
            snprintf(status_msg, sizeof(status_msg), 
                     "{\"status\":\"schedule_received\",\"tasks\":%d}", s_schedule.task_count);
            MQTT_PublishStatus(status_msg);
        }
        else
        {
            LOG_ERROR(TAG_MQTT, ">> SCHEDULE command — parse failed");
            MQTT_PublishStatus("{\"status\":\"error\",\"reason\":\"schedule_parse_failed\"}");
        }
    }

    cJSON_Delete(root);
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Main Program
 * ═══════════════════════════════════════════════════════════════════════════ */

int main(void)
{
    /* ── Phase 1: Hardware Initialization ────────────── */

    HAL_Init();
    CACHE_Enable();
    SystemClock_Config();

    /* Debug UART — must be first for logging */
    Debug_Init();
    LOG_INFO(TAG_BOOT, "========================================");
    LOG_INFO(TAG_BOOT, "  IoT Visual Monitoring Firmware v0.1  ");
    LOG_INFO(TAG_BOOT, "  Board: B-U585I-IOT02A               ");
    LOG_INFO(TAG_BOOT, "========================================");

    /* Status LED */
    BSP_LED_Init(LED_GREEN);
    BSP_LED_Init(LED_RED);
    BSP_LED_On(LED_GREEN);
    BSP_LED_On(LED_RED);

    /* RTC for scheduled wake-ups */
    RTC_Init();
    LOG_INFO(TAG_BOOT, "RTC initialized");

    /* ── OTA boot validation — must be early, after RTC init ── */
    OTA_ValidateBoot();

    /* B3 USER button — instant capture trigger */
    BSP_PB_Init(BUTTON_USER, BUTTON_MODE_EXTI);
    LOG_INFO(TAG_BOOT, "B3 USER button initialized (press for instant capture)");

    /* Stack canary painting — must happen early before deep calls */
#if STACK_WATERMARK_ENABLED
    RAM_PaintStackCanary();
#endif

    /* SEC-07: Initialize IWDG — must be after all blocking HAL inits */
#if WATCHDOG_ENABLED
    Watchdog_Init();
#endif

    /* ── Phase 2: Connectivity ──────────────────────── */

    /* Wi-Fi */
    if (WiFi_Init() != WIFI_OK)
    {
        LOG_ERROR(TAG_BOOT, "FATAL: Wi-Fi init failed");
        LED_SignalError();
    }

    if (WiFi_Connect(WIFI_SSID, WIFI_PASSWORD) != WIFI_OK)
    {
        LOG_ERROR(TAG_BOOT, "FATAL: Wi-Fi connect failed");
        LED_SignalError();
    }

    /* ── Time synchronization — set RTC from server clock ── */
    {
        uint8_t srv_h, srv_m, srv_s, srv_y, srv_mo, srv_d, srv_wd;
        if (WiFi_HttpGetTime(&srv_h, &srv_m, &srv_s,
                             &srv_y, &srv_mo, &srv_d, &srv_wd) == WIFI_OK)
        {
            /* Convert BIN → BCD for RTC registers */
            #define BIN2BCD(x) (((x) / 10) << 4 | ((x) % 10))
            uint32_t tr = ((uint32_t)BIN2BCD(srv_h) << 16)
                        | ((uint32_t)BIN2BCD(srv_m) << 8)
                        | ((uint32_t)BIN2BCD(srv_s));

            uint32_t dr = ((uint32_t)BIN2BCD(srv_y) << 16)
                        | ((uint32_t)srv_wd << 13)
                        | ((uint32_t)BIN2BCD(srv_mo) << 8)
                        | ((uint32_t)BIN2BCD(srv_d));

            /* Unlock write protection */
            RTC->WPR = 0xCA;
            RTC->WPR = 0x53;

            /* Enter init mode */
            RTC->ICSR |= RTC_ICSR_INIT;
            uint32_t tick = HAL_GetTick();
            while (!(RTC->ICSR & RTC_ICSR_INITF))
            {
                if ((HAL_GetTick() - tick) > 2000) break;
            }

            /* Write time and date */
            RTC->TR = tr;
            RTC->DR = dr;

            /* Exit init mode */
            RTC->ICSR &= ~RTC_ICSR_INIT;

            /* Re-lock write protection */
            RTC->WPR = 0xFF;

            LOG_INFO(TAG_BOOT, "RTC synced to server: %02u:%02u:%02u  20%02u-%02u-%02u",
                     srv_h, srv_m, srv_s, srv_y, srv_mo, srv_d);

            /* Verify RTC is actually ticking after 1 second */
            HAL_Delay(1000);

            /* Direct read (read TR then DR — must read both per RM) */
            uint32_t tr_read = RTC->TR;
            uint32_t dr_read = RTC->DR;
            (void)dr_read;

            #define BCD2BIN(x) (((x) >> 4) * 10 + ((x) & 0x0F))
            uint8_t rh = BCD2BIN((tr_read >> 16) & 0x3F);
            uint8_t rm = BCD2BIN((tr_read >> 8) & 0x7F);
            uint8_t rs = BCD2BIN(tr_read & 0x7F);

            LOG_INFO(TAG_BOOT, "RTC verify (1s later): %02u:%02u:%02u  ICSR=0x%08lX  BDCR=0x%08lX",
                     rh, rm, rs,
                     (unsigned long)RTC->ICSR,
                     (unsigned long)RCC->BDCR);
        }
        else
        {
            LOG_WARN(TAG_BOOT, "Time sync failed — RTC uses default 00:00:00");
        }
    }

    /* MQTT */
    MQTTConfig_t mqtt_cfg = {
        .broker_host = MQTT_BROKER_HOST,
        .broker_port = MQTT_BROKER_PORT,
        .client_id   = MQTT_CLIENT_ID,
    };

    /* Flush SPI pipeline — drain any pending responses before MQTT */
    MX_WIFI_IO_YIELD(wifi_obj_get(), 2000);

    if (MQTT_Init(&mqtt_cfg) != 0)
    {
        LOG_ERROR(TAG_BOOT, "FATAL: MQTT connect failed");
        LED_SignalError();
    }

    if (MQTT_SubscribeCommands(on_command_received) != 0)
    {
        LOG_ERROR(TAG_BOOT, "FATAL: MQTT subscribe failed");
        LED_SignalError();
    }

    /* ── Phase 3: Publish online status ─────────────── */

    MQTT_PublishStatus("{\"status\":\"online\",\"firmware\":\"" FW_VERSION "\"}");
    LOG_INFO(TAG_BOOT, "Boot complete (v%s) — waiting for commands...", FW_VERSION);

    /* All subsystems initialized OK — mark boot as successful.
     * This resets the OTA boot failure counter, preventing rollback. */
    OTA_MarkBootSuccessful();

    /* ── Hyper-distinct Board Ready Pattern ── */
    /* 3 crisp GREEN flashes indicate the board is fully initialized and online */
    for (int i = 0; i < 3; i++) {
        BSP_LED_On(LED_GREEN);
        HAL_Delay(100);
        BSP_LED_Off(LED_GREEN);
        HAL_Delay(100);
    }
    
    /* Turn OFF RED LED since boot is now fully complete (it was turned ON at init) */
    BSP_LED_Off(LED_RED);

    /* ── Phase 3b: Persistent Camera Init ──────────────
     *
     * Enterprise optimization: initialize the camera ONCE at boot.
     * The sensor stays powered and AEC-converged, enabling sub-second
     * warm captures for the entire uptime of the board. */
    if (Camera_Init(CAMERA_DEFAULT_RESOLUTION) != CAMERA_OK)
    {
        LOG_ERROR(TAG_BOOT, "WARNING: Camera init failed at boot — captures will cold-start");
    }
    else
    {
        LOG_INFO(TAG_BOOT, "Camera warm and ready (persistent mode)");
    }

    /* ── Phase 4: Unified Main Loop ───────────────────
     *
     * Runs forever. Handles all commands inline:
     *  - capture_now, capture_sequence, button captures
     *  - Scheduled tasks: polls RTC and executes when time arrives
     *  - sleep_mode: only enters STOP2 when explicitly enabled
     *
     * The board stays awake and connected to MQTT by default.
     */

    uint32_t poll_start    = HAL_GetTick();
    uint32_t last_ping     = HAL_GetTick();
    uint32_t last_ota_check = HAL_GetTick();

    while (1)
    {
        MQTT_ProcessLoop();

        /* SEC-07: Refresh watchdog every loop iteration */
#if WATCHDOG_ENABLED
        HAL_IWDG_Refresh(&hiwdg);
#endif

        /* Send MQTT keepalive ping and online status every 30 seconds */
        if ((HAL_GetTick() - last_ping) > 30000)
        {
            MQTT_SendPing();
            MQTT_PublishStatus("{\"status\":\"online\",\"firmware\":\"" FW_VERSION "\"}");
            last_ping = HAL_GetTick();
        }

        /* Idle heartbeat: 50ms GREEN blip every 3 seconds to prove we are alive */
        static uint32_t last_idle_blink = 0;
        static uint8_t idle_led_on = 0;
        
        if (!idle_led_on && (HAL_GetTick() - last_idle_blink) >= 3000)
        {
            BSP_LED_On(LED_GREEN);
            idle_led_on = 1;
            last_idle_blink = HAL_GetTick();
        }
        else if (idle_led_on && (HAL_GetTick() - last_idle_blink) >= 50)
        {
            BSP_LED_Off(LED_GREEN);
            idle_led_on = 0;
            /* Keep last_idle_blink anchor for stable 3000ms period */
        }
        HAL_Delay(SCHEDULER_MQTT_POLL_MS);

        /* ── Handle: Capture Now (MQTT command) ── */
        if (s_capture_now_requested)
        {
            s_capture_now_requested = 0;
            _do_capture_now();
            poll_start = HAL_GetTick();
        }

        /* ── Handle: Capture Sequence (MQTT command) ── */
        if (s_sequence_requested)
        {
            s_sequence_requested = 0;
            _do_capture_sequence();
            poll_start = HAL_GetTick();
        }

        /* ── Handle: B3 button press ── */
        if (s_button_capture_requested)
        {
            s_button_capture_requested = 0;
            _do_button_capture();
            poll_start = HAL_GetTick();
        }

        /* ── Handle: OTA firmware update (MQTT command) ── */
        if (s_ota_requested)
        {
            s_ota_requested = 0;
#if WATCHDOG_ENABLED
            HAL_IWDG_Refresh(&hiwdg);  /* OTA is long — refresh before starting */
#endif
            _do_ota_update();
            poll_start = HAL_GetTick();
        }

        /* ── Periodic OTA version check (every 30 min) ── */
        if ((HAL_GetTick() - last_ota_check) > OTA_CHECK_INTERVAL_MS)
        {
            last_ota_check = HAL_GetTick();
            LOG_INFO(TAG_OTA, "Periodic firmware update check...");
            OTA_CheckAndUpdate(s_image_buffer, sizeof(s_image_buffer));
        }

        /* ── Handle: Scheduled Tasks (RTC polling) ── */
        if (s_schedule_received && s_schedule.current_index < s_schedule.task_count)
        {
            const ScheduledTask_t *next = &s_schedule.tasks[s_schedule.current_index];

            /* Read current RTC time */
            RTC_TimeTypeDef now_time;
            RTC_DateTypeDef now_date;
            HAL_RTC_GetTime(&hrtc, &now_time, RTC_FORMAT_BIN);
            HAL_RTC_GetDate(&hrtc, &now_date, RTC_FORMAT_BIN);

            int32_t now_secs  = (int32_t)now_time.Hours * 3600
                              + (int32_t)now_time.Minutes * 60
                              + (int32_t)now_time.Seconds;
            int32_t task_secs = (int32_t)next->hour * 3600
                              + (int32_t)next->minute * 60
                              + (int32_t)next->second;

            if (now_secs >= task_secs)
            {
                /* ── Time reached — execute this task ── */
                LOG_INFO(TAG_SCHED, "Executing task %u: %02u:%02u:%02u '%s'",
                         next->task_id, next->hour, next->minute, next->second,
                         next->objective);

                poll_start = HAL_GetTick();

                char status_msg[128];
                snprintf(status_msg, sizeof(status_msg),
                         "{\"status\":\"executing\",\"task_id\":%u,\"action\":\"CAPTURE_IMAGE\"}",
                         next->task_id);
                MQTT_PublishStatus(status_msg);

                if (next->action == ACTION_CAPTURE_IMAGE)
                {
                    LOG_INFO(TAG_BOOT, "=== Task %u: CAPTURE_IMAGE ===", next->task_id);

                    uint32_t captured_size = 0;
                    CameraStatus_t cam_ret;

                    /* Turn on RED LED to indicate Image Capturing state */
                    BSP_LED_On(LED_RED);

                    /* Use warm capture if camera is already initialized */
                    if (Camera_IsInitialized())
                    {
                        snprintf(status_msg, sizeof(status_msg), "{\"status\":\"capturing\",\"task_id\":%u}", next->task_id);
                        MQTT_PublishStatus(status_msg);

                        cam_ret = Camera_WarmCapture(
                            s_image_buffer, sizeof(s_image_buffer), &captured_size);
                    }
                    else
                    {
                        LOG_WARN(TAG_CAM, "Camera cold — initializing for task %u", next->task_id);
                        snprintf(status_msg, sizeof(status_msg), "{\"status\":\"camera_init\",\"task_id\":%u}", next->task_id);
                        MQTT_PublishStatus(status_msg);

                        if (Camera_Init(CAMERA_DEFAULT_RESOLUTION) != CAMERA_OK)
                        {
                            LOG_ERROR(TAG_CAM, "Camera init failed for task %u", next->task_id);
                            cam_ret = CAMERA_ERROR_INIT;
                        }
                        else
                        {
                            snprintf(status_msg, sizeof(status_msg), "{\"status\":\"capturing\",\"task_id\":%u}", next->task_id);
                            MQTT_PublishStatus(status_msg);

                            cam_ret = Camera_CaptureFrame(
                                s_image_buffer, sizeof(s_image_buffer), &captured_size);
                        }
                    }

                    if (cam_ret == CAMERA_OK && captured_size > 0)
                    {
                        snprintf(status_msg, sizeof(status_msg),
                                 "{\"status\":\"uploading\",\"task_id\":%u}",
                                 next->task_id);
                        MQTT_PublishStatus(status_msg);

                        WiFiStatus_t upload_ret = WiFi_HttpPostImage(
                            SERVER_UPLOAD_URL, next->task_id,
                            s_image_buffer, captured_size);

                        if (upload_ret == WIFI_OK)
                        {
                            LOG_INFO(TAG_HTTP, "Task %u upload OK (%lu bytes)",
                                     next->task_id, (unsigned long)captured_size);
                            snprintf(status_msg, sizeof(status_msg),
                                     "{\"status\":\"uploaded\",\"task_id\":%u,\"bytes\":%lu}",
                                     next->task_id, (unsigned long)captured_size);
                        }
                        else
                        {
                            LOG_ERROR(TAG_HTTP, "Task %u upload failed", next->task_id);
                            snprintf(status_msg, sizeof(status_msg),
                                     "{\"status\":\"error\",\"task_id\":%u,\"reason\":\"upload_failed\"}",
                                     next->task_id);
                        }

                        /* Turn off RED LED when upload completes */
                        BSP_LED_Off(LED_RED);

                        /* Re-establish MQTT if connection was lost */
                        if (MQTT_Init(&mqtt_cfg) == 0)
                        {
                            MQTT_SubscribeCommands(on_command_received);
                            MQTT_PublishStatus(status_msg);
                        }
                    }
                    else
                    {
                        LOG_ERROR(TAG_CAM, "Capture failed for task %u", next->task_id);
                        BSP_LED_Off(LED_RED);
                    }

#if STACK_WATERMARK_ENABLED
                    RAM_CheckStackHighWater();
#endif
                }

                /* Advance to next task */
                s_schedule.current_index++;

                if (s_schedule.current_index >= s_schedule.task_count)
                {
                    LOG_INFO(TAG_SCHED, "All %d tasks completed!", s_schedule.task_count);
                    MQTT_PublishStatus("{\"status\":\"complete\",\"all_tasks_done\":true}");
                }
            }
            else if (s_sleep_enabled)
            {
                /* ── Sleep mode: enter STOP2 until next task time ── */
                LOG_INFO(TAG_PWR, "Sleep mode — STOP2 until %02u:%02u:%02u",
                         next->hour, next->minute, next->second);

                int alarm_result = Scheduler_SetNextAlarm(&s_schedule);
                if (alarm_result == 0)
                {
                    MQTT_Disconnect();
                    WiFi_DeInit();
                    Camera_DeInit();  /* Power down camera for sleep */
                    Scheduler_EnterLowPower();

                    /* Woke up — reconnect everything */
                    WiFi_Init();
                    WiFi_Connect(WIFI_SSID, WIFI_PASSWORD);
                    MQTT_Init(&mqtt_cfg);
                    MQTT_SubscribeCommands(on_command_received);
                    last_ping = HAL_GetTick();

                    /* Re-initialize camera after sleep wake-up */
                    Camera_Init(CAMERA_DEFAULT_RESOLUTION);
                }
            }
            /* else: awake mode — just keep polling next iteration */
        }
    }
}


/* ═══════════════════════════════════════════════════════════════════════════
 *  System Clock Configuration (160 MHz via PLL from MSI)
 * ═══════════════════════════════════════════════════════════════════════════ */

void SystemClock_Config(void)
{
    RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};
    RCC_OscInitTypeDef RCC_OscInitStruct = {0};

    __HAL_RCC_PWR_CLK_ENABLE();
    HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1);
    HAL_PWREx_ConfigSupply(PWR_SMPS_SUPPLY);
    __HAL_RCC_PWR_CLK_DISABLE();

    /* MSI 4MHz → PLL × 80 / 2 = 160 MHz */
    RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_MSI | RCC_OSCILLATORTYPE_LSE;
    RCC_OscInitStruct.MSIState = RCC_MSI_ON;
    RCC_OscInitStruct.MSIClockRange = RCC_MSIRANGE_4;
    RCC_OscInitStruct.MSICalibrationValue = RCC_MSICALIBRATION_DEFAULT;
    RCC_OscInitStruct.LSEState = RCC_LSE_ON;  /* LSE needed for RTC */
    RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
    RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_MSI;
    RCC_OscInitStruct.PLL.PLLMBOOST = RCC_PLLMBOOST_DIV1;
    RCC_OscInitStruct.PLL.PLLM = 1;
    RCC_OscInitStruct.PLL.PLLN = 80;
    RCC_OscInitStruct.PLL.PLLR = 2;
    RCC_OscInitStruct.PLL.PLLP = 2;
    RCC_OscInitStruct.PLL.PLLQ = 2;
    RCC_OscInitStruct.PLL.PLLFRACN = 0;
    if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
    {
        while (1);
    }

    RCC_ClkInitStruct.ClockType = (RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_HCLK |
                                   RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2 |
                                   RCC_CLOCKTYPE_PCLK3);
    RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
    RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
    RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
    RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;
    RCC_ClkInitStruct.APB3CLKDivider = RCC_HCLK_DIV1;
    if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_4) != HAL_OK)
    {
        while (1);
    }
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  RTC MSP Init — empty stub to prevent weak default from interfering.
 *  All RTC clock setup is done directly in RTC_Init via registers.
 * ═══════════════════════════════════════════════════════════════════════════ */

void HAL_RTC_MspInit(RTC_HandleTypeDef *hrtc_unused)
{
    (void)hrtc_unused;
    /* Intentionally empty — RTC_Init handles everything directly */
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  RTC Initialization (LSI clock source)
 * ═══════════════════════════════════════════════════════════════════════════ */

static void RTC_Init(void)
{
    /* ═══ Direct register RTC init — HAL_RTC_Init was failing ═══ */

    /* 1. Enable PWR clock + backup domain access */
    __HAL_RCC_PWR_CLK_ENABLE();
    HAL_PWR_EnableBkUpAccess();

    /* 2. Reset backup domain to clear any stale RTC state */
    __HAL_RCC_BACKUPRESET_FORCE();
    for (volatile int i = 0; i < 100; i++);  /* brief delay */
    __HAL_RCC_BACKUPRESET_RELEASE();
    for (volatile int i = 0; i < 100; i++);

    /* 3. Enable LSI and wait for ready (STM32U5: LSI bits are in BDCR) */
    RCC->BDCR |= RCC_BDCR_LSION;
    uint32_t tick = HAL_GetTick();
    while (!(RCC->BDCR & RCC_BDCR_LSIRDY))
    {
        if ((HAL_GetTick() - tick) > 2000)
        {
            LOG_ERROR(TAG_BOOT, "LSI timeout");
            break;
        }
    }
    LOG_DEBUG(TAG_BOOT, "LSI ready: %s, BDCR=0x%08lX",
              (RCC->BDCR & RCC_BDCR_LSIRDY) ? "YES" : "NO",
              (unsigned long)RCC->BDCR);

    /* 4. Select LSI as RTC clock source and enable RTC.
     * CRITICAL: must preserve LSION bit! RTCSEL field = bits 9:8 only. */
    uint32_t bdcr = RCC->BDCR;
    bdcr &= ~(0x3UL << 8);     /* Clear only RTCSEL bits [9:8] */
    bdcr |= (0x2UL << 8);      /* RTCSEL = 10 = LSI */
    bdcr |= RCC_BDCR_RTCEN;    /* Enable RTC */
    RCC->BDCR = bdcr;

    /* Enable RTC APB bus clock — CRITICAL on STM32U5!
     * Without this, CPU reads from RTC registers return 0. */
    __HAL_RCC_RTCAPB_CLK_ENABLE();

    LOG_DEBUG(TAG_BOOT, "After RTCSEL: BDCR=0x%08lX (LSION=%lu LSIRDY=%lu)",
              (unsigned long)RCC->BDCR,
              (unsigned long)(RCC->BDCR & RCC_BDCR_LSION),
              (unsigned long)(RCC->BDCR & RCC_BDCR_LSIRDY));

    /* 5. Prepare the HAL handle (for HAL_RTC_SetTime/GetTime/Alarm later) */
    hrtc.Instance = RTC;
    hrtc.State = HAL_RTC_STATE_READY;

    /* 6. Disable write protection (magic keys) */
    RTC->WPR = 0xCA;
    RTC->WPR = 0x53;

    /* 7. Enter initialization mode */
    RTC->ICSR |= RTC_ICSR_INIT;
    tick = HAL_GetTick();
    while (!(RTC->ICSR & RTC_ICSR_INITF))
    {
        if ((HAL_GetTick() - tick) > 2000)
        {
            LOG_ERROR(TAG_BOOT, "RTC INITF timeout");
            break;
        }
    }

    LOG_DEBUG(TAG_BOOT, "RTC INITF: %s, BDCR=0x%08lX",
              (RTC->ICSR & RTC_ICSR_INITF) ? "OK" : "FAIL",
              (unsigned long)RCC->BDCR);

    /* 8. Set prescalers for LSI (~32 kHz): PREDIV_A=127, PREDIV_S=249 → ~1Hz */
    RTC->PRER = (127 << 16) | 249;

    /* 9. Set 24h format, time = 00:00:00 */
    RTC->CR &= ~RTC_CR_FMT;  /* 24h */
    RTC->TR = 0x00000000;     /* 00:00:00 in BCD */
    RTC->DR = 0x00012101;     /* Mon, 01-Jan-2026: YT=2,YU=6,MT=0,MU=1,DT=0,DU=1,WDU=1 */

    /* 10. Exit initialization mode */
    RTC->ICSR &= ~RTC_ICSR_INIT;

    /* Re-enable write protection */
    RTC->WPR = 0xFF;

    LOG_INFO(TAG_BOOT, "RTC initialized (direct register, LSI)");

    /* Enable RTC Alarm A interrupt */
    HAL_NVIC_SetPriority(RTC_IRQn, 0, 0);
    HAL_NVIC_EnableIRQ(RTC_IRQn);
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Cache Enable
 * ═══════════════════════════════════════════════════════════════════════════ */

static void CACHE_Enable(void)
{
    HAL_ICACHE_ConfigAssociativityMode(ICACHE_1WAY);
    HAL_ICACHE_Enable();
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Error Signalling
 * ═══════════════════════════════════════════════════════════════════════════ */

/**
 * Rapid red LED blink to signal a fatal error.
 * Does not return — the system must be reset.
 */
static void LED_SignalError(void)
{
    BSP_LED_Off(LED_GREEN);
    while (1)
    {
        BSP_LED_Toggle(LED_RED);
        HAL_Delay(150);
#if WATCHDOG_ENABLED
        HAL_IWDG_Refresh(&hiwdg);  /* Keep alive during error blink — allows debugger attach */
#endif
    }
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  SEC-07: IWDG Initialization
 *
 *  LSI ≈ 32 kHz, Prescaler = /256 → 1 tick ≈ 8ms.
 *  Reload = WATCHDOG_TIMEOUT_S * 125 → timeout in seconds.
 * ═══════════════════════════════════════════════════════════════════════════ */

#if WATCHDOG_ENABLED
static void Watchdog_Init(void)
{
    hiwdg.Instance = IWDG;
    hiwdg.Init.Prescaler = IWDG_PRESCALER_256;
    hiwdg.Init.Reload = (uint32_t)(WATCHDOG_TIMEOUT_S * 125) - 1;  /* ~16s max */
    hiwdg.Init.Window = IWDG_WINDOW_DISABLE;
    hiwdg.Init.EWI = 0;

    if (HAL_IWDG_Init(&hiwdg) != HAL_OK)
    {
        LOG_ERROR(TAG_BOOT, "IWDG init failed — watchdog NOT active");
    }
    else
    {
        LOG_INFO(TAG_BOOT, "IWDG initialized (%ds timeout)", WATCHDOG_TIMEOUT_S);
    }
}
#endif /* WATCHDOG_ENABLED */

/* ═══════════════════════════════════════════════════════════════════════════
 *  B3 USER Button — Instant Capture + Upload
 * ═══════════════════════════════════════════════════════════════════════════ */

/**
 * BSP button callback — called from EXTI ISR when B3 is pressed.
 * We just set a flag; the actual capture happens in the main loop context
 * to avoid doing heavy I/O in ISR context.
 */
void BSP_PB_Callback(Button_TypeDef Button)
{
    if (Button == BUTTON_USER)
    {
        s_button_capture_requested = 1;
    }
}

/**
 * Perform a single camera capture + HTTP upload cycle.
 * Called from the main loop when B3 button is pressed.
 */
static void _do_button_capture(void)
{
    s_button_task_id++;
    uint32_t perf_start = HAL_GetTick();
    LOG_INFO(TAG_BOOT, "=== BUTTON CAPTURE (task_id=%lu) ===",
             (unsigned long)s_button_task_id);

    char status_msg[256];
    snprintf(status_msg, sizeof(status_msg), "{\"status\":\"job_received\",\"task_id\":%lu}", (unsigned long)s_button_task_id);
    MQTT_PublishStatus(status_msg);

    uint32_t captured_size = 0;
    CameraStatus_t cam_ret = CAMERA_ERROR_CAPTURE;

    /* Turn on RED LED during image capture */
    BSP_LED_On(LED_RED);

    /* ── Attempt 1: Warm capture (with internal retries) ── */
    if (Camera_IsInitialized())
    {
        snprintf(status_msg, sizeof(status_msg), "{\"status\":\"capturing\",\"task_id\":%lu}", (unsigned long)s_button_task_id);
        MQTT_PublishStatus(status_msg);

        cam_ret = Camera_WarmCapture(
            s_image_buffer, CAMERA_FRAME_BUFFER_SIZE, &captured_size);
    }

    /* ── Attempt 2: Cold-reinit fallback ── */
    if (cam_ret != CAMERA_OK || captured_size == 0)
    {
        LOG_WARN(TAG_CAM, "Warm capture failed (ret=%d) — cold-reinit fallback", cam_ret);
        snprintf(status_msg, sizeof(status_msg),
                 "{\"status\":\"camera_reinit\",\"task_id\":%lu}", (unsigned long)s_button_task_id);
        MQTT_PublishStatus(status_msg);

        Camera_DeInit();
        HAL_Delay(100);

        if (Camera_Init(CAMERA_DEFAULT_RESOLUTION) == CAMERA_OK)
        {
            snprintf(status_msg, sizeof(status_msg),
                     "{\"status\":\"capturing\",\"task_id\":%lu,\"fallback\":\"cold\"}", (unsigned long)s_button_task_id);
            MQTT_PublishStatus(status_msg);

            captured_size = 0;
            cam_ret = Camera_CaptureFrame(
                s_image_buffer, CAMERA_FRAME_BUFFER_SIZE, &captured_size);
        }
        else
        {
            LOG_ERROR(TAG_CAM, "Cold reinit failed — capture impossible");
            cam_ret = CAMERA_ERROR_INIT;
        }
    }

    /* ── Final failure — never silent ── */
    if (cam_ret != CAMERA_OK || captured_size == 0)
    {
        LOG_ERROR(TAG_CAM, "Capture failed after all attempts (ret=%d, size=%lu)",
                  cam_ret, (unsigned long)captured_size);
        snprintf(status_msg, sizeof(status_msg),
                 "{\"status\":\"error\",\"task_id\":%lu,\"reason\":\"capture_failed\"}",
                 (unsigned long)s_button_task_id);
        MQTT_PublishStatus(status_msg);
        BSP_LED_Off(LED_GREEN);
        BSP_LED_Off(LED_RED);
        return;
    }

    LOG_INFO(TAG_BOOT, "Captured %lu bytes — uploading...",
             (unsigned long)captured_size);

    /* Notify UI that upload is starting */
    snprintf(status_msg, sizeof(status_msg), "{\"status\":\"uploading\",\"task_id\":%lu}", (unsigned long)s_button_task_id);
    MQTT_PublishStatus(status_msg);

    /* Upload via HTTP POST */
    WiFiStatus_t wifi_ret = WiFi_HttpPostImage(
        SERVER_UPLOAD_URL, (uint16_t)s_button_task_id,
        s_image_buffer, captured_size);

    uint32_t total_ms = HAL_GetTick() - perf_start;

    if (wifi_ret == WIFI_OK)
    {
        snprintf(status_msg, sizeof(status_msg),
                 "{\"status\":\"captured\",\"task_id\":%lu,\"size\":%lu,\"trigger\":\"button\",\"latency_ms\":%lu}",
                 (unsigned long)s_button_task_id,
                 (unsigned long)captured_size,
                 (unsigned long)total_ms);
        LOG_INFO(TAG_BOOT, "[PERF] Button capture complete: %lums total",
                 (unsigned long)total_ms);
    }
    else
    {
        snprintf(status_msg, sizeof(status_msg),
                 "{\"status\":\"error\",\"task_id\":%lu,\"reason\":\"upload_failed\",\"trigger\":\"button\"}",
                 (unsigned long)s_button_task_id);
        LOG_ERROR(TAG_BOOT, "Upload FAILED");
    }

    MQTT_PublishStatus(status_msg);

    /* Turn off RED LED after capture cycle completes */
    BSP_LED_Off(LED_RED);

#if STACK_WATERMARK_ENABLED
    RAM_CheckStackHighWater();
#endif
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  MQTT "capture_now" — Immediate Single Capture
 * ═══════════════════════════════════════════════════════════════════════════ */

static void _do_capture_now(void)
{
    uint32_t task_id = s_capture_now_task_id;
    uint32_t perf_start = HAL_GetTick();
    LOG_INFO(TAG_BOOT, "=== CAPTURE NOW (task_id=%lu) ===",
             (unsigned long)task_id);

    char status_msg[256];
    snprintf(status_msg, sizeof(status_msg), "{\"status\":\"job_received\",\"task_id\":%lu}", (unsigned long)task_id);
    MQTT_PublishStatus(status_msg);

    uint32_t captured_size = 0;
    CameraStatus_t cam_ret = CAMERA_ERROR_CAPTURE;

    /* Turn on RED LED during image capture */
    BSP_LED_On(LED_RED);

    /* ── Attempt 1: Warm capture (with internal retries) ── */
    if (Camera_IsInitialized())
    {
        snprintf(status_msg, sizeof(status_msg), "{\"status\":\"capturing\",\"task_id\":%lu}", (unsigned long)task_id);
        MQTT_PublishStatus(status_msg);

        cam_ret = Camera_WarmCapture(
            s_image_buffer, CAMERA_FRAME_BUFFER_SIZE, &captured_size);
    }

    /* ── Attempt 2: Cold-reinit fallback ──
     * If warm capture failed (or camera was not initialized),
     * fully deinit + reinit the camera and try a cold capture. */
    if (cam_ret != CAMERA_OK || captured_size == 0)
    {
        LOG_WARN(TAG_CAM, "Warm capture failed (ret=%d) — cold-reinit fallback", cam_ret);
        snprintf(status_msg, sizeof(status_msg),
                 "{\"status\":\"camera_reinit\",\"task_id\":%lu}", (unsigned long)task_id);
        MQTT_PublishStatus(status_msg);

        /* Full power-cycle of the camera subsystem */
        Camera_DeInit();
        HAL_Delay(200);  /* Let sensor PLL re-lock after power cycle */

        if (Camera_Init(CAMERA_DEFAULT_RESOLUTION) == CAMERA_OK)
        {
            snprintf(status_msg, sizeof(status_msg),
                     "{\"status\":\"capturing\",\"task_id\":%lu,\"fallback\":\"cold\"}", (unsigned long)task_id);
            MQTT_PublishStatus(status_msg);

            captured_size = 0;
            cam_ret = Camera_CaptureFrame(
                s_image_buffer, CAMERA_FRAME_BUFFER_SIZE, &captured_size);
        }
        else
        {
            LOG_ERROR(TAG_CAM, "Cold reinit failed — capture impossible");
            cam_ret = CAMERA_ERROR_INIT;
        }
    }

    /* ── Final failure — never silent ── */
    if (cam_ret != CAMERA_OK || captured_size == 0)
    {
        LOG_ERROR(TAG_CAM, "Capture failed after all attempts (ret=%d, size=%lu)",
                  cam_ret, (unsigned long)captured_size);
        snprintf(status_msg, sizeof(status_msg),
                 "{\"status\":\"error\",\"task_id\":%lu,\"reason\":\"capture_failed\"}",
                 (unsigned long)task_id);
        MQTT_PublishStatus(status_msg);
        BSP_LED_Off(LED_GREEN);
        BSP_LED_Off(LED_RED);
        return;
    }

    LOG_INFO(TAG_BOOT, "Captured %lu bytes — uploading...",
             (unsigned long)captured_size);

    /* Notify UI that upload is starting */
    snprintf(status_msg, sizeof(status_msg), "{\"status\":\"uploading\",\"task_id\":%lu}", (unsigned long)task_id);
    MQTT_PublishStatus(status_msg);

    /* Upload via HTTP POST */
    WiFiStatus_t wifi_ret = WiFi_HttpPostImage(
        SERVER_UPLOAD_URL, (uint16_t)task_id,
        s_image_buffer, captured_size);

    uint32_t total_ms = HAL_GetTick() - perf_start;

    if (wifi_ret == WIFI_OK)
    {
        snprintf(status_msg, sizeof(status_msg),
                 "{\"status\":\"captured\",\"task_id\":%lu,\"size\":%lu,\"trigger\":\"mqtt_capture_now\",\"latency_ms\":%lu}",
                 (unsigned long)task_id,
                 (unsigned long)captured_size,
                 (unsigned long)total_ms);
        LOG_INFO(TAG_BOOT, "[PERF] Capture now complete: %lums total",
                 (unsigned long)total_ms);
    }
    else
    {
        snprintf(status_msg, sizeof(status_msg),
                 "{\"status\":\"error\",\"task_id\":%lu,\"reason\":\"upload_failed\",\"trigger\":\"mqtt_capture_now\"}",
                 (unsigned long)task_id);
        LOG_ERROR(TAG_BOOT, "Upload FAILED");
    }

    MQTT_PublishStatus(status_msg);

    /* Turn off RED LED after capture cycle completes */
    BSP_LED_Off(LED_RED);

#if STACK_WATERMARK_ENABLED
    RAM_CheckStackHighWater();
#endif
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  MQTT "capture_sequence" — Multiple Timed Captures
 *
 *  Executes captures at precise ms offsets from the moment the command
 *  is processed. Camera stays initialized for the entire sequence to
 *  avoid repeated init/deinit overhead.
 *
 *  JSON format: {"type":"capture_sequence","delays_ms":[0, 2000, 5000]}
 *  → Captures at now+0ms, now+2000ms, now+5000ms
 * ═══════════════════════════════════════════════════════════════════════════ */

static void _do_capture_sequence(void)
{
    uint32_t count = s_sequence_count;
    uint32_t base_id = s_sequence_base_task_id;

    LOG_INFO(TAG_BOOT, "=== CAPTURE SEQUENCE (%lu captures, base_id=%lu) ===",
             (unsigned long)count, (unsigned long)base_id);

    if (count == 0)
    {
        LOG_WARN(TAG_BOOT, "Empty capture sequence — nothing to do");
        return;
    }

    /* Ensure camera is initialized (should already be warm from boot) */
    if (!Camera_IsInitialized())
    {
        LOG_WARN(TAG_CAM, "Camera cold — initializing for sequence");
        if (Camera_Init(CAMERA_DEFAULT_RESOLUTION) != CAMERA_OK)
        {
            LOG_ERROR(TAG_CAM, "Camera init failed for sequence");
            return;
        }
    }

    /* Record the sequence start time for precise ms-offset timing */
    uint32_t sequence_start = HAL_GetTick();

    for (uint32_t i = 0; i < count; i++)
    {
        uint32_t task_id = base_id + i;
        uint32_t target_ms = s_sequence_delays_ms[i];

        /* Wait until the target offset from sequence start */
        uint32_t now = HAL_GetTick();
        uint32_t elapsed = now - sequence_start;
        if (elapsed < target_ms)
        {
            uint32_t wait = target_ms - elapsed;
            LOG_DEBUG(TAG_BOOT, "Seq[%lu]: waiting %lums for offset %lums...",
                      (unsigned long)i, (unsigned long)wait, (unsigned long)target_ms);
            HAL_Delay(wait);
        }

        /* Use warm capture — sensor is already converged */
        BSP_LED_On(LED_RED);
        
        char status_msg[256];
        snprintf(status_msg, sizeof(status_msg), "{\"status\":\"capturing\",\"task_id\":%lu}", (unsigned long)task_id);
        MQTT_PublishStatus(status_msg);

        uint32_t captured_size = 0;
        CameraStatus_t cam_ret = Camera_WarmCapture(
            s_image_buffer, CAMERA_FRAME_BUFFER_SIZE, &captured_size);
        uint32_t capture_tick = HAL_GetTick() - sequence_start;

        if (cam_ret != CAMERA_OK || captured_size == 0)
        {
            LOG_ERROR(TAG_CAM, "Seq[%lu]: capture failed (ret=%d)",
                      (unsigned long)i, cam_ret);
            BSP_LED_Off(LED_RED);
            continue;  /* Skip to next capture in sequence */
        }

        LOG_INFO(TAG_BOOT, "Seq[%lu]: captured %lu bytes at %lums (target=%lums)",
                 (unsigned long)i,
                 (unsigned long)captured_size,
                 (unsigned long)capture_tick,
                 (unsigned long)target_ms);

        /* Notify UI that upload is starting */
        snprintf(status_msg, sizeof(status_msg), "{\"status\":\"uploading\",\"task_id\":%lu}", (unsigned long)task_id);
        MQTT_PublishStatus(status_msg);

        /* Upload immediately */
        WiFiStatus_t wifi_ret = WiFi_HttpPostImage(
            SERVER_UPLOAD_URL, (uint16_t)task_id,
            s_image_buffer, captured_size);

        snprintf(status_msg, sizeof(status_msg),
                 "{\"status\":\"captured\",\"task_id\":%lu,\"size\":%lu,"
                 "\"trigger\":\"sequence\",\"seq_index\":%lu,\"seq_total\":%lu,"
                 "\"actual_offset_ms\":%lu,\"target_offset_ms\":%lu}",
                 (unsigned long)task_id,
                 (unsigned long)captured_size,
                 (unsigned long)i,
                 (unsigned long)count,
                 (unsigned long)capture_tick,
                 (unsigned long)target_ms);

        MQTT_PublishStatus(status_msg);

        if (wifi_ret != WIFI_OK)
        {
            LOG_WARN(TAG_BOOT, "Seq[%lu]: upload failed — continuing sequence", (unsigned long)i);
        }

        /* Turn off RED LED after upload completes */
        BSP_LED_Off(LED_RED);
    }

    /* Do NOT deinit camera — keep warm for next capture */

    LOG_INFO(TAG_BOOT, "[PERF] Sequence complete — %lu captures in %lums",
             (unsigned long)count,
             (unsigned long)(HAL_GetTick() - sequence_start));

#if STACK_WATERMARK_ENABLED
    RAM_CheckStackHighWater();
#endif
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  MQTT "firmware_update" — OTA Update Handler
 * ═══════════════════════════════════════════════════════════════════════════ */

static void _do_ota_update(void)
{
    LOG_INFO(TAG_OTA, "=== FIRMWARE UPDATE REQUESTED ===");
    MQTT_PublishStatus("{\"status\":\"ota_checking\"}");

    OTAVersionInfo_t info;
    OTAStatus_t status = OTA_CheckForUpdate(&info);

    if (status == OTA_NO_UPDATE)
    {
        LOG_INFO(TAG_OTA, "Already up-to-date (v%s)", FW_VERSION);
        MQTT_PublishStatus("{\"status\":\"ota_up_to_date\",\"firmware\":\"" FW_VERSION "\"}");
        return;
    }

    if (status != OTA_OK)
    {
        LOG_ERROR(TAG_OTA, "Version check failed (err=%d)", status);
        char msg[128];
        snprintf(msg, sizeof(msg),
                 "{\"status\":\"ota_error\",\"reason\":\"version_check_failed\",\"code\":%d}",
                 status);
        MQTT_PublishStatus(msg);
        return;
    }

    /* Update available — download and flash */
    char msg[256];
    snprintf(msg, sizeof(msg),
             "{\"status\":\"ota_downloading\",\"new_version\":\"%s\",\"size\":%lu}",
             info.version, (unsigned long)info.size);
    MQTT_PublishStatus(msg);

    /* ── Hyper-distinct Update Received Pattern ── */
    /* 5 rapid RED+GREEN strobe flashes before freezing for Flash Erase (Flushing) */
    for (int i = 0; i < 5; i++) {
        BSP_LED_On(LED_RED);
        BSP_LED_On(LED_GREEN);
        HAL_Delay(80);
        BSP_LED_Off(LED_RED);
        BSP_LED_Off(LED_GREEN);
        HAL_Delay(80);
    }

    status = OTA_DownloadAndFlash(&info, s_image_buffer, sizeof(s_image_buffer));
    if (status != OTA_OK)
    {
        LOG_ERROR(TAG_OTA, "Download/flash failed (err=%d)", status);
        snprintf(msg, sizeof(msg),
                 "{\"status\":\"ota_error\",\"reason\":\"flash_failed\",\"code\":%d}",
                 status);
        MQTT_PublishStatus(msg);
        return;
    }

    /* Success — swap banks and reset */
    MQTT_PublishStatus("{\"status\":\"ota_rebooting\"}");
    HAL_Delay(100);  /* Let MQTT message send before reset */

    OTA_SwapBankAndReset();

    /* If we get here, swap failed */
    MQTT_PublishStatus("{\"status\":\"ota_error\",\"reason\":\"bank_swap_failed\"}");
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  RTC Alarm Callback (called from ISR via HAL)
 * ═══════════════════════════════════════════════════════════════════════════ */

void HAL_RTC_AlarmAEventCallback(RTC_HandleTypeDef *hrtc_ptr)
{
    (void)hrtc_ptr;
    /* Wake-up is handled by hardware — execution resumes after WFI in
     * Scheduler_EnterLowPower(). This callback is for any additional
     * housekeeping. */
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Assert Handler
 * ═══════════════════════════════════════════════════════════════════════════ */

#ifdef USE_FULL_ASSERT
void assert_failed(uint8_t *file, uint32_t line)
{
    LOG_ERROR(TAG_BOOT, "ASSERT at %s:%lu", file, (unsigned long)line);
    while (1) {}
}
#endif
