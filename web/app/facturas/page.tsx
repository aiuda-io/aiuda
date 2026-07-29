"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { api, BUCKET_META, mxn, type InvoiceItem } from "@/lib/api";
import { fechaDM } from "@/lib/format";
import {
  BucketPill,
  ErrorState,
  PageHeader,
  SearchInput,
  Skeleton,
  SourceBadge,
  Tabs,
  useApi,
} from "@/components/ui";
import { AnimatedNumber } from "@/components/motion";
import { RailLayout, RailRow, RailSection } from "@/components/rail";
import { InvoiceDrawer } from "@/components/invoice-drawer";
import { AgregarSheet } from "@/components/agregar-sheet";
import { ExportButton } from "@/components/export-button";

type SortKey = "folio" | "customer" | "amount" | "days_overdue";

// El orden de los tramos de cartera. Etiqueta y colores viven en BUCKET_META (lib/api).
const BUCKET_ORDER = ["por_vencer", "vence_pronto", "vencida_reciente", "vencida", "critica"];

export default function FacturasPage() {
  const [tab, setTab] = useState<"open" | "paid">("open");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({
    key: "days_overdue",
    dir: -1,
  });
  const { data, error, loading, refetch } = useApi<InvoiceItem[]>(
    () => api.invoices(tab),
    [tab],
  );
  const [busy, setBusy] = useState<Record<string, string>>({});
  const [done, setDone] = useState<Record<string, string>>({});
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [bucket, setBucket] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [agregar, setAgregar] = useState(false);

  const syncNow = async () => {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const r = await api.sync();
      const aviso = r.avisos?.length ? ` · ${r.avisos[0]}` : "";
      setSyncMsg(
        r.fuentes.length === 0
          ? `Sin fuentes conectadas todavía${aviso}`
          : `${r.pedidos_importados} pedidos nuevos · ${r.pagos_confirmados.length} pagos confirmados${aviso}`,
      );
      refetch();
    } catch (e) {
      setSyncMsg((e as Error).message);
    } finally {
      setSyncing(false);
      setTimeout(() => setSyncMsg(null), 4000);
    }
  };

  // Cartera completa de la pestaña (sin filtrar por búsqueda/tramo): alimenta el
  // resumen de antigüedad y el riel, que describen el TODO, no el subconjunto visible.
  const grandTotal = useMemo(() => (data ?? []).reduce((a, i) => a + i.amount, 0), [data]);
  const grandCount = (data ?? []).length;

  const aging = useMemo(() => {
    const m = new Map<string, { count: number; total: number }>();
    for (const inv of data ?? []) {
      const b = m.get(inv.bucket) ?? { count: 0, total: 0 };
      b.count += 1;
      b.total += inv.amount;
      m.set(inv.bucket, b);
    }
    return BUCKET_ORDER.filter((b) => m.has(b)).map((b) => ({ bucket: b, ...m.get(b)! }));
  }, [data]);

  const topDeudores = useMemo(() => {
    const m = new Map<string, number>();
    for (const inv of data ?? []) m.set(inv.customer, (m.get(inv.customer) ?? 0) + inv.amount);
    return [...m.entries()]
      .map(([customer, total]) => ({ customer, total }))
      .sort((a, b) => b.total - a.total)
      .slice(0, 6);
  }, [data]);

  const porVencer = useMemo(
    () =>
      (data ?? [])
        .filter((i) => i.days_overdue <= 0 && i.days_overdue >= -7)
        .sort((a, b) => b.days_overdue - a.days_overdue)
        .slice(0, 6),
    [data],
  );

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = (data ?? []).filter(
      (inv) =>
        (!bucket || inv.bucket === bucket) &&
        (!q ||
          inv.customer?.toLowerCase().includes(q) ||
          inv.folio?.toLowerCase().includes(q)),
    );
    list.sort((a, b) => {
      const va = a[sort.key];
      const vb = b[sort.key];
      const cmp = typeof va === "number" ? va - (vb as number) : String(va).localeCompare(String(vb));
      return cmp * sort.dir;
    });
    return list;
  }, [data, sort, query, bucket]);

  if (error) return <ErrorState message={error} retry={refetch} />;

  const act = async (inv: InvoiceItem, action: "pay" | "remind") => {
    setBusy((b) => ({ ...b, [inv.id]: action }));
    try {
      if (action === "pay") {
        await api.pay(inv.id);
        setDone((d) => ({ ...d, [inv.id]: "Pago confirmado, ya está en Pagadas" }));
        setTimeout(refetch, 1100);
      } else {
        await api.remind(inv.id);
        setDone((d) => ({ ...d, [inv.id]: "Borrador listo en Aprobaciones" }));
      }
    } catch (e) {
      setDone((d) => ({ ...d, [inv.id]: (e as Error).message }));
    } finally {
      setBusy((b) => {
        const next = { ...b };
        delete next[inv.id];
        return next;
      });
    }
  };

  const toggleSort = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === 1 ? -1 : 1 } : { key, dir: 1 }));

  const Th = ({
    label,
    sortKey,
    right,
  }: {
    label: string;
    sortKey?: SortKey;
    right?: boolean;
  }) => (
    <th className={`px-4 py-2.5 ${right ? "text-right" : "text-left"}`}>
      {sortKey ? (
        <button
          onClick={() => toggleSort(sortKey)}
          className="inline-flex items-center gap-1 uppercase tracking-[0.06em] transition-colors hover:text-ink"
        >
          {label}
          {sort.key === sortKey && (
            <svg viewBox="0 0 12 12" className="h-3 w-3" fill="none" aria-hidden="true">
              <path
                d={sort.dir === 1 ? "m3 7.5 3-3 3 3" : "m3 4.5 3 3 3-3"}
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          )}
        </button>
      ) : (
        label
      )}
    </th>
  );

  return (
    <div className="min-w-0">
      <PageHeader
        title="Facturas"
        subtitle="Cada registro carga su origen y verificación. Un dicho no es un pago: tú confirmas."
        right={
          <span className="flex items-center gap-3">
            {syncMsg && <span className="text-apoyo text-ink-3">{syncMsg}</span>}
            <ExportButton entidad="facturas" filtros={{ status: tab, bucket, q: query }} />
            <button
              onClick={syncNow}
              disabled={syncing}
              title="Trae pedidos por cobrar de tus fuentes y confirma pagos contra banco/Stripe"
              className="rounded-md border border-line bg-surface px-2.5 py-1 text-sello font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-60"
            >
              {syncing ? "Sincronizando…" : "Sincronizar fuentes"}
            </button>
            <button
              onClick={() => setAgregar(true)}
              className="rounded-md bg-accent px-2.5 py-1 text-sello font-medium text-surface transition-colors hover:bg-accent-strong"
            >
              Agregar factura
            </button>
          </span>
        }
      />
      <AgregarSheet open={agregar} onClose={() => setAgregar(false)} tipo="facturas" label="factura" onCreated={refetch} />

      <Tabs
        tabs={[
          { key: "open", label: "Abiertas", count: tab === "open" ? grandCount : undefined },
          { key: "paid", label: "Pagadas", count: tab === "paid" ? grandCount : undefined },
        ]}
        active={tab}
        onChange={(k) => {
          setTab(k as "open" | "paid");
          setBucket(null);
        }}
      />

      {tab === "open" ? (
        <AgingResumen
          aging={aging}
          total={grandTotal}
          count={grandCount}
          active={bucket}
          onPick={setBucket}
          loading={loading && !data}
        />
      ) : (
        <div className="mb-4 flex items-baseline gap-2.5">
          <span className="hero-num text-cifra font-semibold leading-none text-ink">
            <AnimatedNumber value={grandTotal} format={mxn} />
          </span>
          <span className="text-cuerpo text-ink-3">
            cobrado · {grandCount} {grandCount === 1 ? "factura" : "facturas"}
          </span>
        </div>
      )}

      <RailLayout
        rail={
          tab === "open" ? (
            <FacturasRail deudores={topDeudores} porVencer={porVencer} loading={loading && !data} />
          ) : undefined
        }
      >
          <div className="mb-3">
            <SearchInput value={query} onChange={setQuery} placeholder="Buscar por cliente o folio…" />
          </div>

          <div className="overflow-hidden rounded-lg border border-line bg-surface">
            {loading ? (
              <div className="space-y-2 p-4">
                <Skeleton className="h-7 w-full" />
                <Skeleton className="h-7 w-full" />
                <Skeleton className="h-7 w-full" />
                <Skeleton className="h-7 w-full" />
                <Skeleton className="h-7 w-full" />
              </div>
            ) : rows.length === 0 ? (
              <div className="mx-auto max-w-md px-4 py-12 text-center text-cuerpo leading-relaxed text-ink-3">
                {query || bucket
                  ? "Sin resultados para este filtro."
                  : tab === "open"
                    ? "Sin facturas por cobrar. Sincroniza tus fuentes para traer pedidos, o quizá ya cobraste todo."
                    : "Aún no hay pagadas. Cuando registres o confirmes un pago, quedará aquí con su registro."}
                {!query && !bucket && tab === "open" && (
                  <span className="mt-3 flex items-center justify-center gap-3">
                    <Link
                      href="/importar"
                      className="font-medium text-accent-ink hover:underline"
                    >
                      Subir mi Excel
                    </Link>
                    <Link
                      href="/integraciones"
                      className="font-medium text-accent-ink hover:underline"
                    >
                      Conectar mi sistema
                    </Link>
                  </span>
                )}
              </div>
            ) : (
              <>
                <div className="hidden overflow-x-auto md:block">
                  <table className="w-full min-w-[720px]">
                    <thead>
                      <tr className="border-b border-line bg-panel/60 text-apoyo font-semibold text-ink-3">
                        <Th label="Folio" sortKey="folio" />
                        <Th label="Cliente" sortKey="customer" />
                        <Th label="Monto" sortKey="amount" right />
                        <Th label={tab === "open" ? "Atraso" : "Pagada"} sortKey="days_overdue" right />
                        <Th label="Estado" />
                        {tab === "open" && <Th label="Acciones" right />}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((inv) => (
                        <tr
                          key={inv.id}
                          onClick={() => setOpenId(inv.id)}
                          className="group cursor-pointer border-b border-line/60 text-left transition-colors last:border-0 hover:bg-panel/40"
                        >
                          <td className="px-4 py-2.5">
                            {/* Botón real (no solo tr onClick): el detalle se abre con teclado. */}
                            <button
                              onClick={() => setOpenId(inv.id)}
                              className="tnum block text-left text-cuerpo font-medium text-ink hover:text-accent-ink"
                            >
                              {inv.folio}
                            </button>
                            <SourceBadge
                              source={tab === "paid" ? (inv.paid_source ?? inv.source) : inv.source}
                              verified={inv.verified}
                              presence={tab === "open" ? inv.presence : undefined}
                            />
                          </td>
                          <td className="px-4 py-2.5">
                            <span className="text-cuerpo font-medium text-ink">{inv.customer}</span>
                          </td>
                          <td className="tnum px-4 py-2.5 text-right text-cuerpo font-medium text-ink">
                            {mxn(inv.amount)}
                          </td>
                          <td className="tnum px-4 py-2.5 text-right text-cuerpo">
                            {tab === "paid" ? (
                              <span className="text-ink-2">
                                {inv.paid_at ? fechaDM(inv.paid_at) : "·"}
                              </span>
                            ) : inv.days_overdue > 0 ? (
                              <span className="font-medium text-danger">{inv.days_overdue} d</span>
                            ) : (
                              <span className="text-ink-3">en {-inv.days_overdue} d</span>
                            )}
                          </td>
                          <td className="px-4 py-2.5">
                            {tab === "paid" ? (
                              <span className="inline-flex items-center rounded bg-ok-soft px-1.5 py-px text-sello font-medium text-ok">
                                Pagada
                              </span>
                            ) : inv.payment_reported ? (
                              <span
                                title="El cliente dice que ya pagó. La factura sigue abierta hasta que tú lo confirmes."
                                className="inline-flex items-center rounded bg-warn-soft px-2 py-0.5 text-rotulo font-medium text-warn"
                              >
                                Cliente reporta pago
                              </span>
                            ) : (
                              <BucketPill bucket={inv.bucket} />
                            )}
                          </td>
                          {tab === "open" && (
                            <td className="px-4 py-2.5 text-right">
                              {done[inv.id] ? (
                                <span className="text-apoyo font-medium text-ok">{done[inv.id]}</span>
                              ) : inv.payment_reported ? (
                                <button
                                  disabled={!!busy[inv.id]}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    act(inv, "pay");
                                  }}
                                  className="rounded border border-ok/40 bg-ok-soft px-2 py-1 text-sello font-medium text-ok transition-colors hover:border-ok disabled:opacity-60"
                                >
                                  {busy[inv.id] ? "…" : "Confirmar pago"}
                                </button>
                              ) : (
                                <span className="flex justify-end gap-1.5">
                                  <RowAction
                                    label={busy[inv.id] === "remind" ? "Redactando…" : "Recordar"}
                                    title="Tu ayudante redacta un recordatorio y lo deja en Aprobaciones"
                                    disabled={!!busy[inv.id]}
                                    onClick={() => act(inv, "remind")}
                                  />
                                  <RowAction
                                    label={busy[inv.id] === "pay" ? "…" : "Registrar pago"}
                                    title="Confirmas tú el pago: queda como verificado manualmente"
                                    disabled={!!busy[inv.id]}
                                    onClick={() => act(inv, "pay")}
                                  />
                                </span>
                              )}
                            </td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Vista de tarjetas en móvil */}
                <ul className="divide-y divide-line/60 md:hidden">
                  {rows.map((inv) => (
                    <li key={inv.id} onClick={() => setOpenId(inv.id)} className="cursor-pointer px-4 py-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-cuerpo font-medium text-ink">{inv.customer}</p>
                          <p className="tnum mt-0.5 text-apoyo text-ink-3">{inv.folio}</p>
                        </div>
                        <p className="tnum shrink-0 text-seccion font-semibold text-ink">{mxn(inv.amount)}</p>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
                        <SourceBadge
                          source={tab === "paid" ? (inv.paid_source ?? inv.source) : inv.source}
                          verified={inv.verified}
                          presence={tab === "open" ? inv.presence : undefined}
                        />
                        {tab === "paid" ? (
                          <span className="inline-flex items-center rounded bg-ok-soft px-1.5 py-px text-sello font-medium text-ok">
                            Pagada
                          </span>
                        ) : inv.payment_reported ? (
                          <span className="inline-flex items-center rounded bg-warn-soft px-2 py-0.5 text-rotulo font-medium text-warn">
                            Cliente reporta pago
                          </span>
                        ) : (
                          <>
                            <BucketPill bucket={inv.bucket} />
                            {inv.days_overdue > 0 ? (
                              <span className="tnum text-apoyo font-medium text-danger">{inv.days_overdue} d de atraso</span>
                            ) : (
                              <span className="tnum text-apoyo text-ink-3">vence en {-inv.days_overdue} d</span>
                            )}
                          </>
                        )}
                      </div>
                      {tab === "open" && (
                        <div className="mt-2.5">
                          {done[inv.id] ? (
                            <span className="text-apoyo font-medium text-ok">{done[inv.id]}</span>
                          ) : inv.payment_reported ? (
                            <button
                              disabled={!!busy[inv.id]}
                              onClick={(e) => {
                                e.stopPropagation();
                                act(inv, "pay");
                              }}
                              className="w-full rounded-md border border-ok/40 bg-ok-soft py-2 text-cuerpo font-medium text-ok transition-colors hover:border-ok disabled:opacity-60"
                            >
                              {busy[inv.id] ? "…" : "Confirmar pago"}
                            </button>
                          ) : (
                            <div className="flex gap-2">
                              <button
                                disabled={!!busy[inv.id]}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  act(inv, "remind");
                                }}
                                className="flex-1 rounded-md border border-line bg-surface py-2 text-cuerpo font-medium text-ink-2 transition-colors hover:border-accent hover:text-accent-ink disabled:opacity-60"
                              >
                                {busy[inv.id] === "remind" ? "Redactando…" : "Recordar"}
                              </button>
                              <button
                                disabled={!!busy[inv.id]}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  act(inv, "pay");
                                }}
                                className="flex-1 rounded-md border border-line bg-surface py-2 text-cuerpo font-medium text-ink-2 transition-colors hover:border-accent hover:text-accent-ink disabled:opacity-60"
                              >
                                {busy[inv.id] === "pay" ? "…" : "Registrar pago"}
                              </button>
                            </div>
                          )}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </RailLayout>

      <InvoiceDrawer invoiceId={openId} onClose={() => setOpenId(null)} onChanged={refetch} />
    </div>
  );
}

// Resumen de antigüedad: la barra de cartera (misma que el Resumen) hecha filtro.
// Cada tramo es clickeable — enfoca la tabla en ese tramo, no es decoración.
function AgingResumen({
  aging,
  total,
  count,
  active,
  onPick,
  loading,
}: {
  aging: { bucket: string; count: number; total: number }[];
  total: number;
  count: number;
  active: string | null;
  onPick: (b: string | null) => void;
  loading: boolean;
}) {
  if (loading) return <Skeleton className="mb-4 h-[92px] w-full rounded-lg" />;
  if (aging.length === 0) return null;
  return (
    <div className="reveal elev-sm mb-4 rounded-lg border border-line bg-surface px-4 py-3.5">
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-2.5">
          <span className="hero-num text-cifra font-semibold leading-none text-ink">
            <AnimatedNumber value={total} format={mxn} />
          </span>
          <span className="text-cuerpo text-ink-3">
            por cobrar · {count} {count === 1 ? "factura" : "facturas"}
          </span>
        </div>
        {active && (
          <button
            onClick={() => onPick(null)}
            className="shrink-0 text-apoyo text-ink-3 transition-colors hover:text-ink"
          >
            Ver todas
          </button>
        )}
      </div>
      <div className="mt-2.5 flex h-2 w-full gap-px overflow-hidden rounded-full bg-line/40">
        {aging
          .filter((l) => l.total > 0)
          .map((l) => (
            <button
              key={l.bucket}
              title={`${BUCKET_META[l.bucket].label}: ${mxn(l.total)}`}
              onClick={() => onPick(active === l.bucket ? null : l.bucket)}
              className={`${BUCKET_META[l.bucket].bar} transition-opacity hover:opacity-80 ${
                active && active !== l.bucket ? "opacity-25" : ""
              }`}
              style={{ width: `${Math.max((l.total / (total || 1)) * 100, 2)}%` }}
            />
          ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2">
        {aging.map((l) => {
          const on = active === l.bucket;
          return (
            <button
              key={l.bucket}
              onClick={() => onPick(on ? null : l.bucket)}
              title={`Ver ${BUCKET_META[l.bucket].label.toLowerCase()}`}
              className={`group flex items-center gap-2 transition-opacity ${
                active && !on ? "opacity-45 hover:opacity-100" : ""
              }`}
            >
              <span className={`h-2 w-2 rounded-[3px] ${BUCKET_META[l.bucket].bar}`} />
              <span className="text-cuerpo text-ink-2 group-hover:text-ink">{BUCKET_META[l.bucket].label}</span>
              <span className="tnum text-cuerpo font-medium text-ink">{mxn(l.total)}</span>
              <span className="tnum text-apoyo text-ink-3">· {l.count}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// Riel de contexto: las dos preguntas de cobranza (a quién apretar, qué se viene),
// derivadas de la misma cartera. No es un panel de adorno: son atajos de decisión.
function FacturasRail({
  deudores,
  porVencer,
  loading,
}: {
  deudores: { customer: string; total: number }[];
  porVencer: InvoiceItem[];
  loading: boolean;
}) {
  if (loading) {
    return (
      <>
        <Skeleton className="h-40 w-full rounded-lg" />
        <Skeleton className="h-40 w-full rounded-lg" />
      </>
    );
  }
  return (
    <>
      <RailSection label="Quién debe más">
        {deudores.map((d, i) => (
          <RailRow key={d.customer}>
            <span className="flex min-w-0 items-center gap-2.5">
              <span className="tnum w-3 shrink-0 text-apoyo text-ink-3">{i + 1}</span>
              <span className="truncate text-cuerpo text-ink-2">{d.customer}</span>
            </span>
            <span className="tnum shrink-0 text-cuerpo font-medium text-ink">{mxn(d.total)}</span>
          </RailRow>
        ))}
      </RailSection>

      <RailSection label="Vence esta semana">
        {porVencer.length === 0 ? (
          <p className="text-cuerpo leading-relaxed text-ink-3">
            Nada vence en los próximos 7 días. Vas al corriente.
          </p>
        ) : (
          porVencer.map((inv) => (
            <RailRow key={inv.id}>
              <span className="min-w-0">
                <span className="block truncate text-cuerpo text-ink-2">{inv.customer}</span>
                <span className="text-apoyo text-ink-3">
                  {inv.days_overdue === 0 ? "vence hoy" : `en ${-inv.days_overdue} d`}
                </span>
              </span>
              <span className="tnum shrink-0 text-cuerpo font-medium text-ink">{mxn(inv.amount)}</span>
            </RailRow>
          ))
        )}
      </RailSection>
    </>
  );
}

function RowAction({
  label,
  title,
  disabled,
  onClick,
}: {
  label: string;
  title: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      title={title}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className="rounded border border-line bg-surface px-2 py-1 text-sello font-medium text-ink-2 opacity-100 transition-all hover:border-accent hover:text-accent-ink focus-visible:opacity-100 disabled:opacity-60 md:opacity-60 md:group-hover:opacity-100 md:group-focus-within:opacity-100"
    >
      {label}
    </button>
  );
}
