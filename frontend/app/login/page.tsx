"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Hexagon, Loader2 } from "lucide-react";
import { api, setToken } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setError(null);
    setBusy(true);
    try {
      const { access_token } = await api.login(username, password);
      setToken(access_token);
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-4">
      <div className="w-full max-w-sm rounded-[14px] border border-line bg-surface p-8 shadow-panel">
        <div className="mb-7 flex items-center gap-2.5">
          <span className="flex h-[30px] w-[30px] items-center justify-center rounded-[9px]
                           bg-gradient-to-br from-primary to-primary-dark text-on-primary">
            <Hexagon size={17} strokeWidth={2.1} />
          </span>
          <span className="text-[19px] font-bold tracking-[0.02em] text-primary">JEZSEEM</span>
        </div>

        <h1 className="m-0 mb-1 text-lg font-semibold">Sign in</h1>
        <p className="m-0 mb-6 text-[12.8px] text-muted">Enter your ERP credentials to continue.</p>

        <label className="mb-1.5 block text-xs font-medium text-muted" htmlFor="username">
          Username
        </label>
        <input
          id="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          autoComplete="username"
          className="mb-4 w-full rounded-lg border border-line bg-bg px-3.5 py-2.5 text-sm
                     outline-none transition-colors focus:border-primary"
        />

        <label className="mb-1.5 block text-xs font-medium text-muted" htmlFor="password">
          Password
        </label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          autoComplete="current-password"
          className="mb-5 w-full rounded-lg border border-line bg-bg px-3.5 py-2.5 text-sm
                     outline-none transition-colors focus:border-primary"
        />

        {error && (
          <p className="mb-4 rounded-lg bg-rose/10 px-3 py-2.5 text-[12.5px] text-rose">{error}</p>
        )}

        <button
          onClick={submit}
          disabled={busy || !username || !password}
          className="flex w-full items-center justify-center gap-2 rounded-lg
                     bg-gradient-to-br from-primary to-primary-dark py-2.5 text-sm
                     font-medium text-on-primary transition-opacity disabled:opacity-50"
        >
          {busy && <Loader2 size={15} className="animate-spin" />}
          {busy ? "Signing in" : "Sign in"}
        </button>
      </div>
    </div>
  );
}
