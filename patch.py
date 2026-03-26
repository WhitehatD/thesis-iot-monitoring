import sys
path = 'd:\\- thesis\\thesis-iot-monitoring\\firmware\\Core\\Src\\captive_portal.c'
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_code = '''        /* Test credentials in real-time before saving */
        LOG_INFO(TAG_PORT, "Testing WiFi credentials in background...");

        /* Start streaming response: No Content-Length because we stream chunk by chunk */
        const char *stream_hdrs = 
            "HTTP/1.1 200 OK\\r\\n"
            "Content-Type: text/html; charset=UTF-8\\r\\n"
            "Connection: close\\r\\n"
            "Cache-Control: no-store, no-cache\\r\\n"
            "X-Content-Type-Options: nosniff\\r\\n"
            "\\r\\n";
        _portal_send_all(client_sock, (const uint8_t *)stream_hdrs, (int32_t)strlen(stream_hdrs));
        _portal_send_all(client_sock, (const uint8_t *)HTML_STREAMING_HEADER, (int32_t)strlen(HTML_STREAMING_HEADER));
        
        /* 1024 bytes padding for Safari buffer flush */
        char pad[128]; memset(pad, ' ', sizeof(pad)-1); pad[sizeof(pad)-1]='\\0';
        for(int i=0; i<8; i++) _portal_send_all(client_sock, (const uint8_t *)pad, 127);

        s_current_client_sock = client_sock;
        
        if (WiFi_TestConnection(ssid, password, _wifi_test_callback) != WIFI_OK)
        {
            LOG_WARN(TAG_PORT, "Credentials failed test. Serving error streaming tag.");
            const char *fail_js = "<script>complete(false, 'Check password. Returning to setup...');</script></body></html>\\n";
            _portal_send_all(client_sock, (const uint8_t *)fail_js, (int32_t)strlen(fail_js));
            MX_WIFI_IO_YIELD(wifi_obj_get(), 1000);
            s_current_client_sock = -1;
            return 0; /* Return 0 to keep portal running and NOT reboot */
        }

        LOG_INFO(TAG_PORT, "Credentials verified!");
        
        /* Save to flash */
        WiFiCredStatus_t save_ret = WiFiCred_Save(ssid, password);
        if (save_ret != WIFI_CRED_OK)
        {
            LOG_ERROR(TAG_PORT, "FATAL: Failed to save credentials to flash!");
        }

        /* Send success indication and close HTML */
        const char *succ_js = "<script>complete(true, 'Credentials saved. Rebooting sensor...');</script></body></html>\\n";
        _portal_send_all(client_sock, (const uint8_t *)succ_js, (int32_t)strlen(succ_js));

        /* Give the client time to receive the response */
        MX_WIFI_IO_YIELD(wifi_obj_get(), 1000);
        s_current_client_sock = -1;
        return 1;  /* Signal reboot needed */
'''

for i, l in enumerate(lines):
    if "/* Test credentials in real-time before saving */" in l:
        start_idx = i
        break
for i in range(start_idx, len(lines)):
    if "return 1;  /* Signal reboot needed */" in lines[i]:
        end_idx = i
        break

lines[start_idx:end_idx+1] = [l + '\n' for l in new_code.split('\n')]

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('Patched successfully!')
