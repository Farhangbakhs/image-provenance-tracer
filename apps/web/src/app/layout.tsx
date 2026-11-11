import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
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
        <header className="no-print flex h-10 items-center justify-between border-b border-line bg-surface-1 px-4">
          <span className="text-[12px] font-semibold tracking-[0.14em]">ORIGIN</span>
          <span className="text-[11px] text-muted">All times UTC</span>
        </header>
        <main className="flex flex-1 flex-col">
          <Providers>{children}</Providers>
        </main>
      </body>
    </html>
  );
}
