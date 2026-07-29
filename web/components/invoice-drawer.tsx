"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, type InvoiceDetail } from "@/lib/api";
import { Drawer } from "@/components/drawer";
import { InvoiceDetailContent } from "@/components/invoice-detail";
import { ErrorState } from "@/components/ui";

export function InvoiceDrawer({
  invoiceId,
  onClose,
  onChanged,
}: {
  invoiceId: string | null;
  onClose: () => void;
  onChanged?: () => void;
}) {
  const [data, setData] = useState<InvoiceDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Guarda estilo useApi: cada fetch lleva su runId; solo la respuesta de la
  // factura abierta AHORA se aplica. Cambiar rápido de factura ya no pinta el
  // folio/monto de otra.
  const runIdRef = useRef(0);

  const load = useCallback(() => {
    if (!invoiceId) {
      runIdRef.current++;
      setData(null);
      setError(null);
      return;
    }
    const runId = ++runIdRef.current;
    setLoading(true);
    setError(null);
    api
      .invoiceDetail(invoiceId)
      .then((d) => {
        if (runId !== runIdRef.current) return;
        setData(d);
      })
      .catch((e: Error) => {
        // No lo tragues: una pantalla de cobranza en blanco esconde el fallo de red.
        if (runId === runIdRef.current) setError(e.message);
      })
      .finally(() => {
        if (runId === runIdRef.current) setLoading(false);
      });
  }, [invoiceId]);

  useEffect(() => {
    // Nueva factura: pizarra limpia para no mostrar el detalle de la anterior.
    setData(null);
    setError(null);
    load();
    return () => {
      runIdRef.current++; // invalida el fetch en curso al cambiar de factura o desmontar
    };
  }, [load]);

  // Refresca el detalle y avisa al padre (la lista) para que también se actualice.
  const refresh = useCallback(() => {
    load();
    onChanged?.();
  }, [load, onChanged]);

  return (
    <Drawer
      open={!!invoiceId}
      onClose={onClose}
      title={data?.folio ?? "Factura"}
      subtitle={data?.customer}
    >
      {loading && !data ? (
        <div className="space-y-3">
          <div className="skeleton h-16 w-full rounded-lg" />
          <div className="skeleton h-24 w-full rounded-lg" />
        </div>
      ) : error && !data ? (
        <ErrorState message={error} retry={load} />
      ) : data ? (
        <div className="space-y-4">
          <Link
            href={`/facturas/detalle?id=${data.id}`}
            className="inline-flex items-center gap-1.5 text-[12px] font-medium text-accent-ink hover:underline"
          >
            <svg viewBox="0 0 12 12" className="h-3 w-3" fill="none">
              <path d="M2 7v3h3M10 5V2H7M10 2 6.5 5.5M2 10l3.5-3.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Abrir vista completa
          </Link>
          <InvoiceDetailContent data={data} onChanged={refresh} />
        </div>
      ) : null}
    </Drawer>
  );
}
