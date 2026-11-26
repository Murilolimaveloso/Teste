"""ORION — servidor do assistente pessoal.

Roda no SEU computador: recebe o que você fala/digita na interface,
conversa com o Claude, executa as ferramentas localmente e APRENDE com o uso,
guardando memórias, hábitos e histórico no banco Neon (Postgres).

Ciclo de aprendizado:
  1. A cada pedido, busca no Neon as memórias relacionadas e entrega ao modelo.
  2. Durante a conversa, o próprio modelo grava o que aprende (ferramenta "aprender").
  3. Cada ação é registrada (deu certo ou não, hora, dia) para detectar hábitos.
  4. A cada poucas mensagens, e ao iniciar uma nova conversa, uma "reflexão"
     em segundo plano relê a conversa e extrai fatos, preferências, habilidades
     e lições, além de corrigir memórias que ficaram desatualizadas.

Uso:  python server.py   ->  abre http://localhost:8765
"""
from __future__ import annotations

import json
import os
import re
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Literal

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).parent / ".env")

import db  # noqa: E402
import tools  # noqa: E402  (carrega depois do .env para ler ORION_PERMITIR_COMANDOS)

MODEL = os.getenv("ORION_MODELO", "claude-opus-5-5")
EFFORT = os.getenv("ORION_ESFORCO", "low")  # low = respostas rápidas para voz
USER_NAME = os.getenv("ORION_NOME_USUARIO", "")
PORT = int(os.getenv("ORION_PORTA", "8765"))
MAX_TOOL_ROUNDS = 12
REFLETIR_A_CADA = 6  # mensagens do usuário entre uma reflexão e outra

client = anthropic.Anthropic()
app = FastAPI(title="ORION")
STATIC = Path(__file__).parent / "static"
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


# ============================================================================
# Prompt de sistema (montado no início de cada conversa com o que já aprendeu)
# ============================================================================

def build_system_prompt() -> str:
    perfil = "\n".join(f"- [{m['tipo']}] {m['conteudo']} (#{m['id']})" for m in db.perfil()) or "(nada ainda)"
    habitos = "\n".join(
        f"- {h['alvo']} via {h['ferramenta']}: {h['vezes']} vezes, mais comum por volta das {h['hora_comum']}h"
        for h in db.habitos()) or "(ainda observando)"
    resumos = "\n".join(f"- {r['quando']}: {r['resumo']}" for r in db.resumos_recentes()) or "(nenhuma)"
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
Antes de apagar algo ou rodar um comando que altere o sistema, confirme com o usuário.

VOCÊ APRENDE COM O USO. Você tem uma memória permanente num banco de dados:
- Cada mensagem do usuário chega com as memórias relacionadas que você já tem. Use-as: \
se existe uma habilidade salva para aquele pedido, siga o passo a passo dela; se existe uma lição, \
não repita o erro.
- Quando descobrir algo que vale lembrar, grave com a ferramenta aprender, sem anunciar: \
fatos e preferências do usuário, o jeito exato que funcionou para resolver um pedido (habilidade), \
o que falhou e como contornar (licao), e rotinas que perceber.
- Quando uma ferramenta falhar, tente outro caminho (outro nome de programa, um site, um comando) \
antes de desistir; se conseguir, salve a solução como habilidade.
- Se o usuário corrigir você, atualize a memória (aprender com a versão certa, esquecer a errada).
- Seja proativo com moderação: se um hábito combina com o horário atual, pode oferecer em uma frase.

O que você já sabe sobre o usuário:
{perfil}

Hábitos observados (últimos 45 dias):
{habitos}

Conversas recentes:
{resumos}"""


# ============================================================================
# Conversa
# ============================================================================

class Conversation:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.messages: list = []
        self.id = db.nova_conversa()
        self.turnos = 0
        self.system = build_system_prompt()


conv: Conversation | None = None


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


FALHA = re.compile(r"^(Não encontrei|Não consegui|Erro|Execução de comandos está desativada|"
                   r"Ferramenta desconhecida|Parâmetro obrigatório|A pasta .* não existe|O comando demorou)")


def _foi_falha(conteudo, is_error: bool) -> bool:
    if is_error:
        return True
    if isinstance(conteudo, str):
        m = re.match(r"Código de saída (\d+)", conteudo)
        return bool(FALHA.match(conteudo)) or bool(m and m.group(1) != "0")
    return False


def contexto_memoria(texto: str) -> str:
    try:
        rel = db.buscar(texto)
    except Exception:  # noqa: BLE001 - memória indisponível não pode travar a conversa
        return ""
    if not rel:
        return ""
    linhas = "\n".join(f"- [{m['tipo']}] {m['conteudo']} (#{m['id']})" for m in rel)
    return f"\n[Memórias relacionadas]\n{linhas}"


def run_turn(user_text: str) -> dict:
    agora = datetime.now()
    cabecalho = f"[Agora: {DIAS[agora.weekday()]}, {agora:%d/%m/%Y %H:%M}]"
    actions: list[dict] = []
    log: list[str] = []
    with conv.lock:
        inicio = len(conv.messages)
        conteudo = f"{cabecalho}{contexto_memoria(user_text)}\n\n{user_text}"
        try:
            response = _loop(conteudo, actions, log)
        except Exception:
            del conv.messages[inicio:]  # desfaz o turno que falhou
            raise
        resultado = _resposta(response, actions, log)
        conv.turnos += 1
        conversa_id, turnos = conv.id, conv.turnos
    db.salvar_mensagem(conversa_id, "usuario", user_text)
    db.salvar_mensagem(conversa_id, "orion", resultado["resposta"])
    if turnos % REFLETIR_A_CADA == 0:
        refletir_em_segundo_plano(conversa_id)
    return resultado


def _loop(user_content: str, actions: list, log: list):
    conv.messages.append({"role": "user", "content": user_content})
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
            entrada = dict(block.input)
            content, action, is_error = tools.execute(block.name, entrada)
            if action:
                actions.append(action)
            log.append(block.name)
            if block.name != "ver_tela":
                try:
                    db.registrar_evento(conv.id, block.name, entrada, str(content),
                                        not _foi_falha(content, is_error))
                except Exception:  # noqa: BLE001
                    pass
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


# ============================================================================
# Reflexão: o ORION relê a conversa e aprende sozinho
# ============================================================================

class Aprendizado(BaseModel):
    tipo: Literal["fato", "preferencia", "habilidade", "licao", "rotina"]
    conteudo: str = Field(description="Uma frase autoexplicativa, útil numa conversa futura.")
    tags: str = Field(description="Palavras-chave separadas por espaço.")
    importancia: int = Field(description="1 a 5. 5 = essencial sobre o usuário.")


class Reflexao(BaseModel):
    resumo: str = Field(description="Resumo da conversa em uma frase.")
    aprendizados: list[Aprendizado]
    memorias_obsoletas: list[int] = Field(
        description="ids de memórias existentes que a conversa mostrou estarem erradas ou desatualizadas.")


PROMPT_REFLEXAO = """Você é o módulo de aprendizado do ORION, um assistente pessoal.
Releia o trecho de conversa e as ações executadas abaixo e extraia o que vale guardar
para ficar mais útil ao usuário no futuro:
- fato: informações sobre o usuário, pessoas, lugares, trabalho, projetos.
- preferencia: gostos e o jeito como ele prefere que as coisas sejam feitas.
- habilidade: um procedimento que FUNCIONOU (ex.: comando exato, nome correto do programa).
- licao: algo que falhou e como evitar ou contornar.
- rotina: padrões de horário/dia.
Não repita o que já está nas memórias existentes, a menos que precise corrigir.
Não guarde trivialidades nem o conteúdo de pedidos pontuais sem valor futuro.
Se nada valer a pena, devolva a lista vazia.

MEMÓRIAS EXISTENTES:
{memorias}

AÇÕES EXECUTADAS:
{eventos}

CONVERSA:
{conversa}"""

_reflexao_lock = threading.Lock()


def refletir(conversa_id: int) -> str:
    with _reflexao_lock:
        msgs, eventos = db.pendentes_reflexao(conversa_id)
        if not any(m["papel"] == "usuario" for m in msgs):
            return "nada novo"
        conversa = "\n".join(f"{m['papel'].upper()}: {m['texto']}" for m in msgs)
        memorias = db.perfil(60) + db.buscar(conversa[:2000], 20, marcar_uso=False)
        vistos, mem_txt = set(), []
        for m in memorias:
            if m["id"] not in vistos:
                vistos.add(m["id"])
                mem_txt.append(f"#{m['id']} [{m['tipo']}] {m['conteudo']}")
        ev_txt = "\n".join(
            f"- {'OK' if e['sucesso'] else 'FALHOU'} {e['ferramenta']} {json.dumps(e['entrada'], ensure_ascii=False)}"
            f" -> {(e['resultado'] or '')[:200]}" for e in reversed(eventos)) or "(nenhuma)"
        resp = client.messages.parse(
            model=MODEL,
            max_tokens=8000,
            output_config={"effort": "low"},
            output_format=Reflexao,
            messages=[{"role": "user", "content": PROMPT_REFLEXAO.format(
                memorias="\n".join(mem_txt) or "(nenhuma)", eventos=ev_txt, conversa=conversa)}],
        )
        if resp.stop_reason == "refusal" or resp.parsed_output is None:
            db.marcar_refletida(conversa_id, msgs[-1]["id"], "")
            return "sem resultado"
        r: Reflexao = resp.parsed_output
        corrigidas = [mid for mid in r.memorias_obsoletas if mid in vistos]
        for mid in corrigidas:
            db.esquecer(mid)
        for a in r.aprendizados:
            db.aprender(a.conteudo, a.tipo, a.tags, a.importancia, fonte="reflexao")
        db.marcar_refletida(conversa_id, msgs[-1]["id"], r.resumo)
        return f"{len(r.aprendizados)} aprendizados, {len(corrigidas)} corrigidos"


def refletir_em_segundo_plano(conversa_id: int) -> None:
    def tarefa():
        try:
            print(f"  [reflexão] conversa {conversa_id}: {refletir(conversa_id)}")
        except Exception as e:  # noqa: BLE001 - aprendizado nunca derruba o servidor
            print(f"  [reflexão] falhou: {e}")
    threading.Thread(target=tarefa, daemon=True).start()


# ============================================================================
# API
# ============================================================================

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
        anterior = conv.id
        conv.reset()  # o novo prompt já inclui o que foi aprendido até aqui
    refletir_em_segundo_plano(anterior)
    return {"ok": True}


@app.get("/api/dados")
def dados():
    return {"lembretes": db.lembretes(), "tarefas": db.tarefas(), "listas": db.listas()}


@app.get("/api/memoria")
def memoria():
    return {"memorias": db.listar_memorias(), "habitos": db.habitos(15),
            "estatisticas": db.estatisticas()}


@app.delete("/api/memoria/{id}")
def apagar_memoria(id: int):
    return {"msg": db.esquecer(id)}


@app.post("/api/memoria/refletir")
def refletir_agora():
    try:
        return {"msg": refletir(conv.id)}
    except anthropic.APIError as e:
        raise HTTPException(502, f"Falha na reflexão: {e}")


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


@app.get("/api/avisos")
def avisos():
    try:
        return db.lembretes_vencidos()
    except Exception:  # noqa: BLE001 - banco momentaneamente fora
        return []


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def iniciar() -> None:
    global conv
    db.init()
    # Conversas que ficaram sem reflexão (ex.: o programa foi fechado) são processadas agora.
    for cid in db.conversas_nao_refletidas():
        refletir_em_segundo_plano(cid)
    conv = Conversation()


if __name__ == "__main__":
    import uvicorn

    iniciar()
    if os.getenv("ORION_ABRIR_NAVEGADOR", "1") == "1":
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    print(f"\n  ORION online em http://localhost:{PORT}  (memória: Neon)\n")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
