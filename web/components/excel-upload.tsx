"use client";

import { useRef, useState } from "react";
import { api, type ImportAnalysis, type ImportResult } from "@/lib/api";
import { PrimaryButton, SecondaryButton, inputCls, QuietButton } from "@/components/ui";
import { FalloAccion } from "@/components/cartera-partes";
import { leerFallo, plural, type Fallo } from "@/lib/cartera";

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

/** Subir un Excel: tu IA propone qué es la hoja y a qué corresponde cada columna, tú lo
 *  revisas, y lo que no corresponda a nada se guarda como dato extra (no se pierde
 *  nada). Dos pasos sin recargar. */
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
  const [fallo, setFallo] = useState<Fallo | null>(null);
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
    setFallo(null);
    setResult(null);
    setFile(f);
    try {
      const a = await api.analyzeImport(f);
      setAnalysis(a);
      initColMap(a);
    } catch (e) {
      setFallo(leerFallo(e));
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
      setFallo(leerFallo(e));
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
    setFallo(null);
    try {
      const r = await api.commitImport(file, analysis.entity, mapping, extras);
      setResult(r);
      setAnalysis(null);
      setFile(null);
      if (r.created > 0) onImported?.();
    } catch (e) {
      setFallo(leerFallo(e));
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setAnalysis(null);
    setFile(null);
    setResult(null);
    setFallo(null);
    setColMap({});
  }

  // --- Resultado ---
  if (result) {
    return (
      <div className={className}>
        <p
          className="mark text-cuerpo text-ink"
          style={{ "--mark": "var(--color-ok)", whiteSpace: "normal" } as React.CSSProperties}
        >
          {result.entity_label}: {plural(result.created, "registro cargado", "registros cargados")}
          {result.skipped > 0 &&
            `, ${plural(result.skipped, "ya existía", "ya existían")}`}
        </p>
        {result.errors.map((aviso) => (
          <p key={aviso} className="mt-2 text-apoyo text-ink-2">
            {aviso}
          </p>
        ))}
        <SecondaryButton className="mt-4" onClick={reset}>
          Subir otro archivo
        </SecondaryButton>
      </div>
    );
  }

  // --- Paso 2: revisar qué es cada columna ---
  if (analysis) {
    const fieldKeys = Object.keys(analysis.fields);
    const ready = !!analysis.entity;
    return (
      <div className={className}>
        <p className="text-seccion font-semibold text-ink">{analysis.filename}</p>
        <p className="tnum mt-0.5 text-apoyo text-ink-3">{plural(analysis.row_count, "fila", "filas")}</p>

        <label className="mt-4 flex flex-wrap items-center gap-3 text-cuerpo text-ink">
          <span>Esta hoja trae</span>
          <select
            value={analysis.entity}
            onChange={(e) => changeType(e.target.value)}
            disabled={busy}
            className={`${inputCls} w-auto`}
          >
            <option value="">Elige qué trae</option>
            {analysis.types.map((t) => (
              <option key={t.key} value={t.key}>
                {t.label}
              </option>
            ))}
          </select>
          {ready && analysis.confidence >= 0.5 && (
            <span className="text-apoyo text-ink-3">Lo reconoció tu IA</span>
          )}
        </label>

        {!ready ? (
          <p className="mt-4 text-cuerpo text-ink-2">
            No se reconoció qué trae esta hoja. Elige arriba si son facturas, clientes,
            productos, citas o prospectos.
          </p>
        ) : (
          <>
            <div className="mt-5 grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 border-b border-line pb-2 text-rotulo font-medium text-ink-3">
              <span>Tu columna</span>
              <span>Qué es</span>
            </div>
            <ul>
              {analysis.columns.map((col, i) => {
                const ejemplo = analysis.sample[0]?.[col] ?? "";
                return (
                  <li
                    key={`${col}::${i}`}
                    className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 border-b border-line py-2 last:border-0"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-cuerpo font-medium text-ink">{col}</span>
                      {ejemplo && <span className="block truncate text-apoyo text-ink-3">{ejemplo}</span>}
                    </span>
                    <select
                      value={colMap[i] ?? EXTRA}
                      onChange={(e) => setColTarget(i, e.target.value)}
                      aria-label={`Qué es la columna ${col}`}
                      className={`${inputCls} w-40 max-w-[45vw]`}
                    >
                      {fieldKeys.map((f) => (
                        <option key={f} value={f}>
                          {pretty(f)}
                        </option>
                      ))}
                      <option value={EXTRA}>Dato extra</option>
                      <option value={IGNORE}>No cargar</option>
                    </select>
                  </li>
                );
              })}
            </ul>
            <p className="mt-3 text-apoyo text-ink-2">
              Lo que dejes como dato extra se guarda y se ve en su ficha. Nada se pierde.
            </p>
          </>
        )}

        <div className="mt-5 flex flex-wrap items-center gap-2">
          {ready && (
            <PrimaryButton onClick={doImport} disabled={busy}>
              {busy ? "Cargando…" : `Cargar ${plural(analysis.row_count, "fila", "filas")}`}
            </PrimaryButton>
          )}
          <QuietButton onClick={reset} disabled={busy}>
            Cancelar
          </QuietButton>
        </div>
        {fallo && (
          <div className="mt-3">
            <FalloAccion fallo={fallo} />
          </div>
        )}
      </div>
    );
  }

  // --- Paso 1: elegir archivo ---
  return (
    <div className={className}>
      <p className="text-cuerpo font-medium text-ink">Sube tu Excel tal como lo llevas</p>
      <p className="mt-1 max-w-md text-apoyo text-ink-2">
        No necesitas plantilla. Tu IA reconoce qué trae la hoja y a qué corresponde cada
        columna; tú lo revisas antes de que se cargue.
      </p>
      <input
        ref={fileRef}
        type="file"
        accept=".csv,.xlsx"
        className="hidden"
        onChange={(e) => e.target.files?.[0] && pick(e.target.files[0])}
      />
      <SecondaryButton className="mt-4" onClick={() => fileRef.current?.click()} disabled={busy}>
        {busy ? "Tu IA está leyendo el archivo…" : "Elegir archivo de Excel"}
      </SecondaryButton>
      {fallo && (
        <div className="mt-3">
          <FalloAccion fallo={fallo} />
        </div>
      )}
    </div>
  );
}
