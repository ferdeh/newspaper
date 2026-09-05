import type { Metadata } from "next";
import "./globals.css";
import AppShell from "@/components/AppShell";

export const metadata: Metadata = {
  title: { default: "Fuel Distribution Intelligence", template: "%s · Fuel Intelligence" },
  description: "News and public TikTok early-signal intelligence for Indonesian fuel distribution and reported HSSE incidents.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="id"><body><AppShell>{children}</AppShell></body></html>;
}
