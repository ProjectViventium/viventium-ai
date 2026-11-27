'use client';

import { useEffect, useRef, useState } from 'react';
import styles from './mark.module.css';

// Viventium's mark, alive: the V as poured clear glass. The glass itself is a photoreal render made from the
// logo's exact shape (public/marks/v-glass.webp: an image model given the mark as its reference, the way
// xPerfect's glass X was made; cut out of its black background and graded).
// Nothing is drawn on top of it. One small shader reads the glass's own surface out of the render (thick
// inside each piece, sloping at its bevels, ridged where the render shows folds) and lights that surface:
// a studio light that slowly travels, so its line of light slides along every bevel at once the way it does
// on a real glass object; facets turned toward it brighten and the others dim; the render's own reflections
// shift a little inside the glass as it turns. The pointer is a second, small light and a finger on the
// surface. The outline never moves, so it stays crisp. Light added is warm white only.
// Still when reduced motion is asked for; the plain picture without WebGL.

const SRC = '/marks/v-glass.webp';

const CORNERS = `#version 300 es
in vec2 corner;
out vec2 uv;
void main() { uv = corner * 0.5 + 0.5; uv.y = 1.0 - uv.y; gl_Position = vec4(corner, 0.0, 1.0); }
`;
const LIGHT = `#version 300 es
precision highp float;
uniform sampler2D u_glass;
uniform float u_time;
uniform vec2 u_ptr;      // the pointer in the picture (0..1)
uniform float u_touch;   // 0..1: how near the pointer is
uniform vec2 u_tilt;     // -1..1: how far the glass is turned toward the pointer
in vec2 uv;
out vec4 colour;
float lum(vec3 c) { return dot(c, vec3(0.299, 0.587, 0.114)); }
// The surface, read from the render itself.
float height(vec2 p) {
  float body = textureLod(u_glass, p, 4.0).a;          // each piece is thick in its middle
  float bevel = textureLod(u_glass, p, 2.2).a;         // and slopes at its edge
  float folds = lum(textureLod(u_glass, p, 1.2).rgb);  // the ridges the render shows
  vec2 to = p - u_ptr;
  float finger = exp(-dot(to, to) * 90.0) * u_touch;   // pressed in under the pointer
  return body * 0.55 + bevel * 0.35 + folds * 0.22 - finger * 0.18;
}
void main() {
  float t = u_time;
  float d = 2.0 / float(textureSize(u_glass, 0).x);
  float hx = height(uv + vec2(d, 0.0)) - height(uv - vec2(d, 0.0));
  float hy = height(uv + vec2(0.0, d)) - height(uv - vec2(0.0, d));
  vec3 n = normalize(vec3(-hx, -hy, 2.0 * d * 9.0));
  float thick = textureLod(u_glass, uv, 4.0).a;

  // Seen through: the render's own reflections move a little inside the glass as it turns.
  vec2 at = uv - u_tilt * 0.014 * thick + n.xy * 0.006 * sin(t * 0.37 + thick * 3.0);
  vec4 glass = texture(u_glass, at);
  float shape = texture(u_glass, uv).a;                // the outline never moves
  float body = max(glass.a, shape * 0.2);

  // The light: one studio light that travels slowly, never quite repeating its path.
  vec3 view = normalize(vec3(u_tilt * 0.45, 1.0));
  float a = t * 0.21;
  vec3 key = normalize(vec3(cos(a) * 0.9 + 0.25 * sin(a * 2.3), sin(a * 0.8) * 0.7 - 0.35, 0.75));
  vec3 r = reflect(-view, n);
  // A long softbox seen in the glass: one line of light that slides along every bevel at once.
  float strip = dot(r.xy, normalize(vec2(cos(a * 0.6 + 0.7), sin(a * 0.6 + 0.7)))) - 0.55 * sin(t * 0.17);
  float softbox = exp(-strip * strip * 38.0);
  float spec = pow(max(dot(r, key), 0.0), 70.0);
  float facing = max(dot(n, key), 0.0);
  float rim = pow(1.0 - n.z, 2.5);
  // The pointer is a small second light.
  vec3 near = normalize(vec3((u_ptr - uv) * 2.4, 0.55));
  float touchLight = pow(max(dot(r, near), 0.0), 40.0) * u_touch;

  vec3 warmWhite = vec3(1.0, 0.975, 0.93);
  float added = softbox * (0.25 + rim * 1.6) + spec * 1.3 + touchLight * 0.9;
  vec3 rgb = glass.rgb * (0.78 + 0.42 * facing) + warmWhite * added;
  float a2 = clamp(body + added * 0.75 * shape, 0.0, 1.0) * smoothstep(0.02, 0.2, shape);
  colour = vec4(min(rgb, vec3(1.0)) * a2, a2);
}
`;

/** busy: the light travels faster while something is being changed. */
export function Mark({ size = 132, busy = false }: { size?: number; busy?: boolean }) {
  const box = useRef<HTMLSpanElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const pace = useRef(1);
  const [plain, setPlain] = useState(false); // no WebGL, or reduced motion: the picture itself
  pace.current = busy ? 2.4 : 1;

  useEffect(() => {
    const el = canvas.current;
    const host = box.current;
    if (!el || !host) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return setPlain(true);
    const gl = el.getContext('webgl2', { alpha: true, premultipliedAlpha: true, antialias: false });
    if (!gl) return setPlain(true);
    const program = gl.createProgram();
    for (const [type, source] of [
      [gl.VERTEX_SHADER, CORNERS],
      [gl.FRAGMENT_SHADER, LIGHT],
    ] as const) {
      const shader = gl.createShader(type)!;
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        console.error('mark:', gl.getShaderInfoLog(shader));
        return setPlain(true);
      }
      gl.attachShader(program, shader);
    }
    gl.linkProgram(program);
    gl.useProgram(program);
    const density = Math.min(3, Math.max(2, window.devicePixelRatio || 1));
    el.width = el.height = Math.round(size * density);
    gl.viewport(0, 0, el.width, el.height);
    const corners = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, corners);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const where = gl.getAttribLocation(program, 'corner');
    gl.enableVertexAttribArray(where);
    gl.vertexAttribPointer(where, 2, gl.FLOAT, false, 0, 0);
    const at = (name: string) => gl.getUniformLocation(program, name);
    const [time, ptr, touch, tilt] = [at('u_time'), at('u_ptr'), at('u_touch'), at('u_tilt')];

    const texture = gl.createTexture();
    let ready = false;
    const picture = new Image();
    picture.onload = () => {
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, 0);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, picture);
      gl.generateMipmap(gl.TEXTURE_2D);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      ready = true;
    };
    picture.onerror = () => setPlain(true);
    picture.src = SRC;

    const pointer = { x: 9, y: 9, on: false };
    const felt = { x: 9, y: 9, touch: 0, tx: 0, ty: 0 };
    const moved = (e: PointerEvent) => {
      const here = host.getBoundingClientRect();
      pointer.x = (e.clientX - here.left) / here.width;
      pointer.y = (e.clientY - here.top) / here.height;
      pointer.on = Math.hypot(pointer.x - 0.5, pointer.y - 0.5) < 1.6; // near enough to feel
    };
    window.addEventListener('pointermove', moved, { passive: true });
    let seen = true;
    const watch = new IntersectionObserver(([entry]) => (seen = entry.isIntersecting));
    watch.observe(el);
    let t = 0;
    let last = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      if (ready && seen && document.visibilityState === 'visible') {
        t += dt * pace.current;
        const ease = 1 - Math.exp(-dt * 6);
        felt.x += (pointer.x - felt.x) * ease;
        felt.y += (pointer.y - felt.y) * ease;
        felt.touch += ((pointer.on ? 1 : 0) - felt.touch) * (1 - Math.exp(-dt * 4));
        const turn = 1 - Math.exp(-dt * 3);
        felt.tx += ((pointer.on ? Math.max(-1, Math.min(1, pointer.x - 0.5)) : 0) - felt.tx) * turn;
        felt.ty += ((pointer.on ? Math.max(-1, Math.min(1, pointer.y - 0.5)) : 0) - felt.ty) * turn;
        host.style.setProperty('--tx', felt.tx.toFixed(3));
        host.style.setProperty('--ty', felt.ty.toFixed(3));
        gl.uniform1f(time, t);
        gl.uniform2f(ptr, felt.x, felt.y);
        gl.uniform1f(touch, felt.touch);
        gl.uniform2f(tilt, felt.tx, felt.ty);
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      watch.disconnect();
      window.removeEventListener('pointermove', moved);
      gl.deleteTexture(texture);
      gl.deleteBuffer(corners);
      gl.deleteProgram(program);
    };
  }, [size]);

  return (
    <span
      ref={box}
      role="img"
      aria-label="Viventium"
      data-mark={plain ? 'picture' : 'liquid'}
      className={styles.mark}
      style={{ width: size, height: size }}
    >
      <span className={styles.turn}>
        {plain ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={SRC} alt="" width={size} height={size} draggable={false} />
        ) : (
          <canvas ref={canvas} style={{ width: size, height: size }} aria-hidden />
        )}
      </span>
    </span>
  );
}
