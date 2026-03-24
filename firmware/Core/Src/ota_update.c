/**
 * @file    ota_update.c
 * @brief   Over-The-Air Firmware Update — Dual-Bank Flash OTA
 * @author  Alexandru-Ionut Cioc
 * @date    2026
 *
 * Enterprise OTA implementation for the STM32U585AI (2MB dual-bank flash).
 *
 * Flash Layout (STM32U585AI):
 *   Bank 1: 0x0800_0000 – 0x080F_FFFF  (1 MB, 128 pages × 8 KB)
 *   Bank 2: 0x0810_0000 – 0x081F_FFFF  (1 MB, 128 pages × 8 KB)
 *
 * The active bank is selected by the SWAP_BANK option bit (OPTR register).
 * When SWAP_BANK = 0: Bank 1 is mapped at 0x0800_0000 (active).
 * When SWAP_BANK = 1: Bank 2 is mapped at 0x0800_0000 (active).
 *
 * OTA writes to the INACTIVE bank, then swaps via Option Bytes.
 */

#include "ota_update.h"
#include "firmware_config.h"
#include "debug_log.h"
#include "wifi.h"
#include "main.h"

#include "mx_wifi.h"
#include "mx_wifi_io.h"
#include "mx_address.h"
#include "cJSON.h"

#include <string.h>
#include <stdio.h>

/* ═══════════════════════════════════════════════════════════════════════════
 *  Flash Constants
 * ═══════════════════════════════════════════════════════════════════════════ */

#define FLASH_BANK1_BASE    0x08000000UL
#define FLASH_BANK2_BASE    0x08100000UL
#define FLASH_BANK_SIZE     (1024 * 1024)    /* 1 MB per bank */
#define FLASH_PAGE_SIZE     (8 * 1024)       /* 8 KB per page */
#define FLASH_PAGES_PER_BANK 128

/* TAMP Backup Register for boot counter (BKP0R..BKP3R may be used by HAL,
 * so we use BKP4R to avoid conflicts).
 * On STM32U5, backup registers are in the TAMP peripheral, NOT RTC. */
#define OTA_BOOT_COUNTER_REG   TAMP->BKP4R
#define OTA_MAX_BOOT_FAILURES  3

/* ═══════════════════════════════════════════════════════════════════════════
 *  CRC32 (Software — MPEG-2 variant, no lookup table)
 *
 *  We use software CRC32 instead of the STM32 hardware CRC peripheral
 *  because the HW CRC uses a non-standard polynomial and would require
 *  the server to match it. Standard CRC32 is universally supported.
 * ═══════════════════════════════════════════════════════════════════════════ */

static uint32_t _crc32_update(uint32_t crc, const uint8_t *data, uint32_t len)
{
    for (uint32_t i = 0; i < len; i++)
    {
        crc ^= ((uint32_t)data[i] << 24);
        for (int bit = 0; bit < 8; bit++)
        {
            if (crc & 0x80000000UL)
                crc = (crc << 1) ^ 0x04C11DB7UL;
            else
                crc = (crc << 1);
        }
    }
    return crc;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Flash Bank Helpers
 * ═══════════════════════════════════════════════════════════════════════════ */

/**
 * @brief  Determine which bank is currently active.
 * @retval FLASH_BANK_1 or FLASH_BANK_2
 */
static uint32_t _get_active_bank(void)
{
    /* Read the SWAP_BANK bit from the current option bytes */
    FLASH_OBProgramInitTypeDef ob_cfg;
    HAL_FLASHEx_OBGetConfig(&ob_cfg);

    if (ob_cfg.USERConfig & FLASH_OPTR_SWAP_BANK)
        return FLASH_BANK_2;
    else
        return FLASH_BANK_1;
}

/**
 * @brief  Get the inactive bank (the one we write OTA updates to).
 * @retval FLASH_BANK_1 or FLASH_BANK_2
 */
static uint32_t _get_inactive_bank(void)
{
    return (_get_active_bank() == FLASH_BANK_1) ? FLASH_BANK_2 : FLASH_BANK_1;
}

/**
 * @brief  Get the base address of the inactive bank.
 */
static uint32_t _get_inactive_bank_base(void)
{
    /* In non-swapped mode, Bank 2 starts at FLASH_BANK2_BASE.
     * In swapped mode, Bank 1 starts at FLASH_BANK2_BASE.
     * The physical address is always Bank1=0x0800_0000, Bank2=0x0810_0000. */
    return (_get_inactive_bank() == FLASH_BANK_1) ? FLASH_BANK1_BASE : FLASH_BANK2_BASE;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  TCP Socket Helpers (reused from wifi.c pattern)
 * ═══════════════════════════════════════════════════════════════════════════ */

static int32_t _ota_socket_open(void)
{
    int32_t sock = MX_WIFI_Socket_create(
        wifi_obj_get(), MX_AF_INET, MX_SOCK_STREAM, MX_IPPROTO_TCP);
    if (sock < 0) return -1;

    struct mx_sockaddr_in addr = {0};
    addr.sin_len    = (uint8_t)sizeof(addr);
    addr.sin_family = MX_AF_INET;
    addr.sin_port   = (uint16_t)((SERVER_PORT >> 8) | ((SERVER_PORT & 0xFF) << 8));
    addr.sin_addr.s_addr = (uint32_t)mx_aton_r(SERVER_HOST);

    int32_t ret = MX_WIFI_Socket_connect(
        wifi_obj_get(), sock,
        (struct mx_sockaddr *)&addr, (int32_t)sizeof(addr));

    if (ret < 0)
    {
        MX_WIFI_Socket_close(wifi_obj_get(), sock);
        return -1;
    }

    return sock;
}

static int _ota_send_all(int32_t sock, const uint8_t *data, int32_t len)
{
    int32_t offset = 0;
    int retries = 0;

    while (offset < len)
    {
        int32_t chunk = len - offset;
        if (chunk > OTA_DOWNLOAD_CHUNK_SIZE)
            chunk = OTA_DOWNLOAD_CHUNK_SIZE;

        int32_t sent = MX_WIFI_Socket_send(
            wifi_obj_get(), sock,
            (uint8_t *)(data + offset), chunk,
            HTTP_RESPONSE_TIMEOUT_MS);

        if (sent > 0)
        {
            offset += sent;
            retries = 0;
            if (offset < len)
                MX_WIFI_IO_YIELD(wifi_obj_get(), 10);
        }
        else
        {
            retries++;
            if (retries >= 3) return -1;
            HAL_Delay(100);
        }
    }
    return 0;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Boot Validation (RTC Backup Register Counter)
 * ═══════════════════════════════════════════════════════════════════════════ */

void OTA_ValidateBoot(void)
{
    /* Enable backup domain access */
    __HAL_RCC_PWR_CLK_ENABLE();
    HAL_PWR_EnableBkUpAccess();

    uint32_t boot_count = OTA_BOOT_COUNTER_REG;

    LOG_INFO(TAG_OTA, "Boot counter: %lu / %d",
             (unsigned long)boot_count, OTA_MAX_BOOT_FAILURES);

    if (boot_count >= OTA_MAX_BOOT_FAILURES)
    {
        LOG_ERROR(TAG_OTA, "CRITICAL: %lu consecutive boot failures — REVERTING FIRMWARE",
                  (unsigned long)boot_count);

        /* Reset counter before swap to prevent infinite rollback loop */
        OTA_BOOT_COUNTER_REG = 0;

        /* Swap back to previous bank */
        OTA_SwapBankAndReset();

        /* If swap failed, continue with current firmware */
        LOG_ERROR(TAG_OTA, "Bank swap failed — continuing with current firmware");
    }

    /* Increment boot counter — will be cleared by OTA_MarkBootSuccessful() */
    OTA_BOOT_COUNTER_REG = boot_count + 1;
}

void OTA_MarkBootSuccessful(void)
{
    __HAL_RCC_PWR_CLK_ENABLE();
    HAL_PWR_EnableBkUpAccess();

    OTA_BOOT_COUNTER_REG = 0;

    LOG_INFO(TAG_OTA, "Boot validated — counter reset to 0");
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Version Check (HTTP GET /api/firmware/version)
 * ═══════════════════════════════════════════════════════════════════════════ */

OTAStatus_t OTA_CheckForUpdate(OTAVersionInfo_t *info)
{
    if (info == NULL) return OTA_ERROR_PARSE;

    LOG_INFO(TAG_OTA, "Checking for firmware update (current: %s)...", FW_VERSION);

    /* Build HTTP GET request */
    char header[256];
    int header_len = snprintf(header, sizeof(header),
        "GET %s HTTP/1.1\r\n"
        "Host: %s:%d\r\n"
        "Connection: close\r\n"
        "\r\n",
        OTA_VERSION_PATH, SERVER_HOST, SERVER_PORT);

    /* Open socket */
    int32_t sock = _ota_socket_open();
    if (sock < 0)
    {
        LOG_ERROR(TAG_OTA, "Version check: socket connect failed");
        return OTA_ERROR_NETWORK;
    }

    /* Send request */
    if (_ota_send_all(sock, (uint8_t *)header, header_len) != 0)
    {
        LOG_ERROR(TAG_OTA, "Version check: send failed");
        MX_WIFI_Socket_close(wifi_obj_get(), sock);
        return OTA_ERROR_NETWORK;
    }

    /* Receive response */
    MX_WIFI_IO_YIELD(wifi_obj_get(), 2000);

    uint8_t resp[512] = {0};
    int32_t resp_len = MX_WIFI_Socket_recv(
        wifi_obj_get(), sock, resp, sizeof(resp) - 1, HTTP_RESPONSE_TIMEOUT_MS);

    if (resp_len <= 0)
    {
        MX_WIFI_IO_YIELD(wifi_obj_get(), 3000);
        resp_len = MX_WIFI_Socket_recv(
            wifi_obj_get(), sock, resp, sizeof(resp) - 1, HTTP_RESPONSE_TIMEOUT_MS);
    }

    MX_WIFI_Socket_close(wifi_obj_get(), sock);

    if (resp_len <= 0)
    {
        LOG_ERROR(TAG_OTA, "Version check: no response");
        return OTA_ERROR_NETWORK;
    }

    resp[resp_len] = '\0';

    /* Find JSON body */
    const char *hdr_end = strstr((char *)resp, "\r\n\r\n");
    if (hdr_end == NULL)
    {
        LOG_ERROR(TAG_OTA, "Version check: no HTTP body");
        return OTA_ERROR_PARSE;
    }

    const char *body = strchr(hdr_end + 4, '{');
    if (body == NULL)
    {
        LOG_ERROR(TAG_OTA, "Version check: no JSON in body");
        return OTA_ERROR_PARSE;
    }

    /* Parse JSON */
    cJSON *root = cJSON_Parse(body);
    if (root == NULL)
    {
        LOG_ERROR(TAG_OTA, "Version check: JSON parse failed");
        return OTA_ERROR_PARSE;
    }

    cJSON *j_version = cJSON_GetObjectItem(root, "version");
    cJSON *j_size    = cJSON_GetObjectItem(root, "size");
    cJSON *j_crc32   = cJSON_GetObjectItem(root, "crc32");

    if (!cJSON_IsString(j_version) || !cJSON_IsNumber(j_size))
    {
        LOG_ERROR(TAG_OTA, "Version check: missing fields");
        cJSON_Delete(root);
        return OTA_ERROR_PARSE;
    }

    /* Copy version info */
    strncpy(info->version, j_version->valuestring, sizeof(info->version) - 1);
    info->version[sizeof(info->version) - 1] = '\0';
    info->size  = (uint32_t)j_size->valuedouble;
    info->crc32 = cJSON_IsNumber(j_crc32) ? (uint32_t)j_crc32->valuedouble : 0;

    cJSON_Delete(root);

    /* Compare versions */
    if (strcmp(info->version, FW_VERSION) == 0)
    {
        LOG_INFO(TAG_OTA, "Firmware is up-to-date (v%s)", FW_VERSION);
        return OTA_NO_UPDATE;
    }

    /* Size sanity check */
    if (info->size > OTA_MAX_FW_SIZE || info->size == 0)
    {
        LOG_ERROR(TAG_OTA, "Firmware size invalid: %lu bytes (max=%lu)",
                  (unsigned long)info->size, (unsigned long)OTA_MAX_FW_SIZE);
        return OTA_ERROR_TOO_LARGE;
    }

    LOG_INFO(TAG_OTA, "Update available: v%s → v%s (%lu bytes, crc=0x%08lX)",
             FW_VERSION, info->version,
             (unsigned long)info->size, (unsigned long)info->crc32);

    return OTA_OK;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Download & Flash (HTTP GET → inactive bank write)
 * ═══════════════════════════════════════════════════════════════════════════ */

OTAStatus_t OTA_DownloadAndFlash(const OTAVersionInfo_t *info,
                                 uint8_t *ram_buffer, uint32_t ram_size)
{
    if (info == NULL || info->size == 0 || ram_buffer == NULL)
        return OTA_ERROR_PARSE;

    if (info->size > ram_size)
    {
        LOG_ERROR(TAG_OTA, "Firmware (%lu bytes) exceeds RAM buffer (%lu bytes)",
                  (unsigned long)info->size, (unsigned long)ram_size);
        return OTA_ERROR_TOO_LARGE;
    }

    uint32_t inactive_bank = _get_inactive_bank();
    uint32_t bank_base     = _get_inactive_bank_base();
    uint32_t pages_needed  = (info->size + FLASH_PAGE_SIZE - 1) / FLASH_PAGE_SIZE;

    LOG_INFO(TAG_OTA, "Flashing v%s to Bank %lu (%lu pages to erase)...",
             info->version,
             (unsigned long)(inactive_bank == FLASH_BANK_1 ? 1 : 2),
             (unsigned long)pages_needed);

    /* ═════════════════════════════════════════════════════════════════════
     * Stage 1: Download entire firmware to RAM (NO flash ops during network I/O)
     * ═════════════════════════════════════════════════════════════════════ */

    LOG_INFO(TAG_OTA, "Downloading firmware to RAM (%lu bytes)...",
             (unsigned long)info->size);

    char header[256];
    int header_len = snprintf(header, sizeof(header),
        "GET %s HTTP/1.1\r\n"
        "Host: %s:%d\r\n"
        "Connection: close\r\n"
        "\r\n",
        OTA_DOWNLOAD_PATH, SERVER_HOST, SERVER_PORT);

    int32_t sock = _ota_socket_open();
    if (sock < 0)
    {
        LOG_ERROR(TAG_OTA, "Download: socket connect failed");
        return OTA_ERROR_NETWORK;
    }

    if (_ota_send_all(sock, (uint8_t *)header, header_len) != 0)
    {
        LOG_ERROR(TAG_OTA, "Download: send request failed");
        MX_WIFI_Socket_close(wifi_obj_get(), sock);
        return OTA_ERROR_NETWORK;
    }

    /* Wait for response headers */
    MX_WIFI_IO_YIELD(wifi_obj_get(), 2000);

    /* Read response — first read gets headers + start of body */
    uint8_t recv_buf[OTA_DOWNLOAD_CHUNK_SIZE + 512];
    int32_t recv_len = MX_WIFI_Socket_recv(
        wifi_obj_get(), sock, recv_buf, sizeof(recv_buf), HTTP_RESPONSE_TIMEOUT_MS);

    if (recv_len <= 0)
    {
        MX_WIFI_IO_YIELD(wifi_obj_get(), 3000);
        recv_len = MX_WIFI_Socket_recv(
            wifi_obj_get(), sock, recv_buf, sizeof(recv_buf), HTTP_RESPONSE_TIMEOUT_MS);
    }

    if (recv_len <= 0)
    {
        LOG_ERROR(TAG_OTA, "Download: no response");
        MX_WIFI_Socket_close(wifi_obj_get(), sock);
        return OTA_ERROR_NETWORK;
    }

    /* Skip HTTP headers — find \r\n\r\n */
    uint8_t *body_start = NULL;
    int32_t body_offset = 0;
    for (int32_t i = 0; i < recv_len - 3; i++)
    {
        if (recv_buf[i] == '\r' && recv_buf[i+1] == '\n' &&
            recv_buf[i+2] == '\r' && recv_buf[i+3] == '\n')
        {
            body_start = &recv_buf[i + 4];
            body_offset = i + 4;
            break;
        }
    }

    if (body_start == NULL)
    {
        LOG_ERROR(TAG_OTA, "Download: HTTP headers not found");
        MX_WIFI_Socket_close(wifi_obj_get(), sock);
        return OTA_ERROR_NETWORK;
    }

    /* Copy first chunk's body portion into RAM buffer */
    uint32_t total_downloaded = 0;
    int32_t first_body_len = recv_len - body_offset;
    if (first_body_len > 0)
    {
        memcpy(ram_buffer, body_start, first_body_len);
        total_downloaded = first_body_len;
    }

    /* Continue downloading remainder into RAM buffer */
    uint8_t toggle_led = 0;
    while (total_downloaded < info->size)
    {
        /* Progress LED blink */
        BSP_LED_On(LED_RED);
        if (toggle_led) BSP_LED_On(LED_GREEN);
        else BSP_LED_Off(LED_GREEN);
        toggle_led = !toggle_led;

        MX_WIFI_IO_YIELD(wifi_obj_get(), 100);

        uint32_t remaining = info->size - total_downloaded;
        uint32_t chunk_max = (remaining < OTA_DOWNLOAD_CHUNK_SIZE) ? remaining : OTA_DOWNLOAD_CHUNK_SIZE;

        recv_len = MX_WIFI_Socket_recv(
            wifi_obj_get(), sock, ram_buffer + total_downloaded, chunk_max,
            HTTP_RESPONSE_TIMEOUT_MS);

        if (recv_len <= 0)
        {
            /* Retry once */
            MX_WIFI_IO_YIELD(wifi_obj_get(), 2000);
            recv_len = MX_WIFI_Socket_recv(
                wifi_obj_get(), sock, ram_buffer + total_downloaded, chunk_max,
                HTTP_RESPONSE_TIMEOUT_MS);

            if (recv_len <= 0)
            {
                LOG_ERROR(TAG_OTA, "Download stalled at %lu/%lu bytes",
                          (unsigned long)total_downloaded,
                          (unsigned long)info->size);
                MX_WIFI_Socket_close(wifi_obj_get(), sock);
                BSP_LED_Off(LED_RED);
                BSP_LED_Off(LED_GREEN);
                return OTA_ERROR_NETWORK;
            }
        }

        total_downloaded += recv_len;

        /* Progress logging every 32 KB */
        if ((total_downloaded % (32 * 1024)) < (uint32_t)recv_len)
        {
            LOG_INFO(TAG_OTA, "Download: %lu / %lu bytes (%lu%%)",
                     (unsigned long)total_downloaded,
                     (unsigned long)info->size,
                     (unsigned long)(total_downloaded * 100 / info->size));
        }
    }

    MX_WIFI_Socket_close(wifi_obj_get(), sock);
    BSP_LED_Off(LED_RED);
    BSP_LED_Off(LED_GREEN);

    LOG_INFO(TAG_OTA, "Download complete: %lu bytes in RAM", (unsigned long)total_downloaded);

    /* ── CRC32 verification on RAM buffer (before touching flash) ── */
    uint32_t crc = _crc32_update(0xFFFFFFFF, ram_buffer, total_downloaded);

    if (info->crc32 != 0)
    {
        if (crc != info->crc32)
        {
            LOG_ERROR(TAG_OTA, "CRC32 mismatch: computed=0x%08lX expected=0x%08lX",
                      (unsigned long)crc, (unsigned long)info->crc32);
            return OTA_ERROR_VERIFY;
        }
        LOG_INFO(TAG_OTA, "CRC32 verified OK (0x%08lX)", (unsigned long)crc);
    }

    /* ═════════════════════════════════════════════════════════════════════
     * Stage 2: Erase flash + write from RAM (no network I/O needed)
     * ═════════════════════════════════════════════════════════════════════ */

    BSP_LED_On(LED_RED);
    BSP_LED_On(LED_GREEN);

    HAL_FLASH_Unlock();

    FLASH_EraseInitTypeDef erase_cfg = {0};
    erase_cfg.TypeErase = FLASH_TYPEERASE_PAGES;
    erase_cfg.Banks     = inactive_bank;
    erase_cfg.Page      = 0;
    erase_cfg.NbPages   = pages_needed;

    uint32_t erase_error = 0;
    HAL_StatusTypeDef hal_ret = HAL_FLASHEx_Erase(&erase_cfg, &erase_error);

    if (hal_ret != HAL_OK)
    {
        LOG_ERROR(TAG_OTA, "Flash erase failed (HAL=%d, page_err=%lu)",
                  hal_ret, (unsigned long)erase_error);
        HAL_FLASH_Lock();
        BSP_LED_Off(LED_RED);
        BSP_LED_Off(LED_GREEN);
        return OTA_ERROR_FLASH_ERASE;
    }

    LOG_INFO(TAG_OTA, "Erased %lu pages — writing %lu bytes from RAM to flash...",
             (unsigned long)pages_needed, (unsigned long)total_downloaded);

    /* Write from RAM to flash — quadword aligned (16 bytes) */
    uint32_t flash_addr = bank_base;
    uint32_t written = 0;

    /* Write aligned portion */
    uint32_t aligned_len = total_downloaded & ~0x0FUL;
    for (uint32_t i = 0; i < aligned_len; i += 16)
    {
        hal_ret = HAL_FLASH_Program(
            FLASH_TYPEPROGRAM_QUADWORD,
            flash_addr,
            (uint32_t)(uintptr_t)(ram_buffer + i));

        if (hal_ret != HAL_OK)
        {
            LOG_ERROR(TAG_OTA, "Flash write failed at 0x%08lX",
                      (unsigned long)flash_addr);
            HAL_FLASH_Lock();
            BSP_LED_Off(LED_RED);
            BSP_LED_Off(LED_GREEN);
            return OTA_ERROR_FLASH_WRITE;
        }
        flash_addr += 16;
        written += 16;
    }

    /* Write final partial quadword (pad with 0xFF) */
    uint32_t remainder = total_downloaded - aligned_len;
    if (remainder > 0)
    {
        uint8_t pad_buf[16];
        memset(pad_buf, 0xFF, 16);
        memcpy(pad_buf, ram_buffer + aligned_len, remainder);

        hal_ret = HAL_FLASH_Program(
            FLASH_TYPEPROGRAM_QUADWORD,
            flash_addr,
            (uint32_t)(uintptr_t)pad_buf);

        if (hal_ret != HAL_OK)
        {
            LOG_ERROR(TAG_OTA, "Flash write (final pad) failed");
            HAL_FLASH_Lock();
            BSP_LED_Off(LED_RED);
            BSP_LED_Off(LED_GREEN);
            return OTA_ERROR_FLASH_WRITE;
        }
        written += remainder;
    }

    HAL_FLASH_Lock();
    BSP_LED_Off(LED_RED);
    BSP_LED_Off(LED_GREEN);

    LOG_INFO(TAG_OTA, "Flash write complete: %lu bytes written",
             (unsigned long)written);

    return OTA_OK;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Bank Swap & Reset
 * ═══════════════════════════════════════════════════════════════════════════ */

OTAStatus_t OTA_SwapBankAndReset(void)
{
    uint32_t active = _get_active_bank();

    LOG_INFO(TAG_OTA, "Swapping flash banks (active: Bank %lu → Bank %lu)...",
             (unsigned long)(active == FLASH_BANK_1 ? 1 : 2),
             (unsigned long)(active == FLASH_BANK_1 ? 2 : 1));

    HAL_FLASH_Unlock();
    HAL_FLASH_OB_Unlock();

    /* Read current option bytes */
    FLASH_OBProgramInitTypeDef ob_cfg;
    HAL_FLASHEx_OBGetConfig(&ob_cfg);

    /* Toggle SWAP_BANK bit */
    ob_cfg.OptionType = OPTIONBYTE_USER;
    ob_cfg.USERType   = OB_USER_SWAP_BANK;

    if (active == FLASH_BANK_1)
        ob_cfg.USERConfig = OB_SWAP_BANK_ENABLE;   /* Swap to Bank 2 */
    else
        ob_cfg.USERConfig = OB_SWAP_BANK_DISABLE;  /* Swap to Bank 1 */

    HAL_StatusTypeDef ret = HAL_FLASHEx_OBProgram(&ob_cfg);
    if (ret != HAL_OK)
    {
        LOG_ERROR(TAG_OTA, "Option byte program failed (HAL=%d)", ret);
        HAL_FLASH_OB_Lock();
        HAL_FLASH_Lock();
        return OTA_ERROR_SWAP;
    }

    LOG_INFO(TAG_OTA, "Bank swap programmed — launching reset...");
    
    /* Success: solid GREEN for 1.5 seconds before rebooting */
    BSP_LED_Off(LED_RED);
    BSP_LED_On(LED_GREEN);
    HAL_Delay(1500);

    /* This triggers a system reset with the new bank mapping.
     * DOES NOT RETURN on success. */
    HAL_FLASH_OB_Launch();

    /* If we get here, something went wrong */
    HAL_FLASH_OB_Lock();
    HAL_FLASH_Lock();
    LOG_ERROR(TAG_OTA, "OB_Launch returned — swap failed");
    return OTA_ERROR_SWAP;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Full OTA Flow (convenience)
 * ═══════════════════════════════════════════════════════════════════════════ */

OTAStatus_t OTA_CheckAndUpdate(uint8_t *ram_buffer, uint32_t ram_size)
{
    OTAVersionInfo_t info;
    OTAStatus_t status;

    /* Step 1: Check */
    status = OTA_CheckForUpdate(&info);
    if (status != OTA_OK)
        return status;  /* OTA_NO_UPDATE or error */

    /* Step 2: Download & Flash */
    LOG_INFO(TAG_OTA, "═══════════════════════════════════════");
    LOG_INFO(TAG_OTA, "  OTA UPDATE: v%s → v%s", FW_VERSION, info.version);
    LOG_INFO(TAG_OTA, "═══════════════════════════════════════");

    status = OTA_DownloadAndFlash(&info, ram_buffer, ram_size);
    if (status != OTA_OK)
    {
        LOG_ERROR(TAG_OTA, "Download/flash failed (err=%d) — aborting update", status);
        return status;
    }

    /* Step 3: Swap & Reset */
    return OTA_SwapBankAndReset();
}
