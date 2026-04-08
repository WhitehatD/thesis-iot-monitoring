"use client";

import mqtt from "mqtt";
import { useEffect, useRef, useState } from "react";

export interface BoardTelemetry {
	id: string;
	name: string;
	firmware: string | null;
	lastSeen: number | null;
	status: string;
	captures: number;
	lastImageSize: number | null;
	lastLatencyMs: number | null;
	isOnline: boolean;
}

type MessageHandler = (
	topic: string,
	data: Record<string, any>,
	boardId: string,
) => void;

const OFFLINE_TIMEOUT_MS = 15_000;

function getMqttUrl(): string {
	if (typeof window === "undefined") return "ws://localhost:9001";
	return (
		process.env.NEXT_PUBLIC_MQTT_WS_URL ||
		`${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/mqtt`
	);
}

function extractBoardId(topic: string, data: Record<string, any>): string {
	let boardId = "stm32-iot-cam-01";
	if (topic.startsWith("device/")) {
		const parts = topic.split("/");
		if (parts.length >= 3 && parts[1] !== "stm32") {
			boardId = parts[1];
		}
	}
	if (data.client_id || data.board_id) {
		boardId = data.client_id || data.board_id;
	}
	return boardId;
}

export function useMQTT(topics: string[], onMessage?: MessageHandler) {
	const [connectionStatus, setConnectionStatus] = useState<
		"connecting" | "connected" | "disconnected" | "error"
	>("connecting");
	const clientRef = useRef<mqtt.MqttClient | null>(null);
	const onMessageRef = useRef(onMessage);
	onMessageRef.current = onMessage;
	const topicsRef = useRef(topics);
	topicsRef.current = topics;

	// Stable key for reconnection — only reconnect if topic list actually changes
	const topicKey = topics.join(",");

	// biome-ignore lint/correctness/useExhaustiveDependencies: reconnect controlled by topicKey, topics accessed via ref
	useEffect(() => {
		const client = mqtt.connect(getMqttUrl(), { reconnectPeriod: 3000 });
		clientRef.current = client;

		client.on("connect", () => {
			setConnectionStatus("connected");
			for (const t of topicsRef.current) {
				client.subscribe(t, { qos: 0 });
			}
		});

		client.on("message", (topic, payload) => {
			try {
				const data = JSON.parse(payload.toString());
				const boardId = extractBoardId(topic, data);
				onMessageRef.current?.(topic, data, boardId);
			} catch {
				// skip malformed messages
			}
		});

		client.on("close", () => setConnectionStatus("disconnected"));
		client.on("error", () => setConnectionStatus("error"));

		return () => {
			client.end();
		};
	}, [topicKey]);

	return { connectionStatus, client: clientRef };
}

export function useBoardTracker(topics: string[]) {
	const [boards, setBoards] = useState<Record<string, BoardTelemetry>>({});

	const handleMessage = (
		topic: string,
		data: Record<string, any>,
		boardId: string,
	) => {
		setBoards((prev) => {
			const curr = prev[boardId] || {
				id: boardId,
				name: "STM32 B-U585I-IOT02A",
				firmware: null,
				lastSeen: null,
				status: "idle",
				captures: 0,
				lastImageSize: null,
				lastLatencyMs: null,
				isOnline: true,
			};

			const update = { ...curr, isOnline: true, lastSeen: Date.now() };
			if (data.firmware) update.firmware = data.firmware;
			if (data.status) update.status = data.status;
			if (data.status === "captured" || data.status === "uploaded") {
				update.captures += 1;
				if (data.size) update.lastImageSize = data.size;
				if (data.latency_ms) update.lastLatencyMs = data.latency_ms;
			}

			return { ...prev, [boardId]: update };
		});
	};

	const { connectionStatus } = useMQTT(topics, handleMessage);

	// Mark boards offline after timeout
	useEffect(() => {
		const interval = setInterval(() => {
			setBoards((prev) => {
				let changed = false;
				const next = { ...prev };
				const now = Date.now();
				for (const id in next) {
					if (
						next[id].isOnline &&
						next[id].lastSeen &&
						now - next[id].lastSeen! > OFFLINE_TIMEOUT_MS
					) {
						next[id] = { ...next[id], isOnline: false };
						changed = true;
					}
				}
				return changed ? next : prev;
			});
		}, 5000);
		return () => clearInterval(interval);
	}, []);

	return { boards, connectionStatus };
}
