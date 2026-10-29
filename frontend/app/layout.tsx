import type { Metadata, Viewport } from "next";
import { Cormorant_Garamond, Titillium_Web } from "next/font/google";
import { AuthProvider } from "@/components/AuthProvider";
import VisitTracker from "@/components/VisitTracker";
import "./globals.css";

const sans = Titillium_Web({ subsets: ["latin"], weight: ["400", "600", "700"], variable: "--font-sans", display: "swap" });
const serif = Cormorant_Garamond({ subsets: ["latin"], weight: ["500", "600", "700"], variable: "--font-serif", display: "swap" });

export const metadata: Metadata = {
  title: "Wayfinder - AI Travel Planner for India",
  description:
    "A team of AI agents plans your trip end-to-end - flights and IRCTC trains, hotels, homestays and havelis, and day-by-day plans - tailored to your travel style and rupee budget.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover", // lay out under notches; padding uses env(safe-area-inset-*)
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#1c1418" },
  ],
};

// Applies the saved theme before first paint (no flash). "light" is the default look; "auto" follows the device.
const THEME_SCRIPT = `try{var t=localStorage.getItem("wf-theme")||"light";if(t!=="auto")document.documentElement.dataset.theme=t}catch(e){document.documentElement.dataset.theme="light"}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN" className={`${sans.variable} ${serif.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <AuthProvider>{children}</AuthProvider>
        <VisitTracker />
      </body>
    </html>
  );
}
