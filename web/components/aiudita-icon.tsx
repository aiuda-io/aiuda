import type { ReactNode } from "react";

// Iconos por aiudita (capacidad). Estilo línea, currentColor — el color lo da el
// contenedor (el cuadro de tipo). Reconocibles para un dueño no-técnico: cada
// capacidad tiene su propia figura, no un glifo genérico.
//
// Encuadre: cada figura se dibujó en una retícula de 24 pero ocupando distinto,
// así que dentro del cuadro de fondo unas salían diminutas y otras corridas de
// centro. Para que TODAS se vean del mismo tamaño y centradas, cada icono declara
// la caja de su trazo [x, y, ancho, alto] y aquí se calcula un viewBox cuadrado
// centrado en ella. El grosor de línea se compensa con el mismo factor, así el
// trazo se ve idéntico en todos. Si mueves un trazo, actualiza su caja.
const TRAZO = 1.7; // grosor de línea en unidades de la retícula de 24
const AIRE = 0.92; // qué parte del cuadro ocupa el lado largo de la figura

type Caja = [number, number, number, number];

function svg(caja: Caja, children: ReactNode) {
  const [x, y, w, h] = caja;
  const lado = (Math.max(w, h) + TRAZO) / AIRE;
  const vb = [x + w / 2 - lado / 2, y + h / 2 - lado / 2, lado, lado]
    .map((n) => Math.round(n * 1000) / 1000)
    .join(" ");
  return (
    <svg
      viewBox={vb}
      className="h-full w-full"
      fill="none"
      stroke="currentColor"
      strokeWidth={Math.round((TRAZO * lado) / 24 * 1000) / 1000}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  );
}

// Por id de aiudita. Lo no listado cae al icono de su tipo (consulta/actúa/envía).
const BY_ID: Record<string, ReactNode> = {
  // Cobranza
  "cobranza.consultar_cartera": svg([3, 6, 16, 12], <><path d="M4 6h13a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6z" /><path d="M3 8h16" /><circle cx="15.5" cy="13" r="1.4" /></>),
  "cobranza.redactar_recordatorio": svg([5, 4, 14, 16], <><path d="M5 4h9l5 5v11a0 0 0 0 1 0 0H5z" /><path d="M14 4v5h5" /><path d="M8 13h7M8 16.5h5" /></>),
  "cobranza.registrar_promesa_pago": svg([4, 3, 16, 17], <><rect x="4" y="5" width="16" height="15" rx="2" /><path d="M4 9h16M8 3v4M16 3v4" /><path d="M9 14.5l2 2 4-4" /></>),
  "cobranza.registrar_pago": svg([3.5, 3.5, 17, 17], <><circle cx="12" cy="12" r="8.5" /><path d="M8.5 12.2l2.4 2.4 4.6-5" /></>),
  "cobranza.enviar_whatsapp": svg([3.5, 4.5, 16.5, 15], <><path d="M3.5 11.5 20 4.5l-5 15-4-6-7-2z" /><path d="M11 13.5 20 4.5" /></>),
  "cobranza.resumen_diario": svg([4.5, 2.5, 15, 18], <><circle cx="12" cy="13" r="7.5" /><path d="M12 13V8.5M12 13l3 2" /><path d="M9 2.5h6" /></>),
  // Ventas
  "ventas.consultar_catalogo": svg([4, 3, 16, 18], <><path d="M4 7.5 12 3l8 4.5v9L12 21l-8-4.5z" /><path d="M4 7.5 12 12l8-4.5M12 12v9" /></>),
  "ventas.consultar_cliente": svg([5.5, 5, 13, 14.5], <><circle cx="12" cy="8.5" r="3.5" /><path d="M5.5 19.5a6.5 6.5 0 0 1 13 0" /></>),
  "ventas.generar_cotizacion": svg([6, 3, 12, 18], <><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4" /><path d="M9.5 12.5h5M9.5 16h5" /><path d="M12 9v1.5" /></>),
  "ventas.agendar_seguimiento": svg([4, 4, 16, 16], <><circle cx="12" cy="12" r="8" /><path d="M12 7.5V12l3 2" /></>),
  "ventas.registrar_oportunidad": svg([2, 5, 20, 14], <><path d="M4 19V11M10 19V5M16 19v-6M22 19H2" /></>),
  // Recepción
  "recepcion.consultar_agenda": svg([4, 3, 16, 17], <><rect x="4" y="5" width="16" height="15" rx="2" /><path d="M4 9h16M8 3v4M16 3v4" /></>),
  "recepcion.buscar_cita": svg([4.5, 4.5, 15.5, 15.5], <><circle cx="11" cy="11" r="6.5" /><path d="M16 16l4 4" /></>),
  "recepcion.agendar_cita": svg([4, 3, 16, 17], <><rect x="4" y="5" width="16" height="15" rx="2" /><path d="M4 9h16M8 3v4M16 3v4M12 12v5M9.5 14.5h5" /></>),
  "recepcion.buscar_en_kb": svg([6, 4, 13, 16], <><path d="M6 4h9l4 4v12H6z" /><path d="M14 4v4h4" /><path d="M12 11v4M10 13h4" /></>),
  "recepcion.escalar_a_humano": svg([3.5, 5, 17.5, 14], <><circle cx="9" cy="8" r="3" /><path d="M3.5 19a5.5 5.5 0 0 1 11 0" /><path d="M16 8h5M18.5 5.5 21 8l-2.5 2.5" /></>),
};

// Por tipo (fallback expresivo): consulta = lupa, actúa = lápiz, envía = avión.
const BY_TIPO: Record<string, ReactNode> = {
  consulta: svg([4.5, 4.5, 15.5, 15.5], <><circle cx="11" cy="11" r="6.5" /><path d="M16 16l4 4" /></>),
  actua: svg([4, 4.5, 15.5, 15.5], <><path d="M14.5 4.5 19.5 9.5 9 20H4v-5z" /><path d="M13 6 18 11" /></>),
  envia: svg([3.5, 4.5, 16.5, 15], <><path d="M3.5 11.5 20 4.5l-5 15-4-6-7-2z" /><path d="M11 13.5 20 4.5" /></>),
};

/** Tipo de la aiudita: qué tan "atrevida" es, para el color y la etiqueta. */
export type AiuditaTipo = "consulta" | "actua" | "envia";

export function aiuditaTipo(id: string, lectura: boolean): AiuditaTipo {
  if (id.includes("enviar") || id.includes("publicar") || id.includes("programar")) return "envia";
  return lectura ? "consulta" : "actua";
}

export const TIPO_META: Record<AiuditaTipo, { label: string; tone: string; soft: string; ink: string }> = {
  // tone = punto/realce; soft = fondo del círculo; ink = color del icono y la etiqueta
  consulta: { label: "Consulta", tone: "var(--color-ink-3)", soft: "var(--color-panel)", ink: "var(--color-ink-2)" },
  actua: { label: "Actúa", tone: "var(--color-accent)", soft: "var(--color-accent-soft)", ink: "var(--color-accent-ink)" },
  envia: { label: "Envía", tone: "var(--color-warn)", soft: "var(--color-warn-soft)", ink: "var(--color-warn)" },
};

export function AiuditaIcon({ id, tipo, className = "" }: { id: string; tipo: AiuditaTipo; className?: string }) {
  return (
    <span aria-hidden className={`inline-flex shrink-0 items-center justify-center ${className}`}>
      {BY_ID[id] ?? BY_TIPO[tipo]}
    </span>
  );
}
