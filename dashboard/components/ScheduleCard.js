"use client";

import { useState } from "react";

/**
 * Individual schedule card with expand/collapse, activate, and delete.
 */
export default function ScheduleCard({
	schedule,
	onActivate,
	onDelete,
	onRefresh,
}) {
	const [expanded, setExpanded] = useState(false);
	const [activating, setActivating] = useState(false);
	const [deleting, setDeleting] = useState(false);

	const apiBase =
		typeof window !== "undefined"
			? process.env.NEXT_PUBLIC_API_URL ||
				`http://${window.location.hostname}:8000`
			: "http://localhost:8000";

	const handleActivate = async (e) => {
		e.stopPropagation();
		setActivating(true);
		try {
			const res = await fetch(
				`${apiBase}/api/schedules/${schedule.id}/activate`,
				{
					method: "POST",
				},
			);
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			if (onActivate) onActivate(schedule.id);
			if (onRefresh) onRefresh();
		} catch (err) {
			console.error("Activation failed:", err);
		} finally {
			setActivating(false);
		}
	};

	const handleDelete = async (e) => {
		e.stopPropagation();
		setDeleting(true);
		try {
			const res = await fetch(`${apiBase}/api/schedules/${schedule.id}`, {
				method: "DELETE",
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			if (onDelete) onDelete(schedule.id);
			if (onRefresh) onRefresh();
		} catch (err) {
			console.error("Delete failed:", err);
		} finally {
			setDeleting(false);
		}
	};

	return (
		<div
			className={`schedule-card${schedule.is_active ? " active" : ""}`}
			onClick={() => setExpanded(!expanded)}
		>
			<div className="schedule-card-header">
				<div className="schedule-card-info">
					<div className="schedule-card-title-row">
						<h3 className="schedule-card-name">{schedule.name}</h3>
						{schedule.is_active && (
							<span className="schedule-badge active-badge">
								<span className="active-dot" />
								ACTIVE
							</span>
						)}
					</div>
					{schedule.description && (
						<p className="schedule-card-desc">{schedule.description}</p>
					)}
					<div className="schedule-card-meta">
						<span className="schedule-badge task-count-badge">
							{schedule.tasks?.length || 0} task
							{(schedule.tasks?.length || 0) !== 1 ? "s" : ""}
						</span>
						{schedule.created_at && (
							<span className="schedule-card-date">
								{new Date(schedule.created_at).toLocaleDateString(undefined, {
									month: "short",
									day: "numeric",
									year: "numeric",
								})}
							</span>
						)}
					</div>
				</div>
				<div className="schedule-card-actions">
					{!schedule.is_active && (
						<button
							className="schedule-action-btn activate-btn"
							onClick={handleActivate}
							disabled={activating}
							title="Activate this schedule"
						>
							{activating ? <span className="spinner" /> : "⚡"}
						</button>
					)}
					<button
						className="schedule-action-btn delete-btn"
						onClick={handleDelete}
						disabled={deleting}
						title="Delete schedule"
					>
						{deleting ? <span className="spinner" /> : "🗑"}
					</button>
					<button
						className="schedule-action-btn expand-btn"
						onClick={(e) => {
							e.stopPropagation();
							setExpanded(!expanded);
						}}
						title={expanded ? "Collapse" : "Expand"}
					>
						<span className={`chevron ${expanded ? "up" : "down"}`}>›</span>
					</button>
				</div>
			</div>

			{expanded && schedule.tasks && schedule.tasks.length > 0 && (
				<div className="schedule-tasks-table">
					<div className="schedule-tasks-header-row">
						<span>#</span>
						<span>Time</span>
						<span>Action</span>
						<span>Objective</span>
					</div>
					{schedule.tasks.map((task, i) => (
						<div key={task.id || i} className="schedule-task-row">
							<span className="task-order">{i + 1}</span>
							<span className="task-time-value">{task.time}</span>
							<span className="task-action-value">{task.action}</span>
							<span className="task-objective-value">
								{task.objective || "—"}
							</span>
						</div>
					))}
				</div>
			)}
		</div>
	);
}
