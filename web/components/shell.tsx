"use client";

import { Sidebar } from "@/components/sidebar";
import { Topbar } from "@/components/topbar";
import { CommandPalette } from "@/components/command-palette";
import { ShadowBanner } from "@/components/shadow-banner";
import { Toaster } from "@/components/toast";
import { SetupWizard } from "@/components/setup-wizard";
import { RastroProvider, RastroBack, PageTransition } from "@/components/rastro";

export function Shell({ children }: { children: React.ReactNode }) {
  // Una sola bienvenida: el asistente de primer arranque. El tour con spotlight
  // y la checklist flotante se retiraron — tres onboardings encimados es ruido,
  // y lo que falta ya se ve en "Primeros pasos" del Resumen.
  return (
    <RastroProvider>
      <div className="flex min-h-screen">
        <Toaster />
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <ShadowBanner />
          <Topbar />
          <CommandPalette />
          <main className="min-w-0 flex-1 px-8 py-7">
            <RastroBack className="mb-4" />
            <PageTransition>{children}</PageTransition>
          </main>
        </div>
      </div>
      <SetupWizard />
    </RastroProvider>
  );
}
