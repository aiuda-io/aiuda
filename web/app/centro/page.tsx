import { IrAHoy } from "@/components/hoy/ir-a-hoy";

// El Centro de mando se fundió en Hoy (/). La ruta se queda como redirección para
// no romper ligas viejas ni marcadores.
export default function CentroRedirect() {
  return <IrAHoy />;
}
