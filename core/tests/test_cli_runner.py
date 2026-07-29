"""El CLI que el dueño ya tiene instalado, usado tal cual.

Ningún test ejecuta el CLI de verdad: el ejecutor se inyecta. Lo que se prueba
es que aiuda hable con él sin pedirle al dueño ni un token ni una terminal.
"""

import json
import os
from pathlib import Path

import pytest

from aiuda_core.engine import cli_runner
from aiuda_core.engine.cli_runner import CliNoDisponible, CliRunner
from aiuda_core.engine.provider import ProviderCredential
from aiuda_core.engine.runner import ProviderRunner, make_runner


def _claude(texto: str, entrada: int = 10, salida: int = 5) -> str:
    return json.dumps(
        {"is_error": False, "result": texto, "usage": {"input_tokens": entrada, "output_tokens": salida}}
    )


def test_make_runner_devuelve_el_cli_y_cumple_el_protocolo():
    cred = ProviderCredential(name="claude_cli", mode="cli", secret="")
    runner = make_runner(cred)
    assert isinstance(runner, ProviderRunner)
    assert runner.model_for("redaccion") == "claude-cli"


def test_complete_usa_el_binario_y_registra_uso():
    llamadas, eventos = [], []

    def correr(cmd, entrada):
        llamadas.append(cmd)
        return _claude("Buenas tardes, le escribo por su factura.")

    runner = CliRunner(
        "claude", correr=correr, usage_callback=lambda m, t, i, o: eventos.append((m, t, i, o))
    )
    salida = runner.complete(system="Eres cobranza.", user="Redacta.", task="redaccion")
    assert salida.startswith("Buenas tardes")
    assert Path(llamadas[0][0]).name == "claude" and llamadas[0][1] == "-p"
    assert "--output-format" in llamadas[0]
    assert eventos == [("claude-cli", "redaccion", 10, 5)]


def test_codex_limpia_su_encabezado_y_su_pie():
    salida_codex = "codex\nEl cliente ya pagó.\ntokens used\n14,819\n"
    runner = CliRunner("codex", correr=lambda cmd, entrada: salida_codex)
    assert runner.complete(system="", user="x", task="t") == "El cliente ya pagó."


def test_classify_cae_a_la_ultima_etiqueta():
    runner = CliRunner("claude", correr=lambda cmd, e: _claude("banana"))
    assert runner.classify("s", "u", labels=["pago", "duda"], task="t") == "duda"


def test_tool_loop_consulta_y_responde():
    respuestas = [
        _claude('{"consulta": "consultar_cartera", "datos": {"cliente": "PIMSA"}}'),
        _claude('{"respuesta": "PIMSA debe 3 facturas por 120,000 pesos."}'),
    ]
    ejecutadas = []

    def correr(cmd, entrada):
        return respuestas.pop(0)

    def execute(nombre, args):
        ejecutadas.append((nombre, args))
        return "3 facturas, 120000"

    runner = CliRunner("claude", correr=correr)
    salida = runner.run_tool_loop(
        system="Eres cobranza.",
        user_message="¿Cuánto debe PIMSA?",
        tools=[{"name": "consultar_cartera", "description": "Lee la cartera"}],
        execute_tool=execute,
    )
    assert "120,000" in salida
    assert ejecutadas == [("consultar_cartera", {"cliente": "PIMSA"})]


def test_tool_loop_sin_json_devuelve_lo_que_dijo():
    """Si el modelo contesta en prosa, se respeta en vez de tirarlo."""
    runner = CliRunner("claude", correr=lambda cmd, e: _claude("No tengo esa información."))
    salida = runner.run_tool_loop(
        system="s", user_message="u", tools=[], execute_tool=lambda n, a: ""
    )
    assert salida == "No tengo esa información."


def test_error_del_cli_se_reporta_claro():
    def correr(cmd, entrada):
        return json.dumps({"is_error": True, "result": "sesión expirada"})

    runner = CliRunner("claude", correr=correr)
    with pytest.raises(CliNoDisponible) as exc:
        runner.complete(system="", user="x", task="t")
    assert "sesión expirada" in str(exc.value)


def test_probar_sin_binario_lo_dice(monkeypatch):
    monkeypatch.setattr(cli_runner, "detectar", lambda cli: None)
    verdict = cli_runner.probar("claude")
    assert verdict["ok"] is False and verdict["code"] == "no_instalado"


def test_probar_con_binario_ok(monkeypatch):
    monkeypatch.setattr(cli_runner, "detectar", lambda cli: "/usr/local/bin/claude")
    verdict = cli_runner.probar("claude", correr=lambda cmd, e: _claude("ok"))
    assert verdict["ok"] is True and verdict["model"] == "claude-cli"


def test_sin_sesion_se_explica_en_palabras_del_dueno(monkeypatch):
    """El caso más común: instalado pero sin sesión. Nada de JSON crudo en pantalla."""
    monkeypatch.setattr(cli_runner, "detectar", lambda cli: "/usr/local/bin/claude")

    def correr(cmd, entrada):
        raise CliNoDisponible(
            cli_runner._motivo("claude", json.dumps({"is_error": True, "result": "Not logged in · Please run /login"}), "")
        )

    verdict = cli_runner.probar("claude", correr=correr)
    assert verdict["ok"] is False
    assert verdict["code"] == "sin_sesion"
    assert "Claude Code está instalado pero sin sesión iniciada" in verdict["error"]
    assert "{" not in verdict["error"]


def test_motivo_traduce_el_json_del_cli():
    msg = cli_runner._motivo("codex", json.dumps({"result": "quota exceeded"}), "")
    assert msg.startswith("Codex no pudo responder: quota exceeded")


def test_probar_detecta_binario_ausente_antes_de_correr(monkeypatch):
    monkeypatch.setattr(cli_runner, "detectar", lambda cli: None)
    assert cli_runner.probar("codex")["code"] == "no_instalado"


def test_se_encuentra_aunque_el_path_no_lo_traiga(monkeypatch, tmp_path):
    """La app de escritorio arranca con el PATH mínimo de macOS. Ahí no basta which()."""
    monkeypatch.setattr(cli_runner.shutil, "which", lambda n: None)
    bin_dir = tmp_path / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    falso = bin_dir / "claude"
    falso.write_text("#!/bin/sh\n")
    falso.chmod(0o755)
    monkeypatch.setattr(cli_runner.Path, "home", classmethod(lambda cls: tmp_path))
    assert cli_runner.detectar("claude") == str(falso)
    assert cli_runner.detectar("codex") is None


def test_el_comando_usa_la_ruta_absoluta(monkeypatch):
    monkeypatch.setattr(cli_runner, "detectar", lambda n: "/opt/homebrew/bin/codex")
    llamadas = []
    runner = CliRunner("codex", correr=lambda cmd, e: llamadas.append(cmd) or "hola")
    runner.complete(system="", user="x", task="t")
    assert llamadas[0][0] == "/opt/homebrew/bin/codex"


def test_el_cli_corre_con_su_interprete_a_la_mano(monkeypatch, tmp_path):
    """`codex` es un script que empieza con `#!/usr/bin/env node`. Encontrarlo no
    basta: al arrancarlo el sistema busca `node` en el PATH, y una app abierta
    desde el Finder trae un PATH pelado donde node no está. El dueño veía
    "env: node: No such file or directory", que no dice nada del CLI.

    Por eso la carpeta del propio binario va al frente del PATH: en nvm y fnm,
    node vive justo ahí, junto al comando.
    """
    node_dir = tmp_path / ".nvm" / "versions" / "node" / "v20.19.0" / "bin"
    node_dir.mkdir(parents=True)
    (node_dir / "node").write_text("#!/bin/sh\n")
    codex = node_dir / "codex"
    codex.write_text("#!/usr/bin/env node\n")

    monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    entorno = cli_runner._entorno_para(str(codex))
    carpetas = entorno["PATH"].split(os.pathsep)

    assert carpetas[0] == str(node_dir), "la carpeta del binario debe ir primero"
    assert "/usr/bin" in carpetas, "sin tirar lo que ya traía el PATH"


def _stream_claude(texto: str, **uso) -> str:
    """Lo que imprime `claude -p --output-format stream-json`, en pequeño."""
    lineas = [
        {"type": "system", "subtype": "init"},
        {
            "type": "stream_event",
            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": texto}},
        },
        {"type": "result", "is_error": False, "result": texto, "usage": uso},
    ]
    return "\n".join(json.dumps(ln) for ln in lineas) + "\n"


def test_el_gasto_de_claude_cuenta_lo_que_de_verdad_se_proceso():
    """El medidor estaba ciego y por eso el tope del dueño no tenía cómo cortar.

    Cifras de una llamada real de Claude Code: `input_tokens` 2, caché escrita
    6,468, caché leída 17,957. Antes se registraban 2. Lo que se procesó fueron
    6,470; lo leído de caché queda fuera porque es el mismo prompt de sistema
    releído y se cobra a una décima parte.
    """
    eventos = []
    salida = _stream_claude(
        "ok",
        input_tokens=2,
        cache_creation_input_tokens=6468,
        cache_read_input_tokens=17957,
        output_tokens=218,
    )
    runner = CliRunner(
        "claude",
        correr=lambda cmd, e: salida,
        usage_callback=lambda m, t, i, o: eventos.append((i, o)),
    )
    assert runner.complete(system="", user="x", task="t") == "ok"
    assert eventos == [(2 + 6468, 218)]


def test_claude_pide_el_modo_de_eventos():
    llamadas = []
    runner = CliRunner("claude", correr=lambda cmd, e: llamadas.append(cmd) or _stream_claude("ok"))
    runner.complete(system="", user="x", task="t")
    assert "stream-json" in llamadas[0]
    assert "--include-partial-messages" in llamadas[0]


def test_codex_ya_reporta_sus_tokens():
    """Antes se registraba la llamada en ceros porque la salida no los traía."""
    eventos = []
    salida = "\n".join(
        json.dumps(ln)
        for ln in [
            {"type": "thread.started", "thread_id": "x"},
            {
                "type": "item.completed",
                "item": {"id": "i0", "type": "error", "message": "aviso que no es la respuesta"},
            },
            {"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": "El cliente ya pagó."}},
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 15879, "output_tokens": 26, "reasoning_output_tokens": 19},
            },
        ]
    )
    runner = CliRunner(
        "codex",
        correr=lambda cmd, e: salida,
        usage_callback=lambda m, t, i, o: eventos.append((i, o)),
    )
    assert runner.complete(system="", user="x", task="t") == "El cliente ya pagó."
    assert eventos == [(15879, 26 + 19)]


def test_un_cli_viejo_se_reintenta_con_las_banderas_de_antes():
    """No se le manda al dueño a actualizar nada: se le habla como antes."""
    intentos = []

    def correr(cmd, entrada):
        intentos.append(cmd)
        if "--json" in cmd:
            raise CliNoDisponible("error: unexpected argument '--json' found")
        return "codex\nlisto\ntokens used\n123\n"

    runner = CliRunner("codex", correr=correr)
    assert runner.complete(system="", user="x", task="t") == "listo"
    assert len(intentos) == 2 and "--json" not in intentos[1]


def test_si_se_corta_a_media_respuesta_se_respeta_lo_que_alcanzo_a_decir():
    a_medias = "\n".join(
        json.dumps(ln)
        for ln in [
            {"type": "system", "subtype": "init"},
            {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Buenas tardes, "}}},
            {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "le escribo por su factura."}}},
        ]
    )
    runner = CliRunner("claude", correr=lambda cmd, e: a_medias)
    assert runner.complete(system="", user="x", task="t") == "Buenas tardes, le escribo por su factura."


def test_el_reloj_mide_silencio_y_no_duracion(monkeypatch):
    """Una corrida larga pero sana no debe morir como una colgada.

    Antes el tope era de duración total: un CLI que tardaba tres minutos
    trabajando bien se moría igual que uno trabado. Ahora, mientras siga
    diciendo algo, se le deja seguir.
    """
    import sys

    monkeypatch.setattr(cli_runner, "TIMEOUT_S", 2)

    # Habla despacio pero no se calla: cuatro líneas en ~2.8 s, con el tope en 2.
    hablador = [
        sys.executable,
        "-c",
        "import sys,time\n"
        "for i in range(4):\n"
        "    print('{\"type\": \"system\"}', flush=True)\n"
        "    time.sleep(0.7)\n"
        "print('{\"type\": \"result\", \"is_error\": false, \"result\": \"terminé\"}', flush=True)\n",
    ]
    texto, _, _ = cli_runner._texto_de_claude(cli_runner._correr(hablador, ""))
    assert texto == "terminé"

    mudo = [sys.executable, "-c", "import time; time.sleep(30)"]
    with pytest.raises(CliNoDisponible) as exc:
        cli_runner._correr(mudo, "")
    assert "callado" in str(exc.value)


def test_el_entorno_no_repite_carpetas(monkeypatch, tmp_path):
    """El PATH crece en cada llamada si no se deduplica."""
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:{tmp_path}")
    carpetas = cli_runner._entorno_para(str(tmp_path / "claude"))["PATH"].split(os.pathsep)
    assert len(carpetas) == len(set(carpetas))
