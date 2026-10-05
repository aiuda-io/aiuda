"use client";

// Pestaña Promesas de Cartera: lo que cada cliente dijo que iba a pagar y cuándo.
// Igual que en Facturas, el renglón solo abre el panel de la factura; ahí se registra
// el pago (que cumple la promesa) o se marca cumplida a mano.

import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { fecha, fechaDM } from "@/lib/format";
import { EmptyState, ErrorState, SearchInput, Skeleton, useApi } from "@/components/ui";
import { InvoiceDrawer } from "@/components/invoice-drawer";
import { ExportButton } from "@/components/export-button";
import { Filtro } from "@/components/cartera-partes";
import {
  dinero,
  dineroPorMoneda,
  plural,
  totalesPorMoneda,
  type PromesaConMoneda,
} from "@/lib/cartera";

type Estado = "active" | "fulfilled";

const COLUMNAS = "md:grid-cols-[minmax(0,1fr)_9rem_10rem_15rem]";

export function CarteraPromesas({ onChanged }: { onChanged?: () => void }) {
  const [estado, setEstado] = useState<Estado>("active");
  const { data, error, loading, refetch, refetchQuiet } = useApi<PromesaConMoneda[]>(
    () => api.promises(estado) as Promise<PromesaConMoneda[]>,
    [estado],
  );
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);

  const todas = useMemo(() => data ?? [], [data]);
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return todas.filter(
      (p) =>
        !q ||
        (p.customer ?? "").toLowerCase().includes(q) ||
        (p.folio ?? "").toLowerCase().includes(q),
    );
  }, [todas, query]);

  const prometido = useMemo(
    () => totalesPorMoneda(todas, (p) => p.amount, (p) => p.currency),
    [todas],
  );
  const vencidas = todas.filter((p) => p.vencida).length;

  if (error) return <ErrorState message={error} retry={refetch} />;

  const cargando = loading && !data;
  const vacia = !cargando && todas.length === 0;

  return (
    <div className="min-w-0">
      {!cargando && !vacia && estado === "active" && (
        <div className="reveal mb-10">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="hero-num text-cifra text-ink">{dineroPorMoneda(prometido.slice(0, 1))}</span>
            <span className="text-cuerpo text-ink-2">
              prometido en {plural(prometido[0]?.count ?? 0, "promesa", "promesas")}
            </span>
          </div>
          {prometido.slice(1).map((t) => (
            <p key={t.moneda} className="mt-1.5 text-cuerpo text-ink-2">
              <span className="tnum text-seccion font-semibold text-ink">{dinero(t.total, t.moneda)}</span>{" "}
              prometido en {plural(t.count, "promesa", "promesas")}
            </p>
          ))}
          {vencidas > 0 && (
            <p
              className="mark mt-3 text-cuerpo"
              style={{ "--mark": "var(--color-danger)" } as React.CSSProperties}
            >
              {vencidas === 1 ? "1 ya venció y no se pagó" : `${vencidas} ya vencieron y no se pagaron`}
            </p>
          )}
        </div>
      )}

      <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-3">
        <Filtro
          label="Qué promesas ver"
          activo={estado}
          onChange={setEstado}
          opciones={[
            { key: "active", label: "Abiertas" },
            { key: "fulfilled", label: "Cumplidas" },
          ]}
        />
        {!vacia && (
          <SearchInput value={query} onChange={setQuery} placeholder="Buscar cliente o folio" />
        )}
        <span className="md:ml-auto">
          <ExportButton entidad="promesas" filtros={{ status: estado, q: query }} count={rows.length} />
        </span>
      </div>

      {cargando ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-11 w-full" />
          ))}
        </div>
      ) : vacia ? (
        estado === "active" ? (
          <EmptyState title="Nadie te ha prometido un pago">
            Cuando un cliente conteste algo como &ldquo;te deposito el viernes&rdquo;, tu ayudante lo
            anota aquí con su fecha y te avisa si no cumple.
          </EmptyState>
        ) : (
          <EmptyState title="Aún no hay promesas cumplidas">
            Cuando registres el pago de una factura con promesa, la promesa se queda aquí como
            cumplida.
          </EmptyState>
        )
      ) : rows.length === 0 ? (
        <EmptyState title="Nada coincide">Ninguna promesa coincide con lo que buscas.</EmptyState>
      ) : (
        <>
          <div
            className={`hidden gap-x-6 border-b border-line px-3 pb-2.5 text-rotulo font-medium text-ink-3 md:grid ${COLUMNAS}`}
          >
            <span>Cliente</span>
            <span>Factura</span>
            <span className="text-right">Monto</span>
            <span>{estado === "active" ? "Prometió pagar" : "Se cumplió"}</span>
          </div>
          <ul>
            {rows.map((p) => (
              <li key={p.id} className="border-b border-line last:border-0">
                <button
                  onClick={() => setOpenId(p.invoice_id)}
                  className={`grid w-full grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-6 gap-y-1 py-3.5 text-left transition-colors duration-150 hover:bg-panel md:items-center md:rounded-lg md:px-3 ${COLUMNAS}`}
                >
                  <span className="order-1 truncate text-cuerpo font-medium text-ink" title={p.customer}>
                    {p.customer}
                  </span>
                  <span className="tnum order-2 whitespace-nowrap text-right text-cuerpo font-semibold text-ink md:order-3">
                    {dinero(p.amount, p.currency)}
                  </span>
                  <span className="order-3 col-span-2 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-0.5 md:contents">
                    <span className="tnum truncate text-apoyo text-ink-3 md:order-2">{p.folio}</span>
                    <span className="min-w-0 md:order-4">
                      <Cuando p={p} cumplida={estado === "fulfilled"} />
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      <InvoiceDrawer
        invoiceId={openId}
        onClose={() => setOpenId(null)}
        onChanged={() => {
          refetchQuiet();
          onChanged?.();
        }}
      />
    </div>
  );
}

/** La fecha y qué tan cerca está, en una sola marca. */
function Cuando({ p, cumplida }: { p: PromesaConMoneda; cumplida: boolean }) {
  if (cumplida) {
    return (
      <span className="mark tnum" style={{ "--mark": "var(--color-ok)" } as React.CSSProperties}>
        Cumplida{p.fulfilled_at ? ` el ${fechaDM(p.fulfilled_at)}` : ""}
      </span>
    );
  }
  if (!p.factura_abierta) {
    return <span className="mark tnum">{fecha(p.promised_date)}, factura ya cerrada</span>;
  }
  const color =
    p.days_left < 0 ? "var(--color-danger)" : p.days_left === 0 ? "var(--color-warn)" : "var(--color-line-strong)";
  const cerca =
    p.days_left < 0
      ? `venció hace ${plural(-p.days_left, "día", "días")}`
      : p.days_left === 0
        ? "es hoy"
        : `en ${plural(p.days_left, "día", "días")}`;
  return (
    <span className="mark tnum" style={{ "--mark": color } as React.CSSProperties}>
      {fechaDM(p.promised_date)}, {cerca}
    </span>
  );
}
