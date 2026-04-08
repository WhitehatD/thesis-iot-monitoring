"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface Step {
	id: string;
	label: string;
	status: "running" | "done" | "error";
	summary?: string;
}

interface Message {
	role: "user" | "assistant";
	content: string;
	steps?: Step[];
	streaming?: boolean;
}

interface AgentChatProps {
	boardId: string;
	apiBase: string;
}

const QUICK_ACTIONS = [
	"Take a picture now",
	"Monitor every 15 min",
	"What does the camera see?",
	"Board status?",
];

export default function AgentChat({ boardId, apiBase }: AgentChatProps) {
	const [messages, setMessages] = useState<Message[]>([]);
	const [input, setInput] = useState("");
	const [isStreaming, setIsStreaming] = useState(false);
	const [sessionId] = useState(
		() => `${Date.now()}-${Math.random().toString(36).slice(2)}`,
	);
	const messagesEndRef = useRef<HTMLDivElement>(null);
	const textareaRef = useRef<HTMLTextAreaElement>(null);

	const scrollToBottom = useCallback(() => {
		messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
	}, []);

	// biome-ignore lint/correctness/useExhaustiveDependencies: intentional scroll on message change
	useEffect(() => {
		scrollToBottom();
	}, [messages, scrollToBottom]);

	const handleSend = async () => {
		const msg = input.trim();
		if (!msg || isStreaming) return;

		setInput("");
		setIsStreaming(true);

		const userMsg: Message = { role: "user", content: msg };
		const botMsg: Message = {
			role: "assistant",
			content: "",
			steps: [],
			streaming: true,
		};
		setMessages((prev) => [...prev, userMsg, botMsg]);

		try {
			const res = await fetch(`${apiBase}/api/agent/chat`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ message: msg, sessionId }),
			});

			if (!res.ok || !res.body) {
				throw new Error(`Server error: ${res.status}`);
			}

			const reader = res.body.getReader();
			const decoder = new TextDecoder();
			let buffer = "";

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;

				buffer += decoder.decode(value, { stream: true });
				const lines = buffer.split("\n");
				buffer = lines.pop() || "";

				for (const line of lines) {
					if (!line.startsWith("data: ")) continue;
					const jsonStr = line.slice(6).trim();
					if (!jsonStr) continue;

					try {
						const data = JSON.parse(jsonStr);
						const event = data.event;

						setMessages((prev) => {
							const updated = [...prev];
							const bot = { ...updated[updated.length - 1] };
							const steps = [...(bot.steps || [])];

							if (event === "thinking") {
								bot.content = `*${data.text}*`;
							} else if (event === "tool_call") {
								steps.push({
									id: data.id,
									label: data.label,
									status: "running",
								});
								bot.steps = steps;
							} else if (event === "tool_result") {
								const idx = steps.findIndex((s) => s.id === data.id);
								if (idx >= 0) {
									steps[idx] = {
										...steps[idx],
										status: data.success ? "done" : "error",
										summary: data.summary,
									};
									bot.steps = steps;
								}
							} else if (event === "reply") {
								bot.content = data.text;
								bot.streaming = false;
							} else if (event === "error") {
								bot.content = `Error: ${data.text}`;
								bot.streaming = false;
							} else if (event === "done") {
								bot.streaming = false;
							}

							updated[updated.length - 1] = bot;
							return updated;
						});
					} catch {
						// skip malformed JSON
					}
				}
			}
		} catch (err) {
			setMessages((prev) => {
				const updated = [...prev];
				const bot = updated[updated.length - 1];
				if (bot) {
					updated[updated.length - 1] = {
						...bot,
						content: `Connection error: ${err}`,
						streaming: false,
					};
				}
				return updated;
			});
		} finally {
			setIsStreaming(false);
		}
	};

	const handleKeyDown = (e: React.KeyboardEvent) => {
		if (e.key === "Enter" && !e.shiftKey) {
			e.preventDefault();
			handleSend();
		}
	};

	return (
		<div className="agent-chat">
			<div className="agent-header">
				<div className="agent-icon">
					<svg
						width="16"
						height="16"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						strokeWidth="2"
						strokeLinecap="round"
						strokeLinejoin="round"
						style={{ color: "var(--accent)" }}
						aria-hidden="true"
					>
						<path d="M12 8V4H8" />
						<rect width="16" height="12" x="4" y="8" rx="2" />
						<path d="M2 14h2M20 14h2M15 13v2M9 13v2" />
					</svg>
				</div>
				<div>
					<div className="agent-title">Monitoring Agent</div>
					<div className="agent-subtitle">Natural language control</div>
				</div>
			</div>

			<div className="agent-messages">
				{messages.length === 0 && (
					<div className="agent-welcome">
						<p>What would you like to monitor?</p>
						<div className="agent-quick-actions">
							{QUICK_ACTIONS.map((qa) => (
								<button
									key={qa}
									className="agent-quick-btn"
									onClick={() => {
										setInput(qa);
										setTimeout(() => textareaRef.current?.focus(), 50);
									}}
								>
									{qa}
								</button>
							))}
						</div>
					</div>
				)}

				{messages.map((msg, i) => (
					<div key={i} className={`agent-msg agent-msg-${msg.role}`}>
						{msg.role === "user" ? (
							<div className="agent-bubble user-bubble">{msg.content}</div>
						) : (
							<div className="agent-bubble bot-bubble">
								{msg.steps && msg.steps.length > 0 && (
									<div className="agent-steps">
										{msg.steps.map((step) => (
											<div
												key={step.id}
												className={`agent-step step-${step.status}`}
											>
												<span className="step-icon">
													{step.status === "running"
														? "\u23F3"
														: step.status === "done"
															? "\u2705"
															: "\u274C"}
												</span>
												<span className="step-text">
													{step.summary || step.label}
												</span>
											</div>
										))}
									</div>
								)}
								{msg.content && <MarkdownContent text={msg.content} />}
								{msg.streaming && !msg.content && (
									<div className="agent-typing">
										<span className="typing-dot" />
										<span className="typing-dot" />
										<span className="typing-dot" />
									</div>
								)}
							</div>
						)}
					</div>
				))}
				<div ref={messagesEndRef} />
			</div>

			<div className="agent-input-area">
				<textarea
					ref={textareaRef}
					className="agent-textarea"
					placeholder="Ask the agent..."
					value={input}
					onChange={(e) => setInput(e.target.value)}
					onKeyDown={handleKeyDown}
					rows={1}
					disabled={isStreaming}
				/>
				<button
					className="agent-send-btn"
					onClick={handleSend}
					disabled={isStreaming || !input.trim()}
				>
					{isStreaming ? "\u23F3" : "\u2191"}
				</button>
			</div>
		</div>
	);
}

function MarkdownContent({ text }: { text: string }) {
	const parts = parseMarkdown(text);
	return <div className="agent-reply">{parts}</div>;
}

function parseMarkdown(text: string): React.ReactNode[] {
	const nodes: React.ReactNode[] = [];
	const lines = text.split("\n");
	let tableRows: string[][] = [];

	const flushTable = () => {
		if (tableRows.length === 0) return;
		const rows = tableRows.filter(
			(row) => !row.every((cell) => /^-+$/.test(cell.trim())),
		);
		nodes.push(
			<table key={`t-${nodes.length}`} className="agent-table">
				<tbody>
					{rows.map((row, ri) => (
						<tr key={ri}>
							{row.map((cell, ci) => (
								<td key={ci}>{inlineFormat(cell.trim())}</td>
							))}
						</tr>
					))}
				</tbody>
			</table>,
		);
		tableRows = [];
	};

	for (let i = 0; i < lines.length; i++) {
		const line = lines[i];

		if (line.startsWith("|") && line.endsWith("|")) {
			const cells = line
				.slice(1, -1)
				.split("|")
				.map((c) => c.trim());
			tableRows.push(cells);
			continue;
		}

		flushTable();

		if (line.trim() === "") {
			nodes.push(<br key={`br-${i}`} />);
		} else {
			nodes.push(
				<span key={`l-${i}`}>
					{inlineFormat(line)}
					{i < lines.length - 1 && <br />}
				</span>,
			);
		}
	}

	flushTable();
	return nodes;
}

function inlineFormat(text: string): React.ReactNode[] {
	const parts: React.ReactNode[] = [];
	const regex = /(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)/g;
	let lastIndex = 0;
	let match: RegExpExecArray | null = regex.exec(text);

	while (match !== null) {
		if (match.index > lastIndex) {
			parts.push(text.slice(lastIndex, match.index));
		}

		if (match[2]) {
			parts.push(<strong key={`b-${match.index}`}>{match[2]}</strong>);
		} else if (match[3]) {
			parts.push(<em key={`i-${match.index}`}>{match[3]}</em>);
		} else if (match[4]) {
			parts.push(<code key={`c-${match.index}`}>{match[4]}</code>);
		}

		lastIndex = regex.lastIndex;
		match = regex.exec(text);
	}

	if (lastIndex < text.length) {
		parts.push(text.slice(lastIndex));
	}

	return parts.length > 0 ? parts : [text];
}
