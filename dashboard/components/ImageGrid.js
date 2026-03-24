"use client";

import { useState } from "react";

/**
 * Responsive image grid with animated card entries.
 * New images (pushed via MQTT) get a special glow animation.
 */
export default function ImageGrid({ images, onDelete }) {
	const [selectedImage, setSelectedImage] = useState(null);
	if (images.length === 0) {
		return (
			<div className="empty-state">
				<div className="empty-icon">📡</div>
				<h3 className="empty-title">No captures yet</h3>
				<p className="empty-subtitle">
					Press <strong>Capture Now</strong> or wait for the STM32 board to send
					an image. New images will appear here instantly.
				</p>
			</div>
		);
	}

	return (
		<div className="image-grid">
			{images.map((img, index) => (
				<div
					key={`${img.date}-${img.filename}`}
					className={`image-card${img.isNew ? " new" : ""}`}
					style={{ animationDelay: `${index * 60}ms` }}
				>
					<div className="image-wrapper">
						{/* eslint-disable-next-line @next/next/no-img-element */}
						<img
							src={img.url}
							alt={`Capture — Task ${img.task_id}`}
							loading={img.isNew ? "eager" : "lazy"}
						/>
						<div className="image-overlay">
							<span className="badge task-id">#{img.task_id}</span>
							{img.isNew && <span className="badge live">LIVE</span>}
						</div>
						<div className="image-actions">
							<button
								className="image-action-btn view-btn"
								onClick={() => setSelectedImage(img)}
								title="Focus View"
							>
								🔍
							</button>
							{onDelete && (
								<button
									className="image-action-btn delete-btn"
									onClick={(e) => {
										e.stopPropagation();
										if (window.confirm("Delete this image?")) {
											onDelete(img.date, img.filename);
										}
									}}
									title="Delete Capture"
								>
									🗑
								</button>
							)}
						</div>
					</div>
					<div className="image-meta">
						<span className="image-filename">{img.filename}</span>
						<span className="image-time">
							🕐{" "}
							{img.timestamp
								? new Date(img.timestamp * 1000).toLocaleTimeString()
								: img.date}
						</span>
					</div>
				</div>
			))}

			{selectedImage && (
				<div
					className="image-modal-overlay"
					onClick={() => setSelectedImage(null)}
				>
					<div
						className="image-modal-content"
						onClick={(e) => e.stopPropagation()}
					>
						<button
							className="image-modal-close"
							onClick={() => setSelectedImage(null)}
						>
							✕
						</button>
						{/* eslint-disable-next-line @next/next/no-img-element */}
						<img
							src={selectedImage.url}
							alt={`Task ${selectedImage.task_id} - ${selectedImage.filename}`}
						/>
						<div className="image-modal-meta">
							<span className="badge">#{selectedImage.task_id}</span>
							<span className="image-time">
								{selectedImage.timestamp
									? new Date(selectedImage.timestamp * 1000).toLocaleString()
									: selectedImage.date}
							</span>
						</div>
					</div>
				</div>
			)}
		</div>
	);
}
