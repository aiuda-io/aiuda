"use client";

// Mensajes en UNA ruta: la bandeja a la izquierda y el hilo a la derecha, elegido por
// ?id=. Cambiar de hilo solo cambia el query, así la bandeja no se recarga. En el
// teléfono se ve una cosa a la vez: la lista sin ?id, el hilo con ?id.
import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, type ConversationDetail, type ConversationItem, type CustomerItem } from "@/lib/api";
import {
  ChevronLeft,
  ErrorState,
  PrimaryButton,
  SecondaryButton,
  Skeleton,
  TextInput,
  inputCls,
  useApi,
} from "@/components/ui";
import { Chatter, type ChatterMessage } from "@/components/chatter";
import { ConversationsList } from "@/components/conversations-list";
import { usePageTrail } from "@/components/rastro";
import { toast } from "@/components/toast";

export default function ConversacionesPage() {
  // useSearchParams exige un boundary de Suspense en el export estático.
  return (
    <Suspense fallback={null}>
      <Mensajes />
    </Suspense>
  );
}

function Mensajes() {
  const id = useSearchParams().get("id") ?? "";
  const enHilo = id !== "";
  const { data, error, loading, refetch, refetchQuiet } = useApi<ConversationItem[]>(api.conversations);
  const conversations = data ?? [];
  const sinNada = !loading && !error && conversations.length === 0;

  return (
    <div className="flex h-[calc(100dvh-8.5rem)] min-h-[480px] min-w-0 gap-6">
      <aside
        className={`${enHilo ? "hidden md:flex" : "flex"} w-full min-w-0 flex-col rounded-xl bg-panel ${
          sinNada ? "" : "md:w-[360px] md:shrink-0"
        }`}
      >
        <ConversationsList
          conversations={conversations}
          loading={loading}
          error={error}
          retry={refetch}
          activeId={id}
        />
      </aside>
      {!sinNada && (
        <main className={`${enHilo ? "flex" : "hidden md:flex"} min-w-0 flex-1 flex-col`}>
          {enHilo ? (
            <Hilo id={id} enBandeja={conversations.find((c) => c.id === id)} onCambio={refetchQuiet} />
          ) : (
            <SinHilo />
          )}
        </main>
      )}
    </div>
  );
}

function SinHilo() {
  return (
    <div className="flex h-full flex-col items-center justify-center px-8 text-center">
      <p className="text-seccion font-semibold text-ink">Elige una conversación</p>
      <p className="mt-2 max-w-sm text-cuerpo text-ink-2">
        Aquí lees el hilo y contestas cuando quieras. Lo que tu ayudante redacta queda en Hoy
        para que lo apruebes.
      </p>
    </div>
  );
}

function Hilo({
  id,
  enBandeja,
  onCambio,
}: {
  id: string;
  enBandeja: ConversationItem | undefined;
  onCambio: () => void;
}) {
  const { data, error, loading, refetch } = useApi<ConversationDetail>(() => api.conversation(id), [id]);
  const [ocupado, setOcupado] = useState(false);
  const [reintentando, setReintentando] = useState<string | null>(null);
  usePageTrail(
    data?.customer ?? data?.correo?.nombre ?? data?.correo?.de ?? data?.remote_phone ?? "Conversación",
  );

  const alMando = data?.human_takeover ?? false;
  const esCorreo = data?.channel === "correo";
  const nombre =
    data?.customer ??
    (esCorreo ? data?.correo?.nombre || data?.correo?.de || "Remitente" : data?.remote_phone) ??
    "…";
  const estado = enBandeja?.status ?? "identificado";

  async function hacer(fn: () => Promise<unknown>, falla: string, listo?: string) {
    setOcupado(true);
    try {
      await fn();
      if (listo) toast(listo, "info");
      refetch();
      onCambio();
    } catch (e) {
      toast(`${falla}: ${(e as Error).message}`, "error");
    } finally {
      setOcupado(false);
    }
  }

  const reenviar = async (messageId: string) => {
    if (!data) return;
    setReintentando(messageId);
    try {
      await api.resendMessage(data.id, messageId);
      refetch();
    } catch (e) {
      toast(`No se pudo reintentar: ${(e as Error).message}`, "error");
    } finally {
      setReintentando(null);
    }
  };

  const enviar = async (body: string) => {
    if (!data) return;
    try {
      await api.sendHumanMessage(data.id, body);
      refetch();
      onCambio();
    } catch (e) {
      toast(`No se pudo enviar: ${(e as Error).message}`, "error");
      throw e;
    }
  };

  const messages: ChatterMessage[] = (data?.messages ?? []).map((m) => {
    const mio = m.direction === "out";
    const humano = m.author === "human";
    return {
      id: m.id,
      side: mio ? "me" : "them",
      label: humano ? "Tú" : mio ? "Tu ayudante" : nombre,
      body: m.body,
      time: m.created_at,
      // Solo lo que TÚ mandaste a mano lleva estado de entrega y reintento.
      meta:
        mio && humano ? (
          m.delivery === "failed" ? (
            // El motivo va junto al aviso: "No se envió" a secas no dice qué hacer.
            <span className="flex flex-col items-end gap-0.5 text-right">
              {m.reintentable === false ? (
                <span className="text-rotulo font-medium text-danger">No se envió</span>
              ) : (
                <button
                  onClick={() => reenviar(m.id)}
                  disabled={reintentando === m.id}
                  className="text-rotulo font-medium text-danger underline underline-offset-2 disabled:opacity-60"
                >
                  {reintentando === m.id ? "Reintentando…" : "No se envió. Reintentar"}
                </button>
              )}
              {m.motivo_fallo && <span className="max-w-xs text-rotulo text-ink-3">{m.motivo_fallo}</span>}
            </span>
          ) : m.delivery === "pending" || m.delivery === "sending" ? (
            <span className="text-rotulo text-ink-3">Enviando…</span>
          ) : m.delivery === "sent" ? (
            <span className="text-rotulo text-ink-3">Enviado</span>
          ) : undefined
        ) : undefined,
    };
  });

  if (error) return <ErrorState message={error} retry={refetch} />;

  return (
    <div className="flex h-full min-w-0 flex-col">
      <header className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 pb-4">
        <Link
          href="/conversaciones"
          aria-label="Volver a Mensajes"
          className="-ml-1 shrink-0 rounded-md p-2 text-ink-2 hover:text-ink md:hidden"
        >
          <ChevronLeft className="h-4 w-4" />
        </Link>
        <div className="min-w-0 flex-1 basis-40">
          <h2 className="truncate text-seccion font-semibold text-ink">
            {data?.customer_id ? (
              <Link href={`/clientes/detalle?id=${data.customer_id}`} className="hover:text-accent-ink hover:underline">
                {nombre}
              </Link>
            ) : (
              nombre
            )}
          </h2>
          {data && (
            <p className="tnum truncate text-apoyo text-ink-3">
              {esCorreo
                ? `Correo · ${data.correo?.de || "sin remitente"}${data.correo?.asunto ? ` · ${data.correo.asunto}` : ""}`
                : `WhatsApp · ${data.remote_phone}`}
            </p>
          )}
        </div>
        {data && (
          <div className="flex shrink-0 items-center gap-2">
            <button
              onClick={() =>
                estado === "descartado"
                  ? hacer(() => api.undismissConversation(data.id), "No se pudo regresar", "De vuelta en la bandeja.")
                  : hacer(() => api.dismissConversation(data.id), "No se pudo descartar", "Conversación descartada.")
              }
              disabled={ocupado}
              className="btn btn-quiet btn-sm"
            >
              {estado === "descartado" ? "Regresar a la bandeja" : "Descartar"}
            </button>
            <SecondaryButton
              size="sm"
              onClick={() => hacer(() => api.takeover(data.id, !alMando), "No se pudo cambiar quién atiende")}
              disabled={ocupado}
            >
              {alMando ? "Devolver al ayudante" : "Atender yo"}
            </SecondaryButton>
          </div>
        )}
      </header>

      {alMando && (
        <p className="mb-3 shrink-0 rounded-lg bg-accent-soft px-4 py-2.5 text-cuerpo text-accent-ink">
          Tú atiendes esta conversación. Tu ayudante no contesta aquí hasta que se la devuelvas.
        </p>
      )}

      {data && estado === "por_identificar" && (
        <Identificar
          contacto={esCorreo ? data.correo?.de || "este correo" : data.remote_phone}
          esCorreo={esCorreo}
          ocupado={ocupado}
          onRegistrar={(opts) =>
            hacer(
              () => api.registrarClienteConversacion(data.id, opts),
              "No se pudo registrar",
              opts.linkCustomerId
                ? "Conversación ligada al cliente."
                : "Cliente dado de alta. La conversación quedó identificada.",
            )
          }
        />
      )}

      {/* El hilo llena el alto que queda, con scroll propio y el campo pegado abajo. */}
      <div className="min-h-0 flex-1">
        {loading && !data ? (
          <Skeleton className="h-full w-full rounded-xl" />
        ) : (
          <Chatter
            fill
            messages={messages}
            onSend={enviar}
            emptyTitle="Sin mensajes todavía"
            emptyHint={
              esCorreo
                ? "Cuando el cliente responda por correo, el hilo aparece aquí."
                : "Cuando el cliente escriba por WhatsApp, el hilo aparece aquí."
            }
            placeholder={
              esCorreo ? "Responde por correo" : "Escribe tu respuesta"
            }
          />
        )}
      </div>
    </div>
  );
}

/** Un contacto sin identificar todavía no es de nadie: se liga a un cliente que ya
 *  existe o se da de alta uno nuevo. */
function Identificar({
  contacto,
  esCorreo,
  ocupado,
  onRegistrar,
}: {
  contacto: string;
  esCorreo: boolean;
  ocupado: boolean;
  onRegistrar: (opts: { name?: string; linkCustomerId?: string }) => void;
}) {
  const [clientes, setClientes] = useState<CustomerItem[]>([]);
  const [ligar, setLigar] = useState("");
  const [nombre, setNombre] = useState("");

  useEffect(() => {
    api.customers("cliente").then(setClientes).catch(() => {});
  }, []);

  return (
    <div className="mb-3 shrink-0 rounded-xl bg-panel px-4 py-3.5">
      <p className="text-cuerpo text-ink">
        {esCorreo ? "El correo" : "El número"} <span className="tnum font-medium">{contacto}</span> todavía
        no es de ningún cliente.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {clientes.length > 0 && (
          <>
            <select
              value={ligar}
              onChange={(e) => setLigar(e.target.value)}
              aria-label="Ligar a un cliente que ya tienes"
              className={`${inputCls} max-w-[16rem]`}
            >
              <option value="">Es un cliente que ya tengo</option>
              {clientes.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <SecondaryButton onClick={() => onRegistrar({ linkCustomerId: ligar })} disabled={!ligar || ocupado}>
              Ligar
            </SecondaryButton>
          </>
        )}
        <TextInput
          value={nombre}
          onChange={(e) => setNombre(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && nombre.trim()) onRegistrar({ name: nombre.trim() });
          }}
          placeholder="O es nuevo: su nombre"
          aria-label="Nombre del cliente nuevo"
          className="max-w-[16rem]"
        />
        <PrimaryButton onClick={() => onRegistrar({ name: nombre.trim() })} disabled={!nombre.trim() || ocupado}>
          Dar de alta
        </PrimaryButton>
      </div>
    </div>
  );
}
