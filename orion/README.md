# ORION — sua IA pessoal

Assistente de IA com avatar de partículas, voz, agenda e controle do computador.
Roda **no seu computador**: você fala (ou digita), o ORION entende com o Claude
e executa as ações na sua máquina.

## O que ele faz

| Peça assim… | O que acontece |
|---|---|
| "Orion, abre o Spotify" / "abre a calculadora" / "abre o Word" | Abre o aplicativo no seu PC |
| "Toca Coldplay no YouTube" | Pesquisa e abre o vídeo no navegador |
| "Me mostra Tóquio" / "mostra o Rio em satélite" | Globo 3D gira até o local (e abre o mapa de satélite) |
| "Me lembra do dentista amanhã às 10h" | Cria lembrete no calendário; na hora ele avisa falando |
| "Coloca leite e pão na lista de compras" | Adiciona à lista |
| "Que horas são?" / "mostra o relógio" | Relógio holográfico |
| "O que tem na minha tela?" | Tira um print e descreve |
| "Como está meu computador?" | CPU, memória, bateria e disco |
| "Abre minha pasta de Downloads" | Abre a pasta |
| "Cria uma pasta Projetos na área de trabalho" | Roda o comando (só se você ativar comandos) |

O avatar muda conforme o estado: **ouvindo** (pulsa), **pensando** (vira um vórtice de luz)
e **falando** (a cabeça vibra com a voz).

## Como instalar (Windows)

1. Instale o **Python 3.10+** em <https://www.python.org/downloads/> e marque
   **"Add Python to PATH"** durante a instalação.
2. Crie uma chave da API em <https://console.anthropic.com/> → *API Keys*
   (o uso é cobrado por consumo).
3. Baixe esta pasta `orion` e dê dois cliques em **`iniciar.bat`**.
   - Na primeira vez ele instala tudo e abre o arquivo `.env` no Bloco de Notas:
     cole sua chave em `ANTHROPIC_API_KEY=` e salve.
   - Rode o `iniciar.bat` de novo. O navegador abre em <http://localhost:8765>.
4. Use o **Chrome ou Edge** (a voz depende deles) e permita o microfone.

Mac/Linux: `./iniciar.sh`.

## Como usar a voz

- **Botão do microfone**: clique, fale o pedido, ele responde falando.
- **Escuta contínua** (canto superior esquerdo): fica ouvindo o tempo todo;
  comece a frase com **"Orion"** — ex.: *"Orion, abre o WhatsApp"*.

## Configurações (`.env`)

| Variável | Padrão | Para que serve |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Sua chave (obrigatória) |
| `ORION_NOME_USUARIO` | vazio | Como o Orion te chama |
| `ORION_MODELO` | `claude-opus-5-5` | Modelo do Claude |
| `ORION_ESFORCO` | `low` | `low` responde mais rápido; `medium`/`high` pensa mais |
| `ORION_PERMITIR_COMANDOS` | `0` | `1` deixa o Orion rodar comandos do PowerShell (automação livre) |
| `ORION_PORTA` | `8765` | Porta do servidor |

> **Segurança:** com `ORION_PERMITIR_COMANDOS=1` o Orion consegue fazer praticamente
> qualquer coisa no PC via PowerShell. Ele foi instruído a confirmar antes de apagar
> ou alterar o sistema, mas só ative se quiser essa automação total. O servidor
> só aceita conexões do próprio computador (127.0.0.1).

## Como adicionar novos poderes

Tudo está em `tools.py`:

1. Escreva uma função Python que faz a ação.
2. Adicione a definição em `TOOLS` (nome, descrição, parâmetros).
3. Ligue o nome à função em `HANDLERS`.

O Claude passa a usar a nova ferramenta sozinho quando fizer sentido.
Para adicionar um app à lista de "apps conhecidos", edite o dicionário `APPS`.

## Estrutura

```
orion/
├── server.py        # servidor + conversa com o Claude (loop de ferramentas)
├── tools.py         # ferramentas que rodam no seu PC
├── static/
│   ├── index.html   # interface
│   ├── avatar.js    # avatar de partículas (Three.js)
│   ├── globo.js     # globo 3D + mapa de satélite
│   ├── app.js       # voz, conversa, agenda, relógio
│   └── style.css
├── data/            # lembretes, tarefas, listas e memória (criado na 1ª execução)
├── iniciar.bat      # Windows
└── iniciar.sh       # Mac/Linux
```
