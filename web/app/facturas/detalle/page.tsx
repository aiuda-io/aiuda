"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { api, type InvoiceDetail } from "@/lib/api";
import { ErrorState, Skeleton, useApi } from "@/components/ui";
import { InvoiceDetailContent } from "@/components/invoice-detail";
import { usePageTrail } from "@/components/rastro";

// Un folio provisional (borrador-N) es un marcador interno; no se muestra crudo al usuario.
function folioTitulo(folio: string): string {
  return folio.startsWith("borrador-") ? "Factura en borrador" : folio;
}

export default function FacturaDetallePage() {
  // useSearchParams exige un boundary de Suspense en el export estático.
  return (
    <Suspense fallback={null}>
      <FacturaDetalle />
    </Suspense>
  );
}

function FacturaDetalle() {
  const id = useSearchParams().get("id") ?? "";
  const { data, error, loading, refetch } = useApi<InvoiceDetail>(() => api.invoiceDetail(id), [id]);
  usePageTrail(
    data?.folio
      ? data.folio.startsWith("borrador-")
        ? "Factura en borrador"
        : `Factura ${data.folio}`
      : "Factura",
  );

  if (error) return <ErrorState message={error} retry={refetch} />;

  return (
    <div className="min-w-0">
      {loading && !data ? (
        <div className="space-y-5">
          <Skeleton className="h-8 w-48" />
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_296px]">
            <Skeleton className="h-96 rounded-xl" />
            <div className="hidden space-y-4 lg:block">
              <Skeleton className="h-40 rounded-lg" />
              <Skeleton className="h-24 rounded-lg" />
            </div>
          </div>
        </div>
      ) : data ? (
        <>
          <header className="mb-5">
            <h1 className="tnum text-[18px] font-semibold tracking-tight text-ink">{folioTitulo(data.folio)}</h1>
            <p className="mt-0.5 text-[13px] text-ink-3">{data.customer}</p>
          </header>
          <InvoiceDetailContent data={data} onChanged={refetch} rail />
        </>
      ) : null}
    </div>
  );
}
