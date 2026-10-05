"use client";

// Otros portales: un asistente con IA entra a un sitio del dueño (su banco, un
// proveedor) y trae lo que se le pida. Nadie lo ha usado todavía con un portal de
// verdad, así que todo esto va junto, cerrado y con su sello.
import Link from "next/link";
import { useState } from "react";
import { api, type CuaEstado, type RutinaBackoffice } from "@/lib/api";
import { Collapse } from "@/components/motion";
import { PrimaryButton, SecondaryButton, SinEstrenar, TextInput, inputCls, useConfirm } from "@/components/ui";
import { toast } from "@/components/toast";
import { Accesos } from "@/components/portales/accesos";
import type { Portal } from "@/components/portales/comunes";

export function OtrosPortales({
  portales,
  guardados,
  estado,
  disponible,
  onMandado,
  onCambio,
}: {
  /** Solo los del dueño: los de fábrica sin tocar no llegan aquí. */
  portales: Portal[];
  guardados: RutinaBackoffice[];
  estado: CuaEstado | null;
  disponible: boolean;
  /** Se mandó un encargo: hay que recargar lo que ha hecho. */
  onMandado: () => void;
  /** Cambió un portal, un acceso o un encargo guardado. */
  onCambio: () => void;
}) {
  const [abierto, setAbierto] = useState(false);
  const [accesos, setAccesos] = useState(false);
  const [elegido, setElegido] = useState<string | null>(null);
  const [instruccion, setInstruccion] = useState("");
  const [mandando, setMandando] = useState(false);
  const [guardar, setGuardar] = useState(false);
  const [nombre, setNombre] = useState("");
  const [guardando, setGuardando] = useState(false);
  const [repitiendo, setRepitiendo] = useState<string | null>(null);
  const { confirm, dialog } = useConfirm();

  const portal = portales.find((p) => p.capacidad === elegido) ?? null;
  const faltaIa = estado !== null && estado.navegador_listo && !estado.credencial_ia;

  const mandar = async (capacidad: string, texto: string, a: string) => {
    await api.cuaEncolar(capacidad, texto.trim() || undefined);
    toast(`Encargo mandado a ${a}.`, "info");
    onMandado();
  };

  const mandarAhora = async () => {
    if (!portal) return;
    setMandando(true);
    try {
      await mandar(portal.capacidad, instruccion, portal.sistema);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setMandando(false);
    }
  };

  const repetir = async (r: RutinaBackoffice) => {
    setRepitiendo(r.id);
    try {
      await mandar(r.capacidad, r.instruccion, r.nombre);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setRepitiendo(null);
    }
  };

  const guardarEncargo = async () => {
    if (!portal || !nombre.trim()) return;
    setGuardando(true);
    try {
      await api.cuaGuardarRutina({
        nombre: nombre.trim(),
        capacidad: portal.capacidad,
        instruccion: instruccion.trim() || undefined,
      });
      toast(`Guardado: "${nombre.trim()}".`, "success");
      setNombre("");
      setGuardar(false);
      onCambio();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setGuardando(false);
    }
  };

  const borrar = async (r: RutinaBackoffice) => {
    const ok = await confirm({
      title: "Borrar encargo guardado",
      message: `Se borra "${r.nombre}". Lo que ya trajo se conserva.`,
      confirmLabel: "Borrar",
    });
    if (!ok) return;
    try {
      await api.cuaBorrarRutina(r.id);
      onCambio();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  return (
    <section>
      <button
        onClick={() => setAbierto((v) => !v)}
        aria-expanded={abierto}
        className="-mx-3 flex w-[calc(100%+1.5rem)] items-center gap-3 rounded-lg px-3 py-2 text-left hover:bg-panel"
      >
        <h2 className="text-seccion font-semibold text-ink">Otros portales</h2>
        <SinEstrenar />
        <svg
          viewBox="0 0 12 12"
          aria-hidden
          className={`ml-auto h-3 w-3 shrink-0 text-ink-3 transition-transform ${abierto ? "rotate-90" : ""}`}
          fill="none"
        >
          <path d="M4.5 3 8 6l-3.5 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      <Collapse open={abierto}>
        <div className="space-y-8 pt-3">
          <p className="max-w-2xl text-cuerpo text-ink-2">
            Un asistente con IA entra a un sitio tuyo, como tu banco o el de un proveedor, y te trae lo
            que le pidas, con capturas de lo que vio. Está construido, pero todavía nadie lo ha usado
            con un portal de verdad.
          </p>

          {disponible && faltaIa && (
            <p className="max-w-2xl rounded-lg bg-warn-soft px-4 py-3 text-cuerpo text-ink-2">
              {estado?.ia_detalle}{" "}
              <Link href="/configuracion?seccion=ia" className="font-medium text-accent-ink hover:underline">
                Ir a Tu IA
              </Link>
            </p>
          )}

          {disponible && (
            <div className="max-w-2xl">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h3 className="text-cuerpo font-semibold text-ink">Manda un encargo</h3>
                <SecondaryButton size="sm" onClick={() => setAccesos(true)}>
                  Tus portales
                </SecondaryButton>
              </div>

              {portales.length === 0 ? (
                <p className="mt-2 text-cuerpo text-ink-2">
                  Primero registra a qué sitio entrar, en «Tus portales».
                </p>
              ) : (
                <>
                  <p className="mt-3 text-rotulo text-ink-3">¿A qué portal?</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {portales.map((p) => {
                      const on = elegido === p.capacidad;
                      return (
                        <button
                          key={p.capacidad}
                          onClick={() => setElegido(on ? null : p.capacidad)}
                          aria-pressed={on}
                          title={
                            !p.url_configurada
                              ? "Le falta la dirección"
                              : p.tiene_sesion
                                ? "Acceso conectado"
                                : "Sin acceso todavía"
                          }
                          className={`btn btn-sm ${on ? "bg-accent-soft text-accent-ink" : "btn-secondary"}`}
                        >
                          {p.sistema}
                        </button>
                      );
                    })}
                  </div>

                  <Collapse open={portal !== null}>
                    <div className="pt-4">
                      <label htmlFor="encargo" className="text-rotulo text-ink-3">
                        ¿Qué necesitas que haga ahí?
                      </label>
                      <textarea
                        id="encargo"
                        value={instruccion}
                        onChange={(e) => setInstruccion(e.target.value)}
                        rows={3}
                        placeholder={portal ? `Por ejemplo: ${portal.objetivo}` : ""}
                        className={`${inputCls} mt-2 resize-none`}
                      />
                      {portal && !portal.tiene_sesion && (
                        <p className="mt-2 text-apoyo text-ink-3">
                          Este portal todavía no tiene acceso. Conéctalo en «Tus portales»: entras tú y aiuda
                          reusa tu acceso.
                        </p>
                      )}
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <SecondaryButton onClick={mandarAhora} disabled={mandando}>
                          {mandando ? "Mandando…" : "Mandar ahora"}
                        </SecondaryButton>
                        <button onClick={() => setGuardar((v) => !v)} aria-expanded={guardar} className="btn btn-quiet">
                          Guardar para repetirlo
                        </button>
                      </div>
                      <Collapse open={guardar}>
                        <div className="flex flex-wrap items-center gap-2 pt-3">
                          <TextInput
                            value={nombre}
                            onChange={(e) => setNombre(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") guardarEncargo();
                            }}
                            aria-label="Nombre del encargo"
                            placeholder="Nombre: Depósitos de la quincena"
                            className="min-w-0 flex-1 basis-56"
                          />
                          <PrimaryButton onClick={guardarEncargo} disabled={guardando || !nombre.trim()}>
                            {guardando ? "Guardando…" : "Guardar"}
                          </PrimaryButton>
                        </div>
                      </Collapse>
                    </div>
                  </Collapse>
                </>
              )}
            </div>
          )}

          {guardados.length > 0 && (
            <div className="max-w-2xl">
              <h3 className="text-cuerpo font-semibold text-ink">Encargos guardados</h3>
              <ul className="mt-1">
                {guardados.map((r) => (
                  <li key={r.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line py-3 last:border-0">
                    <div className="min-w-0 flex-1 basis-56">
                      <p className="truncate text-cuerpo font-medium text-ink">{r.nombre}</p>
                      <p className="truncate text-apoyo text-ink-3">
                        {r.sistema}
                        {r.instruccion ? ` · ${r.instruccion}` : ""}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <button onClick={() => borrar(r)} className="btn btn-quiet btn-sm">
                        Borrar
                      </button>
                      {disponible && (
                        <SecondaryButton size="sm" onClick={() => repetir(r)} disabled={repitiendo === r.id}>
                          {repitiendo === r.id ? "Mandando…" : "Mandar"}
                        </SecondaryButton>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </Collapse>

      <Accesos open={accesos} onClose={() => setAccesos(false)} portales={portales} estado={estado} onCambio={onCambio} />
      {dialog}
    </section>
  );
}
