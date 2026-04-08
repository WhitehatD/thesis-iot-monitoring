"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/* ── Block-based message model ─────────────────────────────
   Every SSE event becomes a Block. Blocks render in order,
   giving the Claude-Code-like chained feel. Nothing is
   overwritten — each event adds or updates a block.
*/

type Block =
	| { type: "thinking"; text: string }
	| {
			type: "step";
			id: string;
			label: string;
			status: "running" | "done" | "error";
			summary?: string;
	  }
	| { type: "text"; text: string }
	| { type: "error"; text: string };

interface Message {
	role: "user" | "assistant";
	text?: string; // user messages
	blocks: Block[]; // assistant messages
	streaming?: boolean;
}

interface AgentChatProps {
	boardId: string;
	apiBase: string;
	fullSize?: boolean;
}

const QUICK_ACTIONS = [
	"Take a picture now",
	"Monitor every 15 min",
	"What does the camera see?",
	"Board status?",
];

export default function AgentChat({
	boardId,
	apiBase,
	fullSize,
}: AgentChatProps) {
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

		const userMsg: Message = { role: "user", text: msg, blocks: [] };
		const botMsg: Message = {
			role: "assistant",
			blocks: [],
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
							const bot = {
								...updated[updated.length - 1],
								blocks: [...(updated[updated.length - 1].blocks || [])],
							};

							if (event === "thinking") {
								// Replace existing thinking block or add new one
								const thinkIdx = bot.blocks.findIndex(
									(b) => b.type === "thinking",
								);
								if (thinkIdx >= 0) {
									bot.blocks[thinkIdx] = {
										type: "thinking",
										text: data.text,
									};
								} else {
									bot.blocks.push({
										type: "thinking",
										text: data.text,
									});
								}
							} else if (event === "tool_call") {
								bot.blocks.push({
									type: "step",
									id: data.id,
									label: data.label,
									status: "running",
								});
							} else if (event === "tool_result") {
								// Find the step block and update it
								const idx = bot.blocks.findIndex(
									(b) =>
										b.type === "step" &&
										b.id === data.id &&
										b.status === "running",
								);
								if (idx >= 0) {
									bot.blocks[idx] = {
										...(bot.blocks[idx] as Extract<Block, { type: "step" }>),
										status: data.success ? "done" : "error",
										summary: data.summary,
									};
								}
							} else if (event === "reply") {
								bot.blocks.push({
									type: "text",
									text: data.text,
								});
							} else if (event === "error") {
								bot.blocks.push({
									type: "error",
									text: data.text,
								});
								bot.streaming = false;
							} else if (event === "done") {
								bot.streaming = false;
								// Remove thinking block once done
								bot.blocks = bot.blocks.filter((b) => b.type !== "thinking");
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
						blocks: [
							...bot.blocks,
							{
								type: "error",
								text: `Connection error: ${err}`,
							},
						],
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
		<div className={`agent-chat ${fullSize ? "agent-chat-full" : ""}`}>
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
							<div className="agent-bubble user-bubble">{msg.text}</div>
						) : (
							<div className="agent-bubble bot-bubble">
								{msg.blocks.map((block, bi) => (
									<BlockRenderer key={`${i}-${bi}`} block={block} />
								))}
								{msg.streaming && msg.blocks.length === 0 && (
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

/* ── Block Renderer ─────────────────────────────────────── */

function BlockRenderer({ block }: { block: Block }) {
	if (block.type === "thinking") {
		return (
			<div className="block-thinking">
				<span className="thinking-icon">&bull;</span>
				<span className="thinking-text">{block.text}</span>
			</div>
		);
	}

	if (block.type === "step") {
		return (
			<div className={`block-step step-${block.status}`}>
				<span className="step-icon">
					{block.status === "running"
						? "\u23F3"
						: block.status === "done"
							? "\u2705"
							: "\u274C"}
				</span>
				<div className="step-content">
					<span className="step-label">
						{block.status === "running"
							? block.label
							: block.summary || block.label}
					</span>
					{block.status === "done" &&
						block.summary &&
						block.summary !== block.label && (
							<span className="step-detail">{block.label}</span>
						)}
				</div>
			</div>
		);
	}

	if (block.type === "error") {
		return (
			<div className="block-error">
				<MarkdownContent text={block.text} />
			</div>
		);
	}

	// type === "text"
	return (
		<div className="block-text">
			<MarkdownContent text={block.text} />
		</div>
	);
}

/* ── Markdown Renderer ──────────────────────────────────── */

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
