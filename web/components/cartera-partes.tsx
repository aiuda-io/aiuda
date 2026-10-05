"use client";

// Piezas chicas que comparten las pestañas de Cartera, SAT e Importar.

import Link from "next/link";
import type { SaldoMoneda } from "@/lib/api";
import { dinero, RUTA, type Fallo } from "@/lib/cartera";

/** Filtro de una lista: opciones calladas, la elegida con relleno gris. No es un
 *  control de pestañas: vive DENTRO de una pestaña y solo acota lo que se ve. */
export function Filtro<K extends string>({
  opciones,
  activo,
  onChange,
  label,
}: {
  opciones: { key: K; label: string; count?: number }[];
  activo: K;
  onChange: (key: K) => void;
  /** Qué se está filtrando, para lectores de pantalla. */
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap items-center gap-1">
      {opciones.map((o) => {
        const on = o.key === activo;
        return (
          <button
            key={o.key}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(o.key)}
            className={`btn btn-sm ${on ? "btn-secondary" : "btn-quiet"}`}
          >
            {o.label}
            {typeof o.count === "number" && o.count > 0 && (
              <span className="tnum font-normal text-ink-3">{o.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** Lo que alguien debe, sin mezclar monedas: la principal en el renglón y, si debe en
 *  otra, cada una debajo y más chica. Hereda tamaño y peso de quien lo envuelve. */
export function Saldo({ por }: { por: SaldoMoneda[] | undefined }) {
  const [principal, ...otras] = por ?? [];
  if (!principal) return null;
  return (
    <>
      <span className="tnum whitespace-nowrap">{dinero(principal.open_total, principal.moneda)}</span>
      {otras.map((s) => (
        <span key={s.moneda} className="tnum block whitespace-nowrap text-apoyo font-medium text-ink-2">
          {dinero(s.open_total, s.moneda)}
        </span>
      ))}
    </>
  );
}

/** Lo que salió mal en una acción, junto a su botón. Si se arregla en Tu IA, trae la
 *  liga. Lo que es "falta algo" va como aviso (ámbar); lo que se rompió, en rojo. */
export function FalloAccion({ fallo }: { fallo: Fallo }) {
  return (
    <p role="alert" className="flex items-start gap-2 text-cuerpo text-ink">
      <span
        aria-hidden="true"
        className={`mt-2 h-1.5 w-1.5 shrink-0 rounded-full ${fallo.aviso ? "bg-warn" : "bg-danger"}`}
      />
      <span className="min-w-0">
        {fallo.mensaje}
        {fallo.ia && (
          <>
            {" "}
            <Link href={RUTA.ia} className="font-medium text-accent-ink hover:underline">
              {fallo.aviso ? "Conectar mi IA" : "Revisar mi IA"}
            </Link>
          </>
        )}
      </span>
    </p>
  );
}
