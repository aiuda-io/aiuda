import { IrAHoy } from "@/components/hoy/ir-a-hoy";

// Aprobar vive en Hoy (/). La ruta se queda como redirección para no romper ligas
// viejas ni marcadores.
export default function AprobacionesRedirect() {
  return <IrAHoy />;
}
