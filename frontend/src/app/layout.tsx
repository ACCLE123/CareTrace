import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CareTrace · Clinical collaboration",
  description: "Traceable longitudinal care-note prototype"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}

