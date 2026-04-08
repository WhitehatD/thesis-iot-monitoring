"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useRef, useState } from "react";
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
	const [filterDate, setFilterDate] = useState("all");
	const [sortOrder, setSortOrder] = useState<"newest" | "oldest">("newest");
	const [searchTaskId, setSearchTaskId] = useState("");

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

	// Fetch images from API
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

	// MQTT message handler
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
					`AI analysis complete for task #${data.task_id}: ${data.objective_met ? "Objective MET" : "Objective NOT met"}`,
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

			// Board-specific telemetry
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

	// Offline detection
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

	// Actions
	const capturePicture = async () => {
		try {
			await fetch(`${apiBase}/api/capture`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ board_id: boardId }),
			});
			addLog("info", "Capture triggered");
		} catch (err) {
			addLog("error", `Capture failed: ${err}`);
		}
	};

	const pingBoard = async () => {
		try {
			await fetch(`${apiBase}/api/ping`, {
				method: "POST",
				body: JSON.stringify({ board_id: boardId }),
			});
			addLog("info", "Ping sent");
		} catch (err) {
			addLog("error", `Ping failed: ${err}`);
		}
	};

	const triggerSetupMode = async () => {
		if (
			!confirm(
				"This will erase WiFi credentials and reboot the board into setup mode. Continue?",
			)
		)
			return;
		try {
			await fetch(`${apiBase}/api/erase-wifi`, {
				method: "POST",
				body: JSON.stringify({ board_id: boardId }),
			});
			addLog("warning", "Setup mode triggered (WiFi erased)");
		} catch (err) {
			addLog("error", `Setup mode failed: ${err}`);
		}
	};

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

	// Filter images
	let filteredImages = images;
	if (filterDate !== "all")
		filteredImages = filteredImages.filter((img) => img.date === filterDate);
	if (searchTaskId.trim())
		filteredImages = filteredImages.filter(
			(img) => String(img.taskId) === searchTaskId.trim(),
		);
	filteredImages = [...filteredImages].sort((a, b) =>
		sortOrder === "newest"
			? b.timestamp - a.timestamp
			: a.timestamp - b.timestamp,
	);

	return (
		<div className="app-container split-layout">
			{/* Header */}
			<header className="header full-width">
				<div className="header-title-container">
					<Link href="/" className="btn-back">
						&larr; Fleet
					</Link>
					<div>
						<h1 className="header-title">STM32 B-U585I-IOT02A</h1>
						<div className="header-subtitle">{boardId}</div>
					</div>
				</div>
				<div className="connection-badge">
					<div
						className={`connection-dot ${connectionStatus === "connected" ? "connected" : "disconnected"}`}
					/>
					{connectionStatus === "connected" ? "MQTT Connected" : "Disconnected"}
				</div>
			</header>

			{/* Sidebar */}
			<aside className="sidebar">
				<div className="board-card">
					{/* Telemetry */}
					<div className="board-header">
						<div className="board-name-group">
							<div className="board-icon">
								<svg
									width="16"
									height="16"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									strokeWidth="2"
									style={{ color: "var(--accent)" }}
									aria-hidden="true"
								>
									<path d="M22 12h-4l-3 9L9 3l-3 9H2" />
								</svg>
							</div>
							<span style={{ fontWeight: 600, fontSize: "0.9rem" }}>
								Telemetry
							</span>
						</div>
						<div
							className={`status-indicator ${board.isOnline ? "online" : "offline"}`}
						>
							<div className="dot" />
							{board.isOnline ? "Online" : "Offline"}
						</div>
					</div>

					<div className="telemetry-box">
						<div className="telemetry-row">
							<span>State</span>
							<span className={`telemetry-val ${getStatusClass(board.status)}`}>
								{board.status}
							</span>
						</div>
						<div className="telemetry-row">
							<span>Firmware</span>
							<span className="telemetry-val">
								{board.firmware ? `v${board.firmware}` : "\u2014"}
							</span>
						</div>
						<div className="telemetry-row">
							<span>Captures</span>
							<span className="telemetry-val highlight">{board.captures}</span>
						</div>
						<div className="telemetry-row">
							<span>Payload</span>
							<span className="telemetry-val">
								{board.lastImageSize
									? `${(board.lastImageSize / 1024).toFixed(1)} KB`
									: "\u2014"}
							</span>
						</div>
					</div>

					{/* Actions */}
					<div className="board-actions column-actions">
						<button
							className="btn btn-primary"
							onClick={capturePicture}
							disabled={!board.isOnline}
						>
							Capture Picture
						</button>
						<button
							className="btn btn-secondary"
							onClick={pingBoard}
							disabled={!board.isOnline}
						>
							Ping Node
						</button>
						<button
							className="btn btn-danger"
							onClick={triggerSetupMode}
							disabled={!board.isOnline}
						>
							Setup Mode
						</button>
					</div>

					{/* Agent Chat */}
					<AgentChat boardId={boardId} apiBase={apiBase} />

					{/* Console */}
					<div className="terminal-window">
						<div className="terminal-header">
							<span>Console</span>
							<button
								className="btn-text"
								onClick={() => setBoard((prev) => ({ ...prev, logs: [] }))}
							>
								Clear
							</button>
						</div>
						{board.logs.length === 0 ? (
							<div className="terminal-empty">No telemetry received yet...</div>
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
			</aside>

			{/* Main Content */}
			<main className="main-content">
				<section className="images-section">
					<div className="gallery-header">
						<h2>Capture History</h2>
						<div className="filter-controls">
							<div className="filter-group">
								<label className="filter-label" htmlFor="filter-date">
									Date
								</label>
								<select
									id="filter-date"
									className="filter-select"
									value={filterDate}
									onChange={(e) => setFilterDate(e.target.value)}
								>
									<option value="all">All Dates</option>
									{[...new Set(images.map((img) => img.date))]
										.sort()
										.reverse()
										.map((date) => (
											<option key={date} value={date}>
												{date}
											</option>
										))}
								</select>
							</div>
							<div className="filter-group">
								<label className="filter-label" htmlFor="filter-sort">
									Sort
								</label>
								<select
									id="filter-sort"
									className="filter-select"
									value={sortOrder}
									onChange={(e) =>
										setSortOrder(e.target.value as "newest" | "oldest")
									}
								>
									<option value="newest">Newest First</option>
									<option value="oldest">Oldest First</option>
								</select>
							</div>
							<div className="filter-group">
								<label className="filter-label" htmlFor="filter-task">
									Task ID
								</label>
								<input
									id="filter-task"
									type="text"
									className="filter-input"
									placeholder="e.g. 5"
									value={searchTaskId}
									onChange={(e) => setSearchTaskId(e.target.value)}
								/>
							</div>
						</div>
					</div>

					<div className="gallery-grid">
						{filteredImages.length === 0 ? (
							<div className="empty-state" style={{ gridColumn: "1 / -1" }}>
								{images.length === 0
									? "No captures received yet."
									: "No captures match the current filters."}
							</div>
						) : (
							filteredImages.map((img) => (
								<div
									key={img.filename}
									className="image-card"
									onClick={() => setSelectedImage(img)}
								>
									{img.isNew && <div className="badge-new">NEW</div>}
									{img.analysis && (
										<div
											className={`analysis-indicator ${img.analysis.objectiveMet ? "met" : "unmet"}`}
											title={
												img.analysis.objectiveMet
													? "Objective met"
													: "Objective not met"
											}
										/>
									)}
									<div className="image-wrapper">
										<img
											src={img.url}
											alt={`Capture ${img.taskId}`}
											loading="lazy"
										/>
									</div>
									<div className="image-meta">
										<span>Task #{img.taskId}</span>
										<span className="image-time">
											{new Date(img.timestamp * 1000).toLocaleTimeString()}
										</span>
									</div>
									<button
										className="btn-delete"
										onClick={(e) => {
											e.stopPropagation();
											deleteImage(img);
										}}
										title="Delete"
									>
										&times;
									</button>
								</div>
							))
						)}
					</div>
				</section>
			</main>

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
