// The Live view's map of her brain: each region, where it sits (top to bottom, the way a turn travels), its colour,
// and the wires between them. Regions are what Light really has; the cortices come from the Subconscious page, and
// every cortex that is on runs (brain/rounds.py): after her answer the Subconscious coordinator picks, the cortices
// think, and their thoughts go back to the mind. A cortex switched off is drawn dark, and never lit.

export type Step = {
  region: string;
  at: number;
  took?: number;
  what: string;
  detail?: string; // metadata expanded within its existing turn row
  state: 'ok' | 'act' | 'quiet' | 'warn' | 'error';
  band?: string; // a Feelings step: the band that moved
  full?: string; // what it said, whole as recorded, when `what` shows only its start (a cortex's thought)
  where?: string; // what it ran on, as recorded
  late?: boolean; // recorded after a later turn began
};
export type Trace = {
  id: string;
  channel: 'call' | 'typed' | 'telegram' | 'unknown';
  start: number;
  end: number;
  words: string;
  by: 'you' | 'her'; // who began it: their words, or a heartbeat, a reminder, a Worker's result
  kind: 'words' | 'beat' | 'reminder' | 'greeting' | 'worker' | 'unknown';
  reply: string;
  steps: Step[];
};
export type Cortex = { id: string; name: string; region: string; on: boolean; group: string };

export type Region = {
  id: string;
  name: string;
  part: string; // the brain region it stands for
  at: [number, number, number];
  color: string;
  size: number;
  runs: boolean; // false: shown, never lit (a cortex switched off)
};

// Cool hues only (the settings page's design language: no warm fills), white for the mind.
export const COLORS: Record<string, string> = {
  ears: '#7dd3fc',
  gate: '#e2e8f0',
  memory: '#5eead4',
  feelings: '#c4b5fd',
  mind: '#ffffff',
  voice: '#67e8f9',
  hands: '#a5b4fc',
  clock: '#cbd5e1',
  subconscious: '#b8c4d6',
  cortex: '#93a4bd',
  warn: '#f0abfc',
  error: '#ed9187', // (the settings page's own "low" colour)
};

export const CORE: Region[] = [
  {
    id: 'ears',
    name: 'Hearing',
    part: 'Auditory cortex',
    at: [0, 3.45, 0],
    color: COLORS.ears,
    size: 0.28,
    runs: true,
  },
  {
    id: 'gate',
    name: 'One word',
    part: 'Thalamus · the gate',
    at: [0, 2.25, 0.2],
    color: COLORS.gate,
    size: 0.22,
    runs: true,
  },
  {
    id: 'mind',
    name: 'Conscious mind',
    part: 'Prefrontal cortex',
    at: [0, -0.55, 0.5],
    color: COLORS.mind,
    size: 0.42,
    runs: true,
  },
  {
    id: 'voice',
    name: 'Voice',
    part: "Broca's area",
    at: [0, -2.15, 0.2],
    color: COLORS.voice,
    size: 0.28,
    runs: true,
  },
  {
    id: 'hands',
    name: 'Workers',
    part: 'Hands',
    at: [3.25, -1.25, 0.1],
    color: COLORS.hands,
    size: 0.3,
    runs: true,
  },
  {
    id: 'clock',
    name: 'Continuous awareness',
    part: 'Brainstem',
    at: [-3.25, 2.85, -0.4],
    color: COLORS.clock,
    size: 0.2,
    runs: true,
  },
  {
    id: 'subconscious',
    name: 'Coordinator',
    part: 'Subconscious · its own copy',
    at: [0, 0.72, -1.1],
    color: COLORS.subconscious,
    size: 0.2,
    runs: true,
  },
];

// The two cortices that come running on every turn, by the region the live record names for them (Feelings' own
// trail, Deep memory's finds).
export const EVERY_TURN: Record<string, string> = {
  'emotional-reaction': 'feelings',
  'deep-memory': 'memory',
};

// The cortices behind the mind. The two every turn has stand out on either side, at the height of the limbic system
// (Emotional reaction left, Deep memory right), just under the other cortices' names; the others stand behind the
// coordinator in two staggered rows, in the Subconscious page's order left to right. Their places grow outward from
// the middle and never stand on it: the middle is the path every turn takes (One word, the coordinator), and a cortex
// there sat on the coordinator (the ninth card). On an arc the outer ones met; one row apart, no two names do.
const FLANKS: Record<string, [number, number, number]> = {
  feelings: [-2.15, 0.3, 0.15],
  memory: [2.15, 0.3, 0.15],
};
const STEP = 0.875; // (between neighbours; the same row is two steps apart, room for the longest name)
const GAP = 0.1; // (and a little more either side of the middle: One word's name is there)
const ROWS = [1.86, 1.18]; // (upper, lower)

export function cortexRegions(cortices: Cortex[]): Region[] {
  const resting = cortices.filter((c) => !EVERY_TURN[c.id]);
  // Places by distance from the middle, right first: step 1 either side (upper row), step 2 (lower), and so on.
  const places: number[] = [];
  for (let k = 1; places.length < resting.length; k++) places.push(GAP + k * STEP, -GAP - k * STEP);
  places.length = resting.length;
  places.sort((a, b) => a - b);
  const reach = Math.max(STEP, ...places.map(Math.abs));
  const behind = (x: number): [number, number, number] => [
    x,
    ROWS[Math.round((Math.abs(x) - GAP) / STEP) % 2 ? 0 : 1], // (odd steps the upper row, even ones the lower)
    -1.65 - 0.45 * (1 - (x / reach) ** 2), // (the middle a little deeper)
  ];
  return cortices.map((c) => {
    const flank = EVERY_TURN[c.id];
    const at = flank ? FLANKS[flank] : behind(places[resting.indexOf(c)]);
    return {
      id: flank ?? `cortex:${c.id}`,
      name: c.name,
      part: c.region,
      at,
      color: flank ? COLORS[flank] : COLORS.cortex,
      size: flank ? 0.26 : 0.16,
      runs: c.on, // (switched off on the Subconscious page: drawn dark, never lit)
    };
  });
}

// How far out the drawing reaches either side: the camera and the flat drawing step back to keep it all in view.
export function reach(regions: Region[]): number {
  return Math.max(3.5, ...regions.map((r) => Math.abs(r.at[0])));
}

// Where a name stands across the stage: under its region, but never past the stage's edge (a region near the side,
// a narrow window: "Continuous awareness" ran off the left edge on a phone).
export function inside(x: number, width: number, stage: number): number {
  const half = width / 2 + 6;
  return stage > 2 * half ? Math.min(Math.max(x, half), stage - half) : stage / 2;
}

// A name as drawn: its box (centre, width, height) under its region's sphere (centre, radius), in the stage's pixels.
export type Placed = {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  ball: [number, number, number];
};

// Whether the names, every one shown, would meet each other or cover another region's sphere: the drawing is too small
// for them (a narrow window). Then only the parts every turn takes keep their names, and a cortex's shows when you
// point at it (names over each other said nothing). A touch of a pixel is not a meeting (the page test's measure);
// `room`: pixels to spare besides, so it does not flicker at the edge.
export function crowded(placed: Placed[], room = 0): boolean {
  const near = room - 2;
  for (const a of placed)
    for (const b of placed) {
      if (a === b) continue;
      if (
        a.id < b.id &&
        2 * Math.abs(a.x - b.x) < a.w + b.w + near &&
        2 * Math.abs(a.y - b.y) < a.h + b.h + near
      )
        return true;
      const [cx, cy, r] = b.ball;
      const nx = Math.max(a.x - a.w / 2, Math.min(cx, a.x + a.w / 2));
      const ny = Math.max(a.y - a.h / 2, Math.min(cy, a.y + a.h / 2));
      if ((nx - cx) ** 2 + (ny - cy) ** 2 < Math.max(0, r + near / 2) ** 2) return true;
    }
  return false;
}

// The wires a turn can travel: hearing to the gate, the gate to the mind, the mind to her voice and her Workers, the
// gate to the Workers (a hand-off made in her place), the heartbeat to the mind; after her answer the mind to the
// Subconscious coordinator, the coordinator to every cortex, and every cortex back to the mind.
export function wires(regions: Region[]): [string, string][] {
  const ids = new Set(regions.map((r) => r.id));
  const out: [string, string][] = [
    ['ears', 'gate'],
    ['gate', 'mind'],
    ['gate', 'hands'],
    ['mind', 'voice'],
    ['mind', 'hands'],
    ['clock', 'mind'],
    ['mind', 'subconscious'],
  ];
  for (const r of regions)
    if (!CORE.some((c) => c.id === r.id)) out.push(['subconscious', r.id], [r.id, 'mind']);
  return out.filter(([a, b]) => ids.has(a) && ids.has(b));
}

// Where the signals to a step come from: the wires it lights, given what this turn did before it. Hearing and the
// heartbeat start a turn; the gate hears what was heard; the coordinator is reached by the mind once it answered; a
// cortex by the coordinator; the mind by the gate (or the heartbeat) the first time, and by every cortex and Worker
// that finished since it last spoke; her voice by the mind; a Worker by the gate when the gate itself said "act",
// else by the mind.
export function sources(region: string, earlier: Step[]): string[] {
  const did = (r: string) => earlier.some((s) => s.region === r);
  const last = earlier[earlier.length - 1];
  const core = new Set(CORE.map((c) => c.id));
  switch (region) {
    case 'ears':
    case 'clock':
      return [];
    case 'gate':
      return did('ears') ? ['ears'] : [];
    case 'subconscious':
      return did('mind') ? ['mind'] : [];
    case 'voice':
      return did('mind') ? ['mind'] : [];
    case 'hands':
      return last?.region === 'gate' && last.state === 'act'
        ? ['gate']
        : did('mind')
          ? ['mind']
          : [];
    case 'mind': {
      const spoke = earlier.map((s) => s.region).lastIndexOf('mind');
      const since = earlier.slice(spoke + 1).map((s) => s.region);
      const thoughts = [
        ...new Set(since.filter((r) => (!core.has(r) || r === 'hands') && r !== 'subconscious')),
      ];
      const first = spoke < 0 ? (did('clock') ? ['clock'] : did('gate') ? ['gate'] : []) : [];
      return [...first, ...thoughts];
    }
    default: // a cortex: picked by the coordinator, or started with the round
      return did('subconscious') ? ['subconscious'] : did('mind') ? ['mind'] : [];
  }
}

// A turn's steps, replayed in their own order with their real gaps, made to fit a few seconds.
export function schedule(trace: Trace | undefined, total = 4.2): { step: Step; at: number }[] {
  if (!trace || !trace.steps.length) return [];
  const start = trace.steps[0].at;
  const span = Math.max(0.001, trace.steps[trace.steps.length - 1].at - start);
  const scale = Math.min(1, total / span);
  let last = -1;
  return trace.steps.map((step) => {
    const at = Math.max(last + 0.28, (step.at - start) * scale);
    last = at;
    return { step, at };
  });
}

export function ago(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return s < 60
    ? `${s} s ago`
    : s < 3600
      ? `${Math.round(s / 60)} min ago`
      : `${Math.round(s / 3600)} h ago`;
}
