// Ayuda "Cómo conectar" para cada integración de la consola.
// Se renderiza dentro del drawer de configuración de la integración.
// Una entrada por cada key del catálogo (server/aiuda_server/api/integrations.py).

export type IntegrationHelp = {
  intro: string; // 1 oración: qué hace / por qué conectarla
  steps: string[]; // pasos concretos para conectar desde la consola (3-6 pasos)
  credentials: { field: string; where: string }[]; // por cada credencial: dónde obtenerla
};

export const INTEGRATION_HELP: Record<string, IntegrationHelp> = {
  whatsapp: {
    intro:
      "Tu número de siempre, conectado como una sesión más de WhatsApp Web (no es la API oficial). Para el uso normal el riesgo es bajo; si algún día envías a volumen, conecta WhatsApp Business (oficial).",
    steps: [
      "En este panel pícale Mostrar código QR.",
      "Abre WhatsApp en tu teléfono.",
      "Ve a Ajustes > Dispositivos vinculados > Vincular un dispositivo.",
      "Apunta la cámara al código que aparece en la consola.",
      "En cuanto el teléfono escanea, la consola se actualiza sola a WhatsApp conectado.",
    ],
    credentials: [],
  },

  whatsapp_cloud: {
    intro:
      "La API oficial de WhatsApp Business (Cloud API de Meta), pensada para volumen y dentro de los Términos de Meta. Requiere plantillas aprobadas fuera de la ventana de 24 horas y un servidor con URL pública para recibir webhooks (no aplica corriendo solo local).",
    steps: [
      "Crea una app en developers.facebook.com y agrégale el producto WhatsApp.",
      "Registra o migra el número del negocio en el WhatsApp Manager (no puede estar activo en la app normal de WhatsApp).",
      "Genera un token permanente con un usuario de sistema (Business Settings > Usuarios del sistema) con permiso whatsapp_business_messaging.",
      "Copia el ID del número de teléfono (API Setup) y pégalo junto con el token aquí.",
      "Registra una plantilla de recordatorio de pago y, cuando Meta la apruebe, captura su nombre e idioma.",
      "Pícale Conectar, luego Probar conexión (verifica contra Meta) y por último Usar como mi canal.",
    ],
    credentials: [
      {
        field: "Token de acceso",
        where:
          "Meta Business Settings > Usuarios del sistema > Generar token (permanente). El token temporal del panel de la app caduca en 24 horas.",
      },
      {
        field: "ID del número de teléfono",
        where: "developers.facebook.com > tu app > WhatsApp > API Setup (campo Phone number ID).",
      },
      {
        field: "Plantilla aprobada",
        where:
          "WhatsApp Manager > Plantillas de mensajes. Crea una de categoría Utility para recordatorios de pago y espera la aprobación de Meta.",
      },
    ],
  },

  email: {
    intro:
      "Conecta el correo del negocio (IMAP genérico, Gmail o Outlook): los correos de tus clientes entran como hilos a la bandeja, tu ayudante propone la respuesta y tú apruebas antes de que salga. La vía completa HOY es contraseña de aplicación; entrar con OAuth (botón de Google/Microsoft) está documentado y por cablear.",
    steps: [
      "Elige tu proveedor: IMAP genérico, Gmail o Outlook. Gmail y Outlook rellenan los servidores solos.",
      "En Gmail o Outlook activa la verificación en dos pasos y genera una contraseña de aplicación (no uses tu contraseña normal).",
      "Con IMAP genérico, pon los servidores IMAP (entrada) y SMTP (salida) que te dé tu proveedor. Sin SMTP se puede leer, pero no responder.",
      "Escribe tu correo y pega la contraseña de aplicación.",
      "Pícale Conectar y luego Probar conexión: verifica que entra (IMAP) y que puede enviar (SMTP), sin mandar nada.",
    ],
    credentials: [
      {
        field: "Contraseña de aplicación",
        where:
          "Gmail: myaccount.google.com > Seguridad > Contraseñas de aplicaciones. Outlook: account.microsoft.com > Seguridad. Con IMAP genérico, la contraseña que use tu correo.",
      },
      {
        field: "Servidor IMAP / SMTP",
        where:
          "Gmail: imap.gmail.com:993 y smtp.gmail.com:465. Outlook: outlook.office365.com:993 y smtp.office365.com:587. Otro: revisa la ayuda de tu proveedor.",
      },
      {
        field: "OAuth (Google / Microsoft)",
        where:
          "Aún no está cableado: exige registrar una app OAuth (scope de correo en Google Cloud / permisos IMAP+SMTP en Microsoft Entra) e intercambiar tokens XOAUTH2. La credencial ya guarda esos campos cifrados; cuando se cablee, entrarás sin contraseña de aplicación.",
      },
    ],
  },

  slack: {
    intro:
      "Publica en tu canal de Slack los avisos que aiuda ya genera: el resumen diario de cartera y el aviso cuando la IA se pausa por tope.",
    steps: [
      "Pídele a un administrador del workspace que cree una app de Slack (api.slack.com) con el scope chat:write.",
      "Instala la app en el workspace y copia el bot token (empieza con xoxb-).",
      "Invita al bot al canal donde quieres los avisos: /invite @aiuda en ese canal.",
      "Pega el bot token y el canal (p.ej. #cobranza) abajo, y pícale Conectar.",
      "Pícale Probar conexión: verifica el token contra Slack (auth.test) sin publicar nada.",
    ],
    credentials: [
      {
        field: "Bot token (xoxb-…)",
        where:
          "api.slack.com: un administrador crea una app de Slack, le da el scope chat:write, la instala en el workspace y copia el bot token (empieza con xoxb-).",
      },
      {
        field: "Canal de avisos",
        where:
          "El canal de tu workspace donde quieres los avisos (p.ej. #cobranza). El bot debe estar invitado a ese canal (/invite @aiuda).",
      },
    ],
  },

  excel: {
    intro:
      "Subes tu archivo tal como lo llevas y aiuda detecta qué es (clientes, productos, facturas, citas o prospectos) y entiende cada columna sin que cambies nada.",
    steps: [
      "Excel y CSV no necesitan credenciales ni esta tarjeta.",
      "Entra a la pantalla de Importar.",
      "Sube cualquier hoja: la IA detecta el tipo y la carga al lugar correcto.",
      "Re-subir el mismo archivo no duplica: aiuda reconoce lo que ya tenía.",
    ],
    credentials: [],
  },

  odoo: {
    intro:
      "Lee tus facturas de cliente con saldo y regresa lo que registra al chatter de cada factura en Odoo.",
    steps: [
      "Crea o usa un usuario de Odoo con permiso de leer facturas y dejar mensajes.",
      "Genera una API key para ese usuario en sus preferencias.",
      "Llena URL, base de datos, usuario y la API key abajo.",
      "Pícale Conectar.",
    ],
    credentials: [
      {
        field: "URL de Odoo",
        where: "La dirección de tu Odoo, por ejemplo https://miempresa.odoo.com.",
      },
      {
        field: "Base de datos",
        where: "El nombre de tu base de datos en Odoo, por ejemplo miempresa.",
      },
      {
        field: "Usuario",
        where:
          "El correo del usuario de API en tu Odoo, con permiso de leer facturas y dejar mensajes.",
      },
      {
        field: "API key o contraseña",
        where:
          "Genera una API key en las preferencias de ese usuario en tu Odoo (mejor que la contraseña). Funciona con Odoo v14 o más nuevo.",
      },
    ],
  },

  shopify: {
    intro:
      "Trae los pedidos pendientes de pago de tu tienda y deja la nota de la gestión en cada pedido.",
    steps: [
      "En el admin de Shopify ve a Settings > Apps and sales channels > Develop apps.",
      "Crea una Custom App y dale permiso de leer pedidos.",
      "Copia el Admin API access token.",
      "Llena el dominio de la tienda y el access token abajo, y pícale Conectar.",
    ],
    credentials: [
      {
        field: "Dominio de la tienda",
        where: "Tu dominio de Shopify, por ejemplo mitienda.myshopify.com.",
      },
      {
        field: "Access token",
        where:
          "Admin de Shopify > Settings > Apps and sales channels > Develop apps: crea una Custom App con permiso de leer pedidos y copia el Admin API access token.",
      },
    ],
  },

  woocommerce: {
    intro:
      "Trae los pedidos pendientes de pago de tu tienda en WordPress (estados pendiente y en espera) y los suma a tu cartera.",
    steps: [
      "En el wp-admin de tu WordPress ve a WooCommerce > Ajustes > Avanzado > REST API.",
      "Genera una clave con permiso de lectura.",
      "Copia el consumer key y el consumer secret.",
      "Llena la URL de la tienda y las dos llaves abajo, y pícale Conectar.",
    ],
    credentials: [
      {
        field: "URL de la tienda",
        where: "La dirección de tu tienda, por ejemplo https://mitienda.mx.",
      },
      {
        field: "Consumer key",
        where:
          "wp-admin > WooCommerce > Ajustes > Avanzado > REST API: genera una clave de lectura y copia el consumer key.",
      },
      {
        field: "Consumer secret",
        where:
          "wp-admin > WooCommerce > Ajustes > Avanzado > REST API: la llave secreta que aparece junto al consumer key al generar la clave.",
      },
    ],
  },

  belvo: {
    intro:
      "Conecta tu banco (open banking) y confirma pagos viendo los depósitos que entraron a tus cuentas.",
    steps: [
      "Entra a tu dashboard de Belvo (developers.belvo.com).",
      "Genera tus llaves de API (Secret ID y Secret password).",
      "Crea el link a la cuenta de tu banco y copia su Link ID.",
      "Llena los tres campos abajo y pícale Conectar.",
    ],
    credentials: [
      {
        field: "Link ID",
        where:
          "developers.belvo.com: el identificador del link que creas a la cuenta de tu banco en el dashboard de Belvo.",
      },
      {
        field: "Secret ID",
        where:
          "developers.belvo.com: el identificador de tu llave de API en el dashboard de Belvo.",
      },
      {
        field: "Secret password",
        where:
          "developers.belvo.com: la contraseña de esa llave de API, que ves al generarla. Por defecto trabaja en modo sandbox.",
      },
    ],
  },

  stripe: {
    intro:
      "Confirma cobros con tarjeta detectando los pagos que ya se liquidaron en tu cuenta de Stripe.",
    steps: [
      "Entra al dashboard de Stripe.",
      "Ve a Developers > API keys.",
      "Copia tu Secret key (sk_live_ en producción o sk_test_ para pruebas).",
      "Pega la Secret key abajo y pícale Conectar.",
    ],
    credentials: [
      {
        field: "Secret key (sk_…)",
        where:
          "Dashboard de Stripe > Developers > API keys: copia tu Secret key (empieza con sk_live_ en producción o sk_test_ para pruebas).",
      },
    ],
  },

  facturama: {
    intro:
      "PAC para timbrar y consultar tus CFDI ante el SAT, para que tu cartera tenga respaldo fiscal.",
    steps: [
      "Necesitas una cuenta de Facturama (solo uno: Facturama o Facturapi).",
      "Toma tu usuario y contraseña de Facturama.",
      "Llena usuario y contraseña abajo.",
      "Pícale Conectar.",
    ],
    credentials: [
      {
        field: "Usuario",
        where: "Tu usuario de Facturama, de tu cuenta en apisandbox.facturama.mx.",
      },
      {
        field: "Contraseña",
        where:
          "Tu contraseña de Facturama, de tu cuenta en apisandbox.facturama.mx. Por defecto trabaja en modo sandbox.",
      },
    ],
  },

  facturapi: {
    intro:
      "PAC para timbrar y consultar tus CFDI ante el SAT (la otra opción a Facturama; eliges uno).",
    steps: [
      "Necesitas una cuenta de Facturapi (solo uno: Facturapi o Facturama).",
      "Entra al dashboard de Facturapi y copia tu API key.",
      "Pega la API key abajo (sk_test_ para pruebas o la de producción para timbrar en vivo).",
      "Pícale Conectar.",
    ],
    credentials: [
      {
        field: "API key (sk_…)",
        where:
          "Dashboard de Facturapi (docs.facturapi.io): copia tu API key (sk_test_ para pruebas en sandbox, o la de producción para timbrar en vivo).",
      },
    ],
  },

  googlecalendar: {
    intro:
      "Lee tu disponibilidad real para agendar citas y recordatorios sin encimarse con algo que ya tienes.",
    steps: [
      "Consigue un token de acceso de Google: del consentimiento de tu cuenta o de una service account de Google Cloud.",
      "En Google Calendar, abre los ajustes del calendario y copia su Calendar ID (o usa primary para el principal).",
      "Llena el token y el Calendar ID abajo.",
      "Pícale Conectar.",
    ],
    credentials: [
      {
        field: "Token o service account",
        where:
          "Token de acceso de Google: del consentimiento de la cuenta del negocio o de una service account de Google Cloud.",
      },
      {
        field: "Calendar ID",
        where:
          "En Google Calendar, ajustes del calendario > Integrar el calendario: copia el ID del calendario. Usa primary para el principal.",
      },
    ],
  },

  hubspot: {
    intro:
      "Lee tus contactos y oportunidades del CRM y registra los prospectos nuevos sin capturar a mano.",
    steps: [
      "En HubSpot ve a Settings > Integrations > Private Apps.",
      "Crea una private app y dale permisos de contactos y deals.",
      "Copia su token (no requiere flujo de OAuth).",
      "Pega el token abajo y pícale Conectar.",
    ],
    credentials: [
      {
        field: "Private app token",
        where:
          "HubSpot > Settings > Integrations > Private Apps: crea una private app, dale permisos de contactos y deals, y copia su token.",
      },
    ],
  },

  denue: {
    intro:
      "Directorio público del INEGI con 5.5 millones de unidades económicas para prospectar negocios reales por giro y zona.",
    steps: [
      "Entra a inegi.org.mx/app/api/denue.",
      "Regístrate (es gratis) y el INEGI te da un token sin costo.",
      "Pega el token abajo.",
      "Pícale Conectar.",
    ],
    credentials: [
      {
        field: "Token de INEGI",
        where:
          "inegi.org.mx/app/api/denue: te registras y el INEGI te da un token de la API de DENUE sin costo.",
      },
    ],
  },
};
