"use client";

/**
 * Conectar la IA: una vía recomendada para ESTA Mac arriba, y las demás en
 * "Otras formas de conectar", en la misma pantalla. Lo usan Ajustes > Tu IA y el
 * asistente de primer arranque, para que las dos pantallas ofrezcan lo mismo, con
 * las mismas palabras.
 *
 * Ninguna vía se quita: el programa que el dueño ya tiene (Claude Code, Codex), un
 * modelo en esta computadora, la IA de otra computadora de la oficina, su llave de
 * Claude o de OpenAI, y "Entrar con ChatGPT" con su sello "Sin estrenar".
 *
 * La recomendación sale de lo que el servidor ve en la máquina (GET
 * /v1/setup/maquina): lo que ya está instalado gana; si no hay nada, manda la
 * memoria del equipo.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  type ModeloRecomendado,
  type ProviderMode,
  type ProviderName,
  type ProviderState,
  type ProviderTest,
  type ServidorIAEnRed,
  type SetupEstado,
  type SetupMaquina,
} from "@/lib/api";
import {
  PrimaryButton,
  SecondaryButton,
  SinEstrenar,
  Skeleton,
  inputCls,
  Estado,
  QuietButton,
} from "@/components/ui";
import {
  AdministrarUso,
  AvisoPlanChatGPT,
  EntrarConChatGPT,
  UsandoPlanChatGPT,
} from "@/components/chatgpt";
import { toast } from "@/components/toast";

export type Via = "claude_cli" | "codex_cli" | "local" | "red" | "claude" | "chatgpt" | "codex";

const VIAS: Record<Via, { nombre: string; linea: string; logo: string | null }> = {
  claude_cli: {
    nombre: "Claude Code",
    linea: "El programa de Anthropic que ya tienes aquí. Trabaja con tu propia cuenta.",
    logo: "/brand/anthropic.svg",
  },
  codex_cli: {
    nombre: "Codex",
    linea: "El programa de OpenAI que ya tienes aquí. Trabaja con tu propia cuenta.",
    logo: "/brand/openai.svg",
  },
  local: {
    nombre: "En esta computadora",
    linea: "Gratis y sin internet. Ningún dato de tus clientes sale de aquí.",
    logo: "/brand/ollama.svg",
  },
  red: {
    nombre: "En la red de tu oficina",
    linea: "Si otra computadora ya tiene una IA, la usas desde aquí.",
    logo: null,
  },
  claude: {
    nombre: "Claude con tu llave",
    linea: "De Anthropic. Pegas tu llave y Anthropic te cobra a ti.",
    logo: "/brand/anthropic.svg",
  },
  chatgpt: {
    nombre: "Entrar con ChatGPT",
    linea: "Con el plan de ChatGPT que ya pagas. Sin pegar nada.",
    logo: "/brand/openai.svg",
  },
  codex: {
    nombre: "OpenAI con tu llave",
    linea: "Pegas tu llave y OpenAI te cobra a ti.",
    logo: "/brand/openai.svg",
  },
};

const ORDEN: Via[] = ["claude_cli", "codex_cli", "local", "red", "claude", "chatgpt", "codex"];

const TERMINOS_CLAUDE = "https://www.anthropic.com/legal/consumer-terms";
const TERMINOS_OPENAI = "https://developers.openai.com/codex/auth";
const DIRECCION_LOCAL = "http://localhost:11434/v1";

/** Cómo se le dice al dueño lo que está usando. */
export function nombreDeLaIA(proveedor: string | null | undefined, enRed = false): string {
  switch (proveedor) {
    case "local":
      return enRed ? "la IA de otra computadora de tu oficina" : "un modelo en esta computadora";
    case "claude_cli":
      return "el Claude Code de esta computadora";
    case "codex_cli":
      return "el Codex de esta computadora";
    case "chatgpt":
      return "tu plan de ChatGPT";
    case "claude":
      return "Claude con tu llave";
    case "codex":
      return "OpenAI con tu llave";
    default:
      return "tu IA";
  }
}

function esDeEstaMaquina(url: string | undefined): boolean {
  return !url || /\/\/(localhost|127\.0\.0\.1|\[::1\])[:/]/.test(url);
}

function viaDe(server: ProviderState | null): Via | null {
  if (!server?.connected) return null;
  if (server.name === "local") return esDeEstaMaquina(server.local_config?.base_url) ? "local" : "red";
  return server.name;
}

type Descarga = {
  estado: "descargando" | "listo" | "error";
  pct: number;
  error?: string;
  detalle?: string;
};

function LogoVia({ via, grande = false }: { via: Via; grande?: boolean }) {
  const logo = VIAS[via].logo;
  const caja = grande ? "h-12 w-12 rounded-2xl" : "h-10 w-10 rounded-lg";
  return (
    <span className={`flex shrink-0 items-center justify-center bg-fill ${caja}`}>
      {logo ? (
        <img src={logo} alt="" aria-hidden="true" className={grande ? "h-6 w-6" : "h-5 w-5"} />
      ) : (
        <svg viewBox="0 0 24 24" className={`${grande ? "h-6 w-6" : "h-5 w-5"} text-ink-2`} fill="none" aria-hidden="true">
          <rect x="2.5" y="4" width="8" height="6" rx="1.4" stroke="currentColor" strokeWidth="1.4" />
          <rect x="13.5" y="14" width="8" height="6" rx="1.4" stroke="currentColor" strokeWidth="1.4" />
          <path d="M6.5 10v3.5a1.5 1.5 0 0 0 1.5 1.5h5.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
        </svg>
      )}
    </span>
  );
}

function Resultado({ test }: { test: ProviderTest }) {
  if (test.ok) {
    return (
      <p role="status" className="mark mt-4 !text-cuerpo" style={{ "--mark": "var(--color-ok)" } as React.CSSProperties}>
        Tu IA respondió bien. Ya puede trabajar.
      </p>
    );
  }
  return (
    <div role="status" className="mt-4 rounded-lg bg-panel px-4 py-3">
      <p className="text-cuerpo font-semibold text-ink">No pudo responder</p>
      <p className="mt-1 text-cuerpo leading-relaxed text-ink-2">{test.error}</p>
      {test.code === "limite" && (
        <div className="mt-2.5">
          <AdministrarUso />
        </div>
      )}
    </div>
  );
}

function FilaModelo({
  modelo,
  descarga,
  ocupado,
  principal,
  onDescargar,
  onUsar,
}: {
  modelo: ModeloRecomendado;
  descarga?: Descarga;
  ocupado: boolean;
  principal: boolean;
  onDescargar: () => void;
  onUsar: () => void;
}) {
  const Boton = principal ? PrimaryButton : SecondaryButton;
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line py-3 first:border-t-0">
      <span className="min-w-[14rem] flex-1">
        <span className="block text-cuerpo font-medium text-ink">{modelo.nombre}</span>
        <span className="mt-0.5 block text-apoyo leading-relaxed text-ink-3">
          <span className="tnum">{modelo.tam_gb} GB</span>
          {modelo.instalado
            ? " · ya está en tu computadora"
            : modelo.cabe === "bien"
              ? " · le queda bien a tu equipo"
              : modelo.cabe === "justo"
                ? " · le queda justo a tu equipo"
                : " · no le queda a tu equipo"}
          {modelo.para && !modelo.instalado ? ` · ${modelo.para}` : ""}
        </span>
      </span>

      {descarga?.estado === "descargando" ? (
        <span className="w-36 shrink-0" title={descarga.detalle || undefined}>
          <span className="block h-1 w-full overflow-hidden rounded-full bg-fill-strong">
            <span
              className="block h-full rounded-full bg-accent transition-[width] duration-300"
              style={{ width: `${descarga.pct}%` }}
            />
          </span>
          <span className="tnum mt-1.5 block text-apoyo text-ink-3">Descargando {descarga.pct}%</span>
        </span>
      ) : descarga?.estado === "error" ? (
        <span className="flex min-w-0 shrink-0 flex-wrap items-center gap-2">
          <span className="max-w-[16rem] text-apoyo text-danger">{descarga.error}</span>
          <SecondaryButton size="sm" onClick={onDescargar}>
            Reintentar
          </SecondaryButton>
        </span>
      ) : modelo.instalado ? (
        <Boton className="shrink-0" onClick={onUsar} disabled={ocupado}>
          Usar este
        </Boton>
      ) : (
        <Boton
          className="shrink-0"
          onClick={onDescargar}
          disabled={ocupado || modelo.cabe === "no"}
          title={modelo.cabe === "no" ? "No le queda a la memoria de este equipo" : undefined}
        >
          Descargar y usar
        </Boton>
      )}
    </li>
  );
}

export function ConectarIA({
  enAsistente = false,
  onCambio,
}: {
  /** Dentro del asistente de primer arranque: sin "Desconectar" ni avisos en ventana. */
  enAsistente?: boolean;
  /** Algo cambió (se conectó, se desconectó): quien lo monta refresca lo suyo. */
  onCambio?: () => void;
}) {
  const [server, setServer] = useState<ProviderState | null>(null);
  const [cargando, setCargando] = useState(true);
  const [sinServidor, setSinServidor] = useState<string | null>(null);
  const [maquina, setMaquina] = useState<SetupMaquina | null>(null);
  const [setup, setSetup] = useState<SetupEstado["ia"] | null>(null);

  const [abierta, setAbierta] = useState<Via | null>(null);
  // Una llave por vía: la de Claude no aparece escrita en el campo de OpenAI.
  const [llaves, setLlaves] = useState<Record<string, string>>({});
  const [trabajando, setTrabajando] = useState<Via | "">("");
  // La PRIMERA vez que se despierta un programa puede tardar (26 s medidos en frío;
  // después, 3 s). Sin decirlo, "Conectando…" se lee como colgado.
  const [tardando, setTardando] = useState(false);
  const [test, setTest] = useState<ProviderTest | null>(null);
  const [probando, setProbando] = useState(false);
  const [descargas, setDescargas] = useState<Record<string, Descarga>>({});
  const [enRed, setEnRed] = useState<ServidorIAEnRed[] | null>(null);
  const [avisoRed, setAvisoRed] = useState("");
  const [buscandoRed, setBuscandoRed] = useState(false);
  const [buscando, setBuscando] = useState(false);
  const [aMano, setAMano] = useState(false);
  const [verModelos, setVerModelos] = useState(false);
  // Con algo ya conectado: abrir su propio formulario para cambiar la llave o el
  // modelo sin tener que desconectar primero.
  const [cambiando, setCambiando] = useState(false);
  const [direccion, setDireccion] = useState(DIRECCION_LOCAL);
  const [modeloAMano, setModeloAMano] = useState("");
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const alCambiar = useRef(onCambio);
  useEffect(() => {
    alCambiar.current = onCambio;
  }, [onCambio]);

  const mirar = useCallback(async () => {
    const [p, m, s] = await Promise.all([
      api.provider().catch((e: Error) => e),
      api.setupMaquina().catch(() => null),
      api.setupEstado().catch(() => null),
    ]);
    if (p instanceof Error) setSinServidor(p.message);
    else {
      setSinServidor(null);
      setServer(p);
      if (p.local_config) {
        setDireccion(p.local_config.base_url);
        setModeloAMano(p.local_config.model);
      }
    }
    setMaquina(m);
    setSetup(s?.ia ?? null);
    setCargando(false);
    return { m, s };
  }, []);

  useEffect(() => {
    mirar();
  }, [mirar]);

  useEffect(() => {
    const actuales = timers.current;
    return () => {
      for (const t of Object.values(actuales)) clearTimeout(t);
    };
  }, []);

  // --- Lo que se sabe de esta computadora -----------------------------------
  const tieneClaudeCode = !!maquina?.clis.claude.instalado;
  const tieneCodex = !!maquina?.clis.codex.instalado;
  const ollamaInstalado = maquina ? maquina.ollama.instalado : !!setup?.ollama_corriendo;
  const ollamaCorriendo = maquina ? maquina.ollama.corriendo : !!setup?.ollama_corriendo;
  const equipo = maquina?.equipo;
  const recomendados = maquina?.recomendados ?? [];
  const baseLocal = setup?.base_url_local ?? DIRECCION_LOCAL;
  const descargando = Object.entries(descargas).find(([, d]) => d.estado === "descargando");

  // Lo que se puede elegir aquí: primero lo que YA está bajado, luego lo que le
  // queda a este equipo. Sin repetidos y sin lo que no cabe (salvo que no haya más).
  const modelos: ModeloRecomendado[] = (() => {
    const porNombre = new Map<string, ModeloRecomendado>();
    for (const m of maquina?.modelos_instalados ?? []) {
      porNombre.set(m.nombre, {
        nombre: m.nombre,
        tam_gb: m.tam_gb,
        cabe: "bien",
        instalado: true,
        recomendado: false,
        para: "",
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
  const modeloListo = ollamaCorriendo
    ? (setup?.modelo_sugerido ?? modelos.find((m) => m.instalado)?.nombre ?? null)
    : null;
  const leCabeUno = recomendados.some((r) => r.cabe !== "no");

  // --- La recomendación ------------------------------------------------------
  const recomendada: Via = tieneClaudeCode
    ? "claude_cli"
    : tieneCodex
      ? "codex_cli"
      : modeloListo || ollamaInstalado || leCabeUno
        ? "local"
        : "claude";

  const mac = equipo ? `${equipo.chip}, ${equipo.ram_gb} GB de memoria` : "";
  const porque: Record<Via, string> = {
    claude_cli:
      "Ya tienes Claude Code en esta computadora. Si ya entraste ahí con tu cuenta, es un clic y queda, sin pegar nada.",
    codex_cli:
      "Ya tienes Codex en esta computadora. Si ya entraste ahí con tu cuenta, es un clic y queda, sin pegar nada.",
    local: modeloListo
      ? "Ya hay un modelo listo en esta computadora. Es gratis y ningún dato de tus clientes sale de aquí."
      : `Tu Mac${mac ? ` (${mac})` : ""} puede correr la IA aquí mismo. Es gratis y ningún dato de tus clientes sale de aquí.`,
    claude: equipo
      ? `A tu Mac (${mac}) no le alcanza la memoria para correr una IA aquí. Lo más directo es Claude con tu llave.`
      : "Lo más directo es Claude con tu llave.",
    red: "",
    chatgpt: "",
    codex: "",
  };

  const enUso = viaDe(server);
  const principal: Via = enUso ?? recomendada;
  const otras = ORDEN.filter(
    (v) =>
      v !== principal &&
      (v !== "claude_cli" || tieneClaudeCode) &&
      (v !== "codex_cli" || tieneCodex),
  );
  const ocupado = trabajando !== "" || !!descargando;

  // --- Acciones --------------------------------------------------------------
  async function probar() {
    setProbando(true);
    setTest(null);
    setTardando(false);
    const avisoLento = window.setTimeout(() => setTardando(true), 6000);
    try {
      setTest(await api.testProvider());
    } catch (e) {
      setTest({ ok: false, code: "network", error: (e as Error).message });
    } finally {
      window.clearTimeout(avisoLento);
      setTardando(false);
      setProbando(false);
    }
  }

  /** Guarda la conexión y la prueba de inmediato. */
  async function conectar(via: Via, name: ProviderName, secreto: string, modo: ProviderMode = "api_key") {
    setTrabajando(via);
    setTest(null);
    setTardando(false);
    const avisoLento = modo === "cli" ? window.setTimeout(() => setTardando(true), 6000) : undefined;
    try {
      const r = await api.saveProvider(name, modo, secreto);
      // Venías de ChatGPT y OpenAI no confirmó el cierre de esa sesión: se dice.
      if (r.aviso) toast(r.aviso, "error");
      setTest(await api.testProvider());
      setAbierta(null);
      setCambiando(false);
      setLlaves({});
      await mirar();
      alCambiar.current?.();
    } catch (e) {
      setTest({ ok: false, code: "error", error: (e as Error).message });
    } finally {
      if (avisoLento !== undefined) window.clearTimeout(avisoLento);
      setTardando(false);
      setTrabajando("");
    }
  }

  const usarModelo = (modelo: string) =>
    conectar("local", "local", JSON.stringify({ base_url: baseLocal, model: modelo }));

  async function desconectar() {
    try {
      const r = await api.disconnectProvider();
      // ChatGPT: si OpenAI no confirmó la desconexión, se dice (y qué hacer).
      toast(r.aviso ?? "Tu IA quedó desconectada.", r.aviso ? "error" : "info");
      setTest(null);
      await mirar();
      alCambiar.current?.();
    } catch (e) {
      toast(`No se pudo desconectar: ${(e as Error).message}`, "error");
    }
  }

  async function chatgptConectado() {
    setTrabajando("chatgpt");
    try {
      setTest(await api.testProvider());
    } catch (e) {
      setTest({ ok: false, code: "error", error: (e as Error).message });
    }
    setAbierta(null);
    setCambiando(false);
    await mirar();
    alCambiar.current?.();
    setTrabajando("");
  }

  async function buscarEnLaRed() {
    if (buscandoRed) return;
    setBuscandoRed(true);
    try {
      const r = await api.setupBuscarEnRed();
      setEnRed(r.encontrados);
      setAvisoRed(r.aviso || "");
    } catch {
      setEnRed([]);
      setAvisoRed("No pudimos revisar la red desde aquí.");
    } finally {
      setBuscandoRed(false);
    }
  }

  async function buscarDeNuevo() {
    setBuscando(true);
    const { m } = await mirar();
    setBuscando(false);
    if (!m?.ollama.instalado) {
      toast("Todavía no vemos Ollama en esta computadora. Ábrelo una vez y vuelve a buscar.", "info");
    }
  }

  // Descarga de un modelo: se dispara en el servidor y se pregunta cómo va hasta que
  // queda listo. Al quedar listo se conecta solo (para eso se bajó). Si el servidor
  // deja de saber de esa descarga (se reinició a media bajada), se dice en vez de
  // girar para siempre.
  function sondear(modelo: string, perdidas = 0) {
    timers.current[modelo] = setTimeout(async () => {
      try {
        const p = await api.setupProgresoModelo(modelo);
        const pct = Math.max(0, Math.min(100, Math.round(p.porcentaje ?? p.pct ?? 0)));
        if (p.estado === "listo") {
          setDescargas((d) => ({ ...d, [modelo]: { estado: "listo", pct: 100 } }));
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

  // --- El contenido de cada vía ----------------------------------------------
  function panel(via: Via, esPrincipal: boolean) {
    // Un solo botón relleno en la pantalla: el de la vía recomendada, y solo
    // mientras no haya nada conectado (en el asistente, ahí manda "Continuar").
    const relleno = esPrincipal && !enUso;
    const Boton = relleno ? PrimaryButton : SecondaryButton;

    if (via === "claude_cli" || via === "codex_cli") {
      const marca = via === "claude_cli" ? "Claude Code" : "Codex";
      return (
        <div className="space-y-4">
          <Boton onClick={() => conectar(via, via, "", "cli")} disabled={ocupado}>
            {trabajando === via ? "Conectando…" : `Usar ${marca}`}
          </Boton>
          {tardando && trabajando === via && (
            <p className="text-cuerpo leading-relaxed text-ink-2">
              La primera vez tarda un poco: {marca} está despertando. No cierres esta ventana.
            </p>
          )}
          <p className="max-w-[70ch] text-apoyo leading-relaxed text-ink-3">
            aiuda no guarda ninguna llave tuya: lanza {marca} y lee su respuesta, con la cuenta con
            la que ya entraste ahí. No es una vía oficial según los términos de{" "}
            <a
              href={via === "claude_cli" ? TERMINOS_CLAUDE : TERMINOS_OPENAI}
              target="_blank"
              rel="noreferrer"
              className="font-medium text-accent-ink underline-offset-2 hover:underline"
            >
              {via === "claude_cli" ? "Anthropic" : "OpenAI"}
            </a>
            ; si prefieres cero letras chicas, pega tu llave o usa un modelo de esta computadora.
          </p>
        </div>
      );
    }

    if (via === "local") {
      return (
        <div>
          {!ollamaInstalado ? (
            <div>
              <p className="text-cuerpo leading-relaxed text-ink-2">
                Hace falta un programa gratuito que corre la IA en tu Mac. Se llama Ollama y se
                instala como cualquier otro. Toma unos minutos la primera vez.
              </p>
              <ol className="mt-3 space-y-1.5 text-cuerpo leading-relaxed text-ink-2">
                <li>
                  <span className="tnum text-ink-3">1.</span> Descárgalo de{" "}
                  <a
                    href="https://ollama.com/download"
                    target="_blank"
                    rel="noreferrer"
                    className="font-medium text-accent-ink underline-offset-2 hover:underline"
                  >
                    ollama.com
                  </a>{" "}
                  e instálalo.
                </li>
                <li>
                  <span className="tnum text-ink-3">2.</span> Ábrelo una vez y déjalo abierto.
                </li>
                <li>
                  <span className="tnum text-ink-3">3.</span> Vuelve aquí: aiuda te propone el
                  modelo que le queda a tu equipo y lo baja por ti.
                </li>
              </ol>
              <Boton className="mt-4" onClick={buscarDeNuevo} disabled={buscando}>
                {buscando ? "Buscando…" : "Ya lo instalé, buscar de nuevo"}
              </Boton>
            </div>
          ) : modelos.length > 0 ? (
            <div>
              <p className="text-apoyo leading-relaxed text-ink-3">
                Un modelo se descarga una vez y se queda en tu computadora. Al terminar, aiuda lo
                conecta solo.
              </p>
              {/* El primero es el que aiuda propone para este equipo; los demás, a un clic. */}
              <ul className="mt-1">
                {(verModelos ? modelos : modelos.slice(0, 1)).map((m, i) => (
                  <FilaModelo
                    key={m.nombre}
                    modelo={m}
                    descarga={descargas[m.nombre]}
                    ocupado={ocupado}
                    principal={relleno && i === 0}
                    onDescargar={() => descargar(m.nombre)}
                    onUsar={() => usarModelo(m.nombre)}
                  />
                ))}
              </ul>
              {modelos.length > 1 && !verModelos && (
                <button
                  type="button"
                  onClick={() => setVerModelos(true)}
                  className="mt-1 block text-apoyo font-medium text-accent-ink underline-offset-2 hover:underline"
                >
                  Ver otros {modelos.length - 1} modelos para tu equipo
                </button>
              )}
            </div>
          ) : (
            <div>
              <p className="text-cuerpo leading-relaxed text-ink-2">
                El programa ya está aquí, pero sin ningún modelo. aiuda puede bajar uno por ti;
                tarda unos minutos.
              </p>
              {descargas["llama3.1"]?.estado === "descargando" ? (
                <p className="tnum mt-3 text-cuerpo text-ink-2">
                  Descargando {descargas["llama3.1"].pct}%
                </p>
              ) : (
                <Boton className="mt-3" onClick={() => descargar("llama3.1")} disabled={ocupado}>
                  Descargar un modelo
                </Boton>
              )}
              {descargas["llama3.1"]?.estado === "error" && (
                <p className="mt-2 text-cuerpo text-danger">{descargas["llama3.1"].error}</p>
              )}
            </div>
          )}

          {/* Para quien corre su modelo con otro programa o en otra dirección. */}
          <button
            type="button"
            aria-expanded={aMano}
            onClick={() => setAMano((v) => !v)}
            className="mt-3 block text-apoyo font-medium text-accent-ink underline-offset-2 hover:underline"
          >
            {aMano ? "Ocultar la dirección y el modelo" : "Escribir la dirección y el modelo a mano"}
          </button>
          {aMano && (
            <div className="mt-3 max-w-md space-y-4">
              <label className="block">
                <span className="block text-cuerpo font-semibold text-ink">Dirección</span>
                <span className="mt-0.5 block text-apoyo text-ink-3">
                  La que te da el programa que corre el modelo.
                </span>
                <input
                  className={`${inputCls} mt-2`}
                  value={direccion}
                  onChange={(e) => setDireccion(e.target.value)}
                />
              </label>
              <label className="block">
                <span className="block text-cuerpo font-semibold text-ink">Modelo</span>
                <span className="mt-0.5 block text-apoyo text-ink-3">
                  El nombre tal como lo bajaste.
                </span>
                <input
                  className={`${inputCls} mt-2`}
                  placeholder="llama3.1"
                  value={modeloAMano}
                  onChange={(e) => setModeloAMano(e.target.value)}
                />
              </label>
              <SecondaryButton
                onClick={() =>
                  conectar(
                    esDeEstaMaquina(direccion.trim()) ? "local" : "red",
                    "local",
                    JSON.stringify({ base_url: direccion.trim(), model: modeloAMano.trim() }),
                  )
                }
                disabled={ocupado || !direccion.trim()}
              >
                {trabajando === "local" ? "Conectando…" : "Conectar"}
              </SecondaryButton>
            </div>
          )}
        </div>
      );
    }

    if (via === "red") {
      return (
        <div>
          <p className="text-cuerpo leading-relaxed text-ink-2">
            En una oficina suele haber una computadora buena. Si alguien ya comparte su IA en tu
            red, conectarte ahí es gratis y no hay que bajar nada.
          </p>
          <Boton className="mt-3" onClick={buscarEnLaRed} disabled={ocupado || buscandoRed}>
            {buscandoRed ? "Buscando…" : enRed === null ? "Buscar en mi red" : "Buscar otra vez"}
          </Boton>
          {enRed !== null && enRed.length === 0 && (
            <p className="mt-3 text-cuerpo leading-relaxed text-ink-2">
              {avisoRed ||
                "No vimos ninguna IA compartida en tu red. Si alguien la tiene, pídele que la deje visible para los demás equipos y vuelve a buscar."}
            </p>
          )}
          {enRed !== null && enRed.length > 0 && (
            <>
              <ul className="mt-3 divide-y divide-line border-y border-line">
                {enRed.map((s) => (
                  <li key={s.base_url} className="flex flex-wrap items-center gap-3 py-3">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-cuerpo font-medium text-ink">{s.equipo}</p>
                      <p className="truncate text-apoyo text-ink-3">
                        {s.programa}
                        {s.modelos.length > 0 ? ` · ${s.modelos.slice(0, 2).join(", ")}` : ""}
                        {s.protegido ? " · pide contraseña" : ""}
                      </p>
                    </div>
                    {s.protegido ? (
                      <span className="text-apoyo text-ink-3">Pide contraseña: no se puede usar desde aquí</span>
                    ) : (
                      <SecondaryButton
                        size="sm"
                        onClick={() =>
                          conectar(
                            "red",
                            "local",
                            JSON.stringify({ base_url: s.base_url, model: s.modelos[0] ?? "" }),
                          )
                        }
                        disabled={ocupado || s.modelos.length === 0}
                      >
                        Usar esta
                      </SecondaryButton>
                    )}
                  </li>
                ))}
              </ul>
              {avisoRed && (
                <p className="mt-3 max-w-[70ch] text-apoyo leading-relaxed text-ink-3">{avisoRed}</p>
              )}
            </>
          )}
        </div>
      );
    }

    if (via === "chatgpt") {
      return (
        <EntrarConChatGPT
          chatgpt={server?.chatgpt}
          onConectada={chatgptConectado}
          disabled={ocupado}
        />
      );
    }

    // Llave de Claude o de OpenAI.
    const esClaude = via === "claude";
    return (
      <div className="max-w-md">
        <label className="block">
          <span className="block text-cuerpo font-semibold text-ink">
            Tu llave de {esClaude ? "Anthropic" : "OpenAI"}
          </span>
          <span className="mt-0.5 block text-apoyo leading-relaxed text-ink-3">
            La sacas en {esClaude ? "console.anthropic.com" : "platform.openai.com"}. Se guarda
            cifrada en esta computadora y {esClaude ? "Anthropic" : "OpenAI"} te cobra a ti directo.
          </span>
          <input
            className={`${inputCls} mt-2`}
            type="password"
            autoComplete="off"
            placeholder={esClaude ? "sk-ant-…" : "sk-…"}
            value={llaves[via] ?? ""}
            onChange={(e) => setLlaves((l) => ({ ...l, [via]: e.target.value }))}
          />
        </label>
        <Boton
          className="mt-4"
          onClick={() => conectar(via, via, (llaves[via] ?? "").trim())}
          disabled={ocupado || !(llaves[via] ?? "").trim()}
        >
          {trabajando === via ? "Conectando…" : "Conectar"}
        </Boton>
      </div>
    );
  }

  if (cargando) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-28 w-full rounded-2xl" />
        <Skeleton className="h-44 w-full rounded-2xl" />
      </div>
    );
  }

  if (sinServidor && !server) {
    return (
      <div>
        <p className="text-cuerpo text-ink-2">No se pudo leer cómo está tu IA. {sinServidor}</p>
        <SecondaryButton className="mt-3" onClick={() => mirar()}>
          Reintentar
        </SecondaryButton>
      </div>
    );
  }

  return (
    <div>
      {/* Venías de la vía retirada: se dice qué pasó en vez de apagarte la IA en silencio. */}
      {server?.aviso_retirado && (
        <div className="mb-8 rounded-2xl bg-panel px-5 py-4">
          <p className="text-cuerpo font-semibold text-ink">Tu IA quedó desconectada</p>
          <p className="mt-1 text-cuerpo leading-relaxed text-ink-2">{server.aviso_retirado}</p>
        </div>
      )}

      <p className="eyebrow">{enUso ? "en uso" : "recomendada para esta Mac"}</p>
      {/* Sobre el papel, entre dos rayas: antes era una ficha gris con otra lista
          adentro. La raya de abajo es la de "Otras formas de conectar". */}
      <section className="mt-3 border-t border-line pt-5">
        <div className="flex items-start gap-4">
          <LogoVia via={principal} grande />
          <div className="min-w-0 flex-1">
            <h2 className="flex flex-wrap items-center gap-x-3 gap-y-1 text-seccion font-semibold text-ink">
              {VIAS[principal].nombre}
              {enUso && (
                <Estado tono="ok">
                  Conectada
                </Estado>
              )}
              {principal === "chatgpt" && <SinEstrenar />}
            </h2>
            <p className="mt-1 max-w-[62ch] text-cuerpo leading-relaxed text-ink-2">
              {enUso
                ? `Tus ayudantes están usando ${nombreDeLaIA(server?.name, enUso === "red")}${
                    server?.name === "local" && server.local_config?.model
                      ? ` (${server.local_config.model})`
                      : ""
                  }.`
                : porque[principal] || VIAS[principal].linea}
            </p>
          </div>
        </div>

        <div className="mt-5">
          {enUso ? (
            <div>
              {enUso === "chatgpt" && (
                <div className="mb-4 space-y-3">
                  <UsandoPlanChatGPT email={server?.chatgpt?.email} />
                  <p className="max-w-[70ch] text-apoyo leading-relaxed text-ink-3">
                    Lo que hagan tus ayudantes cuenta en tu plan de ChatGPT, junto con lo que tú
                    uses ahí. aiuda guarda cifrado en esta computadora el permiso que le diste;
                    nunca ve tu contraseña.
                  </p>
                </div>
              )}
              <div className="barra">
                <SecondaryButton onClick={probar} disabled={probando}>
                  {probando ? "Probando…" : "Probar que responde"}
                </SecondaryButton>
                <QuietButton
                  aria-expanded={cambiando}
                  onClick={() => {
                    setTest(null);
                    setCambiando((v) => !v);
                  }}
                >
                  {cambiando
                    ? "Cancelar"
                    : enUso === "claude" || enUso === "codex"
                      ? "Cambiar la llave"
                      : enUso === "local" || enUso === "red"
                        ? "Cambiar de modelo"
                        : enUso === "chatgpt"
                          ? "Entrar con otra cuenta"
                          : "Volver a conectar"}
                </QuietButton>
                {!enAsistente && (
                  <QuietButton onClick={desconectar}>
                    Desconectar
                  </QuietButton>
                )}
              </div>
              {cambiando && (
                <div className="reveal mt-5 border-t border-line pt-5">{panel(enUso, false)}</div>
              )}
              {tardando && probando && (
                <p className="mt-3 text-apoyo text-ink-3">
                  La primera vez tarda unos segundos: está despertando el programa.
                </p>
              )}
            </div>
          ) : (
            panel(principal, true)
          )}
          {test && abierta === null && <Resultado test={test} />}
        </div>
      </section>

      {!enUso && server?.env_fallback && (
        <p className="mt-3 max-w-[70ch] text-apoyo leading-relaxed text-ink-3">
          Esta computadora ya trae una llave de Claude puesta por fuera de la consola, y tus
          ayudantes la están usando. Si conectas otra cosa aquí, esa manda.
        </p>
      )}

      <h2 className="mt-10 text-seccion font-semibold text-ink">Otras formas de conectar</h2>
      <p className="mt-1 text-cuerpo text-ink-2">
        {enUso
          ? "Puedes cambiar cuando quieras. Al conectar otra, deja de usarse la de arriba."
          : "Todas sirven. Elige la que te acomode."}
      </p>
      <ul className="mt-3 divide-y divide-line border-y border-line">
        {otras.map((via) => {
          const abiertaEsta = abierta === via;
          return (
            <li key={via} className="py-3.5">
              <div className="flex items-center gap-3.5">
                <LogoVia via={via} />
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-cuerpo font-medium text-ink">
                    {VIAS[via].nombre}
                    {via === "chatgpt" && <SinEstrenar />}
                    {enUso && via === recomendada && (
                      <span className="text-apoyo font-normal text-ink-3">
                        recomendada para esta Mac
                      </span>
                    )}
                  </p>
                  <p className="text-apoyo leading-relaxed text-ink-3">{VIAS[via].linea}</p>
                </div>
                <SecondaryButton
                  size="sm"
                  className="shrink-0"
                  aria-expanded={abiertaEsta}
                  onClick={() => {
                    setTest(null);
                    setAbierta(abiertaEsta ? null : via);
                  }}
                >
                  {abiertaEsta ? "Cerrar" : "Elegir"}
                </SecondaryButton>
              </div>
              {abiertaEsta && (
                <div className="reveal mt-4 pb-1.5 sm:pl-[54px]">
                  {panel(via, false)}
                  {test && <Resultado test={test} />}
                </div>
              )}
            </li>
          );
        })}
      </ul>

      {!enAsistente && <AvisoPlanChatGPT estado={server} onVisto={() => mirar()} />}
      {enAsistente && <AvisoPlanChatGPT estado={server} onVisto={() => mirar()} enLinea />}
    </div>
  );
}
