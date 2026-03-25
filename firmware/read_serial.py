import serial
import time
import sys

with open("ota_crash_log.txt", "w") as f, serial.Serial("COM7", 115200, timeout=1) as ser:
    f.write("Connected to COM7\n")
    f.flush()
    while True:
        line = ser.readline()
        if line:
            try:
                s = line.decode('utf-8', errors='replace').strip()
                f.write(s + "\n")
                f.flush()
            except Exception as e:
                pass
