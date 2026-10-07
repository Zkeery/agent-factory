import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent 造物坊 · 产品工作台",
  description: "为产品经理与独立创作者打造的小产品工作台：理清需求，构建应用，用真实任务验证，交付并持续迭代。",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="app-viewport" suppressHydrationWarning>{children}</body>
    </html>
  );
}
