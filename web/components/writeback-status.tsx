"use client";

// Estado del write-back donde vive el dato: lo que confirmas en aiuda (un pago,
// un cambio de cliente) se escribe de regreso al sistema de origen, y aquí se ve
// en qué va cada inyección — pendiente / inyectada / falló — con su evidencia
// (qué respondió la fuente y cuándo) y reintento manual de una fallida.
// Si el registro no tiene inyecciones (p.ej. vino de Excel: no hay a dónde
// escribir), no pinta nada.

import { useState } from "react";
import { api, mxn, type WritebackEntry } from "@/lib/api";
import { SOURCE_LABEL, SOURCE_LOGO, useApi } from "@/components/ui";
import { toast } from "@/components/toast";
import { fechaHora } from "@/lib/format";

const CAMPO: Record<string, string> = { name: "nombre", email: "correo", phone: "teléfono" };

// Altas inyectadas (aiuda-born viajando al maestro elegido).
const ALTA: Record<string, string> = {
  crear_cliente: "Alta del cliente",
  crear_producto: "Alta del producto",
  crear_factura: "Alta de la factura",
  crear_cita: "Alta de la cita",
};

function titulo(e: WritebackEntry): string {
  const fuente = e.target_label && e.target_label !== e.target ? e.target_label : (SOURCE_LABEL[e.target] ?? e.target);
  if (e.action === "registrar_pago") {
    return `Pago de ${e.folio ?? "la factura"}${e.amount != null ? ` por ${mxn(e.amount)}` : ""} → ${fuente}`;
  }
  if (e.action === "actualizar_cliente") {
    const campos = Object.keys(e.changes ?? {}).map((k) => CAMPO[k] ?? k);
    return `Datos del cliente${campos.length ? ` (${campos.join(", ")})` : ""} → ${fuente}`;
  }
  if (ALTA[e.action]) {
    return `${ALTA[e.action]}${e.folio ? ` ${e.folio}` : ""} → ${fuente}`;
  }
  return `${e.action} → ${fuente}`;
}

function detalle(e: WritebackEntry): string {
  const fuente = e.target_label && e.target_label !== e.target ? e.target_label : (SOURCE_LABEL[e.target] ?? e.target);
  if (e.estado === "inyectada") {
    const r = e.evidencia?.respuesta ?? {};
    const cuando = e.evidencia?.en ? ` · ${fechaHora(e.evidencia.en)}` : "";
    if (r.detalle) return `${r.detalle}${cuando}`;
    if (r.modo === "pago") {
      const saldo = r.saldo_odoo != null ? ` · saldo allá: ${mxn(r.saldo_odoo)}` : "";
      return `Pago asentado en ${fuente}${saldo}${cuando}`;
    }
    if (r.modo === "nota") return `Quedó nota en ${fuente}${cuando}`;
    if (e.action === "actualizar_cliente") {
      return r.creado
        ? `No había liga: se dio de alta en ${fuente}${cuando}`
        : `Cliente actualizado en ${fuente}${cuando}`;
    }
    if (ALTA[e.action]) {
      return `Quedó de alta en ${fuente}${r.ref ? ` (ref. ${r.ref})` : ""}${cuando}`;
    }
    return `Escrito en ${fuente}${cuando}`;
  }
  if (e.estado === "falló") {
    return `No se pudo escribir tras ${e.attempts} intentos${e.last_error ? `: ${e.last_error}` : "."}`;
  }
  // pendiente
  if (e.attempts > 0) {
    const cuando = e.reintento_en ? ` · reintenta después de las ${fechaHora(e.reintento_en)}` : "";
    return `Intento ${e.attempts} falló${e.last_error ? ` (${e.last_error})` : ""}${cuando}`;
  }
  return "En cola: se escribe en la próxima corrida.";
}

const CHIP: Record<string, string> = {
  inyectada: "bg-ok-soft text-ok",
  pendiente: "bg-panel text-ink-2",
  "falló": "bg-danger-soft text-danger",
};

export function WritebackStatus({
  invoiceId,
  customerId,
  refreshKey,
}: {
  invoiceId?: string;
  customerId?: string;
  refreshKey?: string;
}) {
  const { data, refetchQuiet } = useApi<{ entries: WritebackEntry[] }>(
    () => api.writeback({ invoice_id: invoiceId, customer_id: customerId }),
    [invoiceId, customerId, refreshKey],
  );
  const [busy, setBusy] = useState<string | null>(null);

  const entries = data?.entries ?? [];
  if (entries.length === 0) return null; // sin inyecciones no hay nada que reportar

  async function reintentar(id: string) {
    setBusy(id);
    try {
      await api.retryWriteback(id);
      toast("Reintentando la inyección…", "success");
      await refetchQuiet();
      // El procesado corre en segundo plano: un vistazo más para traer el desenlace.
      setTimeout(() => refetchQuiet(), 4000);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section>
      <h3 className="text-cuerpo font-semibold text-ink">Regreso a la fuente</h3>
      <p className="mt-0.5 text-apoyo text-ink-3">
        Lo que confirmas aquí se escribe de vuelta en el sistema de origen.
      </p>
      <ul className="mt-2.5 space-y-1.5">
        {entries.map((e) => (
          <li
            key={e.id}
            className="rounded-md border border-line bg-surface px-3 py-2"
          >
            <div className="flex items-center gap-2.5">
              {SOURCE_LOGO[e.target] ? (
                <img src={SOURCE_LOGO[e.target]} alt="" className="h-4 w-4" />
              ) : (
                <span className="flex h-4 w-4 items-center justify-center rounded bg-panel text-sello font-bold text-ink-2">
                  {(SOURCE_LABEL[e.target] ?? e.target).slice(0, 2)}
                </span>
              )}
              <span className="min-w-0 flex-1 truncate text-cuerpo font-medium text-ink">
                {titulo(e)}
              </span>
              <span
                className={`shrink-0 rounded-full px-2 py-0.5 text-sello font-medium ${CHIP[e.estado] ?? "bg-panel text-ink-2"}`}
              >
                {e.estado === "inyectada"
                  ? "Inyectada"
                  : e.estado === "falló"
                    ? "Falló"
                    : "Pendiente"}
              </span>
            </div>
            <div className="mt-1 flex items-start justify-between gap-3 pl-6.5">
              <p className="text-apoyo leading-relaxed text-ink-3">{detalle(e)}</p>
              {e.estado === "falló" && (
                <button
                  onClick={() => reintentar(e.id)}
                  disabled={busy !== null}
                  className="shrink-0 rounded-md border border-line bg-surface px-2.5 py-1 text-sello font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
                >
                  {busy === e.id ? "Reintentando…" : "Reintentar"}
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
