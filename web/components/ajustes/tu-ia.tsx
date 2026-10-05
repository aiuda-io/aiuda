"use client";

import { SettingsSection } from "@/components/settings";
import { AdministrarUso } from "@/components/chatgpt";
import { ConectarIA } from "@/components/ajustes/conectar-ia";

/** Ajustes > Tu IA: la vía recomendada para esta Mac, las demás en la misma
 *  pantalla, y al final qué se paga y a quién. */
export function AjustesIA() {
  return (
    <div>
      <p className="mb-8 max-w-2xl text-cuerpo leading-relaxed text-ink-2">
        Es lo que redacta, lee y propone por tus ayudantes. La pagas directo a quien la hace, o la
        corres gratis en esta computadora: aiuda no cobra por el uso ni revende nada.
      </p>

      <ConectarIA />

      <div className="mt-12">
        <SettingsSection title="Qué se paga y a quién" desc="Para que no haya sorpresas.">
          <div className="max-w-[62ch] space-y-4 text-cuerpo leading-relaxed text-ink-2">
            <p>
              <strong className="font-semibold text-ink">
                aiuda no cobra por el uso de la IA ni la revende.
              </strong>{" "}
              Le pagas directo a quien la hace, o no le pagas a nadie si corres un modelo en esta
              computadora.
            </p>
            <p>
              Si usas el programa que ya tienes instalado, ocupa la cuenta con la que ya entraste
              ahí, igual que cuando lo abres tú. aiuda lo lanza y lee su respuesta: nunca ve ni
              guarda tu contraseña.
            </p>
            <p>
              Si entras con ChatGPT, tus ayudantes gastan del plan de ChatGPT que ya pagas, no de
              una factura aparte. Es el mismo cupo que usas tú: si tus ayudantes trabajan mucho, a
              ti te queda menos. El límite que le quieras poner a aiuda se fija en la configuración
              de ChatGPT, en <AdministrarUso />.
            </p>
          </div>
        </SettingsSection>
      </div>
    </div>
  );
}
