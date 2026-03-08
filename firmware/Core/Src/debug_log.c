/**
 * @file    debug_log.c
 * @brief   UART Debug Logging Implementation
 * @author  Alexandru-Ionut Cioc
 * @date    2026
 *
 * Initializes USART1 (ST-Link VCP) and provides formatted debug output.
 * The _write() syscall override redirects printf/puts to the UART.
 */

#include "debug_log.h"

#if DEBUG_LOG_ENABLED

#include "main.h"
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

/* ── UART Handle ──────────────────────────────────────── */

static UART_HandleTypeDef huart_debug;
static volatile uint8_t   s_initialized = 0;

/* 256-byte line buffer — large enough for any single log line */
#define LOG_BUFFER_SIZE  256
static char s_log_buffer[LOG_BUFFER_SIZE];

/* ── Initialization ───────────────────────────────────── */

void Debug_Init(void)
{
    /* USART1 GPIO: PA9 (TX), PA10 (RX) — directly routed to ST-Link VCP
     * on the B-U585I-IOT02A Discovery Kit. */

    __HAL_RCC_USART1_CLK_ENABLE();
    __HAL_RCC_GPIOA_CLK_ENABLE();

    GPIO_InitTypeDef gpio = {0};
    gpio.Pin       = GPIO_PIN_9 | GPIO_PIN_10;
    gpio.Mode      = GPIO_MODE_AF_PP;
    gpio.Pull      = GPIO_NOPULL;
    gpio.Speed     = GPIO_SPEED_FREQ_HIGH;
    gpio.Alternate = GPIO_AF7_USART1;
    HAL_GPIO_Init(GPIOA, &gpio);

    huart_debug.Instance          = DEBUG_UART_INSTANCE;
    huart_debug.Init.BaudRate     = DEBUG_UART_BAUDRATE;
    huart_debug.Init.WordLength   = UART_WORDLENGTH_8B;
    huart_debug.Init.StopBits     = UART_STOPBITS_1;
    huart_debug.Init.Parity       = UART_PARITY_NONE;
    huart_debug.Init.Mode         = UART_MODE_TX;        /* TX only for logging */
    huart_debug.Init.HwFlowCtl    = UART_HWCONTROL_NONE;
    huart_debug.Init.OverSampling = UART_OVERSAMPLING_16;

    if (HAL_UART_Init(&huart_debug) == HAL_OK)
    {
        s_initialized = 1;
    }
}

/* ── Formatted Print ──────────────────────────────────── */

void Debug_Print(const char *level, const char *tag, const char *fmt, ...)
{
    if (!s_initialized)
        return;

    int offset = 0;
    uint32_t ms = HAL_GetTick();

    /* Timestamp + level + tag prefix */
    offset = snprintf(s_log_buffer, LOG_BUFFER_SIZE,
                      "[%7lums] [%s] [%s] ",
                      (unsigned long)ms, level, tag);

    /* User message */
    va_list args;
    va_start(args, fmt);
    offset += vsnprintf(s_log_buffer + offset,
                        LOG_BUFFER_SIZE - offset, fmt, args);
    va_end(args);

    /* Ensure newline termination */
    if (offset < LOG_BUFFER_SIZE - 2)
    {
        s_log_buffer[offset++] = '\r';
        s_log_buffer[offset++] = '\n';
    }

    /* Blocking transmit — acceptable for debug logging */
    HAL_UART_Transmit(&huart_debug, (uint8_t *)s_log_buffer, offset, 100);
}

/* ── printf/puts redirect (optional, for HAL error paths) ─ */

/**
 * @brief  Override _write() so that printf() goes to UART.
 *         This is called by newlib's syscall layer.
 */
int _write(int file, char *ptr, int len)
{
    (void)file;  /* stdout / stderr both go to UART */

    if (s_initialized)
    {
        HAL_UART_Transmit(&huart_debug, (uint8_t *)ptr, len, 100);
    }
    return len;
}

#endif /* DEBUG_LOG_ENABLED */
