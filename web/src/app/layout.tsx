import type { Metadata } from "next";

import { startScheduler } from "@/lib/poller";

import "./globals.css";

startScheduler();

export const metadata: Metadata = {
  title: "Back Office",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
