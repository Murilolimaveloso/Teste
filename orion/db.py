"""Banco de dados do ORION no Neon (Postgres serverless).

Guarda tudo o que ele aprende e usa:
- memorias:   fatos, preferências, habilidades, lições e rotinas aprendidas
- conversas / mensagens: histórico (base para a reflexão automática)
- eventos:    cada ferramenta usada, se deu certo, hora e dia (para detectar hábitos)
- lembretes, tarefas, listas
"""
from __future__ import annotations

import atexit
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

TIPOS = ("fato", "preferencia", "habilidade", "licao", "rotina")

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS memorias (
    id           bigserial PRIMARY KEY,
    tipo         text NOT NULL DEFAULT 'fato',
    conteudo     text NOT NULL,
    tags         text NOT NULL DEFAULT '',
    importancia  smallint NOT NULL DEFAULT 3,
    confianca    real NOT NULL DEFAULT 0.8,
    usos         integer NOT NULL DEFAULT 0,
    fonte        text NOT NULL DEFAULT 'conversa',
    ativo        boolean NOT NULL DEFAULT true,
    criado       timestamptz NOT NULL DEFAULT now(),
    atualizado   timestamptz NOT NULL DEFAULT now(),
    ultimo_uso   timestamptz,
    busca        tsvector GENERATED ALWAYS AS
                 (to_tsvector('portuguese', conteudo || ' ' || tags)) STORED
);
CREATE INDEX IF NOT EXISTS memorias_busca_idx ON memorias USING gin (busca);
CREATE INDEX IF NOT EXISTS memorias_trgm_idx  ON memorias USING gin (conteudo gin_trgm_ops);

CREATE TABLE IF NOT EXISTS conversas (
    id             bigserial PRIMARY KEY,
    iniciada       timestamptz NOT NULL DEFAULT now(),
    resumo         text,
    refletida_ate  bigint NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mensagens (
    id           bigserial PRIMARY KEY,
    conversa_id  bigint NOT NULL REFERENCES conversas(id) ON DELETE CASCADE,
    papel        text NOT NULL,
    texto        text NOT NULL,
    criado       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mensagens_conv_idx ON mensagens (conversa_id, id);

CREATE TABLE IF NOT EXISTS eventos (
    id           bigserial PRIMARY KEY,
    conversa_id  bigint REFERENCES conversas(id) ON DELETE SET NULL,
    ferramenta   text NOT NULL,
    entrada      jsonb NOT NULL DEFAULT '{}',
    resultado    text,
    sucesso      boolean NOT NULL,
    hora_local   smallint NOT NULL,
    dia_semana   smallint NOT NULL,
    criado       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS eventos_criado_idx ON eventos (criado);

CREATE TABLE IF NOT EXISTS lembretes (
    id       text PRIMARY KEY,
    texto    text NOT NULL,
    data     text NOT NULL,
    hora     text NOT NULL DEFAULT '',
    tema     text NOT NULL DEFAULT '',
    avisado  boolean NOT NULL DEFAULT false,
    criado   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tarefas (
    id      text PRIMARY KEY,
    texto   text NOT NULL,
    feita   boolean NOT NULL DEFAULT false,
    criado  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS listas (
    id      bigserial PRIMARY KEY,
    lista   text NOT NULL,
    item    text NOT NULL,
    criado  timestamptz NOT NULL DEFAULT now()
);
"""

pool: ConnectionPool | None = None


def init() -> None:
    """Conecta ao Neon e cria as tabelas (só na primeira vez)."""
    global pool
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit(
            "\n  Falta o DATABASE_URL no arquivo .env.\n"
            "  Crie um banco grátis em https://neon.tech, copie a 'connection string'\n"
            "  e cole em DATABASE_URL=... no .env (veja o README).\n")
    pool = ConnectionPool(
        url, min_size=1, max_size=5, open=True,
        kwargs={"autocommit": True, "row_factory": dict_row},
        # O Neon desliga conexões ociosas; isto testa e reconecta antes de usar.
        check=ConnectionPool.check_connection,
    )
    atexit.register(pool.close)
    with pool.connection() as c:
        c.execute(SCHEMA)
    _importar_json_antigo()


def q(sql: str, params=None) -> list[dict]:
    with pool.connection() as c:
        cur = c.execute(sql, params)
        return cur.fetchall() if cur.description else []


def q1(sql: str, params=None) -> dict | None:
    rows = q(sql, params)
    return rows[0] if rows else None


# ======================================================================
# Memória / aprendizado
# ======================================================================

def aprender(conteudo: str, tipo: str = "fato", tags: str = "", importancia: int = 3,
             fonte: str = "conversa") -> str:
    """Guarda uma memória. Se já existir uma muito parecida, atualiza
    (reforça a confiança) em vez de duplicar."""
    conteudo = conteudo.strip()
    if not conteudo:
        return "Nada para aprender."
    tipo = tipo if tipo in TIPOS else "fato"
    importancia = max(1, min(5, int(importancia)))
    parecida = q1(
        """SELECT id, similarity(conteudo, %(c)s) AS s FROM memorias
           WHERE ativo AND conteudo %% %(c)s
           ORDER BY s DESC LIMIT 1""",
        {"c": conteudo})
    if parecida and parecida["s"] >= 0.5:
        q("""UPDATE memorias SET conteudo = %(c)s, tags = %(g)s, tipo = %(t)s,
                 importancia = GREATEST(importancia, %(i)s),
                 confianca = LEAST(1.0, confianca + 0.1), atualizado = now()
             WHERE id = %(id)s""",
          {"c": conteudo, "g": tags, "t": tipo, "i": importancia, "id": parecida["id"]})
        return f"Memória #{parecida['id']} atualizada e reforçada."
    row = q1("""INSERT INTO memorias (tipo, conteudo, tags, importancia, fonte)
                VALUES (%s, %s, %s, %s, %s) RETURNING id""",
             (tipo, conteudo, tags, importancia, fonte))
    return f"Aprendi (memória #{row['id']}, {tipo})."


def _palavras(texto: str) -> list[str]:
    return list(dict.fromkeys(w.lower() for w in re.findall(r"\w{3,}", texto)))[:20]


def buscar(texto: str, limite: int = 6, marcar_uso: bool = True) -> list[dict]:
    """Busca memórias relevantes por texto completo (português) + semelhança."""
    palavras = _palavras(texto)
    if not palavras:
        return []
    rows = q(
        """SELECT id, tipo, conteudo, importancia,
                  (ts_rank(busca, to_tsquery('portuguese', %(tq)s)) * 2
                   + similarity(conteudo, %(txt)s)) * (1 + importancia / 5.0) AS score
           FROM memorias
           WHERE ativo AND (busca @@ to_tsquery('portuguese', %(tq)s)
                            OR conteudo %% %(txt)s)
           ORDER BY score DESC LIMIT %(lim)s""",
        {"tq": " | ".join(palavras), "txt": texto, "lim": limite})
    if rows and marcar_uso:
        q("UPDATE memorias SET usos = usos + 1, ultimo_uso = now() WHERE id = ANY(%s)",
          ([r["id"] for r in rows],))
    return rows


def perfil(limite: int = 30) -> list[dict]:
    """Memórias mais importantes (vão sempre no prompt de sistema)."""
    return q("""SELECT id, tipo, conteudo FROM memorias
                WHERE ativo AND (importancia >= 4 OR tipo IN ('preferencia', 'rotina'))
                ORDER BY importancia DESC, usos DESC, atualizado DESC LIMIT %s""", (limite,))


def esquecer(id: int) -> str:
    r = q1("UPDATE memorias SET ativo = false WHERE id = %s RETURNING id", (int(id),))
    return "Esquecido." if r else "Não encontrei essa memória."


def listar_memorias() -> list[dict]:
    return q("""SELECT id, tipo, conteudo, importancia, usos, confianca,
                       to_char(atualizado, 'DD/MM/YYYY') AS quando
                FROM memorias WHERE ativo ORDER BY atualizado DESC LIMIT 300""")


# ======================================================================
# Conversas, mensagens e eventos
# ======================================================================

def nova_conversa() -> int:
    return q1("INSERT INTO conversas DEFAULT VALUES RETURNING id")["id"]


def salvar_mensagem(conversa_id: int, papel: str, texto: str) -> None:
    if texto:
        q("INSERT INTO mensagens (conversa_id, papel, texto) VALUES (%s, %s, %s)",
          (conversa_id, papel, texto))


def registrar_evento(conversa_id: int | None, ferramenta: str, entrada: dict,
                     resultado: str, sucesso: bool) -> None:
    agora = datetime.now()
    q("""INSERT INTO eventos (conversa_id, ferramenta, entrada, resultado, sucesso, hora_local, dia_semana)
         VALUES (%s, %s, %s, %s, %s, %s, %s)""",
      (conversa_id, ferramenta, Jsonb(entrada), (resultado or "")[:2000], sucesso,
       agora.hour, agora.isoweekday() % 7))


def habitos(limite: int = 8) -> list[dict]:
    """O que o usuário costuma pedir, e em que horário (últimos 45 dias)."""
    return q(
        """SELECT ferramenta,
                  COALESCE(entrada->>'nome', entrada->>'url', entrada->>'consulta',
                           entrada->>'local', entrada->>'caminho') AS alvo,
                  count(*) AS vezes,
                  mode() WITHIN GROUP (ORDER BY hora_local) AS hora_comum
           FROM eventos
           WHERE sucesso AND criado > now() - interval '45 days'
             AND ferramenta IN ('abrir_aplicativo', 'abrir_site', 'pesquisar',
                                'mostrar_globo', 'abrir_pasta', 'executar_comando')
           GROUP BY 1, 2 HAVING count(*) >= 2
           ORDER BY vezes DESC LIMIT %s""", (limite,))


def pendentes_reflexao(conversa_id: int) -> tuple[list[dict], list[dict]]:
    conv = q1("SELECT refletida_ate FROM conversas WHERE id = %s", (conversa_id,))
    desde = conv["refletida_ate"] if conv else 0
    msgs = q("""SELECT id, papel, texto FROM mensagens
                WHERE conversa_id = %s AND id > %s ORDER BY id""", (conversa_id, desde))
    eventos = q("""SELECT ferramenta, entrada, resultado, sucesso FROM eventos
                   WHERE conversa_id = %s ORDER BY id DESC LIMIT 40""", (conversa_id,))
    return msgs, eventos


def marcar_refletida(conversa_id: int, ate_msg: int, resumo: str) -> None:
    q("""UPDATE conversas SET refletida_ate = %s,
             resumo = trim(both ' ' from coalesce(resumo, '') || ' ' || %s)
         WHERE id = %s""", (ate_msg, resumo, conversa_id))


def conversas_nao_refletidas() -> list[int]:
    return [r["conversa_id"] for r in q(
        """SELECT m.conversa_id FROM mensagens m JOIN conversas c ON c.id = m.conversa_id
           GROUP BY m.conversa_id, c.refletida_ate
           HAVING max(m.id) > c.refletida_ate AND count(*) >= 2
           ORDER BY m.conversa_id DESC LIMIT 3""")]


def resumos_recentes(limite: int = 5) -> list[dict]:
    return q("""SELECT to_char(iniciada, 'DD/MM HH24:MI') AS quando, resumo FROM conversas
                WHERE resumo IS NOT NULL AND resumo <> '' ORDER BY id DESC LIMIT %s""", (limite,))


def estatisticas() -> dict:
    return q1("""SELECT (SELECT count(*) FROM memorias WHERE ativo) AS memorias,
                        (SELECT count(*) FROM conversas) AS conversas,
                        (SELECT count(*) FROM eventos) AS acoes,
                        (SELECT count(*) FROM eventos WHERE NOT sucesso) AS falhas""")


# ======================================================================
# Lembretes, tarefas, listas
# ======================================================================

def _id() -> str:
    return uuid.uuid4().hex[:8]


def add_lembrete(texto, data, hora="", tema=""):
    q("INSERT INTO lembretes (id, texto, data, hora, tema) VALUES (%s, %s, %s, %s, %s)",
      (_id(), texto, data, hora or "", tema or ""))


def lembretes(data: str = "") -> list[dict]:
    if data:
        return q("SELECT id, texto, data, hora, tema, avisado FROM lembretes WHERE data = %s ORDER BY hora", (data,))
    return q("SELECT id, texto, data, hora, tema, avisado FROM lembretes ORDER BY data, hora")


def apagar_lembrete(id: str) -> bool:
    return bool(q1("DELETE FROM lembretes WHERE id = %s RETURNING id", (id,)))


def lembretes_vencidos() -> list[dict]:
    agora = datetime.now().strftime("%Y-%m-%d %H:%M")
    return q("""UPDATE lembretes SET avisado = true
                WHERE NOT avisado AND hora <> '' AND (data || ' ' || hora) <= %s
                RETURNING id, texto, data, hora, tema""", (agora,))


def add_tarefa(texto):
    q("INSERT INTO tarefas (id, texto) VALUES (%s, %s)", (_id(), texto))


def tarefas() -> list[dict]:
    return q("SELECT id, texto, feita FROM tarefas ORDER BY feita, criado")


def concluir_tarefa(id: str) -> bool:
    return bool(q1("UPDATE tarefas SET feita = true WHERE id = %s RETURNING id", (id,)))


def add_itens(lista: str, itens: list[str]):
    with pool.connection() as c:
        with c.cursor() as cur:
            cur.executemany("INSERT INTO listas (lista, item) VALUES (%s, %s)",
                            [(lista.lower().strip(), i) for i in itens])


def listas() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in q("SELECT lista, item FROM listas ORDER BY lista, id"):
        out.setdefault(r["lista"], []).append(r["item"])
    return out


def _importar_json_antigo() -> None:
    """Migra os dados da versão antiga (data/memoria.json), uma única vez."""
    arq = Path(__file__).parent / "data" / "memoria.json"
    if not arq.exists():
        return
    try:
        antigo = json.loads(arq.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    for l in antigo.get("lembretes", []):
        add_lembrete(l["texto"], l["data"], l.get("hora", ""), l.get("tema", ""))
    for t in antigo.get("tarefas", []):
        add_tarefa(t["texto"])
    for nome, itens in antigo.get("listas", {}).items():
        add_itens(nome, itens)
    for n in antigo.get("notas", []):
        aprender(n["texto"], "fato", fonte="importado")
    arq.rename(arq.with_suffix(".json.importado"))
