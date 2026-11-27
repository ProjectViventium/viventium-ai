'use client';

import { useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { Expand, Pane, Segmented, Switch } from '../components/glass';
import { Open, Prompt, Sheet, Sign, Thinking, Who, workers } from '../components/mind';
import { type Reminder, type Routine, type Run, type Scheduling, useKept } from '../lib/kept';
import { useSettings } from '../lib/use-settings';

// Scheduling: what Viventium does at a set time. Yours on top (reminders and repeating moments: real today);
// under them what it does by itself on the same clock: a heartbeat while you are awake, sleep and dreaming at
// night.

// A named zone this browser knows ("Europe/Paris"), else none: then a moment is said on this Mac's own clock.
const known = (zone?: string) => {
  if (!zone) return undefined;
  try {
    new Intl.DateTimeFormat([], { timeZone: zone });
    return zone;
  } catch {
    return undefined;
  }
};
const clock = (d: Date, zone?: string) =>
  d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', timeZone: known(zone) });
// (which calendar day a moment falls on, in that zone or on this Mac: a number of days, to compare)
const dayOf = (d: Date, zone?: string) => {
  const part = Object.fromEntries(
    new Intl.DateTimeFormat('en-US', {
      timeZone: known(zone),
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
    })
      .formatToParts(d)
      .map((p) => [p.type, Number(p.value)])
  );
  return Date.UTC(part.year, part.month - 1, part.day) / 86_400_000;
};
const day = (d: Date, zone?: string) => {
  const days = Math.round(dayOf(d, zone) - dayOf(new Date(), zone));
  if (days === 0) return 'Today';
  if (days === 1) return 'Tomorrow';
  if (days === -1) return 'Yesterday';
  return d.toLocaleDateString([], {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    timeZone: known(zone),
  });
};
const moment = (iso: string, zone?: string) =>
  `${day(new Date(iso), zone)}, ${clock(new Date(iso), zone)}`;
// A moment kept in a named zone is said in that zone, and says so ("9:00 AM · Paris time"); one with none follows this
// Mac wherever it is.
const zoned = (zone?: string) =>
  known(zone) ? ` · ${zone!.split('/').pop()!.replace(/_/g, ' ')} time` : '';
function when(item: Reminder) {
  const d = new Date(item.when);
  const at = `${clock(d, item.zone)}${zoned(item.zone)}`;
  if (item.repeat === 'daily') return `Every day at ${at}`;
  if (item.repeat === 'weekdays') return `Every weekday at ${at}`;
  if (item.repeat === 'weekly')
    return `Every ${d.toLocaleDateString([], { weekday: 'long', timeZone: known(item.zone) })} at ${at}`;
  return `Once, ${moment(item.when, item.zone)}${zoned(item.zone)}`;
}
function late(run: Run) {
  const minutes = Math.round((+new Date(run.at) - +new Date(run.due_at ?? run.due)) / 60_000);
  if (minutes < 2) return 'on time';
  return minutes < 90 ? `${minutes} minutes late` : `${Math.round(minutes / 60)} hours late`;
}
const ENDED: Record<string, string> = {
  told: 'Told you',
  quiet: 'Stayed quiet',
  work: 'Started work',
  owed: 'Kept for your next call or chat',
  missed: 'Missed',
  failed: 'Could not tell you',
};
// A beat of its own (continuous awareness): what it chose to do, and why when it did not reach you.
const BEAT: Record<string, string> = {
  told: 'Reached out',
  quiet: 'Stayed quiet',
  work: 'Started work',
  failed: 'Could not look',
  passed: 'Passed',
  call: 'Passed: you were on a call',
  nochannel: 'No channel to reach you on: connect Telegram',
  noanswer: 'Its model gave no answer: stayed quiet',
  missed: 'Missed',
};
// A night of its own (sleep, dreaming): a Worker did it; what it handed back is under it.
const NIGHT: Record<string, string> = {
  work: 'Done',
  failed: 'Could not run',
  stopped: 'Stopped',
  missed: 'Missed',
};
// Where a night ran, in the words of System's accounts (a route is a Worker type, on this Mac's sign-in or another).
const ROUTES: Record<string, string> = {
  'claude-code': 'your Claude plan',
  'codex-cli': 'your ChatGPT plan',
  'grok-build': 'your Grok plan',
  local: 'this Mac',
};
function routeWords(route?: string) {
  const [kind, account] = (route ?? '').split('@');
  const where = ROUTES[kind];
  return where ? `${where}${account ? ' (another account)' : ''}` : '';
}
// What became of Dreaming's note at the morning's first moment of continuous awareness (brain/night.handed).
const MORNING: Record<string, string> = {
  told: 'Its note was told to you in the morning.',
  unverified: 'Its note was sent to you in the morning.',
  unknown: 'Its note was sent in the morning; whether it reached you is not known.',
  kept: 'Its note was kept in mind, not said.',
  stale: 'Its note was too old by the morning, so it was not said.',
};
// ...and the same, said at the beat that handed it over.
const NOTE: Record<string, string> = {
  told: 'Dreaming’s note: told.',
  unverified: 'Dreaming’s note: sent; it is offered once more.',
  unknown: 'Dreaming’s note: sent; whether it reached you is not known.',
  kept: 'Dreaming’s note: kept in mind, not said.',
  refused: 'Dreaming’s note: it could not go out; it waits for the next look.',
  stale: 'Dreaming’s note: too old, not said.',
};
const counted = (tokens?: Run['tokens']) =>
  tokens?.in
    ? `Read ${tokens.in.toLocaleString()} tokens${tokens.cached ? ` (${tokens.cached.toLocaleString()} kept from before)` : ''}, wrote ${(tokens.out ?? 0).toLocaleString()}`
    : undefined;
// One line of history: what happened, how late and why, when it was due (and, if this Mac has moved since, when that
// is here), and (when it was the backup) that Viventium kept the time itself. A night also says where it ran, what it
// wrote in your Life, the one step that holds it, and what became of its note.
function Ran({
  run,
  named,
  beat,
  night,
}: {
  run: Run;
  named?: boolean;
  beat?: boolean;
  night?: boolean;
}) {
  const here = run.due_at ? moment(run.due_at) : '';
  const moved = here && here !== moment(run.due);
  const words = (night ? NIGHT : beat ? BEAT : ENDED)[run.how];
  const where = night ? routeWords(run.route) : '';
  return (
    <tr data-how={run.how}>
      <td title={run.due_at ? `Due ${run.due_at}` : undefined}>
        {moment(run.due)}
        {moved && <span className="vsx-here">{clock(new Date(run.due_at!))} here</span>}
      </td>
      <td title={counted(run.tokens)}>
        {named && <>{run.what} · </>}
        <b>{words ?? (night ? run.how : 'Woke Viventium with it')}</b>
        {!beat &&
          !night &&
          (run.how === 'missed' ? ' · found too late to be worth telling' : ` · ${late(run)}`)}
        {run.late && (beat || night ? ` · late: ${run.late}` : ` (${run.late})`)}
        {where && ` · on ${where}`}
        {run.by === 'light' && ' · Viventium kept the time itself'}
        {run.why && run.how !== 'work' && <span className="vsx-said">{run.why}</span>}
        {beat && run.said && <span className="vsx-said">“{run.said}”</span>}
        {beat && run.note && NOTE[run.note] && <span className="vsx-said">{NOTE[run.note]}</span>}
        {night && run.span && (
          <span className="vsx-said">
            It went through {moment(run.span[0])} to {moment(run.span[1])}.
          </span>
        )}
        {night && run.unread && <span className="vsx-said">{run.unread}</span>}
        {night && run.limited && <span className="vsx-said">{run.limited}</span>}
        {night && run.result && run.how === 'work' && (
          <span className="vsx-said">{run.result}</span>
        )}
        {night && run.life && (
          <span className="vsx-said" title={run.life.wrote.join('\n') || undefined}>
            {run.life.count
              ? `Wrote ${run.life.count === 1 ? 'one file' : `${run.life.count} files`} in your Life`
              : 'Wrote nothing in your Life'}
            {run.life.others > 0 &&
              ` · ${run.life.others === 1 ? 'one other change' : `${run.life.others} other changes`} there meanwhile, not its own`}
            {run.commit &&
              ` · kept as its own step in your Life's history (${run.commit.slice(0, 7)})`}
            {run.life.outside?.length
              ? ` · it named ${run.life.outside.length === 1 ? 'one file' : `${run.life.outside.length} files`} outside your Life, never kept`
              : ''}
            {run.life.no_commit && ` · not kept as one step: ${run.life.no_commit}`}
          </span>
        )}
        {night && run.morning && MORNING[run.morning] && (
          <span className="vsx-said">{MORNING[run.morning]}</span>
        )}
      </td>
    </tr>
  );
}
const hour = (hhmm: string) => {
  const [h, m] = hhmm.split(':').map(Number);
  return clock(new Date(2026, 0, 1, h, m));
};

function Yours({
  item,
  save,
}: {
  item: Reminder;
  save: ReturnType<typeof useKept<Scheduling>>['save'];
}) {
  const [open, setOpen] = useState(false);
  const patch = (fields: Partial<Reminder>) => (s: Scheduling) => ({
    ...s,
    yours: s.yours.map((y) => (y.id === item.id ? { ...y, ...fields } : y)),
  });
  return (
    <div className="vsx-row" data-on={!item.paused} data-id={item.id}>
      <div className="vsx-row-top">
        <Switch
          label={item.what}
          on={!item.paused}
          onChange={(on) => save({ pause: { id: item.id, paused: !on } }, patch({ paused: !on }))}
        />
        <span className="vsx-what">
          <b className="vs-name">{item.what}</b>
          <span className="vs-sub">{when(item)}</span>
        </span>
        <span className="vsx-next">
          {item.paused ? (
            'Paused'
          ) : (
            <>
              Next: <b>{moment(item.when)}</b>
            </>
          )}
        </span>
        <button
          type="button"
          className="vsx-icon vsx-chev"
          aria-expanded={open}
          aria-label={`History of ${item.what}`}
          onClick={() => setOpen(!open)}
        >
          <ChevronRight />
        </button>
      </div>
      <Expand open={open}>
        <div className="vsx-row-more">
          {item.history.length ? (
            <table className="vsx-hist">
              <tbody>
                {item.history.map((run) => (
                  <Ran key={run.due} run={run} />
                ))}
              </tbody>
            </table>
          ) : (
            <p className="vs-hint">
              {item.repeat ? 'It has not come due yet.' : 'It comes once, then it is gone.'}
            </p>
          )}
          <button
            type="button"
            className="vs-missing"
            data-link="true"
            onClick={() =>
              save({ remove: item.id }, (s) => ({
                ...s,
                yours: s.yours.filter((y) => y.id !== item.id),
              }))
            }
          >
            Remove
          </button>
        </div>
      </Expand>
    </div>
  );
}

function Add({
  state,
  save,
}: {
  state: Scheduling;
  save: ReturnType<typeof useKept<Scheduling>>['save'];
}) {
  const [what, setWhat] = useState('');
  const [at, setAt] = useState('');
  const [repeat, setRepeat] = useState('');
  const add = async () => {
    if (!what.trim() || !at) return;
    const answer = await save({ add: { what: what.trim(), when: at, repeat } });
    if (answer.ok) {
      setWhat('');
      setAt('');
      setRepeat('');
    }
  };
  return (
    <form
      className="vsx-addrow"
      onSubmit={(e) => {
        e.preventDefault();
        add();
      }}
    >
      <div className="vsx-addrow-when">
        <input
          className="vs-input"
          type="datetime-local"
          aria-label="When"
          value={at}
          onChange={(e) => setAt(e.target.value)}
        />
        <Segmented
          label="How often"
          size="sm"
          value={repeat || 'once'}
          options={state.repeats.map((r) => ({ id: r.id || 'once', name: r.name }))}
          onChange={(id) => setRepeat(id === 'once' ? '' : id)}
        />
      </div>
      <textarea
        className="vs-input vsx-addwhat"
        placeholder="What"
        aria-label="What"
        value={what}
        maxLength={2000}
        onChange={(e) => setWhat(e.target.value)}
      />
      <button type="submit" className="vs-act" disabled={!what.trim() || !at}>
        Add
      </button>
    </form>
  );
}

function BuiltIn({
  routine,
  save,
  settings,
}: {
  routine: Routine;
  save: ReturnType<typeof useKept<Scheduling>>['save'];
  settings: NonNullable<ReturnType<typeof useSettings>['settings']>;
}) {
  const change = (fields: Partial<Routine>) =>
    save({ routine: { id: routine.id, ...fields } }, (s) => ({
      ...s,
      builtin: s.builtin.map((r) => (r.id === routine.id ? { ...r, ...fields } : r)),
    }));
  const options = routine.runs_on === 'mind' ? [] : workers(settings, routine.runs_on);
  const time = (field: 'awake_from' | 'awake_to' | 'at', label: string) => (
    <input
      className="vs-input vsx-time"
      type="time"
      aria-label={label}
      title={hour(routine[field] ?? '00:00')}
      defaultValue={routine[field]}
      key={routine[field]}
      onBlur={(e) =>
        e.target.value && e.target.value !== routine[field] && change({ [field]: e.target.value })
      }
    />
  );
  return (
    <article className="vsx-card" data-on={routine.on} data-id={routine.id}>
      <div className="vsx-card-head">
        <Sign name={routine.sign} />
        <span className="vsx-id">
          <span className="vs-h3">
            <span>{routine.name}</span>
            <span className="vs-region">{routine.region}</span>
          </span>
          <span className="vsx-does">{routine.does}</span>
        </span>
        <span className="vsx-tools">
          {!routine.running ? (
            <span className="vsx-quiet" data-yet="true">
              Not running yet
            </span>
          ) : routine.now?.state ? (
            // (a night routine this minute: waiting, and why; or running, and where)
            <span className="vsx-next" role="status" data-now={routine.now.state}>
              {routine.now.state === 'running' ? (
                <>
                  <b>Running now</b>
                  {routeWords(routine.now.route) && ` on ${routeWords(routine.now.route)}`}
                </>
              ) : routine.now.state === 'refused' ? (
                <>
                  <b>Not on the clock</b>
                  {routine.now.why && `: ${routine.now.why}`}
                </>
              ) : (
                <>
                  <b>Waiting</b>
                  {routine.now.why && `: ${routine.now.why}`}
                </>
              )}
            </span>
          ) : (
            routine.on &&
            routine.next && (
              <span className="vsx-next">
                Next: <b>{moment(routine.next)}</b>
              </span>
            )
          )}
          {routine.running && routine.now?.held && (
            // (held by a run Light cannot confirm: let go only once no run of its Worker is going: brain/night.py)
            <button
              type="button"
              className="vs-quiet-btn vsx-clear"
              aria-label={`Clear ${routine.name}`}
              onClick={() => save({ clear: routine.id })}
            >
              Clear
            </button>
          )}
          <Switch label={routine.name} on={routine.on} onChange={(on) => change({ on })} />
        </span>
      </div>
      <div className="vsx-body">
        <div className="vsx-run">
          {routine.every_minutes ? (
            <>
              <span className="vsx-set">
                <span className="vsx-lab">How often</span>
                <Segmented
                  label={`How often ${routine.name} comes`}
                  size="sm"
                  value={String(routine.every_minutes)}
                  options={[20, 30, 60, 120].map((m) => ({
                    id: String(m),
                    name: m < 60 ? `${m} minutes` : m === 60 ? '1 hour' : `${m / 60} hours`,
                  }))}
                  onChange={(m) => change({ every_minutes: Number(m) })}
                />
              </span>
              <span className="vsx-set">
                <span className="vsx-lab">Awake hours</span>
                <span className="vsx-times">
                  {time('awake_from', 'Awake from')}
                  <span className="vs-hint">to</span>
                  {time('awake_to', 'Awake to')}
                </span>
              </span>
            </>
          ) : (
            <span className="vsx-set">
              <span className="vsx-lab">Every night at</span>
              <span className="vsx-times">{time('at', `${routine.name} every night at`)}</span>
            </span>
          )}
          {routine.runs_on === 'mind' ? (
            <span className="vsx-set">
              <span className="vsx-lab">Runs on</span>
              <span className="vsx-plain">The conscious mind itself, so it is one voice</span>
            </span>
          ) : (
            <>
              <Who
                name={routine.name}
                value={routine.runs_on}
                options={options}
                onChange={(runs_on) => change({ runs_on })}
              />
              <Thinking
                name={routine.name}
                option={options.find((o) => o.id === routine.runs_on)}
                value={routine.effort}
                names={settings.effort_names}
                onChange={(effort) => change({ effort })}
              />
            </>
          )}
        </div>
        <Open title="What it is told when it wakes">
          <div className="vsx-box vsx-opened">
            <Prompt
              label={`What ${routine.name} is told`}
              field="prompt"
              whole
              value={routine.prompt}
              onSave={(prompt) => change({ prompt })}
            />
          </div>
        </Open>
        {routine.running && (
          <Open title="Last runs">
            {routine.history.length ? (
              <table className="vsx-hist vsx-opened">
                <tbody>
                  {routine.history.map((run) => (
                    <Ran
                      key={run.due}
                      run={run}
                      beat={Boolean(routine.every_minutes)}
                      night={!routine.every_minutes}
                    />
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="vs-hint vsx-opened">It has not come round yet.</p>
            )}
          </Open>
        )}
      </div>
    </article>
  );
}

export default function SchedulingPage() {
  const { settings } = useSettings();
  const { state, save, notice, saved } = useKept<Scheduling>('scheduling');
  return (
    <Sheet
      title="Scheduling"
      lede="What Viventium does at a set time. Yours on top. What it does by itself, to stay aware and to remember, below."
      notice={notice}
      saved={saved}
    >
      {settings && state && (
        <>
          <Pane
            title="Yours"
            aside={
              <span className="vs-hint">Or just say it: “remind me at 5 to call the dentist”.</span>
            }
          >
            {state.yours.length ? (
              <div className="vsx-rows">
                {state.yours.map((item) => (
                  <Yours key={item.id} item={item} save={save} />
                ))}
              </div>
            ) : (
              <p className="vsx-empty">Nothing is set.</p>
            )}
            <Add state={state} save={save} />
            {state.earlier.length > 0 && (
              <Open title="Earlier">
                <table className="vsx-hist vsx-opened">
                  <tbody>
                    {state.earlier.map((run) => (
                      <Ran key={`${run.what}${run.due}`} run={run} named />
                    ))}
                  </tbody>
                </table>
              </Open>
            )}
            {state.clock === 'light' && (
              <p className="vsx-yet vsx-backup" role="note">
                xPerfect’s clock is not reachable. Viventium is keeping the time itself.
              </p>
            )}
          </Pane>
          <Pane
            title="Built in"
            aside={<span className="vs-hint">On the same clock as yours.</span>}
          >
            <div className="vsx-cards">
              {state.builtin.map((routine) => (
                <BuiltIn key={routine.id} routine={routine} save={save} settings={settings} />
              ))}
            </div>
          </Pane>
        </>
      )}
    </Sheet>
  );
}
