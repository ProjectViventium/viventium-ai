'use client';

// Each region appears as a neuron with a nucleus that glows at rest,
// inside a holographic membrane lit at its rim, with fine filaments of light drifting over it; an aura around it;
// tapered dendrites that branch, with current running out along them and a lit bouton at each tip; particles in orbit;
// a turning ring. A recorded step lights it: the nucleus flares, the aura swells, a ripple goes out, the orbits
// quicken. A cortex switched off is a dark membrane only, and is never lit. All of it is a few small shaders.
//
// Every shader keeps its numbers finite: no pow() of a base that can dip below zero, smoothstep's edges in order. On
// Apple's GPUs one pow() of a base a hair below zero gave NaN, and the bloom carried that one pixel across the whole
// frame: the Live view was black.
import { type MutableRefObject, useEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import { useFrame, useThree } from '@react-three/fiber';
import type { Region } from './brain';
import { COLORS } from './brain';

export type Lit = Map<string, { at: number; state: string }>;

const GLOW = 1.8; // seconds a lit region takes to settle (the scene's)
const now = () => performance.now() / 1000;
const ease = (k: number) => k * k * (3 - 2 * k);

function random(seed: string): () => number {
  // The same shape for the same region, every time (mulberry32).
  let h = 1779033703 ^ seed.length;
  for (let i = 0; i < seed.length; i++) h = Math.imul(h ^ seed.charCodeAt(i), 3432918353);
  let a = (h << 13) | (h >>> 19);
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const NOISE = `
float hash(vec3 p) { p = fract(p * 0.3183099 + 0.1); p *= 17.0; return fract(p.x * p.y * p.z * (p.x + p.y + p.z)); }
float noise(vec3 x) {
  vec3 i = floor(x); vec3 f = fract(x); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(hash(i), hash(i + vec3(1, 0, 0)), f.x), mix(hash(i + vec3(0, 1, 0)), hash(i + vec3(1, 1, 0)), f.x), f.y),
             mix(mix(hash(i + vec3(0, 0, 1)), hash(i + vec3(1, 0, 1)), f.x), mix(hash(i + vec3(0, 1, 1)), hash(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}`;

// The membrane: bright at its rim, nearly clear where it faces you, with slow filaments of light and a thin band that
// drifts down it.
const MEMBRANE = {
  vertexShader: `
    varying vec3 vNormal; varying vec3 vView; varying vec3 vPos;
    void main() {
      vPos = position;
      vec4 mv = modelViewMatrix * vec4(position, 1.0);
      vView = -mv.xyz;
      vNormal = normalMatrix * normal;
      gl_Position = projectionMatrix * mv;
    }`,
  fragmentShader: `
    uniform vec3 uColor; uniform float uTime; uniform float uGlow; uniform float uLife; uniform float uSize;
    varying vec3 vNormal; varying vec3 vView; varying vec3 vPos;
    ${NOISE}
    void main() {
      float facing = clamp(dot(normalize(vNormal), normalize(vView)), 0.0, 1.0);
      float edge = 1.0 - facing;
      float halo = edge * edge;
      float rim = halo * edge;
      vec3 q = vPos / uSize;
      float warp = noise(q * 1.6 + vec3(0.0, uTime * 0.11, uTime * 0.05));
      float flow = noise(q * 2.6 + vec3(warp * 2.0, -uTime * 0.08, uTime * 0.06));
      float filament = smoothstep(0.58, 0.70, flow) * (1.0 - smoothstep(0.70, 0.86, flow));
      float band = 1.0 - smoothstep(0.0, 0.035, abs(fract(q.y * 0.5 + 0.5 - uTime * 0.045) - 0.5));
      float light = rim * (1.6 + uGlow * 3.4) + halo * 0.2 + filament * halo * (0.6 + uGlow * 1.8) + band * facing * 0.1;
      float alpha = clamp(rim * 0.85 + halo * 0.12 + filament * 0.22 + 0.025, 0.0, 1.0);
      gl_FragColor = vec4(uColor * light * mix(0.3, 1.0, uLife), alpha * mix(0.5, 1.0, uLife));
    }`,
};

// The aura: a soft light around the neuron, always facing you; it breathes at rest and swells when the region lights.
const AURA = {
  vertexShader: `
    varying vec2 vXY;
    void main() {
      vXY = position.xy;
      vec4 mv = modelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0);
      mv.xy += position.xy;
      gl_Position = projectionMatrix * mv;
    }`,
  fragmentShader: `
    uniform vec3 uColor; uniform float uGlow; uniform float uLife; uniform float uSize; uniform float uBreath;
    varying vec2 vXY;
    void main() {
      float r = length(vXY) / uSize;
      float near = exp(-r * r * 1.1);
      float far = exp(-r * 1.3);
      float end = 1.0 - smoothstep(3.0, 4.0, r);
      float a = (near * 0.62 + far * 0.3) * end * (0.5 + 0.35 * uBreath + uGlow * 1.7) * uLife;
      gl_FragColor = vec4(uColor * a, clamp(a, 0.0, 1.0));
    }`,
};

const RING = {
  vertexShader: `
    varying vec2 vXY;
    void main() { vXY = position.xy; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: `
    uniform vec3 uColor; uniform float uTime; uniform float uGlow; uniform float uLife; uniform float uSpin;
    varying vec2 vXY;
    void main() {
      float turn = atan(vXY.y, vXY.x) / 6.2831853 + 0.5;
      float dash = step(0.6, fract(turn * 64.0));
      float arc = smoothstep(0.8, 1.0, fract(turn - uTime * uSpin));
      float alpha = (dash * 0.14 + arc * 0.8) * (0.3 + uGlow * 0.7) * uLife;
      gl_FragColor = vec4(uColor * (1.1 + arc * 1.6 + uGlow * 2.4), clamp(alpha, 0.0, 1.0));
    }`,
};

// The ripple a lit region sends out: a thin soft ring of light, facing you, that widens and fades (a ring scaled up
// had grown into a thick grey band).
const RIPPLE = {
  vertexShader: AURA.vertexShader,
  fragmentShader: `
    uniform vec3 uColor; uniform float uFade; uniform float uRadius; uniform float uWidth;
    varying vec2 vXY;
    void main() {
      float x = (length(vXY) - uRadius) / uWidth;
      float a = exp(-x * x) * uFade;
      gl_FragColor = vec4(uColor * 2.2 * a, clamp(a, 0.0, 1.0));
    }`,
};

// Particles in orbit; and, with no orbit (aSpeed 0), the boutons at the tips of the dendrites.
const SPARKS = {
  vertexShader: `
    attribute vec3 aU; attribute vec3 aV; attribute float aRadius; attribute float aSpeed; attribute float aPhase;
    uniform float uTime; uniform float uGlow; uniform float uPx; uniform float uDpr;
    varying float vBright;
    void main() {
      float a = aPhase + uTime * aSpeed * (1.0 + uGlow * 2.5);
      vec3 p = position + (cos(a) * aU + sin(a) * aV) * aRadius;
      vec4 mv = modelViewMatrix * vec4(p, 1.0);
      vBright = 0.55 + 0.45 * sin(aPhase * 3.0 + uTime * (0.9 + abs(aSpeed)));
      gl_PointSize = uPx * uDpr * (1.0 + uGlow * 0.8) * 320.0 / max(-mv.z, 0.1);
      gl_Position = projectionMatrix * mv;
    }`,
  fragmentShader: `
    uniform vec3 uColor; uniform float uGlow;
    varying float vBright;
    void main() {
      float d = length(gl_PointCoord - 0.5);
      float alpha = (1.0 - smoothstep(0.0, 0.5, d)) * vBright;
      gl_FragColor = vec4(uColor * (1.8 + uGlow * 3.0), alpha);
    }`,
};

const DENDRITE = {
  vertexShader: `
    attribute float aSeed;
    varying vec2 vUv; varying float vSeed;
    void main() { vUv = uv; vSeed = aSeed; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: `
    uniform vec3 uColor; uniform float uTime; uniform float uGlow;
    varying vec2 vUv; varying float vSeed;
    void main() {
      float along = clamp(vUv.x, 0.0, 1.0);
      float fade = (1.0 - along) * (1.0 - along);
      float bead = 1.0 - smoothstep(0.0, 0.06, abs(fract(along * 1.4 - uTime * 0.35 - vSeed) - 0.5));
      float alpha = fade * (0.3 + uGlow * 0.6) + bead * (0.2 + 0.8 * (1.0 - along)) * (0.5 + uGlow);
      gl_FragColor = vec4(uColor * (1.1 + bead * 2.4 + uGlow * 2.2), clamp(alpha, 0.0, 1.0));
    }`,
};

function material(
  shader: { vertexShader: string; fragmentShader: string },
  uniforms: Record<string, THREE.IUniform>
) {
  return new THREE.ShaderMaterial({
    ...shader,
    uniforms,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    toneMapped: false,
  });
}

// A tube along `curve`, thinning to a point (a dendrite tapers), its length read 0 to 1 from `from` to `to`.
function tapered(curve: THREE.Curve<THREE.Vector3>, radius: number, from: number, to: number) {
  const segments = 26;
  const sides = 5;
  const tube = new THREE.TubeGeometry(curve, segments, radius, sides, false);
  const at = tube.attributes.position;
  const uv = tube.attributes.uv;
  const centre = new THREE.Vector3();
  const v = new THREE.Vector3();
  for (let i = 0; i <= segments; i++) {
    curve.getPointAt(i / segments, centre);
    const thin = 1 - 0.85 * (i / segments);
    for (let j = 0; j <= sides; j++) {
      const k = i * (sides + 1) + j;
      v.fromBufferAttribute(at, k).sub(centre).multiplyScalar(thin).add(centre);
      at.setXYZ(k, v.x, v.y, v.z);
      uv.setX(k, from + (to - from) * (i / segments));
    }
  }
  return tube;
}

function dendrites(region: Region): { tubes: THREE.BufferGeometry; tips: THREE.BufferGeometry } {
  // A few bent filaments leaving the membrane, most of them forking once; fewer and finer on a small region.
  const rand = random(region.id);
  const count = region.size > 0.3 ? 10 : region.size > 0.2 ? 8 : 6;
  const parts: THREE.BufferGeometry[] = [];
  const tips: number[] = [];
  const width = 0.005 + region.size * 0.012;
  for (let i = 0; i < count; i++) {
    const angle = (i / count) * Math.PI * 2 + rand() * 0.5;
    const lift = (rand() - 0.5) * 1.2;
    const dir = new THREE.Vector3(Math.cos(angle), Math.sin(angle) * 0.9, lift).normalize();
    const side = new THREE.Vector3().crossVectors(dir, new THREE.Vector3(0, 0, 1)).normalize();
    const up = new THREE.Vector3().crossVectors(dir, side).normalize();
    const length = region.size * (1.2 + rand() * 1.1);
    const bend = () =>
      side
        .clone()
        .multiplyScalar((rand() - 0.5) * region.size * 0.5)
        .add(up.clone().multiplyScalar((rand() - 0.5) * region.size * 0.35));
    const points = [0.9, 1.3, 1.75, 2.2].map((k, j) =>
      dir
        .clone()
        .multiplyScalar(region.size * 0.9 + (length * (k - 0.9)) / 1.3)
        .add(bend().multiplyScalar(j / 2))
    );
    const curve = new THREE.CatmullRomCurve3(points);
    const main = tapered(curve, width, 0, 1);
    parts.push(main);
    tips.push(...points[points.length - 1].toArray());
    if (rand() < 0.7) {
      // a branch from about halfway out, turning off to one side
      const from = 0.45 + rand() * 0.2;
      const start = curve.getPointAt(from);
      const heading = curve
        .getTangentAt(from)
        .add(side.clone().multiplyScalar(rand() > 0.5 ? 0.9 : -0.9))
        .normalize();
      const reach = length * (0.35 + rand() * 0.25);
      const fork = new THREE.CatmullRomCurve3([
        start,
        start
          .clone()
          .add(heading.clone().multiplyScalar(reach * 0.5))
          .add(bend().multiplyScalar(0.3)),
        start.clone().add(heading.clone().multiplyScalar(reach)),
      ]);
      parts.push(tapered(fork, width * (1 - 0.85 * from), from, 1));
      tips.push(...start.clone().add(heading.clone().multiplyScalar(reach)).toArray());
    }
  }
  for (const part of parts) {
    const seed = new Float32Array(part.attributes.position.count).fill(rand());
    part.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1));
  }
  const tubes = mergeGeometries(parts);
  for (const part of parts) part.dispose();
  const n = tips.length / 3;
  const ends = new THREE.BufferGeometry();
  ends.setAttribute('position', new THREE.BufferAttribute(new Float32Array(tips), 3));
  ends.setAttribute('aU', new THREE.BufferAttribute(new Float32Array(n * 3), 3));
  ends.setAttribute('aV', new THREE.BufferAttribute(new Float32Array(n * 3), 3));
  ends.setAttribute('aRadius', new THREE.BufferAttribute(new Float32Array(n), 1));
  ends.setAttribute('aSpeed', new THREE.BufferAttribute(new Float32Array(n), 1));
  ends.setAttribute(
    'aPhase',
    new THREE.BufferAttribute(
      Float32Array.from({ length: n }, () => rand() * Math.PI * 2),
      1
    )
  );
  ends.boundingSphere = new THREE.Sphere(new THREE.Vector3(), region.size * 4);
  return { tubes, tips: ends };
}

function orbits(region: Region): THREE.BufferGeometry {
  const rand = random(`${region.id}:orbit`);
  const count = region.size > 0.3 ? 16 : 11;
  const u = new Float32Array(count * 3);
  const v = new Float32Array(count * 3);
  const radius = new Float32Array(count);
  const speed = new Float32Array(count);
  const phase = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    const normal = new THREE.Vector3(rand() - 0.5, rand() - 0.5, rand() - 0.5).normalize();
    const a = new THREE.Vector3().crossVectors(normal, new THREE.Vector3(0, 1, 0.3)).normalize();
    const b = new THREE.Vector3().crossVectors(normal, a).normalize();
    u.set([a.x, a.y, a.z], i * 3);
    v.set([b.x, b.y, b.z], i * 3);
    radius[i] = region.size * (1.25 + rand() * 0.9);
    speed[i] = (0.25 + rand() * 0.55) * (rand() > 0.5 ? 1 : -1);
    phase[i] = rand() * Math.PI * 2;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count * 3), 3));
  g.setAttribute('aU', new THREE.BufferAttribute(u, 3));
  g.setAttribute('aV', new THREE.BufferAttribute(v, 3));
  g.setAttribute('aRadius', new THREE.BufferAttribute(radius, 1));
  g.setAttribute('aSpeed', new THREE.BufferAttribute(speed, 1));
  g.setAttribute('aPhase', new THREE.BufferAttribute(phase, 1));
  g.boundingSphere = new THREE.Sphere(new THREE.Vector3(), region.size * 3);
  return g;
}

export function Neuron({
  region,
  live,
  hovered,
  picked,
  still,
}: {
  region: Region;
  live: MutableRefObject<{ lit: Lit }>;
  hovered: boolean; // (the page finds what a pointer or a finger is on: the nearest sphere on screen)
  picked: boolean;
  still: boolean; // reduced motion: its own slow life stands still (a recorded light still shows)
}) {
  const group = useRef<THREE.Group>(null);
  const ring = useRef<THREE.Mesh>(null);
  const ripple = useRef<THREE.Mesh>(null);
  const { invalidate, gl } = useThree();
  const life = region.runs ? 1 : 0.16;
  const base = useMemo(() => new THREE.Color(region.color), [region.color]);
  const error = useMemo(() => new THREE.Color(COLORS.error), []);
  const tint = useMemo(() => new THREE.Color(), []);
  const breath = useMemo(() => random(region.id)() * Math.PI * 2, [region.id]);
  const membrane = useMemo(
    () =>
      material(MEMBRANE, {
        uColor: { value: new THREE.Color(region.color) },
        uTime: { value: 0 },
        uGlow: { value: 0 },
        uLife: { value: life },
        uSize: { value: region.size },
      }),
    [region.color, region.size, life]
  );
  const nucleus = useMemo(
    () => new THREE.MeshBasicMaterial({ color: region.color, toneMapped: false }),
    [region.color]
  );
  const aura = useMemo(
    () =>
      material(AURA, {
        uColor: { value: new THREE.Color(region.color) },
        uGlow: { value: 0 },
        uLife: { value: region.runs ? 1 : 0 },
        uSize: { value: region.size },
        uBreath: { value: 0 },
      }),
    [region.color, region.size, region.runs]
  );
  const halo = useMemo(
    () =>
      material(RING, {
        uColor: { value: new THREE.Color(region.color) },
        uTime: { value: 0 },
        uGlow: { value: 0 },
        uLife: { value: region.runs ? 1 : 0 },
        uSpin: { value: 0.05 + random(`${region.id}:spin`)() * 0.07 },
      }),
    [region.color, region.id, region.runs]
  );
  const wave = useMemo(
    () =>
      material(RIPPLE, {
        uColor: { value: new THREE.Color(region.color) },
        uFade: { value: 0 },
        uRadius: { value: region.size },
        uWidth: { value: region.size * 0.05 },
      }),
    [region.color]
  );
  const dots = useMemo(
    () =>
      material(SPARKS, {
        uColor: { value: new THREE.Color(region.color) },
        uTime: { value: 0 },
        uGlow: { value: 0 },
        uPx: { value: 0.1 },
        uDpr: { value: gl.getPixelRatio() },
      }),
    [region.color, gl]
  );
  const buds = useMemo(
    () =>
      material(SPARKS, {
        uColor: { value: new THREE.Color(region.color) },
        uTime: { value: 0 },
        uGlow: { value: 0 },
        uPx: { value: 0.085 },
        uDpr: { value: gl.getPixelRatio() },
      }),
    [region.color, gl]
  );
  const wire = useMemo(
    () =>
      material(DENDRITE, {
        uColor: { value: new THREE.Color(region.color) },
        uTime: { value: 0 },
        uGlow: { value: 0 },
      }),
    [region.color]
  );
  const branches = useMemo(() => (region.runs ? dendrites(region) : null), [region]);
  const orbitGeometry = useMemo(() => (region.runs ? orbits(region) : null), [region]);
  useEffect(
    () => () => {
      for (const m of [membrane, nucleus, aura, halo, wave, dots, buds, wire]) m.dispose();
      branches?.tubes.dispose();
      branches?.tips.dispose();
      orbitGeometry?.dispose();
    },
    [membrane, nucleus, aura, halo, wave, dots, buds, wire, branches, orbitGeometry]
  );
  useEffect(() => invalidate(), [hovered, picked, invalidate]); // (a hover shows at once)

  useFrame(({ camera, clock }) => {
    if (!group.current) return;
    const t = still ? 0 : clock.elapsedTime;
    const was = region.runs ? live.current.lit.get(region.id) : undefined; // (switched off: never lit)
    const age = was ? now() - was.at : Infinity;
    const k = age >= 0 && age < GLOW ? ease(1 - age / GLOW) : 0; // (lit when its signal arrives)
    const focus = hovered || picked ? 1 : 0;
    const glow = k + focus * 0.35;
    tint.copy(was && was.state === 'error' && k > 0 ? error : base);
    const breathing = 0.5 + 0.5 * Math.sin(t * 1.3 + breath);
    // The nucleus is bright enough at rest for the bloom to give it a glow, and keeps its hue (brighter, it burnt
    // white); a cortex switched off keeps only a dark ember.
    nucleus.color
      .copy(tint)
      .multiplyScalar(region.runs ? 1.12 + 0.3 * breathing + k * 3.2 + focus * 0.5 : 0.05);
    for (const m of [membrane, halo, dots, buds, wire, aura]) {
      m.uniforms.uColor.value.copy(tint);
      if (m.uniforms.uTime) m.uniforms.uTime.value = t;
      m.uniforms.uGlow.value = glow;
    }
    aura.uniforms.uColor.value.offsetHSL(0, 0.14, -0.04); // (its aura a little deeper in colour than its light)
    aura.uniforms.uBreath.value = breathing;
    group.current.scale.setScalar(1 + (still ? 0 : k * 0.14) + (hovered ? 0.05 : 0));
    if (ring.current) ring.current.quaternion.copy(camera.quaternion); // (it always faces you)
    if (ripple.current) {
      ripple.current.visible = k > 0 && !still;
      wave.uniforms.uColor.value.copy(tint);
      wave.uniforms.uRadius.value = region.size * (1.05 + (1 - k) * 2.3);
      wave.uniforms.uWidth.value = region.size * (0.045 + (1 - k) * 0.05);
      wave.uniforms.uFade.value = k * k * 0.85;
    }
  });

  return (
    <group ref={group} position={region.at}>
      <mesh material={membrane}>
        <sphereGeometry args={[region.size, 48, 48]} />
      </mesh>
      <mesh material={nucleus}>
        <icosahedronGeometry args={[region.size * 0.38, 3]} />
      </mesh>
      {region.runs && (
        <>
          <mesh material={aura} renderOrder={-1}>
            <planeGeometry args={[region.size * 8, region.size * 8]} />
          </mesh>
          <mesh ref={ring} material={halo}>
            <ringGeometry args={[region.size * 1.55, region.size * 1.6, 192, 1]} />
          </mesh>
          <mesh ref={ripple} material={wave} visible={false}>
            <planeGeometry args={[region.size * 8, region.size * 8]} />
          </mesh>
          {branches && <mesh geometry={branches.tubes} material={wire} />}
          {branches && <points geometry={branches.tips} material={buds} />}
          {orbitGeometry && <points geometry={orbitGeometry} material={dots} />}
        </>
      )}
    </group>
  );
}
