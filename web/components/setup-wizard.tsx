"use client";

/**
 * Asistente de primer arranque: la PRIMERA pantalla de quien abre aiuda.
 *
 * Quien la ve es el dueño de un negocio, no un técnico: aquí no existen "API
 * key", "endpoint" ni "modelo LLM". Se habla de tu negocio, tu IA, tus datos y
 * tu ayudante. Cuatro pasos, todos saltables, y un cierre honesto que dice qué
 * quedó configurado y qué no.
 *
 * Se lee de un vistazo, no se lee de corrido: cada opción es una tarjeta grande
 * con el logo de quien la provee, el estado REAL que aiuda detectó en esta
 * computadora debajo del logo, y una sola acción clara. Los párrafos quedan al
 * pie, en una línea discreta.
 *
 * Dos fuentes de verdad, ambas del backend local:
 *   - GET /v1/setup/estado  (siempre): negocio, IA conectada, datos, ayudantes.
 *   - GET /v1/setup/maquina (opcional): chip, memoria, Ollama, modelos que SÍ
 *     caben en este equipo y qué CLIs de IA están instalados. Si no responde,
 *     el paso de la IA sigue funcionando con lo que ya sabe /v1/setup/estado.
 *
 * Se monta desde components/shell.tsx y solo aparece cuando el backend dice
 * `terminado: false`. Si la petición falla, no estorba: la consola se ve igual.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  api,
  type ModeloRecomendado,
  type ProviderMode,
  type ProviderName,
  type ProviderTest,
  type ServidorIAEnRed,
  type SetupEstado,
  type SetupMaquina,
} from "@/lib/api";
import { PrimaryButton, SecondaryButton, inputLgCls } from "@/components/ui";
import { Avatar } from "@/components/avatar";
import { appearanceForSlug } from "@/lib/look";
import { createAyudante, useCatalog } from "@/lib/ayudantes-store";
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
// Conectar Odoo o subir un Excel viven en otra pantalla. Al salir, el asistente
// se hace a un lado (queda una barra para volver) y recuerda en qué paso iba.
const PASO_KEY = "aiuda-setup-paso";
const PAUSA_KEY = "aiuda-setup-pausa";

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

type Paso = "negocio" | "ia" | "datos" | "ayudante" | "cierre";
const ORDEN: Paso[] = ["negocio", "ia", "datos", "ayudante"];

/** Cada paso pide su propio ancho: un formulario de dos campos no se estira a
 *  60rem, y tres tarjetas grandes no caben en 34rem. */
const ANCHO: Record<Paso, string> = {
  negocio: "max-w-[34rem]",
  ia: "max-w-[72rem]",
  datos: "max-w-[58rem]",
  ayudante: "max-w-[46rem]",
  cierre: "max-w-[38rem]",
};

const NOMBRE_POR_DEFECTO = "Mi negocio"; // el que pone el backend al crear el workspace

// --- Piezas visuales --------------------------------------------------------

function Check({ className = "h-4 w-4 text-ok" }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={`shrink-0 ${className}`} fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="7" fill="currentColor" opacity="0.14" />
      <path
        d="m5 8 2 2 4-4.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Arrow() {
  return (
    <svg viewBox="0 0 12 12" className="h-3 w-3 shrink-0 text-ink-3" fill="none" aria-hidden="true">
      <path
        d="M3 6h6m-2.5-2.5L9 6 6.5 8.5"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Titulo({ children, sub }: { children: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="mb-7">
      <h1 className="text-cifra font-semibold leading-[1.15] tracking-[-0.015em] text-ink">
        {children}
      </h1>
      {sub && <p className="mt-2.5 max-w-[52ch] text-cuerpo leading-relaxed text-ink-2">{sub}</p>}
    </div>
  );
}

/** Nota tranquila al pie de un paso (lo honesto: qué es opcional, quién paga qué). */
function Nota({ children }: { children: React.ReactNode }) {
  return <p className="mt-6 max-w-[80ch] text-apoyo leading-relaxed text-ink-3">{children}</p>;
}

/** Logo de marca. El proyecto sirve estáticos desde FastAPI (export estático),
 *  así que aquí se usa `img` como en el resto de la consola, no next/image. */
function Logo({ src, className = "h-8 w-8" }: { src: string; className?: string }) {
  /* eslint-disable-next-line @next/next/no-img-element */
  return <img src={src} alt="" className={`${className} object-contain`} aria-hidden="true" />;
}

/** Dos equipos conectados: la IA que vive en otra computadora de la oficina. */
function IconoRed({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={`${className} text-ink-2`} fill="none" aria-hidden="true">
      <rect x="2.5" y="4" width="8" height="6" rx="1.4" stroke="currentColor" strokeWidth="1.4" />
      <rect x="13.5" y="14" width="8" height="6" rx="1.4" stroke="currentColor" strokeWidth="1.4" />
      <path d="M6.5 10v3.5a1.5 1.5 0 0 0 1.5 1.5h5.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

/** Ícono de hoja de cálculo (Excel no tiene logo propio en el repo y usar el de
 *  Microsoft mentiría: aiuda lee cualquier hoja, venga de donde venga). */
function IconoHoja({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={`${className} text-ink-2`} fill="none" aria-hidden="true">
      <rect x="3.5" y="3.5" width="17" height="17" rx="2.5" stroke="currentColor" strokeWidth="1.4" />
      <path d="M3.5 9.5h17M3.5 15h17M9.5 3.5v17" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}

type Tono = "ok" | "pendiente" | "apagado";

function Punto({ tono }: { tono: Tono }) {
  const color = tono === "ok" ? "bg-ok" : tono === "pendiente" ? "bg-warn" : "bg-ink-3/50";
  return <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${color}`} aria-hidden="true" />;
}

/** Tarjeta grande: logo, nombre, qué es, el estado REAL detectado y una acción.
 *  Toda la tarjeta es el botón (nada de botón dentro de botón); el rótulo de
 *  abajo dice qué pasa al hacer clic. */
function Tarjeta({
  logo,
  nombre,
  resumen,
  estado,
  tono = "apagado",
  chip,
  chipPunto = true,
  accion,
  principal,
  activa,
  onClick,
  disabled,
}: {
  logo: React.ReactNode;
  nombre: string;
  resumen: string;
  estado: string;
  tono?: Tono;
  chip?: string;
  /** El chip lleva punto verde solo cuando es algo DETECTADO (un CLI instalado),
   *  no cuando es un dato del equipo (el chip del chip y la memoria). */
  chipPunto?: boolean;
  accion: string;
  principal?: boolean;
  activa?: boolean;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={activa}
      className={`group flex h-full flex-col items-center rounded-xl border bg-surface px-5 pb-5 pt-7 text-center transition-colors disabled:opacity-60 ${
        activa ? "border-accent bg-accent-soft/50" : "border-line hover:border-line-strong"
      }`}
    >
      <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl border border-line bg-panel">
        {logo}
      </span>
      <span className="mt-4 block text-cuerpo font-semibold leading-tight text-ink">{nombre}</span>
      <span className="mt-1.5 block text-cuerpo leading-relaxed text-ink-3">{resumen}</span>
      {chip && (
        <span className="mt-3 inline-flex items-center gap-1.5 rounded-full border border-line bg-panel px-2.5 py-1 text-sello leading-[1.35] text-ink-2">
          {chipPunto && <Punto tono="ok" />}
          {chip}
        </span>
      )}
      <span className="mt-3 inline-flex items-center gap-1.5 text-apoyo leading-tight text-ink-2">
        <Punto tono={tono} />
        {estado}
      </span>
      <span className="mt-auto block w-full pt-5">
        <span
          className={`block w-full rounded-md px-3 py-2.5 text-cuerpo font-medium transition-colors ${
            principal
              ? "bg-accent text-surface group-hover:bg-accent-strong"
              : "border border-line bg-surface text-ink-2 group-hover:border-line-strong group-hover:text-ink"
          }`}
        >
          {accion}
        </span>
      </span>
    </button>
  );
}

/** Panel que se abre debajo de las tarjetas con el detalle de la elegida. Al
 *  abrirse se trae a la vista: si creció más allá de la ventana, el dueño no
 *  tiene que adivinar que hay que bajar. */
function Panel({ children }: { children: React.ReactNode }) {
  const caja = useRef<HTMLDivElement>(null);
  useEffect(() => {
    caja.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, []);
  return (
    <div ref={caja} className="reveal mt-5 rounded-xl border border-line bg-panel px-6 py-5">
      {children}
    </div>
  );
}

/** Resultado de probar la IA, en palabras del dueño. */
function ResultadoIA({ test }: { test: ProviderTest }) {
  if (test.ok) {
    return (
      <div className="mt-4 flex items-start gap-2.5 rounded-lg border border-line bg-surface px-4 py-3">
        <Check />
        <p className="text-cuerpo leading-relaxed text-ink-2">
          Tu IA respondió bien. Ya puede trabajar.
        </p>
      </div>
    );
  }
  return (
    <div className="mt-4 rounded-lg border border-line bg-surface px-4 py-3">
      <p className="text-cuerpo font-medium text-ink">No pudo responder</p>
      <p className="mt-1 text-cuerpo leading-relaxed text-ink-2">{test.error}</p>
    </div>
  );
}

// --- El asistente -----------------------------------------------------------

export function SetupWizard() {
  const router = useRouter();
  const [estado, setEstado] = useState<SetupEstado | null>(null);
  const [cerrado, setCerrado] = useState(false);
  const [paso, setPaso] = useState<Paso>("negocio");
  const [pausado, setPausado] = useState(false);

  const refrescar = useCallback(
    () =>
      api
        .setupEstado()
        .then((e) => {
          setEstado(e);
          return e;
        })
        .catch(() => null),
    [],
  );

  useEffect(() => {
    api
      .setupEstado()
      .then((e) => {
        setEstado(e);
        setPendiente(!e.terminado);
        if (e.terminado) return;
        // Retomar donde iba (salió a conectar Odoo, recargó la ventana).
        const guardado = leer(PASO_KEY);
        if (guardado) setPaso(guardado as Paso);
        setPausado(leer(PAUSA_KEY) === "1");
      })
      .catch(() => setPendiente(false)); // sin backend: la consola se ve igual
  }, []);

  const irA = useCallback((p: Paso) => {
    setPaso(p);
    escribir(PASO_KEY, p);
    window.scrollTo({ top: 0 });
  }, []);

  if (!estado || estado.terminado || cerrado) return null;

  // Ya hay ayudantes: el paso 4 no tiene nada que pedir.
  const visible = (p: Paso) => p !== "ayudante" || estado.ayudantes.total === 0;
  const indice = ORDEN.indexOf(paso);

  function avanzar() {
    const siguiente = ORDEN.slice(indice + 1).find(visible);
    irA(siguiente ?? "cierre");
  }

  function atras() {
    if (paso === "cierre") {
      const ultimo = [...ORDEN].reverse().find(visible);
      irA(ultimo ?? "negocio");
      return;
    }
    const anterior = [...ORDEN.slice(0, indice)].reverse().find(visible);
    if (anterior) irA(anterior);
  }

  /** Sale a otra pantalla (Odoo, Excel) sin perder el hilo del asistente. */
  function salirA(href: string) {
    escribir(PAUSA_KEY, "1");
    setPausado(true);
    router.push(href);
  }

  function volver() {
    escribir(PAUSA_KEY, "");
    setPausado(false);
    refrescar();
    router.push("/");
  }

  async function terminar() {
    await api.setupTerminar().catch(() => null);
    escribir(PASO_KEY, "");
    escribir(PAUSA_KEY, "");
    setPendiente(false);
    setCerrado(true);
    // Recarga dura: el nombre del negocio, el ayudante recién creado y el
    // estado de la IA los tienen cacheados varias pantallas. Entrar a una
    // consola que todavía dice "Mi negocio" arruinaría el momento.
    if (typeof window !== "undefined") window.location.href = "/";
  }

  // Pausado: el dueño está conectando Odoo o subiendo su Excel en otra pantalla.
  if (pausado) {
    return (
      <div className="fixed inset-x-0 bottom-0 z-50 flex justify-center px-4 pb-4">
        <button
          onClick={volver}
          className="flex items-center gap-3 rounded-full border border-line bg-surface py-2 pl-4 pr-3 text-cuerpo text-ink-2 elev-md transition-colors hover:text-ink"
        >
          Estás en la configuración inicial
          <span className="flex items-center gap-1.5 font-medium text-accent-ink">
            Volver al asistente
            <Arrow />
          </span>
        </button>
      </div>
    );
  }

  const paso4 = ORDEN.filter(visible).length; // pasos que este dueño sí verá
  const numero = paso === "cierre" ? paso4 : ORDEN.slice(0, indice + 1).filter(visible).length;
  const pct = paso === "cierre" ? 100 : Math.round((numero / paso4) * 100);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Configuración inicial de aiuda"
      className="fixed inset-0 z-[60] overflow-y-auto bg-bg"
    >
      {/* Centrado vertical mientras quepa; si el paso crece, la pantalla scrollea. */}
      <div
        className={`mx-auto flex min-h-full w-full flex-col justify-center px-8 py-10 ${ANCHO[paso]}`}
      >
        <header className="mb-8">
          <div className="flex items-baseline justify-between">
            <span className="flex items-baseline gap-1.5">
              <span className="text-cuerpo font-semibold tracking-tight text-ink">aiuda</span>
              <span className="h-1.5 w-1.5 rounded-full bg-accent" />
            </span>
            {paso !== "cierre" && (
              <span className="text-rotulo font-medium uppercase tracking-[0.07em] text-ink-3">
                Paso {numero} de {paso4}
              </span>
            )}
          </div>
          <div className="mt-3 h-0.5 w-full rounded-full bg-line/70">
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
          {paso === "datos" && <PasoDatos estado={estado} onListo={avanzar} onSalir={salirA} />}
          {paso === "ayudante" && <PasoAyudante onListo={avanzar} refrescar={refrescar} />}
          {paso === "cierre" && <PasoCierre estado={estado} onEntrar={terminar} />}
        </div>

        {paso !== "cierre" && (
          <footer className="mt-9 flex items-center justify-between border-t border-line pt-5">
            {indice > 0 ? <SecondaryButton onClick={atras}>Atrás</SecondaryButton> : <span />}
            <button
              onClick={avanzar}
              className="text-cuerpo text-ink-3 transition-colors hover:text-ink"
            >
              Saltar por ahora
            </button>
          </footer>
        )}
      </div>
    </div>
  );
}

// --- Paso 1: tu negocio -----------------------------------------------------

function PasoNegocio({
  estado,
  onListo,
  refrescar,
}: {
  estado: SetupEstado;
  onListo: () => void;
  refrescar: () => Promise<SetupEstado | null>;
}) {
  const inicial = estado.negocio.nombre === NOMBRE_POR_DEFECTO ? "" : estado.negocio.nombre;
  const [nombre, setNombre] = useState(inicial);
  const [telefono, setTelefono] = useState("");
  const [guardando, setGuardando] = useState(false);

  async function guardar() {
    if (!nombre.trim()) return;
    setGuardando(true);
    try {
      await api.setupNegocio(nombre.trim(), telefono.trim());
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
      <Titulo sub="Es lo primero que vas a ver en tu consola y el nombre con el que tu ayudante se presenta con tus clientes.">
        ¿Cómo se llama tu negocio?
      </Titulo>

      <div className="space-y-6">
        <div className="space-y-2">
          <label htmlFor="setup-negocio" className="block text-cuerpo font-medium text-ink">
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
          <label htmlFor="setup-tel" className="block text-cuerpo font-medium text-ink">
            Tu WhatsApp <span className="font-normal text-ink-3">(opcional)</span>
          </label>
          <p className="text-cuerpo leading-relaxed text-ink-3">
            Para avisarte cuando algo necesite tu visto bueno. Lo puedes dejar en blanco y ponerlo
            después.
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

        <PrimaryButton size="lg" onClick={guardar} disabled={!nombre.trim() || guardando}>
          {guardando ? "Guardando…" : "Continuar"}
        </PrimaryButton>
      </div>

      <Nota>Todo esto vive en esta computadora. Nada se sube a internet.</Nota>
    </div>
  );
}

// --- Paso 2: tu IA ----------------------------------------------------------

const LOGO_IA: Record<string, string> = {
  local: "/brand/ollama.svg",
  claude: "/brand/anthropic.svg",
  codex: "/brand/openai.svg",
  claude_cli: "/brand/anthropic.svg",
  codex_cli: "/brand/openai.svg",
};

const NOMBRE_IA: Record<string, string> = {
  local: "En esta computadora",
  claude: "Claude",
  codex: "OpenAI",
};

const TERMINOS_CLAUDE = "https://www.anthropic.com/legal/consumer-terms";
const TERMINOS_OPENAI = "https://developers.openai.com/codex/auth";

type Descarga = {
  estado: "descargando" | "listo" | "error";
  pct: number;
  error?: string;
  /** Lo que dice el backend de esa descarga ("Bajando 2 de 5 partes"). */
  detalle?: string;
};

/** Etiqueta honesta de si un modelo cabe en la memoria de este equipo. */
function EtiquetaCabe({ cabe }: { cabe: ModeloRecomendado["cabe"] }) {
  const meta =
    cabe === "bien"
      ? { texto: "Le queda bien", cls: "bg-ok-soft text-ok" }
      : cabe === "justo"
        ? { texto: "Justo", cls: "bg-warn-strong-soft text-warn-strong" }
        : { texto: "No le queda", cls: "bg-line/60 text-ink-3" };
  return (
    <span
      className={`rounded px-1.5 py-px text-sello font-medium leading-[1.5] ${meta.cls}`}
    >
      {meta.texto}
    </span>
  );
}

function PasoIA({
  estado,
  onListo,
  refrescar,
}: {
  estado: SetupEstado;
  onListo: () => void;
  refrescar: () => Promise<SetupEstado | null>;
}) {
  const [maquina, setMaquina] = useState<SetupMaquina | null>(null);
  const [abierta, setAbierta] = useState<"local" | "claude" | "codex" | "red" | null>(null);
  const [llave, setLlave] = useState("");
  const [trabajando, setTrabajando] = useState<"" | ProviderName>("");
  // La PRIMERA vez que se despierta un CLI puede tardar media hora de reloj de
  // usuario (26 s medidos en una Mac con Apple Silicon; después, 3 s). Sin
  // decirlo, "Conectando…" se lee como colgado.
  const [tardando, setTardando] = useState(false);
  const [buscando, setBuscando] = useState(false);
  // IA compartida en la red de la oficina: null = todavía no hemos buscado.
  const [enRed, setEnRed] = useState<ServidorIAEnRed[] | null>(null);
  const [avisoRed, setAvisoRed] = useState("");
  const [buscandoRed, setBuscandoRed] = useState(false);
  const [test, setTest] = useState<ProviderTest | null>(null);
  const [descargas, setDescargas] = useState<Record<string, Descarga>>({});
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const ia = estado.ia;

  // La radiografía de la máquina es un extra: si el backend no la trae (versión
  // vieja, endpoint apagado), el paso funciona igual con /v1/setup/estado.
  const mirarMaquina = useCallback(
    () =>
      api
        .setupMaquina()
        .then((m) => {
          setMaquina(m);
          return m;
        })
        .catch(() => null),
    [],
  );

  useEffect(() => {
    mirarMaquina();
  }, [mirarMaquina]);

  useEffect(() => {
    const actuales = timers.current;
    return () => {
      for (const t of Object.values(actuales)) clearTimeout(t);
    };
  }, []);

  // Lo que sabemos de esta computadora: manda la radiografía; si no llegó, el
  // estado de siempre.
  const modelos = maquina ? maquina.modelos_instalados.map((m) => m.nombre) : ia.modelos_locales;
  const ollamaCorriendo = maquina ? maquina.ollama.corriendo : ia.ollama_corriendo;
  const ollamaInstalado = maquina ? maquina.ollama.instalado : ia.ollama_corriendo;
  const recomendados = maquina?.recomendados ?? [];
  const sugerido =
    (ollamaCorriendo ? ia.modelo_sugerido : null) ??
    recomendados.find((r) => r.instalado)?.nombre ??
    modelos[0] ??
    null;
  const equipo = maquina?.equipo;
  const descargando = Object.entries(descargas).find(([, d]) => d.estado === "descargando");

  // Lo que se puede elegir en esta computadora: primero lo que YA está bajado,
  // luego lo que aiuda recomienda para este equipo. Sin repetidos y sin lo que
  // no le cabe a la memoria (a menos que no quede nada más que ofrecer).
  const catalogo: ModeloRecomendado[] = (() => {
    const porNombre = new Map<string, ModeloRecomendado>();
    for (const m of maquina?.modelos_instalados ?? []) {
      porNombre.set(m.nombre, {
        nombre: m.nombre,
        tam_gb: m.tam_gb,
        cabe: "bien",
        instalado: true,
        recomendado: false,
        para: "Ya está en tu computadora",
      });
    }
    for (const r of recomendados) {
      const previo = porNombre.get(r.nombre);
      porNombre.set(r.nombre, { ...r, instalado: r.instalado || !!previo?.instalado });
    }
    const todos = [...porNombre.values()];
    const caben = todos.filter((m) => m.instalado || m.cabe !== "no");
    return (caben.length > 0 ? caben : todos)
      .sort(
        (a, b) =>
          Number(b.instalado) - Number(a.instalado) || Number(b.recomendado) - Number(a.recomendado),
      )
      .slice(0, 4);
  })();

  /** Guarda la credencial y la prueba de inmediato. `modo` es "api_key" (la llave que
   *  pega el dueño) o "cli" (el Claude Code o el Codex que ya está en esta
   *  computadora: sin secreto, la sesión vive dentro del propio programa). */
  async function conectar(name: ProviderName, secreto: string, modo: ProviderMode = "api_key") {
    setTrabajando(name);
    setTest(null);
    setTardando(false);
    const avisoLento =
      modo === "cli" ? window.setTimeout(() => setTardando(true), 6000) : undefined;
    try {
      await api.saveProvider(name, modo, secreto);
      const resultado = await api.testProvider();
      setTest(resultado);
      await refrescar();
    } catch (e) {
      setTest({ ok: false, code: "error", error: (e as Error).message });
    } finally {
      if (avisoLento !== undefined) window.clearTimeout(avisoLento);
      setTardando(false);
      setTrabajando("");
    }
  }

  const usarModelo = (modelo: string) =>
    conectar("local", JSON.stringify({ base_url: ia.base_url_local, model: modelo }));

  async function buscarEnLaRed() {
    if (buscandoRed) return;
    setAbierta("red");
    setBuscandoRed(true);
    try {
      const r = await api.setupBuscarEnRed();
      setEnRed(r.encontrados);
      setAvisoRed(r.aviso || "");
      if (r.encontrados.length === 0) {
        toast("No encontramos ninguna IA compartida en tu red.", "info");
      }
    } catch {
      setEnRed([]);
      setAvisoRed("No pudimos revisar la red desde aquí.");
    } finally {
      setBuscandoRed(false);
    }
  }

  async function buscarDeNuevo() {
    setBuscando(true);
    const [nuevo] = await Promise.all([refrescar(), mirarMaquina()]);
    setBuscando(false);
    if (nuevo && !nuevo.ia.ollama_corriendo) {
      toast("Todavía no vemos un modelo corriendo en esta computadora.", "info");
    }
  }

  // Descarga de un modelo local: se dispara en el backend y se sondea hasta que
  // queda listo. Al quedar listo se conecta solo (para eso lo bajaste). Si el
  // servidor deja de saber de esa descarga (se reinició a media bajada), se dice
  // en vez de girar para siempre.
  function sondear(modelo: string, perdidas = 0) {
    timers.current[modelo] = setTimeout(async () => {
      try {
        const p = await api.setupProgresoModelo(modelo);
        const pct = Math.max(0, Math.min(100, Math.round(p.porcentaje ?? p.pct ?? 0)));
        if (p.estado === "listo") {
          setDescargas((d) => ({ ...d, [modelo]: { estado: "listo", pct: 100 } }));
          await mirarMaquina();
          await usarModelo(modelo);
          return;
        }
        const motivo = p.detalle || p.error || p.mensaje || "";
        if (p.estado === "error") {
          setDescargas((d) => ({
            ...d,
            [modelo]: { estado: "error", pct, error: motivo || "No se pudo descargar." },
          }));
          return;
        }
        if (p.estado === "desconocido") {
          if (perdidas >= 6) {
            setDescargas((d) => ({
              ...d,
              [modelo]: {
                estado: "error",
                pct,
                error: "Perdimos el rastro de esta descarga. Vuelve a intentar.",
              },
            }));
            return;
          }
          sondear(modelo, perdidas + 1);
          return;
        }
        setDescargas((d) => ({ ...d, [modelo]: { estado: "descargando", pct, detalle: motivo } }));
        sondear(modelo);
      } catch (e) {
        setDescargas((d) => ({
          ...d,
          [modelo]: { estado: "error", pct: 0, error: (e as Error).message },
        }));
      }
    }, 1500);
  }

  async function descargar(modelo: string) {
    setDescargas((d) => ({ ...d, [modelo]: { estado: "descargando", pct: 0 } }));
    try {
      await api.setupDescargarModelo(modelo);
    } catch (e) {
      setDescargas((d) => ({
        ...d,
        [modelo]: { estado: "error", pct: 0, error: (e as Error).message },
      }));
      return;
    }
    sondear(modelo);
  }

  // Ya quedó: se muestra en claro y se sigue.
  if (ia.conectada) {
    const clave = ia.proveedor && LOGO_IA[ia.proveedor] ? ia.proveedor : "";
    const comoSeLlama =
      ia.proveedor === "local"
        ? "un modelo en esta computadora"
        : ia.proveedor === "claude_cli"
          ? "el Claude Code de esta computadora"
          : ia.proveedor === "codex_cli"
            ? "el Codex de esta computadora"
            : ia.proveedor === "claude"
              ? "Claude"
              : ia.proveedor === "codex"
                ? "OpenAI"
                : "tu IA";
    return (
      /* Ya conectada no hay nada que comparar: el paso se angosta a la medida
         del mensaje en vez de estirar una tarjeta sola a lo ancho. */
      <div className="max-w-[46rem]">
        <Titulo sub="Es el cerebro que redacta, lee y propone. Tú siempre decides qué sale.">
          Tu IA
        </Titulo>
        <div className="flex items-center gap-5 rounded-xl border border-line bg-surface px-6 py-6">
          <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl border border-line bg-panel">
            {LOGO_IA[clave] ? <Logo src={LOGO_IA[clave]} /> : <Check className="h-7 w-7 text-ok" />}
          </span>
          <div className="min-w-0">
            {/* Honestidad: quedó anotada, pero si la prueba falló no se canta
                victoria. El porqué y el cómo arreglarlo van justo abajo. */}
            <p className="flex items-center gap-2 text-cuerpo font-semibold text-ink">
              {test && !test.ok ? null : <Check className="h-4 w-4 text-ok" />}
              {test && !test.ok ? "Quedó guardada, pero no contestó" : "Tu IA ya está conectada"}
            </p>
            <p className="mt-1.5 text-cuerpo leading-relaxed text-ink-2">
              Estás usando {comoSeLlama}. Lo puedes cambiar cuando quieras desde Tu IA, en el menú.
            </p>
          </div>
        </div>
        {test && <ResultadoIA test={test} />}
        <div className="mt-7">
          <PrimaryButton size="lg" onClick={onListo}>
            Continuar
          </PrimaryButton>
        </div>
        <Nota>
          La IA es tuya: la pagas directo al proveedor o la corres gratis aquí. aiuda no cobra por
          el uso ni revende nada.
        </Nota>
      </div>
    );
  }

  // Estado de la tarjeta local, con lo que de verdad se detectó.
  const localEstado: { texto: string; tono: Tono; accion: string; principal: boolean } = descargando
    ? {
        texto: `Descargando ${descargando[0]}`,
        tono: "pendiente",
        accion: `${descargando[1].pct}%`,
        principal: false,
      }
    : sugerido
      ? { texto: "Modelo listo en tu máquina", tono: "ok", accion: "Usar este", principal: true }
      : ollamaInstalado
        ? {
            texto: "Ollama listo, sin modelos",
            tono: "pendiente",
            accion: "Descargar un modelo",
            principal: true,
          }
        : { texto: "Sin instalar", tono: "apagado", accion: "Cómo instalarlo", principal: false };

  // El camino corto: si el programa ya está en esta computadora, con su sesión
  // iniciada, conectar es UN clic. Nada que pegar, nada que abrir.
  const tieneClaudeCode = !!maquina?.clis.claude.instalado;
  const tieneCodex = !!maquina?.clis.codex.instalado;
  const unClic = tieneClaudeCode || tieneCodex;

  // Un solo botón de acento en la pantalla: el camino de un clic manda; si no
  // hay ninguno, el de siempre (un modelo en esta computadora).
  const tarjetas: { k: "local" | "claude" | "codex" | "red"; nodo: React.ReactNode }[] = [
    {
      k: "local",
      nodo: (
        <Tarjeta
          key="local"
          logo={<Logo src={LOGO_IA.local} />}
          nombre={NOMBRE_IA.local}
          resumen="Gratis y sin internet. Ningún dato sale de aquí."
          estado={trabajando === "local" && !descargando ? "Conectando…" : localEstado.texto}
          tono={localEstado.tono}
          chip={equipo ? `${equipo.chip}, ${equipo.ram_gb} GB` : undefined}
          chipPunto={false}
          accion={trabajando === "local" && !descargando ? "Conectando…" : localEstado.accion}
          principal={localEstado.principal && !unClic}
          activa={abierta === "local"}
          disabled={trabajando !== "" || !!descargando}
          onClick={() => {
            setTest(null);
            if (sugerido) {
              usarModelo(sugerido);
              return;
            }
            setAbierta(abierta === "local" ? null : "local");
          }}
        />
      ),
    },
    {
      k: "claude",
      nodo: (
        <Tarjeta
          key="claude"
          logo={<Logo src={LOGO_IA.claude} className="h-7 w-7" />}
          nombre={NOMBRE_IA.claude}
          resumen={
            tieneClaudeCode
              ? "De Anthropic. Trabaja con tu propia cuenta."
              : "De Anthropic. Pega tu llave y listo."
          }
          estado={
            trabajando === "claude_cli"
              ? "Conectando…"
              : tieneClaudeCode
                ? "Listo para usar"
                : "Sin conectar"
          }
          tono={tieneClaudeCode ? "ok" : "apagado"}
          chip={tieneClaudeCode ? "Ya tienes Claude Code en esta computadora" : undefined}
          accion={
            trabajando === "claude_cli"
              ? "Conectando…"
              : tieneClaudeCode
                ? "Usar Claude Code"
                : "Conectar Claude"
          }
          principal={tieneClaudeCode}
          activa={abierta === "claude"}
          disabled={trabajando !== ""}
          onClick={() => {
            setTest(null);
            if (tieneClaudeCode) {
              setAbierta(null);
              conectar("claude_cli", "", "cli");
              return;
            }
            setAbierta(abierta === "claude" ? null : "claude");
          }}
        />
      ),
    },
    {
      k: "codex",
      nodo: (
        <Tarjeta
          key="codex"
          logo={<Logo src={LOGO_IA.codex} className="h-7 w-7" />}
          nombre={NOMBRE_IA.codex}
          resumen={
            tieneCodex
              ? "De OpenAI. Trabaja con tu propia cuenta."
              : "De OpenAI. Entra con la cuenta que ya usas."
          }
          estado={
            trabajando === "codex_cli"
              ? "Conectando…"
              : tieneCodex
                ? "Listo para usar"
                : "Sin conectar"
          }
          tono={tieneCodex ? "ok" : "apagado"}
          chip={tieneCodex ? "Ya tienes Codex en esta computadora" : undefined}
          accion={
            trabajando === "codex_cli"
              ? "Conectando…"
              : tieneCodex
                ? "Usar Codex"
                : "Conectar OpenAI"
          }
          principal={tieneCodex && !tieneClaudeCode}
          activa={abierta === "codex"}
          disabled={trabajando !== ""}
          onClick={() => {
            setTest(null);
            if (tieneCodex) {
              setAbierta(null);
              conectar("codex_cli", "", "cli");
              return;
            }
            setAbierta(abierta === "codex" ? null : "codex");
          }}
        />
      ),
    },
    {
      k: "red",
      /* En una PyME suele haber UNA computadora buena. Si alguien ya la está
         compartiendo, conectarse ahí es gratis y no requiere bajar nada. */
      nodo: (
        <Tarjeta
          key="red"
          logo={<IconoRed />}
          nombre="En la red de tu oficina"
          resumen="Si otra computadora ya tiene una IA, la puedes usar desde aquí."
          estado={
            enRed === null
              ? "Sin revisar"
              : enRed.length > 0
                ? `${enRed.length} ${enRed.length === 1 ? "encontrada" : "encontradas"}`
                : "No encontramos ninguna"
          }
          tono={enRed && enRed.length > 0 ? "ok" : "apagado"}
          accion={buscandoRed ? "Buscando…" : enRed === null ? "Buscar" : "Buscar otra vez"}
          activa={abierta === "red"}
          disabled={trabajando !== "" || buscandoRed}
          onClick={buscarEnLaRed}
        />
      ),
    },
  ];

  // Lo que ya está en esta computadora va primero: es el camino de un clic.
  const peso = (k: string) =>
    (k === "claude" && tieneClaudeCode) || (k === "codex" && tieneCodex) ? 0 : k === "local" ? 1 : 2;
  tarjetas.sort((a, b) => peso(a.k) - peso(b.k));

  return (
    <div>
      <Titulo
        sub={
          unClic
            ? "Es el cerebro que redacta, lee y propone. Tú siempre decides qué sale. Ya tienes una en esta computadora: un clic y queda."
            : "Es el cerebro que redacta, lee y propone. Tú siempre decides qué sale. Elige de dónde la tomas."
        }
      >
        Tu IA
      </Titulo>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{tarjetas.map((t) => t.nodo)}</div>

      {abierta === "red" && enRed !== null && (
        <div className="mt-4 rounded-xl border border-line bg-panel/40 p-4">
          {enRed.length === 0 ? (
            <p className="text-cuerpo text-ink-2">
              No vimos ninguna IA compartida en tu red. Si alguien la tiene, pídele que la
              deje visible para los demás equipos y vuelve a buscar.
            </p>
          ) : (
            <>
              <p className="mb-2.5 text-cuerpo font-semibold text-ink">Encontradas en tu red</p>
              <ul className="space-y-2">
                {enRed.map((s) => (
                  <li
                    key={s.base_url}
                    className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-surface px-3.5 py-2.5"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-cuerpo font-medium text-ink">{s.equipo}</p>
                      <p className="truncate text-apoyo text-ink-3">
                        {s.programa}
                        {s.modelos.length > 0 ? ` · ${s.modelos.slice(0, 2).join(", ")}` : ""}
                        {s.protegido ? " · pide contraseña" : ""}
                      </p>
                    </div>
                    {s.protegido ? (
                      <span className="text-apoyo text-ink-3">
                        Conéctala desde Proveedor de IA con su clave
                      </span>
                    ) : (
                      <SecondaryButton
                        onClick={() =>
                          conectar(
                            "local",
                            JSON.stringify({
                              base_url: s.base_url,
                              model: s.modelos[0] ?? "",
                            }),
                          )
                        }
                        disabled={trabajando !== "" || s.modelos.length === 0}
                      >
                        Usar esta
                      </SecondaryButton>
                    )}
                  </li>
                ))}
              </ul>
              {avisoRed && (
                <p className="mt-3 border-t border-line/60 pt-3 text-apoyo leading-relaxed text-ink-3">
                  {avisoRed}
                </p>
              )}
            </>
          )}
        </div>
      )}

      {abierta === null && (
        <div className="mt-4 space-y-1.5">
          {tardando && (
            <p className="text-cuerpo leading-relaxed text-ink-2">
              La primera vez tarda un poco: tu programa está despertando. No cierres esta ventana.
            </p>
          )}
          {sugerido && catalogo.length > 0 && (
            <button
              onClick={() => setAbierta("local")}
              className="block text-cuerpo text-ink-3 transition-colors hover:text-ink"
            >
              Ver otros modelos para tu equipo
            </button>
          )}
          {/* El camino de un clic manda; quien prefiera otra cosa la tiene aquí,
              en una línea, sin robarle la atención al botón de arriba. */}
          {unClic && (
            <p className="text-cuerpo leading-relaxed text-ink-3">
              Otra forma de conectar:{" "}
              <button
                onClick={() => {
                  setTest(null);
                  setAbierta("claude");
                }}
                className="text-ink-2 underline-offset-2 transition-colors hover:text-ink hover:underline"
              >
                pegar mi llave de Claude
              </button>{" "}
              o{" "}
              <button
                onClick={() => {
                  setTest(null);
                  setAbierta("codex");
                }}
                className="text-ink-2 underline-offset-2 transition-colors hover:text-ink hover:underline"
              >
                pegar mi llave de OpenAI
              </button>
              .
            </p>
          )}
        </div>
      )}

      {(abierta === "claude" || abierta === "codex") && (
        <PanelProveedor
          key={abierta}
          proveedor={abierta}
          llave={llave}
          setLlave={setLlave}
          trabajando={trabajando !== ""}
          onConectarLlave={() => conectar(abierta, llave.trim())}
          test={test}
        />
      )}

      {abierta === "local" && (
        <Panel>
          {ollamaInstalado ? (
            catalogo.length > 0 ? (
              <div>
                <p className="text-seccion font-semibold text-ink">
                  Recomendados para tu equipo
                  {equipo ? ` (${equipo.chip}, ${equipo.ram_gb} GB)` : ""}
                </p>
                <p className="mt-1 text-cuerpo leading-relaxed text-ink-3">
                  Se descargan una vez y se quedan en tu computadora. Al terminar, aiuda lo conecta
                  solo.
                </p>
                <ul className="mt-3">
                  {catalogo.map((r) => (
                    <FilaModelo
                      key={r.nombre}
                      modelo={r}
                      descarga={descargas[r.nombre]}
                      ocupado={trabajando !== "" || !!descargando}
                      onDescargar={() => descargar(r.nombre)}
                      onUsar={() => usarModelo(r.nombre)}
                    />
                  ))}
                </ul>
                {test && <ResultadoIA test={test} />}
              </div>
            ) : (
              <div>
                <p className="text-seccion font-semibold text-ink">
                  Ollama está aquí, pero sin ningún modelo
                </p>
                <p className="mt-1 text-cuerpo leading-relaxed text-ink-3">
                  Abre la app Terminal y pega esta línea. Baja el modelo, tarda unos minutos.
                </p>
                <Comando texto="ollama pull llama3.1" />
                <div className="mt-4">
                  <SecondaryButton onClick={buscarDeNuevo} disabled={buscando}>
                    {buscando ? "Buscando…" : "Ya lo bajé, buscar de nuevo"}
                  </SecondaryButton>
                </div>
              </div>
            )
          ) : (
            <div>
              <p className="text-seccion font-semibold text-ink">
                Instalar un modelo en tu computadora
              </p>
              <p className="mt-1 text-cuerpo leading-relaxed text-ink-3">
                No pagas nada y ningún dato sale de aquí. Toma unos minutos la primera vez.
              </p>
              <ol className="mt-3.5 space-y-2.5 text-cuerpo leading-relaxed text-ink-2">
                <li className="flex gap-2.5">
                  <span className="tnum text-ink-3">1.</span>
                  <span>
                    Descarga Ollama de{" "}
                    <a
                      href="https://ollama.com"
                      target="_blank"
                      rel="noreferrer"
                      className="font-medium text-accent-ink underline-offset-2 hover:underline"
                    >
                      ollama.com
                    </a>{" "}
                    e instálalo como cualquier programa.
                  </span>
                </li>
                <li className="flex gap-2.5">
                  <span className="tnum text-ink-3">2.</span>
                  <span>Ábrelo una vez y déjalo corriendo.</span>
                </li>
                <li className="flex gap-2.5">
                  <span className="tnum text-ink-3">3.</span>
                  <span className="min-w-0 flex-1">
                    Vuelve aquí y aiuda te propone los modelos que le quedan a tu equipo. Si
                    prefieres hacerlo tú, en la app Terminal:
                    <Comando texto="ollama pull llama3.1" />
                  </span>
                </li>
              </ol>
              <div className="mt-4">
                <SecondaryButton onClick={buscarDeNuevo} disabled={buscando}>
                  {buscando ? "Buscando…" : "Ya lo instalé, buscar de nuevo"}
                </SecondaryButton>
              </div>
            </div>
          )}
        </Panel>
      )}

      {abierta === null && test && <ResultadoIA test={test} />}

      {ia.env_key && (
        <p className="mt-4 text-apoyo leading-relaxed text-ink-3">
          Esta computadora ya trae una llave configurada por fuera de la consola. Puedes seguir sin
          pegar nada; si conectas una aquí, esa manda.
        </p>
      )}

      {unClic && <AvisoAqui claude={tieneClaudeCode} codex={tieneCodex} />}

      <Nota>
        La IA es tuya: la pagas directo al proveedor o la corres gratis en tu computadora. aiuda no
        cobra por el uso ni revende nada. Puedes seguir sin conectarla y hacerlo después, pero tus
        ayudantes no van a poder redactar.
      </Nota>
    </div>
  );
}

/** Nota tranquila del camino de un clic: aiuda usa el programa que el dueño ya
 *  tiene aquí, con su propia cuenta. Vive al pie del paso, nunca encima del botón. */
function AvisoAqui({ claude, codex }: { claude: boolean; codex: boolean }) {
  const cuales = claude && codex ? "Claude Code o Codex" : claude ? "Claude Code" : "Codex";
  return (
    <p className="mt-5 max-w-[80ch] text-apoyo leading-relaxed text-ink-3">
      Al usar {cuales}, aiuda ocupa la cuenta con la que ya entraste en esta computadora, como tus
      demás programas. No es una vía oficial según los términos de{" "}
      {claude && (
        <a
          href={TERMINOS_CLAUDE}
          target="_blank"
          rel="noreferrer"
          className="font-medium text-accent-ink underline-offset-2 hover:underline"
        >
          Anthropic
        </a>
      )}
      {claude && codex && " ni de "}
      {codex && (
        <a
          href={TERMINOS_OPENAI}
          target="_blank"
          rel="noreferrer"
          className="font-medium text-accent-ink underline-offset-2 hover:underline"
        >
          OpenAI
        </a>
      )}
      ; si prefieres cero letras chicas, pega tu llave o usa un modelo de esta computadora.
    </p>
  );
}

/** Una línea para la app Terminal, con su botón de copiar. Se usa para bajar un
 *  modelo local. */
function Comando({ texto }: { texto: string }) {
  const [copiado, setCopiado] = useState(false);
  function copiar() {
    navigator.clipboard?.writeText(texto).then(
      () => {
        setCopiado(true);
        setTimeout(() => setCopiado(false), 2000);
      },
      () => toast("No se pudo copiar. Escribe la línea tal cual.", "error"),
    );
  }
  return (
    <span className="mt-2 flex items-center gap-2 rounded-md border border-line bg-surface px-3 py-2">
      <code className="min-w-0 flex-1 truncate font-mono text-cuerpo text-ink">{texto}</code>
      <button
        onClick={copiar}
        className="shrink-0 text-apoyo font-medium text-accent-ink hover:underline"
      >
        {copiado ? "Copiado" : "Copiar"}
      </button>
    </span>
  );
}

/** Un modelo recomendado: nombre, tamaño, si le queda al equipo y su acción. */
function FilaModelo({
  modelo,
  descarga,
  ocupado,
  onDescargar,
  onUsar,
}: {
  modelo: ModeloRecomendado;
  descarga?: Descarga;
  ocupado: boolean;
  onDescargar: () => void;
  onUsar: () => void;
}) {
  return (
    <li className="flex items-center gap-4 border-t border-line py-3 first:border-t-0">
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="text-cuerpo font-medium text-ink">{modelo.nombre}</span>
          {/* Lo que ya está bajado no necesita veredicto de si "cabe": ya cupo. */}
          {!modelo.instalado && <EtiquetaCabe cabe={modelo.cabe} />}
          {modelo.recomendado && !modelo.instalado && !descarga && (
            <span className="rounded bg-accent-soft px-1.5 py-px text-sello font-medium leading-[1.5] text-accent-ink">
              Recomendado
            </span>
          )}
        </span>
        <span className="mt-0.5 block text-apoyo leading-relaxed text-ink-3">
          <span className="tnum">{modelo.tam_gb} GB</span>
          {modelo.para ? ` · ${modelo.para}` : ""}
        </span>
      </span>

      {descarga?.estado === "descargando" ? (
        <span className="w-36 shrink-0" title={descarga.detalle || undefined}>
          <span className="block h-1 w-full overflow-hidden rounded-full bg-line">
            <span
              className="block h-full rounded-full bg-accent transition-[width] duration-300"
              style={{ width: `${descarga.pct}%` }}
            />
          </span>
          <span className="tnum mt-1.5 block text-apoyo text-ink-3">
            Descargando {descarga.pct}%
          </span>
        </span>
      ) : descarga?.estado === "listo" ? (
        <span className="flex shrink-0 items-center gap-1.5 text-apoyo text-ok">
          <Check className="h-3.5 w-3.5 text-ok" />
          Listo
        </span>
      ) : descarga?.estado === "error" ? (
        <span className="flex shrink-0 items-center gap-2">
          <span className="max-w-[13rem] truncate text-apoyo text-danger" title={descarga.error}>
            {descarga.error}
          </span>
          <SecondaryButton onClick={onDescargar}>Reintentar</SecondaryButton>
        </span>
      ) : modelo.instalado ? (
        <SecondaryButton className="shrink-0" onClick={onUsar} disabled={ocupado}>
          Usar este
        </SecondaryButton>
      ) : /* Un solo botón de acento en la lista: el que aiuda recomienda. */
      modelo.recomendado && modelo.cabe !== "no" ? (
        <PrimaryButton className="shrink-0" onClick={onDescargar} disabled={ocupado}>
          Descargar
        </PrimaryButton>
      ) : (
        <SecondaryButton
          className="shrink-0"
          onClick={onDescargar}
          disabled={ocupado || modelo.cabe === "no"}
          title={modelo.cabe === "no" ? "No le queda a la memoria de este equipo" : undefined}
        >
          Descargar
        </SecondaryButton>
      )}
    </li>
  );
}

/** Nota tranquila de la vía "mi cuenta": aiuda corre en TU computadora con TU
 *  cuenta; solo se aclara que no es una vía oficial del proveedor. */
/** El detalle de conectar Claude u OpenAI cuando el programa NO está en esta
 *  computadora (si estuviera, la tarjeta lo conecta de un clic y este panel ni se
 *  abre). Una sola acción visible: pegar tu llave.
 *
 *  Antes había una segunda vía, "entrar con mi cuenta", que mandaba el token de tu
 *  suscripción haciéndose pasar por el programa oficial del proveedor. Se retiró. Si
 *  ya pagas una suscripción, el camino es instalar su programa: la tarjeta de arriba
 *  lo detecta y lo conecta de un clic, con tu propia sesión. */
function PanelProveedor({
  proveedor,
  llave,
  setLlave,
  trabajando,
  onConectarLlave,
  test,
}: {
  proveedor: "claude" | "codex";
  llave: string;
  setLlave: (v: string) => void;
  trabajando: boolean;
  onConectarLlave: () => void;
  test: ProviderTest | null;
}) {
  const esClaude = proveedor === "claude";
  const marca = esClaude ? "Claude" : "OpenAI";
  return (
    <div className="space-y-3">
      <label className="block">
        <span className="text-rotulo uppercase tracking-[0.06em] text-ink-3">
          Tu llave de {marca}
        </span>
        <input
          className="mt-1 w-full rounded-md border border-line bg-surface px-2.5 py-2 text-cuerpo text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none"
          type="password"
          placeholder={esClaude ? "sk-ant-…" : "sk-…"}
          value={llave}
          onChange={(e) => setLlave(e.target.value)}
        />
      </label>
      <p className="text-apoyo leading-relaxed text-ink-3">
        La sacas en {esClaude ? "console.anthropic.com" : "platform.openai.com"}. Se guarda
        cifrada en esta computadora y te la cobran a ti directo: aiuda no cobra por el uso.
      </p>
      <button
        onClick={onConectarLlave}
        disabled={trabajando || !llave.trim()}
        className="rounded-md bg-accent px-3.5 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong disabled:opacity-50"
      >
        {trabajando ? "Conectando…" : "Conectar"}
      </button>
      {test && !test.ok && (
        <p className="rounded-md border border-danger/40 bg-danger-soft px-3 py-2 text-cuerpo text-danger">
          {test.error}
        </p>
      )}
    </div>
  );
}

function PasoDatos({
  estado,
  onListo,
  onSalir,
}: {
  estado: SetupEstado;
  onListo: () => void;
  onSalir: (href: string) => void;
}) {
  const { clientes, facturas, fuentes } = estado.datos;

  if (estado.datos.listo) {
    const partes = [
      facturas > 0 ? `${facturas} ${facturas === 1 ? "factura" : "facturas"}` : "",
      clientes > 0 ? `${clientes} ${clientes === 1 ? "cliente" : "clientes"}` : "",
    ].filter(Boolean);
    return (
      <div>
        <Titulo sub="Es de donde tu ayudante saca el trabajo: a quién le cobras, qué vendiste, quién te debe.">
          Tus datos
        </Titulo>
        <div className="flex items-center gap-5 rounded-xl border border-line bg-surface px-6 py-6">
          <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl border border-line bg-panel">
            {fuentes.includes("odoo") ? (
              <Logo src="/brand/int/odoo.svg" />
            ) : (
              <IconoHoja className="h-8 w-8" />
            )}
          </span>
          <div className="min-w-0">
            <p className="flex items-center gap-2 text-cuerpo font-semibold text-ink">
              <Check className="h-4 w-4 text-ok" />
              {partes.length > 0 ? `Ya tenemos ${partes.join(" y ")}` : "Ya tienes una fuente conectada"}
            </p>
            <p className="mt-1.5 text-cuerpo leading-relaxed text-ink-2">
              {fuentes.length > 0
                ? `Conectado a ${fuentes.join(", ")}. Puedes agregar más fuentes cuando quieras.`
                : "Puedes seguir cargando más datos cuando quieras, desde Importar."}
            </p>
          </div>
        </div>
        <div className="mt-7">
          <PrimaryButton size="lg" onClick={onListo}>
            Continuar
          </PrimaryButton>
        </div>
      </div>
    );
  }

  const odooConectado = fuentes.includes("odoo");
  const otras = fuentes.filter((f) => f !== "odoo" && f !== "excel").length;

  return (
    <div>
      <Titulo sub="Es de donde tu ayudante saca el trabajo: a quién le cobras, qué vendiste, quién te debe. Elige por dónde empezar.">
        Tus datos
      </Titulo>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Tarjeta
          logo={<Logo src="/brand/int/odoo.svg" />}
          nombre="Odoo"
          resumen="Si llevas tu negocio ahí, aiuda lee tus clientes y tus facturas."
          estado={odooConectado ? "Conectado" : "Sin conectar"}
          tono={odooConectado ? "ok" : "apagado"}
          accion={odooConectado ? "Ver la conexión" : "Conectar Odoo"}
          onClick={() => onSalir("/integraciones/detalle?key=odoo")}
        />
        {/* El único con acento: subir una hoja funciona para cualquier negocio,
            tenga o no un sistema del que leer. */}
        <Tarjeta
          logo={<IconoHoja />}
          nombre="Subir un Excel"
          resumen="Tu hoja tal como la llevas. La IA reconoce las columnas y la acomoda."
          estado={facturas > 0 || clientes > 0 ? "Ya cargaste datos" : "Nada cargado todavía"}
          tono={facturas > 0 || clientes > 0 ? "ok" : "apagado"}
          accion="Subir mi archivo"
          principal
          onClick={() => onSalir("/importar")}
        />
        <Tarjeta
          logo={
            <span className="flex items-center -space-x-1.5">
              {["whatsapp.png", "shopify.svg", "stripe.svg"].map((f) => (
                <span
                  key={f}
                  className="flex h-6 w-6 items-center justify-center rounded-full border border-line bg-surface"
                >
                  <Logo src={`/brand/int/${f}`} className="h-3.5 w-3.5" />
                </span>
              ))}
            </span>
          }
          nombre="Otra fuente"
          resumen="WhatsApp, Shopify, Stripe, WooCommerce o tu propia API."
          estado={otras > 0 ? `${otras} ${otras === 1 ? "conectada" : "conectadas"}` : "Sin conectar"}
          tono={otras > 0 ? "ok" : "apagado"}
          accion="Ver todas"
          onClick={() => onSalir("/integraciones")}
        />
      </div>

      <Nota>
        Al conectar o subir tus datos vas a salir un momento de este asistente. Abajo te queda un
        botón para volver justo aquí. También puedes seguir sin datos y cargarlos después.
      </Nota>
    </div>
  );
}

// --- Paso 4: tu primer ayudante ---------------------------------------------

const SUGERENCIAS = ["tavo", "lucía", "abi"];

function PasoAyudante({
  onListo,
  refrescar,
}: {
  onListo: () => void;
  refrescar: () => Promise<SetupEstado | null>;
}) {
  const { catalog } = useCatalog();
  const [nombre, setNombre] = useState("");
  const [oficio, setOficio] = useState("");
  const [creando, setCreando] = useState(false);

  const perfiles = (catalog?.perfiles ?? []).map((p) => ({
    ...p,
    total: (catalog?.aiuditas ?? []).filter((a) => a.perfil === p.slug).length,
  }));

  async function crear() {
    if (!catalog || !nombre.trim() || !oficio) return;
    setCreando(true);
    // Equipa las aiuditas de ese oficio que YA trabajan (las "listas"). Si ninguna
    // lo está todavía, se equipan todas las del oficio para que no nazca vacío.
    const delOficio = catalog.aiuditas.filter((a) => a.perfil === oficio);
    const listas = delOficio.filter((a) => a.live);
    const ids = (listas.length > 0 ? listas : delOficio).map((a) => a.id);
    try {
      await createAyudante(nombre.trim(), appearanceForSlug(oficio), ids);
      await refrescar();
      window.dispatchEvent(new CustomEvent("agents-changed"));
      onListo();
    } catch (e) {
      toast(`No se pudo crear: ${(e as Error).message}`, "error");
    } finally {
      setCreando(false);
    }
  }

  return (
    <div>
      <Titulo sub="Es quien va a hacer el trabajo. Le pones nombre y le dices de qué se encarga.">
        Tu primer ayudante
      </Titulo>

      <div className="flex items-center gap-5 rounded-xl border border-line bg-surface px-5 py-4">
        <Avatar
          name={nombre || "Tu ayudante"}
          size={56}
          {...appearanceForSlug(oficio || "cobranza")}
        />
        <div className="min-w-0 flex-1">
          <label htmlFor="setup-ayudante" className="block text-cuerpo font-medium text-ink">
            ¿Cómo le quieres decir?
          </label>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <input
              id="setup-ayudante"
              className={`${inputLgCls} max-w-[16rem] flex-1`}
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
              placeholder="tavo"
              autoComplete="off"
            />
            <span className="flex flex-wrap items-center gap-1.5">
              <span className="text-apoyo text-ink-3">Ideas:</span>
              {SUGERENCIAS.map((s) => (
                <button
                  key={s}
                  onClick={() => setNombre(s)}
                  className="rounded-md border border-line px-2 py-0.5 text-sello text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
                >
                  {s}
                </button>
              ))}
            </span>
          </div>
        </div>
      </div>

      <div className="mt-6">
        <p className="mb-2.5 text-cuerpo font-medium text-ink">¿De qué se va a encargar?</p>
        {perfiles.length === 0 ? (
          <div className="skeleton h-[140px] w-full rounded-xl" />
        ) : (
          <div className="grid gap-2.5 sm:grid-cols-2">
            {perfiles.map((p) => {
              const activo = oficio === p.slug;
              return (
                <button
                  key={p.slug}
                  onClick={() => setOficio(p.slug)}
                  aria-pressed={activo}
                  className={`flex items-center gap-3 rounded-xl border bg-surface px-3.5 py-2 text-left transition-colors ${
                    activo ? "border-accent bg-accent-soft/50" : "border-line hover:border-line-strong"
                  }`}
                >
                  <Avatar name={p.name} size={32} {...appearanceForSlug(p.slug)} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-cuerpo font-medium text-ink">{p.name}</span>
                    <span className="mt-0.5 block truncate text-apoyo text-ink-3">
                      {p.desc || `${p.total} ${p.total === 1 ? "aiudita" : "aiuditas"}`}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="mt-6">
        <PrimaryButton size="lg" onClick={crear} disabled={!nombre.trim() || !oficio || creando}>
          {creando ? "Creando…" : "Crear ayudante"}
        </PrimaryButton>
      </div>

      <Nota>
        Las aiuditas son las tareas que sabe hacer. Puedes quitarle o ponerle más después, y crear
        más ayudantes cuando quieras.
      </Nota>
    </div>
  );
}

// --- Cierre -----------------------------------------------------------------

function Resumen({ label, valor, ok }: { label: string; valor: string; ok: boolean }) {
  return (
    <li className="flex items-start gap-3.5 border-t border-line py-3.5 first:border-t-0">
      {ok ? (
        <Check className="mt-0.5 h-4 w-4 text-ok" />
      ) : (
        <svg viewBox="0 0 16 16" className="mt-0.5 h-4 w-4 shrink-0 text-ink-3" fill="none">
          <circle
            cx="8"
            cy="8"
            r="6.5"
            stroke="currentColor"
            strokeWidth="1.3"
            strokeDasharray="2.2 2.4"
          />
        </svg>
      )}
      <span className="min-w-0 flex-1">
        <span className="block text-cuerpo text-ink-3">{label}</span>
        <span className="mt-0.5 block text-cuerpo text-ink">{valor}</span>
      </span>
    </li>
  );
}

function PasoCierre({ estado, onEntrar }: { estado: SetupEstado; onEntrar: () => void }) {
  const [entrando, setEntrando] = useState(false);
  const { clientes, facturas } = estado.datos;
  const listo = estado.ia.conectada && estado.ayudantes.total > 0;

  const proveedor =
    estado.ia.proveedor === "local"
      ? "Un modelo en esta computadora"
      : estado.ia.proveedor === "claude"
        ? "Claude"
        : estado.ia.proveedor === "codex"
          ? "OpenAI"
          : "Sin conectar. La conectas en Tu IA, en el menú";

  const datos =
    facturas > 0 || clientes > 0
      ? [
          facturas > 0 ? `${facturas} ${facturas === 1 ? "factura" : "facturas"}` : "",
          clientes > 0 ? `${clientes} ${clientes === 1 ? "cliente" : "clientes"}` : "",
        ]
          .filter(Boolean)
          .join(" y ")
      : estado.datos.fuentes.length > 0
        ? `Conectado a ${estado.datos.fuentes.join(", ")}`
        : "Sin datos todavía. Los subes en Importar";

  return (
    <div>
      <Titulo
        sub={
          listo
            ? "Ya puedes trabajar. Nada sale a tus clientes sin que tú lo apruebes."
            : "Puedes empezar así y completar lo que falta cuando quieras. Nada sale a tus clientes sin que tú lo apruebes."
        }
      >
        {listo ? "Listo. Tu ayudante ya está trabajando." : "Listo por ahora."}
      </Titulo>

      <ul className="rounded-xl border border-line bg-surface px-5 py-1.5">
        <Resumen
          label="Tu negocio"
          valor={estado.negocio.nombre || "Sin nombre"}
          ok={estado.negocio.listo || estado.negocio.nombre !== NOMBRE_POR_DEFECTO}
        />
        <Resumen label="Tu IA" valor={proveedor} ok={estado.ia.conectada} />
        <Resumen label="Tus datos" valor={datos} ok={estado.datos.listo} />
        <Resumen
          label="Tu equipo"
          valor={
            estado.ayudantes.total > 0
              ? `${estado.ayudantes.total} ${estado.ayudantes.total === 1 ? "ayudante" : "ayudantes"}`
              : "Ninguno todavía. Lo creas en Tu equipo"
          }
          ok={estado.ayudantes.total > 0}
        />
      </ul>

      <div className="mt-8">
        <PrimaryButton
          size="lg"
          onClick={() => {
            setEntrando(true);
            onEntrar();
          }}
          disabled={entrando}
        >
          {entrando ? "Entrando…" : "Entrar a mi consola"}
        </PrimaryButton>
      </div>

      <Nota>Este asistente no vuelve a salir. Todo lo de aquí lo puedes cambiar en el menú.</Nota>
    </div>
  );
}
