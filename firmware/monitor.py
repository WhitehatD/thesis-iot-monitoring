#!/usr/bin/env python3
"""
STM32 Serial Monitor — COM7 @ 115200 baud
Continuously reads and prints UART output. Press Ctrl+C to stop.

Usage:  python monitor.py
        python monitor.py COM8        # override port
        python monitor.py COM7 9600   # override port + baud
"""

import sys
import serial
import serial.tools.list_ports

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM7"
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 115200

RESET = "\033[0m"
CYAN  = "\033[36m"
YELLOW = "\033[33m"
RED   = "\033[31m"
GREEN = "\033[32m"
DIM   = "\033[2m"


def colorize(line: str) -> str:
    """Apply ANSI colors based on log level tags."""
    if "[ERROR]" in line or "FATAL" in line:
        return f"{RED}{line}{RESET}"
    if "[WARN]" in line:
        return f"{YELLOW}{line}{RESET}"
    if "[DEBUG]" in line:
        return f"{DIM}{line}{RESET}"
    if "====" in line or "Boot complete" in line or "synced" in line.lower():
        return f"{GREEN}{line}{RESET}"
    return line


def main():
    print(f"{CYAN}╔══════════════════════════════════════════════╗{RESET}")
    print(f"{CYAN}║  STM32 Serial Monitor — {PORT} @ {BAUD}    ║{RESET}")
    print(f"{CYAN}║  Press Ctrl+C to stop                       ║{RESET}")
    print(f"{CYAN}╚══════════════════════════════════════════════╝{RESET}")
    print()

    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
    except serial.SerialException as e:
        print(f"{RED}Could not open {PORT}: {e}{RESET}")
        print(f"\nAvailable ports:")
        for p in serial.tools.list_ports.comports():
            print(f"  {p.device}  —  {p.description}")
        sys.exit(1)

    try:
        while True:
            raw = ser.readline()
            if raw:
                line = raw.decode("utf-8", errors="replace").rstrip()
                print(colorize(line))
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Monitor stopped.{RESET}")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
