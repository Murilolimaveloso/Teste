/* Avatar de partículas do ORION (Three.js).
 * Formas: "busto" (cabeça + ombros) e "vortice" (enquanto pensa).
 * Estados: repouso, ouvindo, pensando, falando. */
(function () {
  const canvas = document.getElementById('cena');
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x030716, 1);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  camera.position.set(0, 0.1, 6.2);

  const rand = (a, b) => a + Math.random() * (b - a);
  const smooth = (e0, e1, x) => { const t = Math.min(1, Math.max(0, (x - e0) / (e1 - e0))); return t * t * (3 - 2 * t); };

  // ---------------------------------------------------------------- formas
  function pontoBusto(out) {
    const r = Math.random();
    if (r < 0.42) { // cabeça (elipsoide), mais densa no contorno
      const u = rand(0, Math.PI * 2), v = Math.acos(rand(-1, 1));
      let x = 0.56 * Math.sin(v) * Math.cos(u), y = 0.74 * Math.cos(v), z = 0.6 * Math.sin(v) * Math.sin(u);
      if (y < -0.35) { x *= 0.85; } // queixo mais estreito
      out.set(x, y + 1.05, z * (z < 0 ? 0.6 : 1));
      return 1;
    }
    if (r < 0.5) { // pescoço
      const a = rand(0, Math.PI * 2), y = rand(0.05, 0.45);
      out.set(0.25 * Math.cos(a), y, 0.22 * Math.sin(a));
      return 2;
    }
    if (r < 0.9) { // ombros e tronco (mais denso na silhueta)
      const t = Math.pow(Math.random(), 0.9);             // 0 = linha dos ombros, 1 = base
      const borda = Math.random() < 0.45;
      const x = borda ? (Math.random() < 0.5 ? -1 : 1) * rand(0.93, 1) : rand(-1, 1);
      const meia = 0.3 + 1.2 * smooth(0, 0.22, t) - 0.1 * t;
      const ax = Math.abs(x) * meia;
      const topo = 0.22 - 0.3 * smooth(0.25, 1.3, ax) - 0.3 * smooth(1.15, 1.5, ax);
      const y = (Math.random() < 0.18 ? topo : topo - t * 2.1);   // reforça a linha dos ombros
      const prof = 0.42 * Math.sqrt(Math.max(0, 1 - Math.pow(ax / (meia + 0.01), 2)));
      const frente = Math.random() < 0.8 ? 1 : -0.6;
      out.set(Math.sign(x) * ax, y, prof * frente);
      return 3;
    }
    // "veias" de luz que sobem do núcleo no peito até o pescoço
    const ramo = Math.floor(rand(0, 7)), t = Math.random();
    const lado = (ramo - 3) * 0.09;
    const x = lado * Math.pow(t, 1.6) * 1.3 + Math.sin(t * 11 + ramo * 2) * 0.025 * t;
    out.set(x, -1.35 + t * 1.55, 0.44 - t * 0.1);
    return 4;
  }

  function pontoVortice(out, i, n) {
    const t = i / n;                       // altura normalizada
    const y = -1.7 + Math.pow(t, 0.9) * 3.6;
    const raio = 0.08 + 1.35 * Math.pow(1 - t, 1.6) + rand(-0.12, 0.12) * (1 - t);
    const a = rand(0, Math.PI * 2);
    out.set(raio * Math.cos(a), y, raio * Math.sin(a));
  }

  // ---------------------------------------------------------------- avatar
  const N = window.innerWidth < 700 ? 16000 : 30000;
  const busto = new Float32Array(N * 3), vort = new Float32Array(N * 3);
  const tam = new Float32Array(N), semente = new Float32Array(N), brilho = new Float32Array(N);
  const v = new THREE.Vector3();
  for (let i = 0; i < N; i++) {
    const parte = pontoBusto(v);
    busto.set([v.x, v.y, v.z], i * 3);
    pontoVortice(v, i, N);
    vort.set([v.x, v.y, v.z], i * 3);
    tam[i] = parte === 4 ? rand(2.2, 3.4) : rand(1.0, 2.6);
    brilho[i] = parte === 4 ? 1.0 : rand(0.35, 0.9);
    semente[i] = Math.random();
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(busto, 3));
  geo.setAttribute('aVort', new THREE.BufferAttribute(vort, 3));
  geo.setAttribute('aTam', new THREE.BufferAttribute(tam, 1));
  geo.setAttribute('aSem', new THREE.BufferAttribute(semente, 1));
  geo.setAttribute('aBri', new THREE.BufferAttribute(brilho, 1));

  const uni = {
    uTempo: { value: 0 }, uMorph: { value: 0 }, uFala: { value: 0 },
    uOuvir: { value: 0 }, uPx: { value: renderer.getPixelRatio() },
  };
  const mat = new THREE.ShaderMaterial({
    uniforms: uni, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `
      attribute vec3 aVort; attribute float aTam; attribute float aSem; attribute float aBri;
      uniform float uTempo, uMorph, uFala, uOuvir, uPx;
      varying float vBri;
      void main() {
        vec3 p = position;
        // respiração / cintilação
        p += 0.012 * vec3(sin(uTempo*1.3 + aSem*40.0), cos(uTempo*1.1 + aSem*30.0), sin(uTempo*0.9 + aSem*20.0));
        // fala: a cabeça vibra em ondas
        float cab = smoothstep(0.3, 0.6, p.y);
        p.xz *= 1.0 + cab * uFala * 0.06 * sin(uTempo*18.0 + p.y*10.0);
        // ouvindo: partículas se expandem levemente
        p *= 1.0 + uOuvir * 0.03 * sin(uTempo*4.0 + aSem*6.28);
        // vórtice girando
        vec3 q = aVort;
        float ang = uTempo * (1.2 + (1.8 - q.y) * 0.5) + aSem * 0.4;
        q.xz = mat2(cos(ang), -sin(ang), sin(ang), cos(ang)) * q.xz;
        float m = smoothstep(0.0, 1.0, clamp(uMorph * 1.4 - aSem * 0.4, 0.0, 1.0));
        p = mix(p, q, m);
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_Position = projectionMatrix * mv;
        gl_PointSize = aTam * uPx * (3.6 / -mv.z) * (1.0 + uFala * 0.25);
        vBri = aBri * (0.75 + 0.25 * sin(uTempo*2.0 + aSem*50.0));
      }`,
    fragmentShader: `
      varying float vBri;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        if (d > 0.5) discard;
        float a = smoothstep(0.5, 0.0, d);
        vec3 cor = mix(vec3(1.0, 0.68, 0.22), vec3(1.0, 0.95, 0.8), vBri * a);
        gl_FragColor = vec4(cor, a * min(1.0, vBri * 1.25));
      }`,
  });
  const avatar = new THREE.Points(geo, mat);
  const grupo = new THREE.Group();
  grupo.position.y = 0.45;
  grupo.add(avatar);
  scene.add(grupo);

  // Núcleo de luz no peito + brilho do rosto
  function texturaBrilho() {
    const c = document.createElement('canvas'); c.width = c.height = 128;
    const g = c.getContext('2d'), gr = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    gr.addColorStop(0, 'rgba(255,250,230,1)'); gr.addColorStop(0.2, 'rgba(255,200,90,.8)');
    gr.addColorStop(0.5, 'rgba(255,150,30,.2)'); gr.addColorStop(1, 'rgba(255,120,0,0)');
    g.fillStyle = gr; g.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  }
  const texBrilho = texturaBrilho();
  const nucleo = new THREE.Sprite(new THREE.SpriteMaterial({ map: texBrilho, blending: THREE.AdditiveBlending, depthWrite: false }));
  nucleo.position.set(0, -1.4, 0.5); nucleo.scale.set(0.9, 0.9, 1);
  const rosto = new THREE.Sprite(new THREE.SpriteMaterial({ map: texBrilho, blending: THREE.AdditiveBlending, depthWrite: false, opacity: 0.35 }));
  rosto.position.set(0, 1.1, 0.4); rosto.scale.set(1.1, 1.1, 1);
  grupo.add(nucleo, rosto);

  // ---------------------------------------------------------------- fitas (asas/horizonte)
  const NF = window.innerWidth < 700 ? 9000 : 18000;
  const fPos = new Float32Array(NF * 3), fSem = new Float32Array(NF * 2), fCor = new Float32Array(NF);
  for (let i = 0; i < NF; i++) {
    const tipo = Math.random();
    fSem[i * 2] = Math.random(); fSem[i * 2 + 1] = Math.random();
    fCor[i] = Math.random() < 0.22 ? 1 : 0; // 1 = azul
    fPos[i * 3 + 2] = tipo < 0.66 ? (tipo < 0.33 ? -1 : 1) : 0; // -1 asa esq, 1 asa dir, 0 horizonte
  }
  const fGeo = new THREE.BufferGeometry();
  fGeo.setAttribute('position', new THREE.BufferAttribute(fPos, 3));
  fGeo.setAttribute('aSem', new THREE.BufferAttribute(fSem, 2));
  fGeo.setAttribute('aCor', new THREE.BufferAttribute(fCor, 1));
  const fMat = new THREE.ShaderMaterial({
    uniforms: uni, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `
      attribute vec2 aSem; attribute float aCor;
      uniform float uTempo, uFala, uPx;
      varying float vCor; varying float vA;
      void main() {
        float lado = position.z;
        float s = fract(aSem.x + uTempo * 0.03);
        float faixa = (aSem.y - 0.5);
        vec3 p;
        if (abs(lado) > 0.5) {               // asas laterais
          float fita = floor(aSem.y * 6.0);
          float fino = (fract(aSem.y * 6.0) - 0.5) * 0.06;
          float x = 0.8 + s * 4.0;
          float fase = fita * 0.7 + uTempo * (0.6 + fita * 0.08);
          float y = -0.1 + s * 0.55 + (0.25 + 0.5 * s) * sin(s * 3.5 - fase) + (fita - 2.5) * 0.05 * (1.0 + s * 2.0) + fino;
          p = vec3(lado * x, y, -0.6 - s * 0.8 + 0.2 * sin(fase + s * 2.0));
        } else {                              // horizonte ondulado abaixo
          float x = (s - 0.5) * 9.0;
          float fita = floor(aSem.y * 5.0);
          float y = -2.0 + (0.2 + fita * 0.04) * sin(x * 0.8 + uTempo * 0.7 + fita * 0.6) + (fita - 2.0) * 0.06 + (fract(aSem.y * 5.0) - 0.5) * 0.05;
          p = vec3(x, y, -0.3 + faixa);
        }
        p.y += uFala * 0.05 * sin(uTempo*10.0 + p.x*3.0);
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_Position = projectionMatrix * mv;
        gl_PointSize = (1.2 + aSem.y * 1.8) * uPx * (3.0 / -mv.z);
        vCor = aCor;
        vA = smoothstep(0.0, 0.15, s) * smoothstep(1.0, 0.75, s) * (0.6 + 0.4*sin(aSem.x*80.0 + uTempo*3.0));
      }`,
    fragmentShader: `
      varying float vCor; varying float vA;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        if (d > 0.5) discard;
        vec3 cor = mix(vec3(1.0, 0.62, 0.18), vec3(0.3, 0.75, 1.0), vCor);
        gl_FragColor = vec4(cor, smoothstep(0.5, 0.0, d) * vA * 0.8);
      }`,
  });
  scene.add(new THREE.Points(fGeo, fMat));

  // ---------------------------------------------------------------- estrelas
  const NE = 1500, ePos = new Float32Array(NE * 3);
  for (let i = 0; i < NE; i++) ePos.set([rand(-14, 14), rand(-8, 8), rand(-12, -3)], i * 3);
  const eGeo = new THREE.BufferGeometry();
  eGeo.setAttribute('position', new THREE.BufferAttribute(ePos, 3));
  const estrelas = new THREE.Points(eGeo, new THREE.PointsMaterial({ color: 0xffd28a, size: 0.025, transparent: true, opacity: 0.7, blending: THREE.AdditiveBlending, depthWrite: false }));
  scene.add(estrelas);

  // ---------------------------------------------------------------- estado e animação
  const alvo = { morph: 0, fala: 0, ouvir: 0 };
  let estado = 'repouso', mouseX = 0, mouseY = 0, pulsoFala = 0;

  window.Avatar = {
    estado(novo) {
      estado = novo;
      alvo.morph = novo === 'pensando' ? 1 : 0;
      alvo.ouvir = novo === 'ouvindo' ? 1 : 0;
      alvo.fala = novo === 'falando' ? 1 : 0;
    },
    pulso() { pulsoFala = 1; }, // chamado a cada palavra falada
  };

  function redimensionar() {
    const w = window.innerWidth, h = window.innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.position.z = w / h < 0.8 ? 8.5 : 6.2;
    camera.updateProjectionMatrix();
  }
  window.addEventListener('resize', redimensionar);
  window.addEventListener('pointermove', e => {
    mouseX = (e.clientX / window.innerWidth - 0.5);
    mouseY = (e.clientY / window.innerHeight - 0.5);
  });
  redimensionar();

  const relogio = new THREE.Clock();
  (function animar() {
    requestAnimationFrame(animar);
    const dt = Math.min(relogio.getDelta(), 0.05), t = relogio.elapsedTime;
    uni.uTempo.value = t;
    uni.uMorph.value += (alvo.morph - uni.uMorph.value) * dt * 2.2;
    uni.uOuvir.value += (alvo.ouvir - uni.uOuvir.value) * dt * 4;
    pulsoFala *= Math.pow(0.02, dt);
    const falaAlvo = alvo.fala * (0.5 + 0.5 * pulsoFala + 0.2 * Math.sin(t * 13));
    uni.uFala.value += (falaAlvo - uni.uFala.value) * dt * 8;

    avatar.rotation.y += ((mouseX * 0.5) - avatar.rotation.y) * dt * 2;
    avatar.rotation.x += ((mouseY * 0.15) - avatar.rotation.x) * dt * 2;
    const escala = 1 + 0.08 * Math.sin(t * 2) + uni.uFala.value * 0.25 + uni.uMorph.value * 0.3;
    nucleo.scale.set(0.9 * escala, 0.9 * escala, 1);
    nucleo.position.y = -1.4 + uni.uMorph.value * 0.1;
    rosto.material.opacity = (0.3 + uni.uFala.value * 0.4) * (1 - uni.uMorph.value * 0.5);
    estrelas.rotation.y = t * 0.005;
    renderer.render(scene, camera);
  })();
})();
