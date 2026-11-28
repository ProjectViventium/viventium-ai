'use client';

import { useState } from 'react';
import Link from 'next/link';
import {
  BookOpen,
  BrainCircuit,
  Brain as BrainIcon,
  ChevronRight,
  Clock,
  FileText,
  Gauge,
  Star,
} from 'lucide-react';
import type { Many, One, Option, Settings, Where } from '../lib/api';
import { Bench, Effort, Missing, ORDER, type Save } from './choices';
import { Check, Disc, Expand, GroupHead, Pane, Why, Words } from './glass';

// The brain: one table. Down the side, what it can run on, in three groups (pay as you go, your subscription,
// this Mac), each provider with its model. Across the top, the three parts: the one you talk to, the one that
// manages the work, the ones that do it. A tick where a row meets a column is the whole setting.

type Role = 'mind' | 'manager' | 'hands';
const ROLES: Role[] = ['mind', 'manager', 'hands'];
type Row = { where: Where; provider: string; model: string; mark: string } & Partial<
  Record<Role, Option>
>;

function rows(settings: Settings): Row[] {
  const out: Row[] = [];
  for (const role of ROLES)
    for (const option of settings.parts[role].options) {
      const same = out.find(
        (r) =>
          r.where === option.where && r.provider === option.provider && r.model === option.model
      );
      if (same) same[role] = option;
      else
        out.push({
          where: option.where,
          provider: option.provider,
          model: option.model,
          mark: option.mark,
          [role]: option,
        });
    }
  return out;
}

// Work on this Mac manages itself; the Worker manager manages the online work. So the manager is this Mac's only
// when every Worker is on this Mac, and the part you did not touch follows (settings/service.py does the same).
function together(settings: Settings, next: { manager?: One; hands?: Many }) {
  const local = (role: Role, id: string) =>
    settings.parts[role].options.find((o) => o.id === id)?.where === 'mac';
  const manager = next.manager ?? settings.choices.manager;
  const hands = next.hands ?? settings.choices.hands;
  if (local('manager', manager.id) === hands.use.every((id) => local('hands', id)))
    return { manager, hands };
  return next.manager
    ? { manager, hands: { use: [manager.id], effort: {} } }
    : { manager: { id: hands.use.find((id) => !local('hands', id)) ?? hands.use[0] }, hands };
}

function Cell({
  row,
  role,
  settings,
  save,
}: {
  row: Row;
  role: Role;
  settings: Settings;
  save: Save;
}) {
  const option = row[role];
  const { mind, manager, hands } = settings.choices;
  if (!option) {
    // An empty place says why when you point at it (a subscription cannot be the one you talk to).
    const why = settings.parts[role].absent?.[row.where];
    if (!why) return <div className="vs-cell" data-none="true" role="cell" />;
    return (
      <div className="vs-cell" data-none="true" role="cell">
        <Why text={why} />
      </div>
    );
  }
  // (the same model in two places of one part, e.g. Grok on a key and on your subscription: its place is in its name)
  const twin = settings.parts[role].options.some(
    (o) => o.id !== option.id && o.provider === option.provider && o.model === option.model
  );
  const name = `${option.provider} ${option.model} as ${settings.parts[role].name}${
    twin ? ` (${settings.where[row.where].name})` : ''
  }`;
  if (option.needs)
    return (
      <div className="vs-cell" role="cell">
        <Check
          role={role === 'hands' ? 'checkbox' : 'radio'}
          on={false}
          disabled
          label={`${name}: not ready`}
          onChange={() => undefined}
        />
      </div>
    );

  if (role === 'hands') {
    const on = hands.use.includes(option.id);
    const many = hands.use.length > 1;
    const first = hands.use[0] === option.id;
    const effort = hands.effort[option.id] ?? option.effort ?? '';
    const set = (next: Many) => {
      const both = together(settings, { hands: next });
      return save({ hands: next }, (s) => ({ ...s, choices: { ...s.choices, ...both } }));
    };
    // Any of them together: the Worker on this Mac beside online ones too (each job runs where its Worker lives).
    const toggle = () => {
      if (on) {
        if (many) set({ ...hands, use: hands.use.filter((id) => id !== option.id) }); // (never the last one)
      } else {
        set({
          use: [...hands.use, option.id],
          effort: effort ? { ...hands.effort, [option.id]: effort } : hands.effort,
        });
      }
    };
    return (
      <div className="vs-cell" data-on={on} role="cell">
        <span className="vs-cell-top">
          <Check on={on} label={name} onChange={toggle} />
          {on && many && (
            <button
              type="button"
              className="vs-star"
              aria-pressed={first}
              aria-label={`${option.provider} ${option.model} preferred`}
              title={first ? 'Preferred' : 'Make this one preferred'}
              onClick={() =>
                !first &&
                set({ ...hands, use: [option.id, ...hands.use.filter((id) => id !== option.id)] })
              }
            >
              <Star fill={first ? 'currentColor' : 'none'} />
              {first && <span>Preferred</span>}
            </button>
          )}
        </span>
        <Expand open={on && !!option.efforts?.length}>
          <Effort
            option={option}
            value={effort}
            names={settings.effort_names}
            onChange={(level) => set({ ...hands, effort: { ...hands.effort, [option.id]: level } })}
          />
        </Expand>
      </div>
    );
  }

  const chosen = role === 'mind' ? mind : manager;
  const on = chosen.id === option.id;
  const effort = on ? (chosen.effort ?? option.effort ?? '') : (option.effort ?? '');
  const set = (next: One) =>
    role === 'mind'
      ? save({ mind: next }, (s) => ({ ...s, choices: { ...s.choices, mind: next } }))
      : save({ manager: next }, (s) => ({
          ...s,
          choices: { ...s.choices, ...together(settings, { manager: next }) },
        }));
  return (
    <div className="vs-cell" data-on={on} role="cell">
      <span className="vs-cell-top">
        <Check
          role="radio"
          on={on}
          label={name}
          onChange={() => !on && set({ id: option.id, effort: option.effort })}
        />
      </span>
      <Expand open={on && !!option.efforts?.length}>
        <Effort
          option={option}
          value={effort}
          names={settings.effort_names}
          onChange={(level) => set({ id: option.id, effort: level })}
        />
      </Expand>
    </div>
  );
}

function Head({
  part,
  cell,
}: {
  part: { name: string; region: string; hint: string };
  cell?: boolean; // the header of a column, in the table
}) {
  return (
    <div className="vs-col-head" role={cell ? 'columnheader' : undefined}>
      <span className="vs-h3">{part.name}</span>
      <span className="vs-region">{part.region}</span>
      <span className="vs-hint">{part.hint}</span>
    </div>
  );
}

// Why the one you talk to is not answering, as its key was last found (core/accounts).
const AWAY: Record<string, string> = {
  key: 'needs your key (System).',
  limited: 'has reached its limit.',
  sign_in: 'needs its key again (System).',
  refused: 'is refused for this key: see what the key may do at its provider (System).',
  down: 'is not answering.',
};
// The same for a mind on your subscription (Viventium's own sign-in: no key)
const AWAY_PLAN: Record<string, string> = {
  ...AWAY,
  sign_in: 'needs you to sign in (System).',
  refused: 'is refused for your subscription at its provider.',
};
const mindWhere = (settings: Settings) =>
  settings.parts.mind.options.find((o) => o.id === settings.choices.mind.id)?.where;
const mindName = (settings: Settings) =>
  settings.parts.mind.options.find((o) => o.id === settings.choices.mind.id)?.model ??
  'The one you talk to';

function Model({ row, bench, settings }: { row: Row; bench: boolean; settings: Settings }) {
  const main = row.mind ?? row.hands ?? row.manager!;
  const needy = ROLES.map((role) => row[role]).find((o) => o?.needs);
  return (
    <div className="vs-model" role="rowheader">
      <Disc mark={row.mark} />
      <span className="vs-kv">
        <span className="vs-sub">{row.provider}</span>
        <b className="vs-name">{row.model}</b>
        {needy && <Missing option={needy} />}
        {bench && <Bench option={main} settings={settings} />}
      </span>
    </div>
  );
}

export function Brain({ settings, save }: { settings: Settings; save: Save }) {
  const [bench, setBench] = useState(false);
  const all = rows(settings);
  const groups = ORDER.filter((where) => all.some((r) => r.where === where));
  const hands = settings.choices.hands;
  const several = hands.use.length > 1;
  const cell = { settings, save };
  // The mind's declared backup sits with the mind at every width: under its column on a desk, at the end of its part
  // on a phone (on a phone it sat above "Conscious mind", between the Brain heading and the part).
  const backup = settings.paused ? (
    // (his choice holds: the mind is off, or not signed in, and nothing else is declared to answer)
    <p className="vs-hint vs-backup" role="status" data-now="true">
      Replies pause until you turn a mind on: sign in or turn it on in System, or choose another
      mind.
    </p>
  ) : settings.backup ? (
    settings.backup_now && settings.backup_of === settings.choices.mind.id ? (
      // (its online mind set aside, as LiveKit's fallback recorded it: the backup answers now, with a quick check; said
      // only of the choice the finding is about, never of one just chosen and not yet asked)
      <p className="vs-hint vs-backup" role="status" data-now="true">
        Answering now: {settings.backup}. {mindName(settings)}{' '}
        {(mindWhere(settings) === 'plan' ? AWAY_PLAN : AWAY)[settings.backup_now] ?? AWAY.down}
        {settings.backup_seen
          ? ` (last found at ${new Date(settings.backup_seen * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })})`
          : ''}
      </p>
    ) : (
      <p className="vs-hint vs-backup">Backup: {settings.backup}.</p>
    )
  ) : null;
  const lastMind = settings.last_mind?.provider && (
    <p className="vs-hint vs-backup" role="status">
      Last reply: {settings.last_mind.provider} ({settings.last_mind.model}).
    </p>
  );
  return (
    <Pane
      id="brain"
      title="Brain"
      aside={
        // (her live brain, the Subconscious page's own button, here too: easy to find where the brain is set)
        <span className="vsx-aside vs-brain-aside">
          <Link href="/settings/subconscious/live" className="vsx-live">
            <BrainCircuit />
            View live
          </Link>
          <button
            type="button"
            className="vs-bench"
            aria-pressed={bench}
            onClick={() => setBench(!bench)}
          >
            <Gauge />
            Speed and smarts
          </button>
        </span>
      }
    >
      {/* Wide screens: one table */}
      <div className="vs-matrix" role="table" aria-label="What each part of the brain runs on">
        <div className="vs-mx-row" data-heads="true" role="row">
          <span role="columnheader" aria-label="Model" />
          {ROLES.map((role) => (
            <Head key={role} part={settings.parts[role]} cell />
          ))}
        </div>
        {groups.map((where) => (
          <div
            key={where}
            className="vs-grp"
            role="rowgroup"
            aria-label={settings.where[where].name}
          >
            <GroupHead where={where} place={settings.where[where]} table={ROLES.length + 1} />
            {all
              .filter((r) => r.where === where)
              .map((row) => (
                <div key={`${row.provider}-${row.model}`} className="vs-mx-row" role="row">
                  <Model row={row} bench={bench} settings={settings} />
                  {ROLES.map((role) => (
                    <Cell key={role} row={row} role={role} {...cell} />
                  ))}
                </div>
              ))}
          </div>
        ))}
        {(backup || lastMind) && (
          <div className="vs-mx-row" data-foot="true" role="row">
            <span role="cell" />
            <div role="cell">
              {backup}
              {lastMind}
            </div>
            <span role="cell" />
            <span role="cell" />
          </div>
        )}
      </div>

      {/* Phones: the same three parts, one under the other */}
      <div className="vs-stack">
        {ROLES.map((role) => (
          <div key={role} className="vs-stack-part">
            <Head part={settings.parts[role]} />
            {groups
              .filter((where) => all.some((r) => r.where === where && r[role]))
              .map((where) => (
                <div key={where} className="vs-grp">
                  <GroupHead where={where} place={settings.where[where]} />
                  {all
                    .filter((r) => r.where === where && r[role])
                    .map((row) => (
                      <div key={`${row.provider}-${row.model}`} className="vs-stack-row">
                        <Model row={row} bench={bench} settings={settings} />
                        <Cell row={row} role={role} {...cell} />
                      </div>
                    ))}
                </div>
              ))}
            {role === 'mind' && (
              <>
                {backup}
                {lastMind}
              </>
            )}
          </div>
        ))}
      </div>

      <Expand open={several}>
        <div className="vs-ask">
          <label className="vs-h3" htmlFor="vs-ask">
            {settings.ask}
          </label>
          <Words
            label={settings.ask}
            value={settings.workers_note}
            placeholder="Codex for code. Claude for everything else."
            onSave={(text) => save({ workers_note: text })}
          />
        </div>
      </Expand>

      {/* One step further in, each a page of its own: what it thinks about unasked, what it does at a set time, what
          it remembers, and every text it is given */}
      <div className="vsx-doors">
        <Link href="/settings/subconscious" className="vsx-door">
          <span className="vsx-sign" aria-hidden="true">
            <BrainIcon strokeWidth={1.7} />
          </span>
          <span>
            <span className="vs-h3">Subconscious</span>
            <span className="vs-hint">What it thinks about on its own.</span>
          </span>
          <ChevronRight />
        </Link>
        <Link href="/settings/scheduling" className="vsx-door">
          <span className="vsx-sign" aria-hidden="true">
            <Clock strokeWidth={1.7} />
          </span>
          <span>
            <span className="vs-h3">Scheduling</span>
            <span className="vs-hint">Reminders, continuous awareness, sleep, dreaming.</span>
          </span>
          <ChevronRight />
        </Link>
        <Link href="/settings/memory" className="vsx-door">
          <span className="vsx-sign" aria-hidden="true">
            <BookOpen strokeWidth={1.7} />
          </span>
          <span>
            <span className="vs-h3">Memory</span>
            <span className="vs-hint">What it remembers, and putting it right.</span>
          </span>
          <ChevronRight />
        </Link>
        <Link href="/settings/prompts" className="vsx-door">
          <span className="vsx-sign" aria-hidden="true">
            <FileText strokeWidth={1.7} />
          </span>
          <span>
            <span className="vs-h3">Prompts</span>
            <span className="vs-hint">Every text it is given.</span>
          </span>
          <ChevronRight />
        </Link>
      </div>
    </Pane>
  );
}
