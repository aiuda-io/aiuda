"use client";

import { useRef, useState } from "react";
import { api, type ImportAnalysis, type ImportResult } from "@/lib/api";
import { SecondaryButton } from "@/components/ui";

const EXTRA = "__extra__";
const IGNORE = "__ignore__";

const KNOWN_LABEL: Record<string, string> = {
  whatsapp: "WhatsApp",
  rfc: "RFC",
  sku: "SKU",
  csv: "CSV",
  url: "URL",
  id: "ID",
};

function pretty(field: string): string {
  const known = KNOWN_LABEL[field.toLowerCase()];
  if (known) return known;
  const s = field.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Importador con mapeo: la IA propone tipo y columnas, tú ajustas, y lo que no
 *  mapeas se guarda como dato extra (no se pierde nada). Dos pasos sin recargar. */
export function ExcelUpload({
  className = "",
  onImported,
}: {
  className?: string;
  onImported?: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<globalThis.File | null>(null);
  const [analysis, setAnalysis] = useState<ImportAnalysis | null>(null);
  // Mapeo por ÍNDICE de columna (no por nombre): dos encabezados iguales ya no colisionan
  // ni se pisan; cada columna conserva su destino y sus datos.
  const [colMap, setColMap] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  function initColMap(a: ImportAnalysis) {
    const reverse: Record<string, string> = {};
    for (const [field, col] of Object.entries(a.mapping)) if (col) reverse[col] = field;
    const cm: Record<number, string> = {};
    a.columns.forEach((col, i) => {
      cm[i] = reverse[col] ?? EXTRA; // sin mapear -> extra
    });
    setColMap(cm);
  }

  async function pick(f: globalThis.File) {
    setBusy(true);
    setError(null);
    setResult(null);
    setFile(f);
    try {
      const a = await api.analyzeImport(f);
      setAnalysis(a);
      initColMap(a);
    } catch (e) {
      setError((e as Error).message);
      setFile(null);
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function changeType(entity: string) {
    if (!file) return;
    setBusy(true);
    try {
      const a = await api.analyzeImport(file, entity || undefined);
      setAnalysis(a);
      initColMap(a);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function setColTarget(idx: number, target: string) {
    setColMap((prev) => {
      const next = { ...prev, [idx]: target };
      // Un campo solo puede venir de una columna: si lo reasignas, libera la otra.
      if (target !== EXTRA && target !== IGNORE) {
        for (const k of Object.keys(next)) {
          const ki = Number(k);
          if (ki !== idx && next[ki] === target) next[ki] = EXTRA;
        }
      }
      return next;
    });
  }

  async function doImport() {
    if (!file || !analysis || !analysis.entity) return;
    const mapping: Record<string, string> = {};
    const extras: string[] = [];
    // Recorre por índice para no perder ninguna columna (incluidas las de nombre repetido).
    analysis.columns.forEach((col, i) => {
      const target = colMap[i] ?? EXTRA;
      if (target === EXTRA) extras.push(col);
      else if (target !== IGNORE) mapping[target] = col;
    });
    setBusy(true);
    setError(null);
    try {
      const r = await api.commitImport(file, analysis.entity, mapping, extras);
      setResult(r);
      setAnalysis(null);
      setFile(null);
      if (r.created > 0) onImported?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setAnalysis(null);
    setFile(null);
    setResult(null);
    setError(null);
    setColMap({});
  }

  // --- Resultado ---
  if (result) {
    return (
      <div className={className}>
        <div className="rounded-md bg-panel px-3.5 py-3">
          <p className="text-cuerpo text-ink">
            Importé{" "}
            <span className="font-semibold text-accent-ink">{result.entity_label}</span>:{" "}
            {result.created} cargados
            {result.skipped > 0 && `, ${result.skipped} ya existían`}.
          </p>
          {result.errors.length > 0 && (
            <p className="mt-1.5 text-apoyo text-warn">{result.errors.join(" · ")}</p>
          )}
        </div>
        <SecondaryButton className="mt-3" onClick={reset}>
          Importar otro archivo
        </SecondaryButton>
      </div>
    );
  }

  // --- Paso 2: mapeo ---
  if (analysis) {
    const fieldKeys = Object.keys(analysis.fields);
    const ready = !!analysis.entity;
    return (
      <div className={className}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-cuerpo font-medium text-ink">
            {analysis.filename}{" "}
            <span className="font-normal text-ink-3">· {analysis.row_count} filas</span>
          </p>
          <button onClick={reset} className="text-apoyo text-ink-3 hover:text-ink">
            Cancelar
          </button>
        </div>

        <label className="mt-3 flex flex-wrap items-center gap-2 text-cuerpo">
          <span className="text-ink-2">Esto son</span>
          <select
            value={analysis.entity}
            onChange={(e) => changeType(e.target.value)}
            disabled={busy}
            className="rounded-md border border-line bg-surface px-2.5 py-1.5 text-cuerpo text-ink focus:border-accent focus:outline-none"
          >
            <option value="">Elige un tipo…</option>
            {analysis.types.map((t) => (
              <option key={t.key} value={t.key}>
                {t.label}
              </option>
            ))}
          </select>
          {ready && analysis.confidence >= 0.5 && (
            <span className="text-apoyo text-ink-3">la IA lo detectó</span>
          )}
        </label>

        {!ready ? (
          <p className="mt-3 rounded-md bg-panel px-3.5 py-3 text-apoyo leading-relaxed text-ink-2">
            No reconocí qué tipo de datos trae. Elige uno arriba para mapear las columnas, o
            cancela: por ahora entiendo facturas, clientes, productos, citas y prospectos.
          </p>
        ) : (
          <>
            <div className="mt-3 overflow-hidden rounded-md border border-line">
              <div className="grid grid-cols-[1fr_auto] gap-2 border-b border-line bg-panel/60 px-3 py-2 text-rotulo font-semibold uppercase tracking-[0.05em] text-ink-3">
                <span>Tu columna</span>
                <span>Campo en aiuda</span>
              </div>
              <ul>
                {analysis.columns.map((col, i) => {
                  const ejemplo = analysis.sample[0]?.[col] ?? "";
                  return (
                    <li
                      key={`${col}::${i}`}
                      className="grid grid-cols-[1fr_auto] items-center gap-2 border-b border-line/50 px-3 py-1.5 last:border-0"
                    >
                      <span className="min-w-0">
                        <span className="text-cuerpo font-medium text-ink">{col}</span>
                        {ejemplo && (
                          <span className="ml-1.5 truncate text-apoyo text-ink-3">{ejemplo}</span>
                        )}
                      </span>
                      <select
                        value={colMap[i] ?? EXTRA}
                        onChange={(e) => setColTarget(i, e.target.value)}
                        className="rounded border border-line bg-surface px-1.5 py-1 text-sello text-ink focus:border-accent focus:outline-none"
                      >
                        {fieldKeys.map((f) => (
                          <option key={f} value={f}>
                            {pretty(f)}
                          </option>
                        ))}
                        <option value={EXTRA}>Dato extra</option>
                        <option value={IGNORE}>Ignorar</option>
                      </select>
                    </li>
                  );
                })}
              </ul>
            </div>
            <p className="mt-2 text-apoyo leading-relaxed text-ink-3">
              Lo que dejes como <span className="font-medium text-ink-2">dato extra</span> se
              guarda y se ve en la ficha; nada se pierde.
            </p>
            <button
              onClick={doImport}
              disabled={busy}
              className="mt-3 rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
            >
              {busy ? "Importando…" : `Importar ${analysis.row_count}`}
            </button>
          </>
        )}

        {error && <p className="mt-2 text-cuerpo text-danger">{error}</p>}
      </div>
    );
  }

  // --- Paso 1: elegir archivo ---
  return (
    <div className={className}>
      <p className="text-cuerpo font-medium text-ink">Sube cualquier Excel y la IA entiende qué es</p>
      <p className="mt-0.5 text-apoyo leading-relaxed text-ink-3">
        Sin plantilla. La IA detecta qué es y propone el mapeo; tú lo revisas, ajustas las
        columnas y lo que no mapees se guarda como dato extra. Nada se pierde.
      </p>
      <input
        ref={fileRef}
        type="file"
        accept=".csv,.xlsx"
        className="hidden"
        onChange={(e) => e.target.files?.[0] && pick(e.target.files[0])}
      />
      <SecondaryButton className="mt-2.5" onClick={() => fileRef.current?.click()} disabled={busy}>
        {busy ? "La IA está leyendo tu archivo…" : "Elegir archivo (.xlsx o .csv)"}
      </SecondaryButton>
      {error && <p className="mt-2 text-cuerpo text-danger">{error}</p>}
    </div>
  );
}
