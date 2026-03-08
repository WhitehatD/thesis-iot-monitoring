/**
 * @file    wifi.h
 * @brief   MXCHIP EMW3080 Wi-Fi Connection Manager
 * @author  Alexandru-Ionut Cioc
 * @date    2026
 *
 * Manages Wi-Fi connectivity via the onboard EMW3080 module
 * on the B-U585I-IOT02A Discovery Kit (SPI interface).
 */

#ifndef __WIFI_H
#define __WIFI_H

#include <stdint.h>
#include <stdbool.h>

/* Wi-Fi status */
typedef enum {
    WIFI_OK = 0,
    WIFI_ERROR_INIT,
    WIFI_ERROR_CONNECT,
    WIFI_ERROR_TIMEOUT,
    WIFI_ERROR_SEND,
} WiFiStatus_t;

/**
 * @brief  Initialize the EMW3080 Wi-Fi module.
 * @retval WIFI_OK on success.
 */
WiFiStatus_t WiFi_Init(void);

/**
 * @brief  Connect to the configured Wi-Fi network.
 * @param  ssid: Network SSID.
 * @param  password: Network password.
 * @retval WIFI_OK on success.
 */
WiFiStatus_t WiFi_Connect(const char *ssid, const char *password);

/**
 * @brief  Check if Wi-Fi is currently connected.
 * @retval true if connected.
 */
bool WiFi_IsConnected(void);

/**
 * @brief  Perform an HTTP POST with binary image data.
 * @param  url: Full URL (e.g., "http://192.168.1.100:8000/api/upload")
 * @param  task_id: Task ID to include in the request.
 * @param  data: Image data buffer.
 * @param  data_len: Length of image data in bytes.
 * @retval WIFI_OK on success.
 */
WiFiStatus_t WiFi_HttpPostImage(const char *url, uint16_t task_id,
                                 const uint8_t *data, uint32_t data_len);

/**
 * @brief  Fetch the current time from the server via HTTP GET /api/time.
 * @param  hour, minute, second: Time output.
 * @param  year: 2-digit year (e.g. 26 = 2026).
 * @param  month, day, weekday: Date output (weekday: Monday=1..Sunday=7).
 * @retval WIFI_OK on success, error otherwise.
 */
WiFiStatus_t WiFi_HttpGetTime(uint8_t *hour, uint8_t *minute, uint8_t *second,
                               uint8_t *year, uint8_t *month, uint8_t *day,
                               uint8_t *weekday);

/**
 * @brief  Disconnect and power down the Wi-Fi module.
 */
void WiFi_DeInit(void);

#endif /* __WIFI_H */
