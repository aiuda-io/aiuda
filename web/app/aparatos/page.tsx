import { Redireccion } from "@/components/ajustes/redireccion";
import { rutaAjustes } from "@/lib/ajustes-api";

// Tus aparatos es ahora Ajustes > Teléfono y equipo.
export default function AparatosRedirect() {
  return <Redireccion a={rutaAjustes("telefono")} />;
}
