"use client";

import { type ReactNode } from "react";
import { Drawer } from "@/components/drawer";
import { ProvenanceBar } from "@/components/provenance";

type Field = { label: string; value: ReactNode };

/** El detalle de un producto o de una cita: sus datos, lo demás que traía tu
 *  archivo y de dónde viene. */
export function RecordDrawer({
  open,
  onClose,
  title,
  subtitle,
  fields,
  meta,
  presence,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  fields: Field[];
  meta?: Record<string, string>;
  presence?: Record<string, { file?: string; at?: string; ref?: string; url?: string }>;
}) {
  const metaEntries = Object.entries(meta ?? {});
  return (
    <Drawer open={open} onClose={onClose} title={title} subtitle={subtitle}>
      <div className="space-y-8">
        <ProvenanceBar presence={presence} nativeLabel="Dado de alta en aiuda" masterHint="vive allá" />
        <dl className="grid grid-cols-2 gap-x-6 gap-y-5">
          {fields.map((f) => (
            <div key={f.label} className="min-w-0">
              <dt className="text-rotulo text-ink-3">{f.label}</dt>
              <dd className="mt-1 break-words text-cuerpo text-ink">
                {f.value ?? <span className="text-ink-3">Sin dato</span>}
              </dd>
            </div>
          ))}
        </dl>

        {metaEntries.length > 0 && (
          <section>
            <h3 className="text-cuerpo font-semibold text-ink">Otros datos</h3>
            <dl className="mt-2">
              {metaEntries.map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4 border-b border-line py-2.5 text-cuerpo last:border-0">
                  <dt className="shrink-0 text-ink-3">{k}</dt>
                  <dd className="min-w-0 break-words text-right font-medium text-ink">{v}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}

      </div>
    </Drawer>
  );
}
