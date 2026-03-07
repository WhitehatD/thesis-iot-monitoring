<#
.SYNOPSIS
    Flash firmware to the STM32 B-U585I-IOT02A via ST-Link.

.DESCRIPTION
    Wrapper around STM32_Programmer_CLI for quick firmware flashing.
    Supports .bin, .hex, and .elf files.

.PARAMETER FirmwarePath
    Path to the firmware file to flash.

.PARAMETER Erase
    If specified, performs a full chip erase before flashing.

.PARAMETER Verify
    If specified, verifies the flash contents after programming.

.EXAMPLE
    .\flash.ps1 -FirmwarePath .\firmware\Debug\firmware.bin
    .\flash.ps1 -FirmwarePath .\firmware.hex -Erase -Verify
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$FirmwarePath,

    [switch]$Erase,
    [switch]$Verify
)

$CLI = "C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe"

if (-not (Test-Path $CLI)) {
    Write-Error "STM32CubeProgrammer CLI not found at: $CLI"
    exit 1
}

if (-not (Test-Path $FirmwarePath)) {
    Write-Error "Firmware file not found: $FirmwarePath"
    exit 1
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  STM32 Flash Utility" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Connect and identify
Write-Host "[1/3] Connecting to ST-Link..." -ForegroundColor Yellow
& $CLI --list 2>$null | Select-String "Board Name|ST-LINK SN|ST-LINK FW"

# Optional erase
if ($Erase) {
    Write-Host ""
    Write-Host "[*] Performing full chip erase..." -ForegroundColor Red
    & $CLI -c port=SWD mode=NORMAL shared -e all
}

# Flash
Write-Host ""
Write-Host "[2/3] Flashing: $FirmwarePath" -ForegroundColor Yellow

$flashArgs = @("-c", "port=SWD", "mode=NORMAL", "shared", "-d", $FirmwarePath, "0x08000000")

if ($Verify) {
    $flashArgs += "-v"
}

$flashArgs += "-rst"

& $CLI @flashArgs

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[3/3] Flash complete! Board reset." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "[!] Flash failed with exit code: $LASTEXITCODE" -ForegroundColor Red
}
