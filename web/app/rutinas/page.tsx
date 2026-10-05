"use client";

// Portales: trabajo que aiuda hace por el dueño dentro de un sitio web. Se entra desde
// Ayudantes. Va primero lo que sí funciona y ya se usó de verdad (los dos documentos
// del SAT); lo que nadie ha usado todavía va junto, cerrado y con su sello. Las piezas
// viven en components/portales/.
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import {
  api,
  type CuaDeterministas,
  type CuaEstado,
  type CuaMision,
  type RutinaBackoffice,
} from "@/lib/api";
import { ESTADO, type Portal } from "@/components/portales/comunes";
import { Historial } from "@/components/portales/historial";
import { OtrosPortales } from "@/components/portales/otros";
import { DocumentosSat } from "@/components/portales/sat";

export default function PortalesPage() {
  const [misiones, setMisiones] = useState<CuaMision[] | null>(null);
  const [guardados, setGuardados] = useState<RutinaBackoffice[] | null>(null);
  const [portales, setPortales] = useState<Portal[]>([]);
  const [estado, setEstado] = useState<CuaEstado | null>(null);
  const [sat, setSat] = useState<CuaDeterministas | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    try {
      const [m, c, r, s] = await Promise.all([
        api.cuaMisiones(),
        api.cuaCapacidades(),
        api.cuaRutinas(),
        api.cuaDeterministas(),
      ]);
      setMisiones(m);
      setPortales(c);
      setGuardados(r);
      setSat(s);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
    // Si esta consulta falla, la página sigue: el servidor corta igual lo que no pueda.
    api.cuaEstado().then(setEstado).catch(() => {});
  }, []);

  useEffect(() => {
    cargar();
  }, [cargar]);

  const refrescar = useCallback(
    () =>
      Promise.all([api.cuaDeterministas().then(setSat), api.cuaMisiones().then(setMisiones)]).catch(() => {}),
    [],
  );

  // Mientras algo siga en cola o adentro de un portal, se refresca solo. También
  // mientras un documento del SAT diga "en curso": las dos lecturas no llegan al mismo
  // tiempo, y sin esto el renglón se quedaría pegado.
  const hayAlgoVivo =
    (misiones ?? []).some((m) => ESTADO[m.status].vivo) ||
    (sat?.empresas ?? []).some((e) => e.rutinas.some((r) => r.en_curso));
  useEffect(() => {
    if (!hayAlgoVivo) return;
    const t = setInterval(refrescar, 4000);
    return () => clearInterval(t);
  }, [hayAlgoVivo, refrescar]);

  const cargado = misiones !== null && guardados !== null && sat !== null;
  const disponible = sat?.navegador_listo ?? false;

  // Los portales de fábrica que el dueño no ha tocado solo se han corrido contra
  // portales de prueba: no se le enseñan. Sí los suyos, y los que ya usó.
  const usados = new Set([...(guardados ?? []).map((r) => r.capacidad), ...(misiones ?? []).map((m) => m.capacidad)]);
  const suyos = portales.filter((p) => p.del_dueno || p.editable || usados.has(p.capacidad));

  return (
    <div className="min-w-0">
      <Link href="/ayudantes" className="mb-5 inline-flex items-center gap-1.5 text-apoyo text-ink-3 hover:text-ink">
        <ChevronLeft /> Ayudantes
      </Link>
      <PageHeader title="Portales" subtitle="aiuda entra a un sitio web por ti y te trae lo que necesitas." />

      {error ? (
        <ErrorState message={error} retry={cargar} />
      ) : !cargado || !sat ? (
        <div className="max-w-3xl space-y-4">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : (
        <div className="reveal max-w-3xl space-y-12">
          {!disponible && (
            <div className="rounded-xl bg-warn-soft px-5 py-4">
              <p className="text-seccion font-semibold text-ink">No disponible en esta instalación</p>
              <p className="mt-1 text-cuerpo text-ink-2">{sat.navegador_detalle}</p>
            </div>
          )}

          <DocumentosSat sat={sat} disponible={disponible} onCambio={refrescar} />

          <OtrosPortales
            portales={suyos}
            guardados={guardados ?? []}
            estado={estado}
            disponible={disponible}
            onMandado={refrescar}
            onCambio={cargar}
          />

          <Historial misiones={misiones ?? []} />
        </div>
      )}
    </div>
  );
}
