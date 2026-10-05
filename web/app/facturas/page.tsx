"use client";

// Cartera: lo que te deben, lo que te prometieron y lo que ya entró, en una sola
// pantalla con tres pestañas que viven en la dirección (?vista=promesas, ?vista=pagos)
// para que un enlace o el botón de atrás caigan en la pestaña correcta.
// /promesas y /conciliacion redirigen aquí.

import { Suspense, useEffect } from "react";
import { api, type ReconcileBandeja } from "@/lib/api";
import { PageHeader, SecondaryLink, Tabs, useApi, useQueryTab } from "@/components/ui";
import { CarteraFacturas } from "@/components/cartera-facturas";
import { CarteraPromesas } from "@/components/cartera-promesas";
import { CarteraPagos } from "@/components/cartera-pagos";
import { RUTA } from "@/lib/cartera";

const VISTAS = ["facturas", "promesas", "pagos"] as const;

export default function CarteraPage() {
  // useSearchParams exige un boundary de Suspense en el export estático.
  return (
    <Suspense fallback={null}>
      <Cartera />
    </Suspense>
  );
}

function Cartera() {
  // La pestaña vive en la dirección y cada una es un enlace de verdad.
  const [vista, hrefFor] = useQueryTab("vista", VISTAS);

  // Los números de las pestañas: cuántas promesas siguen abiertas y cuántos pagos
  // esperan confirmación. Se vuelven a contar tras cualquier escritura.
  const cartera = useApi(() => api.cartera());
  const pagos = useApi<ReconcileBandeja>(api.reconciliation);
  const recontarCartera = cartera.refetchQuiet;
  const recontarPagos = pagos.refetchQuiet;
  useEffect(() => {
    const recontar = () => {
      recontarCartera();
      recontarPagos();
    };
    window.addEventListener("aiuda-escritura", recontar);
    return () => window.removeEventListener("aiuda-escritura", recontar);
  }, [recontarCartera, recontarPagos]);


  return (
    <div className="min-w-0">
      <PageHeader
        title="Cartera"
        right={
          <>
            <SecondaryLink href={RUTA.sat}>Traer del SAT</SecondaryLink>
            <SecondaryLink href={RUTA.importar}>Importar Excel</SecondaryLink>
          </>
        }
      />

      <Tabs
        tabs={[
          { key: "facturas", label: "Facturas" },
          { key: "promesas", label: "Promesas", count: cartera.data?.active_promises || undefined },
          { key: "pagos", label: "Pagos", count: pagos.data?.count || undefined },
        ]}
        active={vista}
        hrefFor={hrefFor}
        label="Vistas de Cartera"
      />

      {vista === "facturas" && <CarteraFacturas />}
      {vista === "promesas" && <CarteraPromesas />}
      {vista === "pagos" && <CarteraPagos />}
    </div>
  );
}
