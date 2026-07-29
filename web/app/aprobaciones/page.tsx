import { redirect } from "next/navigation";

// Consolidado en el Centro de mando: una sola puerta para aprobar/rechazar/corregir.
// Se mantiene la ruta como redirección para no romper enlaces viejos o marcadores.
export default function AprobacionesRedirect() {
  redirect("/centro");
}
