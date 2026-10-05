"use client";

// La cara del ayudante: color, rasgos por capas y un símbolo. Se ve el resultado al
// momento y se guarda con cada toque.
import { useState } from "react";
import { Avatar } from "@/components/avatar";
import { RoleIcon } from "@/components/role-icon";
import { SecondaryButton } from "@/components/ui";
import {
  ACCENT_COLORS,
  PART_KEYS,
  PART_META,
  SYMBOL_KEYS,
  type Appearance,
  type PartCategory,
} from "@/lib/look";

export function Apariencia({
  app,
  onChange,
}: {
  app: Appearance;
  onChange: (patch: Partial<Appearance>) => void;
}) {
  const [parte, setParte] = useState<string>("color");
  const partes: { key: string; label: string }[] = [
    { key: "color", label: "Color" },
    ...PART_META.map((p) => ({ key: p.cat, label: p.label })),
    { key: "symbol", label: "Símbolo" },
  ];

  const alAzar = () => {
    const pick = <T,>(a: readonly T[]): T => a[Math.floor(Math.random() * a.length)];
    onChange({
      color: Math.floor(Math.random() * ACCENT_COLORS.length),
      hair: pick(PART_KEYS.hair),
      eyes: pick(PART_KEYS.eyes),
      mouth: pick(PART_KEYS.mouth),
      hat: pick(PART_KEYS.hat),
      accessory: pick(PART_KEYS.accessory),
      symbol: pick(SYMBOL_KEYS),
    });
  };

  const opcion = (on: boolean) =>
    `flex h-11 w-11 items-center justify-center rounded-lg ${on ? "bg-accent-soft text-accent-ink" : "bg-fill text-ink-2 hover:bg-fill-strong"}`;

  return (
    <section className="max-w-2xl">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-seccion font-semibold text-ink">Su cara</h2>
        <SecondaryButton size="sm" onClick={alAzar}>
          Al azar
        </SecondaryButton>
      </div>

      <div className="flex flex-wrap items-start gap-6">
        <Avatar size={88} {...app} className="shrink-0" />
        <div className="min-w-0 flex-1 basis-72">
          <div role="tablist" className="flex flex-wrap gap-1.5">
            {partes.map((t) => (
              <button
                key={t.key}
                role="tab"
                aria-selected={parte === t.key}
                onClick={() => setParte(t.key)}
                className={`btn btn-sm ${parte === t.key ? "bg-accent-soft text-accent-ink" : "btn-quiet"}`}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            {parte === "color"
              ? ACCENT_COLORS.map((c, i) => (
                  <button
                    key={c}
                    onClick={() => onChange({ color: i })}
                    aria-label={`Color ${i + 1}`}
                    aria-pressed={app.color === i}
                    className="h-9 w-9 rounded-full"
                    style={{
                      background: c,
                      boxShadow: app.color === i ? `0 0 0 2px var(--color-bg), 0 0 0 4px ${c}` : undefined,
                    }}
                  />
                ))
              : parte === "symbol"
                ? SYMBOL_KEYS.map((s) => (
                    <button
                      key={s}
                      onClick={() => onChange({ symbol: s })}
                      aria-label={`Símbolo ${s}`}
                      aria-pressed={app.symbol === s}
                      className={opcion(app.symbol === s)}
                    >
                      <RoleIcon symbol={s} className="h-5 w-5" />
                    </button>
                  ))
                : PART_KEYS[parte as PartCategory].map((opt) => (
                    <button
                      key={opt}
                      onClick={() => onChange({ [parte]: opt } as Partial<Appearance>)}
                      aria-label={`${parte}: ${opt}`}
                      aria-pressed={app[parte as PartCategory] === opt}
                      className={opcion(app[parte as PartCategory] === opt)}
                    >
                      <Avatar size={30} {...{ ...app, [parte]: opt }} />
                    </button>
                  ))}
          </div>
        </div>
      </div>
    </section>
  );
}
