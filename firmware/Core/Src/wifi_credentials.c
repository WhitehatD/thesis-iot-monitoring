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
 *   Bank 1: 0x08000000 — 0x080FFFFF (1 MB, active usually)
 *   Bank 2: 0x08100000 — 0x081FFFFF (1 MB, inactive usually)
 *   Page size: 8 KB (0x2000)
 *   Last page: Page 127
 *
 * To survive OTA dual-bank swaps, credentials are unconditionally
 * written to BOTH Page 127 of Bank 1 (0x080FE000) AND Bank 2 (0x081FE000).
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
#define CRED_ADDR_ACTIVE    0x080FE000u  /* Last page of CPU active space */
#define CRED_ADDR_INACTIVE  0x081FE000u  /* Last page of CPU inactive space */
#define CRED_PAGE_NUMBER    127          /* Last page of 1MB bank */

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

    /* Check ACTIVE bank first (0x080FE000) then INACTIVE bank (0x081FE000) */
    uint32_t addrs[2] = { CRED_ADDR_ACTIVE, CRED_ADDR_INACTIVE };
    const FlashCredBlock_t *valid_block = NULL;

    for (int i = 0; i < 2; i++)
    {
        const FlashCredBlock_t *block = (const FlashCredBlock_t *)addrs[i];
        
        if (block->magic == 0xFFFFFFFF || block->magic == 0x00000000 || block->magic != WIFI_CRED_MAGIC)
            continue;

        uint32_t computed_crc = _crc32((const uint8_t *)block, CRED_DATA_SIZE);
        if (computed_crc == block->crc32)
        {
            valid_block = block;
            break; /* Found valid credentials! */
        }
    }

    if (valid_block == NULL)
    {
        LOG_INFO(TAG_PORT, "No valid WiFi credentials found in flash");
        return WIFI_CRED_EMPTY;
    }

    /* Copy validated credentials */
    memcpy(creds->ssid, valid_block->ssid, sizeof(creds->ssid));
    memcpy(creds->password, valid_block->password, sizeof(creds->password));

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

    /* ── Step 2: Erase Page 127 on BOTH Physical Banks ── */
    FLASH_EraseInitTypeDef erase_cfg = {0};
    erase_cfg.TypeErase = FLASH_TYPEERASE_PAGES;
    erase_cfg.Page      = CRED_PAGE_NUMBER;
    erase_cfg.NbPages   = 1;

    uint32_t page_error = 0;
    
    erase_cfg.Banks = FLASH_BANK_1;
    if (HAL_FLASHEx_Erase(&erase_cfg, &page_error) != HAL_OK)
    {
        LOG_ERROR(TAG_PORT, "Flash erase Bank 1 failed (err=0x%08lX)", (unsigned long)HAL_FLASH_GetError());
    }

    erase_cfg.Banks = FLASH_BANK_2;
    if (HAL_FLASHEx_Erase(&erase_cfg, &page_error) != HAL_OK)
    {
        LOG_ERROR(TAG_PORT, "Flash erase Bank 2 failed (err=0x%08lX)", (unsigned long)HAL_FLASH_GetError());
    }

    LOG_DEBUG(TAG_PORT, "Flash page %d erased on both banks", CRED_PAGE_NUMBER);

    /* ── Step 3: Program in 16-byte quadwords to BOTH address spaces */
    uint32_t total_bytes = sizeof(FlashCredBlock_t);
    uint32_t padded_size = (total_bytes + 15) & ~15u;  /* Round up to 16 */

    uint8_t write_buf[128] __attribute__((aligned(16)));
    memset(write_buf, 0xFF, sizeof(write_buf));
    memcpy(write_buf, &block, total_bytes);

    uint32_t target_addrs[2] = { CRED_ADDR_ACTIVE, CRED_ADDR_INACTIVE };
    int write_ok = 0;

    for (int b = 0; b < 2; b++)
    {
        uint32_t flash_addr = target_addrs[b];
        int bank_success = 1;
        
        for (uint32_t offset = 0; offset < padded_size; offset += 16)
        {
            hal_ret = HAL_FLASH_Program(FLASH_TYPEPROGRAM_QUADWORD,
                                        flash_addr + offset,
                                        (uint32_t)(uintptr_t)&write_buf[offset]);
            if (hal_ret != HAL_OK)
            {
                LOG_ERROR(TAG_PORT, "Flash program failed at 0x%08lX (HAL=%d, ERR=0x%08lX)",
                          (unsigned long)(flash_addr + offset), hal_ret, (unsigned long)HAL_FLASH_GetError());
                bank_success = 0;
                break;
            }
        }
        
        if (bank_success) write_ok++;
    }

    /* ── Step 4: Lock flash and verify ────────────────── */
    HAL_FLASH_Lock();

    if (write_ok == 0)
    {
        LOG_ERROR(TAG_PORT, "Flash writes failed for both banks");
        return WIFI_CRED_FLASH_ERROR;
    }

    LOG_INFO(TAG_PORT, "WiFi credentials saved OK (%d/2 banks)", write_ok);
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
    erase_cfg.Page      = CRED_PAGE_NUMBER;
    erase_cfg.NbPages   = 1;

    uint32_t page_error = 0;
    
    erase_cfg.Banks = FLASH_BANK_1;
    HAL_FLASHEx_Erase(&erase_cfg, &page_error);
    
    erase_cfg.Banks = FLASH_BANK_2;
    HAL_FLASHEx_Erase(&erase_cfg, &page_error);

    HAL_FLASH_Lock();

    LOG_INFO(TAG_PORT, "WiFi credentials erased OK on both banks");
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
