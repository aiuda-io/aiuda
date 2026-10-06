"use client";

import { useRef, useState } from "react";
import { api, type BancoAnalisis, type BancoImportResult } from "@/lib/api";
import { fechaDM } from "@/lib/format";
import { PrimaryButton, SecondaryButton, QuietButton } from "@/components/ui";
import { FalloAccion } from "@/components/cartera-partes";
import { dinero, leerFallo, plural, type Fallo } from "@/lib/cartera";

const METODO_LABEL: Record<string, string> = {
  banorte: "leído directo",
  bbva: "leído directo",
  ia: "leído con tu IA",
};

/** Cuántos movimientos se enseñan de entrada; el resto se abre con un botón. Nada de
 *  una lista con su propio scroll adentro de la página. */
const MUESTRA = 8;

/** Subir el estado de cuenta (PDF): eliges el PDF de tu banco, ves qué se leyó y si
 *  las cuentas cuadran contra los saldos, y solo cuando apruebas entran los depósitos
 *  a Pagos, por confirmar. Nada entra a ciegas. */
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
  const [fallo, setFallo] = useState<Fallo | null>(null);
  const [result, setResult] = useState<BancoImportResult | null>(null);
  const [todos, setTodos] = useState(false);

  async function pick(f: globalThis.File) {
    setBusy(true);
    setFallo(null);
    setResult(null);
    setTodos(false);
    try {
      setPrevia(await api.analizarBanco(f));
    } catch (e) {
      setFallo(leerFallo(e));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function importar() {
    if (!previa || !previa.cuadra) return;
    setBusy(true);
    setFallo(null);
    try {
      const r = await api.importarBanco(previa);
      setResult(r);
      setPrevia(null);
      if (r.creados > 0) onImported?.();
    } catch (e) {
      setFallo(leerFallo(e));
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setPrevia(null);
    setResult(null);
    setFallo(null);
  }

  // --- Resultado ---
  if (result) {
    return (
      <div className={className}>
        <p className="mark text-cuerpo text-ink" style={{ "--mark": "var(--color-ok)", whiteSpace: "normal" } as React.CSSProperties}>
          {plural(result.creados, "depósito entró", "depósitos entraron")} a Pagos, por confirmar
        </p>
        <p className="mt-2 text-cuerpo text-ink-2">
          De tu estado de {result.banco}
          {result.periodo && `, ${result.periodo}`}.
          {result.omitidos > 0 &&
            ` ${plural(result.omitidos, "ya estaba y no se duplicó", "ya estaban y no se duplicaron")}.`}
          {result.cargos_ignorados > 0 &&
            ` ${plural(result.cargos_ignorados, "retiro no entra", "retiros no entran")}: aquí solo cuenta el dinero que te llega.`}
        </p>
        <SecondaryButton className="mt-4" onClick={reset}>
          Subir otro estado de cuenta
        </SecondaryButton>
      </div>
    );
  }

  // --- Previa: qué se leyó, si cuadra, y el botón de aprobar ---
  if (previa) {
    const movimientos = todos ? previa.movimientos : previa.movimientos.slice(0, MUESTRA);
    const puede = previa.cuadra && previa.depositos.n > 0;
    return (
      <div className={className}>
        <p className="text-seccion font-semibold text-ink">
          {previa.banco}
          {previa.periodo && <span className="font-normal text-ink-2">, {previa.periodo}</span>}
        </p>
        <p className="mt-0.5 text-apoyo text-ink-3">{METODO_LABEL[previa.metodo] ?? previa.metodo}</p>

        {/* Que las cuentas cuadren es la prueba de que el PDF se leyó completo. */}
        <p
          className="mark mt-4 text-cuerpo text-ink"
          style={{ "--mark": previa.cuadra ? "var(--color-ok)" : "var(--color-warn)" } as React.CSSProperties}
        >
          {previa.cuadra ? "Las cuentas cuadran" : "Las cuentas no cuadran"}
        </p>
        <p className="tnum mt-1 text-apoyo text-ink-2">
          {previa.cuadra
            ? `Saldo inicial ${dinero(previa.saldo_inicial ?? 0, previa.moneda)}, más depósitos ${dinero(previa.depositos.total, previa.moneda)}, menos retiros ${dinero(previa.retiros.total, previa.moneda)}, da el saldo final de ${dinero(previa.saldo_final ?? 0, previa.moneda)}.`
            : `Hay ${dinero(Math.abs(previa.diferencia), previa.moneda)} de diferencia entre los movimientos leídos y los saldos del estado. Así no entra nada: revisa que el PDF esté completo.`}
        </p>
        {previa.avisos.map((a) => (
          <p key={a} className="mt-2 text-apoyo text-ink-2">
            {a}
          </p>
        ))}

        <p className="mt-5 text-cuerpo text-ink">
          {plural(previa.depositos.n, "depósito", "depósitos")} por{" "}
          <span className="tnum font-semibold">{dinero(previa.depositos.total, previa.moneda)}</span>{" "}
          {previa.depositos.n === 1 ? "entraría" : "entrarían"} a Pagos.
          {previa.retiros.n > 0 && (
            <span className="text-ink-2">
              {" "}
              {plural(previa.retiros.n, "retiro solo se muestra", "retiros solo se muestran")}.
            </span>
          )}
        </p>

        <ul className="mt-3">
          {movimientos.map((m, i) => (
            <li
              key={`${m.fecha}-${i}`}
              className="flex items-baseline gap-3 border-b border-line py-2 last:border-0"
            >
              <span className="tnum w-14 shrink-0 text-apoyo text-ink-3">{fechaDM(m.fecha)}</span>
              <span className="min-w-0 flex-1 truncate text-apoyo text-ink-2" title={m.concepto}>
                {m.concepto || "Sin concepto"}
              </span>
              <span
                className={`tnum shrink-0 text-apoyo ${m.abono !== null ? "font-semibold text-ink" : "text-ink-3"}`}
              >
                {m.abono !== null ? `+${dinero(m.abono, previa.moneda)}` : `-${dinero(m.cargo ?? 0, previa.moneda)}`}
              </span>
            </li>
          ))}
        </ul>
        {previa.movimientos.length > MUESTRA && (
          <button
            onClick={() => setTodos((v) => !v)}
            className="mt-2 text-apoyo font-medium text-accent-ink hover:underline"
          >
            {todos ? "Ver menos" : `Ver los ${previa.movimientos.length} movimientos`}
          </button>
        )}

        <div className="mt-5 flex flex-wrap items-center gap-2">
          <PrimaryButton onClick={importar} disabled={busy || !puede}>
            {busy
              ? "Guardando…"
              : previa.depositos.n === 0
                ? "No hay depósitos que pasar"
                : `Pasar ${plural(previa.depositos.n, "depósito", "depósitos")} a Pagos`}
          </PrimaryButton>
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
        className={`rounded-2xl border border-dashed px-5 py-6 transition-colors ${
          arrastrando ? "border-ink bg-fill" : "border-line-strong"
        }`}
      >
        <p className="text-cuerpo font-medium text-ink">Arrastra aquí el PDF de tu estado de cuenta</p>
        <p className="mt-1 max-w-md text-apoyo text-ink-2">
          BBVA y Banorte se leen directo; cualquier otro banco lo lee tu IA. Primero ves lo que
          se leyó y tú decides si entra.
        </p>
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,application/pdf"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && pick(e.target.files[0])}
        />
        <SecondaryButton className="mt-4" onClick={() => fileRef.current?.click()} disabled={busy}>
          {busy ? "Leyendo tu estado de cuenta…" : "Elegir el PDF"}
        </SecondaryButton>
      </div>
      {fallo && (
        <div className="mt-3">
          <FalloAccion fallo={fallo} />
        </div>
      )}
    </div>
  );
}
