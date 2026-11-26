/* ORION — interface: voz, conversa, painéis e agenda. */
(function () {
  const $ = s => document.querySelector(s);
  const statusEl = $('#status'), conversa = $('#conversa'), texto = $('#texto'), btnMic = $('#btnMic');
  const PALAVRA = 'orion';

  // ------------------------------------------------------------ estado visual
  function estado(e, msg) {
    Avatar.estado(e);
    statusEl.textContent = msg || { repouso: 'pronto', ouvindo: 'ouvindo…', pensando: 'processando…', falando: 'falando…' }[e];
    btnMic.classList.toggle('ouvindo', e === 'ouvindo');
  }

  function bolha(tipo, txt, extra) {
    const d = document.createElement('div');
    d.className = 'msg ' + tipo; d.textContent = txt;
    if (extra) { const s = document.createElement('span'); s.className = 'acoes'; s.textContent = extra; d.appendChild(s); }
    conversa.appendChild(d); conversa.scrollTop = conversa.scrollHeight;
    while (conversa.children.length > 30) conversa.firstChild.remove();
  }

  // ------------------------------------------------------------ fala (TTS)
  let voz = null;
  function escolherVoz() {
    const vs = speechSynthesis.getVoices().filter(v => v.lang.toLowerCase().startsWith('pt'));
    voz = vs.find(v => /br/i.test(v.lang) && /(natural|online|google)/i.test(v.name)) || vs.find(v => /br/i.test(v.lang)) || vs[0] || null;
  }
  if ('speechSynthesis' in window) { escolherVoz(); speechSynthesis.onvoiceschanged = escolherVoz; }

  function falar(txt) {
    return new Promise(res => {
      if (!('speechSynthesis' in window) || !txt) return res();
      speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(txt);
      u.lang = 'pt-BR'; if (voz) u.voice = voz; u.rate = 1.05;
      u.onstart = () => estado('falando');
      u.onboundary = () => Avatar.pulso();
      u.onend = u.onerror = () => res();
      pausarEscuta();
      speechSynthesis.speak(u);
    }).then(() => { estado('repouso'); retomarEscuta(); });
  }

  // ------------------------------------------------------------ escuta (STT)
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec = null, continuo = false, escutando = false, pausado = false;
  if (SR) {
    rec = new SR();
    rec.lang = 'pt-BR'; rec.interimResults = true; rec.maxAlternatives = 1;
    rec.onresult = e => {
      let final = '', parcial = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        (r.isFinal ? (final += r[0].transcript) : (parcial += r[0].transcript));
      }
      if (parcial) statusEl.textContent = '“' + parcial.trim() + '”';
      if (!final) return;
      final = final.trim();
      if (continuo) {
        const i = final.toLowerCase().indexOf(PALAVRA);
        if (i === -1) return;
        final = final.slice(i + PALAVRA.length).replace(/^[\s,.!]+/, '');
        if (!final) { estado('ouvindo', 'pode falar…'); Avatar.pulso(); return; }
      }
      enviar(final);
    };
    rec.onstart = () => { escutando = true; if (!pausado) estado('ouvindo', continuo ? `diga "${PALAVRA}" + seu pedido` : 'ouvindo…'); };
    rec.onend = () => {
      escutando = false;
      if (continuo && !pausado) { try { rec.start(); } catch (_) {} return; }
      if (statusEl.textContent.startsWith('“') || statusEl.textContent === 'ouvindo…') estado('repouso');
      btnMic.classList.remove('ouvindo');
    };
    rec.onerror = e => {
      if (e.error === 'not-allowed') { continuo = false; atualizarBotaoContinuo(); estado('repouso', 'permita o microfone no navegador'); }
    };
  }

  function ouvir() {
    if (!rec) { estado('repouso', 'reconhecimento de voz indisponível — use o Chrome ou Edge'); return; }
    speechSynthesis.cancel();
    rec.continuous = continuo;
    try { rec.start(); } catch (_) { /* já está ouvindo */ }
  }
  function pausarEscuta() { pausado = true; if (rec && escutando) rec.abort(); }
  function retomarEscuta() { pausado = false; if (continuo) ouvir(); }

  const btnContinuo = $('#btnContinuo');
  function atualizarBotaoContinuo() {
    btnContinuo.textContent = 'Escuta contínua: ' + (continuo ? 'on' : 'off');
    btnContinuo.classList.toggle('ativo', continuo);
  }
  btnContinuo.onclick = () => {
    continuo = !continuo; atualizarBotaoContinuo();
    if (continuo) ouvir(); else if (rec) { rec.abort(); estado('repouso'); }
  };
  btnMic.onclick = () => { if (escutando && !continuo) { rec.stop(); return; } ouvir(); };

  // ------------------------------------------------------------ conversa
  let ocupado = false;
  async function enviar(msg) {
    msg = msg.trim();
    if (!msg || ocupado) return;
    ocupado = true;
    bolha('eu', msg);
    pausarEscuta();
    estado('pensando');
    try {
      const r = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mensagem: msg }) });
      const dados = await r.json();
      if (!r.ok) throw new Error(dados.detail || 'Erro no servidor');
      (dados.acoes || []).forEach(executarAcao);
      if ((dados.ferramentas || []).some(f => /lembrete|tarefa|lista/.test(f))) carregarDados();
      bolha('ia', dados.resposta, dados.ferramentas && dados.ferramentas.length ? '⚙ ' + [...new Set(dados.ferramentas)].join(', ') : '');
      ocupado = false;
      await falar(dados.resposta);
    } catch (err) {
      ocupado = false;
      bolha('erro', err.message);
      estado('repouso', 'erro');
      retomarEscuta();
    }
  }
  $('#entrada').onsubmit = e => { e.preventDefault(); const t = texto.value; texto.value = ''; enviar(t); };
  $('#btnReiniciar').onclick = async () => {
    await fetch('/api/reiniciar', { method: 'POST' });
    conversa.innerHTML = ''; bolha('ia', 'Conversa reiniciada.');
  };

  // ------------------------------------------------------------ painéis
  const paineis = { agenda: $('#painel-agenda'), globo: $('#painel-globo'), relogio: $('#painel-relogio'), memoria: $('#painel-memoria') };
  function abrir(nome) {
    Object.entries(paineis).forEach(([k, el]) => { el.hidden = k !== nome; });
    if (nome === 'globo') Globo.abrir(); else Globo.parar();
    if (nome === 'agenda') carregarDados();
    if (nome === 'memoria') carregarMemoria();
  }
  function fecharTudo() { Object.values(paineis).forEach(el => { el.hidden = true; }); Globo.parar(); }
  document.querySelectorAll('[data-abrir]').forEach(b => { b.onclick = () => (paineis[b.dataset.abrir].hidden ? abrir(b.dataset.abrir) : fecharTudo()); });
  document.querySelectorAll('.fechar').forEach(b => { b.onclick = fecharTudo; });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') fecharTudo(); });

  function executarAcao(a) {
    switch (a.tipo) {
      case 'mostrar_globo': abrir('globo'); Globo.irPara(a.local, a.lat, a.lon, a.satelite); break;
      case 'mostrar_calendario': abrir('agenda'); break;
      case 'mostrar_relogio': abrir('relogio'); break;
      case 'mostrar_memoria': abrir('memoria'); break;
      case 'fechar_paineis': fecharTudo(); break;
    }
  }

  // ------------------------------------------------------------ relógio
  const fmtData = new Intl.DateTimeFormat('pt-BR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  $('#fuso').textContent = Intl.DateTimeFormat().resolvedOptions().timeZone;
  setInterval(() => {
    if (paineis.relogio.hidden) return;
    const d = new Date(), p = n => String(n).padStart(2, '0');
    $('#relHM').textContent = `${p(d.getHours())}:${p(d.getMinutes())}`;
    $('#relS').textContent = `:${p(d.getSeconds())}`;
    $('#relData').textContent = fmtData.format(d);
  }, 250);

  // ------------------------------------------------------------ agenda
  let dados = { lembretes: [], tarefas: [], listas: {} };
  let mes = new Date(); mes.setDate(1);
  let diaSel = isoData(new Date());
  function isoData(d) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; }

  async function carregarDados() {
    try { dados = await (await fetch('/api/dados')).json(); } catch (_) { return; }
    desenharCalendario(); desenharLembretes(); desenharTarefas(); desenharListas();
  }
  $('#agendaAtualizar').onclick = carregarDados;

  document.querySelectorAll('.aba').forEach(b => {
    b.onclick = () => {
      document.querySelectorAll('.aba').forEach(x => x.classList.toggle('ativa', x === b));
      ['cal', 'tar', 'lis'].forEach(k => { $('#aba-' + k).hidden = k !== b.dataset.aba; });
    };
  });

  function desenharCalendario() {
    const nomeMes = mes.toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' });
    $('#mesNome').textContent = nomeMes.charAt(0).toUpperCase() + nomeMes.slice(1);
    const g = $('#calGrade'); g.innerHTML = '';
    ['DOM', 'SEG', 'TER', 'QUA', 'QUI', 'SEX', 'SÁB'].forEach(d => { const e = document.createElement('div'); e.className = 'dow'; e.textContent = d; g.appendChild(e); });
    for (let i = 0; i < mes.getDay(); i++) g.appendChild(document.createElement('div'));
    const hoje = isoData(new Date()), dias = new Date(mes.getFullYear(), mes.getMonth() + 1, 0).getDate();
    const comLembrete = new Set(dados.lembretes.map(l => l.data));
    for (let d = 1; d <= dias; d++) {
      const iso = isoData(new Date(mes.getFullYear(), mes.getMonth(), d));
      const b = document.createElement('button');
      b.className = 'dia' + (iso === hoje ? ' hoje' : '') + (iso === diaSel ? ' sel' : '') + (comLembrete.has(iso) ? ' tem' : '');
      b.textContent = d;
      b.onclick = () => { diaSel = iso; $('#formLembrete').data.value = iso; desenharCalendario(); desenharLembretes(); };
      g.appendChild(b);
    }
  }
  $('#mesAnt').onclick = () => { mes.setMonth(mes.getMonth() - 1); desenharCalendario(); };
  $('#mesProx').onclick = () => { mes.setMonth(mes.getMonth() + 1); desenharCalendario(); };
  $('#mesHoje').onclick = () => { mes = new Date(); mes.setDate(1); diaSel = isoData(new Date()); desenharCalendario(); desenharLembretes(); };
  $('#formLembrete').data.value = diaSel;

  function li(txt, meta, botoes) {
    const e = document.createElement('li');
    const s = document.createElement('span'); s.textContent = txt; e.appendChild(s);
    if (meta) { const m = document.createElement('span'); m.className = 'meta'; m.textContent = meta; e.appendChild(m); }
    (botoes || []).forEach(b => e.appendChild(b));
    return e;
  }
  function botao(txt, titulo, fn) { const b = document.createElement('button'); b.textContent = txt; b.title = titulo; b.onclick = fn; return b; }
  function vazio(ul, msg) { const e = document.createElement('li'); e.className = 'vazio'; e.textContent = msg; ul.appendChild(e); }

  function desenharLembretes() {
    const ul = $('#listaLembretes'); ul.innerHTML = '';
    const itens = dados.lembretes.filter(l => l.data === diaSel).sort((a, b) => (a.hora || '').localeCompare(b.hora || ''));
    if (!itens.length) return vazio(ul, 'Nenhum agendamento. Peça ao Orion ou agende acima!');
    itens.forEach(l => ul.appendChild(li(l.texto, [l.hora, l.tema].filter(Boolean).join(' · '), [
      botao('✕', 'Apagar', async () => { await fetch('/api/lembretes/' + l.id, { method: 'DELETE' }); carregarDados(); }),
    ])));
  }
  $('#formLembrete').onsubmit = async e => {
    e.preventDefault();
    const f = e.target, corpo = { texto: f.texto.value, tema: f.tema.value, data: f.data.value, hora: f.hora.value };
    await fetch('/api/lembretes', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo) });
    f.texto.value = ''; f.tema.value = ''; f.hora.value = ''; diaSel = corpo.data; carregarDados();
  };

  function desenharTarefas() {
    const ul = $('#listaTarefas'); ul.innerHTML = '';
    if (!dados.tarefas.length) return vazio(ul, 'Nenhuma tarefa ainda.');
    dados.tarefas.forEach(t => {
      const e = li(t.texto, '', t.feita ? [] : [botao('✓', 'Concluir', async () => { await fetch(`/api/tarefas/${t.id}/concluir`, { method: 'POST' }); carregarDados(); })]);
      if (t.feita) e.classList.add('feita');
      ul.appendChild(e);
    });
  }
  $('#formTarefa').onsubmit = async e => {
    e.preventDefault();
    await fetch('/api/tarefas', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ texto: e.target.texto.value }) });
    e.target.reset(); carregarDados();
  };

  function desenharListas() {
    const c = $('#listas'); c.innerHTML = '';
    const nomes = Object.keys(dados.listas);
    if (!nomes.length) { c.innerHTML = '<p class="vazio">Nenhuma lista. Ex.: "Orion, coloque leite e pão na lista de compras".</p>'; return; }
    nomes.forEach(n => {
      const h = document.createElement('h3'); h.textContent = n; c.appendChild(h);
      const ul = document.createElement('ul'); ul.className = 'lista';
      dados.listas[n].forEach(i => ul.appendChild(li(i)));
      c.appendChild(ul);
    });
  }
  $('#formLista').onsubmit = async e => {
    e.preventDefault();
    const f = e.target;
    await fetch('/api/listas', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lista: f.lista.value, item: f.item.value }) });
    f.item.value = ''; carregarDados();
  };

  // ------------------------------------------------------------ memória
  const NOMES_TIPO = { fato: 'fato', preferencia: 'preferência', habilidade: 'habilidade', licao: 'lição', rotina: 'rotina' };
  let memoria = { memorias: [], habitos: [] }, filtroTipo = '';
  async function carregarMemoria() {
    try { memoria = await (await fetch('/api/memoria')).json(); } catch (_) { return; }
    const e = memoria.estatisticas || {};
    $('#memStats').textContent = `${e.memorias || 0} memórias · ${e.conversas || 0} conversas · ${e.acoes || 0} ações (${e.falhas || 0} falhas) · guardado no Neon`;
    desenharMemorias();
    const ul = $('#listaHabitos'); ul.innerHTML = '';
    if (!memoria.habitos.length) vazio(ul, 'Ainda observando seu uso…');
    memoria.habitos.forEach(h => ul.appendChild(li(h.alvo || h.ferramenta, `${h.vezes}x · por volta das ${h.hora_comum}h`)));
  }
  function desenharMemorias() {
    const ul = $('#listaMemorias'); ul.innerHTML = '';
    const itens = memoria.memorias.filter(m => !filtroTipo || m.tipo === filtroTipo);
    if (!itens.length) return vazio(ul, 'Nada aprendido aqui ainda. Converse com o Orion!');
    itens.forEach(m => {
      const tag = document.createElement('span'); tag.className = 'tipo'; tag.textContent = NOMES_TIPO[m.tipo] || m.tipo;
      const e = li(m.conteudo, `${'★'.repeat(m.importancia)} · usada ${m.usos}x`, [
        botao('✕', 'Esquecer', async () => { await fetch('/api/memoria/' + m.id, { method: 'DELETE' }); carregarMemoria(); }),
      ]);
      e.prepend(tag); ul.appendChild(e);
    });
  }
  document.querySelectorAll('#memFiltros .mini').forEach(b => {
    b.onclick = () => {
      filtroTipo = b.dataset.tipo;
      document.querySelectorAll('#memFiltros .mini').forEach(x => x.classList.toggle('ativo', x === b));
      desenharMemorias();
    };
  });
  $('#memAtualizar').onclick = carregarMemoria;
  $('#memRefletir').onclick = async e => {
    e.target.textContent = 'Aprendendo…';
    try {
      const r = await (await fetch('/api/memoria/refletir', { method: 'POST' })).json();
      bolha('ia', '🧠 Reflexão: ' + (r.msg || r.detail));
    } finally { e.target.textContent = 'Aprender agora'; carregarMemoria(); }
  };

  // ------------------------------------------------------------ avisos de lembretes
  setInterval(async () => {
    try {
      const avisos = await (await fetch('/api/avisos')).json();
      for (const a of avisos) {
        bolha('ia', '⏰ Lembrete: ' + a.texto);
        if (window.Notification && Notification.permission === 'granted') new Notification('ORION', { body: a.texto });
        await falar('Lembrete: ' + a.texto);
      }
    } catch (_) { /* servidor fora do ar */ }
  }, 15000);
  if (window.Notification && Notification.permission === 'default') {
    document.addEventListener('click', () => Notification.requestPermission(), { once: true });
  }

  estado('repouso', rec ? 'toque no microfone ou digite' : 'digite seu pedido (voz requer Chrome/Edge)');
  setTimeout(() => bolha('ia', 'Olá! Eu sou o Orion. Peça para abrir um app, mostrar um lugar no globo, agendar um lembrete… é só falar.'), 600);
})();
