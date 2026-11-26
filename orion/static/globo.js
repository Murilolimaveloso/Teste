/* Globo 3D do ORION: gira até qualquer lugar e abre o mapa de satélite. */
(function () {
  const TEX_DIA = 'https://unpkg.com/three-globe@2.31.0/example/img/earth-blue-marble.jpg';
  const TEX_NOITE = 'https://unpkg.com/three-globe@2.31.0/example/img/earth-night.jpg';
  const TEX_RELEVO = 'https://unpkg.com/three-globe@2.31.0/example/img/earth-topology.png';
  const canvas = document.getElementById('globoCanvas');
  const iframe = document.getElementById('mapaSat');
  let renderer, scene, camera, inclina, terra, marcador, rodando = false;
  let alvoLat = -15, alvoLon = -50, lat = 0, lon = 0, dist = 3.2, alvoDist = 3.2;
  let local = { nome: 'Terra', lat: -15.78, lon: -47.93 }, noite = false, auto = true;
  const loader = new THREE.TextureLoader();
  loader.crossOrigin = 'anonymous';

  function iniciar() {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(40, 1, 0.1, 50);
    scene.add(new THREE.AmbientLight(0xffffff, 0.75));
    const sol = new THREE.DirectionalLight(0xffffff, 0.6); sol.position.set(-3, 2, 5); scene.add(sol);

    inclina = new THREE.Group(); scene.add(inclina);
    terra = new THREE.Mesh(
      new THREE.SphereGeometry(1, 96, 96),
      new THREE.MeshPhongMaterial({ map: loader.load(TEX_DIA), bumpMap: loader.load(TEX_RELEVO), bumpScale: 0.04, shininess: 12 })
    );
    inclina.add(terra);
    // atmosfera
    const atm = new THREE.Mesh(new THREE.SphereGeometry(1.06, 64, 64), new THREE.ShaderMaterial({
      transparent: true, side: THREE.BackSide, blending: THREE.AdditiveBlending, depthWrite: false,
      vertexShader: 'varying vec3 n; void main(){ n = normalize(normalMatrix*normal); gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0);}',
      fragmentShader: 'varying vec3 n; void main(){ float i = pow(0.75 - dot(n, vec3(0,0,1.0)), 3.0); gl_FragColor = vec4(0.3,0.7,1.0,1.0)*i; }',
    }));
    scene.add(atm);
    marcador = new THREE.Mesh(new THREE.SphereGeometry(0.012, 16, 16), new THREE.MeshBasicMaterial({ color: 0xffc04a }));
    const halo = new THREE.Mesh(new THREE.RingGeometry(0.02, 0.03, 32), new THREE.MeshBasicMaterial({ color: 0xffc04a, side: THREE.DoubleSide, transparent: true, opacity: 0.8 }));
    marcador.add(halo);
    marcador.userData.halo = halo;
    terra.add(marcador);
    arrastar();
    animar();
  }

  // posição de lat/lon na esfera (mapeamento UV padrão do Three.js)
  function vetor(la, lo, r) {
    const a = la * Math.PI / 180, b = lo * Math.PI / 180;
    return new THREE.Vector3(Math.cos(a) * Math.cos(b) * r, Math.sin(a) * r, -Math.cos(a) * Math.sin(b) * r);
  }

  function arrastar() {
    let ativo = false, px = 0, py = 0;
    canvas.addEventListener('pointerdown', e => { ativo = true; auto = false; px = e.clientX; py = e.clientY; canvas.setPointerCapture(e.pointerId); });
    canvas.addEventListener('pointerup', () => { ativo = false; });
    canvas.addEventListener('pointermove', e => {
      if (!ativo) return;
      const k = 0.25 * (dist - 1) / 2.2;
      alvoLon -= (e.clientX - px) * k; alvoLat += (e.clientY - py) * k;
      alvoLat = Math.max(-85, Math.min(85, alvoLat));
      px = e.clientX; py = e.clientY;
    });
    canvas.addEventListener('wheel', e => { e.preventDefault(); alvoDist = Math.max(1.25, Math.min(6, alvoDist * (e.deltaY > 0 ? 1.1 : 0.9))); }, { passive: false });
  }

  function animar() {
    if (!rodando) return;
    requestAnimationFrame(animar);
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (canvas.width !== Math.floor(w * renderer.getPixelRatio())) {
      renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
    }
    if (auto) alvoLon += 0.03;
    let dl = alvoLon - lon; dl = ((dl + 540) % 360) - 180;
    lon += dl * 0.06; lat += (alvoLat - lat) * 0.06; dist += (alvoDist - dist) * 0.06;
    terra.rotation.y = -Math.PI / 2 - lon * Math.PI / 180;
    inclina.rotation.x = lat * Math.PI / 180;
    camera.position.set(0, 0, dist);
    const s = 1 + 0.4 * Math.sin(performance.now() / 300);
    marcador.userData.halo.scale.set(s, s, s);
    renderer.render(scene, camera);
  }

  function urlSat() {
    const z = Math.round(Math.max(4, Math.min(16, 18 - dist * 3.5)));
    return `https://maps.google.com/maps?q=${local.lat},${local.lon}&t=k&z=${z}&output=embed`;
  }

  function mostrarSat(sim) {
    iframe.hidden = !sim; canvas.hidden = sim;
    document.getElementById('gSat').textContent = sim ? 'Globo 3D' : 'Satélite aqui';
    if (sim) iframe.src = urlSat();
  }

  window.Globo = {
    abrir() {
      if (!renderer) iniciar();
      if (!rodando) { rodando = true; animar(); }
    },
    parar() { rodando = false; },
    irPara(nome, la, lo, satelite) {
      this.abrir();
      local = { nome, lat: la, lon: lo }; auto = false;
      alvoLat = la; alvoLon = lo; alvoDist = 2.0;
      marcador.position.copy(vetor(la, lo, 1.005));
      marcador.lookAt(vetor(la, lo, 2));
      document.getElementById('globoLocal').textContent = nome;
      document.getElementById('globoCoord').textContent = `${Math.abs(la).toFixed(2)}°${la >= 0 ? 'N' : 'S'} · ${Math.abs(lo).toFixed(2)}°${lo >= 0 ? 'L' : 'O'}`;
      mostrarSat(!!satelite);
    },
  };

  document.getElementById('gSat').onclick = () => mostrarSat(!iframe.hidden ? false : true);
  document.getElementById('gZoom').onclick = () => { alvoDist = Math.max(1.25, alvoDist * 0.75); if (!iframe.hidden) iframe.src = urlSat(); };
  document.getElementById('gAfastar').onclick = () => { alvoDist = Math.min(6, alvoDist * 1.3); if (!iframe.hidden) iframe.src = urlSat(); };
  document.getElementById('gNoite').onclick = e => {
    noite = !noite;
    terra.material.map = loader.load(noite ? TEX_NOITE : TEX_DIA); terra.material.needsUpdate = true;
    e.target.textContent = noite ? 'Dia' : 'Noite';
  };
  document.getElementById('gNova').onclick = () => window.open(`https://www.google.com/maps/@${local.lat},${local.lon},14z/data=!3m1!1e3`, '_blank');
})();
