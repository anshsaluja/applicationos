import type { ReactNode } from "react";

export const metadata = {
  title: "ApplicationOS",
  description: "Application document and requirement review",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
