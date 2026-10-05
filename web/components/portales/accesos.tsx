"use client";

// Tus portales y su acceso. Se registra a qué sitio entrar (por su dirección) y se le
// conecta el acceso: se abre una ventana, el dueño entra él mismo como siempre y su
// sesión se guarda cifrada. aiuda nunca ve ni guarda su contraseña en estos portales.
import { useEffect, useState } from "react";
import { api, type CuaEstado, type CuaSesionHandoff } from "@/lib/api";
import { Drawer } from "@/components/drawer";
import { Collapse } from "@/components/motion";
import {
  PrimaryButton,
  SecondaryButton,
  TextInput,
  useConfirm,
  QuietButton,
} from "@/components/ui";
import { toast } from "@/components/toast";
import { Marca, urlBonita, type Portal } from "@/components/portales/comunes";

const ENTRANDO = ["abriendo", "esperando", "guardando"];

export function Accesos({
  open,
  onClose,
  portales,
  estado,
  onCambio,
}: {
  open: boolean;
  onClose: () => void;
  portales: Portal[];
  estado: CuaEstado | null;
  onCambio: () => void;
}) {
  const [agregar, setAgregar] = useState(false);
  const [nombre, setNombre] = useState("");
  const [url, setUrl] = useState("");
  const [notas, setNotas] = useState("");
  const [creando, setCreando] = useState(false);

  // Dirección de un portal de fábrica que el dueño ya hizo suyo y la perdió.
  const [editCap, setEditCap] = useState<string | null>(null);
  const [editUrl, setEditUrl] = useState("");
  const [guardandoUrl, setGuardandoUrl] = useState(false);

  // La ventana abierta para que el dueño entre (una a la vez).
  const [sesion, setSesion] = useState<CuaSesionHandoff | null>(null);
  const [conectando, setConectando] = useState<string | null>(null);

  const { confirm, dialog } = useConfirm();
  const puedeAbrir = estado?.handoff_posible ?? false;

  // Sigue la ventana mientras esté abierta; al terminar avisa y recarga los accesos.
  useEffect(() => {
    if (!sesion || !ENTRANDO.includes(sesion.estado)) return;
    const t = setInterval(async () => {
      try {
        const s = await api.cuaEstadoSesion(sesion.id);
        setSesion(s);
        if (s.estado === "guardado") {
          toast("Acceso conectado. aiuda ya puede entrar por su cuenta.", "success");
          setSesion(null);
          onCambio();
        } else if (s.estado === "cancelado") {
          setSesion(null);
        } else if (s.estado === "error") {
          toast(s.detalle || "No se pudo conectar el acceso.", "error");
        }
      } catch {
        /* red intermitente: el siguiente intento lo retoma */
      }
    }, 1500);
    return () => clearInterval(t);
  }, [sesion, onCambio]);

  const crear = async () => {
    if (!nombre.trim() || !url.trim()) return;
    setCreando(true);
    try {
      await api.cuaCrearPortal({ nombre: nombre.trim(), url: url.trim(), notas: notas.trim() || undefined });
      setNombre("");
      setUrl("");
      setNotas("");
      setAgregar(false);
      onCambio();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setCreando(false);
    }
  };

  const guardarUrl = async (cap: string) => {
    if (!editUrl.trim()) return;
    setGuardandoUrl(true);
    try {
      await api.cuaSetUrlBuiltin(cap, editUrl.trim());
      setEditCap(null);
      setEditUrl("");
      onCambio();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setGuardandoUrl(false);
    }
  };

  const conectar = async (cap: string) => {
    setConectando(cap);
    try {
      setSesion(await api.cuaIniciarSesion(cap));
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setConectando(null);
    }
  };

  const yaEntre = async () => {
    if (!sesion) return;
    try {
      setSesion(await api.cuaConfirmarSesion(sesion.id));
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const cancelar = async () => {
    if (!sesion) return;
    try {
      await api.cuaCancelarSesion(sesion.id);
    } catch {
      /* si ya no existe, igual se suelta */
    }
    setSesion(null);
  };

  const olvidar = async (p: Portal) => {
    const ok = await confirm({
      title: "Olvidar el acceso",
      message: `Se borra el acceso guardado de "${p.sistema}". Tendrás que volver a entrar para conectarlo.`,
      confirmLabel: "Olvidar",
    });
    if (!ok) return;
    try {
      await api.cuaOlvidarSesion(p.capacidad);
      onCambio();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const borrar = async (p: Portal) => {
    const ok = await confirm({
      title: "Borrar portal",
      message: `Se borra "${p.sistema}" y su acceso guardado. Lo que ya trajo se conserva.`,
      confirmLabel: "Borrar",
    });
    if (!ok) return;
    try {
      await api.cuaBorrarPortal(p.capacidad.slice("portal:".length));
      onCambio();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  return (
    <>
      <Drawer open={open} onClose={onClose} title="Tus portales" subtitle="Tú entras una vez y aiuda reusa tu acceso" size="lg">
        <div className="space-y-6">
          {estado !== null && !puedeAbrir && (
            <p className="rounded-lg bg-panel px-4 py-3 text-cuerpo text-ink-2">
              <span className="font-semibold text-ink">No se pueden conectar accesos en esta instalación.</span>{" "}
              {estado.handoff_detalle}
            </p>
          )}

          {sesion && (
            <div className="rounded-xl bg-panel px-5 py-4">
              {sesion.estado === "abriendo" && (
                <p className="text-cuerpo text-ink-2">Abriendo la ventana de «{sesion.sistema}»…</p>
              )}
              {sesion.estado === "esperando" && (
                <div>
                  <p className="text-cuerpo font-semibold text-ink">Se abrió una ventana con «{sesion.sistema}»</p>
                  <p className="mt-1 text-cuerpo text-ink-2">
                    Entra como siempre. Cuando ya estés dentro, toca «Ya entré» y se guarda tu acceso. Tu
                    contraseña la escribes tú: aiuda no la ve ni la guarda.
                  </p>
                  <div className="mt-4 flex items-center gap-2">
                    <PrimaryButton onClick={yaEntre}>Ya entré</PrimaryButton>
                    <SecondaryButton onClick={cancelar}>Cancelar</SecondaryButton>
                  </div>
                </div>
              )}
              {sesion.estado === "guardando" && <p className="text-cuerpo text-ink-2">Guardando tu acceso…</p>}
              {(sesion.estado === "error" || sesion.estado === "expirado") && (
                <div>
                  <p className="text-cuerpo text-danger">
                    {sesion.detalle ||
                      (sesion.estado === "expirado"
                        ? "Se acabó el tiempo para entrar."
                        : "No se pudo conectar el acceso.")}
                  </p>
                  <button onClick={() => setSesion(null)} className="btn btn-quiet btn-sm -ml-3 mt-2">
                    Cerrar
                  </button>
                </div>
              )}
            </div>
          )}

          {portales.length === 0 ? (
            <p className="text-cuerpo text-ink-2">
              Todavía no registras ningún portal. Agrega el de tu banco o el de un proveedor con su
              dirección.
            </p>
          ) : (
            <ul>
              {portales.map((p) => (
                <li key={p.capacidad} className="border-b border-line py-4 last:border-0">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <p className="min-w-0 flex-1 truncate text-cuerpo font-medium text-ink">{p.sistema}</p>
                    {p.url_configurada && (
                      <Marca color={p.tiene_sesion ? "var(--color-ok)" : undefined}>
                        {p.tiene_sesion ? "Acceso conectado" : "Sin acceso"}
                      </Marca>
                    )}
                  </div>
                  {p.url_configurada ? (
                    <p className="tnum truncate text-apoyo text-ink-3">{urlBonita(p.url)}</p>
                  ) : (
                    <p className="text-apoyo text-ink-3">Le falta la dirección.</p>
                  )}

                  {!p.url_configurada && !p.editable && editCap === p.capacidad && (
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <TextInput
                        value={editUrl}
                        onChange={(e) => setEditUrl(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") guardarUrl(p.capacidad);
                        }}
                        autoFocus
                        aria-label="Dirección del portal"
                        placeholder="https://"
                        className="min-w-0 flex-1 basis-56"
                      />
                      <SecondaryButton
                        onClick={() => guardarUrl(p.capacidad)}
                        disabled={guardandoUrl || !editUrl.trim()}
                      >
                        {guardandoUrl ? "Guardando…" : "Guardar"}
                      </SecondaryButton>
                    </div>
                  )}

                  <div className="-ml-3 mt-2 flex flex-wrap items-center gap-1">
                    {!p.url_configurada && !p.editable && editCap !== p.capacidad && (
                      <QuietButton
                        onClick={() => {
                          setEditCap(p.capacidad);
                          setEditUrl("");
                        }}
 size="sm"
>
                        Poner la dirección
                      </QuietButton>
                    )}
                    {puedeAbrir && p.url_configurada && (
                      <button
                        onClick={() => conectar(p.capacidad)}
                        disabled={conectando === p.capacidad || sesion !== null}
                        className="btn btn-quiet btn-sm text-accent-ink"
                      >
                        {conectando === p.capacidad
                          ? "Abriendo…"
                          : p.tiene_sesion
                            ? "Volver a entrar"
                            : "Conectar acceso (entras tú)"}
                      </button>
                    )}
                    {p.tiene_sesion && (
                      <QuietButton onClick={() => olvidar(p)} size="sm">
                        Olvidar acceso
                      </QuietButton>
                    )}
                    {p.editable && (
                      <QuietButton onClick={() => borrar(p)} size="sm">
                        Borrar portal
                      </QuietButton>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}

          <div>
            <SecondaryButton onClick={() => setAgregar((v) => !v)} aria-expanded={agregar}>
              {agregar ? "Cancelar" : "Agregar un portal"}
            </SecondaryButton>
            <Collapse open={agregar}>
              <div className="space-y-3 pt-4">
                <TextInput
                  value={nombre}
                  onChange={(e) => setNombre(e.target.value)}
                  aria-label="Nombre del portal"
                  placeholder="Nombre: Mi banco"
                />
                <TextInput
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  aria-label="Dirección del portal"
                  placeholder="Dirección: https://"
                />
                <TextInput
                  value={notas}
                  onChange={(e) => setNotas(e.target.value)}
                  aria-label="Notas para el asistente"
                  placeholder="Notas (opcional): qué buscar ahí"
                />
                <PrimaryButton onClick={crear} disabled={creando || !nombre.trim() || !url.trim()}>
                  {creando ? "Agregando…" : "Agregar portal"}
                </PrimaryButton>
              </div>
            </Collapse>
          </div>
        </div>
      </Drawer>
      {dialog}
    </>
  );
}
