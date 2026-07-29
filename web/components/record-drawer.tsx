"use client";

import { type ReactNode } from "react";
import { Drawer } from "@/components/drawer";
import { ProvenanceBar } from "@/components/provenance";

type Field = { label: string; value: ReactNode };

/** Detalle genérico de un registro (producto, cita, etc.): sus campos + datos
 *  extra + de dónde viene. Cualquier registro es clickeable y abre esto. */
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
      <div className="space-y-5">
        <ProvenanceBar presence={presence} nativeLabel="Creado en aiuda" masterHint="vive allá" />
        <div className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg border border-line bg-surface p-4">
          {fields.map((f) => (
            <div key={f.label}>
              <p className="text-rotulo uppercase tracking-[0.06em] text-ink-3">{f.label}</p>
              <p className="mt-0.5 text-cuerpo text-ink">
                {f.value ?? <span className="text-ink-3">·</span>}
              </p>
            </div>
          ))}
        </div>

        {metaEntries.length > 0 && (
          <section>
            <h3 className="text-cuerpo font-semibold text-ink">Datos extra</h3>
            <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
              {metaEntries.map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3 text-cuerpo">
                  <dt className="text-ink-3">{k}</dt>
                  <dd className="font-medium text-ink">{v}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}

      </div>
    </Drawer>
  );
}
