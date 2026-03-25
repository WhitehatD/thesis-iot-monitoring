/**
 * @file    captive_portal.h
 * @brief   WiFi Captive Portal — SoftAP + Embedded HTTP Server
 * @author  Alexandru-Ionut Cioc
 * @date    2026
 *
 * Starts a WiFi Access Point and serves a local configuration page
 * for setting the WiFi SSID/password. Includes DNS redirect for
 * automatic captive portal detection on mobile devices.
 */

#ifndef __CAPTIVE_PORTAL_H
#define __CAPTIVE_PORTAL_H

#include <stdint.h>
#include <stdbool.h>

/* ═══════════════════════════════════════════════════════════════════════════
 *  Types
 * ═══════════════════════════════════════════════════════════════════════════ */

typedef enum {
    PORTAL_OK = 0,
    PORTAL_ERROR_AP,        /* SoftAP start failed */
    PORTAL_ERROR_SERVER,    /* TCP server bind/listen failed */
    PORTAL_ERROR_DNS,       /* DNS redirect setup failed */
    PORTAL_CONFIGURED,      /* User submitted credentials — reboot pending */
} PortalStatus_t;

/* ═══════════════════════════════════════════════════════════════════════════
 *  API
 * ═══════════════════════════════════════════════════════════════════════════ */

/**
 * @brief  Start the captive portal.
 *
 * 1. Starts SoftAP with SSID "IoT-Setup-XXXX" (last 4 MAC hex)
 * 2. Starts DNS redirect (all queries → 192.168.10.1)
 * 3. Starts HTTP server on port 80
 * 4. BLOCKS until user submits WiFi credentials via the config page
 * 5. Saves credentials to flash and triggers system reboot
 *
 * @retval PORTAL_CONFIGURED on success (never returns — reboots).
 *         PORTAL_ERROR_* on failure.
 */
PortalStatus_t CaptivePortal_Start(void);

/**
 * @brief  Stop the captive portal and tear down SoftAP.
 *         Called internally or externally to abort portal mode.
 */
void CaptivePortal_Stop(void);

#endif /* __CAPTIVE_PORTAL_H */
