"use client";

import { useState } from "react";
import { api } from "@/lib/api";

type Result = { ok: boolean | null; message: string; details?: Record<string, number | string> };

/** Botón "Probar conexión": pega de verdad al sistema y reporta ok/falla. Honesto:
 *  si la fuente aún no tiene prueba real, lo dice (ok = null). */
export function ConnectionTester({ intKey, disabled }: { intKey: string; disabled?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);

  async function probar() {
    setBusy(true);
    setResult(null);
    try {
      setResult(await api.testIntegration(intKey));
    } catch (e) {
      setResult({ ok: false, message: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  const tone =
    result?.ok === true
      ? "border-ok/30 bg-ok-soft/50 text-ok"
      : result?.ok === false
        ? "border-danger/30 bg-danger-soft text-danger"
        : "border-line bg-panel/50 text-ink-2";

  return (
    <div>
      <button
        onClick={probar}
        disabled={busy || disabled}
        className="rounded-md border border-line bg-surface px-3 py-1.5 text-[12px] font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-40"
      >
        {busy ? "Probando…" : "Probar conexión"}
      </button>
      {result && (
        <div className={`mt-2 rounded-md border px-3 py-2 text-[12px] ${tone}`}>
          <p className="font-medium">{result.message}</p>
          {result.details && (
            <ul className="mt-1 space-y-0.5 text-[11.5px] text-ink-2">
              {Object.entries(result.details).map(([k, v]) => (
                <li key={k}>
                  {k}: <span className="font-medium">{v}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
