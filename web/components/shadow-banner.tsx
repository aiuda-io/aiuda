"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { SHADOW_EVENT, useApagarModoPrueba } from "@/components/modo-prueba";

// LA franja del modo de prueba, y la única: mientras está encendido, nada sale a
// los clientes. Se queda pegada arriba al hacer scroll, porque una advertencia que
// se va de la vista deja de advertir. Se apaga aquí mismo, pasando por el mismo
// diálogo que Ajustes (components/modo-prueba.tsx): lo ya aprobado no se va solo.
export function ShadowBanner() {
  const [on, setOn] = useState(false);
  const { apagar, apagando, dialogo } = useApagarModoPrueba();

  useEffect(() => {
    api
      .shadowMode()
      .then((s) => setOn(!!s.modo_sombra))
      .catch(() => {});
    const handler = (e: Event) => setOn(!!(e as CustomEvent<{ activo: boolean }>).detail?.activo);
    window.addEventListener(SHADOW_EVENT, handler);
    return () => window.removeEventListener(SHADOW_EVENT, handler);
  }, []);

  if (!on) return dialogo;

  return (
    <>
      <div
        role="status"
        className="franja sticky top-0 z-30 flex min-h-10 flex-wrap items-center justify-center gap-x-4 gap-y-0.5 bg-warn-band px-5 py-1.5 text-center text-apoyo text-ink"
      >
        <span>
          <span className="font-semibold">Modo de prueba:</span> nada sale a tus clientes
        </span>
        <button
          onClick={apagar}
          disabled={apagando}
          className="font-semibold underline decoration-ink/40 underline-offset-[3px] hover:decoration-ink disabled:opacity-50"
        >
          Apagar
        </button>
      </div>
      {dialogo}
    </>
  );
}
