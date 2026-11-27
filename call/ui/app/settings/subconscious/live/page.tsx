'use client';

// Live: her brain, turn by turn, as it really ran. Each turn Light recorded (a call, Chat, Telegram, a heartbeat, a
// Worker's result) is replayed through the regions it went through, in recorded order, with long gaps compressed.
// New records are followed, including a late step of an earlier turn. Hover, click or tap a region for its
// recent results. Nothing here is simulated: a light is a recorded step, and a cortex switched off is never lit.
//
// It starts reliably or says why not: drawn in 3D where the browser can, else (no WebGL 2, a frame that came out black
// even without the glow, a 3D view that did not start, a lost context that did not come back) the same brain flat,
// with a line saying so.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { ArrowLeft, Clock3, MessageSquare, Phone, RotateCcw, Send, Workflow } from 'lucide-react';
import {
  COLORS,
  CORE,
  type Cortex,
  type Placed,
  type Region,
  type Step,
  type Trace,
  ago,
  cortexRegions,
  crowded,
  inside,
  schedule,
  sources,
  wires as wiresOf,
} from './brain';
import Flat, { flatPlace } from './flat';
import './live.css';
import type { Health, Live } from './scene';

const Scene = dynamic(() => import('./scene'), { ssr: false });

const PULSE = 0.5; // (the scene's: a signal's time along a wire; a region lights when it arrives)
const GLOW = 1.8; // (the scene's: seconds a lit region takes to settle)
const LOOK = 1500; // ms between looks at what she did
const START = 8000; // ms of the tab being seen that the 3D view may take to draw its first frame
const RETURN = 3000; // ms a lost WebGL context may take to come back before the view starts afresh

type Showing = { id: string; upto: number }; // the turn on show, and its last step shown so far
type Why = 'none' | 'black' | 'start' | 'lost';

// Why the plain view is shown, in plain words.
const PLAIN: Record<Why, string> = {
  none: 'This browser cannot draw in 3D, so this is the plain view.',
  black: 'The 3D view could not draw on this computer, so this is the plain view.',
  start: 'The 3D view did not start, so this is the plain view.',
  lost: 'The 3D view stopped, so this is the plain view.',
};

function canDraw(): boolean {
  try {
    const gl = document.createElement('canvas').getContext('webgl2');
    gl?.getExtension('WEBGL_lose_context')?.loseContext(); // (a question only: its context is given back at once)
    return Boolean(gl);
  } catch {
    return false;
  }
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : Math.round((sorted[mid - 1] + sorted[mid]) / 2);
}

function took(ms?: number): string {
  if (ms === undefined) return '';
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;
}

function Channel({ trace }: { trace: Trace }) {
  if (trace.kind === 'unknown') return <Workflow />;
  if (trace.kind === 'worker') return <Workflow />;
  if (trace.kind === 'beat' || trace.kind === 'reminder') return <Clock3 />;
  return trace.channel === 'telegram' ? (
    <Send />
  ) : trace.channel === 'typed' ? (
    <MessageSquare />
  ) : (
    <Phone />
  );
}

export default function LivePage() {
  const [traces, setTraces] = useState<Trace[] | null>(null);
  const [skew, setSkew] = useState(0); // the server's clock minus this one, in seconds
  const [failed, setFailed] = useState(false);
  const [cortices, setCortices] = useState<Cortex[]>([]);
  const [bands, setBands] = useState<Record<string, { name: string; color: string }>>({});
  const [following, setFollowing] = useState(true);
  const [showing, setShowing] = useState<Showing | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [draw, setDraw] = useState<'3d' | 'flat' | null>(null);
  const [why, setWhy] = useState<Why | null>(null); // why it is drawn flat
  const [bloom, setBloom] = useState(true);
  const [drawn, setDrawn] = useState(false); // the 3D view's first frames came out right
  const [paused, setPaused] = useState(false); // its WebGL context is lost: the plain view stands in
  const [round, setRound] = useState(0); // a fresh start of the 3D view (a new canvas)
  const [still, setStill] = useState(false);
  const [version, setVersion] = useState(0);
  const [, setTick] = useState(0); // (keeps "2 min ago" true)
  const [flatLit, setFlatLit] = useState<Record<string, { state: string; n: number }>>({});
  const [sparks, setSparks] = useState<{ id: string; from: string; to: string; color: string }[]>(
    []
  );

  const live = useRef<Live>({ lit: new Map(), pulses: [] });
  const labels = useRef<Map<string, HTMLElement>>(new Map());
  const stage = useRef<HTMLDivElement>(null);
  const timers = useRef<number[]>([]);
  const glows = useRef<Map<string, number[]>>(new Map()); // each name's own light, on and off
  const queueEnd = useRef(0);
  const played = useRef<Map<string, Set<string>> | null>(null);
  const losses = useRef<number[]>([]);
  const waiting = useRef<number | null>(null);

  // How it can be drawn here: in 3D (WebGL 2), or flat, still when reduced motion is asked for.
  useEffect(() => {
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const set = () => setStill(motion.matches);
    set();
    motion.addEventListener('change', set);
    if (canDraw()) setDraw('3d');
    else {
      setDraw('flat');
      setWhy('none');
    }
    const clock = setInterval(() => setTick((t) => t + 1), 10000);
    return () => {
      motion.removeEventListener('change', set);
      clearInterval(clock);
    };
  }, []);

  // The 3D view must draw its first frames while the tab is seen; else the plain view, saying so. (A hidden tab draws
  // nothing at all, so only the time it is seen counts.)
  useEffect(() => {
    if (draw !== '3d' || drawn || paused) return;
    let seen = 0;
    const watch = setInterval(() => {
      if (document.hidden) return;
      seen += 250;
      if (seen >= START) {
        setDraw('flat');
        setWhy('start');
      }
    }, 250);
    return () => clearInterval(watch);
  }, [draw, drawn, paused, round, bloom]);

  const health = useCallback(
    (said: Health) => {
      if (said === 'drawn') setDrawn(true);
      else if (said === 'black') {
        setDrawn(false);
        if (bloom)
          setBloom(false); // (drawn again without the glow; black again, and it is the plain view)
        else {
          setDraw('flat');
          setWhy('black');
        }
      } else if (said === 'lost') {
        const t = Date.now();
        losses.current = [...losses.current.filter((at) => t - at < 120000), t];
        setPaused(true);
        setDrawn(false);
        if (losses.current.length >= 3) {
          setDraw('flat');
          setWhy('lost');
          return;
        }
        if (waiting.current) clearTimeout(waiting.current);
        waiting.current = window.setTimeout(() => {
          // (it did not come back by itself: a fresh canvas, a fresh context)
          setRound((r) => r + 1);
          setPaused(false);
        }, RETURN);
      } else if (said === 'restored') {
        if (waiting.current) clearTimeout(waiting.current);
        waiting.current = null;
        setRound((r) => r + 1); // (a fresh start: nothing of the lost context is trusted)
        setPaused(false);
      }
    },
    [bloom]
  );
  useEffect(
    () => () => {
      if (waiting.current) clearTimeout(waiting.current);
    },
    []
  );

  // The cortices as the Subconscious page has them, and Feelings' band colours: once.
  useEffect(() => {
    fetch('/api/settings/subconscious', { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => s && setCortices(s.cortices))
      .catch(() => {});
    fetch('/api/settings', { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => {
        const list = s?.character?.bands ?? [];
        setBands(
          Object.fromEntries(
            list.map((b: { id: string; name: string; color: string }) => [b.id, b])
          )
        );
      })
      .catch(() => {});
  }, []);

  // What she did: looked at again every LOOK ms while this tab is seen.
  useEffect(() => {
    let gone = false;
    const look = async () => {
      if (document.hidden) return;
      try {
        const reply = await fetch('/api/brain', { cache: 'no-store' });
        if (!reply.ok) throw new Error();
        const data = (await reply.json()) as { traces: Trace[]; now: number };
        if (gone) return;
        setTraces(data.traces);
        setSkew(data.now - Date.now() / 1000);
        setFailed(false);
      } catch {
        if (!gone) setFailed(true);
      }
    };
    look();
    const again = setInterval(look, LOOK);
    return () => {
      gone = true;
      clearInterval(again);
    };
  }, []);

  const regions: Region[] = useMemo(() => [...CORE, ...cortexRegions(cortices)], [cortices]);
  const byId = useMemo(() => new Map(regions.map((r) => [r.id, r])), [regions]);
  const wires = useMemo(() => wiresOf(regions), [regions]);
  const wired = useMemo(
    () => new Set(wires.flatMap(([a, b]) => [`${a}>${b}`, `${b}>${a}`])),
    [wires]
  );

  const tint = useCallback(
    (step: Step) =>
      step.state === 'error'
        ? COLORS.error
        : step.state === 'warn'
          ? COLORS.warn
          : (step.band && bands[step.band]?.color) || byId.get(step.region)?.color || COLORS.cortex,
    [bands, byId]
  );

  // A region's name lights with it (and goes back), so a light is read in words too.
  const glow = useCallback((id: string, state: string, after: number) => {
    const el = labels.current.get(id);
    if (!el) return;
    for (const t of glows.current.get(id) ?? []) clearTimeout(t);
    glows.current.set(id, [
      window.setTimeout(() => (el.dataset.lit = state), after),
      window.setTimeout(() => delete el.dataset.lit, after + GLOW * 1000),
    ]);
  }, []);

  // One step shown: its signals run along their wires, and the region lights as they arrive. A region switched off
  // is never lit, and no signal runs into it.
  const fire = useCallback(
    (trace: Trace, i: number) => {
      const step = trace.steps[i];
      if (!step) return;
      const t = performance.now() / 1000;
      const color = tint(step);
      const region = byId.get(step.region);
      const runs = Boolean(region?.runs);
      const from =
        runs && trace.kind !== 'unknown'
          ? sources(step.region, trace.steps.slice(0, i)).filter(
              (s) => wired.has(`${s}>${step.region}`) && byId.get(s)?.runs
            )
          : [];
      for (const s of from) live.current.pulses.push({ from: s, to: step.region, start: t, color });
      if (runs) {
        live.current.lit.set(step.region, { at: from.length ? t + PULSE : t, state: step.state });
        glow(step.region, step.state, from.length ? PULSE * 1000 : 0);
      }
      setShowing({ id: trace.id, upto: i });
      setVersion((v) => v + 1);
      if (runs)
        setFlatLit((had) => ({
          ...had,
          [step.region]: { state: step.state, n: (had[step.region]?.n ?? 0) + 1 },
        }));
      if (from.length) {
        const made = from.map((s) => ({
          id: `${trace.id}:${i}:${s}`,
          from: s,
          to: step.region,
          color,
        }));
        setSparks((had) => [...had.slice(-24), ...made]);
      }
    },
    [byId, tint, wired, glow]
  );

  const stop = useCallback(() => {
    for (const t of timers.current) clearTimeout(t);
    timers.current = [];
    queueEnd.current = 0;
  }, []);

  // Steps first..last of a turn, after whatever is still to be shown, in recorded order with adjusted timing.
  const enqueue = useCallback(
    (trace: Trace, first: number, last: number, total: number) => {
      const plan = schedule({ ...trace, steps: trace.steps.slice(first, last) }, total);
      const base = Math.max(performance.now() + 120, queueEnd.current + 280);
      plan.forEach(({ at }, k) => {
        const when = base + at * 1000;
        timers.current.push(
          window.setTimeout(() => fire(trace, first + k), when - performance.now())
        );
        queueEnd.current = when;
      });
    },
    [fire]
  );

  // A turn shown again from its first step: it only reads the record, and changes nothing.
  const replay = useCallback(
    (trace: Trace) => {
      stop();
      live.current.lit.clear();
      live.current.pulses = [];
      for (const list of glows.current.values()) for (const t of list) clearTimeout(t);
      glows.current.clear();
      for (const el of labels.current.values()) delete el.dataset.lit;
      setFlatLit({});
      setSparks([]);
      setShowing({ id: trace.id, upto: -1 });
      enqueue(trace, 0, trace.steps.length, 4.2);
    },
    [enqueue, stop]
  );

  // Track step identities across all turns. A late result must be shown on its source, even after a newer turn.
  useEffect(() => {
    if (!following || !traces?.length) return;
    const first = played.current === null;
    const seen = played.current ?? new Map<string, Set<string>>();
    const fresh: { trace: Trace; i: number }[] = [];
    for (const trace of traces) {
      const had = seen.get(trace.id) ?? new Set<string>();
      trace.steps.forEach((step, i) => {
        const key = JSON.stringify([step.at, step.region, step.what, step.band]);
        if (!had.has(key)) fresh.push({ trace, i });
        had.add(key);
      });
      seen.set(trace.id, had);
    }
    played.current = new Map(traces.map((trace) => [trace.id, seen.get(trace.id)!]));
    if (first) replay(traces[traces.length - 1]);
    else {
      fresh.sort((a, b) => a.trace.steps[a.i].at - b.trace.steps[b.i].at);
      // Keep recorded gaps within each consecutive group. Flattening every batch to 280 ms can replace a region's
      // first light before it is drawn when that region occurs twice in the batch.
      for (let at = 0; at < fresh.length; ) {
        const { trace, i } = fresh[at];
        let end = at + 1;
        while (
          end < fresh.length &&
          fresh[end].trace === trace &&
          fresh[end].i === fresh[end - 1].i + 1
        )
          end++;
        enqueue(trace, i, fresh[end - 1].i + 1, 4.2);
        at = end;
      }
    }
  }, [traces, following, replay, enqueue]);

  useEffect(() => stop, [stop]);

  // The flat drawing's labels sit where its regions are drawn.
  const flat = draw === 'flat' || paused;
  useEffect(() => {
    if (!flat || !stage.current) return;
    const box = stage.current;
    const place = () => {
      const at = flatPlace(regions, box.clientWidth, box.clientHeight);
      const placed: Placed[] = [];
      let holder: HTMLElement | null = null;
      for (const [id, { label, ball }] of Object.entries(at)) {
        const el = labels.current.get(id);
        if (!el) continue;
        const x = inside(label[0], el.offsetWidth, box.clientWidth);
        el.style.transform = `translate(${x}px, ${label[1]}px)`;
        el.dataset.ball = ball.join(' ');
        placed.push({
          id,
          x,
          y: label[1] + 7 + el.offsetHeight / 2,
          w: el.offsetWidth,
          h: el.offsetHeight,
          ball,
        });
        holder = el.parentElement;
      }
      if (holder) holder.dataset.tight = String(crowded(placed)); // (as in 3D: too small for every name)
    };
    place();
    const watch = new ResizeObserver(place);
    watch.observe(box);
    return () => watch.disconnect();
  }, [flat, regions]);

  const pick = useCallback((id: string) => setPicked((had) => (id && had !== id ? id : null)), []);

  // What a pointer or a finger is on, in 3D and flat alike, from where each region's sphere shows (its name says:
  // data-ball, centre and radius) and where its name is: inside a sphere, the nearest one; else on a name that is
  // shown; else the nearest sphere within 22 px (a 44 px target: a cortex is small on a phone). Names let the pointer
  // through (on a phone a name can lie over a small cortex behind it); a key opens them (they are buttons).
  const under = useCallback(
    (e: React.PointerEvent | React.MouseEvent): string | null | undefined => {
      if (!stage.current || (e.target as Element).closest('.vlx-card')) return undefined;
      const box = stage.current.getBoundingClientRect();
      const x = e.clientX - box.left;
      const y = e.clientY - box.top;
      let inside: string | null = null;
      let near: string | null = null;
      let named: string | null = null;
      let a = Infinity;
      let b = Infinity;
      for (const [id, el] of labels.current) {
        const [cx, cy, r] = (el.dataset.ball ?? '').split(' ').map(Number);
        const d = Math.hypot(x - cx, y - cy);
        if (d <= r && d < a) [inside, a] = [id, d];
        if (d <= Math.max(r * 1.25, 22) && d < b) [near, b] = [id, d];
        const name = el.querySelector('b')?.getBoundingClientRect();
        if (name && getComputedStyle(el).visibility !== 'hidden') {
          const [l, t] = [name.left - box.left, name.top - box.top];
          if (x >= l - 4 && x <= l + name.width + 4 && y >= t - 3 && y <= t + name.height + 3)
            named = id;
        }
      }
      return inside ?? named ?? near;
    },
    []
  );
  const shownTrace = traces?.find((t) => t.id === showing?.id);
  const upto = showing?.upto ?? -1;
  const spoke = shownTrace ? shownTrace.steps.findIndex((s) => s.region === 'voice') : -1;
  const focus = hovered || picked;
  const now = Date.now() / 1000 + skew;

  // A region's recent history, across every turn this page has: newest last.
  const history = useMemo(() => {
    const out = new Map<string, (Step & { trace: string; words: string })[]>();
    for (const trace of traces ?? []) {
      for (const step of trace.steps) {
        const list = out.get(step.region) ?? [];
        list.push({ ...step, trace: trace.id, words: trace.words });
        out.set(step.region, list);
      }
    }
    for (const list of out.values()) list.sort((a, b) => a.at - b.at);
    return out;
  }, [traces]);

  const region = focus ? byId.get(focus) : undefined;
  const past = focus ? (history.get(focus) ?? []).slice(-24) : [];
  const latest = past[past.length - 1];
  const timed = past.flatMap((s) => (s.took !== undefined ? [s.took] : [])); // (a bar's height: how long it took)
  const slowest = Math.max(1, ...timed);

  return (
    <div className="vlx">
      <header className="vlx-top">
        <Link href="/settings/subconscious" className="vlx-back">
          <ArrowLeft />
          Subconscious
        </Link>
        <div className="vlx-head">
          <h1 className="vlx-title">Live</h1>
          <span className="vlx-state" data-on={following}>
            <i aria-hidden="true" />
            {following ? 'Following recorded turns' : 'Replaying a turn'} · long gaps compressed
          </span>
        </div>
        <p className="vlx-lede">
          Recorded steps in their real order; playback timing is adjusted for readability. Nothing
          here is simulated: a light is a step it took, and a cortex switched off stays dark.
        </p>
      </header>

      <div className="vlx-body">
        <section
          ref={stage}
          className="vlx-stage"
          aria-label="Viventium's brain, region by region"
          data-draw={flat ? 'flat' : (draw ?? '')}
          data-drawn={drawn && !flat}
          data-bloom={bloom}
          data-pointing={Boolean(hovered)}
          onPointerLeave={() => setHovered(null)}
          onPointerMove={(e) => {
            if (e.pointerType === 'touch') return; // (a finger has no hover: a tap left one behind, over the next tap)
            const id = under(e);
            if (id !== undefined) setHovered((had) => (had === id ? had : id));
          }}
          onClick={(e) => {
            const id = under(e);
            if (id !== undefined) pick(id ?? ''); // (nowhere near a region: what was open is put away)
          }}
        >
          {draw === '3d' && (
            <Scene
              key={round}
              regions={regions}
              wires={wires}
              live={live}
              labels={labels}
              version={version}
              hovered={hovered}
              picked={picked}
              still={still}
              bloom={bloom}
              onHealth={health}
            />
          )}
          {flat && (
            <div className="vlx-plain" data-over={draw === '3d'}>
              <Flat
                regions={regions}
                wires={wires}
                lit={flatLit}
                sparks={sparks}
                hovered={hovered}
                picked={picked}
                still={still}
              />
            </div>
          )}

          <div className="vlx-labels">
            {regions.map((r) => (
              <button
                type="button"
                key={r.id}
                ref={(el) => {
                  if (el) labels.current.set(r.id, el);
                  else labels.current.delete(r.id);
                }}
                className="vlx-label"
                data-core={CORE.some((c) => c.id === r.id)}
                data-runs={r.runs}
                data-focus={focus === r.id}
                aria-pressed={picked === r.id}
                style={{ ['--glow' as string]: r.runs ? r.color : 'transparent' }}
                onClick={(e) => {
                  e.stopPropagation();
                  pick(r.id);
                }}
                onFocus={() => setHovered(r.id)}
                onBlur={() => setHovered(null)}
              >
                <b style={{ color: r.runs ? undefined : 'var(--vlx-quiet)' }}>{r.name}</b>
                <small>{r.part}</small>
              </button>
            ))}
          </div>

          {shownTrace && (
            <div className="vlx-words" key={shownTrace.id}>
              <span className="vlx-who">
                {shownTrace.kind === 'unknown'
                  ? 'Turn unknown'
                  : shownTrace.kind === 'words'
                    ? 'You'
                    : 'What woke it'}
              </span>
              <p>{shownTrace.words}</p>
            </div>
          )}
          {shownTrace?.reply && spoke >= 0 && upto >= spoke && (
            <div className="vlx-reply" key={`${shownTrace.id}:reply`}>
              <span className="vlx-who">Viventium</span>
              <p>{shownTrace.reply}</p>
            </div>
          )}

          {flat && why && <p className="vlx-plain-note">{PLAIN[why]}</p>}
          {paused && draw === '3d' && <p className="vlx-plain-note">{PLAIN.lost}</p>}

          {region && (
            <aside className="vlx-card" aria-live="polite">
              <span
                className="vlx-dot"
                style={{ background: region.runs ? region.color : 'var(--vlx-quiet)' }}
              />
              <h2>{region.name}</h2>
              <span className="vlx-part">{region.part}</span>
              {!region.runs ? (
                <p className="vlx-none">
                  Switched off on the Subconscious page: it does not run, and is never lit here.
                </p>
              ) : latest ? (
                <>
                  <span className="vlx-cap">Last</span>
                  <p className="vlx-last">
                    {latest.what}
                    {latest.late && <em> · Late</em>}
                    {latest.took !== undefined && <em> · {took(latest.took)}</em>}
                    {latest.where && <em> · {latest.where}</em>}
                    <em> · {ago(now - latest.at)}</em>
                  </p>
                  <p className="vlx-part">{latest.words}</p>
                  {latest.full && <blockquote className="vlx-full">{latest.full}</blockquote>}
                  <span className="vlx-cap">
                    The last {past.length} {past.length === 1 ? 'time' : 'times'}
                    {timed.length > 1 && ` · median ${took(median(timed))}`}
                  </span>
                  <div className="vlx-strip" data-timed={timed.length > 0}>
                    {past.map((s, i) => (
                      <i
                        key={`${s.trace}:${i}`}
                        title={`${s.what}${s.late ? ' · Late' : ''}${s.took !== undefined ? ` · ${took(s.took)}` : ''} · ${s.words} · ${ago(now - s.at)}`}
                        data-state={s.state}
                        style={{
                          background: s.state === 'quiet' ? undefined : tint(s),
                          height:
                            timed.length && s.took !== undefined
                              ? `${4 + 24 * Math.min(1, s.took / slowest)}px`
                              : undefined,
                        }}
                      />
                    ))}
                  </div>
                  <ol className="vlx-history">
                    {past
                      .slice(-5)
                      .reverse()
                      .map((s, i) => (
                        <li key={`${s.trace}:${i}`} data-state={s.state}>
                          <i style={{ background: s.state === 'quiet' ? undefined : tint(s) }} />
                          <span>
                            {s.what}
                            <small>{s.words}</small>
                          </span>
                          <em>
                            {s.late && <b className="vlx-late">Late · </b>}
                            {s.took !== undefined ? `${took(s.took)} · ` : ''}
                            {ago(now - s.at)}
                          </em>
                        </li>
                      ))}
                  </ol>
                </>
              ) : (
                <p className="vlx-none">Nothing yet in the turns this page has.</p>
              )}
            </aside>
          )}

          <div className="vlx-legend" aria-hidden="true">
            <span>
              <i style={{ background: '#ffffff' }} />
              acted
            </span>
            <span>
              <i data-quiet="true" />
              quiet
            </span>
            <span>
              <i style={{ background: COLORS.warn }} />
              switched to a backup
            </span>
            <span>
              <i style={{ background: COLORS.error }} />
              failed
            </span>
          </div>
        </section>

        <section className="vlx-talk" aria-label="Turns">
          <div className="vlx-talk-head">
            <h2>Turns</h2>
            <div className="vlx-talk-do">
              {shownTrace && (
                <button
                  type="button"
                  className="vlx-again"
                  onClick={() => {
                    setFollowing(false);
                    replay(shownTrace);
                  }}
                >
                  <RotateCcw aria-hidden="true" />
                  Replay
                </button>
              )}
              {!following && (
                <button
                  type="button"
                  className="vlx-follow"
                  onClick={() => {
                    played.current = null;
                    setFollowing(true);
                  }}
                >
                  Follow live
                </button>
              )}
            </div>
          </div>
          {failed && !traces && (
            <p className="vlx-none">It could not be read. Is Viventium running?</p>
          )}
          {traces && !traces.length && (
            <p className="vlx-none">
              No turns yet. Talk to Viventium on a call, in Chat or on Telegram, and each turn shows
              here from its record.
            </p>
          )}
          <ol className="vlx-turns">
            {[...(traces ?? [])].reverse().map((trace) => {
              const on = trace.id === showing?.id;
              return (
                <li key={trace.id} data-on={on}>
                  <button
                    type="button"
                    className="vlx-turn"
                    onClick={() => {
                      setFollowing(false);
                      replay(trace);
                    }}
                  >
                    <span className="vlx-turn-head">
                      <Channel trace={trace} />
                      <span>{ago(now - trace.start)}</span>
                      {trace.kind === 'unknown' && <span>Turn unknown</span>}
                    </span>
                    <span className="vlx-turn-words">{trace.words}</span>
                    {trace.reply && <span className="vlx-turn-reply">{trace.reply}</span>}
                  </button>
                  {on && (
                    <ol className="vlx-steps">
                      {trace.steps.map((step, i) => (
                        <li
                          key={i}
                          data-done={i <= upto}
                          data-now={i === upto}
                          data-late={Boolean(step.late)}
                        >
                          <i style={{ background: tint(step) }} data-state={step.state} />
                          <span className="vlx-step-where">
                            {byId.get(step.region)?.name ?? step.region}
                          </span>
                          <span
                            className="vlx-step-what"
                            data-detail={Boolean(step.detail)}
                            title={step.full ?? step.what}
                          >
                            {step.detail ?? step.what}
                          </span>
                          <span className="vlx-step-when">
                            {step.late && <b className="vlx-late">Late · </b>}+
                            {(step.at - trace.start).toFixed(1)} s
                            {step.took !== undefined && <small>took {took(step.took)}</small>}
                          </span>
                        </li>
                      ))}
                    </ol>
                  )}
                </li>
              );
            })}
          </ol>
        </section>
      </div>
    </div>
  );
}
