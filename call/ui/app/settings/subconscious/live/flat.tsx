'use client';

// The same brain, flat (SVG): for a browser without WebGL 2, and when motion is reduced (lit regions, no sparks).
import type { Region } from './brain';
import { COLORS } from './brain';

const W = 900;
const H = 760;
// Drawn as the 3D camera sees it (from z 10.6, its eye at 0.6, a 38° view), so every region and name stands where it
// does in 3D: depth sets how far out and how big. Drawn smaller when the cortices reach further out (more cards).
const EYE = 10.6;
const FOCAL = H / 2 / Math.tan((19 * Math.PI) / 180);
type Spot = { x: number; y: number; r: number };
function view(regions: Region[]): (r: Region) => Spot {
  const out = Math.max(0.3, ...regions.map((r) => Math.abs(r.at[0]) / (EYE - r.at[2])));
  const f = Math.min(FOCAL, (W / 2 - 70) / out);
  return (r) => {
    const d = EYE - r.at[2];
    return {
      x: W / 2 + (r.at[0] / d) * f,
      y: H / 2 - ((r.at[1] - 0.6) / d + 0.05 / EYE) * f,
      r: (r.size / d) * f,
    };
  };
}

export default function Flat({
  regions,
  wires,
  lit,
  sparks,
  hovered,
  picked,
  still,
}: {
  regions: Region[];
  wires: [string, string][];
  lit: Record<string, { state: string; n: number }>; // region id -> how it last lit, and how many times
  sparks: { id: string; from: string; to: string; color: string }[];
  hovered: string | null; // (what a pointer is on: the page finds it, as in 3D)
  picked: string | null;
  still: boolean;
}) {
  const byId = new Map(regions.map((r) => [r.id, r]));
  const spot = view(regions);
  const path = (a: Region, b: Region) => {
    const p = spot(a);
    const q = spot(b);
    return `M ${p.x} ${p.y} Q ${(p.x + q.x) / 2} ${(p.y + q.y) / 2 - 18} ${q.x} ${q.y}`;
  };
  return (
    <svg
      className="vlx-flat"
      data-still={still}
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label="Viventium's brain, region by region"
    >
      {wires.map(([a, b]) => {
        const p = byId.get(a);
        const q = byId.get(b);
        return p && q ? (
          <path
            key={`${a}>${b}`}
            d={path(p, q)}
            className="vlx-flat-wire"
            data-dim={!(p.runs && q.runs)}
          />
        ) : null;
      })}
      {!still &&
        sparks.map((s) => {
          const p = byId.get(s.from);
          const q = byId.get(s.to);
          return p && q ? (
            <circle key={s.id} r={4} fill={s.color} className="vlx-flat-spark">
              <animateMotion dur="0.5s" fill="freeze" path={path(p, q)} />
              <animate
                attributeName="opacity"
                values="1;1;0"
                keyTimes="0;0.7;1"
                dur="0.75s"
                fill="freeze"
              />
            </circle>
          ) : null;
        })}
      {regions.map((r) => (
        <g
          key={r.id}
          className="vlx-flat-node"
          data-lit={Boolean(lit[r.id])}
          data-runs={r.runs}
          data-hover={hovered === r.id || picked === r.id}
        >
          <circle cx={spot(r).x} cy={spot(r).y} r={spot(r).r} fill={r.color} />
          {lit[r.id] && (
            <circle
              key={lit[r.id].n}
              className="vlx-flat-glow"
              cx={spot(r).x}
              cy={spot(r).y}
              r={spot(r).r + 6}
              fill={lit[r.id].state === 'error' ? COLORS.error : r.color}
              style={{ color: lit[r.id].state === 'error' ? COLORS.error : r.color }}
            />
          )}
        </g>
      ))}
    </svg>
  );
}

export function flatPlace(
  regions: Region[],
  width: number,
  height: number
): Record<string, { label: [number, number]; ball: [number, number, number] }> {
  // Where each region's name shows (under its circle), in the box the SVG fills (it keeps its aspect: centered),
  // and where its circle is (centre, radius: the page test checks that no name covers another's).
  const k = Math.min(width / W, height / H);
  const ox = (width - W * k) / 2;
  const oy = (height - H * k) / 2;
  const spot = view(regions);
  return Object.fromEntries(
    regions.map((r) => {
      const { x, y, r: size } = spot(r);
      const ball: [number, number, number] = [
        Math.round(ox + x * k),
        Math.round(oy + y * k),
        Math.round(size * k),
      ];
      return [r.id, { label: [ox + x * k, oy + (y + size + 2) * k], ball }];
    })
  );
}
