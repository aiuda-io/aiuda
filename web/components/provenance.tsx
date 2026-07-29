// Barra de procedencia: de dónde salen los datos de un registro y quién manda.
//
// El principio de aiuda: tus fuentes (Odoo, Excel, tu tienda) son el maestro; aiuda actúa
// encima. Este badge lo hace explícito en cada registro: si vive en un sistema externo, es un
// ESPEJO (los datos maestros mandan allá, con liga directa a la fuente); si no, nació en aiuda
// y aiuda es la fuente. Se usa igual en clientes, facturas y productos.

import { fechaDM } from "@/lib/format";
import { SOURCE_LABEL } from "@/components/ui";

type Presence = Record<string, { ref?: string; url?: string; file?: string; at?: string }>;

export function fuenteEspejo(presence?: Presence | null): string | null {
  const systems = presence ? Object.keys(presence) : [];
  return systems[0] ?? null;
}

export function espejoLiga(presence?: Presence | null): string | null {
  const src = fuenteEspejo(presence);
  return src ? (presence?.[src]?.url ?? null) : null;
}

export function ProvenanceBar({
  presence,
  nativeLabel = "Registro nativo de aiuda",
  nativeHint = "lo creaste aquí; aiuda es la fuente",
  masterHint = "los datos maestros viven allá",
}: {
  presence?: Presence | null;
  nativeLabel?: string;
  nativeHint?: string;
  masterHint?: string;
}) {
  const src = fuenteEspejo(presence);
  const info = src ? (presence?.[src] ?? {}) : {};
  const label = src ? (SOURCE_LABEL[src] ?? src) : "";
  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded-lg border border-line bg-panel/50 px-3.5 py-2 text-[12px]">
      {src ? (
        <>
          <span className="flex items-center gap-1.5 font-medium text-ink-2">
            <span className="h-1.5 w-1.5 rounded-full bg-accent" />
            Espejo de {label}
          </span>
          <span className="text-ink-3">
            {masterHint}
            {info.at ? ` · sincronizado ${fechaDM(info.at)}` : ""}
            {info.file ? ` · ${info.file}` : ""}
          </span>
          {info.url && (
            <a
              href={info.url}
              target="_blank"
              rel="noreferrer"
              className="ml-auto shrink-0 font-medium text-accent-ink underline-offset-2 hover:underline"
            >
              Abrir en {label} ↗
            </a>
          )}
        </>
      ) : (
        <span className="flex flex-wrap items-center gap-1.5 text-ink-3">
          <span className="h-1.5 w-1.5 rounded-full bg-ok" />
          <span className="font-medium text-ink-2">{nativeLabel}</span>
          {nativeHint}
        </span>
      )}
    </div>
  );
}
