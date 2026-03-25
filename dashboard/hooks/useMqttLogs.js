"use client";

import mqtt from "mqtt";
import { useCallback, useEffect, useRef, useState } from "react";

const MQTT_TOPIC_LOGS = "dashboard/logs";
const MQTT_TOPIC_STATE = "dashboard/state";

export function useMqttLogs(maxLogs = 200) {
	const [logs, setLogs] = useState([]);
	const [boardState, setBoardState] = useState(null);
	const clientRef = useRef(null);

	const mqttUrl =
		typeof window !== "undefined"
			? process.env.NEXT_PUBLIC_MQTT_WS_URL ||
				`ws://${window.location.hostname}:9001`
			: "ws://localhost:9001";

	useEffect(() => {
		const client = mqtt.connect(mqttUrl, {
			reconnectPeriod: 3000,
			connectTimeout: 10000,
		});
		clientRef.current = client;

		client.on("connect", () => {
			client.subscribe(MQTT_TOPIC_LOGS, { qos: 0 });
			client.subscribe(MQTT_TOPIC_STATE, { qos: 0 });
			console.log("✓ MQTT connected, subscribed to logs");
		});

		client.on("message", (topic, payload) => {
			try {
				const data = JSON.parse(payload.toString());

				if (topic === MQTT_TOPIC_LOGS) {
					setLogs((prev) => {
						const newLogs = [...prev, data];
						if (newLogs.length > maxLogs) {
							return newLogs.slice(newLogs.length - maxLogs);
						}
						return newLogs;
					});
				} else if (topic === MQTT_TOPIC_STATE) {
					setBoardState((prev) => ({ ...prev, ...data }));
				}
			} catch (err) {
				// Non-JSON or broken payload
			}
		});

		return () => {
			client.end(true);
		};
	}, [mqttUrl, maxLogs]);

	const clearLogs = useCallback(() => setLogs([]), []);

	return { logs, boardState, clearLogs };
}
