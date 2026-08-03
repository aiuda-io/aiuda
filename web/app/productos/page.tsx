"use client";

import { useMemo, useState } from "react";
import { unidad } from "@/lib/format";
import { api, mxn, type ProductItem } from "@/lib/api";
import { EmptyState, ErrorState, PageHeader, PrimaryButton, PrimaryLink, SearchInput, SecondaryButton, SecondaryLink, Skeleton, SOURCE_LABEL, useApi } from "@/components/ui";
import { RailLayout, RailRow, RailSection, RailStat } from "@/components/rail";
import { RecordDrawer } from "@/components/record-drawer";
import { NuevaCotizacion } from "@/components/nueva-cotizacion";
import { fuenteEspejo } from "@/components/provenance";
import { AgregarSheet } from "@/components/agregar-sheet";
import { ExportButton } from "@/components/export-button";

export default function ProductosPage() {
  const { data, error, loading, refetch } = useApi<ProductItem[]>(api.products);
  const [query, setQuery] = useState("");
  const [cotizar, setCotizar] = useState(false);
  const [agregar, setAgregar] = useState(false);
  const [selected, setSelected] = useState<ProductItem | null>(null);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data ?? []).filter(
      (p) => !q || p.name.toLowerCase().includes(q) || (p.sku ?? "").toLowerCase().includes(q),
    );
  }, [data, query]);

  // Salud del catálogo, derivada de los mismos productos (riel de contexto).
  const resumen = useMemo(() => {
    const list = data ?? [];
    return {
      total: list.length,
      conPrecio: list.filter((p) => p.price !== null).length,
      conStock: list.filter((p) => p.stock !== null).length,
    };
  }, [data]);
  const agotados = useMemo(
    () => (data ?? []).filter((p) => p.stock !== null && p.stock <= 0).slice(0, 6),
    [data],
  );

  if (error) return <ErrorState message={error} retry={refetch} />;

  const hayProductos = (data ?? []).length > 0;

  return (
    <div className="min-w-0">
      <PageHeader
        title="Productos"
        subtitle="Tu catálogo. Lo usan tus ayudantes de ventas y de compras. Súbelo desde Excel."
        right={
          <div className="flex items-center gap-2">
            <ExportButton entidad="productos" filtros={{ q: query }} count={rows.length} />
            {hayProductos && (
              <SecondaryButton onClick={() => setCotizar(true)}>Nueva cotización</SecondaryButton>
            )}
            <PrimaryButton onClick={() => setAgregar(true)}>Agregar producto</PrimaryButton>
          </div>
        }
      />

      <NuevaCotizacion open={cotizar} onClose={() => setCotizar(false)} productos={data ?? []} />
      <AgregarSheet open={agregar} onClose={() => setAgregar(false)} tipo="productos" label="producto" onCreated={refetch} />

      {loading && <Skeleton className="h-32 w-full" />}

      {!loading && !hayProductos && (
        <EmptyState
          title="Aún no hay productos"
          action={
            <div className="flex flex-wrap items-center justify-center gap-2">
              <PrimaryLink href="/importar">Subir mi catálogo</PrimaryLink>
              <SecondaryLink href="/integraciones">Conectar mi tienda</SecondaryLink>
            </div>
          }
        >
          Sube tu catálogo desde un Excel (la IA detecta nombre, SKU, precio y existencia) o,
          más adelante, entran desde tu tienda u Odoo.
        </EmptyState>
      )}

      {hayProductos && (
        <RailLayout
          rail={
            <>
              <RailSection label="Catálogo">
                <RailStat label="Productos" value={String(resumen.total)} strong />
                <RailStat label="Con precio" value={`${resumen.conPrecio} de ${resumen.total}`} />
                {resumen.conStock > 0 && (
                  <RailStat label="Con existencia" value={`${resumen.conStock} de ${resumen.total}`} />
                )}
              </RailSection>

              {agotados.length > 0 && (
                <RailSection label="Agotados">
                  {agotados.map((p) => (
                    <RailRow key={p.id}>
                      <button
                        onClick={() => setSelected(p)}
                        className="min-w-0 truncate text-left text-cuerpo text-ink-2 transition-colors hover:text-accent-ink"
                      >
                        {p.name}
                      </button>
                      <span className="tnum shrink-0 text-apoyo text-ink-3">
                        0{p.unit ? ` ${unidad(p.unit)}` : ""}
                      </span>
                    </RailRow>
                  ))}
                </RailSection>
              )}
            </>
          }
        >
          <div className="mb-3">
            <SearchInput value={query} onChange={setQuery} placeholder="Buscar por nombre o SKU…" />
          </div>
          <div className="overflow-x-auto rounded-lg border border-line bg-surface">
            <table className="w-full min-w-[620px] text-left">
              <thead>
                <tr className="border-b border-line bg-panel/60 text-rotulo font-semibold uppercase tracking-[0.06em] text-ink-3">
                  <th className="px-4 py-2.5">Producto</th>
                  <th className="px-4 py-2.5">SKU</th>
                  <th className="px-4 py-2.5">Fuente</th>
                  <th className="px-4 py-2.5 text-right">Precio</th>
                  <th className="px-4 py-2.5 text-right">Existencia</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => {
                  const src = fuenteEspejo(p.presence);
                  return (
                  <tr
                    key={p.id}
                    onClick={() => setSelected(p)}
                    className="cursor-pointer border-b border-line/60 last:border-0 hover:bg-panel/40"
                  >
                    <td className="px-4 py-2.5">
                      {/* Botón real (no solo tr onClick): la ficha se abre con teclado. */}
                      <button
                        onClick={() => setSelected(p)}
                        className="text-left text-cuerpo font-medium text-ink hover:text-accent-ink"
                      >
                        {p.name}
                      </button>
                    </td>
                    <td className="tnum px-4 py-2.5 text-cuerpo text-ink-2">
                      {p.sku ?? <span className="text-ink-3">·</span>}
                    </td>
                    <td className="px-4 py-2.5 text-cuerpo">
                      <span className="rounded bg-panel px-1.5 py-px font-medium text-ink-2">
                        {src ? (SOURCE_LABEL[src] ?? src) : "aiuda"}
                      </span>
                    </td>
                    <td className="tnum px-4 py-2.5 text-right text-cuerpo text-ink">
                      {p.price !== null ? mxn(p.price) : <span className="text-ink-3">·</span>}
                    </td>
                    <td className="tnum px-4 py-2.5 text-right text-cuerpo text-ink-2">
                      {p.stock !== null ? (
                        <>
                          {p.stock}
                          {p.unit ? ` ${unidad(p.unit)}` : ""}
                        </>
                      ) : (
                        <span className="text-ink-3">·</span>
                      )}
                    </td>
                  </tr>
                  );
                })}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-10 text-center text-cuerpo text-ink-3">
                      Sin resultados para tu búsqueda.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </RailLayout>
      )}

      <RecordDrawer
        open={selected !== null}
        onClose={() => setSelected(null)}
        title={selected?.name ?? ""}
        subtitle={selected?.sku ? `SKU ${selected.sku}` : "Producto"}
        fields={
          selected
            ? [
                { label: "Precio", value: selected.price !== null ? mxn(selected.price) : null },
                {
                  label: "Existencia",
                  value:
                    selected.stock !== null
                      ? `${selected.stock}${selected.unit ? ` ${selected.unit}` : ""}`
                      : null,
                },
                { label: "SKU", value: selected.sku },
                { label: "Unidad", value: selected.unit },
              ]
            : []
        }
        meta={selected?.meta}
        presence={selected?.presence}
      />
    </div>
  );
}
