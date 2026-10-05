"use client";

// Importar no está en el menú: se llega desde Cartera ("Importar Excel"), desde
// Conexiones y desde Cartera > Pagos (estado de cuenta). Por eso trae su regreso.

import Link from "next/link";
import { PageHeader } from "@/components/ui";
import { SettingsPage, SettingsSection } from "@/components/settings";
import { ExcelUpload } from "@/components/excel-upload";
import { BancoUpload } from "@/components/banco-upload";
import { RegresoACartera } from "@/components/cartera-partes";
import { RUTA } from "@/lib/cartera";

export default function ImportarPage() {
  return (
    <SettingsPage>
      <RegresoACartera />
      <PageHeader
        title="Importar"
        subtitle="Sube tus archivos tal como los llevas. Nada se carga sin que lo revises primero."
      />

      <SettingsSection
        title="Tu Excel"
        desc="Facturas, clientes, prospectos, productos o citas. Subir el mismo archivo otra vez no duplica nada: actualiza lo que ya estaba."
      >
        <ExcelUpload />
      </SettingsSection>

      <SettingsSection
        title="El estado de cuenta de tu banco"
        desc={
          <>
            El PDF que te manda tu banco cada mes. Los depósitos entran a{" "}
            <Link href={RUTA.pagos} className="font-medium text-accent-ink hover:underline">
              Cartera, en Pagos
            </Link>
            , donde confirmas a qué factura corresponde cada uno.
          </>
        }
      >
        <BancoUpload />
      </SettingsSection>
    </SettingsPage>
  );
}
