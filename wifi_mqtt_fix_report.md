# WiFi → MQTT → Camera → Upload Pipeline — Full Engineering Report

**Date:** 2026-03-08  
**Board:** B-U585I-IOT02A RevC (STM32U585AI + EMW3080 WiFi + OV5640 Camera)  
**Goal:** Establish end-to-end: WiFi → DHCP → MQTT → Camera Capture → HTTP Upload → Dashboard

---

## 1. SPI Communication with EMW3080

### Problem

WiFi module completely unresponsive — `MX_WIFI_Init` failed with SPI timeouts. The FLOW handshake pin always read 0.

### Root Causes & Fixes

| # | Issue | Root Cause | Fix | File |
|---|-------|-----------|-----|------|
| 1 | **FLOW pin dead** | PG15 is on VddIO2 power domain — disabled by default on STM32U585 | Added `HAL_PWREx_EnableVddIO2()` before GPIOG clock enable | [mx_wifi_hw.c](file:///d:/-%20thesis/thesis-iot-monitoring/firmware/Core/Src/mx_wifi_hw.c) |
| 2 | **Wrong FLOW pin** | Code used PE1, schematic (UM2839 Table 14) says **PG15/EXTI15** | Updated pin + EXTI config | [mx_wifi_conf.h](file:///d:/-%20thesis/thesis-iot-monitoring/firmware/Core/Inc/mx_wifi_conf.h), [mx_wifi_hw.c](file:///d:/-%20thesis/thesis-iot-monitoring/firmware/Core/Src/mx_wifi_hw.c) |
| 3 | **Wrong NSS pin** | Code used PA5, schematic says **PB12** | Updated pin config | [mx_wifi_conf.h](file:///d:/-%20thesis/thesis-iot-monitoring/firmware/Core/Inc/mx_wifi_conf.h) |
| 4 | **Wrong NOTIFY pin** | Needed **PD14/EXTI14** per schematic | Updated pin + EXTI handler | [stm32u5xx_it.c](file:///d:/-%20thesis/thesis-iot-monitoring/firmware/Core/Src/stm32u5xx_it.c) |
| 5 | **Insufficient boot delay** | EMW3080 V2.3.4 needs >1.2s after reset | Increased to 3s in `MX_WIFI_HW_RESET` | [mx_wifi_spi.c](file:///d:/-%20thesis/thesis-iot-monitoring/firmware/Drivers/BSP/Components/mx_wifi/io_pattern/mx_wifi_spi.c) |

### Key Lesson

**Always trust the board schematic (UM2839)** over web search results or example code. The RevC board has different pin assignments than older revisions.

---

## 2. DHCP IP Assignment

### Problem

`MX_WIFI_Connect` succeeded but `MX_WIFI_GetIPAddress` returned all zeros.

### Root Cause

`MxWifiObj` is zero-initialized → `NetSettings.DHCP_IsEnabled = 0` → the driver sent a static IP config of `0.0.0.0` instead of requesting DHCP.

### Fix

```c
// wifi.c — before MX_WIFI_Connect
wifi_obj_get()->NetSettings.DHCP_IsEnabled = 1;
```

Also replaced rapid-fire `GetIPAddress` polling with a patient approach:

- 5s initial `MX_WIFI_IO_YIELD` for DHCP negotiation
- Up to 5 retries with 2s `IO_YIELD` gaps

This resolved the `command 0x0107 timeout waiting answer` errors caused by flooding the SPI command pipeline.

---

## 3. MQTT Broker Connectivity

### Problem

`MX_WIFI_Socket_connect` to `192.168.1.218:1883` timed out with `command 0x0202 timeout(10000 ms) waiting answer 6`.

### Diagnosis

1. ✅ Port 1883 reachable from Windows host (both `127.0.0.1` and `192.168.1.218`)
2. ✅ Docker Desktop WSL2 port forwarding working
3. ✅ Mosquitto container healthy, listening on `0.0.0.0:1883`

### Root Cause

The `struct mx_sockaddr_in` has a `sin_len` field that was left as 0. The EMW3080's TCP stack rejected the address structure.

### Fix

```c
// mqtt_handler.c
broker_addr.sin_len    = (uint8_t)sizeof(broker_addr);  // THIS WAS MISSING
broker_addr.sin_family = MX_AF_INET;
broker_addr.sin_port   = htons(config->broker_port);
broker_addr.sin_addr.s_addr = (uint32_t)mx_aton_r(config->broker_host);
```

Also added Windows Firewall inbound rule:

```powershell
netsh advfirewall firewall add rule name="MQTT Broker (Thesis IoT)" dir=in action=allow protocol=TCP localport=1883
```

### Result

```
TCP connected, sending CONNECT packet...
Connected to broker OK (session clean)
Subscribed OK (QoS granted: 0)
Boot complete — waiting for schedule...
```

---

## 4. HTTP Image Upload

### Problem

Same `sin_len` issue in the HTTP socket code — `Socket_connect` to `192.168.1.218:8000` timed out.

### Fix

Applied identical `sin_len` + `mx_aton_r()` fix to [wifi.c](file:///d:/-%20thesis/thesis-iot-monitoring/firmware/Core/Src/wifi.c) `WiFi_HttpPostImage()`, plus firewall rule for port 8000.

### Result

```
TCP connected to 192.168.1.218:8000
Upload OK — 614400 bytes sent
```

---

## 5. Image Not Rendering on Dashboard

### Problem

Server received upload (HTTP 200) but image showed as broken on the dashboard.

### Root Cause

The camera outputs **raw RGB565 pixel data** (640×480×2 = 614400 bytes), NOT JPEG. The server saved raw bytes as `.jpg` — browser can't decode it.

### Fix

Added server-side RGB565→JPEG conversion using numpy + Pillow in [routes.py](file:///d:/-%20thesis/thesis-iot-monitoring/server/app/api/routes.py):

```python
# Detect raw RGB565 by frame size
RGB565_SIZES = {640 * 480 * 2: (640, 480), 320 * 240 * 2: (320, 240)}

if len(content) in RGB565_SIZES:
    width, height = RGB565_SIZES[len(content)]
    pixels = np.frombuffer(content, dtype=np.uint16)
    b = ((pixels >> 11) & 0x1F).astype(np.uint8) * 255 // 31
    g = ((pixels >> 5)  & 0x3F).astype(np.uint8) * 255 // 63
    r = (pixels         & 0x1F).astype(np.uint8) * 255 // 31
    rgb = np.stack([r, g, b], axis=-1).reshape(height, width, 3)
    Image.fromarray(rgb, "RGB").save(filepath, "JPEG", quality=85)
```

> [!IMPORTANT]
> OV5640 `FORMAT_CTRL00 = 0x6F` outputs **BGR565** — bits[15:11]=Blue, bits[4:0]=Red. The R and B extraction is swapped versus standard RGB565.

### Secondary Bug: False JPEG Marker Detection

The `BSP_CAMERA_FrameEventCallback` scanned backward for `0xFF 0xD9` (JPEG end marker) in raw RGB565 data, found a false positive at byte 477201, and truncated the frame. This size didn't match `RGB565_SIZES`, so the server saved raw bytes.

**Fix:** Removed JPEG marker scanning — we only use RGB565 format.

---

## 6. Dark/Underexposed Images

### Problem

Images render correctly as JPEG but are extremely dark — shapes barely visible.

### Root Cause

OV5640 init sequence doesn't configure AEC/AGC registers. The `BSP_CAMERA_SetBrightness` is only a post-processing offset (writes to SDE registers), not actual exposure control.

### Fix

Added to [camera.c](file:///d:/-%20thesis/thesis-iot-monitoring/firmware/Core/Src/camera.c) after `BSP_CAMERA_Init`:

```c
BSP_CAMERA_SetBrightness(0, 2);     // Post-processing brightness +2
BSP_CAMERA_SetContrast(0, 1);       // Contrast +1
BSP_CAMERA_SetSaturation(0, 1);     // Saturation +1
BSP_CAMERA_EnableNightMode(0);      // AEC auto frame rate 15fps→3.75fps
HAL_Delay(1000);                    // Let AEC/AGC converge
```

`EnableNightMode` writes `AEC_CTRL00 = 0x7C` which enables automatic frame rate reduction (15fps → 3.75fps) for low-light environments, allowing longer exposure times.

---

## Summary of All Files Modified

| File | Changes |
|------|---------|
| [mx_wifi_conf.h](file:///d:/-%20thesis/thesis-iot-monitoring/firmware/Core/Inc/mx_wifi_conf.h) | Pin defs: NSS→PB12, NOTIFY→PD14/EXTI14, FLOW→PG15/EXTI15 |
| [mx_wifi_hw.c](file:///d:/-%20thesis/thesis-iot-monitoring/firmware/Core/Src/mx_wifi_hw.c) | VddIO2 enable, GPIO/EXTI config, SPI2 pins PD1/PD3/PD4 AF5 |
| [stm32u5xx_it.c](file:///d:/-%20thesis/thesis-iot-monitoring/firmware/Core/Src/stm32u5xx_it.c) | EXTI14 (NOTIFY) + EXTI15 (FLOW) handlers |
| [mx_wifi_spi.c](file:///d:/-%20thesis/thesis-iot-monitoring/firmware/Drivers/BSP/Components/mx_wifi/io_pattern/mx_wifi_spi.c) | 3s boot delay in `MX_WIFI_HW_RESET` |
| [wifi.c](file:///d:/-%20thesis/thesis-iot-monitoring/firmware/Core/Src/wifi.c) | DHCP enable, IP wait loop, HTTP `sin_len` fix |
| [mqtt_handler.c](file:///d:/-%20thesis/thesis-iot-monitoring/firmware/Core/Src/mqtt_handler.c) | MQTT `sin_len` + `mx_aton_r()` + debug log |
| [main.c](file:///d:/-%20thesis/thesis-iot-monitoring/firmware/Core/Src/main.c) | SPI pipeline flush before MQTT init |
| [camera.c](file:///d:/-%20thesis/thesis-iot-monitoring/firmware/Core/Src/camera.c) | Brightness/contrast/NightMode, removed false JPEG scanning |
| [routes.py](file:///d:/-%20thesis/thesis-iot-monitoring/server/app/api/routes.py) | RGB565→JPEG conversion (BGR565 byte order) |
| [requirements.txt](file:///d:/-%20thesis/thesis-iot-monitoring/server/requirements.txt) | Added `numpy>=1.26.0` |

---

## Current Status

| Component | Status |
|-----------|--------|
| EMW3080 SPI init | ✅ V2.3.4 detected |
| WiFi connect | ✅ First attempt |
| DHCP | ✅ IP 192.168.1.143 |
| MQTT connect | ✅ Broker 192.168.1.218:1883 |
| MQTT subscribe | ✅ `device/stm32/commands` |
| MQTT publish | ✅ Status messages |
| MQTT keepalive | ✅ PINGREQ/PINGRESP |
| Camera capture | ✅ 614400 bytes (VGA RGB565) |
| HTTP upload | ✅ TCP + multipart POST |
| Server conversion | ✅ BGR565→JPEG via numpy+Pillow |
| Dashboard display | ✅ Images render |
| Image brightness | 🔧 NightMode enabled, testing |
