"use client";

import { useCallback, useEffect, useState } from "react";
import ScheduleCard from "./ScheduleCard";

/**
 * Full scheduler panel: create schedules + list existing ones.
 */
export default function SchedulerPanel({ deviceStatus }) {
	const [schedules, setSchedules] = useState([]);
	const [showForm, setShowForm] = useState(false);
	const [loading, setLoading] = useState(true);
	const [submitting, setSubmitting] = useState(false);
	const [sleepEnabled, setSleepEnabled] = useState(false);
	const [togglingSleep, setTogglingSleep] = useState(false);

	// Form state
	const [formName, setFormName] = useState("");
	const [formDesc, setFormDesc] = useState("");
	const [formTasks, setFormTasks] = useState([
		{ time: "09:00:00", action: "CAPTURE_IMAGE", objective: "" },
	]);

	const apiBase =
		typeof window !== "undefined"
			? process.env.NEXT_PUBLIC_API_URL ||
				`http://${window.location.hostname}:8000`
			: "http://localhost:8000";

	const fetchSchedules = useCallback(async () => {
		try {
			const res = await fetch(`${apiBase}/api/schedules`);
			if (res.ok) {
				const data = await res.json();
				setSchedules(data.schedules || []);
			}
		} catch (err) {
			console.error("Failed to fetch schedules:", err);
		} finally {
			setLoading(false);
		}
	}, [apiBase]);

	useEffect(() => {
		fetchSchedules();
	}, [fetchSchedules]);

	// Instant schedule refresh from MQTT commands
	useEffect(() => {
		if (deviceStatus && deviceStatus.status === "schedule_received") {
			console.log("Board received new schedule, refreshing list...");
			fetchSchedules();
		}
	}, [deviceStatus, fetchSchedules]);

	const addTaskRow = () => {
		setFormTasks((prev) => [
			...prev,
			{ time: "12:00:00", action: "CAPTURE_IMAGE", objective: "" },
		]);
	};

	const removeTaskRow = (index) => {
		if (formTasks.length <= 1) return;
		setFormTasks((prev) => prev.filter((_, i) => i !== index));
	};

	const updateTask = (index, field, value) => {
		setFormTasks((prev) =>
			prev.map((t, i) => (i === index ? { ...t, [field]: value } : t)),
		);
	};

	const resetForm = () => {
		setFormName("");
		setFormDesc("");
		setFormTasks([
			{ time: "09:00:00", action: "CAPTURE_IMAGE", objective: "" },
		]);
		setShowForm(false);
	};

	const toggleSleep = async () => {
		const newState = !sleepEnabled;
		setTogglingSleep(true);
		try {
			const res = await fetch(
				`${apiBase}/api/schedules/sleep-mode?enabled=${newState}`,
				{
					method: "POST",
				},
			);
			if (res.ok) setSleepEnabled(newState);
		} catch (err) {
			console.error("Failed to toggle sleep:", err);
		} finally {
			setTogglingSleep(false);
		}
	};

	const handleSubmit = async (e) => {
		e.preventDefault();
		if (!formName.trim() || formTasks.length === 0) return;

		setSubmitting(true);
		try {
			const res = await fetch(`${apiBase}/api/schedules`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					name: formName.trim(),
					description: formDesc.trim(),
					tasks: formTasks,
				}),
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			resetForm();
			fetchSchedules();
		} catch (err) {
			console.error("Failed to create schedule:", err);
		} finally {
			setSubmitting(false);
		}
	};

	return (
		<div className="scheduler-panel">
			{/* ── Create Schedule Toggle ─────────────────────── */}
			<div className="scheduler-toolbar">
				<button
					className={`create-schedule-btn ${showForm ? "cancel" : ""}`}
					onClick={() => setShowForm(!showForm)}
				>
					{showForm ? (
						<>✕ Cancel</>
					) : (
						<>
							<span className="icon">＋</span>
							New Schedule
						</>
					)}
				</button>
				<button
					className={`create-schedule-btn ${sleepEnabled ? "cancel" : ""}`}
					onClick={toggleSleep}
					disabled={togglingSleep}
					title={
						sleepEnabled ? "Board sleeps between tasks" : "Board stays awake"
					}
				>
					{togglingSleep ? (
						<span className="spinner" />
					) : sleepEnabled ? (
						<>🌙 Sleep On</>
					) : (
						<>☀️ Awake</>
					)}
				</button>
			</div>

			{/* ── Create Form ────────────────────────────────── */}
			{showForm && (
				<form className="schedule-form" onSubmit={handleSubmit}>
					<div className="form-grid">
						<div className="form-group">
							<label htmlFor="schedule-name">Schedule Name</label>
							<input
								id="schedule-name"
								type="text"
								placeholder="e.g. Morning Patrol"
								value={formName}
								onChange={(e) => setFormName(e.target.value)}
								required
								autoFocus
							/>
						</div>
						<div className="form-group">
							<label htmlFor="schedule-desc">Description</label>
							<input
								id="schedule-desc"
								type="text"
								placeholder="Optional description"
								value={formDesc}
								onChange={(e) => setFormDesc(e.target.value)}
							/>
						</div>
					</div>

					{/* ── Task Rows ────────────────────────────── */}
					<div className="form-tasks-section">
						<div className="form-tasks-label">
							<span>Capture Tasks</span>
							<button
								type="button"
								className="add-task-btn"
								onClick={addTaskRow}
							>
								＋ Add Task
							</button>
						</div>

						{formTasks.map((task, index) => (
							<div key={index} className="form-task-row">
								<span className="form-task-number">{index + 1}</span>
								<input
									type="time"
									step="1"
									className="form-task-time"
									value={task.time}
									onChange={(e) => updateTask(index, "time", e.target.value)}
									required
								/>
								<select
									className="form-task-action"
									value={task.action}
									onChange={(e) => updateTask(index, "action", e.target.value)}
								>
									<option value="CAPTURE_IMAGE">📸 Capture Image</option>
								</select>
								<input
									type="text"
									className="form-task-objective"
									placeholder="What to look for…"
									value={task.objective}
									onChange={(e) =>
										updateTask(index, "objective", e.target.value)
									}
								/>
								<button
									type="button"
									className="remove-task-btn"
									onClick={() => removeTaskRow(index)}
									disabled={formTasks.length <= 1}
									title="Remove task"
								>
									✕
								</button>
							</div>
						))}
					</div>

					<div className="form-actions">
						<button
							type="submit"
							className="submit-schedule-btn"
							disabled={submitting || !formName.trim()}
						>
							{submitting ? (
								<>
									<span className="spinner" />
									Creating…
								</>
							) : (
								<>💾 Save Schedule</>
							)}
						</button>
					</div>
				</form>
			)}

			{/* ── Schedules List ─────────────────────────────── */}
			{loading ? (
				<div className="scheduler-loading">
					<span className="spinner" />
					Loading schedules…
				</div>
			) : schedules.length === 0 && !showForm ? (
				<div className="scheduler-empty">
					<div className="empty-icon">📋</div>
					<h3 className="empty-title">No schedules yet</h3>
					<p className="empty-subtitle">
						Create a schedule to automate camera captures at specific times.
					</p>
				</div>
			) : (
				<div className="schedule-list">
					{schedules.map((schedule) => (
						<ScheduleCard
							key={schedule.id}
							schedule={schedule}
							onRefresh={fetchSchedules}
						/>
					))}
				</div>
			)}
		</div>
	);
}
