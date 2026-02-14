import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Analytics } from "@vercel/analytics/next";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "ArXivisual",
    template: "%s · ArXivisual",
  },
  description:
    "Turn arXiv papers into scrollytelling explanations with Manim-generated visuals.",
  applicationName: "ArXivisual",
  keywords: [
    "arXiv",
    "research",
    "visualization",
    "scrollytelling",
    "Manim",
    "machine learning",
    "computer science",
  ],
  icons: {
    icon: [
      { url: "/icon.png", type: "image/png" },
      { url: "/icon.png", sizes: "any" },
    ],
    apple: [{ url: "/icon.png", type: "image/png" }],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased min-h-dvh bg-black text-[#e8e8e8]`}
      >
        <div className="min-h-dvh">{children}</div>
        <Analytics />
      </body>
    </html>
  );
}
