"use client";

import { Suspense } from "react";
import { Hoy } from "@/components/hoy/hoy";

// El inicio ES la pantalla de trabajo. `Hoy` lee `?r=` (liga directa a un mensaje),
// y en el export estático `useSearchParams` exige un límite de Suspense.
export default function HoyPage() {
  return (
    <Suspense fallback={null}>
      <Hoy />
    </Suspense>
  );
}
