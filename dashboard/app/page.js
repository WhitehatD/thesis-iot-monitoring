"use client";

import BoardTelemetryPanel from "@/components/BoardTelemetryPanel";
import CaptureButton from "@/components/CaptureButton";
import ConnectionStatus from "@/components/ConnectionStatus";
import DeviceStatusStepper from "@/components/DeviceStatusStepper";
import ImageGrid from "@/components/ImageGrid";
import SchedulerPanel from "@/components/SchedulerPanel";
import { useMqttImages } from "@/hooks/useMqttImages";

export default function DashboardPage() {
	const {
		images,
		status,
		jobState,
		deviceStatus,
		isBoardOnline,
		toasts,
		startManualCapture,
		boardTelemetry,
	} = useMqttImages();

	return (
		<div className="dashboard">
			{/* ── Header ────────────────────────────────────────── */}
			<header className="dashboard-header">
				<div className="header-left">
					<div className="header-logo">👁</div>
					<div>
						<div className="header-title">Visual Monitor</div>
						<div className="header-subtitle">IoT Dashboard</div>
					</div>
				</div>

				<div className="header-right">
					<div className="board-status-badge">
						<span
							className={`status-dot ${isBoardOnline ? "connected" : "disconnected"}`}
						/>
						{isBoardOnline ? "Board Online" : "Board Offline"}
						{boardTelemetry?.firmware && (
							<span className="firmware-chip">v{boardTelemetry.firmware}</span>
						)}
					</div>
					<ConnectionStatus status={status} />
					<CaptureButton onCaptureStart={startManualCapture} />
				</div>
			</header>

			{/* ── Stats Bar ─────────────────────────────────────── */}
			<div className="stats-bar">
				<div className="stat-card">
					<div className="stat-icon blue">📸</div>
					<div>
						<div className="stat-value">{images.length}</div>
						<div className="stat-label">Total Captures</div>
					</div>
				</div>
				<div className="stat-card">
					<div className="stat-icon emerald">🟢</div>
					<div>
						<div className="stat-value">
							{status === "connected" ? "Live" : "—"}
						</div>
						<div className="stat-label">MQTT Status</div>
					</div>
				</div>
				<div className="stat-card">
					<div className="stat-icon amber">📅</div>
					<div>
						<div className="stat-value">
							{images.length > 0
								? new Date(images[0].timestamp * 1000).toLocaleTimeString()
								: "—"}
						</div>
						<div className="stat-label">Last Capture</div>
					</div>
				</div>
			</div>

			{/* ── Board Telemetry Panel ────────────────────────── */}
			<BoardTelemetryPanel
				boardTelemetry={boardTelemetry}
				isBoardOnline={isBoardOnline}
			/>

			{/* ── Live Device Status ─────────────────────────────── */}
			<DeviceStatusStepper jobState={jobState} />

			{/* ── Scheduler ─────────────────────────────────────── */}
			<section className="main-content scheduler-section">
				<div className="section-header">
					<h2 className="section-title">
						<span className="dot amber" />
						Schedules
					</h2>
				</div>
				<SchedulerPanel deviceStatus={deviceStatus} />
			</section>

			{/* ── Image Grid ────────────────────────────────────── */}
			<main className="main-content">
				<div className="section-header">
					<h1 className="section-title">
						<span className="dot" />
						Camera Captures
					</h1>
				</div>
				<ImageGrid images={images} />
			</main>

			{/* ── Toast Notifications ───────────────────────────── */}
			{toasts.length > 0 && (
				<div className="toast-container">
					{toasts.map((toast) => (
						<div key={toast.id} className="toast">
							📸 {toast.message}
						</div>
					))}
				</div>
			)}
		</div>
	);
}
