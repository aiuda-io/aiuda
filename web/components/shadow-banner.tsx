"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useConfirm } from "@/components/ui";

// Evento que se dispara al prender o apagar el modo de prueba (aquí y en Ajustes),
// para que la franja y las pantallas se enteren sin recargar.
export const SHADOW_EVENT = "shadow-mode-changed";

// LA franja del modo de prueba, y la única: mientras está encendido, nada sale a
// los clientes. Se queda pegada arriba al hacer scroll, porque una advertencia que
// se va de la vista deja de advertir. Se apaga aquí mismo.
export function ShadowBanner() {
  const [on, setOn] = useState(false);
  const [apagando, setApagando] = useState(false);
  const [fallo, setFallo] = useState(false);
  const { confirm, dialog } = useConfirm();

  useEffect(() => {
    api
      .shadowMode()
      .then((s) => setOn(!!s.modo_sombra))
      .catch(() => {});
    const handler = (e: Event) => setOn(!!(e as CustomEvent<{ activo: boolean }>).detail?.activo);
    window.addEventListener(SHADOW_EVENT, handler);
    return () => window.removeEventListener(SHADOW_EVENT, handler);
  }, []);

  async function apagar() {
    // Apagarlo cambia lo que hace "Aprobar": de aquí en adelante sí manda. Un
    // clic suelto en una franja no debe bastar para eso.
    const ok = await confirm({
      title: "Apagar el modo de prueba",
      message: "Desde ahora, lo que apruebes sí se envía a tus clientes.",
      confirmLabel: "Apagar",
    });
    if (!ok) return;
    setApagando(true);
    setFallo(false);
    try {
      const res = await api.setShadowMode(false);
      setOn(res.modo_sombra);
      window.dispatchEvent(new CustomEvent(SHADOW_EVENT, { detail: { activo: res.modo_sombra } }));
    } catch {
      setFallo(true);
    } finally {
      setApagando(false);
    }
  }

  if (!on) return dialog;

  return (
    <>
      <div
        role="status"
        className="franja sticky top-0 z-30 flex min-h-10 flex-wrap items-center justify-center gap-x-4 gap-y-0.5 bg-warn-band px-5 py-1.5 text-center text-apoyo text-ink"
      >
        <span>
          <span className="font-semibold">Modo de prueba:</span> nada sale a tus clientes
        </span>
        {fallo && <span className="text-danger">No se pudo apagar. Intenta de nuevo.</span>}
        <button
          onClick={apagar}
          disabled={apagando}
          className="font-semibold underline decoration-ink/40 underline-offset-[3px] hover:decoration-ink disabled:opacity-50"
        >
          {apagando ? "Apagando" : "Apagar"}
        </button>
      </div>
      {dialog}
    </>
  );
}
