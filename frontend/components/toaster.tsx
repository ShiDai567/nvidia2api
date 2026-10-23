"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Info, XCircle } from "lucide-react";

export type ToastType = "success" | "error" | "info";

interface ToastItem {
  id: number;
  type: ToastType;
  message: string;
}

let idSeq = 0;

function emit(type: ToastType, message: string) {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("nvidia2api:toast", { detail: { type, message } }));
  }
}

export const toast = {
  success: (m: string) => emit("success", m),
  error: (m: string) => emit("error", m),
  info: (m: string) => emit("info", m),
};

const STYLES: Record<ToastType, { icon: typeof Info; cls: string }> = {
  success: { icon: CheckCircle2, cls: "border-emerald-500/30 text-emerald-300" },
  error: { icon: XCircle, cls: "border-red-500/30 text-red-300" },
  info: { icon: Info, cls: "border-sky-500/30 text-sky-300" },
};

export function Toaster() {
  const [items, setItems] = useState<ToastItem[]>([]);

  useEffect(() => {
    function onToast(e: Event) {
      const detail = (e as CustomEvent<{ type: ToastType; message: string }>).detail;
      const id = ++idSeq;
      setItems((prev) => [...prev.slice(-4), { id, ...detail }]);
      window.setTimeout(() => {
        setItems((prev) => prev.filter((t) => t.id !== id));
      }, 4000);
    }
    window.addEventListener("nvidia2api:toast", onToast);
    return () => window.removeEventListener("nvidia2api:toast", onToast);
  }, []);

  return (
    <div className="pointer-events-none fixed bottom-5 right-5 z-[100] flex w-80 flex-col gap-2">
      {items.map((t) => {
        const s = STYLES[t.type];
        const Icon = s.icon;
        return (
          <div
            key={t.id}
            className={`pointer-events-auto flex items-start gap-2.5 rounded-xl border bg-[#12121a]/95 px-3.5 py-3 text-sm shadow-2xl backdrop-blur-md ${s.cls}`}
          >
            <Icon size={16} className="mt-0.5 shrink-0" />
            <span className="text-zinc-200">{t.message}</span>
          </div>
        );
      })}
    </div>
  );
}
