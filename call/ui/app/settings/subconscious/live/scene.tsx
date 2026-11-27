'use client';

// Her brain in 3D (three.js through React Three Fiber): regions placed top to bottom the way a turn travels, axons
// between them, and signals that run along an axon when a recorded step happens, lighting it behind them. Each region
// is a living neuron (neuron.tsx). Around them: a floor grid that fades into the dark, dust at several depths, a faint
// haze, and a view that leans with the pointer and sways slowly, so the depth is felt. Its slow motion is drawn about
// 30 times a second, never while the tab is hidden or when reduced motion is asked for; a signal and a lit region are
// drawn as fast as the screen allows.
//
// It watches its own first frames: a frame that comes out all black (it happened: one NaN in a shader, spread by
// the bloom over the whole view) is said to the page, which draws again without the bloom and, if that is black too,
// shows the plain view. A lost WebGL context is said too, and so is its return.
import { type MutableRefObject, useEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Bloom, EffectComposer } from '@react-three/postprocessing';
import { CORE, type Placed, type Region, crowded, inside, reach } from './brain';
import { Neuron } from './neuron';

export type Live = {
  lit: Map<string, { at: number; state: string }>; // region id -> when it lights (performance seconds)
  pulses: { from: string; to: string; start: number; color: string }[];
};

// What the scene tells the page about itself.
export type Health = 'drawn' | 'black' | 'lost' | 'restored';

const PULSE = 0.5; // seconds a signal takes along an axon
const GLOW = 1.8; // seconds a lit region takes to settle
const AFTER = 1.1; // seconds an axon keeps the light of a signal that arrived
const LOOK_AT = new THREE.Vector3(0, 0.55, 0);
const BACKGROUND = '#0a0b0e'; // (graphite: never pure black, so a black frame is known to be a broken one)
const now = () => performance.now() / 1000;
const ease = (k: number) => k * k * (3 - 2 * k);

function curve(a: Region, b: Region): THREE.QuadraticBezierCurve3 {
  const p = new THREE.Vector3(...a.at);
  const q = new THREE.Vector3(...b.at);
  const mid = p
    .clone()
    .lerp(q, 0.5)
    .add(new THREE.Vector3(0, 0, 0.45)); // (a gentle bow toward you)
  return new THREE.QuadraticBezierCurve3(p, mid, q);
}

// An axon: the two regions' colours along it, faint at rest and fading into each membrane; a signal is a bright head
// with the axon lit behind it, and a little afterglow once it has arrived.
const AXON = {
  vertexShader: `
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: `
    uniform vec3 uA; uniform vec3 uB; uniform float uRest;
    uniform vec3 uSignal; uniform float uHead; uniform float uDir; uniform float uOn; uniform float uAfter;
    varying vec2 vUv;
    void main() {
      float u = clamp(vUv.x, 0.0, 1.0);
      float ends = smoothstep(0.0, 0.14, u) * (1.0 - smoothstep(0.86, 1.0, u));
      float rest = uRest * (0.3 + 0.7 * ends);
      float behind = (uHead - u) * uDir;
      float trail = uOn * step(0.0, behind) * exp(-clamp(behind, 0.0, 1.0) * 5.0);
      float head = uOn * exp(-abs(behind) * 55.0);
      vec3 colour = mix(uA, uB, u) * rest + uSignal * (trail * 1.6 + head * 5.0 + uAfter * ends * 0.8);
      gl_FragColor = vec4(colour, clamp(rest + trail * 0.85 + head + uAfter * ends * 0.45, 0.0, 1.0));
    }`,
};

function Axon({ a, b, live }: { a: Region; b: Region; live: MutableRefObject<Live> }) {
  const both = a.runs && b.runs;
  const core = CORE.some((c) => c.id === a.id) && CORE.some((c) => c.id === b.id);
  const width = core ? 0.0105 : 0.006;
  const geometry = useMemo(
    () => new THREE.TubeGeometry(curve(a, b), 64, width, 6, false),
    [a, b, width]
  );
  // At rest: the path every turn takes is clear, the cortices' quieter, a cortex switched off almost gone.
  const rest = !both ? 0.02 : core ? 0.3 : a.size > 0.2 || b.size > 0.2 ? 0.18 : 0.09;
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        ...AXON,
        uniforms: {
          uA: { value: new THREE.Color(a.color).lerp(new THREE.Color('#8b95a7'), 0.15) },
          uB: { value: new THREE.Color(b.color).lerp(new THREE.Color('#8b95a7'), 0.15) },
          uRest: { value: rest },
          uSignal: { value: new THREE.Color() },
          uHead: { value: 0 },
          uDir: { value: 1 },
          uOn: { value: 0 },
          uAfter: { value: 0 },
        },
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        toneMapped: false,
      }),
    [a.color, b.color, rest]
  );
  useEffect(
    () => () => {
      geometry.dispose();
      material.dispose();
    },
    [geometry, material]
  );
  useFrame(() => {
    const t = now();
    let last: Live['pulses'][number] | undefined;
    for (const p of live.current.pulses)
      if (
        ((p.from === a.id && p.to === b.id) || (p.from === b.id && p.to === a.id)) &&
        t >= p.start
      )
        if (!last || p.start > last.start) last = p;
    const u = material.uniforms;
    if (!last) {
      u.uOn.value = 0;
      u.uAfter.value = 0;
      return;
    }
    const k = (t - last.start) / PULSE;
    const forward = last.from === a.id;
    u.uSignal.value.set(last.color);
    u.uHead.value = forward ? Math.min(k, 1.2) : 1 - Math.min(k, 1.2);
    u.uDir.value = forward ? 1 : -1;
    u.uOn.value = k <= 1 ? 1 : Math.max(0, 1 - (k - 1) * 4);
    u.uAfter.value = k <= 1 ? 0 : ease(Math.max(0, 1 - (t - last.start - PULSE) / AFTER));
  });
  return <mesh geometry={geometry} material={material} />;
}

function Pulses({ regions, live }: { regions: Region[]; live: MutableRefObject<Live> }) {
  const max = 96;
  const mesh = useRef<THREE.InstancedMesh>(null);
  const curves = useMemo(() => {
    const byId = new Map(regions.map((r) => [r.id, r]));
    const kept = new Map<string, THREE.QuadraticBezierCurve3 | null>();
    return (from: string, to: string) => {
      const key = `${from}>${to}`;
      if (!kept.has(key)) {
        const a = byId.get(from);
        const b = byId.get(to);
        kept.set(key, a && b ? curve(a, b) : null);
      }
      return kept.get(key)!;
    };
  }, [regions]);
  const place = useMemo(() => new THREE.Object3D(), []);
  const tint = useMemo(() => new THREE.Color(), []);
  useFrame(({ invalidate }) => {
    const m = mesh.current;
    if (!m) return;
    const t = now();
    live.current.pulses = live.current.pulses.filter((p) => t - p.start < PULSE + AFTER + 0.2);
    let i = 0;
    for (const p of live.current.pulses) {
      const c = curves(p.from, p.to);
      const k = (t - p.start) / PULSE;
      if (!c || k < 0 || k > 1.2) continue;
      for (const lag of [0, 0.04, 0.08, 0.12, 0.16]) {
        // (a spark and its short trail; it lands, flares and goes)
        const at = Math.min(1, k - lag);
        if (i >= max || at < 0) continue;
        place.position.copy(c.getPoint(at));
        place.scale.setScalar(lag ? 0.8 - lag * 3.5 : k > 1 ? 1.35 - (k - 1) * 4 : 1.1);
        place.updateMatrix();
        m.setMatrixAt(i, place.matrix);
        m.setColorAt(i, tint.set(p.color).multiplyScalar(lag ? 2.6 - lag * 9 : 6));
        i += 1;
      }
    }
    m.count = i;
    m.instanceMatrix.needsUpdate = true;
    if (m.instanceColor) m.instanceColor.needsUpdate = true;
    const moving =
      live.current.pulses.length > 0 || [...live.current.lit.values()].some((l) => t - l.at < GLOW);
    if (moving) invalidate();
  });
  return (
    <instancedMesh ref={mesh} args={[undefined, undefined, max]} frustumCulled={false}>
      <sphereGeometry args={[0.045, 12, 12]} />
      <meshBasicMaterial toneMapped={false} />
    </instancedMesh>
  );
}

// The floor: a fine grid with a coarser one over it, lit softly under the brain and fading into the dark.
const FLOOR = {
  vertexShader: `
    varying vec3 vWorld;
    void main() { vec4 w = modelMatrix * vec4(position, 1.0); vWorld = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }`,
  fragmentShader: `
    uniform vec3 uColor;
    varying vec3 vWorld;
    float grid(vec2 p) {
      vec2 g = abs(fract(p - 0.5) - 0.5) / max(fwidth(p), vec2(0.0001));
      return 1.0 - min(min(g.x, g.y), 1.0);
    }
    void main() {
      vec2 p = vWorld.xz;
      float d = length(p * vec2(1.0, 1.6));
      float fade = exp(-d * d * 0.014);
      float pool = exp(-d * d * 0.09);
      float a = (grid(p * 2.0) * 0.08 + grid(p * 0.4) * 0.16) * fade + pool * 0.05;
      gl_FragColor = vec4(uColor * a, clamp(a, 0.0, 1.0));
    }`,
};

function Floor() {
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        ...FLOOR,
        uniforms: { uColor: { value: new THREE.Color('#9fb4d4') } },
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        toneMapped: false,
      }),
    []
  );
  useEffect(() => () => material.dispose(), [material]);
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -3.1, 0]} material={material}>
      <planeGeometry args={[44, 44]} />
    </mesh>
  );
}

// Dust: faint points at several depths, drifting very slowly, a few of them catching the light now and then.
const DUST = {
  vertexShader: `
    attribute float aSeed; attribute float aSize;
    uniform float uTime; uniform float uDpr;
    varying float vBright;
    void main() {
      vec3 p = position;
      p.x += sin(uTime * 0.035 + aSeed * 6.2831) * 0.18;
      p.y += cos(uTime * 0.028 + aSeed * 4.0) * 0.12;
      vec4 mv = modelViewMatrix * vec4(p, 1.0);
      vBright = 0.35 + 0.65 * (0.5 + 0.5 * sin(uTime * (0.25 + aSeed * 0.5) + aSeed * 40.0));
      gl_PointSize = aSize * uDpr * 320.0 / max(-mv.z, 0.1);
      gl_Position = projectionMatrix * mv;
    }`,
  fragmentShader: `
    uniform vec3 uColor;
    varying float vBright;
    void main() {
      float d = length(gl_PointCoord - 0.5);
      float a = (1.0 - smoothstep(0.1, 0.5, d)) * vBright * 0.55;
      gl_FragColor = vec4(uColor * a, a);
    }`,
};

function Dust({ still }: { still: boolean }) {
  const { gl } = useThree();
  const geometry = useMemo(() => {
    const n = 1400;
    const at = new Float32Array(n * 3);
    const seed = new Float32Array(n);
    const size = new Float32Array(n);
    let s = 7;
    const rand = () => (s = (s * 16807) % 2147483647) / 2147483647;
    for (let i = 0; i < n; i++) {
      const far = rand() < 0.75;
      at[i * 3] = (rand() - 0.5) * (far ? 26 : 12);
      at[i * 3 + 1] = (rand() - 0.5) * (far ? 14 : 8) + 0.5;
      at[i * 3 + 2] = far ? -2.6 - rand() * 9 : -1.5 + rand() * 4;
      seed[i] = rand();
      size[i] = far ? 0.022 + rand() * 0.02 : 0.012 + rand() * 0.012;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(at, 3));
    g.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1));
    g.setAttribute('aSize', new THREE.BufferAttribute(size, 1));
    return g;
  }, []);
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        ...DUST,
        uniforms: {
          uColor: { value: new THREE.Color('#aab6cc') },
          uTime: { value: 0 },
          uDpr: { value: gl.getPixelRatio() },
        },
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        toneMapped: false,
      }),
    [gl]
  );
  useEffect(
    () => () => {
      geometry.dispose();
      material.dispose();
    },
    [geometry, material]
  );
  useFrame(({ clock }) => {
    if (!still) material.uniforms.uTime.value = clock.elapsedTime;
  });
  return <points geometry={geometry} material={material} frustumCulled={false} />;
}

// A faint cool haze far behind the brain: the dark has depth.
const HAZE = {
  vertexShader: `
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: `
    uniform vec3 uColor; uniform vec3 uDeep;
    varying vec2 vUv;
    void main() {
      vec2 p = (vUv - vec2(0.5, 0.55)) * vec2(1.7, 1.0);
      float d = length(p);
      float a = exp(-d * d * 7.0) * 0.11 + exp(-d * 3.5) * 0.045;
      gl_FragColor = vec4(mix(uDeep, uColor, exp(-d * 4.0)) * a, a);
    }`,
};

function Haze() {
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        ...HAZE,
        uniforms: {
          uColor: { value: new THREE.Color('#7f9cc4') },
          uDeep: { value: new THREE.Color('#3b4a66') },
        },
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        toneMapped: false,
      }),
    []
  );
  useEffect(() => () => material.dispose(), [material]);
  return (
    <mesh position={[0, 0.4, -9]} material={material} renderOrder={-2}>
      <planeGeometry args={[46, 26]} />
    </mesh>
  );
}

// Each region's label follows it on screen, just under its sphere (crisp HTML text, not in the scene): moved
// directly, no React state, and only on a frame that draws.
function Places({
  regions,
  labels,
}: {
  regions: Region[];
  labels: MutableRefObject<Map<string, HTMLElement>>;
}) {
  const at = useMemo(() => new THREE.Vector3(), []);
  const boxes = useRef(new Map<string, [number, number]>()); // (each name's size: read again when the stage resizes)
  const stage = useRef('');
  useFrame(({ camera, size, gl }) => {
    if (gl.getContext().isContextLost()) return; // (the plain view stands in, and places the names itself)
    if (stage.current !== `${size.width}x${size.height}`) {
      stage.current = `${size.width}x${size.height}`;
      boxes.current.clear();
    }
    const placed: Placed[] = [];
    let holder: HTMLElement | null = null;
    for (const r of regions) {
      const el = labels.current.get(r.id);
      if (!el) continue;
      at.set(r.at[0], r.at[1], r.at[2]).project(camera);
      const cx = ((at.x + 1) / 2) * size.width;
      const cy = ((1 - at.y) / 2) * size.height;
      at.set(r.at[0], r.at[1] - r.size * 1.08, r.at[2]).project(camera);
      let box = boxes.current.get(r.id);
      if (!box?.[0]) boxes.current.set(r.id, (box = [el.offsetWidth, el.offsetHeight]));
      const x = inside(((at.x + 1) / 2) * size.width, box[0], size.width);
      const y = ((1 - at.y) / 2) * size.height;
      // (whole pixels: crisp, and still; never lower than its place: on a phone the sphere below is a pixel away)
      el.style.transform = `translate(${Math.round(x)}px, ${Math.floor(y)}px)`;
      // Where its sphere shows (centre, radius): the page test checks that no name covers another's.
      const ball: [number, number, number] = [
        Math.round(cx),
        Math.round(cy),
        Math.round((y - cy) / 1.08),
      ];
      if (el.dataset.ball !== ball.join(' ')) el.dataset.ball = ball.join(' ');
      placed.push({ id: r.id, x, y: y + 7 + box[1] / 2, w: box[0], h: box[1], ball });
      holder = el.parentElement;
    }
    if (!holder) return;
    const was = holder.dataset.tight === 'true';
    const tight = crowded(placed, was ? 12 : 0); // (back to every name only with room to spare)
    if (tight !== was) holder.dataset.tight = String(tight);
  });
  return null;
}

function Frame({ wide }: { wide: number }) {
  // Far enough back that every region and its label fits, whatever the stage's shape (a phone stands tall), and
  // further when the cortices reach further out (more cards).
  const { camera, scene, size, invalidate } = useThree();
  useEffect(() => {
    const aspect = size.width / Math.max(1, size.height);
    camera.position.z = Math.max(10.6, (11.4 * Math.max(1, (wide + 0.75) / 4.25)) / aspect);
    camera.lookAt(LOOK_AT);
    // The haze keeps its depth from the camera: stepped back (a phone, more cards), the brain is not dimmer.
    if (scene.fog instanceof THREE.Fog) {
      scene.fog.near = camera.position.z + 0.9;
      scene.fog.far = camera.position.z + 11.4;
    }
    invalidate();
  }, [camera, scene, size, invalidate, wide]);
  return null;
}

function Drift({ still }: { still: boolean }) {
  // A slight lean with the pointer, and a slow sway of its own: depth you feel, never a spinning model. The sway rests
  // while the pointer is over the stage, so what you aim at holds still. Under reduced motion the view holds still.
  const invalidate = useThree((state) => state.invalidate);
  const over = useRef(false);
  const swing = useRef(1);
  useEffect(() => {
    if (still) return;
    const move = (e: PointerEvent) => {
      over.current = Boolean((e.target as Element | null)?.closest?.('.vlx-stage'));
      invalidate();
    };
    const out = (e: PointerEvent) => {
      if (!e.relatedTarget) over.current = false; // (it left the window)
    };
    window.addEventListener('pointermove', move);
    document.addEventListener('pointerout', out);
    return () => {
      window.removeEventListener('pointermove', move);
      document.removeEventListener('pointerout', out);
    };
  }, [invalidate, still]);
  useFrame(({ camera, pointer, clock }) => {
    if (still) return;
    const t = clock.elapsedTime;
    swing.current += ((over.current ? 0 : 1) - swing.current) * 0.03;
    // (side to side only: up and down it would move a name onto the sphere under it on a phone, where they all but touch)
    const x = pointer.x * 0.6 + Math.sin(t * 0.11) * 0.35 * swing.current;
    const y = 0.6 + pointer.y * 0.3;
    if (Math.abs(camera.position.x - x) + Math.abs(camera.position.y - y) > 0.002) {
      camera.position.x += (x - camera.position.x) * 0.06;
      camera.position.y += (y - camera.position.y) * 0.06;
      camera.lookAt(LOOK_AT);
      invalidate();
    }
  });
  return null;
}

function Ambient({ still }: { still: boolean }) {
  // The neurons' slow life: about 30 frames a second while the tab is seen; none under reduced motion.
  const invalidate = useThree((state) => state.invalidate);
  useEffect(() => {
    if (still) return;
    const tick = setInterval(() => {
      if (!document.hidden) invalidate();
    }, 33);
    return () => clearInterval(tick);
  }, [still, invalidate]);
  return null;
}

function Kick({ version }: { version: number }) {
  // A new step to show: draw again (the scene otherwise sleeps).
  const invalidate = useThree((state) => state.invalidate);
  useEffect(() => {
    invalidate();
  }, [version, invalidate]);
  return null;
}

// Three rows of what was just drawn, read before the browser shows it. All of it exactly black is a broken frame: the
// background is graphite, never pure black.
function black(gl: THREE.WebGLRenderer): boolean {
  const c = gl.getContext();
  const w = c.drawingBufferWidth;
  const h = c.drawingBufferHeight;
  if (!w || !h || c.isContextLost()) return false;
  gl.setRenderTarget(null);
  const row = new Uint8Array(w * 4);
  let zero = 0;
  for (const y of [0.25, 0.5, 0.75]) {
    c.readPixels(0, Math.floor(h * y), w, 1, c.RGBA, c.UNSIGNED_BYTE, row);
    for (let i = 0; i < row.length; i += 4) if (!row[i] && !row[i + 1] && !row[i + 2]) zero++;
  }
  return zero >= w * 3 * 0.98;
}

// The first frames, looked at: the 4th (once what draws is all set up) and the 24th. It draws the scene itself when
// there is no bloom to draw it (`render`).
function Check({
  render,
  priority,
  onHealth,
}: {
  render: boolean;
  priority: number;
  onHealth: (health: Health) => void;
}) {
  const invalidate = useThree((state) => state.invalidate);
  const frames = useRef(0);
  const seen = useRef(-1);
  const done = useRef(false);
  useFrame(({ gl, scene, camera }) => {
    if (render) gl.render(scene, camera);
    if (done.current) return;
    const drew = gl.info.render.frame !== seen.current;
    seen.current = gl.info.render.frame;
    if (drew) frames.current += 1;
    if (drew && (frames.current === 4 || frames.current === 24)) {
      if (black(gl)) {
        done.current = true;
        onHealth('black');
        return;
      }
      if (frames.current === 4) onHealth('drawn');
      else done.current = true;
    }
    if (!done.current) invalidate(); // (a few frames to look at, even when nothing moves)
  }, priority);
  return null;
}

export default function Scene({
  regions,
  wires,
  live,
  labels,
  version,
  hovered,
  picked,
  still,
  bloom,
  onHealth,
}: {
  regions: Region[];
  wires: [string, string][];
  live: MutableRefObject<Live>;
  labels: MutableRefObject<Map<string, HTMLElement>>;
  version: number;
  hovered: string | null; // (what a pointer or a finger is on: the page finds it, the nearest sphere on screen)
  picked: string | null;
  still: boolean; // reduced motion: no lean, no sway, no drift
  bloom: boolean; // the glow: off only when a frame with it came out black
  onHealth: (health: Health) => void;
}) {
  const byId = useMemo(() => new Map(regions.map((r) => [r.id, r])), [regions]);
  const told = useRef(onHealth);
  told.current = onHealth;
  // (a canvas taken away has its context given up, which a browser says as a loss: after that, nothing is told)
  const here = useRef(true);
  useEffect(
    () => () => {
      here.current = false;
    },
    []
  );
  return (
    <Canvas
      frameloop="demand"
      dpr={[1, 2]}
      camera={{ position: [0, 0.6, 10.6], fov: 38 }}
      gl={{ antialias: true, powerPreference: 'high-performance' }}
      onCreated={({ gl }) => {
        gl.domElement.addEventListener(
          'webglcontextlost',
          () => here.current && told.current('lost')
        );
        gl.domElement.addEventListener(
          'webglcontextrestored',
          () => here.current && told.current('restored')
        );
      }}
    >
      <Kick version={version} />
      <Ambient still={still} />
      <Frame wide={reach(regions)} />
      <color attach="background" args={[BACKGROUND]} />
      <fog attach="fog" args={[BACKGROUND, 11.5, 22]} />
      <Haze />
      <Floor />
      <Dust still={still} />
      {wires.map(
        ([a, b]) =>
          byId.has(a) &&
          byId.has(b) && <Axon key={`${a}>${b}`} a={byId.get(a)!} b={byId.get(b)!} live={live} />
      )}
      {regions.map((r) => (
        <Neuron
          key={r.id}
          region={r}
          live={live}
          hovered={hovered === r.id}
          picked={picked === r.id}
          still={still}
        />
      ))}
      <Pulses regions={regions} live={live} />
      <Places regions={regions} labels={labels} />
      <Drift still={still} />
      {bloom ? (
        <>
          <EffectComposer multisampling={4}>
            <Bloom
              mipmapBlur
              luminanceThreshold={0.5}
              luminanceSmoothing={0.3}
              intensity={1.55}
              radius={0.82}
            />
          </EffectComposer>
          <Check render={false} priority={2} onHealth={(h) => told.current(h)} />
        </>
      ) : (
        <Check render priority={1} onHealth={(h) => told.current(h)} />
      )}
    </Canvas>
  );
}
