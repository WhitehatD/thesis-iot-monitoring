"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * WifiConfigPanel — Enterprise WiFi credential management panel with
 * board polling display and ping controls.
 *
 * Features:
 *   - Configure WiFi SSID/password remotely
 *   - Real-time board connection status with polling indicator
 *   - One-click ping to verify board responsiveness
 *   - Live feedback when board confirms reconfiguration
 */
export default function WifiConfigPanel({
	isBoardOnline,
	boardTelemetry,
	wifiStatus,
	apiBase,
}) {
	const [ssid, setSsid] = useState("");
	const [password, setPassword] = useState("");
	const [showPassword, setShowPassword] = useState(false);
	const [submitting, setSubmitting] = useState(false);
	const [result, setResult] = useState(null); // { type: 'success'|'error', message }
	const [currentConfig, setCurrentConfig] = useState(null);
	const [pinging, setPinging] = useState(false);
	const [pingResult, setPingResult] = useState(null);
	const [lastPollTime, setLastPollTime] = useState(null);

	// Tick for live "last seen" display
	const [now, setNow] = useState(Date.now());
	useEffect(() => {
		const interval = setInterval(() => setNow(Date.now()), 1000);
		return () => clearInterval(interval);
	}, []);

	// Update poll time when board telemetry changes
	useEffect(() => {
		if (boardTelemetry?.lastSeen) {
			setLastPollTime(boardTelemetry.lastSeen);
		}
	}, [boardTelemetry?.lastSeen]);

	// Track wifi reconfig status from MQTT
	// biome-ignore lint/correctness/useExhaustiveDependencies: fetchCurrentConfig only needed on reconfig success
	useEffect(() => {
		if (wifiStatus === "wifi_reconfigured") {
			setResult({
				type: "success",
				message: "Board WiFi reconfigured successfully!",
			});
			setSubmitting(false);
			fetchCurrentConfig();
		} else if (wifiStatus === "wifi_reconfig_failed") {
			setResult({
				type: "error",
				message: "Reconfiguration failed — board reverted to defaults",
			});
			setSubmitting(false);
		} else if (wifiStatus === "wifi_reconfig_queued") {
			setResult({
				type: "info",
				message: "Board received command — reconnecting...",
			});
		}
	}, [wifiStatus]);

	// Fetch current config on mount
	const fetchCurrentConfig = useCallback(async () => {
		try {
			const res = await fetch(`${apiBase}/api/wifi/config`);
			if (res.ok) {
				const data = await res.json();
				setCurrentConfig(data);
				if (data.ssid) setSsid(data.ssid);
			}
		} catch (err) {
			console.error("Failed to fetch WiFi config:", err);
		}
	}, [apiBase]);

	useEffect(() => {
		fetchCurrentConfig();
	}, [fetchCurrentConfig]);

	// Submit new WiFi config
	const handleSubmit = async (e) => {
		e.preventDefault();
		setSubmitting(true);
		setResult(null);

		try {
			const res = await fetch(`${apiBase}/api/wifi/config`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ ssid, password }),
			});

			if (!res.ok) {
				const err = await res.json().catch(() => ({}));
				throw new Error(err.detail || `HTTP ${res.status}`);
			}

			const data = await res.json();
			setResult({
				type: "info",
				message: `Command sent to board — SSID: "${data.ssid}"`,
			});
			setPassword("");
			// submitting stays true until board ACKs via MQTT
			// Auto-clear after 30s if no ACK
			setTimeout(() => {
				setSubmitting((prev) => {
					if (prev)
						setResult({
							type: "warning",
							message: "No board response — is it online?",
						});
					return false;
				});
			}, 30000);
		} catch (err) {
			setResult({ type: "error", message: err.message });
			setSubmitting(false);
		}
	};

	// Ping board via dedicated ping command (lightweight health check)
	const handlePing = async () => {
		setPinging(true);
		setPingResult(null);
		const pingStart = Date.now();

		try {
			const res = await fetch(`${apiBase}/api/ping`, {
				method: "POST",
			});

			if (!res.ok) throw new Error(`HTTP ${res.status}`);

			// The board will respond via MQTT status — we just check if we can reach the server
			const latency = Date.now() - pingStart;
			setPingResult({
				type: "success",
				message: `Server reachable (${latency}ms) — awaiting board response...`,
			});

			// Clear after 5s
			setTimeout(() => setPingResult(null), 5000);
		} catch (err) {
			setPingResult({ type: "error", message: `Ping failed: ${err.message}` });
		} finally {
			setPinging(false);
		}
	};

	const formatLastSeen = (ts) => {
		if (!ts) return "Never";
		const delta = Math.floor((now - ts) / 1000);
		if (delta < 3) return "just now";
		if (delta < 60) return `${delta}s ago`;
		if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
		return `${Math.floor(delta / 3600)}h ago`;
	};

	return (
		<section className="main-content wifi-config-section">
			<div className="section-header">
				<h2 className="section-title">
					<span className="dot cyan" />
					Board Control & WiFi
				</h2>
			</div>

			<div className="wifi-config-panel">
				{/* ── Board Polling Status ───────────────────────── */}
				<div className="wifi-board-status">
					<div className="wifi-board-status-header">
						<div className="wifi-board-identity">
							<span
								className={`wifi-board-dot ${isBoardOnline ? "online" : "offline"}`}
							/>
							<div>
								<div className="wifi-board-name">STM32 B-U585I-IOT02A</div>
								<div className="wifi-board-id">stm32-iot-cam-01</div>
							</div>
						</div>
						<div className="wifi-board-actions">
							<button
								type="button"
								className={`wifi-ping-btn ${pinging ? "pinging" : ""}`}
								onClick={handlePing}
								disabled={pinging}
								title="Send a ping to verify board responsiveness"
							>
								{pinging ? <span className="wifi-ping-spinner" /> : "📡"}
								{pinging ? "Pinging..." : "Ping Board"}
							</button>
						</div>
					</div>

					<div className="wifi-board-meta">
						<div className="wifi-meta-item">
							<span className="wifi-meta-label">Status</span>
							<span
								className={`wifi-meta-value ${isBoardOnline ? "value-online" : "value-offline"}`}
							>
								{isBoardOnline ? "● Online" : "○ Offline"}
							</span>
						</div>
						<div className="wifi-meta-item">
							<span className="wifi-meta-label">Last Poll</span>
							<span className="wifi-meta-value">
								{formatLastSeen(lastPollTime)}
							</span>
						</div>
						<div className="wifi-meta-item">
							<span className="wifi-meta-label">Firmware</span>
							<span className="wifi-meta-value">
								{boardTelemetry?.firmware ? `v${boardTelemetry.firmware}` : "—"}
							</span>
						</div>
						<div className="wifi-meta-item">
							<span className="wifi-meta-label">Active SSID</span>
							<span className="wifi-meta-value wifi-ssid-badge">
								{currentConfig?.ssid || "Compile-time default"}
							</span>
						</div>
					</div>

					{pingResult && (
						<div className={`wifi-result wifi-result-${pingResult.type}`}>
							{pingResult.message}
						</div>
					)}
				</div>

				{/* ── WiFi Configuration Form ───────────────────── */}
				<div className="wifi-form-container">
					<div className="wifi-form-header">
						<span className="wifi-form-icon">📶</span>
						<span>WiFi Credentials</span>
					</div>

					<form className="wifi-form" onSubmit={handleSubmit}>
						<div className="wifi-input-group">
							<label htmlFor="wifi-ssid" className="wifi-label">
								SSID
							</label>
							<input
								id="wifi-ssid"
								type="text"
								className="wifi-input"
								placeholder="Network name"
								value={ssid}
								onChange={(e) => setSsid(e.target.value)}
								maxLength={32}
								required
								disabled={submitting}
							/>
						</div>

						<div className="wifi-input-group">
							<label htmlFor="wifi-password" className="wifi-label">
								Password
							</label>
							<div className="wifi-password-wrapper">
								<input
									id="wifi-password"
									type={showPassword ? "text" : "password"}
									className="wifi-input"
									placeholder="WPA2 passphrase (8-63 chars)"
									value={password}
									onChange={(e) => setPassword(e.target.value)}
									minLength={8}
									maxLength={63}
									required
									disabled={submitting}
								/>
								<button
									type="button"
									className="wifi-eye-btn"
									onClick={() => setShowPassword(!showPassword)}
									tabIndex={-1}
								>
									{showPassword ? "🙈" : "👁"}
								</button>
							</div>
						</div>

						<button
							type="submit"
							className={`wifi-submit-btn ${submitting ? "submitting" : ""}`}
							disabled={submitting || !ssid || password.length < 8}
						>
							{submitting ? (
								<>
									<span className="wifi-submit-spinner" />
									Applying...
								</>
							) : (
								<>🔄 Apply to Board</>
							)}
						</button>
					</form>

					{result && (
						<div className={`wifi-result wifi-result-${result.type}`}>
							{result.type === "success" && "✅ "}
							{result.type === "error" && "❌ "}
							{result.type === "info" && "📡 "}
							{result.type === "warning" && "⚠️ "}
							{result.message}
						</div>
					)}
				</div>
			</div>
		</section>
	);
}
