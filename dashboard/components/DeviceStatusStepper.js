"use client";

import { useEffect, useState } from "react";

/**
 * Enterprise Job Stepper — visualizes the IoT board's exact progress
 * across the image capture lifecycle.
 */
export default function DeviceStatusStepper({ jobState }) {
	const [visible, setVisible] = useState(false);

	useEffect(() => {
		let t;
		if (jobState?.isActive) {
			t = setTimeout(() => setVisible(true), 0);
		} else {
			t = setTimeout(() => setVisible(false), 500); // allow fade out
		}
		return () => clearTimeout(t);
	}, [jobState?.isActive]);

	if (!visible) return null;

	const steps = [
		{ id: "sending", label: "Sending", icon: "🚀" },
		{ id: "received", label: "Job Received", icon: "📥" },
		{ id: "camera_init", label: "Camera Init", icon: "⚙️" },
		{ id: "capturing", label: "Capturing Image", icon: "📸" },
		{ id: "uploading", label: "Uploading", icon: "📡" },
		{ id: "finished", label: "Finished", icon: "✅" },
	];

	const currentStepIndex = steps.findIndex((s) => s.id === jobState?.step);

	const getStepClass = (index) => {
		if (jobState?.step === "error") return "error";
		if (index < currentStepIndex) return "completed";
		if (index === currentStepIndex) return "active pulse";
		return "pending";
	};

	return (
		<div
			className={`stepper-banner ${jobState?.isActive ? "visible" : "hidden"}`}
		>
			<div className="stepper-header">
				<span className="stepper-title">
					{jobState?.step === "error" ? "🚨 Error" : "⚡ Live Board Progress"}
				</span>
				{jobState?.taskId && (
					<span className="stepper-task">Task #{jobState.taskId}</span>
				)}
			</div>

			{jobState?.step === "error" ? (
				<div className="stepper-error-msg">
					{jobState?.error || "Unknown Error"}
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
