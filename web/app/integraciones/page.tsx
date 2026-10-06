import { Redireccion } from "@/components/ajustes/redireccion";
import { rutaAjustes } from "@/lib/ajustes";

// Integraciones es ahora Ajustes > Conexiones. La ruta se queda para no romper
// enlaces viejos ni marcadores.
export default function IntegracionesRedirect() {
  return <Redireccion a={rutaAjustes("conexiones")} />;
}
