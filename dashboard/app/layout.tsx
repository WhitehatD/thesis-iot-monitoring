import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
	title: "Visual Monitor | Enterprise Edge AI",
	description: "Autonomous IoT Visual Monitoring System Dashboard",
};

export default function RootLayout({
	children,
}: {
	children: React.ReactNode;
}) {
	return (
		<html lang="en">
			<body>{children}</body>
		</html>
	);
}
