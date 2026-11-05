import type { Metadata } from "next";

import "./globals.css";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Back Office",
  robots: { index: false, follow: false },
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  if (!process.env.VERCEL) {
    const { startScheduler } = await import("@/lib/poller");
    startScheduler();
  }
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
