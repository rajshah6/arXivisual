import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Analytics } from "@vercel/analytics/next";
import { SpeedInsights } from "@vercel/speed-insights/next";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "arXivisual",
  alternateName: ["arxivisuals", "arxiv visual", "arxiv visuals", "arXivisuals"],
  url: "https://arxivisual.org",
  applicationCategory: "EducationalApplication",
  operatingSystem: "Web",
  description:
    "arXivisual transforms arXiv research papers into interactive scrollytelling experiences with Manim-generated animated visualizations. Built by Armaan Gupta, Nikhil Hooda, Raj Shah, and Ajith Bondili.",
  author: [
    { "@type": "Person", name: "Armaan Gupta", sameAs: "https://x.com/armaangupt0" },
    { "@type": "Person", name: "Nikhil Hooda", sameAs: "https://x.com/_nikhilhooda" },
    { "@type": "Person", name: "Raj Shah", sameAs: "https://x.com/_rajshah6" },
    { "@type": "Person", name: "Ajith Bondili", sameAs: "https://x.com/AjithBondili" },
  ],
  offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
  keywords: "arXiv, arXivisual, arXivisuals, arxiv visual, arxiv visuals, research paper visualizer, Manim, scrollytelling, AI, machine learning",
};

export const metadata: Metadata = {
  metadataBase: new URL("https://arxivisual.org"),
  title: {
    default: "arXivisual — arXiv Papers, Visualized",
    template: "%s · arXivisual",
  },
  description:
    "arXivisual transforms any arXiv research paper into an interactive scrollytelling experience with AI-generated Manim animations. Paste an arXiv URL and watch complex papers come to life.",
  applicationName: "arXivisual",
  keywords: [
    "arXivisual",
    "arXivisuals",
    "arxiv visual",
    "arxiv visuals",
    "arXiv",
    "arXiv paper visualizer",
    "research paper explainer",
    "Manim animations",
    "AI paper summary",
    "scrollytelling",
    "machine learning visualization",
    "academic paper visualization",
    "computer science",
    "AI research",
    "3Blue1Brown style",
    "Armaan Gupta",
    "Nikhil Hooda",
    "Raj Shah",
    "Ajith Bondili",
    "interactive research",
    "paper to video",
  ],
  authors: [
    { name: "Armaan Gupta", url: "https://x.com/armaangupt0" },
    { name: "Nikhil Hooda", url: "https://x.com/_nikhilhooda" },
    { name: "Raj Shah", url: "https://x.com/_rajshah6" },
    { name: "Ajith Bondili", url: "https://x.com/AjithBondili" },
  ],
  creator: "Armaan Gupta, Nikhil Hooda, Raj Shah, Ajith Bondili",
  openGraph: {
    type: "website",
    url: "https://arxivisual.org",
    siteName: "arXivisual",
    title: "arXivisual — arXiv Papers, Visualized",
    description:
      "Transform any arXiv paper into an interactive scrollytelling experience with AI-generated Manim animations. One edit: arxiv → arxivisual.",
    images: [
      {
        url: "/landing.jpeg",
        width: 1200,
        height: 630,
        alt: "arXivisual — arXiv papers transformed into animated visual explanations",
      },
    ],
    locale: "en_US",
  },
  twitter: {
    card: "summary_large_image",
    site: "@armaangupt0",
    creator: "@armaangupt0",
    title: "arXivisual — arXiv Papers, Visualized",
    description:
      "Transform any arXiv paper into an interactive scrollytelling experience with AI-generated Manim animations.",
    images: ["/landing.jpeg"],
  },
  icons: {
    icon: [
      { url: "/icon.png", type: "image/png" },
      { url: "/icon.png", sizes: "any" },
    ],
    apple: [{ url: "/icon.png", type: "image/png" }],
  },
  alternates: {
    canonical: "https://arxivisual.org",
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-video-preview": -1,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
      </head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased min-h-dvh bg-black text-[#e8e8e8]`}
      >
        <div className="min-h-dvh">{children}</div>
        <Analytics />
        <SpeedInsights />
      </body>
    </html>
  );
}
