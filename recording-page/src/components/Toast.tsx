"use client";
import { createContext, useCallback, useContext, useState } from "react";

type Toast = { id: number; message: string; tone: "default" | "error" };
const ToastContext = createContext<(message: string, tone?: Toast["tone"]) => void>(() => {});

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const show = useCallback((message: string, tone: Toast["tone"] = "default") => {
    const id = Date.now() + Math.random();
    setToasts(list => [...list, { id, message, tone }]);
    setTimeout(() => setToasts(list => list.filter(t => t.id !== id)), tone === "error" ? 7000 : 3500);
  }, []);
  return <ToastContext.Provider value={show}>
    {children}
    <div className="toasts" aria-live="polite">
      {toasts.map(t => <div key={t.id} role={t.tone === "error" ? "alert" : "status"}
        className={`toast${t.tone === "error" ? " toast-error" : ""}`}>{t.message}</div>)}
    </div>
  </ToastContext.Provider>;
}

export const useToast = () => useContext(ToastContext);
