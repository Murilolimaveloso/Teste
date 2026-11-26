"""Ferramentas que o ORION pode executar no seu computador.

Cada ferramenta tem uma definição (enviada ao Claude) e uma função Python
que roda localmente. Ferramentas de "tela" devolvem uma ação para a
interface (ex.: mostrar o globo, abrir o calendário).
"""
from __future__ import annotations

import base64
import io
import json
import os
import platform
import shutil
import subprocess
import threading
import urllib.parse
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_FILE = DATA_DIR / "memoria.json"
_lock = threading.Lock()

SYSTEM = platform.system()  # "Windows", "Darwin" ou "Linux"
ALLOW_SHELL = os.getenv("ORION_PERMITIR_COMANDOS", "0") == "1"

# --------------------------------------------------------------------------
# Banco de dados simples em JSON (lembretes, tarefas, listas, notas)
# --------------------------------------------------------------------------

def _load() -> dict:
    if DB_FILE.exists():
        try:
            return json.loads(DB_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"lembretes": [], "tarefas": [], "listas": {}, "notas": []}


def _save(db: dict) -> None:
    DB_FILE.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")


def db_read() -> dict:
    with _lock:
        return _load()


def db_update(fn):
    with _lock:
        db = _load()
        result = fn(db)
        _save(db)
        return result


# --------------------------------------------------------------------------
# Aplicativos conhecidos (nome falado -> comando por sistema)
# --------------------------------------------------------------------------
APPS = {
    "navegador": {"Windows": "start chrome", "Darwin": "Google Chrome", "Linux": "xdg-open https://google.com"},
    "chrome": {"Windows": "start chrome", "Darwin": "Google Chrome", "Linux": "google-chrome"},
    "edge": {"Windows": "start msedge", "Darwin": "Microsoft Edge", "Linux": "microsoft-edge"},
    "firefox": {"Windows": "start firefox", "Darwin": "Firefox", "Linux": "firefox"},
    "bloco de notas": {"Windows": "notepad", "Darwin": "TextEdit", "Linux": "gedit"},
    "calculadora": {"Windows": "calc", "Darwin": "Calculator", "Linux": "gnome-calculator"},
    "explorador de arquivos": {"Windows": "explorer", "Darwin": "Finder", "Linux": "xdg-open ~"},
    "paint": {"Windows": "mspaint", "Darwin": "Preview", "Linux": "pinta"},
    "terminal": {"Windows": "start cmd", "Darwin": "Terminal", "Linux": "x-terminal-emulator"},
    "powershell": {"Windows": "start powershell", "Darwin": "Terminal", "Linux": "x-terminal-emulator"},
    "gerenciador de tarefas": {"Windows": "taskmgr", "Darwin": "Activity Monitor", "Linux": "gnome-system-monitor"},
    "configurações": {"Windows": "start ms-settings:", "Darwin": "System Settings", "Linux": "gnome-control-center"},
    "word": {"Windows": "start winword", "Darwin": "Microsoft Word", "Linux": "libreoffice --writer"},
    "excel": {"Windows": "start excel", "Darwin": "Microsoft Excel", "Linux": "libreoffice --calc"},
    "powerpoint": {"Windows": "start powerpnt", "Darwin": "Microsoft PowerPoint", "Linux": "libreoffice --impress"},
    "outlook": {"Windows": "start outlook", "Darwin": "Microsoft Outlook", "Linux": "thunderbird"},
    "vscode": {"Windows": "code", "Darwin": "Visual Studio Code", "Linux": "code"},
    "spotify": {"Windows": "start spotify:", "Darwin": "Spotify", "Linux": "spotify"},
    "whatsapp": {"Windows": "start whatsapp:", "Darwin": "WhatsApp", "Linux": "xdg-open https://web.whatsapp.com"},
    "discord": {"Windows": "start discord:", "Darwin": "Discord", "Linux": "discord"},
    "teams": {"Windows": "start msteams:", "Darwin": "Microsoft Teams", "Linux": "xdg-open https://teams.microsoft.com"},
    "câmera": {"Windows": "start microsoft.windows.camera:", "Darwin": "Photo Booth", "Linux": "cheese"},
    "fotos": {"Windows": "start ms-photos:", "Darwin": "Photos", "Linux": "xdg-open ~/Pictures"},
    "relógio": {"Windows": "start ms-clock:", "Darwin": "Clock", "Linux": "gnome-clocks"},
    "loja": {"Windows": "start ms-windows-store:", "Darwin": "App Store", "Linux": "gnome-software"},
}
WEB_APPS = {
    "youtube": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "google maps": "https://www.google.com/maps",
    "chatgpt": "https://chat.openai.com",
    "netflix": "https://www.netflix.com",
    "instagram": "https://www.instagram.com",
    "agenda google": "https://calendar.google.com",
    "drive": "https://drive.google.com",
}


def _run(cmd: str) -> None:
    subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_app(nome: str) -> str:
    key = nome.strip().lower()
    if key in WEB_APPS:
        webbrowser.open(WEB_APPS[key])
        return f"Abri {nome} no navegador."
    entry = APPS.get(key)
    if entry:
        cmd = entry[SYSTEM] if SYSTEM in entry else None
        if cmd:
            if SYSTEM == "Darwin" and not cmd.startswith(("open", "xdg")):
                _run(f'open -a "{cmd}"')
            else:
                _run(cmd)
            return f"Abrindo {nome}."
    # Não está na lista: tenta pelo nome do executável / app instalado.
    if SYSTEM == "Windows":
        _run(f'start "" "{nome}"')
    elif SYSTEM == "Darwin":
        _run(f'open -a "{nome}"')
    else:
        exe = shutil.which(key)
        if not exe:
            return f"Não encontrei o aplicativo '{nome}' neste computador."
        _run(exe)
    return f"Tentei abrir '{nome}'. Se não abriu, me diga o nome exato do programa."


def open_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Abri {url}."


def web_search(consulta: str, site: str = "google") -> str:
    q = urllib.parse.quote_plus(consulta)
    urls = {
        "google": f"https://www.google.com/search?q={q}",
        "youtube": f"https://www.youtube.com/results?search_query={q}",
        "maps": f"https://www.google.com/maps/search/{q}",
        "imagens": f"https://www.google.com/search?tbm=isch&q={q}",
        "noticias": f"https://news.google.com/search?q={q}&hl=pt-BR",
    }
    webbrowser.open(urls.get(site, urls["google"]))
    return f"Pesquisei '{consulta}' no {site}."


def open_folder(caminho: str) -> str:
    p = Path(os.path.expandvars(os.path.expanduser(caminho)))
    if not p.exists():
        return f"A pasta {p} não existe."
    if SYSTEM == "Windows":
        os.startfile(str(p))  # type: ignore[attr-defined]
    elif SYSTEM == "Darwin":
        _run(f'open "{p}"')
    else:
        _run(f'xdg-open "{p}"')
    return f"Abri {p}."


def run_command(comando: str) -> str:
    if not ALLOW_SHELL:
        return ("Execução de comandos está desativada. Para ativar, defina "
                "ORION_PERMITIR_COMANDOS=1 no arquivo .env.")
    shell = ["powershell", "-NoProfile", "-Command", comando] if SYSTEM == "Windows" else ["bash", "-lc", comando]
    try:
        out = subprocess.run(shell, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return "O comando demorou mais de 60 segundos e foi interrompido."
    text = (out.stdout + out.stderr).strip()
    return f"Código de saída {out.returncode}.\n{text[-4000:]}"


def take_screenshot():
    try:
        from PIL import ImageGrab
    except ImportError:
        return "Instale o Pillow para capturar a tela."
    try:
        img = ImageGrab.grab()
    except Exception as e:  # noqa: BLE001 - sem tela disponível, etc.
        return f"Não consegui capturar a tela: {e}"
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                      "data": base64.b64encode(buf.getvalue()).decode()}},
        {"type": "text", "text": "Captura da tela atual do usuário."},
    ]


def system_info() -> str:
    info = {"sistema": f"{SYSTEM} {platform.release()}", "maquina": platform.node(),
            "processador": platform.processor() or platform.machine()}
    try:
        import psutil  # opcional
        info["cpu_uso"] = f"{psutil.cpu_percent(interval=0.5)}%"
        mem = psutil.virtual_memory()
        info["memoria"] = f"{mem.percent}% de {round(mem.total / 2**30, 1)} GB"
        bat = psutil.sensors_battery()
        if bat:
            info["bateria"] = f"{bat.percent}%{' (carregando)' if bat.power_plugged else ''}"
    except ImportError:
        pass
    total, _, free = shutil.disk_usage(Path.home())
    info["disco_livre"] = f"{round(free / 2**30, 1)} GB de {round(total / 2**30, 1)} GB"
    return json.dumps(info, ensure_ascii=False)


# ---- Agenda / tarefas / listas / notas -----------------------------------

def add_reminder(texto: str, data: str, hora: str = "", tema: str = "") -> str:
    item = {"id": uuid.uuid4().hex[:8], "texto": texto, "data": data, "hora": hora,
            "tema": tema, "avisado": False}
    db_update(lambda db: db["lembretes"].append(item))
    return f"Lembrete criado: {texto} em {data} {hora}".strip()


def list_reminders(data: str = "") -> str:
    items = db_read()["lembretes"]
    if data:
        items = [i for i in items if i["data"] == data]
    return json.dumps(items, ensure_ascii=False) if items else "Nenhum lembrete."


def delete_reminder(id: str) -> str:
    def fn(db):
        before = len(db["lembretes"])
        db["lembretes"] = [i for i in db["lembretes"] if i["id"] != id]
        return before != len(db["lembretes"])
    return "Lembrete removido." if db_update(fn) else "Não encontrei esse lembrete."


def add_task(texto: str) -> str:
    item = {"id": uuid.uuid4().hex[:8], "texto": texto, "feita": False}
    db_update(lambda db: db["tarefas"].append(item))
    return f"Tarefa adicionada: {texto}"


def complete_task(id: str) -> str:
    def fn(db):
        for t in db["tarefas"]:
            if t["id"] == id:
                t["feita"] = True
                return True
        return False
    return "Tarefa concluída." if db_update(fn) else "Não encontrei essa tarefa."


def list_tasks() -> str:
    items = db_read()["tarefas"]
    return json.dumps(items, ensure_ascii=False) if items else "Nenhuma tarefa."


def add_to_list(lista: str, itens: list[str]) -> str:
    db_update(lambda db: db["listas"].setdefault(lista.lower(), []).extend(itens))
    return f"Adicionei {len(itens)} item(ns) à lista '{lista}'."


def get_lists() -> str:
    return json.dumps(db_read()["listas"], ensure_ascii=False) or "Nenhuma lista."


def save_note(texto: str) -> str:
    item = {"quando": datetime.now().isoformat(timespec="minutes"), "texto": texto}
    db_update(lambda db: db["notas"].append(item))
    return "Anotado. Vou lembrar disso."


# --------------------------------------------------------------------------
# Definições enviadas ao Claude
# --------------------------------------------------------------------------

def _tool(name, description, props=None, required=None):
    return {
        "name": name,
        "description": description,
        "input_schema": {"type": "object", "properties": props or {},
                         "required": required or [], "additionalProperties": False},
    }


S = {"type": "string"}
TOOLS = [
    _tool("abrir_aplicativo",
          "Abre um aplicativo no computador do usuário. Nomes conhecidos: "
          + ", ".join(list(APPS) + list(WEB_APPS))
          + ". Para outros, passe o nome do programa/executável.",
          {"nome": S}, ["nome"]),
    _tool("abrir_site", "Abre uma URL no navegador padrão.", {"url": S}, ["url"]),
    _tool("pesquisar", "Pesquisa na web e abre o resultado no navegador. "
          "Use site='youtube' para tocar/achar vídeos e músicas.",
          {"consulta": S, "site": {"type": "string", "enum": ["google", "youtube", "maps", "imagens", "noticias"]}},
          ["consulta"]),
    _tool("abrir_pasta", "Abre uma pasta no explorador de arquivos (ex.: ~/Downloads, ~/Documents).",
          {"caminho": S}, ["caminho"]),
    _tool("executar_comando",
          "Executa um comando de terminal (PowerShell no Windows, bash no Linux/Mac) e devolve a saída. "
          "Use para automações que as outras ferramentas não cobrem. Nunca rode comandos destrutivos "
          "(apagar arquivos, formatar, desligar) sem o usuário ter pedido isso explicitamente.",
          {"comando": S}, ["comando"]),
    _tool("ver_tela", "Captura a tela do usuário para você ver o que está aberto nela."),
    _tool("info_sistema", "Mostra uso de CPU, memória, bateria e disco do computador."),
    _tool("criar_lembrete", "Agenda um lembrete no calendário interno. data no formato AAAA-MM-DD, hora HH:MM.",
          {"texto": S, "data": S, "hora": S, "tema": S}, ["texto", "data"]),
    _tool("listar_lembretes", "Lista lembretes (opcionalmente de uma data AAAA-MM-DD).", {"data": S}),
    _tool("apagar_lembrete", "Remove um lembrete pelo id.", {"id": S}, ["id"]),
    _tool("criar_tarefa", "Adiciona uma tarefa à lista de tarefas.", {"texto": S}, ["texto"]),
    _tool("concluir_tarefa", "Marca uma tarefa como feita pelo id.", {"id": S}, ["id"]),
    _tool("listar_tarefas", "Lista as tarefas."),
    _tool("adicionar_na_lista", "Adiciona itens a uma lista nomeada (compras, filmes, etc.).",
          {"lista": S, "itens": {"type": "array", "items": S}}, ["lista", "itens"]),
    _tool("ver_listas", "Mostra todas as listas e seus itens."),
    _tool("memorizar", "Guarda uma informação sobre o usuário para lembrar em conversas futuras.",
          {"texto": S}, ["texto"]),
    # --- ferramentas de interface (mostram algo na tela do ORION) ---
    _tool("mostrar_globo",
          "Mostra o globo 3D na interface do ORION e gira até um local. Informe latitude e longitude "
          "(você sabe as coordenadas de cidades e países).",
          {"local": S, "lat": {"type": "number"}, "lon": {"type": "number"},
           "satelite": {"type": "boolean", "description": "true para abrir direto no mapa de satélite aproximado"}},
          ["local", "lat", "lon"]),
    _tool("mostrar_calendario", "Abre o painel de calendário, tarefas e listas na interface."),
    _tool("mostrar_relogio", "Mostra o relógio holográfico com data e hora na interface."),
    _tool("fechar_paineis", "Fecha os painéis abertos e volta ao avatar."),
]

UI_TOOLS = {"mostrar_globo", "mostrar_calendario", "mostrar_relogio", "fechar_paineis"}

HANDLERS = {
    "abrir_aplicativo": lambda a: open_app(a["nome"]),
    "abrir_site": lambda a: open_url(a["url"]),
    "pesquisar": lambda a: web_search(a["consulta"], a.get("site", "google")),
    "abrir_pasta": lambda a: open_folder(a["caminho"]),
    "executar_comando": lambda a: run_command(a["comando"]),
    "ver_tela": lambda a: take_screenshot(),
    "info_sistema": lambda a: system_info(),
    "criar_lembrete": lambda a: add_reminder(a["texto"], a["data"], a.get("hora", ""), a.get("tema", "")),
    "listar_lembretes": lambda a: list_reminders(a.get("data", "")),
    "apagar_lembrete": lambda a: delete_reminder(a["id"]),
    "criar_tarefa": lambda a: add_task(a["texto"]),
    "concluir_tarefa": lambda a: complete_task(a["id"]),
    "listar_tarefas": lambda a: list_tasks(),
    "adicionar_na_lista": lambda a: add_to_list(a["lista"], a["itens"]),
    "ver_listas": lambda a: get_lists(),
    "memorizar": lambda a: save_note(a["texto"]),
}


def execute(name: str, args: dict):
    """Executa uma ferramenta. Retorna (conteúdo_do_resultado, ação_de_interface_ou_None, erro?)."""
    if name in UI_TOOLS:
        return "Mostrado na tela.", {"tipo": name, **args}, False
    handler = HANDLERS.get(name)
    if not handler:
        return f"Ferramenta desconhecida: {name}", None, True
    try:
        return handler(args), None, False
    except KeyError as e:
        return f"Parâmetro obrigatório ausente: {e}", None, True
    except Exception as e:  # noqa: BLE001 - devolve o erro ao modelo
        return f"Erro ao executar {name}: {e}", None, True
