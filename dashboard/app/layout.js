import "./globals.css";

export const metadata = {
	title: "IoT Visual Monitoring — Dashboard",
	description:
		"Real-time monitoring dashboard for the Autonomous IoT Visual Monitoring system. View camera captures and AI analysis results.",
};

export default function RootLayout({ children }) {
	return (
		<html lang="en">
			<body>{children}</body>
		</html>
	);
}
