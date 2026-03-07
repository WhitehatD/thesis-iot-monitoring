# Firmware: STM32 B-U585I-IOT02A

This directory will contain the STM32CubeIDE project for the edge device.

## Setup Instructions

1. **Open STM32CubeIDE** and create a new project:
   - Board selector → **B-U585I-IOT02A**
   - Initialize with default peripherals → **Yes**
   - Project location → this `firmware/` directory

2. **Enable peripherals in CubeMX**:
   - DCMI (for OV5640 camera)
   - I2C1 (for OV5640 SCCB configuration)
   - SPI (for EMW3080 Wi-Fi)
   - USART1 (debug UART, 115200 baud)
   - RTC (for alarm-based wake-up)
   - FreeRTOS (via X-CUBE-FREERTOS middleware)

3. **Add middleware**:
   - coreMQTT (from FreeRTOS libraries)
   - coreHTTP (for image uploads)
   - cJSON (for JSON parsing)

4. **BSP components**:
   - Camera (OV5640) — from STM32CubeU5 BSP
   - Wi-Fi (EMW3080) — from STM32CubeU5 BSP

## Reference Projects

- [FreeRTOS/iot-reference-stm32u5](https://github.com/FreeRTOS/iot-reference-stm32u5) — Gold standard reference
- [DigiKey B-U585I Camera Tutorial](https://www.digikey.com/en/maker/projects/using-a-camera-module-with-the-b-u585i-iot02a-discovery-board/) — Step-by-step camera setup

## Custom Modules

| File | Purpose |
|---|---|
| `Core/Inc/scheduler.h` | RTC alarm task scheduler (JSON → RTC alarms) |
| `Core/Inc/camera.h` | OV5640 capture abstraction |
| `Core/Inc/wifi.h` | EMW3080 connection manager |
| `Core/Inc/mqtt_handler.h` | coreMQTT pub/sub handler |
