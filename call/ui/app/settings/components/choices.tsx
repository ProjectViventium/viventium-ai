'use client';

import { Clapperboard, Image as ImageIcon } from 'lucide-react';
import type { Change, Option, Settings, Where } from '../lib/api';
import { Check, Disc, GroupHead, Play, Segmented, useChoiceKeys } from './glass';
import { Install } from './install';

// What every table of choices on the page shares: groups named once (pay as you go, your subscription, this
// Mac), one option's plain facts, its thinking effort, and where to go when it still needs a key or a sign-in.

export type Save = (change: Change, now?: (s: Settings) => Settings) => Promise<boolean>;

export const ORDER: Where[] = ['key', 'plan', 'mac']; // online first, this Mac last, the same in every table

export function Effort({
  option,
  value,
  names,
  onChange,
}: {
  option: Option;
  value: string;
  names: Record<string, string>;
  onChange: (level: string) => void;
}) {
  if (!option.efforts?.length) return null;
  return (
    <span className="vs-effort">
      <span className="vs-effort-name">Thinking effort</span>
      <Segmented
        label={`Thinking effort for ${option.model}`}
        size="sm"
        value={value}
        options={option.efforts.map((id) => ({ id, name: names[id] ?? id }))}
        onChange={onChange}
      />
    </span>
  );
}

// "Speed and smarts": two plain words in colour, with the time measured here when there is one.
const TONE = {
  fast: 'good',
  ok: 'mid',
  slow: 'low',
  smart: 'good',
  balanced: 'mid',
  simple: 'low',
} as const;
export function Bench({ option, settings }: { option: Option; settings: Settings }) {
  return (
    <span className="vs-tags">
      {option.pick && (
        <span className="vs-tag" data-tone="pick">
          Recommended
        </span>
      )}
      {option.speed && (
        <span className="vs-tag" data-tone={TONE[option.speed]}>
          {settings.speed[option.speed]}
          {option.timed ? ` · ${option.timed}` : ''}
        </span>
      )}
      {option.smart && (
        <span className="vs-tag" data-tone={TONE[option.smart]}>
          {settings.smart[option.smart]}
        </span>
      )}
      {option.decides !== undefined && (
        <span
          className="vs-tag"
          data-tone={option.decides ? 'good' : 'mid'}
          title={
            option.decides
              ? 'It decides itself when work goes to a Worker.'
              : 'A quick check beside it decides when work goes to a Worker.'
          }
        >
          {option.decides ? 'Decides itself' : 'With a quick check'}
        </span>
      )}
      {!option.tried && <span className="vs-tag">Not tried here yet</span>}
    </span>
  );
}

// A choice that cannot run yet says so in two words and points at the one place accounts are kept (System).
export function goToAccount(id?: string) {
  const el = document.getElementById(id ? `account-${id}` : 'accounts');
  if (!el) {
    window.location.assign(`/settings#${id ? `account-${id}` : 'accounts'}`);
    return;
  }
  el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  el.setAttribute('data-called', 'true');
  window.setTimeout(() => el.removeAttribute('data-called'), 2400);
}
export function Missing({ option }: { option: Option }) {
  if (!option.needs) return null;
  if (option.needs === 'model') return <Install item={option.install} />; // one click gets it
  return (
    <button
      type="button"
      className="vs-missing"
      data-link="true"
      onClick={(e) => {
        e.stopPropagation();
        goToAccount(option.account);
      }}
    >
      {option.needs.startsWith('key') ? 'Needs your key' : 'Needs your login'}
    </button>
  );
}

const DRAWN_MARK: Record<string, React.ComponentType<{ strokeWidth?: number }>> = {
  image: ImageIcon,
  film: Clapperboard,
};
export function Mark({ mark, size }: { mark: string; size?: 'lg' | 'sm' }) {
  const Drawn = DRAWN_MARK[mark];
  if (!Drawn) return <Disc mark={mark} size={size} />;
  return (
    <span className="vs-disc" data-size={size} aria-hidden="true">
      <Drawn strokeWidth={1.7} />
    </span>
  );
}

// One option where only one may be chosen (ears, voice, photos, videos): what it is, in a few plain words; hear
// it; tick it. The whole tile is the control.
export function OptionTile({
  option,
  on,
  bench,
  settings,
  onChoose,
}: {
  option: Option;
  on: boolean;
  bench?: boolean;
  settings: Settings;
  onChoose: () => void;
}) {
  const ready = !option.needs;
  return (
    <div
      className="vs-opt"
      data-on={on}
      data-ready={ready}
      onClick={() => ready && !on && onChoose()}
    >
      <Mark mark={option.mark} />
      <span className="vs-opt-main">
        <span className="vs-opt-name">
          <span className="vs-name">{option.title ?? `${option.provider} ${option.model}`}</span>
          {option.title && <span className="vs-sub">{option.detail}</span>}
        </span>
        {bench ? (
          <Bench option={option} settings={settings} />
        ) : (
          <span className="vs-plain">
            {[
              ...(option.words ?? []),
              // (its key missing while it is chosen: its backup speaks, said only then)
              ...(on && option.backup_name
                ? [
                    option.needs
                      ? `Answering now: ${option.backup_name}`
                      : `Backup: ${option.backup_name}`,
                  ]
                : []),
            ].join(' · ')}
          </span>
        )}
      </span>
      <span className="vs-opt-side">
        {option.sample && <Play sample={option.sample} name={option.title ?? option.model} />}
        {ready ? (
          <Check
            role="radio"
            on={on}
            label={`${option.provider} ${option.model}`}
            onChange={() => !on && onChoose()}
          />
        ) : (
          <Missing option={option} />
        )}
      </span>
    </div>
  );
}

// Two lists side by side, each its own column (Listening and Talking; Photos and Videos), cut down the middle by one
// thin line. Each column has its own groups and rows.
export function Pair({
  left,
  right,
  settings,
  bench,
}: {
  left: Column;
  right: Column;
  settings: Settings;
  bench?: boolean;
}) {
  const shown = new Set(left.options.map((o) => o.where)); // (a group's facts are said once: in the left column)
  const keys = { left: useChoiceKeys<HTMLDivElement>(), right: useChoiceKeys<HTMLDivElement>() };
  const column = (c: Column, side: 'left' | 'right') => (
    <div
      className="vs-pair-col"
      role="radiogroup"
      aria-label={c.name}
      ref={keys[side].ref}
      onKeyDown={keys[side].onKeyDown}
    >
      <div className="vs-col-head">
        <span className="vs-h3">{c.name}</span>
        <span className="vs-hint">{c.hint}</span>
      </div>
      {ORDER.filter((where) => c.options.some((o) => o.where === where)).map((where) => (
        <div key={where} className="vs-grp">
          <GroupHead
            where={where}
            place={settings.where[where]}
            said={side === 'right' && shown.has(where)}
          />
          <div className="vs-pair-cell">
            {c.options
              .filter((o) => o.where === where)
              .map((option) => (
                <OptionTile
                  key={option.id}
                  option={option}
                  on={option.id === c.chosen}
                  bench={bench}
                  settings={settings}
                  onChoose={() => c.choose(option)}
                />
              ))}
          </div>
        </div>
      ))}
    </div>
  );
  return (
    <div className="vs-pair">
      {column(left, 'left')}
      <span className="vs-pair-split" aria-hidden="true" />
      {column(right, 'right')}
    </div>
  );
}
export type Column = {
  name: string;
  hint: string;
  options: Option[];
  chosen: string;
  choose: (option: Option) => void;
};
