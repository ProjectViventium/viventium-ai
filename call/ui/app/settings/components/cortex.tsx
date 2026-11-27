'use client';

import { ChevronRight, Link2, Link2Off, Trash2 } from 'lucide-react';
import type { Option, Settings } from '../lib/api';
import type { Cortex, LastRun, Place } from '../lib/kept';
import { Expand, Switch } from './glass';
import { Prompt, Sign, Thinking, Who, allWorkers, onThisMac } from './mind';

// One cortex: its name, when it runs, a line down to what it does, who runs it and how hard it thinks.
// If this, then that: When on top, Then under it. An empty "When" means every turn, and the line says so.
// In the collapsed overview,
// it is one row: what it is, where it runs, what it did last, its link and its switch; it opens in place.

export const ago = (at: number) => {
  const s = Math.max(0, Date.now() / 1000 - at);
  return s < 60
    ? 'just now'
    : s < 3600
      ? `${Math.round(s / 60)} min ago`
      : s < 86400
        ? `${Math.round(s / 3600)} h ago`
        : `${Math.round(s / 86400)} d ago`;
};

// What a part did last, in a few plain words (brain/rounds.py keeps it; nothing here is made up).
export function lastWords(last: LastRun | null | undefined, on: boolean): string {
  if (!last) return on ? 'Not run yet' : 'Off';
  const what =
    last.state === 'thought'
      ? 'had a thought'
      : last.state === 'feelings'
        ? 'Feelings reacted'
        : last.state === 'failed'
          ? `could not run${last.how ? ` (${last.how.replace(/_/g, ' ')})` : ''}`
          : last.picked
            ? last.picked.length
              ? `picked ${last.picked.length}`
              : 'picked none'
            : 'nothing to add';
  return `Last: ${what}, ${ago(last.at)}`;
}

// Where a part runs now, as it really runs on this profile (brain/rounds.place), never only what was chosen: its name
// and the effort it thinks at. Until a place says its effort, the card's own is shown.
export function runsNow(
  place: Place | undefined,
  effort: string,
  names: Record<string, string>
): string {
  if (!place?.name) return '';
  const level = place.effort ?? effort;
  const name = place.name[0].toUpperCase() + place.name.slice(1);
  return [name, level && level !== 'none' && names[level]].filter(Boolean).join(' · ');
}

export function CortexCard({
  cortex,
  settings,
  helpers,
  macEfforts,
  open,
  onToggle,
  change,
  remove,
}: {
  cortex: Cortex;
  settings: Settings;
  helpers?: Option; // her quick helpers, as a choice (they follow the profile)
  macEfforts?: string[]; // this Mac's levels, for a cortex asked there directly
  open: boolean;
  onToggle: () => void;
  change: (fields: Partial<Cortex>) => Promise<unknown>;
  remove: () => void;
}) {
  const always = !cortex.when.trim();
  const options = [...(helpers ? [helpers] : []), ...allWorkers(settings)];
  const option = onThisMac(
    options.find((o) => o.id === cortex.runs_on),
    macEfforts
  );
  const called = cortex.name || 'this cortex';
  const effort = option?.efforts?.includes(cortex.effort) ? cortex.effort : (option?.effort ?? '');
  // What runs now, and why it differs from the choice (on Local everything thinks on this Mac, whatever a card chose):
  // said where the choice is.
  const now = runsNow(cortex.place, effort, settings.effort_names);
  const here = cortex.place?.kind === 'mac' && option && option.where !== 'mac';
  const why = cortex.place?.note || (here ? 'On Local it thinks on this Mac.' : '');
  const runs = [
    option
      ? option.where === 'mac'
        ? `${option.model} · this Mac`
        : option.model
      : cortex.runs_on,
    effort && effort !== 'none' && settings.effort_names[effort], // (thinking off: nothing to say)
  ]
    .filter(Boolean)
    .join(' · ');
  return (
    <article className="vsx-card" data-on={cortex.on} data-id={cortex.id} data-open={open}>
      <div className="vsx-card-head">
        <Sign name={cortex.sign} />
        <span className="vsx-id">
          <span className="vs-h3">
            {cortex.system ? (
              <span>{cortex.name}</span>
            ) : (
              <input
                className="vsx-name"
                defaultValue={cortex.name}
                placeholder="Name it"
                aria-label="Name"
                maxLength={60}
                onBlur={(e) => e.target.value !== cortex.name && change({ name: e.target.value })}
              />
            )}
            {cortex.region && <span className="vs-region">{cortex.region}</span>}
          </span>
          {cortex.does && <span className="vsx-does">{cortex.does}</span>}
          {!open && (
            <span className="vsx-glance" data-glance={cortex.id}>
              <span>{always ? 'Every turn' : 'When the coordinator picks it'}</span>
              <span title={why || undefined}>{now ? `Runs now: ${now}` : runs}</span>
              <span data-last={cortex.last?.state ?? 'none'}>
                {lastWords(cortex.last, cortex.on)}
              </span>
            </span>
          )}
        </span>
        <span className="vsx-tools">
          {cortex.hands_back === 'feelings' ? (
            open && <span className="vsx-quiet">Changes Feelings; hands back no thought</span>
          ) : (
            <button
              type="button"
              className="vsx-icon"
              aria-pressed={cortex.linked}
              aria-label={
                cortex.linked ? `${called}: waits for the others` : `${called}: on its own`
              }
              onClick={() => change({ linked: !cortex.linked })}
            >
              {cortex.linked ? <Link2 /> : <Link2Off />}
              <span className="vs-tip" role="tooltip">
                {cortex.linked ? (
                  <>
                    <b>Waits for the others.</b> Its thought reaches the conscious mind together
                    with the rest, once every linked one is done.
                  </>
                ) : (
                  <>
                    <b>On its own.</b> Its thought reaches the conscious mind as soon as it is done.
                  </>
                )}
              </span>
            </button>
          )}
          {!cortex.system && (
            <button
              type="button"
              className="vsx-icon"
              aria-label={`Remove ${called}`}
              onClick={remove}
            >
              <Trash2 />
            </button>
          )}
          <Switch label={called} on={cortex.on} onChange={(on) => change({ on })} />
          <button
            type="button"
            className="vsx-icon vsx-chev"
            aria-expanded={open}
            aria-label={open ? `Close ${called}` : `Open ${called}`}
            onClick={onToggle}
          >
            <ChevronRight />
          </button>
        </span>
      </div>
      <Expand open={open}>
        <div className="vsx-body">
          <div className="vsx-flow">
            <div className="vsx-box">
              <span className="vsx-box-name">
                When
                <em>
                  {always ? 'empty: it runs on every turn' : 'the coordinator decides, from this'}
                </em>
              </span>
              <Prompt
                label={`When ${called} runs`}
                field="when"
                whole
                value={cortex.when}
                placeholder="Leave empty to run on every turn, without asking the coordinator."
                onSave={(when) => change({ when })}
              />
            </div>
            <div className="vsx-wire" data-always={always} aria-hidden="true">
              <span>{always ? 'every turn' : 'if so'}</span>
              <i />
              <span>then</span>
            </div>
            <div className="vsx-box">
              <span className="vsx-box-name">
                Then<em>what this cortex is told to do</em>
              </span>
              <Prompt
                label={`What ${called} does`}
                field="then"
                whole
                value={cortex.then}
                placeholder="What should it think about, and what should it hand back?"
                onSave={(then) => change({ then })}
              />
            </div>
          </div>
          <div className="vsx-run">
            <Who
              name={called}
              value={cortex.runs_on}
              options={options}
              aside={
                now && (why || now !== runs)
                  ? `Runs now: ${now}${why ? `. ${why}` : ''}`
                  : undefined
              }
              onChange={(runs_on) => change({ runs_on })}
            />
            <Thinking
              name={called}
              option={option}
              value={cortex.effort}
              names={settings.effort_names}
              onChange={(effort) => change({ effort })}
            />
            <span className="vsx-set">
              <span className="vsx-lab">Last</span>
              <span className="vsx-plain" data-last={cortex.last?.state ?? 'none'}>
                {lastWords(cortex.last, cortex.on).replace(/^Last: /, '')}
                {cortex.last?.words ? `: “${cortex.last.words}”` : ''}
              </span>
            </span>
          </div>
        </div>
      </Expand>
    </article>
  );
}
