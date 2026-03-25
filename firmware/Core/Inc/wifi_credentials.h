/**
 * @file    wifi_credentials.h
 * @brief   Flash-Persistent WiFi Credential Storage (STM32U585 Bank 2)
 * @author  Alexandru-Ionut Cioc
 * @date    2026
 *
 * Stores WiFi SSID/password in the last page of Flash Bank 2 with
 * magic header + CRC32 validation. Survives power cycles.
 *
 * Flash Layout at WIFI_CRED_FLASH_ADDR:
 *   [Magic: 4B] [SSID: 33B] [Password: 64B] [CRC32: 4B] = 105 bytes
 */

#ifndef __WIFI_CREDENTIALS_H
#define __WIFI_CREDENTIALS_H

#include <stdint.h>
#include <stdbool.h>

/* ═══════════════════════════════════════════════════════════════════════════
 *  Types
 * ═══════════════════════════════════════════════════════════════════════════ */

typedef enum {
    WIFI_CRED_OK = 0,
    WIFI_CRED_EMPTY,        /* No credentials stored (virgin flash) */
    WIFI_CRED_CORRUPT,      /* CRC mismatch — data corrupted */
    WIFI_CRED_FLASH_ERROR,  /* HAL flash operation failed */
} WiFiCredStatus_t;

/**
 * @brief  WiFi credential container — matches the flash layout
 */
typedef struct {
    char ssid[33];      /* Max 32-char SSID + null terminator */
    char password[64];  /* Max 63-char WPA2 password + null */
} WiFiCredentials_t;

/* ═══════════════════════════════════════════════════════════════════════════
 *  API
 * ═══════════════════════════════════════════════════════════════════════════ */

/**
 * @brief  Load WiFi credentials from flash.
 * @param  creds: Output buffer for credentials.
 * @retval WIFI_CRED_OK if valid credentials found.
 *         WIFI_CRED_EMPTY if flash is blank (0xFF).
 *         WIFI_CRED_CORRUPT if magic/CRC mismatch.
 */
WiFiCredStatus_t WiFiCred_Load(WiFiCredentials_t *creds);

/**
 * @brief  Save WiFi credentials to flash (erases page first).
 * @param  ssid: WiFi SSID string (max 32 chars).
 * @param  password: WiFi password string (max 63 chars).
 * @retval WIFI_CRED_OK on success.
 *         WIFI_CRED_FLASH_ERROR on HAL failure.
 */
WiFiCredStatus_t WiFiCred_Save(const char *ssid, const char *password);

/**
 * @brief  Erase stored credentials (factory reset).
 * @retval WIFI_CRED_OK on success.
 */
WiFiCredStatus_t WiFiCred_Erase(void);

/**
 * @brief  Quick check if valid credentials exist in flash.
 * @retval true if credentials are present and CRC-valid.
 */
bool WiFiCred_HasValid(void);

#endif /* __WIFI_CREDENTIALS_H */
