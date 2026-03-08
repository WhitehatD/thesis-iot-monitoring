"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import mqtt from "mqtt";

const MQTT_TOPIC = "dashboard/images/new";

/**
 * Custom hook: connects to Mosquitto via MQTT-over-WebSocket,
 * fetches existing images from the REST API, and listens for
 * real-time push notifications when new images arrive.
 */
export function useMqttImages() {
    const [images, setImages] = useState([]);
    const [status, setStatus] = useState("disconnected"); // connected | disconnected | connecting
    const [toasts, setToasts] = useState([]);
    const clientRef = useRef(null);

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
            client.subscribe(MQTT_TOPIC, { qos: 0 });
            console.log("✓ MQTT connected, subscribed to", MQTT_TOPIC);
        });

        client.on("message", (_topic, payload) => {
            try {
                const meta = JSON.parse(payload.toString());
                const newImage = {
                    ...meta,
                    url: `${apiBase}${meta.url}`,
                    isNew: true,
                };
                setImages((prev) => [newImage, ...prev]);
                addToast(`📸 New capture: Task #${meta.task_id}`);

                // Remove "new" flag after animation completes
                setTimeout(() => {
                    setImages((prev) =>
                        prev.map((img) =>
                            img.timestamp === meta.timestamp ? { ...img, isNew: false } : img
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

    return { images, status, toasts };
}
