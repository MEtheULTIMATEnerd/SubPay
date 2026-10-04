import type { Metadata, Viewport } from "next";
import "./globals.css";
import { AppShell } from "@/components/shell";

export const metadata: Metadata = {
  title: "SubPay",
  description: "Verified progress claims, from site photo to payment.",
  manifest: "/manifest.webmanifest",
};
export const viewport: Viewport = { themeColor: "#0f2e27" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
