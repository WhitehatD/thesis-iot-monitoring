"use client";

import mqtt from "mqtt";
import { useCallback, useEffect, useRef, useState } from "react";

const MQTT_TOPIC_IMAGES = "dashboard/images/new";
const MQTT_TOPIC_STATUS = "device/stm32/status";

/**
 * Custom hook: connects to Mosquitto via MQTT-over-WebSocket,
 * fetches existing images from the REST API, and listens for
 * real-time push notifications when new images arrive.
 */
export function useMqttImages() {
	const [images, setImages] = useState([]);
	const [status, setStatus] = useState("disconnected"); // connected | disconnected | connecting
	const [jobState, setJobState] = useState({
		isActive: false,
		step: "idle",
		taskId: null,
		error: null,
		logs: [],
	}); // stepper state
	const [deviceStatus, setDeviceStatus] = useState(null); // legacy/fallback
	const jobTimeoutRef = useRef(null);
	const [isBoardOnline, setIsBoardOnline] = useState(false);
	const [toasts, setToasts] = useState([]);
	const clientRef = useRef(null);

	// ── Persistent Board Telemetry ──────────────────────────
	const [boardTelemetry, setBoardTelemetry] = useState({
		firmware: null,
		lastSeen: null,
		lastEvent: null,
		captureStats: {
			count: 0,
			lastLatencyMs: null,
			lastSizeBytes: null,
			lastTrigger: null,
		},
		uptimeStart: null,
	});
	const boardTimeoutRef = useRef(null);

	const mqttUrl =
		typeof window !== "undefined"
			? process.env.NEXT_PUBLIC_MQTT_WS_URL ||
				`ws://${window.location.hostname}:9001`
			: "ws://localhost:9001";

	const apiBase =
		typeof window !== "undefined"
			? process.env.NEXT_PUBLIC_API_URL ||
				`http://${window.location.hostname}:8000`
			: "http://localhost:8000";

	// Fetch existing images from REST API
	const fetchImages = useCallback(async () => {
		try {
			const res = await fetch(`${apiBase}/api/images`);
			if (res.ok) {
				const data = await res.json();
				setImages(
					data.images.map((img) => ({
						...img,
						url: `${apiBase}${img.url}`,
						isNew: false,
					})),
				);
			}
		} catch (err) {
			console.error("Failed to fetch images:", err);
		}
	}, [apiBase]);

	// Add a toast notification
	const addToast = useCallback((message) => {
		const id = Date.now();
		setToasts((prev) => [...prev, { id, message }]);
		setTimeout(() => {
			setToasts((prev) => prev.filter((t) => t.id !== id));
		}, 4000);
	}, []);

	// Force jobState to "sending" immediately
	const startManualCapture = useCallback(() => {
		setJobState({
			isActive: true,
			step: "sending",
			taskId: null,
			error: null,
			logs: [
				`[${new Date().toLocaleTimeString()}] 🚀 Sending manual capture command...`,
			],
		});
		if (jobTimeoutRef.current) clearTimeout(jobTimeoutRef.current);
		jobTimeoutRef.current = setTimeout(() => {
			setJobState((prev) =>
				prev.step === "sending" ? { ...prev, isActive: false } : prev,
			);
		}, 15000); // 15s timeout if board doesn't respond
	}, []);

	useEffect(() => {
		// Load existing images
		// eslint-disable-next-line react-hooks/set-state-in-effect
		fetchImages();

		// Connect to MQTT broker via WebSocket
		setStatus("connecting");
		const client = mqtt.connect(mqttUrl, {
			reconnectPeriod: 3000,
			connectTimeout: 10000,
		});
		clientRef.current = client;

		client.on("connect", () => {
			setStatus("connected");
			client.subscribe(MQTT_TOPIC_IMAGES, { qos: 0 });
			client.subscribe(MQTT_TOPIC_STATUS, { qos: 0 });
			console.log(
				"✓ MQTT connected, subscribed to",
				MQTT_TOPIC_IMAGES,
				"and",
				MQTT_TOPIC_STATUS,
			);
		});

		client.on("message", (topic, payload) => {
			try {
				const data = JSON.parse(payload.toString());

				if (topic === MQTT_TOPIC_STATUS) {
					// ANY message from the board proves it is online
					setIsBoardOnline(true);
					if (boardTimeoutRef.current) clearTimeout(boardTimeoutRef.current);
					// Board pings every 30s, timeout after 40s
					boardTimeoutRef.current = setTimeout(
						() => setIsBoardOnline(false),
						40000,
					);

					// ── Accumulate persistent board telemetry ──
					setBoardTelemetry((prev) => {
						const update = {
							...prev,
							lastSeen: Date.now(),
							lastEvent: data.status,
						};

						// Extract firmware version from online pings
						if (data.firmware) {
							update.firmware = data.firmware;
							if (!prev.uptimeStart) update.uptimeStart = Date.now();
						}

						// Extract capture performance on completion
						if (data.status === "captured" || data.status === "uploaded") {
							update.captureStats = {
								count: prev.captureStats.count + 1,
								lastLatencyMs:
									data.latency_ms ?? prev.captureStats.lastLatencyMs,
								lastSizeBytes:
									data.size ?? data.bytes ?? prev.captureStats.lastSizeBytes,
								lastTrigger: data.trigger ?? prev.captureStats.lastTrigger,
							};
						}

						return update;
					});

					if (data.status === "online") {
						return; // don't show generic online pings in the banner/stepper
					}

					// Determine job stepper state
					if (data.status === "schedule_cleared") {
						setJobState({
							isActive: false,
							step: "idle",
							taskId: null,
							error: null,
							logs: [],
						});
					} else if (data.status === "error") {
						const errorMsg = `[${new Date().toLocaleTimeString()}] 🚨 Error: ${data.reason}`;
						setJobState((prev) => ({
							...prev,
							isActive: true,
							step: "error",
							error: data.reason,
							logs: [...(prev.logs || []), errorMsg],
						}));
						if (jobTimeoutRef.current) clearTimeout(jobTimeoutRef.current);
						jobTimeoutRef.current = setTimeout(
							() => setJobState((prev) => ({ ...prev, isActive: false })),
							8000,
						);
					} else {
						let step = "idle";
						let otaProgress = null;

						/* ── OTA-specific status mapping ── */
						if (
							data.status === "ota_update_queued" ||
							data.status === "ota_checking"
						)
							step = "ota_checking";
						else if (data.status === "ota_downloading")
							step = "ota_downloading";
						else if (data.status === "ota_progress") {
							step = "ota_downloading";
							otaProgress = {
								downloaded: data.downloaded,
								total: data.total,
								percent: data.percent,
								throughputKbps: data.throughput_kbps,
								elapsedMs: data.elapsed_ms,
								attempt: data.attempt,
							};
						} else if (data.status === "ota_rebooting") step = "ota_rebooting";
						else if (data.status === "ota_up_to_date") step = "ota_up_to_date";
						else if (data.status === "ota_error") {
							step = "error";
						} else if (
							/* ── Capture lifecycle status mapping ── */
							data.status === "schedule_received" ||
							data.status === "job_received"
						)
							step = "received";
						else if (
							data.status === "executing" ||
							data.status === "camera_init" ||
							data.status === "camera_reinit"
						)
							step = "camera_init";
						else if (
							data.status === "capturing" ||
							data.status === "capture_retry"
						)
							step = "capturing";
						else if (data.status === "uploading") step = "uploading";
						else if (
							data.status === "uploaded" ||
							data.status === "complete" ||
							data.status === "captured"
						)
							step = "finished";
						else if (data.status === "capture_failed") step = "error";

						if (step !== "idle") {
							const isOta = step.startsWith("ota_");
							const newLog = isOta
								? `[${new Date().toLocaleTimeString()}] 🔄 OTA: ${data.status}${data.percent != null ? ` (${data.percent}%)` : ""}${data.throughput_kbps != null ? ` @ ${data.throughput_kbps} KB/s` : ""}`
								: `[${new Date().toLocaleTimeString()}] ⚡ Status changed to: ${data.status}`;
							setJobState((prev) => {
								const prevLogs =
									(!prev.isActive && step !== "finished") ||
									prev.step === "error"
										? []
										: prev.logs || [];
								// Track step timestamps for per-step timing
								const isNewJob = !prev.isActive && step !== "finished";
								const prevTimestamps = isNewJob
									? {}
									: prev.stepTimestamps || {};
								const stepTimestamps = { ...prevTimestamps };
								if (!stepTimestamps[step]) stepTimestamps[step] = Date.now();
								return {
									isActive: true,
									step,
									taskId: data.task_id || data.tasks || prev.taskId || null,
									error:
										data.status === "ota_error"
											? data.reason || "OTA update failed"
											: null,
									logs: [...prevLogs, newLog],
									otaProgress: otaProgress || prev.otaProgress || null,
									stepTimestamps,
								};
							});
							if (jobTimeoutRef.current) clearTimeout(jobTimeoutRef.current);

							const timeout =
								step === "finished"
									? 4000
									: step === "ota_rebooting"
										? 15000
										: step === "ota_up_to_date"
											? 5000
											: 30000;
							jobTimeoutRef.current = setTimeout(() => {
								setJobState((prev) => ({ ...prev, isActive: false }));
							}, timeout);
						}
					}

					// Legacy status auto-clear (keep for backward compatibility if needed)
					setDeviceStatus({ ...data, receivedAt: Date.now() });
					setTimeout(() => {
						setDeviceStatus((prev) =>
							prev && Date.now() - prev.receivedAt > 14000 ? null : prev,
						);
					}, 15000);
					return;
				}

				// Image notification
				const newImage = {
					...data,
					url: `${apiBase}${data.url}`,
					isNew: true,
				};
				setImages((prev) => [newImage, ...prev]);
				addToast(`📸 New capture: Task #${data.task_id}`);

				// We don't forcefully clear jobState here, it will auto-clear via timeout
				// because the board also sends 'uploaded' or 'complete' which sets step='finished'.
				// If it was stuck, the new image at least shows up.

				// Remove "new" flag after animation completes
				setTimeout(() => {
					setImages((prev) =>
						prev.map((img) =>
							img.timestamp === data.timestamp ? { ...img, isNew: false } : img,
						),
					);
				}, 3000);
			} catch (err) {
				console.error("Failed to parse MQTT message:", err);
			}
		});

		client.on("reconnect", () => {
			setStatus("connecting");
		});

		client.on("close", () => {
			setStatus("disconnected");
		});

		client.on("error", (err) => {
			console.error("MQTT error:", err);
			setStatus("disconnected");
		});

		return () => {
			client.end(true);
		};
	}, [mqttUrl, apiBase, fetchImages, addToast]);

	return {
		images,
		status,
		jobState,
		deviceStatus,
		isBoardOnline,
		toasts,
		startManualCapture,
		boardTelemetry,
	};
}
