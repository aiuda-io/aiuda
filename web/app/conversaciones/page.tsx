"use client";

// Master-detail de Conversaciones en UNA ruta: la bandeja (izquierda) fija y el
// hilo (derecha) elegido por ?id=. Navegar entre hilos cambia solo el query, así
// la lista no se remonta ni se recarga. En móvil se muestra una sola: la lista
// sin ?id, el hilo con ?id.
import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, type ConversationDetail } from "@/lib/api";
import { ChevronLeft, ErrorState, Skeleton, useApi } from "@/components/ui";
import { Chatter, type ChatterMessage } from "@/components/chatter";
import { ConversationsList } from "@/components/conversations-list";
import { usePageTrail } from "@/components/rastro";
import { toast } from "@/components/toast";

export default function ConversacionesPage() {
  // useSearchParams exige un boundary de Suspense en el export estático.
  return (
    <Suspense fallback={null}>
      <Conversaciones />
    </Suspense>
  );
}

function Conversaciones() {
  const id = useSearchParams().get("id") ?? "";
  const enHilo = id !== "";

  return (
    <div className="flex h-[calc(100dvh-8.5rem)] min-h-[480px] overflow-hidden rounded-xl border border-line bg-surface">
      <aside
        className={`${enHilo ? "hidden md:flex" : "flex"} w-full shrink-0 flex-col border-r border-line bg-panel/40 md:w-[344px]`}
      >
        <ConversationsList />
      </aside>
      <main className={`${enHilo ? "flex" : "hidden md:flex"} min-w-0 flex-1 flex-col bg-surface`}>
        {enHilo ? <Conversacion id={id} /> : <SinHilo />}
      </main>
    </div>
  );
}

function SinHilo() {
  return (
    <div className="hidden h-full flex-col items-center justify-center px-8 text-center md:flex">
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-panel text-ink-3">
        <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.4">
          <path d="M4 5.5h16v10H9l-4 3v-3H4z" strokeLinejoin="round" />
        </svg>
      </span>
      <p className="mt-3 text-[13px] font-medium text-ink">Elige una conversación</p>
      <p className="mt-1 max-w-xs text-[12px] text-ink-3">
        Sus mensajes aparecen aquí. Entras a responder cuando quieras; tu ayudante te avisa lo
        que necesita tu aprobación en el Centro.
      </p>
    </div>
  );
}

function Conversacion({ id }: { id: string }) {
  const { data, error, loading, refetch } = useApi<ConversationDetail>(
    () => api.conversation(id),
    [id],
  );
  const [toggling, setToggling] = useState(false);
  const [retryingId, setRetryingId] = useState<string | null>(null);
  usePageTrail(
    data?.customer ?? data?.correo?.nombre ?? data?.correo?.de ?? data?.remote_phone ?? "Conversación",
  );

  const takeover = data?.human_takeover ?? false;
  const esCorreo = data?.channel === "correo";
  const themName =
    data?.customer ??
    (esCorreo ? data?.correo?.nombre || data?.correo?.de || "Remitente" : data?.remote_phone) ??
    "…";

  const toggleTakeover = async () => {
    if (!data) return;
    setToggling(true);
    try {
      await api.takeover(data.id, !takeover);
      refetch();
    } catch (e) {
      toast(`No se pudo cambiar quién atiende: ${(e as Error).message}`, "error");
    } finally {
      setToggling(false);
    }
  };

  const resend = async (messageId: string) => {
    if (!data) return;
    setRetryingId(messageId);
    try {
      await api.resendMessage(data.id, messageId);
      refetch();
    } catch (e) {
      toast(`No se pudo reintentar: ${(e as Error).message}`, "error");
    } finally {
      setRetryingId(null);
    }
  };

  const send = async (body: string) => {
    if (!data) return;
    try {
      await api.sendHumanMessage(data.id, body);
      refetch();
    } catch (e) {
      toast(`No se pudo enviar: ${(e as Error).message}`, "error");
      throw e;
    }
  };

  const messages: ChatterMessage[] = (data?.messages ?? []).map((m) => {
    const mine = m.direction === "out";
    const human = m.author === "human";
    return {
      id: m.id,
      side: mine ? "me" : "them",
      label: human ? "Tú" : mine ? "Ayudante" : themName,
      body: m.body,
      time: m.created_at,
      // Solo lo que TÚ mandaste a mano lleva estado de entrega + reintento.
      meta:
        mine && human ? (
          m.delivery === "failed" ? (
            <button
              onClick={() => resend(m.id)}
              disabled={retryingId === m.id}
              className="text-[10px] font-medium text-danger underline decoration-danger/40 underline-offset-2 hover:decoration-danger disabled:opacity-60"
            >
              {retryingId === m.id ? "Reintentando…" : "No se envió · Reintentar"}
            </button>
          ) : m.delivery === "pending" ? (
            <span className="text-[10px] text-ink-3">Enviando…</span>
          ) : m.delivery === "sent" ? (
            <span className="text-[10px] text-ink-3">Enviado</span>
          ) : undefined
        ) : undefined,
    };
  });

  if (error) {
    return (
      <div className="p-6">
        <ErrorState message={error} retry={refetch} />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Cabecera del hilo */}
      <header className="flex h-[52px] shrink-0 items-center gap-3 border-b border-line px-4">
        <Link
          href="/conversaciones"
          aria-label="Volver a conversaciones"
          className="-ml-1 shrink-0 rounded-md p-1 text-ink-3 hover:text-ink md:hidden"
        >
          <ChevronLeft />
        </Link>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-[14px] font-semibold text-ink">
            {data?.customer_id ? (
              <Link
                href={`/clientes/detalle?id=${data.customer_id}`}
                className="underline-offset-2 transition-colors hover:text-accent-ink hover:underline"
              >
                {themName}
              </Link>
            ) : (
              themName
            )}
          </h1>
          {data && (
            <p className="tnum truncate text-[11px] text-ink-3">
              {esCorreo
                ? `Correo · ${data.correo?.de || "sin remitente"}${data.correo?.asunto ? ` · ${data.correo.asunto}` : ""}`
                : `WhatsApp · ${data.remote_phone}`}
            </p>
          )}
        </div>
        {data && (
          <button
            onClick={toggleTakeover}
            disabled={toggling}
            className={`shrink-0 rounded-md px-3 py-1.5 text-[12px] font-medium transition-colors disabled:opacity-60 ${
              takeover
                ? "bg-accent text-surface hover:bg-accent-strong"
                : "border border-line bg-surface text-ink-2 hover:border-accent hover:text-accent-ink"
            }`}
          >
            {takeover ? "Devolver al ayudante" : "Tomar el control"}
          </button>
        )}
      </header>

      {takeover && (
        <p className="shrink-0 border-b border-line bg-accent-soft px-4 py-2 text-[12px] font-medium text-accent-ink">
          Tú tienes el control. Tu ayudante está en pausa y no responderá hasta que se lo devuelvas.
        </p>
      )}

      {/* Hilo: llena el alto del panel, con scroll interno y composer pegado abajo */}
      <div className="min-h-0 flex-1 p-3">
        {loading && !data ? (
          <Skeleton className="h-full w-full rounded-xl" />
        ) : (
          <Chatter
            fill
            messages={messages}
            onSend={send}
            emptyTitle="Sin mensajes todavía"
            emptyHint={
              esCorreo
                ? "Cuando el cliente responda por correo, el hilo aparece aquí."
                : "Cuando el cliente escriba por WhatsApp, el hilo aparece aquí."
            }
            placeholder={
              esCorreo
                ? "Escribe tu respuesta; sale por correo en el mismo hilo (Re:)…"
                : "Escribe como tú; el cliente lo recibe de tu parte…"
            }
          />
        )}
      </div>
    </div>
  );
}
