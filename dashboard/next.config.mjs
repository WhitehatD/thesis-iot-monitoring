/** @type {import('next').NextConfig} */
const nextConfig = {
	output: "standalone",
	images: {
		unoptimized: true,
	},
	async rewrites() {
		return [
			{
				source: "/api/:path*",
				destination: "http://server:8000/api/:path*",
			},
			{
				source: "/mqtt",
				destination: "http://mosquitto:9001",
			},
		];
	},
};

export default nextConfig;
