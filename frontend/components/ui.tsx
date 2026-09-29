"use client";

import React from "react";
import { Loader2, X } from "lucide-react";

/* ---------- helpers ---------- */
export function NvidiaLogo({ size = 20, className }: { size?: number; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 15"
      width={size}
      height={(size * 15) / 24}
      className={className}
      aria-label="NVIDIA"
    >
      <path
        fill="#76B900"
        d="M12 0.5C5.9 0.5 1.4 4.3.1 7.5c1.3 3.2 5.8 7 11.9 7s10.6-3.8 11.9-7C22.6 4.3 18.1.5 12 .5zM12 12c-2.6 0-4.6-2-4.6-4.5S9.4 3 12 3s4.6 2 4.6 4.5S14.6 12 12 12z"
      />
      <circle cx="12" cy="7.5" r="2.1" fill="#76B900" />
    </svg>
  );
}

export function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

/* ---------- Card ---------- */
export function Card({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return <div className={cx("glass p-5 shadow-glass", className)}>{children}</div>;
}

/* ---------- Button ---------- */
type ButtonVariant = "primary" | "ghost" | "danger" | "outline";

export function Button({
  variant = "ghost",
  loading,
  className,
  children,
  disabled,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  loading?: boolean;
}) {
  const styles: Record<ButtonVariant, string> = {
    primary:
      "bg-accent/90 hover:bg-accent text-black font-medium border border-accent/40",
    ghost:
      "bg-white/5 hover:bg-white/10 text-gray-200 border border-white/10",
    danger:
      "bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/30",
    outline:
      "bg-transparent hover:bg-white/5 text-gray-300 border border-white/15",
  };
  return (
    <button
      className={cx(
        "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
        styles[variant],
        className
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <Loader2 size={14} className="animate-spin" />}
      {children}
    </button>
  );
}

/* ---------- Badge ---------- */
const badgeColors: Record<string, string> = {
  available: "bg-accent/15 text-accent border-accent/30",
  healthy: "bg-accent/15 text-accent border-accent/30",
  enabled: "bg-accent/15 text-accent border-accent/30",
  success: "bg-accent/15 text-accent border-accent/30",
  rate_limited: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  degraded: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  error: "bg-red-500/15 text-red-400 border-red-500/30",
  unhealthy: "bg-red-500/15 text-red-400 border-red-500/30",
  failed: "bg-red-500/15 text-red-400 border-red-500/30",
  invalid: "bg-red-500/15 text-red-400 border-red-500/30",
  disabled: "bg-gray-500/15 text-gray-400 border-gray-500/30",
  retired: "bg-purple-500/15 text-purple-400 border-purple-500/30",
  unknown: "bg-gray-500/15 text-gray-400 border-gray-500/30",
  unknown_status: "bg-blue-500/15 text-blue-400 border-blue-500/30",
};

const badgeLabels: Record<string, string> = {
  available: "正常",
  healthy: "正常",
  enabled: "启用",
  success: "成功",
  rate_limited: "限流",
  degraded: "降级",
  error: "异常",
  unhealthy: "异常",
  failed: "失败",
  invalid: "无效",
  disabled: "禁用",
  retired: "已下架",
  unknown: "未知",
};

export function Badge({ status, label }: { status: string; label?: string }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs",
        badgeColors[status] || badgeColors.unknown_status
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {label || badgeLabels[status] || status}
    </span>
  );
}

/* ---------- Modal ---------- */
export function Modal({
  open,
  title,
  onClose,
  children,
  wide,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  wide?: boolean;
}) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className={cx(
          "glass w-full shadow-glass p-6",
          wide ? "max-w-2xl" : "max-w-md"
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-semibold text-gray-100">{title}</h3>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-200 transition-colors"
          >
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

/* ---------- Field / Input ---------- */
export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-gray-400">{label}</span>
      {children}
    </label>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cx(
        "w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-gray-100 outline-none placeholder:text-gray-600 focus:border-accent/50 focus:ring-1 focus:ring-accent/30",
        props.className
      )}
    />
  );
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={cx(
        "w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm font-mono text-gray-100 outline-none placeholder:text-gray-600 focus:border-accent/50 focus:ring-1 focus:ring-accent/30",
        props.className
      )}
    />
  );
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={cx(
        "w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent/50 [&>option]:bg-[#141419]",
        props.className
      )}
    />
  );
}

/* ---------- Table ---------- */
export function Th({ children, className }: { children?: React.ReactNode; className?: string }) {
  return (
    <th
      className={cx(
        "px-3 py-2.5 text-left text-xs font-medium uppercase tracking-wider text-gray-500",
        className
      )}
    >
      {children}
    </th>
  );
}

export function Td({
  children,
  className,
  title,
  colSpan,
}: {
  children?: React.ReactNode;
  className?: string;
  title?: string;
  colSpan?: number;
}) {
  return (
    <td colSpan={colSpan} title={title} className={cx("px-3 py-2.5 text-sm text-gray-300", className)}>
      {children}
    </td>
  );
}

export function DataTable({
  head,
  children,
  empty,
  loading,
}: {
  head: React.ReactNode;
  children: React.ReactNode;
  empty?: string;
  loading?: boolean;
}) {
  return (
    <div className="glass overflow-x-auto">
      <table className="w-full min-w-max border-collapse">
        <thead>
          <tr className="border-b border-white/5">{head}</tr>
        </thead>
        <tbody className="divide-y divide-white/5">
          {children}
          {!loading && React.Children.count(children) === 0 && (
            <tr>
              <td colSpan={50} className="px-3 py-10 text-center text-sm text-gray-500">
                {empty || "暂无数据"}
              </td>
            </tr>
          )}
          {loading && (
            <tr>
              <td colSpan={50} className="px-3 py-10 text-center text-sm text-gray-500">
                <Loader2 className="mx-auto animate-spin text-gray-500" size={20} />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- Toggle ---------- */
export function Toggle({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx(
        "relative h-5 w-9 rounded-full transition-colors disabled:opacity-40",
        checked ? "bg-accent" : "bg-white/15"
      )}
    >
      <span
        className={cx(
          "absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all",
          checked ? "left-[18px]" : "left-0.5"
        )}
      />
    </button>
  );
}

/* ---------- Page header ---------- */
export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-gray-100">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-gray-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/* ---------- misc ---------- */
export function fmtTime(v?: string | null) {
  if (!v) return "—";
  const d = new Date(v);
  if (isNaN(d.getTime())) return v;
  return d.toLocaleString("zh-CN", { hour12: false });
}

export function fmtLatency(ms?: number | null) {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

export function safePct(ok: number, total: number) {
  if (!total) return "—";
  return `${((ok / total) * 100).toFixed(1)}%`;
}
