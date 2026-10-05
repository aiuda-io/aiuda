"use client";

// La ficha de un ayudante. Cuatro vistas y nada más: lo que sabe hacer (con sus
// ajustes), platicar con él, lo que hizo y cómo es. Cada vista vive en su archivo, en
// components/ayudante/.
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import {
  ErrorState,
  Skeleton,
  Tabs,
  useConfirm,
  QuietButton,
} from "@/components/ui";
import { Avatar } from "@/components/avatar";
import { AiuditaPicker } from "@/components/aiudita-picker";
import { Apariencia } from "@/components/ayudante/apariencia";
import { Bitacora } from "@/components/ayudante/bitacora";
import { ComoEs } from "@/components/ayudante/como-es";
import { Platicar } from "@/components/ayudante/platicar";
import { Tareas } from "@/components/ayudante/tareas";
import { usePageTrail } from "@/components/rastro";
import { toast } from "@/components/toast";
import { deleteAyudante, refreshAyudante, updateAyudante, useAyudante, useCatalog } from "@/lib/ayudantes-store";
import { api, type CorridaAyudante } from "@/lib/api";
import { normalizeAppearance, type Appearance } from "@/lib/look";
import { perfilesActivos } from "@/lib/perfiles";

/** La única tarea que trabaja sola por toda la cartera (la misma constante que el
 *  servidor: AIUDITAS_DE_CORRIDA en api/ayudantes.py). Las demás trabajan cuando
 *  platicas con él o desde su pantalla. */
const TAREA_QUE_TRABAJA_SOLA = "cobranza.redactar_recordatorio";

type Vista = "tareas" | "platicar" | "hizo" | "como";

export default function AyudanteDetailPage() {
  // useSearchParams exige un boundary de Suspense en el export estático.
  return (
    <Suspense fallback={null}>
      <Ficha />
    </Suspense>
  );
}

function Ficha() {
  const params = useSearchParams();
  const id = params.get("id") ?? "";
  const recienCreado = params.get("nuevo") === "1";
  const router = useRouter();
  const { ayudante, loading, error, retry } = useAyudante(id);
  const { catalog, error: catError, retry: catRetry } = useCatalog();
  const [vista, setVista] = useState<Vista>("tareas");
  const [agregando, setAgregando] = useState(false);
  const [guiaCerrada, setGuiaCerrada] = useState(false);
  const [trabajando, setTrabajando] = useState(false);
  const [resultado, setResultado] = useState<CorridaAyudante | null>(null);
  const { confirm, dialog } = useConfirm();
  usePageTrail(ayudante?.name ?? "Ayudante");

  if (error || catError) {
    return <ErrorState message={error ?? catError ?? ""} retry={error ? retry : catRetry} />;
  }
  if (loading || !catalog) {
    return (
      <div className="min-w-0 space-y-4">
        <Skeleton className="h-16 w-80" />
        <Skeleton className="h-10 w-96" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (!ayudante) {
    return (
      <div className="mx-auto max-w-xl px-6 py-20 text-center">
        <p className="text-seccion font-semibold text-ink">Este ayudante ya no existe</p>
        <p className="mt-2 text-cuerpo text-ink-2">Puede que lo hayas eliminado. Elige otro de tu equipo.</p>
        <Link href="/ayudantes" className="btn btn-primary mt-6">
          Ver mis ayudantes
        </Link>
      </div>
    );
  }

  const app = normalizeAppearance(ayudante.appearance);
  const activos = ayudante.aiuditas; // { aiudita_id: config }
  const oficios = perfilesActivos(catalog, activos);
  const trabajaSolo = TAREA_QUE_TRABAJA_SOLA in activos;
  const { pendientes, enviadas } = ayudante.acciones;

  const setAppearance = (patch: Partial<Appearance>) =>
    updateAyudante(id, { appearance: { ...ayudante.appearance, ...patch } }).catch(() =>
      toast("No se pudo guardar su cara.", "error"),
    );

  const eliminar = async () => {
    const ok = await confirm({
      title: `Eliminar a ${ayudante.name}`,
      message: "Se borran el ayudante y sus ajustes. Lo que ya propuso o envió se conserva.",
    });
    if (!ok) return;
    try {
      await deleteAyudante(id);
      router.push("/ayudantes");
    } catch (e) {
      toast(`No se pudo eliminar: ${(e as Error).message}`, "error");
    }
  };

  const trabajar = async () => {
    if (trabajando) return;
    setTrabajando(true);
    setResultado(null);
    try {
      setResultado(await api.correrAyudante(id));
      // Lo pendiente y lo enviado se cuentan en el servidor: se vuelve a leer.
      await refreshAyudante(id);
    } catch (e) {
      toast(e instanceof Error ? e.message : "No se pudo poner a trabajar ahora.", "error");
    } finally {
      setTrabajando(false);
    }
  };

  return (
    <div className="min-w-0">
      <header className="mb-9 flex flex-wrap items-center gap-x-5 gap-y-4">
        <Avatar name={ayudante.name} size={64} {...app} />
        <div className="min-w-0 flex-1 basis-64">
          <input
            key={ayudante.name}
            defaultValue={ayudante.name}
            onBlur={(e) => {
              const v = e.target.value.trim();
              if (v && v !== ayudante.name) {
                updateAyudante(id, { name: v })
                  .then(() => toast("Nombre guardado", "info"))
                  .catch(() => toast("No se pudo guardar el nombre.", "error"));
              }
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.currentTarget.blur();
            }}
            aria-label="Nombre del ayudante"
            className="-ml-2 w-full max-w-md truncate rounded-lg border border-transparent bg-transparent px-2 py-0.5 text-titulo font-semibold text-ink hover:border-line-strong focus:border-accent focus:bg-surface focus:outline-none"
          />
          <p className="mt-1 text-cuerpo text-ink-2">
            {oficios.length > 0 ? oficios.map((p) => p.name).join(" y ") : "Todavía sin tareas"}
            {pendientes + enviadas > 0 && (
              <>
                {" · "}
                {pendientes > 0 ? (
                  <Link href="/" className="font-medium text-accent-ink hover:underline">
                    {pendientes} por aprobar
                  </Link>
                ) : (
                  "nada por aprobar"
                )}
                {enviadas > 0 && `, ${enviadas} ${enviadas === 1 ? "enviado" : "enviados"}`}
              </>
            )}
          </p>
        </div>
        <div className="barra shrink-0">
          <QuietButton onClick={eliminar}>
            Eliminar
          </QuietButton>
          {trabajaSolo && (
            // En Platicar el relleno es el de enviar: aquí baja a contorno, para que
            // la pantalla siga teniendo un solo botón relleno.
            <button
              onClick={trabajar}
              disabled={trabajando}
              className={`btn ${vista === "platicar" ? "btn-secondary" : "btn-primary"}`}
            >
              {trabajando ? "Trabajando…" : "Poner a trabajar"}
            </button>
          )}
        </div>
      </header>

      {resultado && (
        <p className="mb-8 rounded-xl bg-panel px-5 py-3.5 text-cuerpo text-ink" aria-live="polite">
          {resultado.propuestas > 0 ? (
            <>
              {ayudante.name} redactó {resultado.propuestas}{" "}
              {resultado.propuestas === 1 ? "recordatorio, que queda" : "recordatorios, que quedan"} en Hoy
              para que {resultado.propuestas === 1 ? "lo" : "los"} apruebes.{" "}
              <Link href="/" className="font-medium text-accent-ink hover:underline">
                Ir a Hoy
              </Link>
            </>
          ) : (
            (resultado.detalle ?? "Revisó tu cartera y no encontró a quién escribirle ahora.")
          )}
        </p>
      )}

      {recienCreado && !guiaCerrada && (
        <div className="mb-8 flex flex-wrap items-start gap-x-6 gap-y-3 rounded-xl bg-panel px-5 py-4">
          <div className="min-w-0 flex-1 basis-72">
            <p className="text-cuerpo font-semibold text-ink">{ayudante.name} ya es parte de tu equipo</p>
            <p className="mt-1 text-cuerpo text-ink-2">
              {Object.keys(activos).length === 0
                ? "Agrégale lo que quieres que haga. Cada tarea trae sus ajustes."
                : "Revisa sus tareas y ajústalas a tu negocio: el tono, tus reglas y cuándo pide tu aprobación."}{" "}
              Para trabajar necesita tu IA conectada, en{" "}
              <Link href="/configuracion?seccion=ia" className="font-medium text-accent-ink hover:underline">
                Ajustes
              </Link>
              .
            </p>
          </div>
          <QuietButton onClick={() => setGuiaCerrada(true)} size="sm">
            Entendido
          </QuietButton>
        </div>
      )}

      <Tabs
        tabs={[
          { key: "tareas", label: "Lo que sabe hacer" },
          { key: "platicar", label: "Platicar" },
          { key: "hizo", label: "Lo que hizo" },
          { key: "como", label: "Cómo es" },
        ]}
        active={vista}
        onChange={(k) => setVista(k as Vista)}
      />

      {vista === "tareas" && (
        <Tareas ayudanteId={id} catalog={catalog} activos={activos} onAgregar={() => setAgregando(true)} />
      )}
      {vista === "platicar" && <Platicar id={id} name={ayudante.name} activos={activos} />}
      {vista === "hizo" && <Bitacora ayudanteId={id} name={ayudante.name} />}
      {vista === "como" && (
        <div className="space-y-12">
          <ComoEs id={id} name={ayudante.name} instructions={ayudante.instructions} />
          <Apariencia app={app} onChange={setAppearance} />
        </div>
      )}

      {agregando && (
        <AiuditaPicker ayudanteId={id} catalog={catalog} activos={activos} onClose={() => setAgregando(false)} />
      )}
      {dialog}
    </div>
  );
}
