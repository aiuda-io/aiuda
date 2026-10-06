"use client";

/**
 * Ajustes: una sola página con cuatro secciones, por query.
 *
 *   /configuracion                      Negocio (la de entrada)
 *   /configuracion?seccion=conexiones   Conexiones (&abrir=odoo abre ese panel)
 *   /configuracion?seccion=ia           Tu IA
 *   /configuracion?seccion=telefono     Teléfono y equipo
 *
 * Antes eran cuatro destinos del menú (Configuración, Integraciones, Tu IA, Tus
 * aparatos). Sus rutas viejas siguen vivas como redirecciones a su sección.
 */

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { PageHeader, Tabs, useApi, useQueryTab } from "@/components/ui";
import { api } from "@/lib/api";
import { AjustesNegocio } from "@/components/ajustes/negocio";
import { AjustesConexiones } from "@/components/ajustes/conexiones";
import { AjustesIA } from "@/components/ajustes/tu-ia";
import { AjustesTelefono } from "@/components/ajustes/telefono";
import { SECCIONES, rutaAjustes, type Seccion } from "@/lib/ajustes";

const CLAVES = SECCIONES.map((s) => s.key);

export default function AjustesPage() {
  // useSearchParams exige un límite de Suspense en el export estático.
  return (
    <Suspense fallback={<div className="min-w-0" />}>
      <Ajustes />
    </Suspense>
  );
}

function Ajustes() {
  const params = useSearchParams();
  const [seccion] = useQueryTab<Seccion>("seccion", CLAVES);
  const abrir = seccion === "conexiones" ? params.get("abrir") : null;

  return (
    <div className="min-w-0">
      <PageHeader title="Ajustes" />

      <Tabs
        tabs={SECCIONES.map((s) => ({ key: s.key, label: s.label }))}
        active={seccion}
        // Cambiar de sección no arrastra el panel abierto (`abrir`) de la anterior.
        hrefFor={(k) => rutaAjustes(k as Seccion)}
        label="Secciones de Ajustes"
      />

      {seccion === "negocio" && <AjustesNegocio />}
      {seccion === "conexiones" && (
        <AjustesConexiones
          abrir={abrir}
          // Solo cambia la dirección (se va `abrir`), sin navegar: Next sincroniza
          // useSearchParams con history.replaceState.
          onCerrarPanel={() => window.history.replaceState(null, "", rutaAjustes("conexiones"))}
        />
      )}
      {seccion === "ia" && <AjustesIA />}
      {seccion === "telefono" && <AjustesTelefono />}

      <PieDeAjustes />
    </div>
  );
}

/** Que aiuda corre en esta computadora, su versión y el crédito: se dice una vez,
 *  al fondo de Ajustes, y no en el marco de cada pantalla. */
function PieDeAjustes() {
  const { data } = useApi(() => api.workspace(), []);
  return (
    <footer className="mt-16 border-t border-line pt-6 text-apoyo leading-relaxed text-ink-3">
      <p>
        Todo vive en esta Mac: tus datos, tus credenciales y lo que hacen tus ayudantes. No hay
        cuentas ni nube.
      </p>
      <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
        <a
          href="https://hanova.mx"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-2 hover:text-ink"
        >
          <img src="/brand/hanova-icon-blue.svg" alt="" className="h-3 w-3 opacity-60 grayscale" />
          Un proyecto de Hanova Consulting
        </a>
        {data?.version && <span className="tnum">aiuda {data.version}</span>}
        <a href="/manual/" className="hover:text-ink">
          Manual
        </a>
      </p>
    </footer>
  );
}
