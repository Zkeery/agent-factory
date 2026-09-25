import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent造物坊",
  description: "给非技术产品经理用的 AI 产品工厂",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
