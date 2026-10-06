"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { useApi } from "@/components/ui";
import { toast } from "@/components/toast";

/** La IA se pausó por el tope de gasto del mes. Sin este aviso la lista amanece
 *  vacía y nadie dice por qué. */
export function AvisoTopeIA() {
  const { data, refetch } = useApi(() => api.avisoTopeIa().catch(() => ({ aviso: null })), []);
  if (!data?.aviso) return null;
  return (
    <div className="mb-8 flex flex-wrap items-center gap-x-5 gap-y-1 rounded-2xl bg-panel px-5 py-3.5 text-cuerpo text-ink-2">
      <p className="min-w-0 flex-1 basis-64">
        <span className="font-semibold text-ink">Tu IA está en pausa.</span> Llegó al tope de gasto
        de este mes y tus ayudantes no redactan nada nuevo hasta el mes que entra.
      </p>
      <Link
        href="/configuracion?seccion=ia"
        className="shrink-0 font-medium text-accent-ink underline-offset-2 hover:underline"
      >
        Tu IA
      </Link>
      <button
        type="button"
        onClick={async () => {
          try {
            await api.descartarAvisoTopeIa();
            refetch();
          } catch (e) {
            toast((e as Error).message, "error");
          }
        }}
        className="shrink-0 text-apoyo text-ink-3 hover:text-ink"
      >
        Descartar
      </button>
    </div>
  );
}
