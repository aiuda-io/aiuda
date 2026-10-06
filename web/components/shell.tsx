"use client";

import { Sidebar } from "@/components/sidebar";
import { Topbar } from "@/components/topbar";
import { CommandPalette } from "@/components/command-palette";
import { ShadowBanner } from "@/components/shadow-banner";
import { Toaster } from "@/components/toast";
import { SetupWizard } from "@/components/setup-wizard";
import { RastroProvider, RastroBack, PageTransition } from "@/components/rastro";

/** EL ancho del contenido, y el único. 1120px de contenido útil más el margen
 *  lateral (20 en teléfono, 32 en tableta, 40 en escritorio), centrado en lo que
 *  deja libre el menú. Ninguna pantalla define su propio ancho máximo de página:
 *  hereda este. Adentro sí puede acotar un bloque de lectura (`max-w-xl` en un
 *  párrafo), pero no la página. La barra superior usa el mismo contenedor, para
 *  que sus bordes y los del contenido caigan en la misma vertical. */
const ANCHO_CONTENIDO = "mx-auto w-full max-w-[1200px] px-5 sm:px-8 lg:px-10";

export function Shell({ children }: { children: React.ReactNode }) {
  // Una sola bienvenida: el asistente de primer arranque.
  return (
    <RastroProvider>
      {/* La franja del modo de prueba va por encima de todo el marco, de lado a
          lado. `.marco` le avisa al menú cuánto bajar cuando está (globals.css). */}
      <div className="marco flex min-h-screen flex-col">
        <ShadowBanner />
        <div className="flex min-w-0 flex-1">
          <Toaster />
          <Sidebar />
          <div className="flex min-w-0 flex-1 flex-col">
            <div className={ANCHO_CONTENIDO}>
              <Topbar />
            </div>
            <CommandPalette />
            <main className={`${ANCHO_CONTENIDO} min-w-0 flex-1 pb-16 pt-6 lg:pb-24 lg:pt-10`}>
              <RastroBack className="mb-6" />
              <PageTransition>{children}</PageTransition>
            </main>
          </div>
        </div>
      </div>
      <SetupWizard />
    </RastroProvider>
  );
}
