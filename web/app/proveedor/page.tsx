import { Redireccion } from "@/components/ajustes/redireccion";
import { rutaAjustes } from "@/lib/ajustes";

// Tu IA es ahora una sección de Ajustes. La ruta se queda para no romper enlaces
// viejos (los avisos de "falta conectar tu IA" de otras pantallas apuntan aquí).
export default function ProveedorRedirect() {
  return <Redireccion a={rutaAjustes("ia")} />;
}
