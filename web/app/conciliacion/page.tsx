"use client";

// Lo que era Conciliación vive en Cartera, pestaña Pagos. La ruta se queda como
// redirección para no romper enlaces ni marcadores, y conserva los parámetros que traiga.

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

export default function ConciliacionRedirect() {
  return (
    <Suspense fallback={null}>
      <Redirigir />
    </Suspense>
  );
}

function Redirigir() {
  const router = useRouter();
  const params = useSearchParams();
  useEffect(() => {
    const next = new URLSearchParams(params.toString());
    next.set("vista", "pagos");
    router.replace(`/facturas?${next.toString()}`);
  }, [router, params]);
  return null;
}
