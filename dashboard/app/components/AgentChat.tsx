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

export default function AgentChat({ boardId, apiBase }: AgentChatProps) {
	const [messages, setMessages] = useState<Message[]>([]);
	const [input, setInput] = useState("");
	const [isStreaming, setIsStreaming] = useState(false);
	const [sessionId] = useState(
		() =>
			`${Date.now()}-${Math.random().toString(36).slice(2)}`,
	);
	const messagesEndRef = useRef<HTMLDivElement>(null);
	const textareaRef = useRef<HTMLTextAreaElement>(null);

	const scrollToBottom = useCallback(() => {
		messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
	}, []);

	// biome-ignore lint/correctness/useExhaustiveDependencies: scroll on every message change is intentional
	useEffect(() => {
		scrollToBottom();
	}, [messages, scrollToBottom]);

	const handleSend = async () => {
		const msg = input.trim();
		if (!msg || isStreaming) return;

		setInput("");
		setIsStreaming(true);

		// Add user message
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

				// Parse SSE lines from buffer
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
						// Skip malformed JSON
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

	const quickActions = [
		"Take a picture now",
		"Monitor every 15 min from 9AM to 5PM",
		"What does the latest image show?",
		"Is the board online?",
	];

	return (
		<div className="agent-chat">
			<div className="agent-header">
				<div className="agent-icon">&#x1F9E0;</div>
				<div>
					<div className="agent-title">Monitoring Agent</div>
					<div className="agent-subtitle">
						Natural language control &amp; analysis
					</div>
				</div>
			</div>

			<div className="agent-messages">
				{messages.length === 0 && (
					<div className="agent-welcome">
						<p>What would you like to monitor?</p>
						<div className="agent-quick-actions">
							{quickActions.map((qa) => (
								<button
									key={qa}
									className="agent-quick-btn"
									onClick={() => {
										setInput(qa);
										setTimeout(() => {
											textareaRef.current?.focus();
										}, 50);
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
								{msg.content && (
									<div
										className="agent-reply"
										// biome-ignore lint/security/noDangerouslySetInnerHtml: controlled markdown rendering from our own renderMarkdown
										dangerouslySetInnerHTML={{
											__html: renderMarkdown(msg.content),
										}}
									/>
								)}
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
					placeholder="Describe what you want to monitor..."
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

/** Minimal markdown → HTML for agent replies. */
function renderMarkdown(text: string): string {
	return text
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
		.replace(/\*(.+?)\*/g, "<em>$1</em>")
		.replace(/`(.+?)`/g, "<code>$1</code>")
		.replace(
			/\|(.+)\|/g,
			(_, row) =>
				`<tr>${row
					.split("|")
					.map((c: string) => `<td>${c.trim()}</td>`)
					.join("")}</tr>`,
		)
		.replace(/(<tr>.*<\/tr>(\n|$))+/g, (block: string) => {
			const rows = block.trim().split("\n");
			// Skip separator rows (|---|---|)
			const filtered = rows.filter(
				(r) => !r.match(/^<tr>(<td>-+<\/td>)+<\/tr>$/),
			);
			return `<table class="agent-table">${filtered.join("\n")}</table>`;
		})
		.replace(/\n/g, "<br>");
}
