"use client";

import { useEffect, useRef } from "react";
import { useMqttLogs } from "@/hooks/useMqttLogs";

export default function LogTerminal() {
	const { logs, boardState, clearLogs } = useMqttLogs(300);
	const endRef = useRef(null);

	// Auto-scroll to bottom
	// biome-ignore lint/correctness/useExhaustiveDependencies: auto-scroll on logs
	useEffect(() => {
		if (endRef.current) {
			endRef.current.scrollIntoView({ behavior: "smooth" });
		}
	}, [logs]);

	const formatTime = (ts) => {
		const date = new Date(ts * 1000);
		return `${date.getHours().toString().padStart(2, "0")}:${date
			.getMinutes()
			.toString()
			.padStart(2, "0")}:${date.getSeconds().toString().padStart(2, "0")}.${date
			.getMilliseconds()
			.toString()
			.padStart(3, "0")}`;
	};

	return (
		<div className="log-terminal-container">
			<div className="log-terminal-header">
				<div className="log-terminal-title">
					<span className="terminal-icon">_&gt;</span>
					Live Firmware Logs{" "}
					{boardState?.phase ? `(Phase: ${boardState.phase})` : ""}
				</div>
				<button type="button" className="log-clear-btn" onClick={clearLogs}>
					Clear
				</button>
			</div>
			<div className="log-terminal-body">
				{logs.length === 0 ? (
					<div className="log-empty">
						Waiting for logs... (ensure monitor.py is running)
					</div>
				) : (
					logs.map((log, i) => (
						<div key={i} className={`log-line level-${log.level}`}>
							<span className="log-time">[{formatTime(log.timestamp)}]</span>
							<span className="log-text">{log.text}</span>
						</div>
					))
				)}
				<div ref={endRef} />
			</div>
		</div>
	);
}
