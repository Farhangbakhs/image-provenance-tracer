import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import Link from "next/link";

import { SNAPSHOT } from "@/lib/api/client";
import { EARLIEST_DISCLAIMER } from "@/lib/copy";

import { Providers } from "./providers";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const jetbrainsMono = JetBrains_Mono({ variable: "--font-jetbrains-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "ORIGIN",
  description: "Image provenance tracer: earliest found sightings, variants and narratives.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <header className="no-print flex h-11 items-center justify-between border-b border-line bg-surface-1 px-4">
          <Link href="/" className="flex items-baseline gap-3 hover:opacity-90">
            <span className="text-[13px] font-bold tracking-[0.22em]">ORIGIN</span>
            <span className="label hidden sm:inline">Image provenance</span>
          </Link>
          <div className="flex items-center gap-3">
            {SNAPSHOT ? (
              <span className="label border border-intent px-1.5 py-0.5 text-intent" title="A read-only copy of the demo investigations">
                Snapshot · read-only
              </span>
            ) : null}
            <span className="mono text-[12px] text-muted">All times UTC</span>
          </div>
        </header>
        <div className="no-print flex items-center gap-2 border-b border-line bg-bg px-4 py-1 text-[12px] text-muted">
          <span className="label text-faint">Open source</span>
          <span>{EARLIEST_DISCLAIMER}</span>
        </div>
        <main className="flex flex-1 flex-col">
          <Providers>{children}</Providers>
        </main>
      </body>
    </html>
  );
}
