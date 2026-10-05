"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { api, type CustomerItem, type Tag } from "@/lib/api";
import { Saldo } from "@/components/cartera-partes";
import { dinero, dineroPorMoneda, totalesPorMoneda } from "@/lib/cartera";
import { telefonoMx } from "@/lib/format";
import {
  EmptyState,
  ErrorState,
  PageHeader,
  PrimaryButton,
  PrimaryLink,
  SearchInput,
  SecondaryButton,
  Skeleton,
  Tabs,
  useApi,
} from "@/components/ui";
import { RailLayout, RailRow, RailSection, RailStat } from "@/components/rail";
import { TagChip, TagManager } from "@/components/tags";
import { AgregarSheet } from "@/components/agregar-sheet";
import { Drawer } from "@/components/drawer";
import { ExportButton } from "@/components/export-button";

type Ver = "todos" | "clientes" | "prospectos";

export default function ClientesPage() {
  // useSearchParams (?ver=prospectos) exige un boundary de Suspense en el export estático.
  return (
    <Suspense fallback={<div className="min-w-0" />}>
      <Clientes />
    </Suspense>
  );
}

function Clientes() {
  const router = useRouter();
  // Clientes y prospectos comparten tabla (Customer.kind) y comparten esta lista: un
  // prospecto es alguien a quien todavía no le facturas, no otra pantalla.
  const { data: todos, error, loading, refetch } = useApi<CustomerItem[]>(() => api.customers(), []);
  const lista = useMemo(() => todos ?? [], [todos]);
  const clientes = useMemo(() => lista.filter((c) => c.kind !== "prospecto"), [lista]);
  const prospectos = useMemo(() => lista.filter((c) => c.kind === "prospecto"), [lista]);
  const [elegido, setElegido] = useState<Ver | null>(
    useSearchParams().get("ver") === "prospectos" ? "prospectos" : null,
  );
  const ver: Ver = prospectos.length === 0 ? "todos" : (elegido ?? "todos");
  const [query, setQuery] = useState("");
  const [allTags, setAllTags] = useState<Tag[]>([]);
  const [filterTag, setFilterTag] = useState<string | null>(null);
  const [agregar, setAgregar] = useState(false);
  const [etiquetas, setEtiquetas] = useState(false);

  const cargarEtiquetas = useCallback(() => {
    api.tags().then(setAllTags).catch(() => {});
  }, []);
  useEffect(cargarEtiquetas, [cargarEtiquetas]);

  const tagById = useMemo(() => Object.fromEntries(allTags.map((t) => [t.id, t])), [allTags]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const base = ver === "prospectos" ? prospectos : ver === "clientes" ? clientes : lista;
    return base.filter(
      (c) =>
        (!q || c.name.toLowerCase().includes(q) || c.phone?.toLowerCase().includes(q)) &&
        (!filterTag || (c.tags ?? []).includes(filterTag)),
    );
  }, [lista, clientes, prospectos, ver, query, filterTag]);

  // Resumen de cartera, derivado de los mismos clientes (riel de contexto). Cada
  // moneda por su lado: lo que un cliente debe en dólares no se suma a los pesos.
  const resumen = useMemo(() => {
    const saldos = clientes.flatMap((c) => c.por_moneda ?? []);
    const totales = totalesPorMoneda(
      saldos,
      (s) => s.open_total,
      (s) => s.moneda,
    );
    return {
      cartera: dineroPorMoneda(totales),
      // La moneda en la que se ordena "Mayor saldo": la principal del negocio.
      moneda: totales[0]?.moneda ?? "MXN",
      conSaldo: clientes.filter((c) => c.open_invoices > 0).length,
      sinTel: clientes.filter((c) => !c.phone).length,
    };
  }, [clientes]);

  const mayorSaldo = useMemo(() => {
    const debe = (c: CustomerItem) =>
      (c.por_moneda ?? []).find((s) => s.moneda === resumen.moneda)?.open_total ?? 0;
    return clientes
      .filter((c) => debe(c) > 0)
      .sort((a, b) => debe(b) - debe(a))
      .slice(0, 6)
      .map((c) => ({ ...c, debe: debe(c) }));
  }, [clientes, resumen.moneda]);

  if (error) return <ErrorState message={error} retry={refetch} />;

  const hayGente = lista.length > 0;

  return (
    <div className="min-w-0">
      <PageHeader
        title="Clientes"
        subtitle="A quién le vendes y cuánto te debe cada uno."
        right={
          hayGente ? (
            <div className="flex flex-wrap items-center gap-2">
              <ExportButton
                entidad={ver === "prospectos" ? "prospectos" : "clientes"}
                filtros={{ q: query, tag: filterTag }}
                count={rows.length}
              />
              <SecondaryButton onClick={() => setEtiquetas(true)}>Etiquetas</SecondaryButton>
              <PrimaryButton onClick={() => setAgregar(true)}>Agregar cliente</PrimaryButton>
            </div>
          ) : undefined
        }
      />
      <AgregarSheet open={agregar} onClose={() => setAgregar(false)} tipo="clientes" label="cliente" onCreated={refetch} />
      <Drawer
        open={etiquetas}
        onClose={() => {
          setEtiquetas(false);
          cargarEtiquetas();
        }}
        title="Etiquetas"
        subtitle="Para agrupar a tus clientes a tu manera"
      >
        <TagManager />
      </Drawer>

      {loading && (
        <div className="space-y-2">
          <Skeleton className="h-10 w-72" />
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      )}

      {!loading && !hayGente && (
        <EmptyState title="Aún no hay clientes" action={<PrimaryLink href="/importar">Subir mi Excel</PrimaryLink>}>
          Falta tu lista de clientes. Súbela en un Excel, tal como la llevas; también entran solos
          al subir tus facturas.
        </EmptyState>
      )}

      {hayGente && (
        <RailLayout
          rail={
            <>
              <RailSection label="Cartera">
                <RailStat label="Por cobrar" value={resumen.cartera} strong />
                <RailStat label="Clientes con saldo" value={String(resumen.conSaldo)} />
                <RailStat
                  label="Sin WhatsApp"
                  value={String(resumen.sinTel)}
                  hint={resumen.sinTel > 0 ? "no puedes cobrarles por chat" : undefined}
                />
              </RailSection>

              {mayorSaldo.length > 0 && (
                <RailSection label="Mayor saldo">
                  {mayorSaldo.map((c) => (
                    <RailRow key={c.id}>
                      <Link
                        href={`/clientes/detalle?id=${c.id}`}
                        className="min-w-0 truncate text-cuerpo text-ink-2 hover:text-accent-ink hover:underline"
                      >
                        {c.name}
                      </Link>
                      <span className="tnum shrink-0 text-cuerpo font-medium text-ink">
                        {dinero(c.debe, resumen.moneda)}
                      </span>
                    </RailRow>
                  ))}
                </RailSection>
              )}
            </>
          }
        >
          {prospectos.length > 0 && (
            <Tabs
              tabs={[
                { key: "todos", label: "Todos", count: lista.length },
                { key: "clientes", label: "Clientes", count: clientes.length },
                { key: "prospectos", label: "Prospectos", count: prospectos.length },
              ]}
              active={ver}
              onChange={(k) => setElegido(k as Ver)}
            />
          )}
          <div className="mb-5 flex flex-wrap items-center gap-x-3 gap-y-2">
            <SearchInput value={query} onChange={setQuery} placeholder="Buscar por nombre o WhatsApp" />
            {allTags.map((t) => (
              <button
                key={t.id}
                onClick={() => setFilterTag(filterTag === t.id ? null : t.id)}
                aria-pressed={filterTag === t.id}
                className={`rounded-full ${filterTag && filterTag !== t.id ? "opacity-40" : ""}`}
                title={`Ver solo ${t.name}`}
              >
                <TagChip tag={t} />
              </button>
            ))}
          </div>

          <div className="hidden overflow-x-auto md:block">
            <table className="w-full min-w-[620px] table-fixed text-left">
              <thead>
                <tr className="border-b border-line text-rotulo text-ink-3">
                  <th className="px-4 pb-3 font-medium">Nombre</th>
                  <th className="w-44 px-4 pb-3 font-medium">WhatsApp</th>
                  <th className="w-28 px-4 pb-3 text-right font-medium">Facturas</th>
                  <th className="w-40 px-4 pb-3 text-right font-medium">Te debe</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => {
                  const prospecto = c.kind === "prospecto";
                  const tags = (c.tags ?? []).map((id) => tagById[id]).filter(Boolean);
                  return (
                    <tr
                      key={c.id}
                      onClick={() => router.push(`/clientes/detalle?id=${c.id}`)}
                      className="cursor-pointer border-b border-line last:border-0 hover:bg-panel"
                    >
                      <td className="px-4 py-3.5">
                        {/* Una sola línea: el nombre se corta con puntos y lo demás no lo empuja. */}
                        <div className="flex min-w-0 items-center gap-2">
                          <Link
                            href={`/clientes/detalle?id=${c.id}`}
                            onClick={(e) => e.stopPropagation()}
                            title={c.name}
                            className="min-w-0 truncate text-cuerpo font-medium text-ink hover:text-accent-ink hover:underline"
                          >
                            {c.name}
                          </Link>
                          {prospecto && <span className="mark shrink-0">Prospecto</span>}
                          {tags.slice(0, 2).map((t) => (
                            <span key={t.id} className="shrink-0">
                              <TagChip tag={t} small />
                            </span>
                          ))}
                          {tags.length > 2 && (
                            <span className="tnum shrink-0 text-rotulo text-ink-3">+{tags.length - 2}</span>
                          )}
                        </div>
                      </td>
                      <td className="tnum truncate whitespace-nowrap px-4 py-3.5 text-cuerpo text-ink-2">
                        {c.phone ? telefonoMx(c.phone) : <span className="text-ink-3">Sin teléfono</span>}
                      </td>
                      <td className="tnum px-4 py-3.5 text-right text-cuerpo text-ink-2">
                        {prospecto ? <span className="text-ink-3">·</span> : c.open_invoices}
                      </td>
                      <td className="tnum whitespace-nowrap px-4 py-3.5 text-right text-cuerpo font-semibold text-ink">
                        {c.open_invoices > 0 ? (
                          <Saldo por={c.por_moneda} />
                        ) : (
                          <span className="font-normal text-ink-3">·</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* En el teléfono: nombre en una línea y lo que debe, al frente. */}
          <ul className="md:hidden">
            {rows.map((c) => (
              <li key={c.id} className="border-b border-line last:border-0">
                <Link href={`/clientes/detalle?id=${c.id}`} className="flex items-center gap-3 py-3.5">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-cuerpo font-medium text-ink">{c.name}</p>
                    <p className="tnum truncate text-apoyo text-ink-3">
                      {c.kind === "prospecto" ? "Prospecto · " : ""}
                      {c.phone ? telefonoMx(c.phone) : "Sin teléfono"}
                    </p>
                  </div>
                  {c.open_invoices > 0 && (
                    <span className="tnum shrink-0 text-right text-cuerpo font-semibold text-ink">
                      <Saldo por={c.por_moneda} />
                    </span>
                  )}
                </Link>
              </li>
            ))}
          </ul>

          {rows.length === 0 && (
            <p className="px-4 py-12 text-center text-cuerpo text-ink-3">
              Nadie coincide con lo que buscas.
            </p>
          )}
        </RailLayout>
      )}
    </div>
  );
}
