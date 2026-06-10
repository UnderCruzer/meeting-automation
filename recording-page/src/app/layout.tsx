import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Meeting Recording",
  description: "회의 녹음 페이지",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body style={{ margin: 0, background: "#fff" }}>{children}</body>
    </html>
  );
}
