"use client";

/**
 * Live device status banner — shows real-time STM32 board activity.
 * Displays when the board is capturing, uploading, or processing.
 * Appears with a slide-in animation and auto-hides when idle.
 */
export default function DeviceStatusBanner({ deviceStatus }) {
    if (!deviceStatus) return null;

    const statusConfig = {
        captured: { icon: "✅", label: "Image captured & uploaded", color: "emerald" },
        executing: { icon: "📸", label: "Capturing image...", color: "blue", pulse: true },
        uploading: { icon: "📡", label: "Uploading to server...", color: "amber", pulse: true },
        online: { icon: "🟢", label: "Board online", color: "emerald" },
        ota_checking: { icon: "🔄", label: "Checking for updates...", color: "amber", pulse: true },
        ota_downloading: { icon: "⬇️", label: "Downloading firmware...", color: "amber", pulse: true },
        ota_rebooting: { icon: "🔁", label: "Rebooting with new firmware...", color: "amber", pulse: true },
        schedule_cleared: { icon: "🗑️", label: "Schedule cleared", color: "slate" },
        error: { icon: "❌", label: `Error: ${deviceStatus?.reason || "unknown"}`, color: "red" },
    };

    const cfg = statusConfig[deviceStatus.status] || {
        icon: "ℹ️",
        label: deviceStatus.status || "Unknown",
        color: "slate",
    };

    return (
        <div className={`device-status-banner ${cfg.color}${cfg.pulse ? " pulse" : ""}`}>
            <span className="device-status-icon">{cfg.icon}</span>
            <span className="device-status-label">{cfg.label}</span>
            {deviceStatus.task_id != null && (
                <span className="device-status-task">Task #{deviceStatus.task_id}</span>
            )}
            {deviceStatus.latency_ms != null && (
                <span className="device-status-latency">{deviceStatus.latency_ms}ms</span>
            )}
        </div>
    );
}
