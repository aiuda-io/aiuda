"use client";

import { useRef, useState } from "react";
import { api, mxn, type BancoAnalisis, type BancoImportResult } from "@/lib/api";
import { fechaDM } from "@/lib/format";
import { SecondaryButton } from "@/components/ui";

const METODO_LABEL: Record<string, string> = {
  banorte: "leído directo (sin IA)",
  bbva: "leído directo (sin IA)",
  ia: "leído con tu IA",
};

/** Importador de estados de cuenta (PDF): arrastras el PDF de tu banco, ves qué
 *  se leyó y si cuadra contra los saldos, y solo cuando apruebas entran los
 *  depósitos a la bandeja de conciliación. Nada se importa a ciegas. */
export function BancoUpload({
  className = "",
  onImported,
}: {
  className?: string;
  onImported?: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [previa, setPrevia] = useState<BancoAnalisis | null>(null);
  const [busy, setBusy] = useState(false);
  const [arrastrando, setArrastrando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BancoImportResult | null>(null);

  async function pick(f: globalThis.File) {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setPrevia(await api.analizarBanco(f));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function importar() {
    if (!previa || !previa.cuadra) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.importarBanco(previa);
      setResult(r);
      setPrevia(null);
      if (r.creados > 0) onImported?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setPrevia(null);
    setResult(null);
    setError(null);
  }

  // --- Resultado ---
  if (result) {
    return (
      <div className={className}>
        <div className="rounded-md bg-panel px-3.5 py-3">
          <p className="text-[12px] text-ink">
            Importé <span className="font-semibold text-accent-ink">{result.creados}</span>{" "}
            {result.creados === 1 ? "depósito" : "depósitos"} de tu estado de{" "}
            {result.banco}
            {result.periodo && ` de ${result.periodo}`}: ya están en Por conciliar.
            {result.omitidos > 0 && ` ${result.omitidos} ya estaban y no se duplicaron.`}
          </p>
          {result.cargos_ignorados > 0 && (
            <p className="mt-1 text-[11.5px] text-ink-3">
              Los {result.cargos_ignorados} cargos del estado no entran: la conciliación es de
              dinero que te llega.
            </p>
          )}
        </div>
        <SecondaryButton className="mt-3" onClick={reset}>
          Subir otro estado
        </SecondaryButton>
      </div>
    );
  }

  // --- Previa: qué se leyó, si cuadra, y el botón de aprobar ---
  if (previa) {
    return (
      <div className={className}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-[12.5px] font-medium text-ink">
            {previa.banco}
            {previa.periodo && <span className="font-normal text-ink-2"> · {previa.periodo}</span>}{" "}
            <span className="font-normal text-ink-3">
              · {METODO_LABEL[previa.metodo] ?? previa.metodo}
            </span>
          </p>
          <button onClick={reset} className="text-[11.5px] text-ink-3 hover:text-ink">
            Cancelar
          </button>
        </div>

        {/* El cuadre: la evidencia de que se leyó completo */}
        <div
          className={`mt-3 rounded-md px-3.5 py-2.5 text-[12px] ${
            previa.cuadra ? "bg-ok-soft text-ok" : "bg-warn-soft text-warn"
          }`}
        >
          {previa.cuadra ? (
            <>
              Cuadra: saldo inicial {mxn(previa.saldo_inicial ?? 0)} + depósitos{" "}
              {mxn(previa.depositos.total)} - retiros {mxn(previa.retiros.total)} = saldo final{" "}
              {mxn(previa.saldo_final ?? 0)}.
            </>
          ) : (
            <>
              No cuadra: hay una diferencia de {mxn(Math.abs(previa.diferencia))} entre los
              movimientos leídos y los saldos del estado. No se importa nada así; revisa que el
              PDF esté completo.
            </>
          )}
        </div>
        {previa.avisos.map((a) => (
          <p key={a} className="mt-1.5 text-[11.5px] text-warn">
            {a}
          </p>
        ))}

        <p className="mt-3 text-[12px] text-ink-2">
          {previa.depositos.n} {previa.depositos.n === 1 ? "depósito" : "depósitos"} por{" "}
          <span className="tnum font-medium text-ink">{mxn(previa.depositos.total)}</span>{" "}
          entrarían a conciliación. Los {previa.retiros.n} retiros solo se muestran, no entran.
        </p>

        <div className="mt-2 max-h-72 overflow-y-auto rounded-md border border-line">
          <ul>
            {previa.movimientos.map((m, i) => (
              <li
                key={`${m.fecha}-${i}`}
                className={`flex items-baseline gap-3 border-b border-line/50 px-3 py-1.5 last:border-0 ${
                  m.abono === null ? "opacity-55" : ""
                }`}
              >
                <span className="tnum shrink-0 text-[11px] text-ink-3">{fechaDM(m.fecha)}</span>
                <span className="min-w-0 flex-1 truncate text-[11.5px] text-ink-2" title={m.concepto}>
                  {m.concepto || "(sin concepto)"}
                </span>
                <span
                  className={`tnum shrink-0 text-[12px] font-medium ${
                    m.abono !== null ? "text-ok" : "text-ink-3"
                  }`}
                >
                  {m.abono !== null ? `+${mxn(m.abono)}` : `-${mxn(m.cargo ?? 0)}`}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <button
          onClick={importar}
          disabled={busy || !previa.cuadra || previa.depositos.n === 0}
          className="mt-3 rounded-md bg-accent px-3.5 py-1.5 text-[12.5px] font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
        >
          {busy
            ? "Importando…"
            : previa.depositos.n === 0
              ? "Sin depósitos que importar"
              : `Importar ${previa.depositos.n} ${previa.depositos.n === 1 ? "depósito" : "depósitos"} a conciliación`}
        </button>
        {error && <p className="mt-2 text-[12px] text-danger">{error}</p>}
      </div>
    );
  }

  // --- Paso 1: arrastrar o elegir el PDF ---
  return (
    <div className={className}>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setArrastrando(true);
        }}
        onDragLeave={() => setArrastrando(false)}
        onDrop={(e) => {
          e.preventDefault();
          setArrastrando(false);
          const f = e.dataTransfer.files?.[0];
          if (f) pick(f);
        }}
        className={`rounded-lg border border-dashed px-4 py-5 text-center transition-colors ${
          arrastrando ? "border-accent bg-accent-soft/30" : "border-line"
        }`}
      >
        <p className="text-[12.5px] font-medium text-ink">
          Arrastra aquí el PDF de tu estado de cuenta
        </p>
        <p className="mx-auto mt-1 max-w-md text-[11.5px] leading-relaxed text-ink-3">
          BBVA y Banorte se leen directo. Cualquier otro banco lo lee tu IA. Ves la previa con el
          cuadre y apruebas; solo entonces los depósitos entran a conciliación.
        </p>
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,application/pdf"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && pick(e.target.files[0])}
        />
        <SecondaryButton
          className="mt-3"
          onClick={() => fileRef.current?.click()}
          disabled={busy}
        >
          {busy ? "Leyendo tu estado de cuenta…" : "Elegir archivo (.pdf)"}
        </SecondaryButton>
      </div>
      {error && <p className="mt-2 text-[12px] text-danger">{error}</p>}
    </div>
  );
}
