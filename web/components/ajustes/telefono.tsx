"use client";

/**
 * Teléfono y equipo.
 *
 * En esta computadora no hay nada que instalar: se prende la red, sale un código
 * y se escanea. El TELÉFONO sí necesita la app de aiuda para iPhone, porque el
 * código es un enlace `aiuda://` que solo ella sabe abrir, y esa app todavía no
 * está en la App Store. Las dos cosas se dicen arriba, juntas, para que nadie
 * prenda la red creyendo que con la cámara basta.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, mxn, type Dispositivo, type Invitacion, type RedLocal } from "@/lib/api";
import {
  ErrorState,
  PrimaryButton,
  SecondaryButton,
  Skeleton,
  Tabs,
  inputCls,
  useApi,
} from "@/components/ui";
import { SettingsSection } from "@/components/settings";
import { toast } from "@/components/toast";
import { fechaDM, instante } from "@/lib/format";

function cuando(iso: string | null): string {
  const d = instante(iso);
  if (!d) return "nunca";
  const dias = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  if (dias <= 0) return "hoy";
  if (dias === 1) return "ayer";
  if (dias < 30) return `hace ${dias} días`;
  return fechaDM(iso);
}

function loQuePuede(d: Dispositivo): string {
  if (d.papel === "dueno") return "Aprueba todo y puede invitar";
  if (d.tope_aprobacion === null) return "Ve y propone, no aprueba";
  return `Aprueba hasta ${mxn(d.tope_aprobacion)}`;
}

export function AjustesTelefono() {
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

  // La cuenta regresiva del código, para que nadie se quede viendo uno muerto.
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

  // Mientras el código está en pantalla, se revisa si alguien ya entró: el dueño ve
  // aparecer el teléfono en su lista sin recargar nada.
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

  // Salir de la sección con un código vivo lo cancela. Solo si hubo uno: sin esto,
  // cambiar de pestaña en Ajustes disparaba una escritura cada vez.
  const huboCodigo = useRef(false);
  useEffect(() => {
    if (invitacion) huboCodigo.current = true;
  }, [invitacion]);
  useEffect(
    () => () => {
      if (huboCodigo.current) void api.cancelarInvitacion().catch(() => undefined);
    },
    [],
  );

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

  const prendida = !!red?.prendida;

  return (
    <div>
      <div className="max-w-2xl">
        <p className="text-cuerpo leading-relaxed text-ink-2">
          Aprueba desde tu iPhone sin estar frente a la computadora, y deja entrar a quien trabaje
          contigo, cada quien con su tope. Todo pasa dentro de tu WiFi.
        </p>
        {/* Lo que falta se dice antes de que nadie gaste tiempo. */}
        <div className="mt-5 rounded-[14px] bg-panel px-5 py-4">
          <p className="text-cuerpo font-semibold text-ink">
            El teléfono necesita la app de aiuda para iPhone, y todavía no está en la App Store
          </p>
          <p className="mt-1 text-cuerpo leading-relaxed text-ink-2">
            En esta computadora no hay nada que instalar. En el teléfono sí: el código de abajo solo
            lo entiende esa app, y apuntarle la cámara sin tenerla no hace nada. Hoy solo la tiene
            quien la instaló desde su código. No hay app para Android.{" "}
            <a
              className="font-medium text-accent-ink underline-offset-2 hover:underline"
              href="/manual/aparatos.html"
            >
              Cómo funciona
            </a>
          </p>
        </div>
      </div>

      {loading && !red ? (
        <div className="mt-8 space-y-3">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-44 w-full" />
        </div>
      ) : (
        <div className="mt-10">
          <SettingsSection
            title="La red de tu negocio"
            desc="Mientras esté prendida, los aparatos que tú dejes entrar pueden llegarle a esta computadora, sin salir de tu WiFi."
          >
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <SecondaryButton disabled={cambiando} onClick={() => prenderApagar(!prendida)}>
                  {cambiando ? "Un momento…" : prendida ? "Apagar la red" : "Prender la red"}
                </SecondaryButton>
                <span
                  className="mark"
                  style={
                    {
                      "--mark": prendida ? "var(--color-ok)" : "var(--color-line-strong)",
                    } as React.CSSProperties
                  }
                >
                  {prendida
                    ? `Prendida, ${dentro.length} ${dentro.length === 1 ? "aparato dentro" : "aparatos dentro"}`
                    : "Apagada"}
                </span>
              </div>
              {prendida && red?.direccion ? (
                <p className="text-cuerpo text-ink-2">
                  Esta computadora es <span className="tnum text-ink">{red.direccion}</span> en tu
                  red.
                </p>
              ) : null}

              {/* El caso que sí pasa: el dueño le dio "No permitir" al aviso de
                  macOS y después nada funciona sin explicación. */}
              {prendida && red?.permiso_del_sistema === false ? (
                <div className="rounded-[14px] bg-warn-soft px-5 py-4">
                  <p className="text-cuerpo font-semibold text-ink">
                    Tu Mac no está dejando que aiuda vea la red
                  </p>
                  <p className="mt-1 text-cuerpo leading-relaxed text-ink-2">
                    Es el permiso que te pidió al prenderla. Sin él, tu teléfono no va a encontrar
                    esta computadora. Se da en los Ajustes de tu Mac, en Red local, dejando aiuda
                    encendido.
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {red.ajustes ? (
                      <a className="btn btn-secondary" href={red.ajustes}>
                        Abrir los Ajustes de la Mac
                      </a>
                    ) : null}
                    <button type="button" className="btn btn-quiet" onClick={refetchQuiet}>
                      Ya lo permití
                    </button>
                  </div>
                </div>
              ) : null}

              {prendida && red?.permiso_del_sistema !== false && !red?.anunciada ? (
                <p className="text-cuerpo leading-relaxed text-ink-2">
                  aiuda no pudo anunciarse en tu red. Todo sigue funcionando: el teléfono va a usar
                  la dirección que trae el código.
                </p>
              ) : null}
            </div>
          </SettingsSection>

          <SettingsSection
            title="Sumar un aparato"
            desc="Se escanea con la app de aiuda en el iPhone. El código dura cinco minutos y sirve una sola vez."
          >
            {!prendida ? (
              <p className="text-cuerpo leading-relaxed text-ink-2">
                Primero prende la red de tu negocio, arriba.
              </p>
            ) : invitacion ? (
              <div className="space-y-3">
                <div className="inline-block rounded-[14px] bg-surface p-3 elev-md">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={invitacion.qr_svg}
                    alt="Código para emparejar un aparato"
                    className="h-52 w-52"
                  />
                </div>
                <p className="text-cuerpo leading-relaxed text-ink-2">
                  Quien lo escanee entra como{" "}
                  <b className="font-semibold text-ink">
                    {invitacion.papel === "dueno" ? "dueño" : "invitado"}
                  </b>
                  {invitacion.tope_aprobacion !== null
                    ? `, aprobando hasta ${mxn(invitacion.tope_aprobacion)}`
                    : ""}
                  .
                </p>
                <div className="flex items-center gap-3">
                  <span className="tnum text-cuerpo text-ink-2">
                    Caduca en {Math.floor(restan / 60)}:{String(restan % 60).padStart(2, "0")}
                  </span>
                  <SecondaryButton onClick={cerrarInvitacion}>Cancelar</SecondaryButton>
                </div>
              </div>
            ) : (
              <div>
                <Tabs
                  tabs={[
                    { key: "invitado", label: "Como invitado" },
                    { key: "dueno", label: "Como dueño" },
                  ]}
                  active={papel}
                  onChange={(k) => setPapel(k as "dueno" | "invitado")}
                />
                {papel === "invitado" ? (
                  <div className="space-y-2">
                    <label className="block text-cuerpo font-semibold text-ink" htmlFor="tope">
                      Hasta cuánto puede aprobar solo
                    </label>
                    <p className="text-apoyo leading-relaxed text-ink-3">
                      Déjalo vacío si prefieres que solo vea y proponga, y que tú apruebes todo.
                    </p>
                    <input
                      id="tope"
                      inputMode="decimal"
                      placeholder="Vacío: no aprueba"
                      value={tope}
                      onChange={(e) => setTope(e.target.value)}
                      className={`${inputCls} max-w-[14rem]`}
                    />
                  </div>
                ) : (
                  <p className="text-cuerpo leading-relaxed text-ink-2">
                    Un aparato como dueño aprueba lo que sea y puede meter a otros. Dáselo solo a
                    tu propio teléfono.
                  </p>
                )}
                <PrimaryButton className="mt-5" onClick={invitar}>
                  Enseñar el código
                </PrimaryButton>
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
              <ul className="divide-y divide-line border-y border-line">
                {dispositivos.map((d) => (
                  <li key={d.id} className="flex flex-wrap items-center gap-3 py-3.5">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-cuerpo font-medium text-ink">
                        {d.nombre}
                        {d.papel === "dueno" ? (
                          <span className="ml-2 text-apoyo font-normal text-ink-3">dueño</span>
                        ) : null}
                      </p>
                      <p className="text-apoyo text-ink-3">
                        {d.activo
                          ? `${loQuePuede(d)} · visto ${cuando(d.ultimo_visto)}`
                          : `Fuera desde ${cuando(d.revocado_en)}`}
                      </p>
                    </div>
                    {d.activo ? (
                      <SecondaryButton size="sm" onClick={() => sacar(d)}>
                        Sacar
                      </SecondaryButton>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </SettingsSection>
        </div>
      )}
    </div>
  );
}
