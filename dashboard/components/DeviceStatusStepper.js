"use client";

import { useEffect, useState } from "react";

/**
 * Enterprise Job Stepper — visualizes the IoT board's exact progress
 * across image capture and OTA update lifecycles.
 *
 * Dynamically switches between capture steps and OTA steps based on
 * the current jobState.step value.
 */
export default function DeviceStatusStepper({ jobState }) {
	const [visible, setVisible] = useState(false);

	useEffect(() => {
		let t;
		if (jobState?.isActive) {
			t = setTimeout(() => setVisible(true), 0);
		} else {
			t = setTimeout(() => setVisible(false), 500);
		}
		return () => clearTimeout(t);
	}, [jobState?.isActive]);

	if (!visible) return null;

	/* ── Step definitions ────────────────────────────────── */
	const captureSteps = [
		{ id: "sending", label: "Sending", icon: "🚀" },
		{ id: "received", label: "Job Received", icon: "📥" },
		{ id: "camera_init", label: "Camera Init", icon: "⚙️" },
		{ id: "capturing", label: "Capturing Image", icon: "📸" },
		{ id: "uploading", label: "Uploading", icon: "📡" },
		{ id: "finished", label: "Finished", icon: "✅" },
	];

	const otaSteps = [
		{ id: "ota_checking", label: "Checking", icon: "🔍" },
		{ id: "ota_downloading", label: "Downloading", icon: "⬇️" },
		{ id: "ota_rebooting", label: "Rebooting", icon: "🔄" },
	];

	const isOta =
		jobState?.step?.startsWith("ota_") ||
		(jobState?.step === "error" && jobState?.error?.includes?.("OTA"));
	const steps = isOta ? otaSteps : captureSteps;
	const currentStepIndex = steps.findIndex((s) => s.id === jobState?.step);

	const getStepClass = (index) => {
		if (jobState?.step === "error") return "error";
		if (jobState?.step === "ota_up_to_date") return "completed";
		if (index < currentStepIndex) return "completed";
		if (index === currentStepIndex) return "active pulse";
		return "pending";
	};

	const ota = jobState?.otaProgress;

	return (
		<div
			className={`stepper-banner ${jobState?.isActive ? "visible" : "hidden"}`}
		>
			<div className="stepper-header">
				<span className="stepper-title">
					{jobState?.step === "error"
						? "🚨 Error"
						: isOta
							? "🔄 OTA Firmware Update"
							: "⚡ Live Board Progress"}
				</span>
				{jobState?.taskId && (
					<span className="stepper-task">Task #{jobState.taskId}</span>
				)}
			</div>

			{jobState?.step === "error" ? (
				<div className="stepper-error-msg">
					{jobState?.error || "Unknown Error"}
				</div>
			) : jobState?.step === "ota_up_to_date" ? (
				<div className="ota-up-to-date-msg">
					✅ Firmware is already up-to-date
				</div>
			) : (
				<div className="stepper-track">
					{steps.map((step, idx) => (
						<div
							key={step.id}
							className={`stepper-step-container ${getStepClass(idx)}`}
						>
							<div className="stepper-step">
								<div className="step-icon">{step.icon}</div>
								<div className="step-label">{step.label}</div>
							</div>
							{idx < steps.length - 1 && (
								<div
									className={`step-line ${idx < currentStepIndex ? "active-line" : ""}`}
								/>
							)}
						</div>
					))}
				</div>
			)}

			{/* ── OTA Real-Time Progress Panel ────────────────────── */}
			{isOta && ota && (
				<div className="ota-progress-panel">
					<div className="ota-progress-bar-track">
						<div
							className="ota-progress-bar-fill"
							style={{ width: `${ota.percent || 0}%` }}
						/>
					</div>
					<div className="ota-metrics-grid">
						<div className="ota-metric">
							<span className="ota-metric-value">{ota.percent || 0}%</span>
							<span className="ota-metric-label">Progress</span>
						</div>
						<div className="ota-metric">
							<span className="ota-metric-value">
								{ota.downloaded ? `${(ota.downloaded / 1024).toFixed(1)}` : "0"}{" "}
								/ {ota.total ? `${(ota.total / 1024).toFixed(1)}` : "?"} KB
							</span>
							<span className="ota-metric-label">Downloaded</span>
						</div>
						<div className="ota-metric">
							<span className="ota-metric-value">
								{ota.throughputKbps || 0} KB/s
							</span>
							<span className="ota-metric-label">Throughput</span>
						</div>
						<div className="ota-metric">
							<span className="ota-metric-value">
								{ota.elapsedMs ? `${(ota.elapsedMs / 1000).toFixed(1)}s` : "—"}
							</span>
							<span className="ota-metric-label">Elapsed</span>
						</div>
					</div>
				</div>
			)}

			{/* ── Live Log Stream ───────────────────────────────── */}
			{jobState?.logs && jobState.logs.length > 0 && (
				<div className="stepper-logs-terminal">
					{jobState.logs.map((log, idx) => (
						<div key={idx} className="log-line">
							{log}
						</div>
					))}
				</div>
			)}
		</div>
	);
}
