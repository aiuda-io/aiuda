"use client";

/**
 * Asistente de primer arranque: la PRIMERA pantalla de quien abre aiuda.
 *
 * Quien la ve es el dueño de un negocio, no un técnico. Tres pantallas y un cierre,
 * y de ninguna se sale a la consola a media configuración:
 *
 *   1. Tu negocio      el nombre, y tu ayudante de Cobranza con un nombre
 *                      sugerido que puedes cambiar ahí mismo.
 *   2. Tu IA           una recomendada para esta Mac y las demás en "Otras formas
 *                      de conectar" (el mismo componente que Ajustes > Tu IA).
 *   3. Tu cartera      subes tu Excel o conectas Odoo AQUÍ, y ves la cifra.
 *   Cierre             qué quedó y qué falta, con un botón que lo resuelve.
 *
 * La IA va antes que la cartera porque leer un Excel lo hace la IA del dueño: sin
 * ella el servidor contesta que falta conectarla (`_exigir_ia_para_importar`).
 *
 * El negocio nace en modo de prueba (lo escribe el servidor al guardar el paso 1) y
 * el cierre lo dice en una línea.
 *
 * Se monta desde components/shell.tsx y solo aparece cuando el backend dice
 * `terminado: false`. Si la petición falla, no estorba: la consola se ve igual.
 */

import { useCallback, useEffect, useState } from "react";
import {
  api,
  mxn,
  type Cartera,
  type SetupEstado,
  type WhatsappStatus,
} from "@/lib/api";
import { PrimaryButton, SecondaryButton, inputCls, inputLgCls } from "@/components/ui";
import { Avatar } from "@/components/avatar";
import { appearanceForSlug } from "@/lib/look";
import { createAyudante, useAyudantes, useCatalog } from "@/lib/ayudantes-store";
import { fieldsFor } from "@/lib/integration-fields";
import { ConectarIA, nombreDeLaIA } from "@/components/ajustes/conectar-ia";
import { ExcelUpload } from "@/components/excel-upload";
import { WhatsAppPairing } from "@/components/integration-config-drawer";
import { toast } from "@/components/toast";

// --- Compuerta compartida con el Shell -------------------------------------
// Mientras el asistente esté pendiente, el tour y la checklist de activación no
// deben pintarse debajo: dos capas de bienvenida a la vez es ruido. Store mínimo
// (module-level + suscriptores), igual que lib/ayudantes-store.
let pendiente: boolean | null = null; // null = todavía no sabemos
const subs = new Set<() => void>();

function setPendiente(v: boolean) {
  pendiente = v;
  for (const fn of subs) fn();
}

/** true mientras el primer arranque siga sin resolverse o sin terminar. */
export function useSetupPendiente(): boolean {
  const [, force] = useState(0);
  useEffect(() => {
    const fn = () => force((n) => n + 1);
    subs.add(fn);
    return () => {
      subs.delete(fn);
    };
  }, []);
  return pendiente !== false;
}

// --- Memoria de la sesión ---------------------------------------------------
// Recargar la ventana a media configuración retoma el paso en el que iba.
const PASO_KEY = "aiuda-setup-paso";

function leer(key: string): string {
  try {
    return window.sessionStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function escribir(key: string, value: string) {
  try {
    if (value) window.sessionStorage.setItem(key, value);
    else window.sessionStorage.removeItem(key);
  } catch {
    /* sin sessionStorage: el asistente simplemente empieza de nuevo */
  }
}

type Paso = "negocio" | "ia" | "datos" | "cierre";
const ORDEN: Paso[] = ["negocio", "ia", "datos"];
const PASOS: Paso[] = [...ORDEN, "cierre"];

/** Cada paso pide su propio ancho: un formulario de dos campos no se estira. */
const ANCHO: Record<Paso, string> = {
  negocio: "max-w-[34rem]",
  ia: "max-w-[46rem]",
  datos: "max-w-[44rem]",
  cierre: "max-w-[40rem]",
};

const NOMBRE_POR_DEFECTO = "Mi negocio"; // el que pone el backend al crear el workspace
const AYUDANTE_SUGERIDO = "Tavo";
const OFICIO = "cobranza"; // el único oficio maduro; los demás se agregan en Ayudantes

/** El estado del asistente, con lo que el servidor agrega y lib/api aún no tipa. */
type Estado = SetupEstado & { modo_prueba?: boolean; cerrado_por_el_dueno?: boolean };

// --- Piezas visuales --------------------------------------------------------

function Titulo({ children, sub }: { children: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="mb-8">
      <h1 className="text-titulo font-semibold text-ink">{children}</h1>
      {sub && <p className="mt-2.5 max-w-[56ch] text-cuerpo leading-relaxed text-ink-2">{sub}</p>}
    </div>
  );
}

/** Nota tranquila al pie de un paso (lo honesto: qué es opcional, quién paga qué). */
function Nota({ children }: { children: React.ReactNode }) {
  return <p className="mt-7 max-w-[70ch] text-apoyo leading-relaxed text-ink-3">{children}</p>;
}

function plural(n: number, uno: string, varios: string): string {
  return `${n.toLocaleString("es-MX")} ${n === 1 ? uno : varios}`;
}

// --- El asistente -----------------------------------------------------------

export function SetupWizard() {
  const [estado, setEstado] = useState<Estado | null>(null);
  // Se decide UNA vez, al abrir: si el asistente sale o no. Después ya no se esconde
  // solo. El servidor da por terminado un negocio con nombre, IA, datos y ayudante, y
  // eso se cumple justo al cargar la cartera: el asistente se esfumaba a medio paso,
  // sin enseñar la cifra, ni el cierre, ni que el negocio empieza en modo de prueba.
  const [visible, setVisible] = useState(false);
  const [paso, setPaso] = useState<Paso>("negocio");

  const refrescar = useCallback(
    () =>
      api
        .setupEstado()
        .then((e) => {
          setEstado(e);
          return e as Estado;
        })
        .catch(() => null),
    [],
  );

  useEffect(() => {
    api
      .setupEstado()
      .then((e) => {
        setEstado(e);
        // Retomar donde iba (recargó la ventana). Un paso guardado quiere decir que
        // el dueño iba a medio asistente en esta ventana: sigue, aunque el servidor
        // ya vea completo el negocio. Al entrar a la consola ese paso se borra.
        const guardado = leer(PASO_KEY) as Paso;
        const aMedias = PASOS.includes(guardado);
        const sale = !(e as Estado).cerrado_por_el_dueno && (!e.terminado || aMedias);
        setVisible(sale);
        setPendiente(sale);
        if (sale && aMedias) setPaso(guardado);
        if (!sale) escribir(PASO_KEY, "");
      })
      .catch(() => setPendiente(false)); // sin backend: la consola se ve igual
  }, []);

  const irA = useCallback((p: Paso) => {
    setPaso(p);
    escribir(PASO_KEY, p);
    document.getElementById("asistente")?.scrollTo({ top: 0 });
  }, []);

  if (!estado || !visible) return null;

  const indice = ORDEN.indexOf(paso);

  function avanzar() {
    irA(ORDEN[indice + 1] ?? "cierre");
  }

  function atras() {
    if (paso === "cierre") irA(ORDEN[ORDEN.length - 1]);
    else if (indice > 0) irA(ORDEN[indice - 1]);
  }

  /** Cierra el asistente y entra a la consola, a Hoy o a donde se resuelve algo. */
  async function terminar(destino = "/") {
    await api.setupTerminar().catch(() => null);
    escribir(PASO_KEY, "");
    setPendiente(false);
    setVisible(false);
    // Recarga dura: el nombre del negocio, el ayudante recién creado y el estado
    // de la IA los tienen guardados varias pantallas. Entrar a una consola que
    // todavía dice "Mi negocio" arruinaría el momento.
    if (typeof window !== "undefined") window.location.href = destino;
  }

  const numero = paso === "cierre" ? ORDEN.length : indice + 1;
  const pct = paso === "cierre" ? 100 : Math.round((numero / ORDEN.length) * 100);

  return (
    <div
      id="asistente"
      role="dialog"
      aria-modal="true"
      aria-label="Configuración inicial de aiuda"
      className="fixed inset-0 z-[60] overflow-y-auto bg-bg"
    >
      {/* Centrado vertical mientras quepa; si el paso crece, la pantalla scrollea. */}
      <div
        className={`mx-auto flex min-h-full w-full flex-col justify-center px-5 py-10 sm:px-8 ${ANCHO[paso]}`}
      >
        <header className="mb-10">
          <div className="flex items-baseline justify-between">
            <span className="wordmark flex items-baseline gap-1.5">
              <span className="text-seccion font-semibold text-ink">aiuda</span>
              <span className="h-1.5 w-1.5 rounded-full bg-brand" />
            </span>
            {paso !== "cierre" && (
              <span className="eyebrow">
                paso {numero} de {ORDEN.length}
              </span>
            )}
          </div>
          <div className="mt-3 h-0.5 w-full rounded-full bg-fill-strong">
            <div
              className="h-full rounded-full bg-accent transition-[width] duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>
        </header>

        <div>
          {paso === "negocio" && (
            <PasoNegocio estado={estado} onListo={avanzar} refrescar={refrescar} />
          )}
          {paso === "ia" && <PasoIA estado={estado} onListo={avanzar} refrescar={refrescar} />}
          {paso === "datos" && (
            <PasoCartera
              estado={estado}
              onListo={avanzar}
              refrescar={refrescar}
              irAIA={() => irA("ia")}
            />
          )}
          {paso === "cierre" && (
            <PasoCierre estado={estado} irA={irA} refrescar={refrescar} onEntrar={terminar} />
          )}
        </div>

        {paso !== "cierre" && (
          <footer className="mt-10 flex items-center justify-between border-t border-line pt-5">
            {indice > 0 ? (
              <button className="btn btn-quiet" onClick={atras}>
                Atrás
              </button>
            ) : (
              <span />
            )}
            <button className="btn btn-quiet" onClick={avanzar}>
              Saltar por ahora
            </button>
          </footer>
        )}
      </div>
    </div>
  );
}

// --- Paso 1: tu negocio y tu ayudante ---------------------------------------

function PasoNegocio({
  estado,
  onListo,
  refrescar,
}: {
  estado: Estado;
  onListo: () => void;
  refrescar: () => Promise<Estado | null>;
}) {
  const { catalog } = useCatalog();
  const inicial = estado.negocio.nombre === NOMBRE_POR_DEFECTO ? "" : estado.negocio.nombre;
  const [nombre, setNombre] = useState(inicial);
  const [telefono, setTelefono] = useState("");
  const [ayudante, setAyudante] = useState(AYUDANTE_SUGERIDO);
  const [guardando, setGuardando] = useState(false);
  // Si ya hay un ayudante (volvió a este paso, o lo creó por otra vía), no se pide otro.
  const faltaAyudante = estado.ayudantes.total === 0;

  async function guardar() {
    if (!nombre.trim()) return;
    setGuardando(true);
    try {
      await api.setupNegocio(nombre.trim(), telefono.trim() || undefined);
      if (faltaAyudante && catalog) {
        // El ayudante de Cobranza nace con lo que ya sabe hacer hoy. Si nada de ese
        // oficio estuviera listo, se le da todo para que no nazca vacío.
        const delOficio = catalog.aiuditas.filter((a) => a.perfil === OFICIO);
        const listas = delOficio.filter((a) => a.live);
        const ids = (listas.length > 0 ? listas : delOficio).map((a) => a.id);
        await createAyudante(
          ayudante.trim() || AYUDANTE_SUGERIDO,
          appearanceForSlug(OFICIO),
          ids,
        );
        window.dispatchEvent(new CustomEvent("agents-changed"));
      }
      await refrescar();
      onListo();
    } catch (e) {
      toast(`No se pudo guardar: ${(e as Error).message}`, "error");
    } finally {
      setGuardando(false);
    }
  }

  return (
    <div>
      <Titulo sub="Es lo primero que vas a ver en aiuda y el nombre con el que tu ayudante se presenta con tus clientes.">
        ¿Cómo se llama tu negocio?
      </Titulo>

      <div className="space-y-7">
        <div className="space-y-2">
          <label htmlFor="setup-negocio" className="block text-cuerpo font-semibold text-ink">
            Nombre del negocio
          </label>
          <input
            id="setup-negocio"
            autoFocus
            className={inputLgCls}
            value={nombre}
            onChange={(e) => setNombre(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && guardar()}
            placeholder="Taquería La Esquina"
          />
        </div>

        <div className="space-y-2">
          <label htmlFor="setup-tel" className="block text-cuerpo font-semibold text-ink">
            Tu WhatsApp <span className="font-normal text-ink-3">(opcional)</span>
          </label>
          <p className="text-apoyo leading-relaxed text-ink-3">
            Para avisarte cuando algo necesite tu visto bueno. Lo puedes poner después.
          </p>
          <input
            id="setup-tel"
            className={inputLgCls}
            value={telefono}
            onChange={(e) => setTelefono(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && guardar()}
            placeholder="229 123 4567"
            inputMode="tel"
          />
        </div>

        {faltaAyudante && (
          <div className="space-y-2">
            <label htmlFor="setup-ayudante" className="block text-cuerpo font-semibold text-ink">
              Tu ayudante de Cobranza
            </label>
            <p className="text-apoyo leading-relaxed text-ink-3">
              Es quien redacta los recordatorios de pago para que tú los apruebes. Le pusimos un
              nombre; cámbialo si quieres.
            </p>
            <div className="flex items-center gap-3">
              <Avatar
                name={ayudante || AYUDANTE_SUGERIDO}
                size={52}
                {...appearanceForSlug(OFICIO)}
              />
              <input
                id="setup-ayudante"
                className={`${inputLgCls} min-w-0 flex-1`}
                value={ayudante}
                onChange={(e) => setAyudante(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && guardar()}
                placeholder={AYUDANTE_SUGERIDO}
                autoComplete="off"
              />
            </div>
          </div>
        )}

        <PrimaryButton
          size="lg"
          onClick={guardar}
          disabled={!nombre.trim() || guardando || (faltaAyudante && !catalog)}
        >
          {guardando ? "Guardando…" : "Continuar"}
        </PrimaryButton>
      </div>

      <Nota>
        Todo esto vive en esta computadora. Nada se sube a internet. Más ayudantes (ventas,
        recepción) los agregas después, en Ayudantes.
      </Nota>
    </div>
  );
}

// --- Paso 2: tu IA ----------------------------------------------------------

function PasoIA({
  estado,
  onListo,
  refrescar,
}: {
  estado: Estado;
  onListo: () => void;
  refrescar: () => Promise<Estado | null>;
}) {
  return (
    <div>
      <Titulo sub="Es lo que redacta, lee y propone por tu ayudante. Tú siempre decides qué sale.">
        Tu IA
      </Titulo>

      <ConectarIA enAsistente onCambio={refrescar} />

      {(estado.ia.conectada || estado.ia.env_key) && (
        <div className="mt-8">
          <PrimaryButton size="lg" onClick={onListo}>
            Continuar
          </PrimaryButton>
        </div>
      )}

      <Nota>
        La IA es tuya: la pagas directo a quien la hace o la corres gratis en tu computadora. aiuda
        no cobra por el uso ni revende nada. Puedes seguir sin conectarla, pero tu ayudante no va a
        poder redactar ni leer tu Excel.
      </Nota>
    </div>
  );
}

// --- Paso 3: tu cartera -----------------------------------------------------

/** Conectar Odoo sin salir del asistente: se guardan las credenciales, se prueban
 *  contra el Odoo de verdad y, si entran, se trae la cartera en ese momento. */
function OdooEnLinea({ onListo }: { onListo: () => void }) {
  const campos = fieldsFor("odoo");
  const [values, setValues] = useState<Record<string, string>>({});
  const [trabajando, setTrabajando] = useState<"" | "conectando" | "trayendo">("");
  const [fallo, setFallo] = useState<string | null>(null);
  const completo = campos.every((c) => (values[c.key] ?? "").trim());

  async function conectar() {
    setTrabajando("conectando");
    setFallo(null);
    try {
      await api.saveIntegration("odoo", values);
      const prueba = await api.testIntegration("odoo");
      if (prueba.ok === false) {
        setFallo(prueba.message);
        return;
      }
      setTrabajando("trayendo");
      const r = await api.sync();
      if (r.avisos.length > 0) toast(r.avisos[0], "info");
      onListo();
    } catch (e) {
      setFallo((e as Error).message);
    } finally {
      setTrabajando("");
    }
  }

  return (
    <div className="max-w-md space-y-4">
      {campos.map((c) => (
        <label key={c.key} className="block">
          <span className="block text-cuerpo font-semibold text-ink">{c.label}</span>
          <input
            className={`${inputCls} mt-2`}
            type={c.secret ? "password" : "text"}
            autoComplete="off"
            placeholder={c.placeholder}
            value={values[c.key] ?? ""}
            onChange={(e) => setValues((v) => ({ ...v, [c.key]: e.target.value }))}
          />
        </label>
      ))}
      <p className="text-apoyo leading-relaxed text-ink-3">
        La API key la genera cada usuario en sus preferencias de Odoo. Se guarda cifrada en esta
        computadora. aiuda lee tus clientes y tus facturas por cobrar; no cambia nada en tu Odoo
        hasta que tú confirmes un pago aquí.
      </p>
      <SecondaryButton onClick={conectar} disabled={!completo || trabajando !== ""}>
        {trabajando === "conectando"
          ? "Conectando…"
          : trabajando === "trayendo"
            ? "Trayendo tu cartera…"
            : "Conectar y traer mi cartera"}
      </SecondaryButton>
      {fallo && (
        <p role="status" className="rounded-[10px] bg-danger-soft px-4 py-3 text-cuerpo text-ink">
          {fallo}
        </p>
      )}
    </div>
  );
}

function PasoCartera({
  estado,
  onListo,
  refrescar,
  irAIA,
}: {
  estado: Estado;
  onListo: () => void;
  refrescar: () => Promise<Estado | null>;
  irAIA: () => void;
}) {
  const { clientes, facturas } = estado.datos;
  const [abierto, setAbierto] = useState<"excel" | "odoo" | null>(null);
  const [cartera, setCartera] = useState<Cartera | null>(null);
  const hayDatos = facturas > 0 || clientes > 0;

  // La cifra: lo que se acaba de cargar, dicho en dinero.
  useEffect(() => {
    if (facturas === 0) return;
    let vivo = true;
    api
      .cartera()
      .then((c) => vivo && setCartera(c))
      .catch(() => undefined);
    return () => {
      vivo = false;
    };
  }, [facturas]);

  const alCargar = async () => {
    await refrescar();
    setAbierto(null);
  };

  // Sin superficie propia: el importador ya trae las suyas (no hay caja dentro de caja).
  const subir = (
    <div className="reveal mt-5">
      <ExcelUpload onImported={alCargar} />
    </div>
  );

  if (hayDatos) {
    const partes = [
      facturas > 0 ? plural(facturas, "factura", "facturas") : "",
      clientes > 0 ? plural(clientes, "cliente", "clientes") : "",
    ].filter(Boolean);
    return (
      <div>
        <Titulo sub="De aquí saca tu ayudante el trabajo: a quién le vendiste y quién te debe.">
          Tu cartera
        </Titulo>

        {cartera && facturas > 0 ? (
          <div>
            <p className="hero-num tnum text-cifra text-ink">{mxn(cartera.open_total)}</p>
            <p className="mt-1.5 text-cuerpo text-ink-2">
              por cobrar en {plural(cartera.open_count, "factura abierta", "facturas abiertas")}.
              Ya tenemos {partes.join(" de ")}.
            </p>
          </div>
        ) : (
          <p className="text-seccion font-semibold text-ink">Ya tenemos {partes.join(" y ")}.</p>
        )}
        {facturas === 0 && (
          <p className="mt-2 max-w-[56ch] text-cuerpo leading-relaxed text-ink-2">
            Todavía no hay facturas. Sin ellas tu ayudante no tiene qué cobrar: sube la hoja donde
            llevas lo que te deben.
          </p>
        )}

        <div className="mt-8 flex flex-wrap items-center gap-2">
          <PrimaryButton size="lg" onClick={onListo}>
            Continuar
          </PrimaryButton>
          <button
            className="btn btn-quiet btn-lg"
            aria-expanded={abierto === "excel"}
            onClick={() => setAbierto(abierto === "excel" ? null : "excel")}
          >
            Subir otro archivo
          </button>
        </div>
        {abierto === "excel" && subir}
      </div>
    );
  }

  // Una llave puesta por fuera de la consola también sirve para leer la hoja.
  const conIA = estado.ia.conectada || estado.ia.env_key;

  return (
    <div>
      <Titulo sub="De aquí saca tu ayudante el trabajo: a quién le vendiste y quién te debe. Se carga aquí mismo.">
        Tu cartera
      </Titulo>

      <ul className="divide-y divide-line border-y border-line">
        <li className="py-4">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
            <div className="min-w-0 flex-1">
              <p className="text-cuerpo font-semibold text-ink">Subir un Excel</p>
              <p className="mt-0.5 text-apoyo leading-relaxed text-ink-3">
                Tu hoja tal como la llevas, sin plantilla. Tu IA reconoce las columnas y tú las
                revisas antes de cargar.
              </p>
            </div>
            {conIA ? (
              abierto === "excel" ? (
                <SecondaryButton onClick={() => setAbierto(null)}>Cerrar</SecondaryButton>
              ) : (
                <PrimaryButton onClick={() => setAbierto("excel")}>Subir mi archivo</PrimaryButton>
              )
            ) : (
              <SecondaryButton onClick={irAIA}>Conectar mi IA primero</SecondaryButton>
            )}
          </div>
          {!conIA && (
            <p className="mt-2 text-apoyo leading-relaxed text-ink-2">
              Para entender tu hoja hace falta tu IA, y todavía no está conectada.
            </p>
          )}
          {abierto === "excel" && conIA && subir}
        </li>

        <li className="py-4">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/brand/int/odoo.svg" alt="" aria-hidden="true" className="h-6 w-6 shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="text-cuerpo font-semibold text-ink">Conectar Odoo</p>
              <p className="mt-0.5 text-apoyo leading-relaxed text-ink-3">
                Si llevas tu negocio ahí, aiuda lee tus clientes y tus facturas por cobrar.
              </p>
            </div>
            <SecondaryButton
              aria-expanded={abierto === "odoo"}
              onClick={() => setAbierto(abierto === "odoo" ? null : "odoo")}
            >
              {abierto === "odoo" ? "Cerrar" : "Conectar"}
            </SecondaryButton>
          </div>
          {abierto === "odoo" && (
            <div className="reveal mt-4">
              <OdooEnLinea onListo={alCargar} />
            </div>
          )}
        </li>
      </ul>

      <Nota>
        WhatsApp se conecta en el siguiente paso. El SAT, tu correo y lo demás, cuando quieras, en
        Ajustes. También puedes seguir sin cartera y cargarla después.
      </Nota>
    </div>
  );
}

// --- Cierre -----------------------------------------------------------------

/** Un renglón del cierre: qué es, cómo quedó y, si falta, el botón que lo resuelve. */
function Renglon({
  label,
  valor,
  ok,
  accion,
  children,
}: {
  label: string;
  valor: string;
  ok: boolean;
  accion?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <li className="py-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <p
            className="mark"
            style={
              { "--mark": ok ? "var(--color-ok)" : "var(--color-line-strong)" } as React.CSSProperties
            }
          >
            {label}
          </p>
          <p className="mt-0.5 text-cuerpo text-ink">{valor}</p>
        </div>
        {accion}
      </div>
      {children}
    </li>
  );
}

function PasoCierre({
  estado,
  irA,
  refrescar,
  onEntrar,
}: {
  estado: Estado;
  irA: (p: Paso) => void;
  refrescar: () => Promise<Estado | null>;
  onEntrar: (destino?: string) => void;
}) {
  const [entrando, setEntrando] = useState(false);
  const [whatsapp, setWhatsapp] = useState<WhatsappStatus | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [vincular, setVincular] = useState(false);
  const { ayudantes } = useAyudantes();
  const nombres = (ayudantes ?? []).map((a) => a.name).join(", ");
  const { clientes, facturas } = estado.datos;
  const conIA = estado.ia.conectada || estado.ia.env_key;
  const listo = conIA && estado.ayudantes.total > 0 && facturas > 0;

  const mirarWhatsapp = useCallback(
    () =>
      api
        .whatsappStatus()
        .then(setWhatsapp)
        .catch(() => setWhatsapp(null)),
    [],
  );
  useEffect(() => {
    mirarWhatsapp();
    // Lo que hay que saber antes de vincular el número (no es la vía oficial de Meta).
    api
      .integrationDetail("whatsapp")
      .then((d) => setAviso((d as { warning?: string | null }).warning ?? null))
      .catch(() => undefined);
  }, [mirarWhatsapp]);

  const datos =
    facturas > 0 || clientes > 0
      ? [
          facturas > 0 ? plural(facturas, "factura", "facturas") : "",
          clientes > 0 ? plural(clientes, "cliente", "clientes") : "",
        ]
          .filter(Boolean)
          .join(" y ")
      : estado.datos.fuentes.length > 0
        ? "Conectada. Todavía no llega ninguna factura"
        : "Sin cargar. Tu ayudante no tiene a quién cobrarle";

  return (
    <div>
      <Titulo
        sub={
          listo
            ? "Tu ayudante ya puede redactar. Nada sale a tus clientes sin que tú lo apruebes."
            : "Puedes empezar así y completar lo que falta aquí mismo o después. Nada sale a tus clientes sin que tú lo apruebes."
        }
      >
        {listo ? "Listo. Ya puedes empezar." : "Casi listo."}
      </Titulo>

      <ul className="divide-y divide-line border-y border-line">
        <Renglon
          label="Tu negocio"
          valor={
            estado.negocio.nombre === NOMBRE_POR_DEFECTO
              ? "Sin nombre todavía"
              : estado.negocio.nombre
          }
          ok={estado.negocio.listo}
          accion={
            !estado.negocio.listo && (
              <SecondaryButton onClick={() => irA("negocio")}>Ponerle nombre</SecondaryButton>
            )
          }
        />
        <Renglon
          label="Tu ayudante de Cobranza"
          valor={
            estado.ayudantes.total > 0
              ? nombres || "Creado"
              : "Sin crear. Nadie va a redactar tus recordatorios"
          }
          ok={estado.ayudantes.total > 0}
          accion={
            estado.ayudantes.total === 0 && (
              <SecondaryButton onClick={() => irA("negocio")}>Crearlo</SecondaryButton>
            )
          }
        />
        <Renglon
          label="Tu IA"
          valor={
            estado.ia.conectada
              ? `Conectada: ${nombreDeLaIA(estado.ia.proveedor)}`
              : estado.ia.env_key
                ? "Conectada con una llave puesta fuera de la consola"
                : "Sin conectar. Tu ayudante no puede redactar"
          }
          ok={conIA}
          accion={
            !conIA && <SecondaryButton onClick={() => irA("ia")}>Conectarla</SecondaryButton>
          }
        />
        <Renglon
          label="Tu cartera"
          valor={datos}
          ok={facturas > 0}
          accion={
            facturas === 0 && (
              <SecondaryButton onClick={() => irA("datos")}>Cargarla</SecondaryButton>
            )
          }
        />
        <Renglon
          label="WhatsApp"
          valor={
            whatsapp?.connected
              ? `Conectado${whatsapp.telefono ? `: +${whatsapp.telefono}` : ""}`
              : "Sin conectar. Tu ayudante redacta, pero no puede mandar"
          }
          ok={!!whatsapp?.connected}
          accion={
            !whatsapp?.connected && (
              <SecondaryButton aria-expanded={vincular} onClick={() => setVincular((v) => !v)}>
                {vincular ? "Cerrar" : "Conectarlo"}
              </SecondaryButton>
            )
          }
        >
          {vincular && !whatsapp?.connected && (
            <div className="reveal mt-4">
              <WhatsAppPairing
                discreto
                aviso={aviso}
                onChange={() => {
                  mirarWhatsapp();
                  refrescar();
                }}
              />
            </div>
          )}
        </Renglon>
      </ul>

      {/* Lo que el dueño tiene que saber antes de su primer "Aprobar". */}
      {estado.modo_prueba && (
        <p className="mt-6 text-cuerpo leading-relaxed text-ink-2">
          <strong className="font-semibold text-ink">Empiezas en modo de prueba:</strong> apruebas
          y ves cómo escribe tu ayudante, pero nada sale a tus clientes hasta que lo apagues en
          Ajustes.
        </p>
      )}

      <div className="mt-8">
        <PrimaryButton
          size="lg"
          onClick={() => {
            setEntrando(true);
            onEntrar("/");
          }}
          disabled={entrando}
        >
          {entrando ? "Entrando…" : "Entrar a aiuda"}
        </PrimaryButton>
      </div>

      <Nota>
        Este asistente no vuelve a salir. Todo lo de aquí lo puedes cambiar en Ajustes y en
        Ayudantes.
      </Nota>
    </div>
  );
}
