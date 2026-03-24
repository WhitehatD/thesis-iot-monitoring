"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import mqtt from "mqtt";

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
    const [jobState, setJobState] = useState({ isActive: false, step: "idle", taskId: null, error: null }); // stepper state
    const [deviceStatus, setDeviceStatus] = useState(null); // legacy/fallback
    const jobTimeoutRef = useRef(null);
    const [isBoardOnline, setIsBoardOnline] = useState(false);
    const [toasts, setToasts] = useState([]);
    const clientRef = useRef(null);
    const boardTimeoutRef = useRef(null);

    const mqttUrl =
        typeof window !== "undefined"
            ? process.env.NEXT_PUBLIC_MQTT_WS_URL || `ws://${window.location.hostname}:9001`
            : "ws://localhost:9001";

    const apiBase =
        typeof window !== "undefined"
            ? process.env.NEXT_PUBLIC_API_URL || `http://${window.location.hostname}:8000`
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
                    }))
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
            console.log("✓ MQTT connected, subscribed to", MQTT_TOPIC_IMAGES, "and", MQTT_TOPIC_STATUS);
        });

        client.on("message", (topic, payload) => {
            try {
                const data = JSON.parse(payload.toString());

                if (topic === MQTT_TOPIC_STATUS) {
                    // ANY message from the board proves it is online
                    setIsBoardOnline(true);
                    if (boardTimeoutRef.current) clearTimeout(boardTimeoutRef.current);
                    // Board pings every 30s, timeout after 40s
                    boardTimeoutRef.current = setTimeout(() => setIsBoardOnline(false), 40000);

                    if (data.status === "online") {
                        return; // don't show generic online pings in the banner/stepper
                    }

                    // Determine job stepper state
                    if (data.status === "schedule_cleared") {
                        setJobState({ isActive: false, step: "idle", taskId: null, error: null });
                    } else if (data.status === "error") {
                        setJobState(prev => ({ ...prev, isActive: true, step: "error", error: data.reason }));
                        if (jobTimeoutRef.current) clearTimeout(jobTimeoutRef.current);
                        jobTimeoutRef.current = setTimeout(() => setJobState(prev => ({ ...prev, isActive: false })), 8000);
                    } else {
                        let step = "idle";
                        if (data.status === "schedule_received") step = "received";
                        else if (data.status === "executing" || data.status === "capturing") step = "capturing";
                        else if (data.status === "uploading") step = "uploading";
                        else if (data.status === "uploaded" || data.status === "complete" || data.status === "captured") step = "finished";
                        
                        if (step !== "idle") {
                            setJobState({ isActive: true, step, taskId: data.task_id || data.tasks || null, error: null });
                            if (jobTimeoutRef.current) clearTimeout(jobTimeoutRef.current);
                            
                            // Auto-clear after 10s of inactivity if not finished
                            // If finished, clear after 4s
                            const timeout = step === "finished" ? 4000 : 10000;
                            jobTimeoutRef.current = setTimeout(() => {
                                setJobState(prev => ({ ...prev, isActive: false }));
                            }, timeout);
                        }
                    }

                    // Legacy status auto-clear (keep for backward compatibility if needed)
                    setDeviceStatus({ ...data, receivedAt: Date.now() });
                    setTimeout(() => {
                        setDeviceStatus((prev) =>
                            prev && Date.now() - prev.receivedAt > 14000 ? null : prev
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
                            img.timestamp === data.timestamp ? { ...img, isNew: false } : img
                        )
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

    return { images, status, jobState, deviceStatus, isBoardOnline, toasts };
}
