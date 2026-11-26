"""ORION — servidor do assistente pessoal.

Roda no SEU computador: recebe o que você fala/digita na interface,
conversa com o Claude e executa as ferramentas localmente (abrir apps,
sites, agenda, etc.).

Uso:  python server.py   ->  abre http://localhost:8765
"""
from __future__ import annotations

import os
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv(Path(__file__).parent / ".env")

import tools  # noqa: E402  (carrega depois do .env para ler ORION_PERMITIR_COMANDOS)

MODEL = os.getenv("ORION_MODELO", "claude-opus-5-5")
EFFORT = os.getenv("ORION_ESFORCO", "low")  # low = respostas rápidas para voz
USER_NAME = os.getenv("ORION_NOME_USUARIO", "")
PORT = int(os.getenv("ORION_PORTA", "8765"))
MAX_TOOL_ROUNDS = 12

client = anthropic.Anthropic()
app = FastAPI(title="ORION")
STATIC = Path(__file__).parent / "static"


def build_system_prompt() -> str:
    notas = tools.db_read()["notas"]
    memoria = "\n".join(f"- {n['texto']}" for n in notas[-50:]) or "(nada ainda)"
    quem = f"O nome do usuário é {USER_NAME}. " if USER_NAME else ""
    return f"""Você é ORION, o assistente pessoal de IA do usuário, rodando no computador dele \
({tools.SYSTEM}). {quem}Fale sempre em português do Brasil.

Suas respostas são lidas em voz alta por síntese de fala, então:
- Seja breve e natural: 1 a 3 frases, como um assistente falando.
- Não use markdown, listas, emojis nem links nas respostas.

Você controla o computador pelas ferramentas. Quando o usuário pedir algo que uma ferramenta faz, \
faça direto, sem pedir confirmação, e depois diga em poucas palavras o que fez. Se pedir para \
"mostrar" um lugar, use mostrar_globo. Para tocar música ou vídeo, pesquise no YouTube. \
Datas relativas ("amanhã", "sexta") devem ser convertidas usando a data atual informada em cada mensagem. \
Antes de apagar algo ou rodar um comando que altere o sistema, confirme com o usuário. \
Use memorizar quando o usuário contar algo pessoal que valha lembrar.

O que você já sabe sobre o usuário:
{memoria}"""


class Conversation:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.messages: list = []
        self.system = build_system_prompt()


conv = Conversation()


def call_claude(messages: list, system: str):
    return client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        tools=tools.TOOLS,
        messages=messages,
        output_config={"effort": EFFORT},
        cache_control={"type": "ephemeral"},
        # Se o modelo recusar por engano, o servidor tenta outro modelo automaticamente.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )


def run_turn(user_text: str) -> dict:
    agora = datetime.now().strftime("%A, %d/%m/%Y %H:%M")
    actions: list[dict] = []
    log: list[str] = []
    with conv.lock:
        inicio = len(conv.messages)
        try:
            response = _loop(f"[Agora: {agora}]\n{user_text}", actions, log)
        except Exception:
            del conv.messages[inicio:]  # desfaz o turno que falhou
            raise
    return _resposta(response, actions, log)


def _loop(user_text: str, actions: list, log: list):
    conv.messages.append({"role": "user", "content": user_text})
    response = None
    for _ in range(MAX_TOOL_ROUNDS):
        response = call_claude(conv.messages, conv.system)
        # Guarda a resposta inteira (inclui blocos de raciocínio) sem editar.
        conv.messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "pause_turn":
            continue
        if response.stop_reason != "tool_use":
            break

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            content, action, is_error = tools.execute(block.name, dict(block.input))
            if action:
                actions.append(action)
            log.append(block.name)
            result = {"type": "tool_result", "tool_use_id": block.id, "content": content}
            if is_error:
                result["is_error"] = True
            results.append(result)
        conv.messages.append({"role": "user", "content": results})
    return response


def _resposta(response, actions: list, log: list) -> dict:
    if response is None:
        reply = ""
    elif response.stop_reason == "refusal":
        reply = "Desculpe, não posso ajudar com isso."
    else:
        reply = " ".join(b.text for b in response.content if b.type == "text").strip()
        if not reply and response.stop_reason == "tool_use":
            reply = "Fiz várias ações seguidas e parei para não exagerar. Quer que eu continue?"
    return {"resposta": reply or "Feito.", "acoes": actions, "ferramentas": log}


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
class ChatIn(BaseModel):
    mensagem: str


@app.post("/api/chat")
def chat(body: ChatIn):
    text = body.mensagem.strip()
    if not text:
        raise HTTPException(400, "Mensagem vazia")
    try:
        return run_turn(text)
    except anthropic.AuthenticationError:
        raise HTTPException(401, "Chave da API inválida. Confira o ANTHROPIC_API_KEY no arquivo .env.")
    except anthropic.RateLimitError:
        raise HTTPException(429, "Muitas requisições. Espere alguns segundos e tente de novo.")
    except anthropic.APIConnectionError:
        raise HTTPException(503, "Sem conexão com a internet ou com a API.")
    except anthropic.APIStatusError as e:
        raise HTTPException(502, f"Erro da API ({e.status_code}): {e.message}")


@app.post("/api/reiniciar")
def reiniciar():
    with conv.lock:
        conv.reset()
    return {"ok": True}


@app.get("/api/dados")
def dados():
    return tools.db_read()


class LembreteIn(BaseModel):
    texto: str
    data: str
    hora: str = ""
    tema: str = ""


@app.post("/api/lembretes")
def novo_lembrete(body: LembreteIn):
    return {"msg": tools.add_reminder(body.texto, body.data, body.hora, body.tema)}


@app.delete("/api/lembretes/{id}")
def apagar_lembrete(id: str):
    return {"msg": tools.delete_reminder(id)}


class TarefaIn(BaseModel):
    texto: str


@app.post("/api/tarefas")
def nova_tarefa(body: TarefaIn):
    return {"msg": tools.add_task(body.texto)}


@app.post("/api/tarefas/{id}/concluir")
def concluir(id: str):
    return {"msg": tools.complete_task(id)}


class ListaIn(BaseModel):
    lista: str
    item: str


@app.post("/api/listas")
def nova_lista_item(body: ListaIn):
    return {"msg": tools.add_to_list(body.lista, [body.item])}


# Avisos de lembretes que venceram -------------------------------------------
_avisos: list[dict] = []
_avisos_lock = threading.Lock()


def _vigia_lembretes() -> None:
    while True:
        agora = datetime.now()

        def fn(db):
            vencidos = []
            for lem in db["lembretes"]:
                if lem.get("avisado") or not lem.get("hora"):
                    continue
                try:
                    quando = datetime.strptime(f"{lem['data']} {lem['hora']}", "%Y-%m-%d %H:%M")
                except ValueError:
                    continue
                if quando <= agora:
                    lem["avisado"] = True
                    vencidos.append(lem)
            return vencidos

        vencidos = tools.db_update(fn)
        if vencidos:
            with _avisos_lock:
                _avisos.extend(vencidos)
        time.sleep(15)


@app.get("/api/avisos")
def avisos():
    with _avisos_lock:
        out = list(_avisos)
        _avisos.clear()
    return out


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


if __name__ == "__main__":
    import uvicorn

    threading.Thread(target=_vigia_lembretes, daemon=True).start()
    if os.getenv("ORION_ABRIR_NAVEGADOR", "1") == "1":
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    print(f"\n  ORION online em http://localhost:{PORT}\n")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
