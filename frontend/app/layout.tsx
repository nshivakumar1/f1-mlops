import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "F1 Pitstop Predictor",
  description: "Live F1 pitstop predictions powered by XGBoost + AWS",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-[#0f0f0f] text-white">
        <nav className="border-b border-[#2a2a2a] px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl font-black tracking-tight">
              <span className="text-[#e10600]">F1</span> Predictor
            </span>
          </div>
          <div className="flex gap-6 text-sm text-gray-400">
            <a href="/" className="hover:text-white transition-colors">Live</a>
            <a href="/history" className="hover:text-white transition-colors">History</a>
            <a href="/about" className="hover:text-white transition-colors">About</a>
          </div>
        </nav>
        <main>{children}</main>
        <footer className="border-t border-[#2a2a2a] px-6 py-4 text-center text-xs text-gray-600 mt-16">
          Powered by XGBoost · AWS SageMaker · Groq (Llama 3.3) · Data: OpenF1
        </footer>
      </body>
    </html>
  );
}
