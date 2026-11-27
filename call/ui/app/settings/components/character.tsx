'use client';

import { useEffect, useId, useRef, useState } from 'react';
import {
  Anchor,
  ChevronDown,
  Feather,
  Flame,
  Flower2,
  Heart,
  Moon,
  PartyPopper,
  Scale,
  SlidersHorizontal,
  Sun,
  Telescope,
} from 'lucide-react';
import { motion } from 'motion/react';
import type { Band, Nature, Settings } from '../lib/api';
import type { Save } from './choices';
import { Expand, Pane, Segmented, Switch, Words, useChoiceKeys } from './glass';
import { Install } from './install';

// Character: a personality (where the nine feelings rest), and the feelings themselves. Each feeling is a tube of
// light: how full it is, is the feeling now (it moves by itself as you talk); the dashed line is where it rests,
// and you set that by dragging it. Its trail shows where it has been and how fast it is coming back. Side by
// side on a wide screen, rows on a phone. "Fine-tune" opens every level's words and the exact numbers.

// -- A personality's sign: a small drawing, never an emoji --
function Clown() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="13.6" r="7.4" />
      <circle cx="4.5" cy="9.6" r="2" />
      <circle cx="19.500" cy="9.6" r="2" />
      <path d="M9.4 6.600 12 2.400l2.600 4.200" />
      <circle cx="12" cy="14" r="1.500" fill="currentColor" />
      <path d="M9.300 11.300h.01M14.700 11.300h.01" strokeWidth="2.600" />
      <path d="M8.500 16.200c.9 1.700 2.100 2.500 3.500 2.500s2.600-.8 3.500-2.500" />
    </svg>
  );
}
const SIGN: Record<string, React.ComponentType<{ strokeWidth?: number }>> = {
  anchor: Anchor,
  sun: Sun,
  telescope: Telescope,
  scale: Scale,
  clown: Clown,
  feather: Feather,
  heart: Heart,
  flame: Flame,
  party: PartyPopper,
  moon: Moon,
  lotus: Flower2,
  own: SlidersHorizontal,
};

function Preset({
  nature,
  on,
  colors,
  onChoose,
}: {
  nature: Nature;
  on: boolean;
  colors: string[];
  onChoose: () => void;
}) {
  const Sign = SIGN[nature.sign] ?? Anchor;
  return (
    <motion.button
      type="button"
      role="radio"
      aria-checked={on}
      className="vs-preset"
      data-on={on}
      whileTap={{ scale: 0.95 }}
      onClick={() => !on && onChoose()}
    >
      <span className="vs-preset-sign">
        <Sign strokeWidth={1.7} />
      </span>
      <span className="vs-name">{nature.name}</span>
      {/* its shape: where each of the nine feelings rests */}
      <span className="vs-preset-shape" aria-hidden="true">
        {nature.rests.map((rest, n) => (
          <i key={n} style={{ height: `${Math.max(8, rest)}%`, background: colors[n] }} />
        ))}
      </span>
    </motion.button>
  );
}

// -- The trail: where a feeling has been over the last hours, true to time (a jump when something moved it,
// then the slow curve back toward where it rests) --
const HOURS = 6;
function trailPath(band: Band, hours = HOURS) {
  const now = Date.now();
  const start = now - hours * 3600e3;
  const events = band.trail
    .map((e) => ({ t: Date.parse(e.t), from: e.from, to: e.to }))
    .filter((e) => !Number.isNaN(e.t))
    .sort((a, b) => a.t - b.t);
  const at = (t: number) => {
    let last = null;
    for (const e of events) {
      if (e.t <= t) last = e;
      else break;
    }
    if (!last) return events.length ? events[0].from : band.now;
    return (
      band.rest + (last.to - band.rest) * 2 ** (-(t - last.t) / 60000 / Math.max(1, band.pace))
    );
  };
  const times = new Set<number>();
  for (let i = 0; i <= 60; i += 1) times.add(start + ((now - start) * i) / 60);
  for (const e of events) if (e.t > start && e.t < now) [e.t - 1, e.t].forEach((t) => times.add(t));
  const points = [...times]
    .sort((a, b) => a - b)
    .map((t) => [((t - start) / (now - start)) * 100, 100 - at(t)] as const);
  points[points.length - 1] = [100, 100 - band.now];
  const moved = events.some((e) => e.t > start) || Math.abs(band.now - band.rest) >= 1;
  return {
    d: points.map(([x, y], n) => `${n ? 'L' : 'M'}${x.toFixed(2)} ${y.toFixed(2)}`).join(' '),
    moved,
  };
}

function Trail({ band, tall }: { band: Band; tall?: boolean }) {
  const id = useId();
  const { d, moved } = trailPath(band);
  return (
    <svg
      className="vs-trail"
      data-tall={tall}
      data-moved={moved}
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={id} gradientUnits="userSpaceOnUse" x1="0" x2="100" y1="0" y2="0">
          <stop offset="0" stopColor="var(--c)" stopOpacity="0.05" />
          <stop offset="1" stopColor="var(--c)" stopOpacity="1" />
        </linearGradient>
      </defs>
      <line
        x1="0"
        x2="100"
        y1={100 - band.rest}
        y2={100 - band.rest}
        className="vs-trail-rest"
        vectorEffect="non-scaling-stroke"
      />
      <path d={d} stroke={`url(#${id})`} fill="none" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

// How long the drift back takes, as a speed for the little current inside the tube (fast feelings flow fast).
const flow = (pace: number) => `${(0.9 + Math.log10(Math.max(10, pace) / 10) * 2.6).toFixed(2)}s`;

function patch(
  save: Save,
  band: Band,
  change: Partial<Band>,
  send: Record<string, number | boolean>
) {
  return save({ band: { id: band.id, ...send } }, (s) => ({
    ...s,
    character: {
      ...s.character,
      ...('rest' in send ? { nature: 'custom' } : {}),
      bands: s.character.bands.map((b) => (b.id === band.id ? { ...b, ...change } : b)),
    },
  }));
}

function BandTube({ band, save, alive }: { band: Band; save: Save; alive: boolean }) {
  const tube = useRef<HTMLDivElement>(null);
  const [held, setHeld] = useState<number | null>(null);
  const rest = held ?? band.rest;
  const on = band.on && alive;
  const read = (e: React.PointerEvent) => {
    const box = tube.current!.getBoundingClientRect();
    const share =
      box.height > box.width
        ? 1 - (e.clientY - box.top) / box.height
        : (e.clientX - box.left) / box.width;
    return Math.round(Math.min(1, Math.max(0, share)) * 100);
  };
  const keys = (e: React.KeyboardEvent) => {
    const step =
      (e.shiftKey ? 5 : 1) *
      ({ ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1 }[e.key] ?? 0);
    if (!step) return;
    e.preventDefault();
    const value = Math.min(100, Math.max(0, band.rest + step));
    patch(save, band, { rest: value }, { rest: value });
  };
  const drift = Math.abs(band.now - rest) < 1 ? 'none' : band.now > rest ? 'down' : 'up';
  return (
    <div
      className="vs-band"
      data-on={on}
      style={
        {
          '--c': band.color,
          '--now': band.now,
          '--rest': rest,
          '--flow': flow(band.pace),
        } as React.CSSProperties
      }
    >
      <button
        type="button"
        className="vs-band-top"
        aria-pressed={band.on}
        aria-label={`${band.name}: ${band.on ? 'on' : 'off'}`}
        title={band.on ? 'Switch this feeling off' : 'Switch this feeling on'}
        onClick={() => patch(save, band, { on: !band.on }, { on: !band.on })}
      >
        <span className="vs-band-light" />
        <span>{band.name}</span>
      </button>
      <span className="vs-pole" data-end="high">
        {band.high}
      </span>
      <div
        ref={tube}
        className="vs-tube"
        onPointerDown={(e) => {
          if (!on) return;
          e.currentTarget.setPointerCapture(e.pointerId);
          setHeld(read(e));
        }}
        onPointerMove={(e) => held !== null && setHeld(read(e))}
        onPointerUp={() => {
          if (held === null) return;
          const value = held;
          setHeld(null);
          if (value !== band.rest) patch(save, band, { rest: value }, { rest: value });
        }}
        onPointerCancel={() => setHeld(null)}
      >
        <span className="vs-fill" />
        {/* the stretch still to travel back to where it rests, with a current flowing that way */}
        <span className="vs-wake" data-drift={drift} />
        <span
          className="vs-rest"
          role="slider"
          tabIndex={on ? 0 : -1}
          aria-label={`Where ${band.name} rests`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={rest}
          aria-valuetext={`${rest}, now ${band.now}`}
          data-held={held !== null}
          onKeyDown={keys}
        />
      </div>
      <span className="vs-pole" data-end="low">
        {band.low}
      </span>
      <Trail band={band} />
      <span className="vs-band-num">
        <b>{band.word}</b>
        <span>
          {band.now} · rests {rest}
        </span>
      </span>
    </div>
  );
}

// -- Fine-tune: one feeling's five levels, what each says, your own words for it, and the exact numbers --
const PACES = [
  { id: '10', name: '10 min' },
  { id: '20', name: '20 min' },
  { id: '45', name: '45 min' },
  { id: '90', name: '1.5 h' },
  { id: '240', name: '4 h' },
  { id: '480', name: '8 h' },
  { id: '1440', name: '24 h' },
];
const LEAST = 5; // points each level keeps, so every level can still be reached (settings/service.py: LEAST)
// Where each of the five levels begins and ends, from the four thresholds (lowest level first).
const ranges = (bounds: number[]) =>
  [0, ...bounds].map((from, n) => [from, n < bounds.length ? bounds[n] - 1 : 100] as const);
const levelOf = (value: number, bounds: number[]) => bounds.filter((b) => value >= b).length;

// Where a feeling's levels begin: one slim scale, a handle at each threshold (drag it, or focus it and use the arrow
// keys; Shift moves five). A level keeps at least five points. It saves when you let go, at once.
function Thresholds({ band, save }: { band: Band; save: Save }) {
  const bar = useRef<HTMLDivElement>(null);
  const [held, setHeld] = useState<{ i: number; at: number } | null>(null);
  const at = band.bounds.map((b, i) => (held?.i === i ? held.at : b));
  const room = (i: number) =>
    [(i ? at[i - 1] : 0) + LEAST, (i < 3 ? at[i + 1] : 101) - LEAST] as const;
  const place = (i: number, value: number) => {
    const [low, high] = room(i);
    return Math.min(high, Math.max(low, Math.round(value)));
  };
  const keep = (next: number[]) =>
    save({ bounds: { band: band.id, at: next } }, (s) => ({
      ...s,
      character: {
        ...s.character,
        bands: s.character.bands.map((b) => (b.id === band.id ? { ...b, bounds: next } : b)),
      },
    }));
  const read = (e: React.PointerEvent) => {
    const box = bar.current!.getBoundingClientRect();
    return (1 - (e.clientY - box.top) / box.height) * 100;
  };
  const parts = ranges(at);
  const now = levelOf(band.now, at);
  return (
    <div
      className="vs-scale"
      ref={bar}
      aria-label={`Where each level of ${band.name} begins`}
      role="group"
    >
      {parts.map(([from, to], n) => (
        <span
          key={n}
          className="vs-scale-part"
          data-now={n === now}
          style={{ bottom: `${from}%`, height: `${to + (n === 4 ? 0 : 1) - from}%` }}
        />
      ))}
      {at.map((b, i) => (
        <span
          key={i}
          className="vs-scale-handle"
          role="slider"
          tabIndex={0}
          data-held={held?.i === i}
          style={{ bottom: `${b}%` }}
          aria-label={`Where ${band.name} becomes ${band.levels[i + 1].word}`}
          aria-valuemin={room(i)[0]}
          aria-valuemax={room(i)[1]}
          aria-valuenow={b}
          aria-valuetext={`from ${b}`}
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId);
            setHeld({ i, at: place(i, read(e)) });
          }}
          onPointerMove={(e) => held?.i === i && setHeld({ i, at: place(i, read(e)) })}
          onPointerUp={() => {
            if (held?.i !== i) return;
            const next = at.map((x, j) => (j === i ? held.at : x));
            setHeld(null);
            if (next[i] !== band.bounds[i]) keep(next);
          }}
          onPointerCancel={() => setHeld(null)}
          onKeyDown={(e) => {
            const step =
              (e.shiftKey ? 5 : 1) *
              ({ ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1 }[e.key] ?? 0);
            if (!step) return;
            e.preventDefault();
            const value = place(i, b + step);
            if (value !== b) keep(at.map((x, j) => (j === i ? value : x)));
          }}
        />
      ))}
    </div>
  );
}

// What a level says, in your words in place of main Viventium's: written in place, kept as you type; one click puts
// main's back.
function Says({ band, n, save }: { band: Band; n: number; save: Save }) {
  const level = band.levels[n];
  const changed = level.text !== level.original;
  const put = (text: string) =>
    save({ says: { band: band.id, level: n, text } }, (s) => ({
      ...s,
      character: {
        ...s.character,
        bands: s.character.bands.map((b) =>
          b.id !== band.id
            ? b
            : {
                ...b,
                levels: b.levels.map((l, j) => (j === n ? { ...l, text: text || l.original } : l)),
              }
        ),
      },
    }));
  return (
    <span className="vs-rung-says" data-changed={changed}>
      <Words
        rows={2}
        max={1200}
        label={`What ${band.name} says when ${level.word}`}
        value={level.text}
        onSave={(text) => put(text.trim() === level.original ? '' : text)}
      />
      {changed && (
        <button type="button" className="vs-quiet-btn" onClick={() => put('')}>
          Back to the original
        </button>
      )}
    </span>
  );
}

function Exact({
  label,
  value,
  onSave,
}: {
  label: string;
  value: number;
  onSave: (n: number) => void;
}) {
  const [text, setText] = useState(String(value));
  const editing = useRef(false);
  useEffect(() => {
    if (!editing.current) setText(String(value));
  }, [value]);
  const keep = () => {
    editing.current = false;
    const n = Math.round(Number(text));
    if (Number.isFinite(n) && n >= 0 && n <= 100 && n !== value) onSave(n);
    else setText(String(value));
  };
  return (
    <label className="vs-num">
      <span>{label}</span>
      <input
        inputMode="numeric"
        value={text}
        aria-label={label}
        onFocus={() => (editing.current = true)}
        onChange={(e) => setText(e.target.value.replace(/[^0-9]/g, '').slice(0, 3))}
        onBlur={keep}
        onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
      />
    </label>
  );
}

function Editor({ band, save, tune }: { band: Band; save: Save; tune: boolean }) {
  const level = levelOf(band.now, band.bounds);
  const restLevel = levelOf(band.rest, band.bounds);
  const spans = ranges(band.bounds);
  return (
    <div className="vs-editor" style={{ '--c': band.color } as React.CSSProperties}>
      <div className="vs-editor-head">
        <span className="vs-band-light" />
        <b className="vs-h3">{band.name}</b>
        <span className="vs-sub">{band.word}</span>
      </div>
      <div className="vs-editor-set">
        <Exact
          label="Now"
          value={band.now}
          onSave={(n) => patch(save, band, { now: n }, { now: n })}
        />
        <Exact
          label="Rests at"
          value={band.rest}
          onSave={(n) => patch(save, band, { rest: n }, { rest: n })}
        />
        <span className="vs-num" data-wide="true">
          <span>Comes halfway back in</span>
          <Segmented
            label={`How fast ${band.name} comes back`}
            size="sm"
            value={PACES.some((p) => p.id === String(band.pace)) ? String(band.pace) : ''}
            options={PACES}
            onChange={(id) => patch(save, band, { pace: +id }, { pace: +id })}
          />
        </span>
      </div>
      <div className="vs-editor-trail">
        <Trail band={band} tall />
        <span className="vs-hint">{HOURS} hours ago</span>
        <span className="vs-hint">now</span>
      </div>
      <div className="vs-ladder-wrap" data-tune={tune}>
        {tune && <Thresholds band={band} save={save} />}
        <ol className="vs-ladder" reversed>
          {[4, 3, 2, 1, 0].map((n) => (
            <li key={n} data-now={n === level} data-rest={n === restLevel}>
              <span className="vs-rung">
                <span className="vs-rung-range">
                  {spans[n][0]}–{spans[n][1]}
                </span>
                <b>{band.levels[n].word}</b>
                {n === level && <i>now</i>}
                {n === restLevel && n !== level && <i data-quiet="true">rests</i>}
              </span>
              {tune ? (
                <Says band={band} n={n} save={save} />
              ) : (
                <span className="vs-rung-says">{band.levels[n].text}</span>
              )}
              <Words
                rows={1}
                label={`Your own words for ${band.name} when ${band.levels[n].word}`}
                placeholder="Add your own words"
                value={band.levels[n].yours}
                onSave={(text) => save({ words: { band: band.id, level: n, text } })}
              />
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

function ago(iso: string) {
  const minutes = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000));
  if (!Number.isFinite(minutes)) return '';
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} d ago`;
}

export function Character({ settings, save }: { settings: Settings; save: Save }) {
  const c = settings.character;
  const [fine, setFine] = useState(false);
  const [all, setAll] = useState(false);
  const [picked, setPicked] = useState('');
  const presetKeys = useChoiceKeys<HTMLDivElement>();
  const chipKeys = useChoiceKeys<HTMLDivElement>();
  const colors = c.bands.map((b) => b.color);
  const one = c.bands.find((b) => b.id === picked) ?? c.bands[0];
  const own: Nature = {
    id: 'custom',
    name: 'Your own',
    sign: 'own',
    rests: c.bands.map((b) => b.rest),
  };
  return (
    <Pane
      title="Character"
      aside={
        <span className="vs-aside">
          <span className="vs-name">Feelings</span>
          <Switch
            label="Feelings"
            on={c.on}
            onChange={(on) =>
              save({ feelings: on }, (s) => ({ ...s, character: { ...s.character, on } }))
            }
          />
        </span>
      }
    >
      {c.on && c.bands.length > 0 && (
        <p className="vs-inner" data-empty={!c.inner}>
          {c.inner ? (
            <>
              <q>{c.inner.text}</q>
              <span className="vs-hint">In Viventium’s own words · {ago(c.inner.at)}</span>
            </>
          ) : (
            <span className="vs-hint">
              The next thing you say will put this state into Viventium’s own words.
            </span>
          )}
        </p>
      )}

      <div className="vs-col-head vs-part" style={{ marginBottom: 16 }}>
        <span className="vs-h3">Personality</span>
        <span className="vs-hint">
          {c.nature === 'custom'
            ? 'Your own: you moved where a feeling rests.'
            : (c.natures.find((n) => n.id === c.nature)?.line ?? 'Where every feeling rests.')}
        </span>
      </div>
      <div
        className="vs-presets"
        role="radiogroup"
        aria-label="Personality"
        ref={presetKeys.ref}
        onKeyDown={presetKeys.onKeyDown}
      >
        {c.natures.map((nature) => (
          <Preset
            key={nature.id}
            nature={nature}
            colors={colors}
            on={c.nature === nature.id}
            onChoose={() =>
              save({ nature: nature.id }, (s) => ({
                ...s,
                character: { ...s.character, nature: nature.id },
              }))
            }
          />
        ))}
        {c.nature === 'custom' && (
          <Preset nature={own} colors={colors} on onChoose={() => undefined} />
        )}
      </div>

      {c.bands.length > 0 && (
        <>
          <div className="vs-bands" role="group" aria-label="Feelings">
            {c.bands.map((band) => (
              <BandTube key={band.id} band={band} save={save} alive={c.on} />
            ))}
          </div>
          <button
            type="button"
            className="vs-more-btn"
            aria-expanded={fine}
            onClick={() => setFine(!fine)}
          >
            Fine-tune
            <ChevronDown />
          </button>
          <Expand open={fine}>
            <div className="vs-fine">
              <div className="vs-fine-top">
                <div
                  className="vs-chips"
                  role="radiogroup"
                  aria-label="Feeling to fine-tune"
                  data-dim={all}
                  ref={chipKeys.ref}
                  onKeyDown={chipKeys.onKeyDown}
                >
                  {c.bands.map((band) => (
                    <button
                      key={band.id}
                      type="button"
                      role="radio"
                      aria-checked={!all && band.id === one.id}
                      className="vs-chip"
                      style={{ '--c': band.color } as React.CSSProperties}
                      onClick={() => {
                        setAll(false);
                        setPicked(band.id);
                      }}
                    >
                      <span className="vs-band-light" />
                      {band.name}
                    </button>
                  ))}
                </div>
                <span className="vs-aside">
                  <span className="vs-sub">All feelings</span>
                  <Switch label="Show all feelings" on={all} onChange={setAll} />
                  <button
                    type="button"
                    className="vs-quiet-btn"
                    onClick={() => save({ reset_feelings: true })}
                  >
                    Back to rest
                  </button>
                </span>
              </div>
              <div className="vs-editors" data-all={all}>
                {(all ? c.bands : [one]).map((band) => (
                  <Editor key={band.id} band={band} save={save} tune={c.tune} />
                ))}
              </div>
            </div>
          </Expand>
        </>
      )}

      {/* How Viventium shows above the conversation. Soulface is an add-on, on this Mac only once switched on here (the
          requirement: someone who does not want it never downloads it): switching it on adds it, then shows it. One
          word on the page (few words); what it is, in its title. */}
      <div className="vs-foot">
        <span
          className="vs-kv"
          title="A living face that shows what Viventium feels and does. Adds about 1 MB."
        >
          <span className="vs-h3">Soulface</span>
        </span>
        {settings.presence.chosen === 'soulface' && settings.presence.soulface.install && (
          <Install item={settings.presence.soulface.install} />
        )}
        <Switch
          label="Soulface"
          on={settings.presence.chosen === 'soulface'}
          onChange={(on) => {
            const id = on ? 'soulface' : 'dots';
            save({ presence: id }, (s) => ({ ...s, presence: { ...s.presence, chosen: id } }));
          }}
        />
      </div>
    </Pane>
  );
}
