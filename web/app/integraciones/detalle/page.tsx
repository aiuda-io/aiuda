"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { Redireccion } from "@/components/ajustes/redireccion";
import { rutaAjustes } from "@/lib/ajustes";

// La vista completa de una integración repetía el panel lateral (y le faltaba lo
// principal de WhatsApp: el botón de instalar y conectar). Ahora la única vista es
// el panel, dentro de Ajustes > Conexiones: `?key=odoo` abre el de Odoo.
export default function IntegracionDetalleRedirect() {
  // useSearchParams exige un límite de Suspense en el export estático.
  return (
    <Suspense fallback={<div className="min-w-0" />}>
      <Destino />
    </Suspense>
  );
}

function Destino() {
  const key = useSearchParams().get("key") ?? "";
  return <Redireccion a={rutaAjustes("conexiones", key || undefined)} />;
}
