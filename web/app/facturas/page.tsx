"use client";

// Cartera: lo que te deben, lo que te prometieron y lo que ya entró, en una sola
// pantalla con tres pestañas que viven en la dirección (?vista=promesas, ?vista=pagos)
// para que un enlace o el botón de atrás caigan en la pestaña correcta.
// /promesas y /conciliacion redirigen aquí.

import { Suspense, useEffect } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { api, type ReconcileBandeja } from "@/lib/api";
import { PageHeader, SecondaryLink, Tabs, useApi } from "@/components/ui";
import { CarteraFacturas } from "@/components/cartera-facturas";
import { CarteraPromesas } from "@/components/cartera-promesas";
import { CarteraPagos } from "@/components/cartera-pagos";
import { RUTA, type CarteraConMonedas } from "@/lib/cartera";

type Vista = "facturas" | "promesas" | "pagos";

function vistaDe(valor: string | null): Vista {
  return valor === "promesas" || valor === "pagos" ? valor : "facturas";
}

export default function CarteraPage() {
  // useSearchParams exige un boundary de Suspense en el export estático.
  return (
    <Suspense fallback={null}>
      <Cartera />
    </Suspense>
  );
}

function Cartera() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const vista = vistaDe(params.get("vista"));

  // Los números de las pestañas: cuántas promesas siguen abiertas y cuántos pagos
  // esperan confirmación. Se vuelven a contar tras cualquier escritura.
  const cartera = useApi<CarteraConMonedas>(() => api.cartera() as Promise<CarteraConMonedas>);
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

  const ir = (v: string) => {
    const next = new URLSearchParams(params.toString());
    if (v === "facturas") next.delete("vista");
    else next.set("vista", v);
    const q = next.toString();
    router.replace(q ? `${pathname}?${q}` : pathname, { scroll: false });
  };

  return (
    <div className="min-w-0">
      <PageHeader
        title="Cartera"
        right={
          <span className="flex flex-wrap items-center gap-2">
            <SecondaryLink href={RUTA.sat}>Traer del SAT</SecondaryLink>
            <SecondaryLink href={RUTA.importar}>Importar Excel</SecondaryLink>
          </span>
        }
      />

      <Tabs
        tabs={[
          { key: "facturas", label: "Facturas" },
          { key: "promesas", label: "Promesas", count: cartera.data?.active_promises || undefined },
          { key: "pagos", label: "Pagos", count: pagos.data?.count || undefined },
        ]}
        active={vista}
        onChange={ir}
      />

      {vista === "facturas" && <CarteraFacturas />}
      {vista === "promesas" && <CarteraPromesas />}
      {vista === "pagos" && <CarteraPagos />}
    </div>
  );
}
