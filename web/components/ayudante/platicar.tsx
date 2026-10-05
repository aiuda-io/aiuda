"use client";

// Platicar con el ayudante. Aquí solo consulta (cartera, catálogo, agenda, pagos) y
// propone texto: nada sale a un cliente desde esta plática.
import { useRef, useState } from "react";
import { api, type AiuditaConfig } from "@/lib/api";
import { Chatter, type ChatterMessage } from "@/components/chatter";

/** Preguntas de arranque HONESTAS: solo las que este ayudante puede contestar de
 *  verdad con lo que sabe hacer. */
const PREGUNTAS_POR_AIUDITA: [string, string][] = [
  ["cobranza.consultar_cartera", "¿Cómo va mi cartera?"],
  ["cobranza.consultar_cartera", "¿A quién le cobro hoy?"],
  ["cobranza.redactar_recordatorio", "Propón un recordatorio para el cliente que más debe"],
  ["conciliacion.consultar_pagos", "¿Qué pagos entraron esta semana?"],
  ["ventas.consultar_cliente", "Cuéntame de mi cliente más importante"],
  ["ventas.consultar_catalogo", "¿Qué le puedo ofrecer a un cliente nuevo?"],
  ["recepcion.consultar_agenda", "¿Cómo está mi agenda de hoy?"],
  ["recepcion.buscar_cita", "¿Tengo alguna cita sin confirmar?"],
];

function preguntasDeArranque(activos: Record<string, AiuditaConfig>): string[] {
  const puede = (id: string) => id in activos;
  const lista = PREGUNTAS_POR_AIUDITA.filter(([aiudita]) => {
    if (!puede(aiudita)) return false;
    // Redactar sin de dónde leer no daría un borrador con datos reales.
    if (aiudita === "cobranza.redactar_recordatorio") return puede("cobranza.consultar_cartera");
    return true;
  }).map(([, pregunta]) => pregunta);
  return [...lista.slice(0, 3), "¿Qué sabes hacer?"];
}

export function Platicar({
  id,
  name,
  activos,
}: {
  id: string;
  name: string;
  activos: Record<string, AiuditaConfig>;
}) {
  const [messages, setMessages] = useState<ChatterMessage[]>([]);
  const [thinking, setThinking] = useState(false);
  const historyRef = useRef<{ role: string; body: string }[]>([]);

  async function send(body: string) {
    const now = new Date().toISOString();
    setMessages((prev) => [
      ...prev,
      { id: `u-${historyRef.current.length}-${now}`, side: "me", label: "Tú", body, time: now },
    ]);
    historyRef.current.push({ role: "user", body });
    setThinking(true);
    try {
      const { reply } = await api.ayudanteChat(id, body, historyRef.current);
      historyRef.current.push({ role: "agent", body: reply });
      setMessages((prev) => [
        ...prev,
        {
          id: `a-${historyRef.current.length}-${reply.slice(0, 6)}`,
          side: "them",
          label: name,
          body: reply,
          time: new Date().toISOString(),
        },
      ]);
    } catch (e) {
      // El servidor ya redacta el motivo en español (falta tu IA, llegaste a tu tope).
      const motivo = e instanceof Error && e.message && !/^Error \d+$/.test(e.message) ? e.message : "";
      setMessages((prev) => [
        ...prev,
        {
          id: `e-${historyRef.current.length}`,
          side: "them",
          label: name,
          body: motivo || "No pude responder. Intenta de nuevo en un momento.",
        },
      ]);
    } finally {
      setThinking(false);
    }
  }

  return (
    <div className="h-[min(640px,calc(100dvh-20rem))] min-h-[420px]">
      <Chatter
        messages={messages}
        onSend={send}
        thinking={thinking}
        thinkingLabel={name}
        fill
        placeholder={`Pregúntale a ${name}`}
        emptyTitle={`Platica con ${name}`}
        emptyHint={`Pregúntale por tu negocio o pídele una propuesta. ${name} propone y tú decides qué sale.`}
        suggestions={preguntasDeArranque(activos)}
      />
    </div>
  );
}
