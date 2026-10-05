"use client";

import { useState } from "react";
import { SecondaryButton } from "@/components/ui";
import { api } from "@/lib/api";

type Result = { ok: boolean | null; message: string; details?: Record<string, number | string> };

/** Botón "Probar conexión": pega de verdad al sistema y reporta ok/falla. Honesto:
 *  si la fuente aún no tiene prueba real, lo dice (ok = null). */
export function ConnectionTester({
  intKey,
  disabled,
  onProbada,
}: {
  intKey: string;
  disabled?: boolean;
  /** Terminó una prueba: el semáforo de la lista ya cambió y quien monta lo relee. */
  onProbada?: () => void;
}) {
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
      onProbada?.();
    }
  }

  // El color va solo en el punto; lo que pasó se dice con palabras.
  const marca =
    result?.ok === true
      ? "var(--color-ok)"
      : result?.ok === false
        ? "var(--color-danger)"
        : "var(--color-line-strong)";

  return (
    <div>
      <SecondaryButton onClick={probar} disabled={busy || disabled}>
        {busy ? "Probando…" : "Probar conexión"}
      </SecondaryButton>
      {result && (
        <div role="status" className="mt-3 max-w-md text-cuerpo">
          <p
            className="mark !items-start !whitespace-normal !text-cuerpo !text-ink"
            style={{ "--mark": marca } as React.CSSProperties}
          >
            {result.message}
          </p>
          {result.details && (
            <ul className="mt-1.5 space-y-0.5 pl-3 text-apoyo text-ink-2">
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
