"use client";

import { useEffect, useRef, useState } from "react";
import { api, type ChatGPTEstado, type ProviderState } from "@/lib/api";
import { Modal } from "@/components/modal";
import { PrimaryButton, SinEstrenar } from "@/components/ui";

// "Entrar con ChatGPT": el dueño usa su plan de ChatGPT desde aiuda, por el flujo
// oficial de OpenAI. Lo comparten el asistente de primer arranque y la página Tu IA.
//
// El login NO pasa por esta ventana: el servidor abre el navegador de la computadora,
// el dueño entra allá y OpenAI lo regresa a aiuda. Aquí solo se espera, preguntando
// cada segundo y medio cómo va (GET /v1/provider).

/** Abre la página de ChatGPT donde se ve y se limita el uso. Va por el servidor
 *  porque en la app de escritorio un enlace a otra ventana no abre nada. */
async function abrirUso() {
  try {
    const r = await api.chatgptUso();
    if (!r.abierto) window.open(r.url, "_blank", "noopener,noreferrer");
  } catch {
    window.open("https://chatgpt.com/settings/usage", "_blank", "noopener,noreferrer");
  }
}

/** La marca que ya vive en el repo. `invertido` = en blanco, para el botón negro. */
function LogoChatGPT({ invertido = true }: { invertido?: boolean }) {
  return (
    /* eslint-disable-next-line @next/next/no-img-element */
    <img
      src="/brand/openai.svg"
      alt=""
      aria-hidden="true"
      className={`h-4 w-4 ${invertido ? "invert" : ""}`}
    />
  );
}

/** El botón de entrar. Negro con la marca, como lo piden los lineamientos de OpenAI. */
function BotonChatGPT({
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className="inline-flex items-center gap-2 rounded-md bg-ink px-3.5 py-2 text-cuerpo font-medium text-surface transition-colors hover:bg-ink/85 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50"
    >
      <LogoChatGPT />
      {children}
    </button>
  );
}

export function AdministrarUso({ principal = false }: { principal?: boolean }) {
  return (
    <button
      onClick={abrirUso}
      className={
        principal
          ? "rounded-md bg-accent px-3 py-1.5 text-cuerpo font-medium text-surface transition-colors hover:bg-accent-strong"
          : "font-medium text-accent-ink underline-offset-2 hover:underline"
      }
    >
      Administrar uso
    </button>
  );
}

/** Renglón de "esto es lo que se está usando", con la cuenta y dónde limitarlo. */
export function UsandoPlanChatGPT({ email }: { email?: string | null }) {
  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-cuerpo text-ink-2">
      <LogoChatGPT invertido={false} />
      <span>
        Usando tu plan de ChatGPT{email ? ` (${email})` : ""}.
      </span>
      <AdministrarUso />
    </p>
  );
}

/** Aviso de la primera vez: lo que hagan los ayudantes sale del plan del dueño. Se
 *  enseña una sola vez; que ya se vio lo recuerda el servidor, no esta pantalla.
 *  `enLinea` lo pinta dentro de la página en vez de como ventana: el asistente de
 *  primer arranque ya es una ventana a pantalla completa y taparía la otra. */
export function AvisoPlanChatGPT({
  estado,
  onVisto,
  enLinea = false,
}: {
  estado: ProviderState | null;
  onVisto: () => void;
  enLinea?: boolean;
}) {
  const [cerrando, setCerrando] = useState(false);
  const toca =
    !!estado &&
    estado.name === "chatgpt" &&
    estado.connected &&
    !estado.chatgpt?.bienvenida_vista;

  async function entendido() {
    setCerrando(true);
    try {
      await api.chatgptEntendido();
    } catch {
      /* si no se pudo anotar, se vuelve a enseñar la próxima vez: no es grave */
    }
    setCerrando(false);
    onVisto();
  }

  const titulo = "Estás usando tu plan de ChatGPT";
  const cuerpo = (
    <>
      <p className="text-cuerpo leading-relaxed text-ink-2">
        Lo que hagan tus ayudantes cuenta en tu plan de ChatGPT, junto con lo que tú uses en
        ChatGPT. Puedes ver y limitar ese uso en la configuración de ChatGPT.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <PrimaryButton onClick={entendido} disabled={cerrando}>
          Entendido
        </PrimaryButton>
        <AdministrarUso />
      </div>
    </>
  );

  if (enLinea) {
    if (!toca) return null;
    return (
      <div className="mt-4 rounded-xl border border-line bg-surface px-5 py-4">
        <p className="mb-1.5 text-cuerpo font-semibold text-ink">{titulo}</p>
        {cuerpo}
      </div>
    );
  }
  return (
    <Modal open={toca} onClose={entendido} title={titulo} size="sm">
      {cuerpo}
    </Modal>
  );
}

/** Empezar a entrar y esperar el regreso. `onConectada` corre cuando la conexión ya
 *  quedó guardada; quien lo usa decide qué sigue (probarla, refrescar su pantalla). */
export function EntrarConChatGPT({
  chatgpt,
  onConectada,
  disabled,
}: {
  /** Lo último que se sabe del servidor; sirve para ofrecer "volver a entrar". */
  chatgpt?: ChatGPTEstado;
  onConectada: () => void;
  disabled?: boolean;
}) {
  const [esperando, setEsperando] = useState(false);
  const [enlace, setEnlace] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Quien usa esto suele pasar una función nueva en cada render: se guarda en un ref
  // para que la espera no se reinicie por eso.
  const alConectar = useRef(onConectada);
  useEffect(() => {
    alConectar.current = onConectada;
  }, [onConectada]);

  // Mientras se espera el regreso del navegador, se pregunta cada segundo y medio.
  useEffect(() => {
    if (!esperando) return;
    let vivo = true;
    const reloj = setInterval(async () => {
      try {
        const p = await api.provider();
        if (!vivo) return;
        if (p.name === "chatgpt" && p.connected) {
          setEsperando(false);
          setEnlace(null);
          alConectar.current();
        } else if (p.chatgpt?.error) {
          setEsperando(false);
          setError(p.chatgpt.error);
        } else if (!p.chatgpt?.pendiente) {
          setEsperando(false);
          setError("Pasó demasiado tiempo. Vuelve a intentarlo.");
        }
      } catch {
        /* un tropiezo de red local no cancela la espera */
      }
    }, 1500);
    return () => {
      vivo = false;
      clearInterval(reloj);
    };
  }, [esperando]);

  async function entrar(otraCuenta = false) {
    setError(null);
    setEnlace(null);
    setEsperando(true);
    try {
      const r = await api.chatgptIniciar(otraCuenta);
      if (!r.abierto) setEnlace(r.url);
    } catch (e) {
      setEsperando(false);
      setError((e as Error).message);
    }
  }

  function cancelar() {
    setEsperando(false);
    setEnlace(null);
  }

  const cuenta = chatgpt?.registrada ? chatgpt.email : null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-cuerpo font-semibold text-ink">Usa tu plan de ChatGPT</p>
        <SinEstrenar />
      </div>
      <p className="text-cuerpo leading-relaxed text-ink-2">
        Entras con tu cuenta en el navegador y tus ayudantes trabajan con el plan de ChatGPT
        que ya pagas. No pegas ninguna llave. Lo que usen cuenta en tu plan, junto con lo que
        tú uses en ChatGPT, y ahí mismo puedes ponerle un límite a aiuda.
      </p>
      <p className="text-apoyo leading-relaxed text-ink-3">
        Es la vía que OpenAI abrió para programas abiertos que corren en tu computadora.
        Todavía nadie la ha usado en aiuda con una cuenta real. Lo menos seguro es que tus
        ayudantes puedan consultar tus datos al platicar contigo por esta vía. Si tu cuenta,
        tu plan u OpenAI no lo admiten, aquí mismo te lo decimos y puedes conectar tu IA de
        otra forma.
      </p>

      {chatgpt?.vencida && !esperando && !error && (
        <p className="rounded-md border border-warn/40 bg-warn-soft px-3 py-2 text-cuerpo text-ink">
          Tu conexión con ChatGPT venció. Vuelve a entrar.
        </p>
      )}

      {esperando ? (
        <div className="space-y-2 rounded-lg border border-line bg-surface px-4 py-3">
          <p className="text-cuerpo leading-relaxed text-ink">
            Te abrimos el navegador. Entra con tu cuenta de ChatGPT y regresa aquí.
          </p>
          {enlace && (
            <p className="text-cuerpo leading-relaxed text-ink-2">
              Si no se abrió,{" "}
              <a
                href={enlace}
                target="_blank"
                rel="noreferrer"
                className="font-medium text-accent-ink underline-offset-2 hover:underline"
              >
                abre esta página
              </a>
              .
            </p>
          )}
          <button
            onClick={cancelar}
            className="text-cuerpo text-ink-3 underline-offset-2 transition-colors hover:text-ink hover:underline"
          >
            Cancelar
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <BotonChatGPT onClick={() => entrar(false)} disabled={disabled}>
            Continuar con ChatGPT
          </BotonChatGPT>
          {cuenta && (
            <span className="text-apoyo text-ink-3">
              Entrarás como {cuenta}.{" "}
              <button
                onClick={() => entrar(true)}
                disabled={disabled}
                className="text-ink-2 underline-offset-2 transition-colors hover:text-ink hover:underline"
              >
                Entrar con otra cuenta
              </button>
            </span>
          )}
        </div>
      )}

      {error && (
        <p className="rounded-md border border-danger/40 bg-danger-soft px-3 py-2 text-cuerpo text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
