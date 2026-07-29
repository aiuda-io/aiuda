import { redirect } from "next/navigation";

// El mapa de burbujas se reemplazó por el organigrama dentro de Integraciones. Se mantiene la
// ruta como redirección para no romper enlaces viejos o marcadores.
export default function MapaRedirect() {
  redirect("/integraciones?vista=organigrama");
}
