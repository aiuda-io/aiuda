"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

function Redirigir() {
  const router = useRouter();
  const params = useSearchParams();
  useEffect(() => {
    // Se conserva la consulta: /centro?r=<id> sigue abriendo ese mensaje en Hoy.
    const q = params.toString();
    router.replace(q ? `/?${q}` : "/");
  }, [router, params]);
  return null;
}

/** Las rutas viejas del trabajo diario (/centro, /aprobaciones) llevan a Hoy. La
 *  consola es un export estático: la redirección corre en el navegador. */
export function IrAHoy() {
  return (
    <Suspense fallback={null}>
      <Redirigir />
    </Suspense>
  );
}
