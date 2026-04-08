"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import AgentChat from "../../components/AgentChat";
import { useMQTT } from "../../hooks/useMQTT";

interface BoardState {
	firmware: string | null;
	lastSeen: number | null;
	status: string;
	captures: number;
	lastImageSize: number | null;
	lastLatencyMs: number | null;
	isOnline: boolean;
	logs: LogEntry[];
}

interface LogEntry {
	time: string;
	level: string;
	text: string;
}

interface ImageCapture {
	taskId: number;
	filename: string;
	url: string;
	date: string;
	timestamp: number;
	isNew: boolean;
	analysis?: {
		objective: string;
		objectiveMet: boolean;
		description: string;
		findings: string;
		recommendation: string;
		model: string;
		inferenceMs: number;
	};
}

const MAX_LOGS = 500;

export default function BoardPage({
	params,
}: {
	params: Promise<{ id: string }>;
}) {
	const { id: boardId } = use(params);
	const apiBase = process.env.NEXT_PUBLIC_API_URL || "";

	const [board, setBoard] = useState<BoardState>({
		firmware: null,
		lastSeen: null,
		status: "idle",
		captures: 0,
		lastImageSize: null,
		lastLatencyMs: null,
		isOnline: true,
		logs: [],
	});
	const [images, setImages] = useState<ImageCapture[]>([]);
	const [selectedImage, setSelectedImage] = useState<ImageCapture | null>(null);
	const [activeTab, setActiveTab] = useState<"gallery" | "console">("gallery");

	const addLog = useCallback((level: string, text: string) => {
		const entry: LogEntry = {
			time: new Date().toLocaleTimeString(),
			level,
			text,
		};
		setBoard((prev) => ({
			...prev,
			logs: [entry, ...prev.logs].slice(0, MAX_LOGS),
		}));
	}, []);

	const fetchImages = useCallback(() => {
		fetch(`${apiBase}/api/images?board_id=${boardId}`)
			.then((res) => res.json())
			.then((data) => {
				if (data.images) {
					setImages(
						data.images.map((img: any) => ({
							taskId: img.task_id,
							filename: img.filename,
							url: `${apiBase}${img.url}`,
							date: img.date,
							timestamp: img.timestamp,
							isNew: false,
						})),
					);
				}
			})
			.catch(console.error);
	}, [apiBase, boardId]);

	useEffect(() => {
		fetchImages();
	}, [fetchImages]);

	const handleMessage = useCallback(
		(topic: string, data: Record<string, any>, sourceBoardId: string) => {
			if (topic === "dashboard/images/new") {
				fetchImages();
				return;
			}
			if (topic === "dashboard/analysis/new") {
				setImages((prev) =>
					prev.map((img) =>
						img.filename === data.filename
							? {
									...img,
									analysis: {
										objective: data.objective || "",
										objectiveMet: data.objective_met || false,
										description: data.description || "",
										findings: data.findings || "",
										recommendation: data.recommendation || "",
										model: data.model || "",
										inferenceMs: data.inference_ms || 0,
									},
								}
							: img,
					),
				);
				addLog(
					"info",
					`AI analysis: task #${data.task_id} — ${data.objective_met ? "MET" : "NOT MET"}`,
				);
				return;
			}
			if (topic === "dashboard/logs") {
				const logTime = data.timestamp
					? new Date(data.timestamp * 1000).toLocaleTimeString()
					: new Date().toLocaleTimeString();
				setBoard((prev) => ({
					...prev,
					logs: [
						{ time: logTime, level: data.level || "log", text: data.text },
						...prev.logs,
					].slice(0, MAX_LOGS),
				}));
				return;
			}
			if (sourceBoardId !== boardId) return;
			setBoard((prev) => {
				const update = { ...prev, isOnline: true, lastSeen: Date.now() };
				if (data.firmware) update.firmware = data.firmware;
				if (data.status) {
					update.status = data.status;
					update.logs = [
						{
							time: new Date().toLocaleTimeString(),
							level: "info",
							text: `Status: ${data.status}`,
						},
						...update.logs,
					].slice(0, MAX_LOGS);
				}
				if (data.status === "captured" || data.status === "uploaded") {
					update.captures += 1;
					if (data.size) update.lastImageSize = data.size;
					if (data.latency_ms) update.lastLatencyMs = data.latency_ms;
				}
				return update;
			});
		},
		[boardId, fetchImages, addLog],
	);

	const topics = [
		`device/${boardId}/status`,
		"device/stm32/status",
		"dashboard/images/new",
		"dashboard/analysis/new",
		"dashboard/logs",
	];
	const { connectionStatus } = useMQTT(topics, handleMessage);

	useEffect(() => {
		const interval = setInterval(() => {
			setBoard((prev) => {
				if (
					prev.isOnline &&
					prev.lastSeen &&
					Date.now() - prev.lastSeen > 15000
				) {
					return { ...prev, isOnline: false };
				}
				return prev;
			});
		}, 5000);
		return () => clearInterval(interval);
	}, []);

	const deleteImage = async (img: ImageCapture) => {
		if (!confirm("Delete this capture permanently?")) return;
		try {
			await fetch(`${apiBase}/api/images/${img.date}/${img.filename}`, {
				method: "DELETE",
			});
			setImages((prev) => prev.filter((i) => i.filename !== img.filename));
			setSelectedImage(null);
		} catch (err) {
			addLog("error", `Delete failed: ${err}`);
		}
	};

	const sortedImages = [...images].sort((a, b) => b.timestamp - a.timestamp);

	return (
		<div className="app-container agent-layout">
			{/* Header with inline telemetry */}
			<header className="agent-header-bar">
				<div className="agent-header-left">
					<Link href="/" className="btn-back">
						&larr;
					</Link>
					<div className="agent-header-info">
						<h1 className="agent-header-title">Monitoring Agent</h1>
						<span className="agent-header-node">{boardId}</span>
					</div>
				</div>
				<div className="agent-header-stats">
					<div className="header-stat">
						<div
							className={`status-indicator ${board.isOnline ? "online" : "offline"}`}
						>
							<div className="dot" />
							{board.isOnline ? "Online" : "Offline"}
						</div>
					</div>
					<div className="header-stat">
						<span className="header-stat-label">FW</span>
						<span className="header-stat-value">
							{board.firmware ? `v${board.firmware}` : "\u2014"}
						</span>
					</div>
					<div className="header-stat">
						<span className="header-stat-label">Captures</span>
						<span className="header-stat-value highlight">
							{board.captures}
						</span>
					</div>
					<div className="header-stat">
						<span className="header-stat-label">State</span>
						<span
							className={`header-stat-value ${getStatusClass(board.status)}`}
						>
							{board.status}
						</span>
					</div>
					<div className="connection-badge">
						<div
							className={`connection-dot ${connectionStatus === "connected" ? "connected" : "disconnected"}`}
						/>
						MQTT
					</div>
				</div>
			</header>

			{/* Agent Chat — hero element */}
			<main className="agent-main">
				<AgentChat boardId={boardId} apiBase={apiBase} fullSize />
			</main>

			{/* Right panel: Gallery + Console */}
			<aside className="agent-sidebar">
				<div className="panel-tabs">
					<button
						className={`panel-tab ${activeTab === "gallery" ? "active" : ""}`}
						onClick={() => setActiveTab("gallery")}
					>
						Gallery
						{images.length > 0 && (
							<span className="tab-count">{images.length}</span>
						)}
					</button>
					<button
						className={`panel-tab ${activeTab === "console" ? "active" : ""}`}
						onClick={() => setActiveTab("console")}
					>
						Console
						{board.logs.length > 0 && (
							<span className="tab-count">{board.logs.length}</span>
						)}
					</button>
				</div>

				{activeTab === "gallery" && (
					<div className="panel-content">
						<div className="sidebar-gallery">
							{sortedImages.length === 0 ? (
								<div className="empty-state-sm">
									No captures yet. Ask the agent to take a picture.
								</div>
							) : (
								sortedImages.map((img) => (
									<div
										key={img.filename}
										className="sidebar-image-card"
										onClick={() => setSelectedImage(img)}
									>
										{img.analysis && (
											<div
												className={`analysis-indicator ${img.analysis.objectiveMet ? "met" : "unmet"}`}
											/>
										)}
										<div className="sidebar-image-wrapper">
											<img
												src={img.url}
												alt={`Task ${img.taskId}`}
												loading="lazy"
											/>
										</div>
										<div className="sidebar-image-meta">
											<span>#{img.taskId}</span>
											<span className="image-time">
												{new Date(img.timestamp * 1000).toLocaleTimeString()}
											</span>
										</div>
									</div>
								))
							)}
						</div>
					</div>
				)}

				{activeTab === "console" && (
					<div className="panel-content">
						<div className="terminal-window compact">
							<div className="terminal-header">
								<span>Board Console</span>
								<button
									className="btn-text"
									onClick={() => setBoard((prev) => ({ ...prev, logs: [] }))}
								>
									Clear
								</button>
							</div>
							{board.logs.length === 0 ? (
								<div className="terminal-empty">
									No telemetry received yet...
								</div>
							) : (
								board.logs.map((log, idx) => (
									<div key={idx} className={`log-line log-${log.level}`}>
										<span className="log-time">[{log.time}]</span>
										{log.text}
									</div>
								))
							)}
						</div>
					</div>
				)}
			</aside>

			{/* Lightbox */}
			{selectedImage && (
				<div
					className="lightbox-overlay"
					onClick={() => setSelectedImage(null)}
				>
					<div
						className="lightbox-content"
						onClick={(e) => e.stopPropagation()}
					>
						<button
							className="lightbox-close"
							onClick={() => setSelectedImage(null)}
						>
							&times;
						</button>
						<img
							src={selectedImage.url}
							alt="Full size capture"
							className="lightbox-image"
						/>
						<div className="lightbox-footer">
							<div>
								<h3>Task #{selectedImage.taskId}</h3>
								<p>
									{new Date(selectedImage.timestamp * 1000).toLocaleString()}
								</p>
							</div>
							<div className="lightbox-actions">
								<a
									href={selectedImage.url}
									download
									className="btn btn-secondary"
								>
									Download
								</a>
								<button
									className="btn btn-danger"
									onClick={() => deleteImage(selectedImage)}
								>
									Delete
								</button>
							</div>
						</div>
						{selectedImage.analysis && (
							<div className="analysis-panel">
								<div className="analysis-header">
									<span
										className={`analysis-badge ${selectedImage.analysis.objectiveMet ? "badge-met" : "badge-unmet"}`}
									>
										{selectedImage.analysis.objectiveMet
											? "Objective Met"
											: "Objective Not Met"}
									</span>
									<span className="analysis-meta">
										{selectedImage.analysis.model} &middot;{" "}
										{selectedImage.analysis.inferenceMs.toFixed(0)}ms
									</span>
								</div>
								{selectedImage.analysis.objective && (
									<div className="analysis-row">
										<span className="analysis-label">Objective</span>
										<p>{selectedImage.analysis.objective}</p>
									</div>
								)}
								<div className="analysis-row">
									<span className="analysis-label">Findings</span>
									<p>{selectedImage.analysis.findings}</p>
								</div>
								<div className="analysis-row">
									<span className="analysis-label">Recommendation</span>
									<p>{selectedImage.analysis.recommendation}</p>
								</div>
							</div>
						)}
					</div>
				</div>
			)}
		</div>
	);
}

function getStatusClass(status: string): string {
	if (status.includes("error") || status.includes("failed"))
		return "status-error";
	if (status.includes("captur") || status.includes("upload"))
		return "status-active";
	if (status.includes("ota") || status.includes("ping")) return "status-ota";
	return "status-idle";
}
