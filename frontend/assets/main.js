import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const CONFIG = {
  timeScale: 0.78,
  rotationSpeedX: 0.002,
  rotationSpeedY: 0.005,
  plasmaScale: 0.1404,
  plasmaBrightness: 1.31,
  voidThreshold: 0.072,
  colorDeep: 0x001433,
  colorMid: 0x0084ff,
  colorBright: 0x00ffe1,
  shellColor: 0x0066ff,
  shellOpacity: 0.41,
  particleCount: 640,
};

const MODE_PROFILES = {
  listening: {
    label: 'LISTENING',
    dot: '#1ed7ff',
    pulseRate: 0.9,
    baseAmplitude: 0.15,
    swirl: 0.78,
    turbulence: 0.24,
    rx: 0.0013,
    ry: 0.0028,
  },
  processing: {
    label: 'PROCESSING',
    dot: '#ffc45f',
    pulseRate: 2.35,
    baseAmplitude: 0.34,
    swirl: 1.34,
    turbulence: 0.64,
    rx: 0.0024,
    ry: 0.0059,
  },
  speaking: {
    label: 'SPEAKING',
    dot: '#58ffbe',
    pulseRate: 3.8,
    baseAmplitude: 0.52,
    swirl: 1.08,
    turbulence: 0.52,
    rx: 0.0033,
    ry: 0.0076,
  },
};

const state = {
  mode: 'listening',
  apiActive: false,
  apiLoad: 0,
  skipPending: false,
  amplitude: 0,
  targetAmplitude: 0,
  responseEnergy: 0,
  speechPulse: 0,
  micVolume: 0,
  micPitch: 0,
  assistantDraft: '',
  transcriptEntries: [],
  browserBattery: null,
  metrics: {
    cpuPercent: null,
    ramPercent: null,
    ramUsedGb: null,
    ramTotalGb: null,
    diskPercent: null,
    diskUsedGb: null,
    diskTotalGb: null,
    temperatureC: null,
    threads: null,
    netDownMBps: null,
    netUpMBps: null,
    netPacketsTotal: null,
    latencyMs: null,
    batteryPercent: null,
    batteryCharging: null,
    batterySecsLeft: null,
    batteryPlugged: null,
    hostname: 'UNKNOWN',
    systemTime: '--:--:--',
    systemDate: '----/--/--',
    uptimeSeconds: 0,
  },
};

const ui = {
  timeHm: byId('timeHm'),
  timeSec: byId('timeSec'),
  timeTz: byId('timeTz'),
  timeDate: byId('timeDate'),
  uptime: byId('uptime'),
  hostName: byId('hostName'),
  battPct: byId('battPct'),
  battStatus: byId('battStatus'),
  battBar: byId('battBar'),
  battVolt: byId('battVolt'),
  battTemp: byId('battTemp'),
  battCycles: byId('battCycles'),
  battSolar: byId('battSolar'),
  battGrid: byId('battGrid'),
  battBackup: byId('battBackup'),
  cpuVal: byId('cpuVal'),
  cpuBar: byId('cpuBar'),
  ramVal: byId('ramVal'),
  ramBar: byId('ramBar'),
  gpuVal: byId('gpuVal'),
  gpuBar: byId('gpuBar'),
  diskVal: byId('diskVal'),
  diskBar: byId('diskBar'),
  tempVal: byId('tempVal'),
  tempBar: byId('tempBar'),
  threadVal: byId('threadVal'),
  modeWaveViewport: byId('modeWaveViewport'),
  modeTagListening: byId('modeTagListening'),
  modeTagProcessing: byId('modeTagProcessing'),
  modeTagSpeaking: byId('modeTagSpeaking'),
  modeWaveNote: byId('modeWaveNote'),
  transcriptLine: byId('transcriptLine'),
  statusText: byId('statusText'),
  statusBarFill: byId('statusBarFill'),
  skipVoiceBtn: byId('skipVoiceBtn'),
  skipVoiceOrb: byId('skipVoiceOrb'),
};

const NOISE_FUNCTIONS = `
  vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec4 permute(vec4 x) { return mod289(((x*34.0)+1.0)*x); }
  vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

  float snoise(vec3 v) {
    const vec2 C = vec2(1.0/6.0, 1.0/3.0);
    const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
    vec3 i = floor(v + dot(v, C.yyy));
    vec3 x0 = v - i + dot(i, C.xxx);
    vec3 g = step(x0.yzx, x0.xyz);
    vec3 l = 1.0 - g;
    vec3 i1 = min(g.xyz, l.zxy);
    vec3 i2 = max(g.xyz, l.zxy);
    vec3 x1 = x0 - i1 + C.xxx;
    vec3 x2 = x0 - i2 + C.yyy;
    vec3 x3 = x0 - D.yyy;
    i = mod289(i);
    vec4 p = permute(permute(permute(
      i.z + vec4(0.0, i1.z, i2.z, 1.0))
      + i.y + vec4(0.0, i1.y, i2.y, 1.0))
      + i.x + vec4(0.0, i1.x, i2.x, 1.0));
    float n_ = 0.142857142857;
    vec3 ns = n_ * D.wyz - D.xzx;
    vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
    vec4 x_ = floor(j * ns.z);
    vec4 y_ = floor(j - 7.0 * x_);
    vec4 x = x_ * ns.x + ns.yyyy;
    vec4 y = y_ * ns.x + ns.yyyy;
    vec4 h = 1.0 - abs(x) - abs(y);
    vec4 b0 = vec4(x.xy, y.xy);
    vec4 b1 = vec4(x.zw, y.zw);
    vec4 s0 = floor(b0) * 2.0 + 1.0;
    vec4 s1 = floor(b1) * 2.0 + 1.0;
    vec4 sh = -step(h, vec4(0.0));
    vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
    vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
    vec3 p0 = vec3(a0.xy, h.x);
    vec3 p1 = vec3(a0.zw, h.y);
    vec3 p2 = vec3(a1.xy, h.z);
    vec3 p3 = vec3(a1.zw, h.w);
    vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
    p0 *= norm.x;
    p1 *= norm.y;
    p2 *= norm.z;
    p3 *= norm.w;
    vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
    m = m * m;
    return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
  }

  float fbm(vec3 p) {
    float total = 0.0;
    float amplitude = 0.5;
    float frequency = 1.0;
    for (int i = 0; i < 3; i++) {
      total += snoise(p * frequency) * amplitude;
      amplitude *= 0.5;
      frequency *= 2.0;
    }
    return total;
  }
`;

const stage = byId('plasmaStage');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x000000);

const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 100);
camera.position.z = 2.85;

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.9;
stage.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.enablePan = false;
controls.minDistance = 1.5;
controls.maxDistance = 20;

const mainGroup = new THREE.Group();
scene.add(mainGroup);

const pointLight = new THREE.PointLight(0x0088ff, 2.0, 10);
mainGroup.add(pointLight);

const shellGeo = new THREE.SphereGeometry(1.0, 64, 64);
const shellShader = {
  vertexShader: `
    varying vec3 vNormal;
    varying vec3 vViewPosition;
    void main() {
      vNormal = normalize(normalMatrix * normal);
      vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
      vViewPosition = -mvPosition.xyz;
      gl_Position = projectionMatrix * mvPosition;
    }
  `,
  fragmentShader: `
    varying vec3 vNormal;
    varying vec3 vViewPosition;
    uniform vec3 uColor;
    uniform float uOpacity;
    void main() {
      float fresnel = pow(1.0 - dot(normalize(vNormal), normalize(vViewPosition)), 2.5);
      gl_FragColor = vec4(uColor, fresnel * uOpacity);
    }
  `,
};

const shellBackMat = new THREE.ShaderMaterial({
  vertexShader: shellShader.vertexShader,
  fragmentShader: shellShader.fragmentShader,
  uniforms: {
    uColor: { value: new THREE.Color(0x000055) },
    uOpacity: { value: 0.28 },
  },
  transparent: true,
  blending: THREE.AdditiveBlending,
  side: THREE.BackSide,
  depthWrite: false,
});

const shellFrontMat = new THREE.ShaderMaterial({
  vertexShader: shellShader.vertexShader,
  fragmentShader: shellShader.fragmentShader,
  uniforms: {
    uColor: { value: new THREE.Color(CONFIG.shellColor) },
    uOpacity: { value: CONFIG.shellOpacity },
  },
  transparent: true,
  blending: THREE.AdditiveBlending,
  side: THREE.FrontSide,
  depthWrite: false,
});

mainGroup.add(new THREE.Mesh(shellGeo, shellBackMat));
mainGroup.add(new THREE.Mesh(shellGeo, shellFrontMat));

const plasmaGeo = new THREE.SphereGeometry(0.998, 128, 128);
const plasmaMat = new THREE.ShaderMaterial({
  uniforms: {
    uTime: { value: 0 },
    uScale: { value: CONFIG.plasmaScale },
    uBrightness: { value: CONFIG.plasmaBrightness },
    uThreshold: { value: CONFIG.voidThreshold },
    uPulse: { value: 0.2 },
    uColorDeep: { value: new THREE.Color(CONFIG.colorDeep) },
    uColorMid: { value: new THREE.Color(CONFIG.colorMid) },
    uColorBright: { value: new THREE.Color(CONFIG.colorBright) },
  },
  vertexShader: `
    uniform float uTime;
    uniform float uPulse;
    varying vec3 vPosition;
    varying vec3 vNormal;
    varying vec3 vViewPosition;

    ${NOISE_FUNCTIONS}

    void main() {
      float displacement = uPulse * 0.035 * snoise(position * 3.0 + vec3(uTime * 0.5));
      vec3 displaced = position + normal * displacement;
      vPosition = displaced;
      vNormal = normalize(normalMatrix * normal);
      vec4 mvPosition = modelViewMatrix * vec4(displaced, 1.0);
      vViewPosition = -mvPosition.xyz;
      gl_Position = projectionMatrix * mvPosition;
    }
  `,
  fragmentShader: `
    uniform float uTime;
    uniform float uScale;
    uniform float uBrightness;
    uniform float uThreshold;
    uniform float uPulse;
    uniform vec3 uColorDeep;
    uniform vec3 uColorMid;
    uniform vec3 uColorBright;

    varying vec3 vPosition;
    varying vec3 vNormal;
    varying vec3 vViewPosition;

    ${NOISE_FUNCTIONS}

    void main() {
      vec3 p = vPosition * uScale;
      vec3 q = vec3(
        fbm(p + vec3(0.0, uTime * 0.05, 0.0)),
        fbm(p + vec3(5.2, 1.3, 2.8) + uTime * 0.05),
        fbm(p + vec3(2.2, 8.4, 0.5) - uTime * 0.02)
      );

      float density = fbm(p * (1.0 + uPulse * 0.35) + 2.0 * q);
      float t = (density + 0.4) * 0.8;
      float alpha = smoothstep(uThreshold, 0.7, t);

      vec3 color = mix(uColorDeep, uColorMid, smoothstep(uThreshold, 0.5, t));
      color = mix(color, uColorBright, smoothstep(0.5, 0.8, t));
      color = mix(color, vec3(1.0), smoothstep(0.8, 1.0, t));
      color *= (1.0 + uPulse * 0.28);

      float facing = dot(normalize(vNormal), normalize(vViewPosition));
      float depthFactor = (facing + 1.0) * 0.5;
      float finalAlpha = alpha * (0.02 + 0.98 * depthFactor);

      gl_FragColor = vec4(color * uBrightness, finalAlpha);
    }
  `,
  transparent: true,
  blending: THREE.AdditiveBlending,
  side: THREE.DoubleSide,
  depthWrite: false,
});

const plasmaMesh = new THREE.Mesh(plasmaGeo, plasmaMat);
mainGroup.add(plasmaMesh);

const particlePositions = new Float32Array(CONFIG.particleCount * 3);
const particleSizes = new Float32Array(CONFIG.particleCount);

for (let i = 0; i < CONFIG.particleCount; i += 1) {
  const r = 0.95 * Math.cbrt(Math.random());
  const theta = Math.random() * Math.PI * 2;
  const phi = Math.acos(2 * Math.random() - 1);
  particlePositions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
  particlePositions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
  particlePositions[i * 3 + 2] = r * Math.cos(phi);
  particleSizes[i] = Math.random();
}

const particleGeo = new THREE.BufferGeometry();
particleGeo.setAttribute('position', new THREE.BufferAttribute(particlePositions, 3));
particleGeo.setAttribute('aSize', new THREE.BufferAttribute(particleSizes, 1));

const particleMat = new THREE.ShaderMaterial({
  uniforms: {
    uTime: { value: 0 },
    uPulse: { value: 0.2 },
    uColor: { value: new THREE.Color(0xffffff) },
  },
  vertexShader: `
    uniform float uTime;
    uniform float uPulse;
    attribute float aSize;
    varying float vAlpha;

    void main() {
      vec3 pos = position;
      float travel = 0.02 + uPulse * 0.05;
      pos.y += sin(uTime * 0.22 + pos.x * 8.0) * travel;
      pos.x += cos(uTime * 0.16 + pos.z * 8.0) * travel;

      vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
      gl_Position = projectionMatrix * mvPosition;

      float baseSize = (8.0 * aSize + 4.0) * (1.0 + uPulse * 0.65);
      gl_PointSize = baseSize * (1.0 / -mvPosition.z);
      vAlpha = 0.78 + 0.22 * sin(uTime + aSize * 10.0);
    }
  `,
  fragmentShader: `
    uniform vec3 uColor;
    varying float vAlpha;

    void main() {
      vec2 uv = gl_PointCoord - vec2(0.5);
      float dist = length(uv);
      if (dist > 0.5) {
        discard;
      }
      float glow = pow(1.0 - dist * 2.0, 1.8);
      gl_FragColor = vec4(uColor, glow * vAlpha);
    }
  `,
  transparent: true,
  blending: THREE.AdditiveBlending,
  depthWrite: false,
});

const particles = new THREE.Points(particleGeo, particleMat);
mainGroup.add(particles);

const modeWaveField = initModeWaveField();
const skipButtonFx = initSkipButtonFx();

buildTickRing();
refreshModeUI();

let recognizer = null;
let recognitionRunning = false;
let sttReconnectEnabled = true;
let sttCooldownUntil = 0;
let sttRearmRequired = false;
let sttRearmState = 'armed';
let sttSilenceSince = 0;
let sttSpeechSince = 0;
let lastSubmittedNorm = '';
let lastSubmittedTs = 0;

const STT_RESUME_DELAY_MS = 1850;
const STT_REARM_SILENCE_MS = 200;
const STT_REARM_SPEECH_MS = 120;
const STT_DUP_WINDOW_MS = 3400;

window.jarvis = {
  setMode(mode) {
    if (!Object.prototype.hasOwnProperty.call(MODE_PROFILES, mode)) {
      return;
    }
    if (mode === 'processing') {
      state.assistantDraft = '';
    }
    state.mode = mode;
    if (mode === 'speaking') {
      sttCooldownUntil = Date.now() + STT_RESUME_DELAY_MS;
      sttRearmRequired = true;
      sttRearmState = 'wait_silence';
      sttSilenceSince = 0;
      sttSpeechSince = 0;
    }
    refreshModeUI();
  },

  setApiActivity(active) {
    state.apiActive = !!active;
    updateSkipButtonState();
  },

  setSystemMetrics(payloadOrCpu, ram, clockTime, dateValue, uptimeSeconds) {
    if (payloadOrCpu && typeof payloadOrCpu === 'object' && !Array.isArray(payloadOrCpu)) {
      ingestMetrics(payloadOrCpu);
      return;
    }

    ingestMetrics({
      cpuPercent: normalizePercent(payloadOrCpu, 1),
      ramPercent: normalizePercent(ram, 1),
      systemTime: safeText(clockTime, '--:--:--'),
      systemDate: safeText(dateValue, '----/--/--'),
      uptimeSeconds: safeNumber(uptimeSeconds),
    });
  },

  onAssistantDelta(delta) {
    if (!delta) {
      return;
    }
    state.assistantDraft += String(delta);
    upsertTranscriptEntry('JARVIS', state.assistantDraft, { replaceLastSameRole: true });
    state.responseEnergy = clamp(state.responseEnergy + String(delta).length / 220, 0, 1.2);
  },

  onUserTranscript(text) {
    state.assistantDraft = '';
    upsertTranscriptEntry('YOU', safeText(text, ''));
    state.mode = 'processing';
    refreshModeUI();
  },

  setMicFeatures(volume, pitch, speaking) {
    applyMicFeatures(Number(volume || 0), Number(pitch || 0), !!speaking);
  },
};

initMicReactivity();
initSpeechRecognition();
initBrowserBatteryMetrics();
initSkipVoiceButton();

notifyPythonReady();
window.addEventListener('pywebviewready', notifyPythonReady);

const clock = new THREE.Clock();
setInterval(updateHud, 350);
updateHud();

function animate() {
  requestAnimationFrame(animate);
  const t = clock.getElapsedTime();
  const profile = MODE_PROFILES[state.mode] || MODE_PROFILES.listening;

  state.responseEnergy = Math.max(0, state.responseEnergy - 0.012);
  state.speechPulse *= 0.915;
  state.apiLoad += ((state.apiActive ? 1 : 0) - state.apiLoad) * 0.08;

  const cpuNorm = normalizePercent(state.metrics.cpuPercent, 100) || 0;
  const ramNorm = normalizePercent(state.metrics.ramPercent, 100) || 0;
  const workload = (cpuNorm + ramNorm) * 0.5;

  const voiceEnergy = Math.max(state.micVolume * 0.82, state.speechPulse, state.responseEnergy);
  const pulseWave = 0.5 + 0.5 * Math.sin(t * profile.pulseRate * Math.PI * 2);

  state.targetAmplitude = clamp(
    profile.baseAmplitude +
      voiceEnergy * 0.82 +
      state.apiLoad * 0.22 +
      workload * 0.18 +
      pulseWave * 0.16,
    0,
    1.22,
  );
  state.amplitude += (state.targetAmplitude - state.amplitude) * 0.11;

  const timeScale = profile.swirl + state.apiLoad * 0.32 + workload * 0.2 + state.micVolume * 0.3;
  const brightness = CONFIG.plasmaBrightness + state.amplitude * 0.64 + pulseWave * 0.18;

  plasmaMat.uniforms.uScale.value = CONFIG.plasmaScale * (1 + profile.turbulence * 0.16 + state.amplitude * 0.08);
  plasmaMat.uniforms.uBrightness.value = brightness;
  plasmaMat.uniforms.uTime.value = t * timeScale;
  plasmaMat.uniforms.uPulse.value = state.amplitude;

  const tintStrength = clamp(state.micPitch + (state.mode === 'processing' ? 0.2 : 0), 0, 1);
  const tintMid = new THREE.Color(CONFIG.colorMid).lerp(new THREE.Color(0x00cfff), tintStrength);
  const tintBright = new THREE.Color(CONFIG.colorBright).lerp(new THREE.Color(0x7fffea), tintStrength * 0.65);
  plasmaMat.uniforms.uColorMid.value.copy(tintMid);
  plasmaMat.uniforms.uColorBright.value.copy(tintBright);

  particleMat.uniforms.uTime.value = t;
  particleMat.uniforms.uPulse.value = state.amplitude;

  plasmaMesh.rotation.y = t * (0.08 + profile.swirl * 0.04 + state.apiLoad * 0.08);

  const rotationBoost = 1 + state.amplitude * 1.15 + state.apiLoad * 0.52;
  mainGroup.rotation.x += (profile.rx + CONFIG.rotationSpeedX * 0.24) * rotationBoost;
  mainGroup.rotation.y += (profile.ry + CONFIG.rotationSpeedY * 0.24) * rotationBoost;

  shellFrontMat.uniforms.uOpacity.value = CONFIG.shellOpacity + state.amplitude * 0.22 + state.apiLoad * 0.1;
  updateModeWaveField(t, profile);
  updateSkipButtonFx(t);
  controls.update();
  renderer.render(scene, camera);
}

animate();

window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  resizeModeWaveField();
  resizeSkipButtonFx();
});

function ingestMetrics(payload) {
  const m = state.metrics;

  m.cpuPercent = normalizePercent(payload.cpuPercent, 100);
  m.ramPercent = normalizePercent(payload.ramPercent, 100);
  m.ramUsedGb = safeNumber(payload.ramUsedGb);
  m.ramTotalGb = safeNumber(payload.ramTotalGb);
  m.diskPercent = normalizePercent(payload.diskPercent, 100);
  m.diskUsedGb = safeNumber(payload.diskUsedGb);
  m.diskTotalGb = safeNumber(payload.diskTotalGb);
  m.temperatureC = safeNumber(payload.temperatureC);
  m.threads = safeInteger(payload.threads);
  m.netDownMBps = safeNumber(payload.netDownMBps);
  m.netUpMBps = safeNumber(payload.netUpMBps);
  m.netPacketsTotal = safeNumber(payload.netPacketsTotal);
  m.latencyMs = safeNumber(payload.latencyMs);
  m.batteryPercent = normalizePercent(payload.batteryPercent, 100);
  m.batteryCharging = parseNullableBoolean(payload.batteryCharging);
  m.batteryPlugged = parseNullableBoolean(payload.batteryPlugged);
  m.batterySecsLeft = safeNumber(payload.batterySecsLeft);
  m.hostname = safeText(payload.hostname, m.hostname || 'UNKNOWN');
  m.systemTime = safeText(payload.systemTime, m.systemTime || '--:--:--');
  m.systemDate = safeText(payload.systemDate, m.systemDate || '----/--/--');
  m.uptimeSeconds = Math.max(0, safeInteger(payload.uptimeSeconds) || 0);

  updateHud();
}

function updateHud() {
  const now = new Date();
  const h = String(now.getHours()).padStart(2, '0');
  const m = String(now.getMinutes()).padStart(2, '0');
  const s = String(now.getSeconds()).padStart(2, '0');
  ui.timeHm.textContent = `${h}:${m}`;
  ui.timeSec.textContent = `:${s}`;

  const days = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
  const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
  ui.timeDate.textContent = `${days[now.getDay()]} ${months[now.getMonth()]} ${now.getDate()}, ${now.getFullYear()}`;

  const tzMinutes = -now.getTimezoneOffset();
  const sign = tzMinutes >= 0 ? '+' : '-';
  const tzHour = String(Math.floor(Math.abs(tzMinutes) / 60)).padStart(2, '0');
  const tzMin = String(Math.abs(tzMinutes) % 60).padStart(2, '0');
  ui.timeTz.textContent = `UTC${sign}${tzHour}:${tzMin}`;

  ui.uptime.textContent = formatUptime(state.metrics.uptimeSeconds);
  ui.hostName.textContent = (state.metrics.hostname || 'UNKNOWN').toUpperCase().slice(0, 14);

  updatePowerWidget();
  updateSystemWidget();
  updateModeWaveLegend();
  updateStatusLine();
}

function updatePowerWidget() {
  const battery = resolvedBattery();
  const pct = battery.percent;
  const charging = battery.charging;

  if (pct == null) {
    ui.battPct.textContent = '--%';
    ui.battStatus.textContent = 'UNAVAILABLE';
    ui.battBar.style.width = '0%';
    ui.battSolar.textContent = 'UNKNOWN';
    ui.battGrid.textContent = '--';
    ui.battBackup.textContent = '--';
    ui.battVolt.textContent = '--.-V';
  } else {
    const rounded = Math.round(pct);
    ui.battPct.textContent = `${rounded}%`;
    ui.battStatus.textContent = charging === true ? 'CHARGING' : 'DISCHARGING';
    ui.battBar.style.width = `${rounded}%`;
    ui.battSolar.textContent = charging === true ? 'CONNECTED' : 'OFFLINE';
    ui.battBackup.textContent = `${Math.max(0, Math.min(100, rounded))}%`;
    ui.battVolt.textContent = `${(11.2 + rounded * 0.016).toFixed(1)}V`;

    if (battery.secsLeft == null || battery.secsLeft < 0) {
      ui.battGrid.textContent = charging === true ? 'FULL SOON' : '--';
    } else {
      ui.battGrid.textContent = formatCountdown(battery.secsLeft);
    }
  }

  const temp = state.metrics.temperatureC;
  ui.battTemp.textContent = temp == null ? '--.-C' : `${temp.toFixed(1)}C`;
  ui.battCycles.textContent = state.metrics.threads == null ? '--' : String(state.metrics.threads);
}

function updateSystemWidget() {
  const cpu = state.metrics.cpuPercent;
  const ram = state.metrics.ramPercent;
  const disk = state.metrics.diskPercent;
  const temp = state.metrics.temperatureC;

  ui.cpuVal.textContent = cpu == null ? '--%' : `${Math.round(cpu)}%`;
  ui.cpuBar.style.width = `${cpu == null ? 0 : clamp(cpu, 0, 100)}%`;

  if (ram != null && state.metrics.ramUsedGb != null) {
    ui.ramVal.textContent = `${state.metrics.ramUsedGb.toFixed(1)}G`;
  } else if (ram != null) {
    ui.ramVal.textContent = `${Math.round(ram)}%`;
  } else {
    ui.ramVal.textContent = '--';
  }
  ui.ramBar.style.width = `${ram == null ? 0 : clamp(ram, 0, 100)}%`;

  ui.gpuVal.textContent = 'N/A';
  ui.gpuBar.style.width = '0%';

  if (disk != null && state.metrics.diskUsedGb != null) {
    ui.diskVal.textContent = `${state.metrics.diskUsedGb.toFixed(0)}G`;
  } else if (disk != null) {
    ui.diskVal.textContent = `${Math.round(disk)}%`;
  } else {
    ui.diskVal.textContent = '--';
  }
  ui.diskBar.style.width = `${disk == null ? 0 : clamp(disk, 0, 100)}%`;

  ui.tempVal.textContent = temp == null ? '--.-C' : `${temp.toFixed(1)}C`;
  ui.tempBar.style.width = `${temp == null ? 0 : clamp((temp / 95) * 100, 0, 100)}%`;

  ui.threadVal.textContent = state.metrics.threads == null ? '--' : String(state.metrics.threads);
}

function updateModeWaveLegend() {
  const mode = state.mode;
  if (ui.modeTagListening) {
    ui.modeTagListening.classList.toggle('active', mode === 'listening');
  }
  if (ui.modeTagProcessing) {
    ui.modeTagProcessing.classList.toggle('active', mode === 'processing');
  }
  if (ui.modeTagSpeaking) {
    ui.modeTagSpeaking.classList.toggle('active', mode === 'speaking');
  }

  if (!ui.modeWaveNote) {
    return;
  }

  if (mode === 'processing') {
    ui.modeWaveNote.textContent = 'PROCESSING WAVEFIELD AMPLIFIED';
  } else if (mode === 'speaking') {
    ui.modeWaveNote.textContent = 'SPEECH WAVEFIELD LOCKED';
  } else {
    ui.modeWaveNote.textContent = 'LISTENING WAVEFIELD STABLE';
  }
}

function updateStatusLine() {
  const profile = MODE_PROFILES[state.mode] || MODE_PROFILES.listening;
  const temperature = state.metrics.temperatureC;
  const cpu = state.metrics.cpuPercent;

  let text;
  if (state.mode === 'processing') {
    text = 'PROCESSING REQUEST - CONTEXT ENGINE ACTIVE';
  } else if (state.mode === 'speaking') {
    text = 'SPEECH SYNTHESIS ACTIVE - RESPONSE STREAMING';
  } else if (temperature != null && temperature > 78) {
    text = 'THERMAL LOAD ELEVATED - COOLING PRIORITIZED';
  } else if (cpu != null && cpu > 90) {
    text = 'CPU LOAD HIGH - THROTTLING NON-CRITICAL TASKS';
  } else {
    text = 'ALL SYSTEMS NOMINAL - PLASMA CORE STABLE';
  }

  ui.statusText.textContent = text;
  ui.statusText.style.color = profile.dot;
  const barRate = 2.9 / Math.max(0.5, profile.pulseRate * 0.55);
  ui.statusBarFill.style.animationDuration = `${barRate.toFixed(2)}s`;
}

function refreshModeUI() {
  document.body.dataset.mode = state.mode;
  updateModeWaveLegend();
  updateStatusLine();
  updateSkipButtonState();
}

function isSkipActionAvailable() {
  if (state.skipPending) {
    return false;
  }
  if (state.mode === 'speaking' || state.mode === 'processing') {
    return true;
  }
  return !!state.apiActive;
}

function updateSkipButtonState() {
  if (!ui.skipVoiceBtn) {
    return;
  }

  const available = isSkipActionAvailable();
  ui.skipVoiceBtn.disabled = !available;
  ui.skipVoiceBtn.classList.toggle('ready', available);
  ui.skipVoiceBtn.classList.toggle('speaking', state.mode === 'speaking');
  ui.skipVoiceBtn.classList.toggle('working', state.mode === 'processing');
  ui.skipVoiceBtn.classList.toggle('pending', !!state.skipPending);
}

function initSkipVoiceButton() {
  if (!ui.skipVoiceBtn) {
    return;
  }

  ui.skipVoiceBtn.addEventListener('click', async () => {
    if (!isSkipActionAvailable()) {
      return;
    }

    state.skipPending = true;
    updateSkipButtonState();

    try {
      if (window.pywebview && window.pywebview.api && window.pywebview.api.skip_current_reply) {
        await window.pywebview.api.skip_current_reply();
      }
    } catch (_) {
      // Ignore UI-side errors; runtime handles interruption best-effort.
    } finally {
      state.skipPending = false;
      updateSkipButtonState();
    }
  });

  updateSkipButtonState();
}

function setTranscript(text) {
  ui.transcriptLine.textContent = safeText(text, 'READY FOR VOICE COMMANDS');
  ui.transcriptLine.scrollTop = ui.transcriptLine.scrollHeight;
}

function upsertTranscriptEntry(role, text, options = {}) {
  const message = safeText(text, '');
  if (!message) {
    return;
  }

  const normalizedMessage = message.replace(/\s+/g, ' ').trim();
  if (!normalizedMessage) {
    return;
  }

  const entry = `${role}: ${normalizedMessage}`;
  if (options.replaceLastSameRole && state.transcriptEntries.length > 0) {
    const last = state.transcriptEntries[state.transcriptEntries.length - 1];
    if (last.startsWith(`${role}:`)) {
      state.transcriptEntries[state.transcriptEntries.length - 1] = entry;
    } else {
      state.transcriptEntries.push(entry);
    }
  } else {
    const last = state.transcriptEntries[state.transcriptEntries.length - 1];
    if (last !== entry) {
      state.transcriptEntries.push(entry);
    }
  }

  if (state.transcriptEntries.length > 5) {
    state.transcriptEntries = state.transcriptEntries.slice(-5);
  }

  setTranscript(state.transcriptEntries.join('\n'));
}

function initModeWaveField() {
  if (!ui.modeWaveViewport) {
    return null;
  }

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x000000, 0);
  ui.modeWaveViewport.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 10);
  camera.position.z = 3;

  const bars = [];
  const barCount = 42;
  const barWidth = 0.032;
  const barHeight = 0.08;
  const baseY = -0.95;

  for (let i = 0; i < barCount; i += 1) {
    const x = -0.96 + (1.92 * i) / (barCount - 1);

    const glow = new THREE.Mesh(
      new THREE.PlaneGeometry(barWidth * 1.9, barHeight),
      new THREE.MeshBasicMaterial({
        color: 0x1ed7ff,
        transparent: true,
        opacity: 0.18,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );

    const core = new THREE.Mesh(
      new THREE.PlaneGeometry(barWidth, barHeight),
      new THREE.MeshBasicMaterial({
        color: 0x80f4ff,
        transparent: true,
        opacity: 0.78,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );

    glow.position.set(x, baseY + barHeight * 0.5, -0.01);
    core.position.set(x, baseY + barHeight * 0.5, 0.02);
    scene.add(glow);
    scene.add(core);

    bars.push({
      glow,
      core,
      phase: Math.random() * Math.PI * 2,
      baseY,
      baseHeight: barHeight,
      indexNorm: i / (barCount - 1),
    });
  }

  const field = { renderer, scene, camera, bars };
  resizeModeWaveField(field);
  return field;
}

function resizeModeWaveField(field = modeWaveField) {
  if (!field || !ui.modeWaveViewport) {
    return;
  }
  const width = Math.max(20, ui.modeWaveViewport.clientWidth);
  const height = Math.max(20, ui.modeWaveViewport.clientHeight);
  field.renderer.setSize(width, height, false);
}

function updateModeWaveField(timeSeconds, profile) {
  if (!modeWaveField) {
    return;
  }

  const accent = new THREE.Color(profile.dot);
  const highlight = accent.clone().lerp(new THREE.Color(0xffffff), 0.45);

  const intensity = clamp(
    profile.baseAmplitude +
      state.micVolume * 0.95 +
      state.speechPulse * 0.58 +
      state.responseEnergy * 0.35 +
      state.apiLoad * 0.35,
    0.12,
    1.65,
  );

  for (const bar of modeWaveField.bars) {
    const u = bar.indexNorm;
    const envelope = Math.pow(Math.sin(Math.PI * u), 1.15);
    const waveA = 0.5 + 0.5 * Math.sin(timeSeconds * profile.pulseRate * 6.2 + u * 16.0 + bar.phase);
    const waveB = 0.5 + 0.5 * Math.sin(timeSeconds * profile.pulseRate * 3.9 - u * 11.0 + state.micPitch * 4.0);
    const ripple = 0.5 + 0.5 * Math.sin(timeSeconds * 1.4 + u * 8.0 + state.apiLoad * 3.0);
    const composite = (waveA * 0.62 + waveB * 0.38) * envelope * (0.72 + ripple * 0.28);

    const height = bar.baseHeight + composite * (0.22 + intensity * 0.56);
    const scaleYCore = Math.max(0.2, height / bar.baseHeight);
    const scaleYGlow = scaleYCore * 1.22;

    bar.core.scale.y = scaleYCore;
    bar.glow.scale.y = scaleYGlow;
    bar.core.position.y = bar.baseY + (bar.baseHeight * scaleYCore) * 0.5;
    bar.glow.position.y = bar.baseY + (bar.baseHeight * scaleYGlow) * 0.5;

    bar.core.material.color.copy(accent).lerp(highlight, composite * 0.55);
    bar.glow.material.color.copy(accent);
    bar.core.material.opacity = 0.3 + composite * 0.62;
    bar.glow.material.opacity = 0.08 + composite * 0.25;
  }

  modeWaveField.renderer.render(modeWaveField.scene, modeWaveField.camera);
}

function initSkipButtonFx() {
  if (!ui.skipVoiceOrb) {
    return null;
  }

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x000000, 0);
  ui.skipVoiceOrb.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(44, 1, 0.1, 10);
  camera.position.z = 2.4;

  const ring = new THREE.Mesh(
    new THREE.TorusGeometry(0.62, 0.14, 18, 48),
    new THREE.MeshStandardMaterial({
      color: 0x6fdcff,
      emissive: 0x1a5f7a,
      emissiveIntensity: 0.7,
      metalness: 0.45,
      roughness: 0.24,
    }),
  );
  scene.add(ring);

  const core = new THREE.Mesh(
    new THREE.IcosahedronGeometry(0.28, 1),
    new THREE.MeshStandardMaterial({
      color: 0xa8f2ff,
      emissive: 0x22a6c8,
      emissiveIntensity: 0.8,
      metalness: 0.28,
      roughness: 0.2,
    }),
  );
  scene.add(core);

  const keyLight = new THREE.PointLight(0x74e3ff, 1.1, 6.0);
  keyLight.position.set(1.8, 1.6, 2.2);
  scene.add(keyLight);

  const rimLight = new THREE.PointLight(0x00ffd9, 0.9, 5.0);
  rimLight.position.set(-1.6, -1.5, 1.4);
  scene.add(rimLight);

  const fx = {
    renderer,
    scene,
    camera,
    ring,
    core,
  };
  resizeSkipButtonFx(fx);
  return fx;
}

function resizeSkipButtonFx(fx = skipButtonFx) {
  if (!fx || !ui.skipVoiceOrb) {
    return;
  }
  const width = Math.max(8, ui.skipVoiceOrb.clientWidth);
  const height = Math.max(8, ui.skipVoiceOrb.clientHeight);
  fx.camera.aspect = width / height;
  fx.camera.updateProjectionMatrix();
  fx.renderer.setSize(width, height, false);
}

function updateSkipButtonFx(timeSeconds) {
  if (!skipButtonFx) {
    return;
  }

  const active = isSkipActionAvailable();
  const speakingBoost = state.mode === 'speaking' ? 1 : 0;
  const processingBoost = state.mode === 'processing' ? 1 : 0;
  const pulse = 0.5 + 0.5 * Math.sin(timeSeconds * (2.2 + speakingBoost * 1.6 + processingBoost * 0.6));

  skipButtonFx.ring.rotation.z += 0.014 + speakingBoost * 0.012 + processingBoost * 0.007;
  skipButtonFx.ring.rotation.x += 0.003;
  skipButtonFx.core.rotation.x += 0.018;
  skipButtonFx.core.rotation.y -= 0.015;

  const ringMaterial = skipButtonFx.ring.material;
  const coreMaterial = skipButtonFx.core.material;

  if (active) {
    ringMaterial.emissiveIntensity = 0.6 + pulse * (0.35 + speakingBoost * 0.25);
    coreMaterial.emissiveIntensity = 0.74 + pulse * (0.38 + speakingBoost * 0.2);
  } else {
    ringMaterial.emissiveIntensity = 0.22;
    coreMaterial.emissiveIntensity = 0.26;
  }

  skipButtonFx.renderer.render(skipButtonFx.scene, skipButtonFx.camera);
}

function applyMicFeatures(volume, pitch, speaking) {
  state.micVolume = clamp(volume, 0, 1);
  state.micPitch = clamp(pitch, 0, 1);

  if (speaking) {
    state.speechPulse = clamp(state.speechPulse + 0.09, 0, 1.2);
  }

  if (!sttRearmRequired || state.mode !== 'listening') {
    return;
  }

  const now = Date.now();
  if (sttRearmState === 'wait_silence') {
    if (speaking) {
      sttSilenceSince = 0;
    } else {
      if (!sttSilenceSince) {
        sttSilenceSince = now;
      }
      if ((now - sttSilenceSince) >= STT_REARM_SILENCE_MS) {
        sttRearmState = 'wait_speech';
        sttSpeechSince = 0;
      }
    }
  } else if (sttRearmState === 'wait_speech') {
    if (speaking) {
      if (!sttSpeechSince) {
        sttSpeechSince = now;
      }
      if ((now - sttSpeechSince) >= STT_REARM_SPEECH_MS) {
        sttRearmRequired = false;
        sttRearmState = 'armed';
      }
    } else {
      sttSpeechSince = 0;
    }
  }
}

async function initMicReactivity() {
  try {
    const media = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });

    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    const audioCtx = new AudioCtx();
    const src = audioCtx.createMediaStreamSource(media);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 2048;
    analyser.smoothingTimeConstant = 0.72;
    src.connect(analyser);

    const tData = new Float32Array(analyser.fftSize);

    const loop = () => {
      analyser.getFloatTimeDomainData(tData);
      let sumSq = 0;
      for (let i = 0; i < tData.length; i += 1) {
        sumSq += tData[i] * tData[i];
      }

      const rms = Math.sqrt(sumSq / tData.length);
      const volume = clamp(rms * 5.2, 0, 1);
      const pitch = detectPitch(tData, audioCtx.sampleRate);
      const speaking = volume > 0.06;

      applyMicFeatures(volume, pitch, speaking);
      requestAnimationFrame(loop);
    };

    loop();
    setTranscript('MIC CONNECTED - ALWAYS LISTENING');
  } catch (error) {
    setTranscript('MIC PERMISSION REQUIRED FOR VOICE MODE');
    console.error('Microphone init failed:', error);
  }
}

function detectPitch(buffer, sampleRate) {
  let bestOffset = -1;
  let bestCorr = 0;
  const minLag = Math.floor(sampleRate / 300);
  const maxLag = Math.floor(sampleRate / 70);

  for (let lag = minLag; lag <= maxLag; lag += 1) {
    let corr = 0;
    for (let i = 0; i < buffer.length - lag; i += 1) {
      corr += buffer[i] * buffer[i + lag];
    }
    if (corr > bestCorr) {
      bestCorr = corr;
      bestOffset = lag;
    }
  }

  if (bestOffset <= 0 || bestCorr < 0.004) {
    return 0;
  }

  const freq = sampleRate / bestOffset;
  return clamp((freq - 85) / (280 - 85), 0, 1);
}

function initSpeechRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    setTranscript('BROWSER DOES NOT SUPPORT WEB SPEECH API');
    return;
  }

  recognizer = new SR();
  recognizer.continuous = true;
  recognizer.interimResults = false;
  recognizer.lang = 'en-US';

  const restartRecognition = (delayMs = 220) => {
    if (!sttReconnectEnabled || !recognizer) {
      return;
    }
    const wait = Math.max(80, Number(delayMs || 0));
    setTimeout(() => {
      if (recognitionRunning || !sttReconnectEnabled || !recognizer) {
        return;
      }
      try {
        recognizer.start();
        recognitionRunning = true;
      } catch (_) {
        restartRecognition(Math.min(wait + 180, 1200));
      }
    }, wait);
  };

  recognizer.onresult = (event) => {
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const result = event.results[i];
      if (!result.isFinal) {
        continue;
      }
      submitVoiceToBackend(result[0]?.transcript || '');
    }
  };

  recognizer.onerror = () => {
    recognitionRunning = false;
    restartRecognition(320);
  };

  recognizer.onend = () => {
    recognitionRunning = false;
    restartRecognition(150);
  };

  try {
    recognizer.start();
    recognitionRunning = true;
  } catch (_) {
    restartRecognition(260);
  }
}

function submitVoiceToBackend(text) {
  const clean = safeText(text, '').trim();
  if (!clean || state.mode !== 'listening') {
    return;
  }
  if (Date.now() < sttCooldownUntil || sttRearmRequired) {
    return;
  }

  const normalized = normalizeTranscript(clean);
  if (normalized.length < 2) {
    return;
  }

  const now = Date.now();
  if (normalized === lastSubmittedNorm && (now - lastSubmittedTs) < STT_DUP_WINDOW_MS) {
    return;
  }

  lastSubmittedNorm = normalized;
  lastSubmittedTs = now;

  if (window.pywebview && window.pywebview.api && window.pywebview.api.submit_voice) {
    window.pywebview.api.submit_voice(clean).catch(() => {});
  }
}

async function initBrowserBatteryMetrics() {
  if (!navigator.getBattery) {
    return;
  }

  try {
    const battery = await navigator.getBattery();
    const pushBattery = () => {
      state.browserBattery = {
        percent: battery.level * 100,
        charging: battery.charging,
        secsLeft: Number.isFinite(battery.dischargingTime) ? battery.dischargingTime : null,
      };
      updatePowerWidget();
    };

    pushBattery();
    battery.addEventListener('levelchange', pushBattery);
    battery.addEventListener('chargingchange', pushBattery);
    battery.addEventListener('dischargingtimechange', pushBattery);
  } catch (_) {
    state.browserBattery = null;
  }
}

function resolvedBattery() {
  if (state.metrics.batteryPercent != null) {
    return {
      percent: state.metrics.batteryPercent,
      charging: state.metrics.batteryCharging,
      secsLeft: state.metrics.batterySecsLeft,
    };
  }
  if (state.browserBattery) {
    return {
      percent: state.browserBattery.percent,
      charging: state.browserBattery.charging,
      secsLeft: state.browserBattery.secsLeft,
    };
  }
  return { percent: null, charging: null, secsLeft: null };
}

function notifyPythonReady() {
  if (window.pywebview && window.pywebview.api && window.pywebview.api.ui_ready) {
    window.pywebview.api.ui_ready().catch(() => {});
  }
}

function buildTickRing() {
  const ring = byId('tickRing');
  for (let i = 0; i < 60; i += 1) {
    const tick = document.createElement('div');
    tick.className = `tick${i % 5 === 0 ? ' major' : ''}`;
    tick.style.transform = `rotate(${i * 6}deg)`;
    ring.appendChild(tick);
  }
}

function byId(id) {
  return document.getElementById(id);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function safeNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function safeInteger(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) {
    return null;
  }
  return Math.trunc(n);
}

function safeText(value, fallback = '') {
  const t = value == null ? '' : String(value).trim();
  return t || fallback;
}

function parseNullableBoolean(value) {
  if (value === true || value === false) {
    return value;
  }
  return null;
}

function normalizePercent(value, max) {
  const n = safeNumber(value);
  if (n == null) {
    return null;
  }
  const bounded = clamp(n, 0, max);
  if (max === 1) {
    return bounded * 100;
  }
  return bounded;
}

function normalizeTranscript(text) {
  return String(text || '')
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function formatUptime(totalSeconds) {
  const seconds = Math.max(0, Number(totalSeconds || 0) | 0);
  const h = String(Math.floor((seconds % 86400) / 3600)).padStart(2, '0');
  const m = String(Math.floor((seconds % 3600) / 60)).padStart(2, '0');
  const s = String(seconds % 60).padStart(2, '0');
  const d = Math.floor(seconds / 86400);
  if (d > 0) {
    return `${d}D ${h}:${m}:${s}`;
  }
  return `${h}:${m}:${s}`;
}

function formatCountdown(totalSeconds) {
  const seconds = Math.max(0, Number(totalSeconds || 0) | 0);
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${String(h).padStart(2, '0')}H ${String(m).padStart(2, '0')}M`;
}

function formatCountCompact(value) {
  const n = Math.max(0, Number(value || 0));
  if (!Number.isFinite(n)) {
    return '--';
  }
  if (n >= 1_000_000_000) {
    return `${(n / 1_000_000_000).toFixed(1)}B`;
  }
  if (n >= 1_000_000) {
    return `${(n / 1_000_000).toFixed(1)}M`;
  }
  if (n >= 1_000) {
    return `${(n / 1_000).toFixed(1)}K`;
  }
  return `${Math.round(n)}`;
}
