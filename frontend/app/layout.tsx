import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
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
    default: "ArXiviz",
    template: "%s · ArXiviz",
  },
  description:
    "Turn arXiv papers into scrollytelling explanations with Manim-generated visuals.",
  applicationName: "ArXiviz",
  keywords: [
    "arXiv",
    "research",
    "visualization",
    "scrollytelling",
    "Manim",
    "machine learning",
    "computer science",
  ],
  icons: [{ rel: "icon", url: "/favicon.ico" }],
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
      </body>
    </html>
  );
}
