"use client";

import { useCallback, useState } from "react";
import { api, type ModoPruebaCambio } from "@/lib/api";
import { Modal } from "@/components/modal";
import { PrimaryButton, QuietButton, SecondaryButton } from "@/components/ui";
import { toast } from "@/components/toast";

// Evento que se dispara al prender o apagar el modo de prueba, para que la franja y
// las pantallas se enteren sin recargar.
export const SHADOW_EVENT = "shadow-mode-changed";

export function avisarModoPrueba(activo: boolean) {
  window.dispatchEvent(new CustomEvent(SHADOW_EVENT, { detail: { activo } }));
}

/** Apagar el modo de prueba: UNA sola implementación, la usan la franja y Ajustes.
 *
 *  Apagarlo no es inocuo: lo que el dueño aprobó mientras estaba encendido se quedó
 *  esperando, y con el modo apagado saldría solo a clientes de verdad en la siguiente
 *  revisión. Por eso aquí siempre se pregunta antes: si hay algo aprobado sin salir,
 *  qué hacer con ello (mandarlo ya o no mandarlo); si no hay nada, solo se confirma.
 *
 *  Uso: `const { apagar, apagando, dialogo } = useApagarModoPrueba()` y pintar
 *  `{dialogo}` una vez. */
export function useApagarModoPrueba(alCambiar?: (res: ModoPruebaCambio) => void) {
  const [abierto, setAbierto] = useState(false);
  const [retenidos, setRetenidos] = useState(0);
  const [apagando, setApagando] = useState(false);

  const apagar = useCallback(async () => {
    // Se cuenta en este momento: lo aprobado pudo cambiar desde que cargó la pantalla.
    try {
      const estado = await api.shadowMode();
      setRetenidos(estado.modo_sombra ? (estado.retenidos ?? 0) : 0);
    } catch {
      toast("No se pudo consultar el modo de prueba. Intenta de nuevo.", "error");
      return;
    }
    setAbierto(true);
  }, []);

  async function confirmar(quehacer?: "enviar" | "no_enviar") {
    setApagando(true);
    try {
      const res = await api.setShadowMode(false, quehacer);
      avisarModoPrueba(res.modo_sombra);
      const n = res.retenidos;
      const cuantos = n === 1 ? "1 mensaje" : `${n} mensajes`;
      toast(
        res.retenidos_accion === "enviando"
          ? `Modo de prueba apagado. Se ${n === 1 ? "está mandando" : "están mandando"} ${cuantos}.`
          : res.retenidos_accion === "no_enviados"
            ? `Modo de prueba apagado. ${cuantos} ${n === 1 ? "quedó" : "quedaron"} sin mandar, en Hoy.`
            : "Modo de prueba apagado: lo que apruebes ya se envía.",
        "info",
      );
      setAbierto(false);
      alCambiar?.(res);
    } catch (e) {
      toast((e as Error).message || "No se pudo apagar. Intenta de nuevo.", "error");
    } finally {
      setApagando(false);
    }
  }

  const uno = retenidos === 1;
  const cerrar = () => {
    if (!apagando) setAbierto(false);
  };

  const dialogo = (
    <Modal
      open={abierto}
      onClose={cerrar}
      title={
        retenidos > 0
          ? `Tienes ${uno ? "1 mensaje aprobado" : `${retenidos} mensajes aprobados`} sin mandar`
          : "Apagar el modo de prueba"
      }
      size="sm"
    >
      {retenidos > 0 ? (
        <>
          <p className="text-cuerpo text-ink-2">
            {uno ? "Lo aprobaste" : "Los aprobaste"} en modo de prueba y por eso no{" "}
            {uno ? "salió" : "salieron"}. Si apagas el modo de prueba,{" "}
            {uno ? "puede irse a un cliente" : "pueden irse a clientes"} de verdad. Tú decides.
          </p>
          <p className="mt-3 text-cuerpo text-ink-2">
            Si no {uno ? "lo mandas, queda" : "los mandas, quedan"} en Hoy, en No salió, y puedes
            reintentar {uno ? "ese" : "el que quieras"}.
          </p>
          <div className="mt-6 flex flex-col gap-2">
            <PrimaryButton onClick={() => confirmar("enviar")} disabled={apagando}>
              {uno ? "Apagar y mandarlo ahora" : `Apagar y mandar los ${retenidos} ahora`}
            </PrimaryButton>
            <SecondaryButton onClick={() => confirmar("no_enviar")} disabled={apagando}>
              {uno ? "Apagar sin mandarlo" : "Apagar sin mandarlos"}
            </SecondaryButton>
            <QuietButton onClick={cerrar} disabled={apagando}>
              Dejarlo encendido
            </QuietButton>
          </div>
        </>
      ) : (
        <>
          <p className="text-cuerpo text-ink-2">
            Desde ahora, lo que apruebes sí se envía a tus clientes.
          </p>
          <div className="mt-6 flex justify-end gap-2">
            <QuietButton onClick={cerrar} disabled={apagando}>
              Dejarlo encendido
            </QuietButton>
            <PrimaryButton onClick={() => confirmar()} disabled={apagando}>
              {apagando ? "Apagando" : "Apagar"}
            </PrimaryButton>
          </div>
        </>
      )}
    </Modal>
  );

  return { apagar, apagando, dialogo };
}
