"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, KeyRound } from "lucide-react";
import { NvidiaLogo } from "@/components/ui";
import { api, setToken } from "@/lib/api";
import { Button, Input } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await api.post<{ token: string }>("/api/admin/login", {
        password,
      });
      setToken(res.token);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-accent/15 text-accent">
            <NvidiaLogo size={30} />
          </div>
          <h1 className="text-2xl font-semibold tracking-wide text-gray-100">NVIDIA2API</h1>
          <p className="mt-1 text-sm text-gray-500">输入管理密码，进入控制台</p>
        </div>

        <form onSubmit={submit} className="glass space-y-4 p-6">
          <label htmlFor="admin-password" className="block text-sm text-gray-300">
            管理密码
          </label>
          <div className="relative">
            <Input
              id="admin-password"
              name="password"
              type={showPassword ? "text" : "password"}
              placeholder="请输入管理密码"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              autoFocus
              required
              disabled={loading}
              aria-invalid={!!error}
              aria-describedby={error ? "login-error" : undefined}
              className="pr-11"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? "隐藏密码" : "显示密码"}
              aria-pressed={showPassword}
              className="absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-r-lg text-gray-400 hover:text-gray-200 focus-visible:outline focus-visible:outline-accent"
            >
              {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
          {error && (
            <p id="login-error" role="alert" className="text-sm text-red-400">
              {error}
            </p>
          )}
          <Button
            variant="primary"
            className="w-full justify-center py-2.5"
            loading={loading}
            type="submit"
          >
            <KeyRound size={15} />
            进入控制台
          </Button>
        </form>
      </div>
    </div>
  );
}
