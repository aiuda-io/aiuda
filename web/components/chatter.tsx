"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";
import { SecondaryButton } from "@/components/ui";
import { WaText } from "@/components/wa-text";
import { fechaHora } from "@/lib/format";

export type ChatterMessage = {
  id: string;
  side: "them" | "me";
  label?: string;
  avatar?: string | null;
  body: string;
  time?: string | null;
  /** Pie opcional bajo la burbuja (estado de envío, reintentar): así un hilo con
   *  entrega (cliente por WhatsApp) reusa el mismo chat sin perder esa señal. */
  meta?: ReactNode;
};

const fmtTime = (iso?: string | null) => (iso ? fechaHora(iso) : "");

function Avatar({ name, src }: { name: string; src?: string | null }) {
  if (src)
    return (
      <span className="flex h-6 w-6 shrink-0 items-center justify-center overflow-hidden rounded-full bg-fill">
        <img src={src} alt={name} className="h-full w-full object-contain p-0.5" />
      </span>
    );
  return (
    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-fill text-sello font-semibold text-ink-2">
      {name.slice(0, 2).toUpperCase()}
    </span>
  );
}

export function Chatter({
  messages,
  onSend,
  onSendFile,
  placeholder = "Escribe un mensaje…",
  emptyTitle = "Sin mensajes todavía",
  emptyHint,
  suggestions = [],
  channel,
  thinking,
  thinkingLabel,
  sendLabel = "Enviar",
  fill = false,
}: {
  messages: ChatterMessage[];
  onSend: (body: string) => Promise<void>;
  /** Si se pasa, muestra el botón de adjuntar (PDF/imagen). El draft actual va de caption. */
  onSendFile?: (file: File, caption: string) => Promise<void>;
  placeholder?: string;
  emptyTitle?: string;
  emptyHint?: string;
  /** Preguntas de arranque, tocables, en el hilo vacío: quitan el "y ahora qué le digo".
   *  Solo son texto que se manda como mensaje; no disparan ninguna acción por su cuenta. */
  suggestions?: string[];
  channel?: { active: string; options?: string[] };
  thinking?: boolean;
  /** Quién está pensando (nombre del ayudante), para que la espera tenga cara. */
  thinkingLabel?: string;
  sendLabel?: string;
  /** Llena la altura del contenedor (el hilo crece con él) en vez del tope fijo de 420px.
   *  Para la superficie de trabajo del ayudante, donde el chat es el centro. */
  fill?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const hiloRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function pickFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // permite re-elegir el mismo archivo
    if (!file || !onSendFile || sending) return;
    setSending(true);
    const caption = draft.trim();
    setDraft("");
    try {
      await onSendFile(file, caption);
    } finally {
      setSending(false);
    }
  }

  // Baja al último mensaje moviendo SOLO el hilo. Antes usaba scrollIntoView, que
  // también arrastraba la página: abrir la ficha de un cliente la dejaba a media
  // pantalla, con el encabezado fuera de vista.
  useEffect(() => {
    const hilo = hiloRef.current;
    if (hilo) hilo.scrollTop = hilo.scrollHeight;
  }, [messages.length, thinking]);

  async function enviar(texto: string) {
    const body = texto.trim();
    if (!body || sending) return;
    setSending(true);
    setDraft("");
    try {
      await onSend(body);
    } finally {
      setSending(false);
    }
  }

  const submit = () => enviar(draft);

  const CHANNEL_LOGO: Record<string, string> = {
    whatsapp: "/brand/int/whatsapp.png",
  };

  return (
    // Sin caja: el hilo va sobre el papel y una raya fina lo separa del campo donde
    // se escribe. Lo que llega va sobre gris pálido; lo que sale, con contorno. El
    // acento se guarda para el botón de enviar.
    <div className={`flex min-w-0 flex-col ${fill ? "h-full" : ""}`}>
      {/* Hilo */}
      <div
        ref={hiloRef}
        className={`space-y-4 overflow-y-auto py-4 pr-1 ${
          fill ? "min-h-0 flex-1" : "max-h-[420px] min-h-[180px] flex-1"
        }`}
      >
        {messages.length === 0 && !thinking && (
          <div className="flex h-full min-h-[140px] flex-col items-center justify-center px-2 text-center">
            <p className="text-cuerpo font-medium text-ink">{emptyTitle}</p>
            {emptyHint && (
              <p className="mt-1 max-w-sm text-cuerpo leading-relaxed text-ink-3">{emptyHint}</p>
            )}
            {suggestions.length > 0 && (
              <div className="mt-4 flex flex-wrap justify-center gap-1.5">
                {suggestions.map((s) => (
                  <SecondaryButton
                    key={s}
                    type="button"
                    onClick={() => enviar(s)}
                    disabled={sending}
 size="sm"
>
                    {s}
                  </SecondaryButton>
                ))}
              </div>
            )}
          </div>
        )}
        {messages.map((m) => {
          const mine = m.side === "me";
          return (
            <div key={m.id} className={`flex items-end gap-2 ${mine ? "flex-row-reverse" : ""}`}>
              <Avatar name={m.label ?? (mine ? "Tú" : "··")} src={m.avatar} />
              <div className={`max-w-[78%] ${mine ? "items-end text-right" : ""}`}>
                {m.label && <p className="mb-0.5 px-1 text-sello font-medium text-ink-3">{m.label}</p>}
                <div
                  className={`inline-block rounded-2xl px-3.5 py-2 text-left text-ink ${
                    mine ? "bg-surface shadow-[inset_0_0_0_1px_var(--color-line-strong)]" : "bg-fill"
                  }`}
                >
                  <WaText className="text-cuerpo leading-relaxed">{m.body}</WaText>
                </div>
                {(m.time || m.meta) && (
                  <div className={`mt-0.5 flex items-center gap-2 px-1 ${mine ? "justify-end" : ""}`}>
                    {m.meta}
                    {m.time && <span className="tnum text-sello text-ink-3">{fmtTime(m.time)}</span>}
                  </div>
                )}
              </div>
            </div>
          );
        })}
        {thinking && (
          <div className="flex items-end gap-2" aria-live="polite">
            <Avatar name={thinkingLabel ?? "··"} />
            <div>
              {thinkingLabel && (
                <p className="mb-0.5 px-1 text-sello font-medium text-ink-3">{thinkingLabel}</p>
              )}
              <div className="flex items-center gap-2 rounded-2xl bg-fill px-3.5 py-2.5">
                <span className="chatter-dots inline-flex gap-1">
                  <span className="h-1.5 w-1.5 rounded-full bg-ink-3" />
                  <span className="h-1.5 w-1.5 rounded-full bg-ink-3" />
                  <span className="h-1.5 w-1.5 rounded-full bg-ink-3" />
                </span>
                <span className="text-apoyo text-ink-3">Pensando…</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Compositor */}
      <div className="border-t border-line pt-3">
        {channel && (
          <div className="mb-2 flex items-center gap-1.5">
            <span className="sello gap-1">
              {CHANNEL_LOGO[channel.active] && (
                <img src={CHANNEL_LOGO[channel.active]} alt="" className="h-3 w-3" />
              )}
              {channel.active === "whatsapp" ? "WhatsApp" : channel.active}
            </span>
            {(channel.options ?? []).map((opt) => (
              <span
                key={opt}
                title="Disponible al conectar este canal"
                className="sello gap-1 text-ink-3"
              >
                {CHANNEL_LOGO[opt] && <img src={CHANNEL_LOGO[opt]} alt="" className="h-3 w-3 grayscale" />}
                {opt === "email" ? "Correo" : opt}
              </span>
            ))}
          </div>
        )}
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          {onSendFile && (
            <>
              <input
                ref={fileRef}
                type="file"
                accept=".pdf,image/*"
                onChange={pickFile}
                className="hidden"
              />
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                disabled={sending}
                aria-label="Adjuntar PDF o imagen"
                title="Adjuntar PDF o imagen"
                className="btn btn-secondary w-10 shrink-0 px-0"
              >
                <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none">
                  <path
                    d="M10.5 5.5 6 10a1.5 1.5 0 0 0 2.12 2.12l4.6-4.6a3 3 0 0 0-4.24-4.24l-4.6 4.6a4.5 4.5 0 0 0 6.36 6.36L13.5 11"
                    stroke="currentColor"
                    strokeWidth="1.3"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            </>
          )}
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            rows={1}
            placeholder={placeholder}
            className="field max-h-28 flex-1 resize-none focus:border-accent focus:outline-none"
          />
          <button
            type="submit"
            disabled={sending || !draft.trim()}
            aria-label={sendLabel}
            className="btn btn-primary w-10 shrink-0 px-0"
          >
            <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none">
              <path d="M2 8 14 2l-4 12-2.5-4.5L2 8Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
            </svg>
          </button>
        </form>
      </div>

      <style>{`
        @keyframes chatterBlink { 0%,80%,100% { opacity:.3 } 40% { opacity:1 } }
        .chatter-dots span { animation: chatterBlink 1.2s infinite both; }
        .chatter-dots span:nth-child(2) { animation-delay: .2s; }
        .chatter-dots span:nth-child(3) { animation-delay: .4s; }
        @media (prefers-reduced-motion: reduce) { .chatter-dots span { animation: none; } }
      `}</style>
    </div>
  );
}
