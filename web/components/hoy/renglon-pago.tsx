"use client";

import { useState } from "react";
import Link from "next/link";
import { api, CONCILIACION_ORIGEN, type ReconcileItem } from "@/lib/api";
import { dinero } from "@/lib/cartera";
import { fechaDM } from "@/lib/format";
import { Cabeza, Fila, Marca } from "@/components/hoy/piezas";
import { idPago, type Ejecutar } from "@/components/hoy/tipos";

/** A qué se puede aplicar un pago: una factura, o varias del mismo cliente que suman. */
type Opcion = {
  key: string;
  ids: string[];
  folios: string;
  cliente: string;
  /** Lo que falta por cobrar de esa factura (o del grupo). */
  porCobrar: number;
  cuadra: boolean;
  parcial: boolean;
  porque: string;
};

function opcionesDe(p: ReconcileItem): Opcion[] {
  const facturas = [p.proposal, ...p.alternates]
    .filter((c): c is NonNullable<typeof c> => c !== null)
    .map(
      (c): Opcion => ({
        key: c.invoice_id,
        ids: [c.invoice_id],
        folios: c.folio,
        cliente: c.customer,
        porCobrar: c.saldo ?? c.amount,
        cuadra: c.cuadra,
        parcial: Boolean(c.parcial),
        porque: c.reason,
      }),
    );
  const grupos = p.grupos.map(
    (g): Opcion => ({
      key: g.invoice_ids.join("+"),
      ids: g.invoice_ids,
      folios: g.folios.join(", "),
      cliente: g.customer,
      porCobrar: g.total,
      cuadra: g.cuadra,
      parcial: false,
      porque: g.reason,
    }),
  );
  // Lo que el ayudante propone va primero; lo demás queda como alternativa.
  return p.propuesta_tipo === "grupo" ? [...grupos, ...facturas] : [...facturas, ...grupos];
}

/** Un pago recibido que espera que el dueño confirme a qué factura va, con el
 *  porqué de la propuesta a la vista. */
export function RenglonPago({
  p,
  ocupado,
  saliendo,
  ejecutar,
}: {
  p: ReconcileItem;
  ocupado: boolean;
  saliendo: boolean;
  ejecutar: Ejecutar;
}) {
  const id = idPago(p);
  const opciones = opcionesDe(p);
  const [elegida, setElegida] = useState<string | null>(null);
  const [porDescartar, setPorDescartar] = useState(false);
  const sel = opciones.find((o) => o.key === elegida) ?? opciones[0] ?? null;
  const diferencia = sel ? p.amount - sel.porCobrar : 0;
  const quieto = ocupado || saliendo;
  const variasFacturas = (sel?.ids.length ?? 0) > 1;

  return (
    <Fila id={id} saliendo={saliendo}>
      <Cabeza nombre={p.counterparty ?? sel?.cliente ?? "Pago recibido"} monto={dinero(p.amount, p.currency)}>
        <span className="font-medium text-ink-2">Pago por confirmar</span>
        <span>{p.origen ?? CONCILIACION_ORIGEN[p.source] ?? p.source}</span>
        <span className="tnum">recibido {fechaDM(p.paid_at)}</span>
        {p.reference && <span className="tnum">{p.reference}</span>}
      </Cabeza>

      <div className="mt-4 max-w-2xl rounded-[14px] bg-panel px-4 py-3">
        {sel ? (
          <>
            <p className="text-cuerpo leading-relaxed text-ink">
              {variasFacturas ? "Contra las facturas " : "Contra la factura "}
              <span className="tnum font-semibold">{sel.folios}</span> de {sel.cliente}, por{" "}
              <span className="tnum font-semibold">{dinero(sel.porCobrar, p.currency)}</span>.
            </p>
            <p className="mt-2">
              {sel.cuadra ? (
                <Marca color="ok">El monto cuadra</Marca>
              ) : sel.parcial ? (
                <Marca color="warn">
                  Es un abono: faltarían {dinero(Math.abs(diferencia), p.currency)} y la factura sigue abierta
                </Marca>
              ) : (
                <Marca color="warn">
                  No cuadra: {diferencia > 0 ? "sobran" : "faltan"} {dinero(Math.abs(diferencia), p.currency)}
                </Marca>
              )}
            </p>
            {sel.porque && (
              <p className="mt-2 text-cuerpo leading-relaxed text-ink-2">
                <span className="font-medium text-ink">Por qué esta:</span> {sel.porque}
              </p>
            )}
            {p.ambiguo && p.nota && (
              <p className="mt-2 text-cuerpo leading-relaxed text-ink-2">{p.nota}</p>
            )}
            {opciones.length > 1 && (
              <label className="mt-3 block text-apoyo text-ink-3">
                Aplicar a otra
                <select
                  value={sel.key}
                  onChange={(e) => setElegida(e.target.value)}
                  disabled={quieto}
                  className="field mt-1 focus:border-accent focus:outline-none"
                >
                  {opciones.map((o) => (
                    <option key={o.key} value={o.key}>
                      {o.folios} · {o.cliente} · {dinero(o.porCobrar, p.currency)}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </>
        ) : (
          <p className="text-cuerpo leading-relaxed text-ink-2">
            {p.nota || "No hay una factura abierta que coincida con este pago."}
          </p>
        )}
      </div>

      {porDescartar ? (
        <div className="mt-4">
          <p className="text-cuerpo text-ink-2">
            ¿Descartar este pago? No se aplica a ninguna factura. Queda en el historial de Pagos.
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={quieto}
              onClick={() =>
                ejecutar(() => api.ignoreReconcile(p.id), "Pago descartado. No se aplicó a nada.", id)
              }
              className="btn btn-danger"
            >
              Sí, descartar
            </button>
            <button
              type="button"
              onClick={() => setPorDescartar(false)}
              disabled={quieto}
              className="btn btn-quiet"
            >
              Cancelar
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {sel && (
            <button
              type="button"
              disabled={quieto}
              onClick={() =>
                ejecutar(
                  () => api.confirmReconcile(p.id, sel.ids),
                  sel.parcial
                    ? `Abono aplicado a ${sel.folios}. La factura sigue abierta.`
                    : `Pago aplicado a ${sel.folios}.`,
                  id,
                )
              }
              className="btn btn-primary"
            >
              Confirmar pago
            </button>
          )}
          <button
            type="button"
            onClick={() => setPorDescartar(true)}
            disabled={quieto}
            className="btn btn-quiet"
          >
            Descartar pago
          </button>
          <Link href="/facturas?vista=pagos" className="btn btn-quiet">
            Ver en Pagos
          </Link>
        </div>
      )}
    </Fila>
  );
}
