"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, type CustomerItem } from "@/lib/api";
import {
  EmptyState,
  ErrorState,
  PageHeader,
  SearchInput,
  Skeleton,
  SOURCE_LABEL,
  useApi,
} from "@/components/ui";
import { RailLayout, RailRow, RailSection, RailStat } from "@/components/rail";
import { ExportButton } from "@/components/export-button";

// Liga al buscador de negocios (DENUE · INEGI): el "Agregar" de esta página
// lleva a la fuente, como en el resto de la consola.
function BuscarNegociosLink() {
  return (
    <Link
      href="/prospectos/buscar"
      className="inline-flex rounded-md bg-accent px-3 py-1.5 text-[12.5px] font-medium text-surface transition-colors hover:bg-accent-strong"
    >
      Buscar negocios
    </Link>
  );
}

export default function ProspectosPage() {
  const { data, error, loading, refetch } = useApi<CustomerItem[]>(() => api.customers("prospecto"), []);
  const [query, setQuery] = useState("");
  const router = useRouter();

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data ?? []).filter(
      (c) =>
        !q ||
        c.name.toLowerCase().includes(q) ||
        (c.meta?.empresa ?? "").toLowerCase().includes(q) ||
        c.phone?.toLowerCase().includes(q),
    );
  }, [data, query]);

  // Resumen de prospección, derivado de los mismos prospectos (riel de contexto).
  const total = (data ?? []).length;
  const conTel = useMemo(() => (data ?? []).filter((c) => c.phone).length, [data]);
  const porOrigen = useMemo(() => {
    const acc = new Map<string, number>();
    for (const c of data ?? []) {
      const o = (c.meta?.origen as string) || "Sin origen";
      acc.set(o, (acc.get(o) ?? 0) + 1);
    }
    return [...acc.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
  }, [data]);

  if (error) return <ErrorState message={error} retry={refetch} />;

  return (
    <div className="min-w-0">
      <PageHeader
        title="Prospectos"
        subtitle="Posibles clientes por contactar. Aún no compran: cuando lo hagan, pasan a Clientes."
        right={
          <div className="flex items-center gap-2">
            <ExportButton entidad="prospectos" filtros={{ q: query }} count={rows.length} />
            <BuscarNegociosLink />
          </div>
        }
      />

      {loading && <Skeleton className="h-32 w-full" />}

      {!loading && total === 0 && (
        <EmptyState title="Aún no hay prospectos" action={<BuscarNegociosLink />}>
          Busca negocios reales en el directorio público del INEGI (DENUE) y cárgalos aquí, o
          súbelos desde un Excel en Importar (la IA reconoce listas de prospectos con su origen
          y empresa).
        </EmptyState>
      )}

      {total > 0 && (
        <RailLayout
          rail={
            <>
              <RailSection label="Prospección">
                <RailStat label="Prospectos" value={String(total)} strong />
                <RailStat
                  label="Con WhatsApp"
                  value={`${conTel} de ${total}`}
                  hint={conTel < total ? "solo esos son contactables" : undefined}
                />
              </RailSection>

              {porOrigen.length > 0 && (
                <RailSection label="Por origen">
                  {porOrigen.map(([origen, n]) => (
                    <RailRow key={origen}>
                      <span className="truncate text-[12.5px] text-ink-2">
                        {SOURCE_LABEL[origen] ?? origen}
                      </span>
                      <span className="tnum shrink-0 text-[12.5px] font-medium text-ink">{n}</span>
                    </RailRow>
                  ))}
                </RailSection>
              )}
            </>
          }
        >
          <div className="mb-3">
            <SearchInput value={query} onChange={setQuery} placeholder="Buscar por nombre o empresa…" />
          </div>
          <div className="reveal overflow-x-auto rounded-lg border border-line bg-surface">
            <table className="w-full min-w-[560px] text-left">
              <thead>
                <tr className="border-b border-line bg-panel/60 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">
                  <th className="px-4 py-2.5">Prospecto</th>
                  <th className="px-4 py-2.5">Empresa</th>
                  <th className="px-4 py-2.5">Origen</th>
                  <th className="px-4 py-2.5">WhatsApp</th>
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
                      {/* Liga real (no solo tr onClick): navegable con teclado. */}
                      <Link
                        href={`/clientes/detalle?id=${c.id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="text-[12.5px] font-medium text-ink hover:text-accent-ink hover:underline"
                      >
                        {c.name}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-[12px] text-ink-2">
                      {c.meta?.empresa ?? <span className="text-ink-3">·</span>}
                    </td>
                    <td className="px-4 py-2.5 text-[12px] text-ink-2">
                      {c.meta?.origen ? (
                        (SOURCE_LABEL[c.meta.origen] ?? c.meta.origen)
                      ) : (
                        <span className="text-ink-3">·</span>
                      )}
                    </td>
                    <td className="tnum px-4 py-2.5 text-[12px] text-ink-2">
                      {c.phone ?? <span className="text-ink-3">sin teléfono</span>}
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
        </RailLayout>
      )}
    </div>
  );
}
