"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, mxn, type CustomerItem, type Tag } from "@/lib/api";
import { telefonoMx } from "@/lib/format";
import { EmptyState, ErrorState, PageHeader, PrimaryButton, PrimaryLink, SearchInput, SecondaryLink, Skeleton, useApi } from "@/components/ui";
import { RailLayout, RailRow, RailSection, RailStat } from "@/components/rail";
import { TagChip } from "@/components/tags";
import { AgregarSheet } from "@/components/agregar-sheet";
import { ExportButton } from "@/components/export-button";

export default function ClientesPage() {
  const router = useRouter();
  const { data, error, loading, refetch } = useApi<CustomerItem[]>(() => api.customers("cliente"), []);
  const [query, setQuery] = useState("");
  const [allTags, setAllTags] = useState<Tag[]>([]);
  const [filterTag, setFilterTag] = useState<string | null>(null);
  const [agregar, setAgregar] = useState(false);

  useEffect(() => {
    api.tags().then(setAllTags).catch(() => {});
  }, []);

  const tagById = useMemo(() => Object.fromEntries(allTags.map((t) => [t.id, t])), [allTags]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data ?? []).filter(
      (c) =>
        (!q || c.name.toLowerCase().includes(q) || c.phone?.toLowerCase().includes(q)) &&
        (!filterTag || (c.tags ?? []).includes(filterTag)),
    );
  }, [data, query, filterTag]);

  // Resumen de cartera, derivado de los mismos clientes (para el riel de contexto).
  const resumen = useMemo(() => {
    const list = data ?? [];
    return {
      cartera: list.reduce((a, c) => a + c.open_total, 0),
      conSaldo: list.filter((c) => c.open_total > 0).length,
      sinTel: list.filter((c) => !c.phone).length,
    };
  }, [data]);

  const mayorSaldo = useMemo(
    () =>
      (data ?? [])
        .filter((c) => c.open_total > 0)
        .sort((a, b) => b.open_total - a.open_total)
        .slice(0, 6),
    [data],
  );

  if (error) return <ErrorState message={error} retry={refetch} />;

  const hayClientes = (data ?? []).length > 0;

  return (
    <div className="min-w-0">
      <PageHeader
        title="Clientes"
        subtitle="Quienes ya te compran y tienen cartera. ¿Buscas posibles clientes? Ve a Prospectos."
        right={
          <div className="flex items-center gap-2">
            <ExportButton entidad="clientes" filtros={{ q: query, tag: filterTag }} count={rows.length} />
            <PrimaryButton onClick={() => setAgregar(true)}>Agregar cliente</PrimaryButton>
          </div>
        }
      />
      <AgregarSheet open={agregar} onClose={() => setAgregar(false)} tipo="clientes" label="cliente" onCreated={refetch} />

      {loading && (
        <div className="space-y-2">
          <Skeleton className="h-9 w-72 rounded-lg" />
          <Skeleton className="h-11 w-full rounded-lg" />
          <Skeleton className="h-11 w-full rounded-lg" />
          <Skeleton className="h-11 w-full rounded-lg" />
        </div>
      )}

      {!loading && !hayClientes && (
        <EmptyState
          title="Aún no hay clientes"
          action={
            <div className="flex flex-wrap items-center justify-center gap-2">
              <PrimaryLink href="/importar">Subir mi Excel</PrimaryLink>
              <SecondaryLink href="/integraciones">Conectar mi sistema</SecondaryLink>
            </div>
          }
        >
          Súbelos desde un Excel en Importar, o entran al importar facturas y conectar Odoo o tu
          tienda.
        </EmptyState>
      )}

      {hayClientes && (
        <RailLayout
          rail={
            <>
              <RailSection label="Cartera">
                <RailStat label="Por cobrar" value={mxn(resumen.cartera)} strong />
                <RailStat label="Clientes con saldo" value={String(resumen.conSaldo)} />
                <RailStat
                  label="Sin WhatsApp"
                  value={String(resumen.sinTel)}
                  hint={resumen.sinTel > 0 ? "no puedes cobrarles por chat" : undefined}
                />
              </RailSection>

              {mayorSaldo.length > 0 && (
                <RailSection label="Mayor saldo">
                  {mayorSaldo.map((c, i) => (
                    <RailRow key={c.id}>
                      <span className="flex min-w-0 items-center gap-2.5">
                        <span className="tnum w-3 shrink-0 text-[11px] text-ink-3">{i + 1}</span>
                        <Link
                          href={`/clientes/detalle?id=${c.id}`}
                          className="truncate text-[12.5px] text-ink-2 transition-colors hover:text-accent-ink hover:underline"
                        >
                          {c.name}
                        </Link>
                      </span>
                      <span className="tnum shrink-0 text-[12.5px] font-medium text-ink">
                        {mxn(c.open_total)}
                      </span>
                    </RailRow>
                  ))}
                </RailSection>
              )}
            </>
          }
        >
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <SearchInput value={query} onChange={setQuery} placeholder="Buscar por nombre o WhatsApp…" />
            {allTags.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                {allTags.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => setFilterTag(filterTag === t.id ? null : t.id)}
                    className={`rounded-full px-0.5 transition-opacity ${filterTag && filterTag !== t.id ? "opacity-40" : ""}`}
                    title={`Filtrar por ${t.name}`}
                  >
                    <TagChip tag={t} />
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="rounded-lg border border-line bg-surface">
            <div className="hidden overflow-x-auto md:block">
            <table className="w-full min-w-[560px] text-left">
              <thead>
                <tr className="border-b border-line bg-panel/60 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">
                  <th className="px-4 py-2.5">Cliente</th>
                  <th className="px-4 py-2.5">WhatsApp</th>
                  <th className="px-4 py-2.5 text-right">Facturas abiertas</th>
                  <th className="px-4 py-2.5 text-right">Saldo pendiente</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr
                    key={c.id}
                    onClick={() => router.push(`/clientes/detalle?id=${c.id}`)}
                    className="cursor-pointer border-b border-line/60 transition-colors last:border-0 hover:bg-panel/40"
                  >
                    <td className="px-4 py-2.5">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Link
                          href={`/clientes/detalle?id=${c.id}`}
                          onClick={(e) => e.stopPropagation()}
                          className="text-[12.5px] font-medium text-ink hover:text-accent-ink hover:underline"
                        >
                          {c.name}
                        </Link>
                        {(c.tags ?? [])
                          .map((id) => tagById[id])
                          .filter(Boolean)
                          .map((t) => (
                            <TagChip key={t.id} tag={t} small />
                          ))}
                      </div>
                    </td>
                    <td className="tnum px-4 py-2.5 text-[12px] text-ink-2">
                      {c.phone ? telefonoMx(c.phone) : <span className="text-ink-3">sin teléfono</span>}
                    </td>
                    <td className="tnum px-4 py-2.5 text-right text-[12.5px] text-ink-2">
                      {c.open_invoices}
                    </td>
                    <td className="tnum px-4 py-2.5 text-right text-[12.5px] font-medium text-ink">
                      {c.open_total > 0 ? mxn(c.open_total) : <span className="text-ink-3">$0.00</span>}
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-4 py-10 text-center text-[12.5px] text-ink-3">
                      Sin resultados para tu búsqueda.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            </div>

            {/* Tarjetas en móvil: el SALDO es el dato de cobranza, va al frente. */}
            <ul className="divide-y divide-line/60 md:hidden">
              {rows.map((c) => (
                <li key={c.id}>
                  <Link href={`/clientes/detalle?id=${c.id}`} className="block px-4 py-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-[13px] font-medium text-ink">{c.name}</p>
                        <p className="tnum mt-0.5 text-[11.5px] text-ink-3">
                          {c.phone ? telefonoMx(c.phone) : "sin teléfono"}
                        </p>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="tnum text-[13.5px] font-semibold text-ink">
                          {c.open_total > 0 ? mxn(c.open_total) : <span className="font-normal text-ink-3">$0.00</span>}
                        </p>
                        {c.open_invoices > 0 && (
                          <p className="tnum mt-0.5 text-[11.5px] text-ink-3">
                            {c.open_invoices} factura{c.open_invoices === 1 ? "" : "s"}
                          </p>
                        )}
                      </div>
                    </div>
                  </Link>
                </li>
              ))}
              {rows.length === 0 && (
                <li className="px-4 py-10 text-center text-[12.5px] text-ink-3">
                  Sin resultados para tu búsqueda.
                </li>
              )}
            </ul>
          </div>
        </RailLayout>
      )}
    </div>
  );
}
