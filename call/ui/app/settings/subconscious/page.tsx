'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { BrainCircuit, Plus } from 'lucide-react';
import { CortexCard, ago, runsNow } from '../components/cortex';
import { Pane, Segmented, Switch } from '../components/glass';
import { Open, Prompt, Sheet, Thinking, Who, onThisMac } from '../components/mind';
import { type Cortex, type Subconscious, useKept } from '../lib/kept';
import { useSettings } from '../lib/use-settings';

// The Subconscious: what Viventium thinks about on its own, beside the conversation. A second copy of the
// Worker manager reads the cards after every turn and decides which cortices run; each cortex is two prompts.

// How the cortices are shown: each one a row (the overview), or every card open (the details). This viewer's choice,
// kept in this browser only; the page works the same without it.
type View = 'overview' | 'details';
const VIEW = 'viventium.cortices.view';
const views: { id: View; name: string }[] = [
  { id: 'overview', name: 'Overview' },
  { id: 'details', name: 'Details' },
];

export default function SubconsciousPage() {
  const { settings } = useSettings();
  const { state, save, notice, saved } = useKept<Subconscious>('subconscious');
  const ready = settings && state;
  const [view, setView] = useState<View>('overview');
  const [opened, setOpened] = useState<Set<string>>(new Set());
  useEffect(() => {
    try {
      if (localStorage.getItem(VIEW) === 'details') setView('details');
    } catch {
      /* (no storage here: the overview) */
    }
  }, []);
  const show = (next: View) => {
    setView(next);
    setOpened(new Set());
    try {
      localStorage.setItem(VIEW, next);
    } catch {
      /* (kept for this visit only) */
    }
  };
  const isOpen = (id: string) => view === 'details' || opened.has(id);
  const toggle = (id: string) => {
    if (view === 'details') {
      // (closing one card in the details: the rest stay open, as an overview with those opened)
      setView('overview');
      setOpened(new Set(state?.cortices.map((c) => c.id).filter((x) => x !== id)));
      return;
    }
    setOpened((now) => {
      const next = new Set(now);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const card = (id: string, fields: Partial<Cortex>) =>
    save({ card: { id, ...fields } }, (s) => ({
      ...s,
      cortices: s.cortices.map((c) => (c.id === id ? { ...c, ...fields } : c)),
    }));
  const add = async () => {
    const answer = await save({ add: true });
    if (!answer.added) return;
    setOpened((now) => new Set(now).add(String(answer.added)));
    requestAnimationFrame(() => {
      const name = document.querySelector<HTMLInputElement>(
        `[data-id="${answer.added}"] .vsx-name`
      );
      name?.scrollIntoView({ block: 'center', behavior: 'smooth' });
      name?.focus({ preventScroll: true });
    });
  };

  const co = state?.coordinator;
  const managers = settings?.parts.manager.options.filter((o) => !o.needs) ?? [];
  const follows = co?.runs_on === 'manager';
  const runsOn = follows ? (settings?.choices.manager.id ?? '') : (co?.runs_on ?? '');
  const manager = managers.find((o) => o.id === runsOn);
  const coordinator = (fields: Partial<Subconscious['coordinator']>) =>
    save({ coordinator: fields }, (s) => ({ ...s, coordinator: { ...s.coordinator, ...fields } }));

  return (
    <Sheet
      wide
      title="Subconscious"
      lede="What Viventium thinks about on its own, beside your conversation. It never delays an answer, and it never touches the work you asked for."
      note={
        state
          ? state.status +
            (state.running && state.last_round ? ` Last round: ${ago(state.last_round.at)}.` : '')
          : undefined
      }
      notice={notice}
      saved={saved}
    >
      {ready && co && (
        <>
          <Pane
            title="Coordinator"
            aside={
              <Switch label="Subconscious" on={co.on} onChange={(on) => coordinator({ on })} />
            }
          >
            <div className="vsx-two">
              <div className="vsx-words">
                <p>
                  After every turn, the coordinator reads the “When” of each card below and decides
                  which ones to run. It is the same Worker manager you already have, in a second,
                  separate copy that only does this.
                </p>
                <p>A card with an empty “When” does not ask it: it just runs.</p>
              </div>
              <div className="vsx-sets">
                <Who
                  name="The coordinator"
                  aside={
                    [
                      follows && 'the same as the Worker manager',
                      co.place &&
                        `runs now: ${runsNow(co.place, co.effort, settings.effort_names)}`,
                      co.place?.note?.replace(/\.$/, '') ||
                        (co.place?.kind === 'mac' &&
                          manager &&
                          manager.where !== 'mac' &&
                          'on Local it thinks on this Mac'),
                    ]
                      .filter(Boolean)
                      .join('; ') || undefined
                  }
                  value={runsOn}
                  options={managers}
                  onChange={(runs_on) => coordinator({ runs_on })}
                />
                <Thinking
                  name="the coordinator"
                  option={
                    co.place?.kind === 'mac' ? onThisMac(manager, state.mac_efforts) : manager
                  }
                  value={co.effort}
                  names={settings.effort_names}
                  onChange={(effort) => coordinator({ effort })}
                />
                <span className="vsx-set">
                  <span className="vsx-lab">Wait for linked cortices, at most</span>
                  <Segmented
                    label="Wait for linked cortices, at most"
                    size="sm"
                    value={String(co.wait)}
                    options={state.waits.map((m) => ({
                      id: String(m),
                      name: m === 1 ? '1 minute' : `${m} minutes`,
                    }))}
                    onChange={(m) => coordinator({ wait: Number(m) })}
                  />
                </span>
              </div>
            </div>
            <Open title="The one prompt it reads, made from the cards">
              <pre className="vsx-pre" data-merged="true">
                {state.merged}
                {state.always.length > 0 &&
                  `\n\n(Not asked, started at once on every turn: ${state.always.join(', ')}.)`}
              </pre>
            </Open>
          </Pane>

          <Pane
            title="Cortices"
            aside={
              <span className="vsx-aside">
                <span className="vs-hint">{state.cortices.filter((c) => c.on).length} on</span>
                <Segmented
                  label="Show the cortices"
                  size="sm"
                  value={view}
                  options={views}
                  onChange={show}
                />
                <Link href="/settings/subconscious/live" className="vsx-live">
                  <BrainCircuit />
                  View live
                </Link>
              </span>
            }
          >
            {state.groups.map((group) => (
              <div key={group.id} className="vs-grp vsx-grp">
                <div className="vs-grp-head">
                  <span className="vs-grp-name">{group.name}</span>
                  <span className="vsx-say">{group.say}</span>
                  <span className="vs-grp-line" aria-hidden="true" />
                </div>
                <div className="vsx-cards" data-view={view}>
                  {state.cortices
                    .filter((c) => c.group === group.id)
                    .map((c) => (
                      <CortexCard
                        key={c.id}
                        cortex={c}
                        settings={settings}
                        helpers={state.helpers}
                        macEfforts={state.mac_efforts}
                        open={isOpen(c.id)}
                        onToggle={() => toggle(c.id)}
                        change={(fields) => card(c.id, fields)}
                        remove={() =>
                          save({ remove: c.id }, (s) => ({
                            ...s,
                            cortices: s.cortices.filter((x) => x.id !== c.id),
                          }))
                        }
                      />
                    ))}
                </div>
              </div>
            ))}
            <button type="button" className="vsx-add" onClick={add}>
              <Plus />
              Add a cortex
            </button>
          </Pane>

          <Pane title="How a thought reaches you">
            <div className="vsx-two">
              <div className="vsx-words">
                <p>
                  A cortex never speaks to you. What it finds goes to the conscious mind as its own
                  background thinking. The conscious mind then either continues its thought to you,
                  in its own voice, or keeps it in mind and says nothing.
                </p>
                <p>
                  Linked cortices arrive together. If you speak first, your words come first and the
                  thoughts ride along with that turn.
                </p>
              </div>
              <div className="vsx-box">
                <span className="vsx-box-name">What the conscious mind is told</span>
                <Prompt
                  label="What the conscious mind is told"
                  field="surfacing"
                  whole
                  value={state.surfacing}
                  onSave={(surfacing) => save({ surfacing })}
                />
              </div>
            </div>
            <Open title="What every cortex is told first">
              <div className="vsx-box vsx-opened">
                <Prompt
                  label="What every cortex is told first"
                  field="every_cortex"
                  whole
                  value={state.every_cortex}
                  onSave={(every_cortex) => save({ every_cortex })}
                />
              </div>
            </Open>
          </Pane>
        </>
      )}
    </Sheet>
  );
}
