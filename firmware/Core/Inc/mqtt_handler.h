/**
 * @file    mqtt_handler.h
 * @brief   MQTT Subscribe/Publish Handler (coreMQTT)
 * @author  Alexandru-Ionut Cioc
 * @date    2026
 *
 * Handles MQTT communication via coreMQTT (FreeRTOS).
 * Subscribes to schedule commands from the cloud server
 * and publishes status updates.
 */

#ifndef __MQTT_HANDLER_H
#define __MQTT_HANDLER_H

#include <stdint.h>

/* MQTT Topics */
#define MQTT_TOPIC_COMMANDS     "device/stm32/commands"
#define MQTT_TOPIC_STATUS       "device/stm32/status"
#define MQTT_TOPIC_LOGS         "device/stm32/logs"

/* MQTT connection config */
typedef struct {
    const char *broker_host;
    uint16_t broker_port;
    const char *client_id;
} MQTTConfig_t;

/* Callback for received schedule commands */
typedef void (*MQTTScheduleCallback_t)(const char *json_schedule, uint32_t length);

/**
 * @brief  Initialize the MQTT client and connect to the broker.
 * @param  config: Connection configuration.
 * @retval 0 on success.
 */
int MQTT_Init(const MQTTConfig_t *config);

/**
 * @brief  Subscribe to the commands topic and register a callback.
 * @param  callback: Function to call when a schedule is received.
 * @retval 0 on success.
 */
int MQTT_SubscribeCommands(MQTTScheduleCallback_t callback);

/**
 * @brief  Publish a status message to the cloud server.
 * @param  status_json: JSON status string.
 * @retval 0 on success.
 */
int MQTT_PublishStatus(const char *status_json);

/**
 * @brief  Publish a raw formatted log message over MQTT.
 * @param  log_text: Raw log message.
 * @retval 0 on success.
 */
int MQTT_PublishLog(const char *log_text);

/**
 * @brief  Process pending MQTT messages (call from FreeRTOS task loop).
 */
void MQTT_ProcessLoop(void);

/**
 * @brief  Disconnect from the broker.
 */
void MQTT_Disconnect(void);

/**
 * @brief  Send a PINGREQ to keep the connection alive.
 *         Should be called periodically from the main loop.
 */
void MQTT_SendPing(void);

/**
 * @brief  Returns connection status.
 * @retval 1 if connected, 0 otherwise.
 */
uint8_t MQTT_IsConnected(void);

#endif /* __MQTT_HANDLER_H */
