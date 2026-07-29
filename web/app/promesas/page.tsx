"use client";

import { useMemo, useState } from "react";
import { api, mxn, type PromiseItem } from "@/lib/api";
import { fecha, fechaDM } from "@/lib/format";
import { EmptyState, ErrorState, PageHeader, SearchInput, Skeleton, Tabs, useApi } from "@/components/ui";
import { RailLayout, RailSection, RailStat } from "@/components/rail";
import { InvoiceDrawer } from "@/components/invoice-drawer";
import { toast } from "@/components/toast";
import { ExportButton } from "@/components/export-button";

export default function PromesasPage() {
  const [tab, setTab] = useState<"active" | "fulfilled">("active");
  const { data, error, loading, refetch } = useApi<PromiseItem[]>(
    () => api.promises(tab),
    [tab],
  );
  const [leaving, setLeaving] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);

  const fulfill = async (id: string) => {
    setLeaving((s) => new Set(s).add(id));
    try {
      await api.fulfill(id);
      setTimeout(() => {
        refetch();
        setLeaving(new Set());
      }, 250);
    } catch (e) {
      // Fallar mudo dejaba la promesa "activa" sin explicar por qué no se marcó.
      toast(`No se pudo marcar como cumplida: ${(e as Error).message}`, "error");
      setLeaving(new Set());
    }
  };

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data ?? []).filter(
      (p) =>
        !q ||
        (p.customer ?? "").toLowerCase().includes(q) ||
        (p.folio ?? "").toLowerCase().includes(q),
    );
  }, [data, query]);

  // Resumen de la cobranza prometida (solo tiene sentido en activas).
  const resumen = useMemo(() => {
    const list = data ?? [];
    return {
      prometido: list.reduce((a, p) => a + p.amount, 0),
      incumplidas: list.filter((p) => p.days_left < 0).length,
      hoy: list.filter((p) => p.days_left === 0).length,
    };
  }, [data]);

  const hayDatos = !loading && (data ?? []).length > 0;

  if (error) return <ErrorState message={error} retry={refetch} />;

  return (
    <div className="min-w-0">
      <PageHeader
        title="Promesas de pago"
        subtitle="Tu ayudante registra cada promesa y su desenlace. Las cumplidas quedan como historial."
        right={<ExportButton entidad="promesas" filtros={{ status: tab, q: query }} count={rows.length} />}
      />

      <Tabs
        tabs={[
          { key: "active", label: "Activas", count: tab === "active" ? rows.length : undefined },
          {
            key: "fulfilled",
            label: "Cumplidas",
            count: tab === "fulfilled" ? rows.length : undefined,
          },
        ]}
        active={tab}
        onChange={(k) => setTab(k as "active" | "fulfilled")}
      />

      {loading && (
        <div className="space-y-2">
          <Skeleton className="h-9 w-72 rounded-lg" />
          <Skeleton className="h-11 w-full rounded-lg" />
          <Skeleton className="h-11 w-full rounded-lg" />
          <Skeleton className="h-11 w-full rounded-lg" />
        </div>
      )}

      {!loading && (data ?? []).length === 0 && tab === "active" && (
        <EmptyState title="Sin promesas activas">
          Cuando un cliente responda algo como “te deposito el viernes”, tu ayudante registrará la
          promesa aquí y propondrá el siguiente recordatorio si no se cumple.
        </EmptyState>
      )}
      {!loading && (data ?? []).length === 0 && tab === "fulfilled" && (
        <EmptyState title="Aún no hay promesas cumplidas">
          Cada promesa que marques como cumplida se archiva aquí con su fecha. El historial
          nunca se borra.
        </EmptyState>
      )}

      {hayDatos && (
        <RailLayout
          rail={
            tab === "active" ? (
              <RailSection label="Cobranza prometida">
                <RailStat label="Prometido" value={mxn(resumen.prometido)} strong />
                <RailStat
                  label="Incumplidas"
                  value={String(resumen.incumplidas)}
                  hint={resumen.incumplidas > 0 ? "ya pasó la fecha" : undefined}
                />
                <RailStat label="Vencen hoy" value={String(resumen.hoy)} />
              </RailSection>
            ) : undefined
          }
        >
          <div className="mb-3">
            <SearchInput value={query} onChange={setQuery} placeholder="Buscar por cliente o folio…" />
          </div>
          <div className="overflow-x-auto rounded-lg border border-line bg-surface">
            <table className="w-full min-w-[560px] text-left">
              <thead>
                <tr className="border-b border-line bg-panel/60 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">
                  <th className="px-4 py-2.5">Cliente</th>
                  <th className="px-4 py-2.5">Factura</th>
                  <th className="px-4 py-2.5 text-right">Monto</th>
                  <th className="px-4 py-2.5">
                    {tab === "active" ? "Prometió pagar" : "Se cumplió"}
                  </th>
                  <th className="px-4 py-2.5">Nota</th>
                  {tab === "active" && <th className="px-4 py-2.5 text-right" />}
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr
                    key={p.id}
                    onClick={() => setOpenId(p.invoice_id)}
                    className={`${
                      leaving.has(p.id) ? "row-leaving" : ""
                    } group cursor-pointer border-b border-line/60 last:border-0`}
                  >
                    <td className="px-4 py-2.5">
                      {/* Disparador real (no solo el onClick del tr): abre el detalle con
                          Enter/teclado, replicando la liga navegable de Prospectos. */}
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setOpenId(p.invoice_id);
                        }}
                        className="text-left text-[12.5px] font-medium text-ink hover:text-accent-ink hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                      >
                        {p.customer}
                      </button>
                    </td>
                    <td className="tnum px-4 py-2.5 text-[12.5px] text-ink">{p.folio}</td>
                    <td className="tnum px-4 py-2.5 text-right text-[12.5px] font-medium text-ink">
                      {mxn(p.amount)}
                    </td>
                    <td className="tnum px-4 py-2.5 text-[12px]">
                      {tab === "active" ? (
                        <span className={p.days_left < 0 ? "font-medium text-danger" : "text-ink-2"}>
                          {fecha(p.promised_date)}
                          {p.days_left < 0
                            ? ` · incumplida hace ${-p.days_left} d`
                            : p.days_left === 0
                              ? " · hoy"
                              : ` · en ${p.days_left} d`}
                        </span>
                      ) : (
                        <span className="flex items-center gap-1.5 text-ok">
                          <svg viewBox="0 0 12 12" className="h-3 w-3" fill="none">
                            <path
                              d="m2.5 6.5 2.5 2.5 4.5-5"
                              stroke="currentColor"
                              strokeWidth="1.6"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                          </svg>
                          {p.fulfilled_at ? fechaDM(p.fulfilled_at) : "·"}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-[12px] text-ink-3">{p.note ?? "·"}</td>
                    {tab === "active" && (
                      <td className="px-4 py-2.5 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            fulfill(p.id);
                          }}
                          disabled={leaving.has(p.id)}
                          title="El cliente cumplió: pasa al historial de cumplidas"
                          className="rounded border border-line bg-surface px-2 py-1 text-[11.5px] font-medium text-ink-2 opacity-100 transition-all hover:border-ok hover:text-ok focus-visible:opacity-100 disabled:opacity-60 md:opacity-60 md:group-hover:opacity-100 md:group-focus-within:opacity-100"
                        >
                          Marcar cumplida
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-10 text-center text-[12.5px] text-ink-3">
                      Sin resultados para tu búsqueda.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </RailLayout>
      )}

      <InvoiceDrawer invoiceId={openId} onClose={() => setOpenId(null)} onChanged={refetch} />
    </div>
  );
}
