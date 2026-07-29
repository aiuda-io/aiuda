"use client";

import Link from "next/link";
import { PageHeader } from "@/components/ui";
import { SettingsPage, SettingsSection } from "@/components/settings";
import { ExcelUpload } from "@/components/excel-upload";
import { BancoUpload } from "@/components/banco-upload";

const TIPOS = [
  { label: "Clientes", desc: "Nombre, WhatsApp, correo", href: "/clientes" },
  { label: "Prospectos", desc: "Posibles clientes a contactar", href: "/prospectos" },
  { label: "Productos", desc: "Catálogo: precio, existencia, SKU", href: "/productos" },
  { label: "Facturas", desc: "Cartera: folio, monto, vencimiento", href: "/facturas" },
  { label: "Citas", desc: "Agenda: asunto, cliente, fecha", href: "/citas" },
];

export default function ImportarPage() {
  return (
    <SettingsPage>
      <PageHeader
        title="Importar tus datos"
        subtitle="Sube tus archivos tal como los llevas: hojas de Excel o el estado de cuenta de tu banco. La IA detecta qué son y los carga al lugar correcto."
      />

      <div className="mt-2">
        <SettingsSection
          title="Sube tu Excel"
          desc="Arrastra tu Excel o CSV tal como lo llevas. La IA lee las columnas y lo manda al lugar correcto."
        >
          <div className="rounded-lg border border-line bg-surface">
            <ExcelUpload className="px-5 py-5" />
          </div>
        </SettingsSection>

        <SettingsSection
          title="Estado de cuenta bancario (PDF)"
          desc="El PDF que te manda tu banco cada mes. BBVA y Banorte se leen directo; cualquier otro banco lo lee tu IA. Los depósitos entran a conciliación tras tu visto bueno."
        >
          <div className="rounded-lg border border-line bg-surface">
            <BancoUpload className="px-5 py-5" />
          </div>
          <p className="mt-2 text-[11.5px] leading-relaxed text-ink-3">
            Los depósitos aparecen en{" "}
            <Link href="/conciliacion" className="text-accent-ink underline-offset-2 hover:underline">
              Conciliación
            </Link>
            , donde tu ayudante propone qué factura liquida cada uno y tú confirmas.
          </p>
        </SettingsSection>

        <SettingsSection
          title="La IA reconoce estos tipos"
          desc="Al leer tu hoja, la IA identifica de qué es y la carga al módulo que le toca."
        >
          <div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {TIPOS.map((t) => (
                <Link
                  key={t.label}
                  href={t.href}
                  className="rounded-lg border border-line bg-surface px-4 py-3 transition-colors hover:border-line-strong"
                >
                  <p className="text-[12.5px] font-medium text-ink">{t.label}</p>
                  <p className="mt-0.5 text-[11.5px] text-ink-3">{t.desc}</p>
                </Link>
              ))}
            </div>
            <p className="mt-3 text-[11.5px] leading-relaxed text-ink-3">
              Re-subir el mismo archivo no duplica: actualiza lo que ya existe. Más adelante, lo
              mismo entra solo desde tus integraciones (Odoo, tu tienda, Stripe).
            </p>
          </div>
        </SettingsSection>
      </div>
    </SettingsPage>
  );
}
