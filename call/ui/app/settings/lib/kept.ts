'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { Option } from './api';

// The two pages of their own (Subconscious, Scheduling): what each shows and the one small change it saves.
// Each page has its own module in the settings package and its own kept file; this is their one adapter.

export type Cortex = {
  id: string;
  name: string;
  group: string;
  region: string;
  does: string;
  sign: string;
  system: boolean; // comes with Viventium: switched on or off, never removed
  hands_back: 'thought' | 'feelings';
  when: string; // empty: it runs every turn, and the coordinator is not asked
  then: string;
  runs_on: string;
  effort: string;
  linked: boolean; // its thought waits for the other linked ones
  on: boolean;
  place?: Place; // where it runs on the profile now (Local: this Mac, whatever it chose)
  last?: LastRun | null; // what it did last (brain/rounds.py keeps it)
};
// Where a part runs now (brain/rounds.place): on a Worker harness, on this Mac's model, or on her quick helpers, at the
// effort it really thinks at; `note` says why that is not exactly what was chosen ("" when it is).
export type Place = {
  kind: 'worker' | 'mac' | 'helpers' | 'none';
  name: string;
  effort?: string;
  note?: string;
};
// One part's last outcome: a thought, nothing to add, Feelings moved, or could not run (`how` says why).
export type LastRun = {
  at: number; // seconds since the epoch
  state?: 'thought' | 'nothing' | 'feelings' | 'failed';
  ms?: number;
  where?: string;
  how?: string;
  words?: string;
  why?: string;
  picked?: string[];
};
export type Subconscious = {
  running: boolean; // a round runs after every answer while the one switch is on
  status: string; // one true line under the title
  last_round?: LastRun | null;
  helpers: Option; // her quick helpers, as a choice for a card (they follow the profile)
  coordinator: {
    on: boolean;
    runs_on: string; // 'manager': whatever the Worker manager runs on
    effort: string;
    wait: number;
    before: string;
    after: string;
    place?: Place;
    last?: LastRun | null;
  };
  groups: { id: string; name: string; say: string }[];
  cortices: Cortex[];
  every_cortex: string;
  surfacing: string;
  merged: string; // the one prompt the coordinator reads
  always: string[];
  waits: number[];
  mac_efforts: string[]; // what a part on this Mac's model can take: thinking off, low, medium, high
};

// What happened when a moment came: told, quiet (it chose to say nothing), work (it started a Worker), owed (kept for
// your next call or chat), missed (found too late to be worth telling); for a beat also call (you were on a call, so
// it passed) and nochannel (no Telegram to reach you on). `by`: who rang it: xPerfect's clock, or
// Light itself because no notice came.
export type Run = {
  what: string;
  due: string; // as this Mac read it when the line was written
  due_at?: string; // the instant it is known by, with its offset (core/schedules)
  at: string;
  how: string;
  by: string;
  why?: string; // why it ended so: quiet, failed, passed, missed, stopped
  late?: string; // taken long after its time, and why ("this Mac was asleep")
  night?: string; // the evening a night run belongs to
  route?: string; // where a night run ran: a Worker type's route ("claude-code", "codex-cli@<account>")
  // what a night run wrote in your Life: its own files, how many others changed there meanwhile, what it named outside
  // your Life (never kept), and why nothing could be kept as one step
  life?: { wrote: string[]; count: number; others: number; outside?: string[]; no_commit?: string };
  span?: [string, string]; // the part of the day a night went through
  unread?: string; // lines of the record a night could not read (gone through again next night)
  limited?: string; // what a night left out, and why (a backlog of more than a week)
  said?: string; // the words a beat delivered
  note?: string; // what became of Dreaming's note at this beat: told, unverified, unknown, kept, refused, stale
  tokens?: { in?: number; out?: number; cached?: number }; // what a beat read and wrote, as its model counted it
  commit?: string; // the one step in your Life folder's history that holds what it wrote
  morning?: string; // what became of Dreaming's note: told, unverified, unknown, kept, stale
  morning_at?: string;
  result?: string; // what a night run (sleep, dreaming) handed back
};
export type Reminder = {
  id: string;
  what: string;
  when: string;
  repeat: string;
  paused: boolean;
  zone?: string; // kept in a named zone ("Europe/Paris"); none: it follows this Mac
  history: Run[];
};
export type Routine = {
  id: string;
  name: string;
  region: string;
  does: string;
  sign: string;
  on: boolean;
  runs_on: string; // 'mind': the conscious mind itself
  effort: string;
  prompt: string;
  every_minutes?: number;
  awake_from?: string;
  awake_to?: string;
  at?: string;
  running: boolean; // it runs: the heartbeat on its beat, sleep and dreaming every night (brain/night.py)
  next: string; // its next beat, when it runs and is on
  // a night routine this minute: waiting (and why), running (and where), or refused (its time is inside your day)
  // (held: a night held by a run Light cannot confirm; Clear asks both of his xPerfects first, brain/night.py)
  now?: {
    state?: 'waiting' | 'running' | 'refused';
    why?: string;
    route?: string;
    since?: string;
    held?: boolean;
  };
  history: Run[]; // what its last beats did
};
export type Scheduling = {
  yours: Reminder[];
  earlier: Run[]; // moments that came once and are gone
  clock: 'xperfect' | 'light'; // who keeps the time now
  builtin: Routine[];
  repeats: { id: string; name: string }[];
  every: number[];
};

type Answer<T> = { ok: boolean; why?: string; warning?: string; state?: T; added?: string };

// A page's state, live. A change shows at once, saves itself, and is put back with a plain reason if it
// cannot be kept. The page looks again now and then (a reminder may have come due meanwhile).
export function useKept<T>(page: 'subconscious' | 'scheduling' | 'memory') {
  const [state, setState] = useState<T | null>(null);
  const [notice, setNotice] = useState('');
  const [saved, setSaved] = useState(0);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const pending = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const say = useCallback((text: string) => {
    setNotice(text);
    if (timer.current) clearTimeout(timer.current);
    if (text) timer.current = setTimeout(() => setNotice(''), 7000);
  }, []);

  const look = useCallback(async () => {
    if (pending.current) return;
    try {
      const reply = await fetch(`/api/settings/${page}`, { cache: 'no-store' });
      if (!reply.ok) throw new Error();
      const fresh = (await reply.json()) as T;
      if (!pending.current) setState(fresh);
    } catch {
      setState((had) => {
        if (!had) say('It could not be read. Is Viventium running?');
        return had;
      });
    }
  }, [page, say]);

  useEffect(() => {
    look();
    const again = setInterval(look, 15000);
    return () => clearInterval(again);
  }, [look]);

  const save = useCallback(
    (change: Record<string, unknown>, now?: (s: T) => T) => {
      pending.current += 1;
      if (now) setState((had) => (had ? now(had) : had));
      const run = queue.current.then(async (): Promise<Answer<T>> => {
        let answer: Answer<T> = { ok: false };
        try {
          const reply = await fetch(`/api/settings/${page}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(change),
          });
          if (reply.ok) answer = await reply.json();
        } catch {
          /* said below */
        }
        pending.current -= 1;
        if (answer.ok && answer.state) {
          if (!pending.current) setState(answer.state);
          setSaved((n) => n + 1);
          return answer;
        }
        say([answer.why || 'That could not be saved.', answer.warning].filter(Boolean).join(' '));
        if (!pending.current) await look();
        return answer;
      });
      queue.current = run.catch(() => undefined);
      return run;
    },
    [page, say, look]
  );

  return { state, save, notice, saved };
}
