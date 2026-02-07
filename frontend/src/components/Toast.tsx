import React, { createContext, useContext, useState } from "react";
import classNames from "../utils/classNames";

type Toast = { id: number; message: string; tone?: "success" | "error" | "info" };

const ToastContext = createContext<{
  push: (message: string, tone?: Toast["tone"]) => void;
} | null>(null);

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = (message: string, tone: Toast["tone"] = "info") => {
    const id = Date.now();
    setToasts((prev) => [...prev, { id, message, tone }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 2500);
  };

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 space-y-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={classNames(
              "min-w-[220px] rounded-lg px-4 py-3 text-sm shadow-lg border",
              t.tone === "success" && "bg-emerald-50 text-emerald-800 border-emerald-200",
              t.tone === "error" && "bg-red-50 text-red-800 border-red-200",
              t.tone === "info" && "bg-slate-900 text-white border-slate-800"
            )}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
};

export const useToast = () => {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
};
