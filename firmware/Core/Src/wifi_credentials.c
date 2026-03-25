/**
 * @file    wifi_credentials.c
 * @brief   Flash-Persistent WiFi Credential Storage (STM32U585 Bank 2)
 * @author  Alexandru-Ionut Cioc
 * @date    2026
 *
 * Uses the LAST page of Flash Bank 2 (0x081FE000) to store WiFi
 * credentials with integrity validation (magic header + CRC32).
 *
 * STM32U585AI Flash geometry:
 *   Bank 1: 0x08000000 — 0x080FFFFF (1 MB, firmware)
 *   Bank 2: 0x08100000 — 0x081FFFFF (1 MB, available)
 *   Page size: 8 KB (0x2000)
 *   Last page: 0x081FE000 — 0x081FFFFF
 *
 * Flash Layout:
 *   Offset 0x00: Magic   (4 bytes) = 0x57494649 ("WIFI")
 *   Offset 0x04: SSID    (33 bytes, null-terminated)
 *   Offset 0x25: Password(64 bytes, null-terminated)
 *   Offset 0x65: CRC32   (4 bytes) over bytes 0x00-0x64
 *
 * The STM32U5 flash must be programmed in 128-bit (16-byte) quadwords.
 */

#include "wifi_credentials.h"
#include "firmware_config.h"
#include "debug_log.h"
#include "main.h"

#include <string.h>

/* ═══════════════════════════════════════════════════════════════════════════
 *  Flash Page Geometry for STM32U585
 * ═══════════════════════════════════════════════════════════════════════════ */

#define CRED_PAGE_SIZE      0x2000    /* 8 KB */
#define CRED_BANK           FLASH_BANK_2
#define CRED_PAGE_NUMBER    127       /* Last page of Bank 2 (128 pages, 0-indexed) */

/* ═══════════════════════════════════════════════════════════════════════════
 *  On-Flash Data Structure (packed, 105 bytes)
 * ═══════════════════════════════════════════════════════════════════════════ */

#pragma pack(push, 1)
typedef struct {
    uint32_t magic;       /* WIFI_CRED_MAGIC = 0x57494649 */
    char     ssid[33];    /* Null-terminated SSID */
    char     password[64];/* Null-terminated password */
    uint32_t crc32;       /* CRC32 over magic + ssid + password */
} FlashCredBlock_t;
#pragma pack(pop)

#define CRED_DATA_SIZE  (offsetof(FlashCredBlock_t, crc32))  /* Bytes covered by CRC */

/* ═══════════════════════════════════════════════════════════════════════════
 *  Software CRC32 (no hardware dependency)
 *
 *  Polynomial: 0xEDB88320 (reflected Ethernet CRC32)
 * ═══════════════════════════════════════════════════════════════════════════ */

static uint32_t _crc32(const uint8_t *data, uint32_t len)
{
    uint32_t crc = 0xFFFFFFFF;
    for (uint32_t i = 0; i < len; i++)
    {
        crc ^= data[i];
        for (int j = 0; j < 8; j++)
        {
            if (crc & 1)
                crc = (crc >> 1) ^ 0xEDB88320;
            else
                crc >>= 1;
        }
    }
    return ~crc;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Load — Read and validate credentials from flash
 * ═══════════════════════════════════════════════════════════════════════════ */

WiFiCredStatus_t WiFiCred_Load(WiFiCredentials_t *creds)
{
    if (creds == NULL)
        return WIFI_CRED_CORRUPT;

    const FlashCredBlock_t *flash_block =
        (const FlashCredBlock_t *)WIFI_CRED_FLASH_ADDR;

    /* Check for blank/zeroed flash — both 0xFFFFFFFF (erased) and
     * 0x00000000 (zeroed by OTA bank erase or fresh MCU) mean
     * no credentials have been stored yet. */
    if (flash_block->magic == 0xFFFFFFFF || flash_block->magic == 0x00000000)
    {
        LOG_INFO(TAG_PORT, "No stored WiFi credentials (flash %s)",
                 flash_block->magic == 0xFFFFFFFF ? "erased" : "zeroed");
        return WIFI_CRED_EMPTY;
    }

    /* Validate magic */
    if (flash_block->magic != WIFI_CRED_MAGIC)
    {
        LOG_INFO(TAG_PORT, "Flash magic mismatch: 0x%08lX (expected 0x%08lX)",
                 (unsigned long)flash_block->magic,
                 (unsigned long)WIFI_CRED_MAGIC);
        return WIFI_CRED_CORRUPT;
    }

    /* Validate CRC32 */
    uint32_t computed_crc = _crc32((const uint8_t *)flash_block, CRED_DATA_SIZE);
    if (computed_crc != flash_block->crc32)
    {
        LOG_ERROR(TAG_PORT, "Flash CRC32 mismatch: stored=0x%08lX computed=0x%08lX",
                  (unsigned long)flash_block->crc32,
                  (unsigned long)computed_crc);
        return WIFI_CRED_CORRUPT;
    }

    /* Copy validated credentials */
    memcpy(creds->ssid, flash_block->ssid, sizeof(creds->ssid));
    memcpy(creds->password, flash_block->password, sizeof(creds->password));

    /* Ensure null termination (defense in depth) */
    creds->ssid[sizeof(creds->ssid) - 1] = '\0';
    creds->password[sizeof(creds->password) - 1] = '\0';

    LOG_INFO(TAG_PORT, "Loaded WiFi credentials from flash: SSID='%s'", creds->ssid);
    return WIFI_CRED_OK;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Save — Erase page + write credentials to flash
 *
 *  STM32U5 requires 128-bit (16-byte) aligned quadword programming.
 *  We build a page-aligned buffer and program it in 16-byte chunks.
 * ═══════════════════════════════════════════════════════════════════════════ */

WiFiCredStatus_t WiFiCred_Save(const char *ssid, const char *password)
{
    if (ssid == NULL || password == NULL)
        return WIFI_CRED_FLASH_ERROR;

    if (strlen(ssid) == 0 || strlen(ssid) > 32 || strlen(password) > 63)
    {
        LOG_ERROR(TAG_PORT, "Invalid credential lengths: SSID=%u, PWD=%u",
                  (unsigned)strlen(ssid), (unsigned)strlen(password));
        return WIFI_CRED_FLASH_ERROR;
    }

    LOG_INFO(TAG_PORT, "Saving WiFi credentials to flash: SSID='%s'", ssid);

    /* Build the credential block in RAM */
    FlashCredBlock_t block;
    memset(&block, 0, sizeof(block));
    block.magic = WIFI_CRED_MAGIC;
    strncpy(block.ssid, ssid, sizeof(block.ssid) - 1);
    strncpy(block.password, password, sizeof(block.password) - 1);
    block.crc32 = _crc32((const uint8_t *)&block, CRED_DATA_SIZE);

    LOG_DEBUG(TAG_PORT, "CRC32=0x%08lX, block_size=%u bytes",
              (unsigned long)block.crc32, (unsigned)sizeof(block));

    /* ── Step 1: Unlock flash ─────────────────────────── */
    HAL_StatusTypeDef hal_ret = HAL_FLASH_Unlock();
    if (hal_ret != HAL_OK)
    {
        LOG_ERROR(TAG_PORT, "Flash unlock failed (HAL=%d)", hal_ret);
        return WIFI_CRED_FLASH_ERROR;
    }

    /* ── Step 2: Erase the credential page ────────────── */
    FLASH_EraseInitTypeDef erase_cfg = {0};
    erase_cfg.TypeErase = FLASH_TYPEERASE_PAGES;
    erase_cfg.Banks     = CRED_BANK;
    erase_cfg.Page      = CRED_PAGE_NUMBER;
    erase_cfg.NbPages   = 1;

    uint32_t page_error = 0;
    hal_ret = HAL_FLASHEx_Erase(&erase_cfg, &page_error);
    if (hal_ret != HAL_OK)
    {
        LOG_ERROR(TAG_PORT, "Flash erase failed (HAL=%d, page_error=0x%08lX)",
                  hal_ret, (unsigned long)page_error);
        HAL_FLASH_Lock();
        return WIFI_CRED_FLASH_ERROR;
    }

    LOG_DEBUG(TAG_PORT, "Flash page %d erased OK", CRED_PAGE_NUMBER);

    /* ── Step 3: Program in 16-byte quadwords ─────────── */
    /*
     * STM32U5 flash row programming: each HAL_FLASH_Program call writes
     * exactly 16 bytes (128-bit quadword). We pad the block to 16-byte
     * alignment and write sequentially.
     */
    uint32_t total_bytes = sizeof(FlashCredBlock_t);
    uint32_t padded_size = (total_bytes + 15) & ~15u;  /* Round up to 16 */

    /* Zero-padded write buffer (aligned for flash DMA) */
    uint8_t write_buf[128] __attribute__((aligned(16)));
    memset(write_buf, 0xFF, sizeof(write_buf));  /* Fill with erased state */
    memcpy(write_buf, &block, total_bytes);

    uint32_t flash_addr = WIFI_CRED_FLASH_ADDR;
    for (uint32_t offset = 0; offset < padded_size; offset += 16)
    {
        /* Build 128-bit quadword from the buffer */
        uint32_t qw[4];
        memcpy(qw, &write_buf[offset], 16);

        hal_ret = HAL_FLASH_Program(FLASH_TYPEPROGRAM_QUADWORD,
                                    flash_addr + offset,
                                    (uint32_t)(uintptr_t)&write_buf[offset]);
        if (hal_ret != HAL_OK)
        {
            LOG_ERROR(TAG_PORT, "Flash program failed at 0x%08lX (HAL=%d)",
                      (unsigned long)(flash_addr + offset), hal_ret);
            HAL_FLASH_Lock();
            return WIFI_CRED_FLASH_ERROR;
        }
    }

    /* ── Step 4: Lock flash and verify ────────────────── */
    HAL_FLASH_Lock();

    /* Read-back verification */
    const FlashCredBlock_t *verify =
        (const FlashCredBlock_t *)WIFI_CRED_FLASH_ADDR;

    if (verify->magic != WIFI_CRED_MAGIC)
    {
        LOG_ERROR(TAG_PORT, "Flash write verify FAILED: magic=0x%08lX",
                  (unsigned long)verify->magic);
        return WIFI_CRED_FLASH_ERROR;
    }

    uint32_t verify_crc = _crc32((const uint8_t *)verify, CRED_DATA_SIZE);
    if (verify_crc != verify->crc32)
    {
        LOG_ERROR(TAG_PORT, "Flash write verify FAILED: CRC mismatch");
        return WIFI_CRED_FLASH_ERROR;
    }

    LOG_INFO(TAG_PORT, "WiFi credentials saved and verified OK");
    return WIFI_CRED_OK;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  Erase — Clear stored credentials
 * ═══════════════════════════════════════════════════════════════════════════ */

WiFiCredStatus_t WiFiCred_Erase(void)
{
    LOG_INFO(TAG_PORT, "Erasing stored WiFi credentials...");

    HAL_StatusTypeDef hal_ret = HAL_FLASH_Unlock();
    if (hal_ret != HAL_OK)
    {
        LOG_ERROR(TAG_PORT, "Flash unlock failed for erase");
        return WIFI_CRED_FLASH_ERROR;
    }

    FLASH_EraseInitTypeDef erase_cfg = {0};
    erase_cfg.TypeErase = FLASH_TYPEERASE_PAGES;
    erase_cfg.Banks     = CRED_BANK;
    erase_cfg.Page      = CRED_PAGE_NUMBER;
    erase_cfg.NbPages   = 1;

    uint32_t page_error = 0;
    hal_ret = HAL_FLASHEx_Erase(&erase_cfg, &page_error);

    HAL_FLASH_Lock();

    if (hal_ret != HAL_OK)
    {
        LOG_ERROR(TAG_PORT, "Flash erase failed");
        return WIFI_CRED_FLASH_ERROR;
    }

    LOG_INFO(TAG_PORT, "WiFi credentials erased OK");
    return WIFI_CRED_OK;
}

/* ═══════════════════════════════════════════════════════════════════════════
 *  HasValid — Quick existence check
 * ═══════════════════════════════════════════════════════════════════════════ */

bool WiFiCred_HasValid(void)
{
    WiFiCredentials_t tmp;
    return (WiFiCred_Load(&tmp) == WIFI_CRED_OK);
}
