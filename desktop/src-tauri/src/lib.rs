//! La app de escritorio de aiuda.
//!
//! No reimplementa nada: arranca el MISMO server local que `aiuda start`
//! (empaquetado como sidecar), espera a que responda y muestra su consola en
//! la ventana. Al cerrar la app, el server se va con ella.

use std::sync::Mutex;
use std::time::Duration;

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Puerto del server local: el mismo default del CLI.
const PORT: u16 = 4747;

struct Servidor(Mutex<Option<CommandChild>>);

/// Token de sesión de este arranque (patrón Jupyter). Se genera aquí y viaja
/// al server por env; la ventana entra con `?token=` una sola vez.
fn nuevo_token() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let pid = u128::from(std::process::id());
    format!("{:x}{:x}", nanos, pid.wrapping_mul(0x9E37_79B9_7F4A_7C15))
}

/// Carpeta de datos de aiuda (~/.aiuda), donde el server anota su sesión.
fn carpeta_datos() -> Option<std::path::PathBuf> {
    let casa = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE"))?;
    Some(std::path::PathBuf::from(casa).join(".aiuda"))
}

/// El token de un aiuda que YA está corriendo en este puerto, si lo hay.
///
/// Abrir la app dos veces dejaba dos servers peleando el puerto: el segundo no
/// podía escuchar, y la ventana nueva le hablaba al server viejo con un token
/// que ese no conocía. El dueño veía un error en crudo. Ahora la segunda
/// ventana se suma a la sesión que ya existe.
fn sesion_en_curso() -> Option<String> {
    if !esperar_salud(1) {
        return None;
    }
    let ruta = carpeta_datos()?.join("sesion.json");
    let crudo = std::fs::read_to_string(ruta).ok()?;
    let datos: serde_json::Value = serde_json::from_str(&crudo).ok()?;
    if datos.get("port").and_then(|p| p.as_u64()) != Some(u64::from(PORT)) {
        return None;
    }
    datos
        .get("token")
        .and_then(|t| t.as_str())
        .filter(|t| !t.is_empty())
        .map(str::to_owned)
}

/// Sondea /health hasta que el server responde. Sin red externa: es 127.0.0.1.
fn esperar_salud(intentos: u32) -> bool {
    let direccion = format!("127.0.0.1:{PORT}");
    for _ in 0..intentos {
        if let Ok(mut stream) = std::net::TcpStream::connect(&direccion) {
            use std::io::{Read, Write};
            let peticion = format!("GET /health HTTP/1.1\r\nHost: {direccion}\r\nConnection: close\r\n\r\n");
            if stream.write_all(peticion.as_bytes()).is_ok() {
                let mut respuesta = String::new();
                let _ = stream.read_to_string(&mut respuesta);
                if respuesta.contains("\"status\":\"ok\"") {
                    return true;
                }
            }
        }
        std::thread::sleep(Duration::from_millis(400));
    }
    false
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(Servidor(Mutex::new(None)))
        .setup(|app| {
            // Si aiuda ya está corriendo (la abriste dos veces), esta ventana se
            // suma a esa sesión en vez de levantar un segundo server.
            let sesion = sesion_en_curso();
            let token = match &sesion {
                Some(existente) => existente.clone(),
                None => nuevo_token(),
            };

            if sesion.is_none() {
                let sidecar = app
                    .shell()
                    .sidecar("aiuda-server")?
                    .env("AIUDA_SESSION_TOKEN", token.clone())
                    .args([
                        "start",
                        "--no-browser",
                        "--quiet",
                        "--exit-with-parent",
                        "--port",
                        &PORT.to_string(),
                    ]);
                let (mut rx, child) = sidecar.spawn()?;
                app.state::<Servidor>().0.lock().unwrap().replace(child);

                // Los logs del server van a la bitácora de la app: diagnosticar sin
                // abrir una terminal, sin enseñárselos al dueño salvo que falle.
                tauri::async_runtime::spawn(async move {
                    while let Some(event) = rx.recv().await {
                        match event {
                            CommandEvent::Stderr(linea) | CommandEvent::Stdout(linea) => {
                                log::info!("server: {}", String::from_utf8_lossy(&linea).trim_end());
                            }
                            _ => {}
                        }
                    }
                });
            } else {
                log::info!("aiuda ya estaba corriendo en :{PORT}; esta ventana se suma");
            }

            let listo = sesion.is_some() || esperar_salud(75); // ~30 s: el primer arranque crea la base
            let url = if listo {
                WebviewUrl::External(
                    format!("http://127.0.0.1:{PORT}/?token={token}")
                        .parse()
                        .expect("url del server local"),
                )
            } else {
                // Falla honesta: la ventana explica qué pasó, no se queda en blanco.
                WebviewUrl::App("arranque-fallido.html".into())
            };

            WebviewWindowBuilder::new(app, "principal", url)
                .title("aiuda")
                .inner_size(1280.0, 860.0)
                .min_inner_size(960.0, 640.0)
                .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error al construir la app")
        .run(|app, event| {
            // Cerrar la app apaga el server: nada queda corriendo a tus espaldas.
            if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
                if let Some(child) = app.state::<Servidor>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}
