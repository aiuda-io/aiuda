"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** Una ruta vieja que ahora es una sección de Ajustes. La consola es un export
 *  estático: no hay servidor que redirija, así que lo hace la página al montarse.
 *  `replace` y no `push`, para que "atrás" no regrese a la ruta que ya no existe. */
export function Redireccion({ a }: { a: string }) {
  const router = useRouter();
  useEffect(() => {
    router.replace(a);
  }, [router, a]);
  return <div className="min-w-0" aria-busy="true" />;
}
