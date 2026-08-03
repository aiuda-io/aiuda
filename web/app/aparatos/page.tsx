"use client";

/**
 * Tu teléfono y tu equipo.
 *
 * Todo pasa aquí adentro: se prende la red, sale un QR, se escanea y ya. Nada
 * que descargar, ninguna cuenta que crear, ninguna terminal que abrir. Y si
 * macOS no nos dio permiso para ver la red local, esta pantalla lo dice y lleva
 * al lugar exacto donde se arregla.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, mxn, type Dispositivo, type Invitacion, type RedLocal } from "@/lib/api";
import { ErrorState, PageHeader, Skeleton, useApi } from "@/components/ui";
import { SettingsPage, SettingsSection } from "@/components/settings";
import { toast } from "@/components/toast";

const BOTON_PRIMARIO =
  "rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50";
const BOTON_SUAVE =
  "rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50";
const BOTON_SACAR =
  "rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-3 transition-colors hover:border-danger hover:text-danger disabled:opacity-50";

function cuando(iso: string | null): string {
  if (!iso) return "nunca";
  const dias = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (dias === 0) return "hoy";
  if (dias === 1) return "ayer";
  if (dias < 30) return `hace ${dias} días`;
  return new Date(iso).toLocaleDateString("es-MX", { day: "numeric", month: "short" });
}

function loQuePuede(d: Dispositivo): string {
  if (d.papel === "dueno") return "Aprueba todo y puede invitar";
  if (d.tope_aprobacion === null) return "Ve y propone, no aprueba";
  return `Aprueba hasta ${mxn(d.tope_aprobacion)}`;
}

export default function AparatosPage() {
  const { data: red, error, loading, refetch, refetchQuiet } = useApi<RedLocal>(() =>
    api.redLocal(),
  );
  const { data: lista, refetchQuiet: recargarLista } = useApi<{ dispositivos: Dispositivo[] }>(
    () => api.dispositivos(),
  );

  const [cambiando, setCambiando] = useState(false);
  const [invitacion, setInvitacion] = useState<Invitacion | null>(null);
  const [restan, setRestan] = useState(0);
  const [papel, setPapel] = useState<"dueno" | "invitado">("invitado");
  const [tope, setTope] = useState("");
  const sondeo = useRef<ReturnType<typeof setInterval> | null>(null);

  const dispositivos = lista?.dispositivos ?? [];
  const dentro = dispositivos.filter((d) => d.activo);

  const cerrarInvitacion = useCallback(() => {
    setInvitacion(null);
    setRestan(0);
    api.cancelarInvitacion().catch(() => undefined);
  }, []);

  // La cuenta regresiva del código, para que nadie se quede viendo un QR muerto.
  useEffect(() => {
    if (!invitacion) return;
    const t = setInterval(() => {
      setRestan((s) => {
        if (s <= 1) {
          setInvitacion(null);
          return 0;
        }
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(t);
  }, [invitacion]);

  // Mientras el QR está en pantalla, revisamos si alguien ya entró: el dueño ve
  // aparecer el teléfono en su lista sin tener que recargar nada.
  useEffect(() => {
    if (!invitacion) {
      if (sondeo.current) clearInterval(sondeo.current);
      return;
    }
    const antes = dispositivos.length;
    sondeo.current = setInterval(async () => {
      const ahora = await api.dispositivos().catch(() => null);
      if (ahora && ahora.dispositivos.length > antes) {
        const nuevo = ahora.dispositivos[ahora.dispositivos.length - 1];
        setInvitacion(null);
        recargarLista();
        toast(`${nuevo.nombre} ya está dentro`, "success");
      }
    }, 2000);
    return () => {
      if (sondeo.current) clearInterval(sondeo.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invitacion]);

  useEffect(() => () => void api.cancelarInvitacion().catch(() => undefined), []);

  async function prenderApagar(prendida: boolean) {
    setCambiando(true);
    try {
      await api.cambiarRedLocal(prendida);
      if (!prendida) cerrarInvitacion();
      await refetchQuiet();
      toast(
        prendida
          ? "Listo: tus aparatos ya pueden ver esta computadora"
          : "Apagada. Solo esta computadora entra a aiuda",
        "success",
      );
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setCambiando(false);
    }
  }

  async function invitar() {
    try {
      const limpio = tope.replace(/[^0-9.]/g, "");
      const inv = await api.crearInvitacion(
        papel,
        papel === "invitado" && limpio ? Number(limpio) : null,
      );
      setInvitacion(inv);
      setRestan(inv.caduca_en);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  async function sacar(d: Dispositivo) {
    try {
      await api.revocarDispositivo(d.id);
      await recargarLista();
      toast(`${d.nombre} quedó fuera`, "success");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  if (error) return <ErrorState message={error} retry={refetch} />;

  return (
    <SettingsPage>
      <PageHeader
        title="Tus aparatos"
        subtitle="Conecta tu celular para aprobar sin estar frente a la computadora, y deja entrar a quien trabaje contigo. Sin instalar nada."
        right={
          red ? (
            <span className="rounded-full border border-line px-2.5 py-1 text-sello text-ink-2">
              {red.prendida ? `${dentro.length} dentro` : "Red apagada"}
            </span>
          ) : null
        }
      />

      {/* Lo que falta se dice antes de que nadie gaste tiempo: esta computadora ya
          empareja, pero la app que lee el código todavía no se publica. Sin este
          aviso la pantalla promete algo que hoy no pasa. */}
      <div className="mt-4 rounded-md border border-line bg-panel p-3.5">
        <p className="text-cuerpo font-medium text-ink">
          Falta la app del teléfono
        </p>
        <p className="mt-1 text-cuerpo leading-relaxed text-ink-2">
          Esta mitad ya está lista: la red, el código, los papeles y sacar aparatos. La app que
          lee el código todavía no se publica, así que hoy apuntarle la cámara no hace nada.{" "}
          <a className="underline hover:text-ink" href="/manual/aparatos.html">
            Cómo va a funcionar
          </a>
          .
        </p>
      </div>

      {loading && !red ? (
        <div className="mt-2 space-y-3">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-44 w-full" />
        </div>
      ) : (
        <div className="mt-2">
          <SettingsSection
            title="La red de tu negocio"
            desc="Mientras esté prendida, los aparatos que tú dejes entrar pueden llegarle a esta computadora, sin salir de tu WiFi."
          >
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  className={red?.prendida ? BOTON_SUAVE : BOTON_PRIMARIO}
                  disabled={cambiando}
                  onClick={() => prenderApagar(!red?.prendida)}
                >
                  {cambiando ? "Un momento…" : red?.prendida ? "Apagar" : "Prender"}
                </button>
                {red?.prendida && red.direccion ? (
                  <span className="text-cuerpo text-ink-3">
                    Esta computadora es <span className="tnum text-ink-2">{red.direccion}</span> en
                    tu red
                  </span>
                ) : null}
              </div>

              {/* El caso que sí pasa: el dueño le dio "No permitir" al aviso de
                  macOS y después nada funciona sin explicación. */}
              {red?.prendida && red.permiso_del_sistema === false ? (
                <div className="rounded-md border border-line bg-panel p-3.5">
                  <p className="text-cuerpo font-medium text-ink">
                    Tu Mac no está dejando que aiuda vea la red
                  </p>
                  <p className="mt-1 text-cuerpo leading-relaxed text-ink-2">
                    Es el permiso que te pidió al prenderla. Sin él, tu teléfono no va a encontrar
                    esta computadora. Se prende en Ajustes, en Red local, dejando aiuda encendido.
                  </p>
                  {red.ajustes ? (
                    <a className={`${BOTON_PRIMARIO} mt-3 inline-block`} href={red.ajustes}>
                      Abrir Ajustes
                    </a>
                  ) : null}
                  <button type="button" className={`${BOTON_SUAVE} ml-2`} onClick={refetchQuiet}>
                    Ya lo permití
                  </button>
                </div>
              ) : null}

              {red?.prendida && red.permiso_del_sistema !== false && !red.anunciada ? (
                <p className="text-cuerpo leading-relaxed text-ink-3">
                  aiuda no pudo anunciarse en tu red. Todo sigue funcionando: el teléfono va a usar
                  la dirección que trae el QR.
                </p>
              ) : null}
            </div>
          </SettingsSection>

          <SettingsSection
            title="Sumar un aparato"
            desc="Enséñale este código al teléfono que quieras meter. Dura cinco minutos y sirve una sola vez."
          >
            {!red?.prendida ? (
              <p className="text-cuerpo leading-relaxed text-ink-2">
                Primero prende la red de tu negocio, arriba.
              </p>
            ) : invitacion ? (
              <div className="space-y-3">
                <div className="inline-block rounded-md border border-line bg-surface p-3">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={invitacion.qr_svg}
                    alt="Código para emparejar un aparato"
                    className="h-52 w-52"
                  />
                </div>
                <p className="text-cuerpo leading-relaxed text-ink-2">
                  Quien lo escanee entra como{" "}
                  <b>{invitacion.papel === "dueno" ? "dueño" : "invitado"}</b>
                  {invitacion.tope_aprobacion !== null
                    ? `, aprobando hasta ${mxn(invitacion.tope_aprobacion)}`
                    : ""}
                  .
                </p>
                <div className="flex items-center gap-3">
                  <span className="tnum text-cuerpo text-ink-3">
                    Caduca en {Math.floor(restan / 60)}:
                    {String(restan % 60).padStart(2, "0")}
                  </span>
                  <button type="button" className={BOTON_SUAVE} onClick={cerrarInvitacion}>
                    Cancelar
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-2">
                  {(["invitado", "dueno"] as const).map((p) => (
                    <button
                      key={p}
                      type="button"
                      className={papel === p ? BOTON_PRIMARIO : BOTON_SUAVE}
                      onClick={() => setPapel(p)}
                    >
                      {p === "dueno" ? "Como dueño" : "Como invitado"}
                    </button>
                  ))}
                </div>
                {papel === "invitado" ? (
                  <div className="space-y-1.5">
                    <label className="block text-cuerpo font-medium text-ink" htmlFor="tope">
                      Hasta cuánto puede aprobar solo
                    </label>
                    <p className="text-apoyo leading-relaxed text-ink-3">
                      Déjalo vacío si prefieres que solo vea y proponga, y que tú apruebes todo.
                    </p>
                    <input
                      id="tope"
                      inputMode="decimal"
                      placeholder="Sin límite de aprobación: vacío"
                      value={tope}
                      onChange={(e) => setTope(e.target.value)}
                      className="w-56 rounded-md border border-line bg-surface px-3 py-2 text-cuerpo text-ink"
                    />
                  </div>
                ) : (
                  <p className="text-cuerpo leading-relaxed text-ink-3">
                    Un aparato como dueño aprueba lo que sea y puede meter a otros. Dáselo solo a
                    tu propio teléfono.
                  </p>
                )}
                <button type="button" className={BOTON_PRIMARIO} onClick={invitar}>
                  Enseñar el código
                </button>
              </div>
            )}
          </SettingsSection>

          <SettingsSection
            title="Quién está dentro"
            desc="Los aparatos emparejados con este aiuda. Sacar uno lo deja fuera de inmediato."
          >
            {dispositivos.length === 0 ? (
              <p className="text-cuerpo leading-relaxed text-ink-2">
                Todavía no hay ningún aparato. Empieza por el tuyo.
              </p>
            ) : (
              <ul className="divide-y divide-line rounded-md border border-line">
                {dispositivos.map((d) => (
                  <li key={d.id} className="flex flex-wrap items-center gap-3 px-3.5 py-3">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-cuerpo font-medium text-ink">
                        {d.nombre}
                        {d.papel === "dueno" ? (
                          <span className="ml-2 rounded-full bg-panel px-2 py-0.5 text-sello font-normal text-ink-2">
                            dueño
                          </span>
                        ) : null}
                      </p>
                      <p className="text-apoyo text-ink-3">
                        {d.activo
                          ? `${loQuePuede(d)} · visto ${cuando(d.ultimo_visto)}`
                          : `Fuera desde ${cuando(d.revocado_en)}`}
                      </p>
                    </div>
                    {d.activo ? (
                      <button type="button" className={BOTON_SACAR} onClick={() => sacar(d)}>
                        Sacar
                      </button>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </SettingsSection>
        </div>
      )}
    </SettingsPage>
  );
}
