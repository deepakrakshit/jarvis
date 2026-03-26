import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const P = {
  timeScale: 0.78,
  rotSpeedX: 0.002,
  rotSpeedY: 0.005,
  plasmaScale: 0.1404,
  plasmaBright: 1.31,
  voidThresh: 0.072,
  colorDeep: 0x001433,
  colorMid: 0x0084ff,
  colorBright: 0x00ffe1,
  shellColor: 0x0066ff,
  shellOpacity: 0.41,
  particleCount: 700,
  mode: 'listening',
  isTalking: false,
  amplitude: 0.0,
  micVolume: 0.0,
  micPitchNorm: 0.0,
  speechPulse: 0.0,
  apiActive: false,
  apiLoad: 0.0,
  cpuLoad: 0.0,
  ramLoad: 0.0,
  responseEnergy: 0.0,
};

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.9;
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x000000);

const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 100);
camera.position.z = 2.4;

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.enablePan = false;
controls.minDistance = 1.5;
controls.maxDistance = 20;

const group = new THREE.Group();
scene.add(group);

const NOISE = /* glsl */`
  vec3 mod289(vec3 x){return x-floor(x*(1./289.))*289.;}
  vec4 mod289(vec4 x){return x-floor(x*(1./289.))*289.;}
  vec4 permute(vec4 x){return mod289(((x*34.)+1.)*x);}
  vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-0.85373472095314*r;}

  float snoise(vec3 v){
    const vec2 C=vec2(1./6.,1./3.);
    const vec4 D=vec4(0.,.5,1.,2.);
    vec3 i=floor(v+dot(v,C.yyy));
    vec3 x0=v-i+dot(i,C.xxx);
    vec3 g=step(x0.yzx,x0.xyz);
    vec3 l=1.-g;
    vec3 i1=min(g.xyz,l.zxy);
    vec3 i2=max(g.xyz,l.zxy);
    vec3 x1=x0-i1+C.xxx;
    vec3 x2=x0-i2+C.yyy;
    vec3 x3=x0-D.yyy;
    i=mod289(i);
    vec4 p=permute(permute(permute(
      i.z+vec4(0.,i1.z,i2.z,1.))
      +i.y+vec4(0.,i1.y,i2.y,1.))
      +i.x+vec4(0.,i1.x,i2.x,1.));
    float n_=.142857142857;
    vec3 ns=n_*D.wyz-D.xzx;
    vec4 j=p-49.*floor(p*ns.z*ns.z);
    vec4 x_=floor(j*ns.z);
    vec4 y_=floor(j-7.*x_);
    vec4 x=x_*ns.x+ns.yyyy;
    vec4 y=y_*ns.x+ns.yyyy;
    vec4 h=1.-abs(x)-abs(y);
    vec4 b0=vec4(x.xy,y.xy);
    vec4 b1=vec4(x.zw,y.zw);
    vec4 s0=floor(b0)*2.+1.;
    vec4 s1=floor(b1)*2.+1.;
    vec4 sh=-step(h,vec4(0.));
    vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy;
    vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
    vec3 p0=vec3(a0.xy,h.x);
    vec3 p1=vec3(a0.zw,h.y);
    vec3 p2=vec3(a1.xy,h.z);
    vec3 p3=vec3(a1.zw,h.w);
    vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
    p0*=norm.x;p1*=norm.y;p2*=norm.z;p3*=norm.w;
    vec4 m=max(.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.);
    m=m*m;
    return 42.*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
  }

  float fbm(vec3 p){
    float t=0.,a=.5,f=1.;
    for(int i=0;i<4;i++){t+=snoise(p*f)*a;a*=.5;f*=2.;}
    return t;
  }
`;

const light = new THREE.PointLight(0x0088ff, 2.0, 10);
group.add(light);

const shellGeo = new THREE.SphereGeometry(1.0, 64, 64);

const shellVert = /* glsl */`
  varying vec3 vNormal;
  varying vec3 vViewPos;
  void main(){
    vNormal = normalize(normalMatrix * normal);
    vec4 mvp = modelViewMatrix * vec4(position, 1.);
    vViewPos = -mvp.xyz;
    gl_Position = projectionMatrix * mvp;
  }
`;

const shellFrag = /* glsl */`
  varying vec3 vNormal;
  varying vec3 vViewPos;
  uniform vec3 uColor;
  uniform float uOpacity;
  void main(){
    float f = pow(1. - dot(normalize(vNormal), normalize(vViewPos)), 2.5);
    gl_FragColor = vec4(uColor, f * uOpacity);
  }
`;

const shellBack = new THREE.ShaderMaterial({
  vertexShader: shellVert,
  fragmentShader: shellFrag,
  uniforms: { uColor: { value: new THREE.Color(0x000055) }, uOpacity: { value: 0.3 } },
  transparent: true,
  blending: THREE.AdditiveBlending,
  side: THREE.BackSide,
  depthWrite: false,
});

const shellFront = new THREE.ShaderMaterial({
  vertexShader: shellVert,
  fragmentShader: shellFrag,
  uniforms: {
    uColor: { value: new THREE.Color(P.shellColor) },
    uOpacity: { value: P.shellOpacity },
  },
  transparent: true,
  blending: THREE.AdditiveBlending,
  side: THREE.FrontSide,
  depthWrite: false,
});

group.add(new THREE.Mesh(shellGeo, shellBack));
group.add(new THREE.Mesh(shellGeo, shellFront));

const plasmaGeo = new THREE.SphereGeometry(0.998, 128, 128);
const plasmaMat = new THREE.ShaderMaterial({
  uniforms: {
    uTime: { value: 0 },
    uScale: { value: P.plasmaScale },
    uBrightness: { value: P.plasmaBright },
    uThreshold: { value: P.voidThresh },
    uAmplitude: { value: 0.0 },
    uColorDeep: { value: new THREE.Color(P.colorDeep) },
    uColorMid: { value: new THREE.Color(P.colorMid) },
    uColorBright: { value: new THREE.Color(P.colorBright) },
  },
  vertexShader: /* glsl */`
    varying vec3 vPos;
    varying vec3 vNormal;
    varying vec3 vViewPos;
    uniform float uTime;
    uniform float uAmplitude;
    ${NOISE}
    void main(){
      vPos = position;
      vNormal = normalize(normalMatrix * normal);
      float disp = uAmplitude * 0.06 * snoise(position * 3. + uTime * 0.5);
      vec3 displaced = position + normal * disp;
      vec4 mvp = modelViewMatrix * vec4(displaced, 1.);
      vViewPos = -mvp.xyz;
      gl_Position = projectionMatrix * mvp;
    }
  `,
  fragmentShader: /* glsl */`
    uniform float uTime;
    uniform float uScale;
    uniform float uBrightness;
    uniform float uThreshold;
    uniform float uAmplitude;
    uniform vec3 uColorDeep;
    uniform vec3 uColorMid;
    uniform vec3 uColorBright;
    varying vec3 vPos;
    varying vec3 vNormal;
    varying vec3 vViewPos;
    ${NOISE}
    void main(){
      vec3 p = vPos * uScale;
      float turb = 1.0 + uAmplitude * 0.6;
      vec3 q = vec3(
        fbm(p + vec3(0., uTime*.05, 0.)),
        fbm(p + vec3(5.2,1.3,2.8) + uTime*.05),
        fbm(p + vec3(2.2,8.4,0.5) - uTime*.02)
      );
      float density = fbm(p * turb + 2. * q);
      float t = (density + .4) * .8;
      float alpha = smoothstep(uThreshold, .7, t);

      vec3 col = mix(uColorDeep, uColorMid, smoothstep(uThreshold, .5, t));
      col = mix(col, uColorBright, smoothstep(.5, .8, t));
      col = mix(col, vec3(1.), smoothstep(.8, 1.0, t));
      col *= 1.0 + uAmplitude * 0.4;

      float facing = dot(normalize(vNormal), normalize(vViewPos));
      float depth = (facing + 1.) * .5;
      float fAlpha = alpha * (.02 + .98 * depth);
      gl_FragColor = vec4(col * uBrightness, fAlpha);
    }
  `,
  transparent: true,
  blending: THREE.AdditiveBlending,
  side: THREE.DoubleSide,
  depthWrite: false,
});

const plasmaMesh = new THREE.Mesh(plasmaGeo, plasmaMat);
group.add(plasmaMesh);

const PC = P.particleCount;
const pPos = new Float32Array(PC * 3);
const pSz = new Float32Array(PC);

for (let i = 0; i < PC; i++) {
  const r = 0.95 * Math.cbrt(Math.random());
  const th = Math.random() * Math.PI * 2;
  const ph = Math.acos(2 * Math.random() - 1);
  pPos[i * 3] = r * Math.sin(ph) * Math.cos(th);
  pPos[i * 3 + 1] = r * Math.sin(ph) * Math.sin(th);
  pPos[i * 3 + 2] = r * Math.cos(ph);
  pSz[i] = Math.random();
}

const pGeo = new THREE.BufferGeometry();
pGeo.setAttribute('position', new THREE.BufferAttribute(pPos, 3));
pGeo.setAttribute('aSize', new THREE.BufferAttribute(pSz, 1));

const pMat = new THREE.ShaderMaterial({
  uniforms: {
    uTime: { value: 0 },
    uAmplitude: { value: 0 },
    uColor: { value: new THREE.Color(0xffffff) },
  },
  vertexShader: /* glsl */`
    uniform float uTime;
    uniform float uAmplitude;
    attribute float aSize;
    varying float vAlpha;
    void main(){
      vec3 pos = position;
      pos.y += sin(uTime*.2 + pos.x * 10.) * (0.02 + uAmplitude * 0.06);
      pos.x += cos(uTime*.15 + pos.z * 10.) * (0.02 + uAmplitude * 0.06);
      vec4 mvp = modelViewMatrix * vec4(pos, 1.);
      gl_Position = projectionMatrix * mvp;
      float base = (10. + uAmplitude * 8.) * aSize + 4.;
      gl_PointSize = base * (1. / -mvp.z);
      vAlpha = 0.8 + 0.2 * sin(uTime + aSize * 10.);
    }
  `,
  fragmentShader: /* glsl */`
    uniform vec3 uColor;
    varying float vAlpha;
    void main(){
      vec2 uv = gl_PointCoord - .5;
      float dist = length(uv);
      if(dist > .5) discard;
      float glow = pow(1. - dist*2., 1.8);
      gl_FragColor = vec4(uColor, glow * vAlpha);
    }
  `,
  transparent: true,
  blending: THREE.AdditiveBlending,
  depthWrite: false,
});

group.add(new THREE.Points(pGeo, pMat));

let _amp = 0.0;
let _targetAmp = 0.0;
let _recognizer = null;
let _recognitionRunning = false;
let _reconnectRecognition = true;
let _sttCooldownUntil = 0;

const STT_RESUME_DELAY_MS = 1100;

const statusEl = document.getElementById('status');
const telemetryEl = document.getElementById('telemetry');
const transcriptEl = document.getElementById('transcript');

const MODE_STYLE = {
  listening: { label: 'LISTENING', dot: '#00c8ff', blink: '1.2s' },
  processing: { label: 'PROCESSING', dot: '#ffb300', blink: '0.35s' },
  speaking: { label: 'SPEAKING', dot: '#00ff88', blink: '0.22s' },
};

function clamp(v, min, max) { return Math.max(min, Math.min(max, v)); }

function updateStatusHUD() {
  const modeCfg = MODE_STYLE[P.mode] || MODE_STYLE.listening;
  statusEl.innerHTML = `<span class="dot" style="background:${modeCfg.dot};animation:blink ${modeCfg.blink} ease-in-out infinite"></span>${modeCfg.label}`;

  const mic = P.micVolume.toFixed(2);
  const pitch = P.micPitchNorm.toFixed(2);
  const cpu = Math.round(P.cpuLoad * 100);
  const ram = Math.round(P.ramLoad * 100);
  const api = P.apiActive ? 'ON' : 'OFF';
  telemetryEl.textContent = `MODE: ${modeCfg.label} | MIC: ${mic} | PITCH: ${pitch} | API: ${api} | CPU: ${cpu}% | RAM: ${ram}%`;
}

function setMode(mode) {
  if (!MODE_STYLE[mode]) return;
  P.mode = mode;
  if (mode === 'speaking') {
    P.isTalking = true;
    _sttCooldownUntil = Date.now() + STT_RESUME_DELAY_MS;
  } else if (mode === 'listening') {
    P.isTalking = false;
  }

  updateStatusHUD();
}

function setTranscript(text) {
  transcriptEl.textContent = text && text.trim() ? text.trim() : 'READY FOR VOICE COMMANDS';
}

function updateFromMic(volume, pitchNorm, speaking) {
  P.micVolume = clamp(volume, 0, 1);
  P.micPitchNorm = clamp(pitchNorm, 0, 1);
  if (speaking) {
    P.speechPulse = clamp(P.speechPulse + 0.08, 0, 1);
  }
}

function detectPitch(buffer, sampleRate) {
  let bestOffset = -1;
  let bestCorr = 0;
  const minLag = Math.floor(sampleRate / 300);
  const maxLag = Math.floor(sampleRate / 70);

  for (let lag = minLag; lag <= maxLag; lag++) {
    let corr = 0;
    for (let i = 0; i < buffer.length - lag; i++) {
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
      for (let i = 0; i < tData.length; i++) {
        sumSq += tData[i] * tData[i];
      }

      const rms = Math.sqrt(sumSq / tData.length);
      const volume = clamp(rms * 5.2, 0, 1);
      const pitch = detectPitch(tData, audioCtx.sampleRate);
      const speaking = volume > 0.06;

      updateFromMic(volume, pitch, speaking);
      requestAnimationFrame(loop);
    };

    loop();
    setTranscript('MIC CONNECTED - ALWAYS LISTENING');
  } catch (err) {
    setTranscript('MIC PERMISSION REQUIRED FOR VOICE MODE');
    console.error('Mic init failed:', err);
  }
}

function submitVoiceToPython(text) {
  if (!text || !text.trim()) return;
  if (P.mode !== 'listening') return;
  if (Date.now() < _sttCooldownUntil) return;

  const clean = text.trim();
  if (clean.length < 2) return;
  setTranscript(`YOU: ${clean}`);

  if (window.pywebview && window.pywebview.api && window.pywebview.api.submit_voice) {
    window.pywebview.api.submit_voice(clean).catch(() => {});
  }
}

function initSpeechRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    setTranscript('BROWSER DOES NOT SUPPORT WEB SPEECH API');
    return;
  }

  _recognizer = new SR();
  _recognizer.continuous = true;
  _recognizer.interimResults = false;
  _recognizer.lang = 'en-US';

  const restartRecognition = (delayMs = 240) => {
    if (!_reconnectRecognition || !_recognizer) return;
    const wait = Math.max(80, Number(delayMs || 0));
    setTimeout(() => {
      if (_recognitionRunning || !_reconnectRecognition || !_recognizer) {
        return;
      }
      try {
        _recognizer.start();
        _recognitionRunning = true;
      } catch (_) {
        restartRecognition(Math.min(wait + 180, 1200));
      }
    }, wait);
  };

  _recognizer.onresult = (event) => {
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const r = event.results[i];
      if (!r.isFinal) continue;
      const text = r[0]?.transcript || '';
      submitVoiceToPython(text);
    }
  };

  _recognizer.onerror = () => {
    _recognitionRunning = false;
    restartRecognition(320);
  };

  _recognizer.onend = () => {
    _recognitionRunning = false;
    restartRecognition(140);
  };

  try {
    _recognizer.start();
    _recognitionRunning = true;
  } catch (_) {
    restartRecognition(260);
  }
}

window.jarvis = {
  setMode(mode) { setMode(mode); },
  setApiActivity(active) {
    P.apiActive = !!active;
    P.apiLoad = active ? 1.0 : 0.0;
    updateStatusHUD();
  },
  setSystemMetrics(cpu, ram) {
    P.cpuLoad = clamp(Number(cpu || 0), 0, 1);
    P.ramLoad = clamp(Number(ram || 0), 0, 1);
    updateStatusHUD();
  },
  onAssistantDelta(delta) {
    if (!delta) return;
    setTranscript(`JARVIS: ${delta}`);
    P.responseEnergy = clamp(P.responseEnergy + delta.length / 180, 0, 1);
  },
  onUserTranscript(text) {
    setTranscript(`YOU: ${text || ''}`);
    setMode('processing');
  },
  setMicFeatures(volume, pitch, speaking) {
    updateFromMic(Number(volume || 0), Number(pitch || 0), !!speaking);
  },
};

updateStatusHUD();
initMicReactivity();
initSpeechRecognition();

function notifyPythonReady() {
  if (window.pywebview && window.pywebview.api && window.pywebview.api.ui_ready) {
    window.pywebview.api.ui_ready().catch(() => {});
  }
}

notifyPythonReady();
window.addEventListener('pywebviewready', notifyPythonReady);

const clock = new THREE.Clock();

function animate() {
  requestAnimationFrame(animate);
  const t = clock.getElapsedTime();

  const modeProfile = {
    listening: { swirl: 0.72, turb: 0.24, pulse: 0.18, rx: 0.0013, ry: 0.0026 },
    processing: { swirl: 1.36, turb: 0.72, pulse: 0.42, rx: 0.0026, ry: 0.0062 },
    speaking: { swirl: 1.02, turb: 0.50, pulse: 0.95, rx: 0.0034, ry: 0.0080 },
  }[P.mode] || { swirl: 0.8, turb: 0.3, pulse: 0.2, rx: 0.0015, ry: 0.003 };

  P.responseEnergy = Math.max(0, P.responseEnergy - 0.01);
  P.apiLoad += ((P.apiActive ? 1.0 : 0.0) - P.apiLoad) * 0.08;
  P.speechPulse *= 0.92;

  const micEnergy = P.micVolume;
  const metricsLoad = (P.cpuLoad + P.ramLoad) * 0.5;
  const talkingEnergy = Math.max(P.responseEnergy, P.speechPulse, micEnergy * 0.8);

  const adaptiveAmp = clamp(
    modeProfile.pulse * 0.25 +
    talkingEnergy * 0.95 +
    P.apiLoad * 0.25 +
    metricsLoad * 0.18,
    0,
    1
  );
  _targetAmp = adaptiveAmp;

  _amp += (_targetAmp - _amp) * 0.12;

  const dynamicTimeScale =
    modeProfile.swirl +
    P.apiLoad * 0.35 +
    metricsLoad * 0.22 +
    micEnergy * 0.28;

  const dynamicBrightness =
    P.plasmaBright +
    micEnergy * 0.9 +
    P.apiLoad * 0.35 +
    _amp * 0.35;

  const pitchTint = P.micPitchNorm;
  const modeTint = P.mode === 'processing' ? 0.26 : 0.0;
  const tintMix = clamp(pitchTint + modeTint, 0, 1);

  const baseMid = new THREE.Color(P.colorMid);
  const brightMid = new THREE.Color(0x00d5ff);
  const baseBright = new THREE.Color(P.colorBright);
  const brightTone = new THREE.Color(0x6dffea);
  plasmaMat.uniforms.uColorMid.value.copy(baseMid).lerp(brightMid, tintMix);
  plasmaMat.uniforms.uColorBright.value.copy(baseBright).lerp(brightTone, tintMix * 0.7);

  plasmaMat.uniforms.uScale.value = P.plasmaScale * (1 + modeProfile.turb * 0.16 + P.apiLoad * 0.10);
  plasmaMat.uniforms.uBrightness.value = dynamicBrightness;

  plasmaMat.uniforms.uTime.value = t * dynamicTimeScale;
  plasmaMat.uniforms.uAmplitude.value = _amp;
  pMat.uniforms.uTime.value = t;
  pMat.uniforms.uAmplitude.value = _amp;

  plasmaMesh.rotation.y = t * (0.06 + modeProfile.swirl * 0.05 + P.apiLoad * 0.07);

  const boost = 1.0 + _amp * 1.2 + P.apiLoad * 0.6;
  group.rotation.x += (modeProfile.rx + P.rotSpeedX * 0.2) * boost;
  group.rotation.y += (modeProfile.ry + P.rotSpeedY * 0.2) * boost;

  shellFront.uniforms.uOpacity.value = P.shellOpacity + _amp * 0.26 + P.apiLoad * 0.12;

  controls.update();
  renderer.render(scene, camera);
}

window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

animate();
