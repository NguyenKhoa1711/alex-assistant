import * as THREE from 'three';

const stage = document.getElementById('stage');
const hint = document.getElementById('hint');
const hudMode = document.getElementById('hudMode');
const hudAudio = document.getElementById('hudAudio');
const hudVoiceDb = document.getElementById('hudVoiceDb');
const barVoice = document.getElementById('barVoice');
const barHarmonic = document.getElementById('barHarmonic');
const corners = document.querySelectorAll('.corner');

window.__alexReady = false;
window.__alexError = '';

let renderer, scene, camera, rootGroup;
let coronaMesh, coronaUniforms;
let neuralCloud, neuralUniforms;
let innerCore, innerCoreUniforms;
let holoDiscs = [], eqBars = [], filamentLines, orbitalSatellites;
let meshes = [];
let active = !document.hidden, requestedActive = true, reduced = false;
let mode = 'paused', volume = 0, pointerX = 0, pointerY = 0, lastFrame = 0, raf = 0;
let pose = { jaw: 0, yaw: 0, pitch: 0 };
let frames = 0;

// Movie-accurate Marvel J.A.R.V.I.S. / Arc Reactor palettes
const PALETTES = {
  paused:    { primary: new THREE.Color(0x00d2ff), secondary: new THREE.Color(0x0055aa), accent: new THREE.Color(0xffaa00), label: 'J.A.R.V.I.S // STANDBY',    hex: '#00d2ff' },
  listening: { primary: new THREE.Color(0x00f6ff), secondary: new THREE.Color(0xffaa00), accent: new THREE.Color(0x90ffff), label: 'J.A.R.V.I.S // LISTENING',  hex: '#00f6ff' },
  thinking:  { primary: new THREE.Color(0xffaa00), secondary: new THREE.Color(0x00f0ff), accent: new THREE.Color(0xffe57f), label: 'J.A.R.V.I.S // PROCESSING', hex: '#ffaa00' },
  speaking:  { primary: new THREE.Color(0xffae00), secondary: new THREE.Color(0x00f6ff), accent: new THREE.Color(0xffffff), label: 'J.A.R.V.I.S // VOCALIZING', hex: '#ffb700' },
  error:     { primary: new THREE.Color(0xff3b30), secondary: new THREE.Color(0xff8800), accent: new THREE.Color(0xffb3b3), label: 'J.A.R.V.I.S // ALERT',      hex: '#ff453a' }
};

const curPrimary = new THREE.Color(0x00f6ff);
const curSecondary = new THREE.Color(0xffaa00);
const curAccent = new THREE.Color(0x90ffff);

window.alexDiagnostics = () => ({
  ready: window.__alexReady,
  error: window.__alexError,
  frames,
  jaw: pose.jaw,
  meshes: meshes.length,
  active,
  reduced
});

// Create a shader-rendered Polar HUD Disc with crisp thick/thin glowing arcs, degree ticks, and scanner sweeps
function createShaderHudRing(size, tiltX, tiltY, speedZ, variant) {
  const geo = new THREE.PlaneGeometry(size, size);
  const uniforms = {
    uTime: { value: 0 },
    uAudio: { value: 0 },
    uPrimary: { value: curPrimary },
    uSecondary: { value: curSecondary },
    uVariant: { value: variant }
  };
  const mat = new THREE.ShaderMaterial({
    uniforms,
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending,
    vertexShader: `
      varying vec2 vUv;
      void main() {
        vUv = uv * 2.0 - 1.0;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: `
      varying vec2 vUv;
      uniform float uTime;
      uniform float uAudio;
      uniform vec3 uPrimary;
      uniform vec3 uSecondary;
      uniform float uVariant;

      void main() {
        float r = length(vUv);
        if (r > 1.0 || r < 0.18) discard;
        float a = atan(vUv.y, vUv.x);

        // Soft glowing main ring band
        float ring1 = exp(-pow((r - 0.88) * 55.0, 2.0));
        float seg1 = smoothstep(-0.15, 0.15, sin(a * (4.0 + uVariant * 2.0) + uTime * 1.4));

        // Precision degree tick marks
        float tickZone = smoothstep(0.81, 0.82, r) * (1.0 - smoothstep(0.855, 0.865, r));
        float ticks = smoothstep(0.75, 0.92, cos(a * 72.0));
        float majorTicks = smoothstep(0.92, 0.99, cos(a * 12.0)) * smoothstep(0.78, 0.79, r) * (1.0 - smoothstep(0.865, 0.875, r));

        // Inner segmented data track
        float ring2 = exp(-pow((r - 0.72) * 70.0, 2.0));
        float seg2 = step(0.1, sin(a * 8.0 - uTime * 2.1)) * step(-0.3, cos(a * 3.0 + uTime));

        // Audio-reactive glowing arc
        float audioRadius = 0.62 + uAudio * 0.06 * sin(a * 10.0 + uTime * 12.0);
        float ringAudio = exp(-pow((r - audioRadius) * 65.0, 2.0)) * (0.45 + uAudio * 1.4);

        // Rotating radar sweep glow
        float sweep = pow(0.5 + 0.5 * sin(a - uTime * 2.5 + uVariant), 8.0) * smoothstep(0.60, 0.90, r) * (1.0 - smoothstep(0.90, 0.96, r)) * 0.28;

        vec3 col = uPrimary * (ring1 * seg1 * 1.15 + tickZone * ticks * 0.65 + sweep);
        col += uSecondary * (majorTicks * 1.3 + ring2 * seg2 * 0.95 + ringAudio * 1.1);

        float alpha = clamp((ring1 * seg1 + tickZone * ticks * 0.6 + majorTicks + ring2 * seg2 + ringAudio + sweep) * 0.85, 0.0, 0.95);
        if (alpha < 0.01) discard;
        gl_FragColor = vec4(col, alpha);
      }
    `
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.rotation.x = tiltX;
  mesh.rotation.y = tiltY;
  meshes.push(mesh);
  return { mesh, uniforms, tiltX, tiltY, speedZ };
}

function buildMarvelJarvisMk85() {
  rootGroup = new THREE.Group();
  scene.add(rootGroup);

  // 1. Background Volumetric Corona / Arc-Reactor Glow Billboard
  coronaUniforms = {
    uTime: { value: 0 },
    uAudio: { value: 0 },
    uPrimary: { value: curPrimary },
    uSecondary: { value: curSecondary }
  };
  const coronaGeo = new THREE.PlaneGeometry(3.8, 3.8);
  const coronaMat = new THREE.ShaderMaterial({
    uniforms: coronaUniforms,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    vertexShader: `
      varying vec2 vUv;
      void main() {
        vUv = uv * 2.0 - 1.0;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: `
      varying vec2 vUv;
      uniform float uTime;
      uniform float uAudio;
      uniform vec3 uPrimary;
      uniform vec3 uSecondary;
      void main() {
        float r = length(vUv);
        if (r > 1.0) discard;
        float a = atan(vUv.y, vUv.x);
        float rays = 0.5 + 0.5 * sin(a * 16.0 + uTime * 1.2) * cos(a * 9.0 - uTime * 1.8);
        float coreGlow = exp(-r * r * (5.2 - uAudio * 1.8));
        float outerHalo = exp(-pow((r - 0.36 - uAudio * 0.06) * 5.5, 2.0)) * (0.35 + 0.25 * rays);
        vec3 col = mix(uPrimary, uSecondary, clamp(r * 1.1 + uAudio * 0.4, 0.0, 1.0));
        float alpha = clamp(coreGlow * 0.48 + outerHalo * (0.45 + uAudio * 0.5), 0.0, 0.85);
        gl_FragColor = vec4(col * alpha * 1.35, alpha);
      }
    `
  });
  coronaMesh = new THREE.Mesh(coronaGeo, coronaMat);
  scene.add(coronaMesh);
  meshes.push(coronaMesh);

  // 2. Inner Incandescent Quantum Singularity Sphere
  innerCoreUniforms = {
    uTime: { value: 0 },
    uAudio: { value: 0 },
    uPrimary: { value: curPrimary },
    uSecondary: { value: curSecondary },
    uAccent: { value: curAccent }
  };
  const innerGeo = new THREE.SphereGeometry(0.36, 64, 64);
  const innerMat = new THREE.ShaderMaterial({
    uniforms: innerCoreUniforms,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    vertexShader: `
      varying vec3 vNormal;
      varying vec3 vPos;
      varying vec3 vView;
      uniform float uTime;
      uniform float uAudio;
      void main() {
        vPos = position;
        vNormal = normalize(normalMatrix * normal);
        float wave = sin(position.x * 14.0 + uTime * 6.0) * cos(position.y * 14.0 - uTime * 5.0) * sin(position.z * 14.0 + uTime * 4.0);
        float disp = 1.0 + uAudio * 0.22 + wave * (0.04 + uAudio * 0.10);
        vec4 mv = modelViewMatrix * vec4(position * disp, 1.0);
        vView = -mv.xyz;
        gl_Position = projectionMatrix * mv;
      }
    `,
    fragmentShader: `
      varying vec3 vNormal;
      varying vec3 vPos;
      varying vec3 vView;
      uniform float uTime;
      uniform float uAudio;
      uniform vec3 uPrimary;
      uniform vec3 uSecondary;
      uniform vec3 uAccent;
      void main() {
        vec3 viewDir = normalize(vView);
        float ndotv = abs(dot(normalize(vNormal), viewDir));
        float fresnel = pow(1.0 - ndotv, 2.0);
        float hotCenter = pow(ndotv, 2.2);
        float plasma = 0.5 + 0.5 * sin(vPos.x * 26.0 + uTime * 5.0 + cos(vPos.y * 22.0 - uTime * 4.0));
        vec3 col = uAccent * hotCenter * (0.75 + uAudio * 0.6);
        col += mix(uPrimary, uSecondary, plasma) * fresnel * (1.25 + uAudio * 0.8);
        col += uSecondary * pow(plasma, 3.0) * (0.45 + uAudio * 0.7);
        float alpha = clamp(hotCenter * 0.65 + fresnel * 0.90 + plasma * 0.18, 0.25, 0.96);
        gl_FragColor = vec4(col, alpha);
      }
    `
  });
  innerCore = new THREE.Mesh(innerGeo, innerMat);
  rootGroup.add(innerCore);
  meshes.push(innerCore);

  // 3. 3,600-Node 3D Quantum Neural Particle Cloud (with custom Gaussian Bokeh Shader)
  const particleCount = 3600;
  const positions = new Float32Array(particleCount * 3);
  const scales = new Float32Array(particleCount);
  const phases = new Float32Array(particleCount);
  const layers = new Float32Array(particleCount);

  for (let i = 0; i < particleCount; i++) {
    // Fibonacci sphere + multi-shell distribution
    const layer = i < 1800 ? 0.0 : (i < 2900 ? 1.0 : 2.0);
    const u = (i * 0.618033988749895) % 1.0;
    const v = (i % 1800) / 1800.0;
    const theta = u * Math.PI * 2.0;
    const phi = Math.acos(2.0 * v - 1.0);
    const baseR = layer === 0.0 ? (0.52 + (i % 7) * 0.018)
                : (layer === 1.0 ? (0.78 + (i % 11) * 0.022) : (1.15 + (i % 17) * 0.032));
    positions[i * 3]     = baseR * Math.sin(phi) * Math.cos(theta);
    positions[i * 3 + 1] = baseR * Math.sin(phi) * Math.sin(theta);
    positions[i * 3 + 2] = baseR * Math.cos(phi);
    scales[i] = (layer === 0.0 ? 1.0 : (layer === 1.0 ? 1.35 : 0.85)) * (0.65 + (i % 5) * 0.22);
    phases[i] = (i * 1.37) % (Math.PI * 2.0);
    layers[i] = layer;
  }

  const pGeo = new THREE.BufferGeometry();
  pGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  pGeo.setAttribute('aScale', new THREE.BufferAttribute(scales, 1));
  pGeo.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1));
  pGeo.setAttribute('aLayer', new THREE.BufferAttribute(layers, 1));

  neuralUniforms = {
    uTime: { value: 0 },
    uAudio: { value: 0 },
    uPixelRatio: { value: Math.min(window.devicePixelRatio || 1, 1.5) },
    uPrimary: { value: curPrimary },
    uSecondary: { value: curSecondary },
    uAccent: { value: curAccent }
  };

  const pMat = new THREE.ShaderMaterial({
    uniforms: neuralUniforms,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    vertexShader: `
      attribute float aScale;
      attribute float aPhase;
      attribute float aLayer;
      varying float vLayer;
      varying float vPulse;
      uniform float uTime;
      uniform float uAudio;
      uniform float uPixelRatio;

      void main() {
        vLayer = aLayer;
        vec3 pos = position;
        float t = uTime * (1.4 - aLayer * 0.3);
        // 3D harmonic wave turbulence (like movie J.A.R.V.I.S. neural matrix)
        float wave = sin(pos.x * 6.0 + t + aPhase) * cos(pos.y * 6.0 - t * 0.8) * sin(pos.z * 6.0 + t * 1.1);
        float audioBurst = uAudio * (aLayer == 0.0 ? 0.24 : (aLayer == 1.0 ? 0.34 : 0.14));
        pos *= 1.0 + wave * (0.06 + audioBurst) + uAudio * 0.08 * sin(aPhase + uTime * 10.0);

        vPulse = 0.55 + 0.45 * sin(uTime * 3.5 + aPhase) + uAudio * 0.7;
        vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
        gl_Position = projectionMatrix * mvPosition;
        gl_PointSize = aScale * uPixelRatio * (18.0 + uAudio * 10.0) / -mvPosition.z;
      }
    `,
    fragmentShader: `
      varying float vLayer;
      varying float vPulse;
      uniform vec3 uPrimary;
      uniform vec3 uSecondary;
      uniform vec3 uAccent;

      void main() {
        vec2 uv = gl_PointCoord * 2.0 - 1.0;
        float d = length(uv);
        if (d > 1.0) discard;
        // Soft Gaussian bokeh glow + bright white-hot center
        float halo = exp(-d * d * 5.0);
        float core = exp(-d * d * 24.0);
        vec3 baseCol = vLayer < 0.5 ? uPrimary : (vLayer < 1.5 ? uSecondary : mix(uPrimary, uSecondary, 0.5));
        vec3 col = baseCol * halo * vPulse + uAccent * core * 0.9;
        float alpha = clamp((halo * 0.75 + core * 0.5) * vPulse, 0.0, 0.95);
        gl_FragColor = vec4(col, alpha);
      }
    `
  });

  neuralCloud = new THREE.Points(pGeo, pMat);
  rootGroup.add(neuralCloud);

  // 4. Synaptic Neural Filaments connecting inner & middle matrix shells
  const linePositions = [];
  const lineCount = 160;
  for (let i = 0; i < lineCount; i++) {
    const a1 = (i / lineCount) * Math.PI * 2.0;
    const phi1 = Math.acos(2.0 * ((i * 0.381966) % 1.0) - 1.0);
    const r1 = 0.48;
    const r2 = 0.82 + (i % 4) * 0.05;
    const x1 = r1 * Math.sin(phi1) * Math.cos(a1);
    const y1 = r1 * Math.sin(phi1) * Math.sin(a1);
    const z1 = r1 * Math.cos(phi1);
    const x2 = r2 * Math.sin(phi1 + 0.12) * Math.cos(a1 + 0.15);
    const y2 = r2 * Math.sin(phi1 + 0.12) * Math.sin(a1 + 0.15);
    const z2 = r2 * Math.cos(phi1 + 0.12);
    linePositions.push(x1, y1, z1, x2, y2, z2);
  }
  const lineGeo = new THREE.BufferGeometry();
  lineGeo.setAttribute('position', new THREE.Float32BufferAttribute(linePositions, 3));
  const lineMat = new THREE.LineBasicMaterial({
    color: 0x00f6ff,
    transparent: true,
    opacity: 0.22,
    blending: THREE.AdditiveBlending,
    depthWrite: false
  });
  filamentLines = new THREE.LineSegments(lineGeo, lineMat);
  rootGroup.add(filamentLines);

  // 5. 4 Multi-Axis Shader-Rendered Polar HUD Rings (Gyroscopic Stark Rings)
  const disc1 = createShaderHudRing(2.35, 0.25, -0.18, 0.28, 0.0);
  const disc2 = createShaderHudRing(2.65, -0.62, 0.38, -0.35, 1.2);
  const disc3 = createShaderHudRing(2.95, 0.78, 0.52, 0.22, 2.5);
  const disc4 = createShaderHudRing(3.25, 0.05, -0.05, -0.14, 3.8);
  holoDiscs.push(disc1, disc2, disc3, disc4);
  for (const d of holoDiscs) rootGroup.add(d.mesh);

  // 6. 72 Radial 3D Audio Harmonic Prism Bars
  const barCount = 72;
  const barGroup = new THREE.Group();
  rootGroup.add(barGroup);
  for (let i = 0; i < barCount; i++) {
    const angle = (i / barCount) * Math.PI * 2;
    const bGeo = new THREE.BoxGeometry(0.012, 0.075, 0.012);
    const bMat = new THREE.MeshBasicMaterial({
      color: i % 3 === 0 ? 0xffaa00 : 0x00f6ff,
      transparent: true,
      opacity: 0.78,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    });
    const bar = new THREE.Mesh(bGeo, bMat);
    const radius = 1.05;
    bar.position.set(Math.cos(angle) * radius, Math.sin(angle) * radius, 0);
    bar.rotation.z = angle - Math.PI * 0.5;
    barGroup.add(bar);
    eqBars.push({ mesh: bar, angle, baseR: radius });
  }
}

function frameScene() {
  const width = stage.clientWidth, height = stage.clientHeight;
  if (!width || !height || !renderer || !camera) return;
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  const minAspect = Math.min(1.0, camera.aspect);
  camera.position.set(0, 0, 3.95 / Math.pow(minAspect, 0.45));
  camera.lookAt(0, 0, 0);
}

function updateHudDom(pal, energyLevel, t) {
  if (hudMode) hudMode.textContent = pal.label;
  const pct = Math.round(Math.min(100, energyLevel * 145));
  if (hudAudio) {
    hudAudio.textContent = mode === 'speaking' ? `VOICE // ${pct}%` : (mode === 'listening' ? 'MIC // ONLINE' : 'CORE // STABLE');
  }
  if (hudVoiceDb) {
    const db = (-48 + energyLevel * 44).toFixed(1);
    hudVoiceDb.textContent = `${db} dB`;
  }
  if (barVoice) barVoice.style.width = `${Math.max(12, pct)}%`;
  if (barHarmonic) barHarmonic.style.width = `${Math.round(68 + 28 * Math.sin(t * 2.5))}%`;
  corners.forEach(c => { c.style.borderColor = pal.hex; });
}

function loop(ms) {
  if (!active) { raf = 0; return; }
  const pal = PALETTES[mode] || PALETTES.paused;
  curPrimary.lerp(pal.primary, 0.1);
  curSecondary.lerp(pal.secondary, 0.1);
  curAccent.lerp(pal.accent, 0.12);

  if (reduced) {
    pose.jaw = 0;
    if (rootGroup) rootGroup.rotation.set(0, 0, 0);
    updateHudDom(pal, 0, 0);
    if (renderer) renderer.render(scene, camera);
    raf = 0;
    return;
  }

  raf = requestAnimationFrame(loop);
  if (ms - lastFrame < 32) return;
  lastFrame = ms;
  const t = ms / 1000;

  const targetEnergy = mode === 'speaking'
    ? Math.min(0.92, Math.max(0.15, volume * 0.88 + 0.09 * Math.sin(t * 16.0)))
    : (mode === 'thinking' ? 0.34 + 0.14 * Math.sin(t * 8.0) : (mode === 'listening' ? 0.10 + 0.04 * Math.sin(t * 3.0) : 0.03));
  pose.jaw = THREE.MathUtils.lerp(pose.jaw, targetEnergy, 0.35);

  const yaw = pointerX * 0.35 + Math.sin(t * 0.4) * 0.07;
  const pitch = pointerY * 0.25 + Math.cos(t * 0.3) * 0.05;
  pose.yaw = THREE.MathUtils.lerp(pose.yaw, yaw, 0.08);
  pose.pitch = THREE.MathUtils.lerp(pose.pitch, pitch, 0.08);

  if (rootGroup) {
    rootGroup.rotation.y = pose.yaw;
    rootGroup.rotation.x = pose.pitch;
  }

  const speed = mode === 'thinking' ? 2.2 : (mode === 'speaking' ? 1.65 : (mode === 'listening' ? 1.0 : 0.5));

  if (coronaUniforms) {
    coronaUniforms.uTime.value = t;
    coronaUniforms.uAudio.value = pose.jaw;
  }
  if (innerCoreUniforms) {
    innerCoreUniforms.uTime.value = t * speed;
    innerCoreUniforms.uAudio.value = pose.jaw;
  }
  if (neuralUniforms) {
    neuralUniforms.uTime.value = t * speed;
    neuralUniforms.uAudio.value = pose.jaw;
  }
  if (neuralCloud) {
    neuralCloud.rotation.y = t * 0.24 * speed;
    neuralCloud.rotation.z = Math.sin(t * 0.35) * 0.18;
  }
  if (filamentLines) {
    filamentLines.rotation.y = -t * 0.32 * speed;
    filamentLines.rotation.x = t * 0.18 * speed;
    filamentLines.material.color.copy(curPrimary);
    filamentLines.material.opacity = 0.16 + pose.jaw * 0.28;
    filamentLines.scale.setScalar(1.0 + pose.jaw * 0.15);
  }

  for (const d of holoDiscs) {
    d.uniforms.uTime.value = t * speed;
    d.uniforms.uAudio.value = pose.jaw;
    d.mesh.rotation.z += 0.012 * d.speedZ * speed;
    d.mesh.rotation.x = d.tiltX + Math.sin(t * 0.45 * d.speedZ) * 0.14;
    d.mesh.rotation.y = d.tiltY + Math.cos(t * 0.38 * d.speedZ) * 0.14;
  }

  for (let i = 0; i < eqBars.length; i++) {
    const b = eqBars[i];
    const harmonic = Math.abs(Math.sin(i * 0.32 + t * 15.0) * Math.cos(i * 0.19 - t * 10.5));
    const scaleY = 0.4 + (pose.jaw * 4.2 + 0.25) * harmonic;
    b.mesh.scale.y = scaleY;
    const r = b.baseR + pose.jaw * 0.09 * harmonic;
    b.mesh.position.x = Math.cos(b.angle) * r;
    b.mesh.position.y = Math.sin(b.angle) * r;
    b.mesh.material.color.copy(i % 3 === 0 ? curSecondary : curPrimary);
  }

  updateHudDom(pal, pose.jaw, t);

  if (renderer) {
    renderer.render(scene, camera);
    frames++;
  }
}

window.alexState = (nextMode, level, reduce, running) => {
  mode = String(nextMode);
  volume = Math.max(0, Math.min(1, Number(level) || 0));
  reduced = !!reduce;
  requestedActive = !!running;
  active = requestedActive && !document.hidden;
  if (active && !raf) raf = requestAnimationFrame(loop);
};

document.addEventListener('visibilitychange', () => {
  active = requestedActive && !document.hidden;
  if (active && !raf) raf = requestAnimationFrame(loop);
});

stage.addEventListener('pointermove', e => {
  const rect = stage.getBoundingClientRect();
  pointerX = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
  pointerY = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
});
stage.addEventListener('pointerleave', () => { pointerX = pointerY = 0; });
stage.addEventListener('dblclick', () => { console.log('ALEX_EXIT_FULLSCREEN'); });
window.addEventListener('keydown', e => {
  if (e.key === 'Escape') console.log('ALEX_EXIT_FULLSCREEN');
});

try {
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  stage.appendChild(renderer.domElement);

  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(38, 1, 0.1, 30);

  buildMarvelJarvisMk85();
  frameScene();
  new ResizeObserver(frameScene).observe(stage);
  if (hint) hint.remove();
  window.__alexReady = true;
  if (active && !raf) raf = requestAnimationFrame(loop);
} catch (err) {
  window.__alexError = String(err);
  if (hint) hint.textContent = 'Máy chưa mở được đồ họa 3D.';
}
