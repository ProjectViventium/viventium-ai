import { NextResponse } from 'next/server';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import { ROOT, allowed, headers } from '../settings/carry';

// What her brain did, turn by turn, read only from what Light records: logs/turns.jsonl (each turn's hearing, the
// one-word gate, memory, the mind, her voice, Workers, heartbeats) and her Feelings' trail. Nothing is made up: a part
// switched off is never drawn as running (the Live view of the Subconscious page).
export const dynamic = 'force-dynamic';

// Where Light keeps them: its state (VX_STATE, as the rest of Light reads it) and logs/ in its root (VX_LOGS: a
// test's own folder).
const STATE = process.env.VX_STATE ?? path.join(ROOT, 'state');
const LOGS = process.env.VX_LOGS ?? path.join(ROOT, 'logs');

type Step = {
  region: string; // ears | gate | memory | feelings | mind | voice | hands | clock | subconscious | cortex:<id>
  at: number; // seconds since the epoch
  took?: number; // milliseconds, when it was measured
  what: string;
  detail?: string; // metadata expanded within its existing turn row
  state: 'ok' | 'act' | 'quiet' | 'warn' | 'error';
  band?: string; // a Feelings step: the band that moved (the page colours it with the band's own colour)
  full?: string; // what it said, whole as recorded, when `what` shows only its start (a cortex's thought)
  where?: string; // what it ran on, as recorded (a cortex, the coordinator)
  late?: boolean; // arrived after a later turn in the same room had begun
};
type Trace = {
  id: string;
  channel: 'call' | 'typed' | 'telegram' | 'unknown';
  start: number;
  end: number;
  words: string; // what they said, or what woke her (a heartbeat, a reminder, a Worker's result)
  by: 'you' | 'her'; // who began it: their words, or something that woke her
  kind: 'words' | 'beat' | 'reminder' | 'greeting' | 'worker' | 'unknown';
  reply: string;
  steps: Step[];
};

type Row = { t: number; kind: string; room?: string; [k: string]: unknown };
type Felt = { t: number; what: string; band: string };

const s = (v: unknown, n = 140) =>
  String(v ?? '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, n);
const n = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : undefined);
const ms = (v: unknown) => (n(v) !== undefined ? Math.round(n(v)! * 1000) : undefined);
const cap = (v: string) => v.charAt(0).toUpperCase() + v.slice(1);

const TAIL = 3 * 1024 * 1024; // (the log only grows: read its end, a few thousand lines, not all of it)

async function tail(file: string, lines: number): Promise<Row[]> {
  try {
    const handle = await fs.open(file, 'r');
    let text = '';
    try {
      const { size } = await handle.stat();
      const start = Math.max(0, size - TAIL);
      const buffer = Buffer.alloc(size - start);
      await handle.read(buffer, 0, buffer.length, start);
      text = buffer.toString('utf8');
      if (start > 0) text = text.slice(text.indexOf('\n') + 1); // (the first line read may be cut)
    } finally {
      await handle.close();
    }
    const out: Row[] = [];
    for (const line of text.split('\n').slice(-lines)) {
      try {
        const row = JSON.parse(line);
        if (row && typeof row.t === 'number' && typeof row.kind === 'string') out.push(row);
      } catch {
        /* (a line still being written) */
      }
    }
    return out;
  } catch {
    return [];
  }
}

async function feelings(): Promise<Felt[]> {
  try {
    const state = JSON.parse(
      await fs.readFile(path.join(STATE, 'feelings', 'feelings.json'), 'utf8')
    );
    return (Array.isArray(state.trail) ? state.trail : [])
      .filter((e: Record<string, unknown>) => e.sourceType !== 'manual')
      .map((e: Record<string, unknown>) => ({
        t: Date.parse(String(e.timestamp)) / 1000,
        band: s(e.band, 20),
        what: `${cap(s(e.band, 20))} ${e.direction === 'down' ? 'down' : 'up'}${e.strength ? `, ${s(e.strength, 12)}` : ''}`,
      }))
      .filter((e: Felt) => Number.isFinite(e.t));
  } catch {
    return [];
  }
}

// (by the turn's own channel where it says one, since one room can be typed and spoken; older rows by their room)
function channel(room: string, said?: unknown): Trace['channel'] {
  if (said === 'telegram' || said === 'typed' || said === 'call') return said;
  return room === 'telegram' ? 'telegram' : room.startsWith('typed_chat_room') ? 'typed' : 'call';
}

function worker(r: Row): Step {
  const event = s(r.event, 20);
  const what: Record<string, string> = {
    started: `Worker started${r.harness ? ` (${s(r.harness, 20)})` : ''}`,
    done: `Worker done${r.ran_on ? ` on ${s(r.ran_on, 30)}` : ''}`,
    fallback: `switched to its backup${r.to ? `: ${s(r.to, 30)}` : ''}`,
    failed: 'Worker failed',
    cancelled: 'Worker stopped',
    steered: 'Worker told more',
    resumed: 'Worker resumed',
  };
  const state = event === 'failed' ? 'error' : event === 'fallback' ? 'warn' : 'ok';
  return { region: 'hands', at: r.t, what: what[event] ?? `Worker ${event}`, state };
}

// A cortex's own region: the two every turn has are drawn as Feelings and memory; the others by their own id.
const EVERY_TURN: Record<string, string> = {
  'emotional-reaction': 'feelings',
  'deep-memory': 'memory',
};
const named = (id: unknown) => cap(s(id, 40).replace(/-/g, ' '));

// What the Subconscious did after her answer (brain/rounds.py, Queen._continue): one step each.
function subconscious(r: Row): Step | null {
  const how = s(r.how, 40);
  switch (r.event) {
    case 'round':
      return {
        region: 'subconscious',
        at: r.t,
        what: 'began a round after the answer',
        state: 'ok',
      };
    case 'coordinator': {
      const picked = Array.isArray(r.picked) ? r.picked.map(named) : [];
      const where = s(r.where, 40);
      return {
        region: 'subconscious',
        at: r.t,
        took: n(r.ms),
        what: picked.length
          ? `picked ${picked.join(', ')}`
          : how && how !== 'ok'
            ? `could not decide (${how.replace(/_/g, ' ')})`
            : 'picked none',
        state: picked.length ? 'act' : how && how !== 'ok' ? 'warn' : 'quiet',
        ...(where ? { where } : {}),
      };
    }
    case 'cortex': {
      const id = s(r.id, 40);
      const state = s(r.state, 20);
      const words = s(r.words, 90);
      const whole = s(r.words, 600); // (its thought as recorded: shown whole when its card is opened)
      const why = s(r.why, 120);
      const where = s(r.where, 40);
      return {
        region: EVERY_TURN[id] ?? `cortex:${id}`,
        at: r.t,
        took: n(r.ms),
        what:
          state === 'thought'
            ? `a thought${words ? `: “${words}”` : ''}`
            : state === 'feelings'
              ? 'asked her Feelings to react'
              : state === 'failed'
                ? `could not run${how ? ` (${how.replace(/_/g, ' ')})` : why ? ` (${why})` : ''}`
                : `nothing to add${why ? ` (${why})` : ''}`,
        state:
          state === 'thought'
            ? 'act'
            : state === 'failed'
              ? 'warn'
              : state === 'nothing'
                ? 'quiet'
                : 'ok',
        ...(state === 'thought' && whole.length > words.length ? { full: whole } : {}),
        ...(where ? { where } : {}),
      };
    }
    case 'late':
      return {
        region: 'subconscious',
        at: r.t,
        what: 'the linked thoughts went without the slow ones',
        state: 'warn',
      };
    case 'surfaced':
      return {
        region: 'mind',
        at: r.t,
        what:
          how === 'said'
            ? 'continued its thought to you'
            : how === 'rode'
              ? 'kept its thoughts for your next words'
              : how === 'no answer'
                ? 'its one word gave no answer: kept its thoughts'
                : 'kept its thoughts in mind',
        state: how === 'said' ? 'act' : how === 'no answer' ? 'warn' : 'quiet',
      };
    case 'failed':
      return { region: 'subconscious', at: r.t, what: 'the round failed', state: 'error' };
    default:
      return null;
  }
}

function traces(rows: Row[], felt: Felt[]): Trace[] {
  const out: Trace[] = [];
  const turns = new Map<string, Trace>();
  const records = new Map<Row, Trace>();
  const replies = new Map<string, string>();
  const nextTurn = new Map<Trace, number>();
  const said = new Map<string, string>(); // a reply's own speech id, never the room's latest voice
  const gates = new Map<string, Trace>(); // a beat whose one word is recorded, waiting for what came of it
  const key = (room: string, id: unknown) => `${room}:${String(id)}`;
  const begin = (room: string, r: Row, words: string, kind: Trace['kind']) => {
    const id = key(room, r.id || `${kind}:${r.t}`);
    const existing = turns.get(id);
    if (existing) {
      records.set(r, existing);
      return existing;
    }
    const by = kind === 'words' ? 'you' : 'her';
    const trace: Trace = {
      id,
      channel: channel(room, r.channel),
      start: r.t,
      end: r.t,
      words,
      by,
      kind,
      reply: '',
      steps: [],
    };
    turns.set(id, trace);
    records.set(r, trace);
    out.push(trace);
    return trace;
  };
  // Index identities first: a reply or a round may finish after another question, or be recorded before its source.
  for (const r of rows) {
    const room = String(r.room ?? '');
    if (!room) continue;
    if (r.kind === 'turn' && r.role === 'user') begin(room, r, s(r.text, 400), 'words');
    if (r.kind === 'reply_source' && r.speech && r.turn_id)
      replies.set(key(room, r.speech), String(r.turn_id));
  }
  const rooms = new Map<string, Set<Trace>>();
  for (const r of rows) {
    if (r.kind !== 'turn' || r.role !== 'user' || !r.room) continue;
    const list = rooms.get(r.room) ?? new Set<Trace>();
    list.add(records.get(r)!);
    rooms.set(r.room, list);
  }
  for (const room of rooms.values()) {
    const list = [...room].sort((a, b) => a.start - b.start);
    list.slice(0, -1).forEach((trace, i) => nextTurn.set(trace, list[i + 1].start));
  }
  const cause = (r: Row): Trace | undefined => {
    const room = String(r.room ?? '');
    const id = r.turn_id || (r.speech && replies.get(key(room, r.speech)));
    return records.get(r) ?? (id ? turns.get(key(room, id)) : undefined);
  };
  const unknown = (r: Row): Trace => {
    const room = String(r.room ?? '');
    const id = key(
      room,
      `unknown:${String(r.turn_id || r.speech || (r.kind === 'turn' && r.id) || '')}`
    );
    let trace = turns.get(id);
    if (!trace) {
      trace = {
        id,
        channel: room === 'feelings' ? 'unknown' : channel(room, r.channel),
        start: r.t,
        end: r.t,
        words: 'Events with no recorded turn',
        by: 'her',
        kind: 'unknown',
        reply: '',
        steps: [],
      };
      turns.set(id, trace);
      out.push(trace);
    }
    return trace;
  };
  const add = (r: Row, step: Step) => {
    const trace = cause(r) ?? unknown(r);
    if (r.t >= (nextTurn.get(trace) ?? Infinity)) step.late = true;
    trace.steps.push(step);
    trace.start = Math.min(trace.start, step.at);
    trace.end = Math.max(trace.end, step.at);
  };
  for (const r of rows) {
    const room = String(r.room ?? '');
    if (!room) continue;
    const m = (r.metrics ?? {}) as Record<string, unknown>;
    switch (r.kind) {
      // What begins a turn: their words, a heartbeat, a reminder, the start of a call, a Worker's result.
      case 'turn':
        if (r.role === 'user') {
          begin(room, r, s(r.text, 400), 'words');
          add(r, {
            region: 'ears',
            at: r.t,
            took: ms(m.transcription_delay),
            what:
              room === 'telegram'
                ? 'read your message'
                : channel(room, r.channel) === 'typed'
                  ? 'read what you typed'
                  : 'heard you',
            state: 'ok',
          });
        } else if (r.role === 'assistant') {
          const trace = cause(r) ?? unknown(r);
          trace.reply = s(r.text, 400);
          trace.start = Math.min(trace.start, r.t);
          trace.end = Math.max(trace.end, r.t);
          const where = channel(room, r.channel);
          const spoke = n(m.started_speaking_at);
          const first = n(m.llm_node_ttft);
          if (first !== undefined) {
            // TTFT is a duration, not a timestamp. Use the actual record time, never invent an earlier mind event.
            const meta = (m.llm_metadata ?? {}) as Record<string, unknown>;
            const model = s(meta.model_name, 40);
            add(r, {
              region: 'mind',
              at: r.t,
              took: Math.round(first * 1000),
              what: model ? `answer recorded (${model})` : 'answer recorded',
              state: 'ok',
            });
          }
          if (where === 'call' && spoke !== undefined)
            add(r, {
              region: 'voice',
              at: spoke,
              took: ms(m.tts_node_ttfb),
              what: said.get(key(room, r.speech)) || s(r.text, 90),
              state: 'ok',
            });
          else if (where === 'typed')
            add(r, { region: 'voice', at: r.t, what: 'wrote back', state: 'ok' });
          said.delete(key(room, r.speech));
        }
        break;
      case 'beat': {
        // Continuous awareness (core/routines.beat) records two kinds of row. On this Mac's model it first asks its
        // one word (`choice`: quiet, speak, act; "no answer" when the model gave none). Every beat then records what
        // came of it (`how`, with `why`), at its end. On Hybrid there is no one word: the beat is a turn of her own
        // mind, and only that last row is written (read as "its one word gave no answer", 25 times out of 25).
        const how = s(r.how, 20);
        const beat = r.beat_id ? key(room, r.beat_id) : undefined;
        if (!how) {
          const trace = begin(room, r, 'Continuous awareness', 'beat');
          if (beat) gates.set(beat, trace);
          const choice = s(r.choice, 40);
          add(r, {
            region: 'clock',
            at: r.t,
            what: ['quiet', 'speak', 'act'].includes(choice)
              ? `its one word: ${choice}`
              : choice === 'no answer'
                ? 'its one word gave no answer'
                : 'its one word was none of quiet, speak or act',
            state:
              choice === 'quiet'
                ? 'quiet'
                : choice === 'speak' || choice === 'act'
                  ? 'act'
                  : 'error',
          });
          break;
        }
        const gate = beat ? gates.get(beat) : undefined;
        if (beat) gates.delete(beat);
        const asked = gate !== undefined;
        if (asked) records.set(r, gate);
        if (!asked) {
          begin(room, r, 'Continuous awareness', 'beat');
          add(r, { region: 'clock', at: r.t, what: 'woke the mind', state: 'ok' });
        }
        const why = s(r.why, 160);
        const ended: Record<string, [string, Step['state']]> = {
          quiet: [`stayed quiet${why ? `: ${why}` : ''}`, 'quiet'],
          told: ['reached out', 'act'],
          work: [`started work${why ? `: ${why}` : ''}`, 'act'],
          act: [`chose to act; nothing started${why ? ` (${why})` : ''}`, 'quiet'],
          call: ['passed: a call was on', 'quiet'],
          passed: [`passed${why ? `: ${why}` : ''}`, 'quiet'],
          failed: [`failed${why ? `: ${why}` : ''}`, 'error'],
        };
        const [what, state] = ended[how] ?? [`ended (${how})`, 'ok'];
        // (her own turn decided it, so it is her mind's; after its one word, a quiet or failed beat stays the beat's)
        const region = !asked || how === 'told' ? 'mind' : how === 'work' ? 'hands' : 'clock';
        add(r, { region, at: r.t, what, state });
        break;
      }
      case 'woken':
        begin(room, r, 'A reminder came due', 'reminder');
        add(r, { region: 'clock', at: r.t, what: 'a reminder came due', state: 'act' });
        break;
      case 'greeting':
        begin(room, r, 'A call begins', 'greeting');
        add(r, {
          region: 'mind',
          at: r.t,
          what: r.ahead
            ? 'greeting written ahead'
            : r.said === false
              ? 'listened: too late to greet'
              : 'greeting written now',
          state: r.said === false ? 'quiet' : 'ok',
        });
        break;
      case 'worker':
        if (r.event === 'done' || r.event === 'failed')
          begin(room, r, r.event === 'done' ? 'A Worker finished' : 'A Worker failed', 'worker');
        add(r, worker(r));
        break;
      // What happens inside a turn.
      case 'eot':
        add(r, {
          region: 'ears',
          at: r.t,
          took: ms(r.delay),
          what: 'you finished speaking',
          state: 'ok',
        });
        break;
      case 'hands':
        if (r.started)
          add(r, {
            region: 'hands',
            at: r.t,
            took: ms(r.waited),
            what: 'handed off at once',
            state: 'act',
          });
        else {
          const said = s(r.said, 20) || 'no answer';
          add(r, {
            region: 'gate',
            at: r.t,
            what: `one word: ${said}`,
            state: said === 'act' ? 'act' : said === 'no answer' ? 'warn' : 'ok',
          });
        }
        break;
      case 'wing':
        add(r, {
          region: 'gate',
          at: r.t,
          what: r.spoken_to === 'no' ? 'not spoken to' : 'spoken to',
          state: r.spoken_to === 'no' ? 'quiet' : 'act',
        });
        break;
      case 'listened':
        add(r, { region: 'mind', at: r.t, what: 'listened, said nothing', state: 'quiet' });
        break;
      case 'mind_attempt': {
        const primary = (r.primary ?? {}) as Record<string, unknown>;
        const backup = (r.backup ?? {}) as Record<string, unknown>;
        const answered = (r.answered_by ?? {}) as Record<string, unknown>;
        const error = (primary.error ?? {}) as Record<string, unknown>;
        const first = n(primary.first_token_seconds);
        const outcome = s(primary.outcome, 30);
        const details = [
          answered.model ? `Answered by ${s(answered.model, 60)}` : 'No answer recorded',
          `primary ${s(primary.model, 60)}: ${outcome === 'timeout' ? `timed out at ${n(primary.wait_seconds) ?? '?'} s` : outcome === 'provider_error' ? `${s(error.class, 40)}${n(error.status) ? ` (${n(error.status)})` : ''}` : first !== undefined ? `first token ${first.toFixed(2)} s` : outcome.replace(/_/g, ' ')}`,
          n(primary.prompt_tokens) !== undefined
            ? `${n(primary.prompt_tokens)} prompt tokens, ${Math.round((n(primary.cached_share) ?? 0) * 100)}% cached`
            : `${n(r.context_chars) ?? '?'} context characters`,
        ];
        if (backup.outcome && backup.outcome !== 'not_attempted') {
          details.push(
            `backup ${s(backup.model, 60)}: ${s(backup.readiness, 30).replace(/_/g, ' ')}`
          );
          if (n(backup.load_seconds_upper_bound) !== undefined)
            details.push(
              `load observed within ${n(backup.load_seconds_upper_bound)!.toFixed(2)} s`
            );
          if (n(backup.first_token_seconds) !== undefined)
            details.push(`backup first token ${n(backup.first_token_seconds)!.toFixed(2)} s`);
        }
        add(r, {
          region: 'mind',
          at: r.t,
          what: details.slice(0, 2).join('; '),
          detail: details.join('; '),
          state: outcome === 'timeout' || outcome === 'provider_error' ? 'warn' : 'ok',
        });
        break;
      }
      case 'deep_memory': {
        const found = Array.isArray(r.found) ? r.found.length : Number(r.found) || 0;
        add(r, {
          region: 'memory',
          at: r.t,
          took: n(r.ms),
          what: found
            ? `Deep memory found ${found}${r.say ? ', for the mind' : ''}`
            : 'Deep memory: nothing new',
          state: found ? (r.say ? 'act' : 'ok') : 'quiet',
        });
        break;
      }
      case 'remembered': {
        const files = Array.isArray(r.files) ? r.files.length : 0;
        add(r, {
          region: 'memory',
          at: r.t,
          what: files ? `remembered ${files} ${files === 1 ? 'note' : 'notes'}` : 'remembered',
          state: 'ok',
        });
        break;
      }
      case 'tool': {
        const name = s(r.name, 30);
        const steps = cause(r)?.steps ?? [];
        if (
          name === 'hand_off_to' &&
          steps.some((x) => x.what === 'handed off at once' && r.t - x.at < 5)
        )
          break; // (the hand-off made in the gate's place, already shown)
        const region = ['hand_off_to', 'update_worker', 'cancel_job'].includes(name)
          ? 'hands'
          : ['recall', 'read_file'].includes(name)
            ? 'memory'
            : 'mind';
        add(r, { region, at: r.t, what: name.replace(/_/g, ' '), state: 'act' });
        break;
      }
      case 'spoken': // (her voice's step comes with the reply's record: when she began to speak)
        if (r.speech) said.set(key(room, r.speech), s(r.text, 90));
        break;
      case 'sent':
        add(r, {
          region: 'voice',
          at: r.t,
          what: r.voice ? 'sent a voice note' : 'sent a message',
          state: 'ok',
        });
        break;
      case 'shown':
        add(r, { region: 'voice', at: r.t, what: 'showed a link', state: 'ok' });
        break;
      case 'subconscious': {
        const step = subconscious(r);
        if (step) add(r, step);
        break;
      }
    }
  }
  // Older Feelings trails have no source identity. Keep the real change, without guessing a turn from its time.
  for (const f of felt) {
    add(
      { t: f.t, kind: 'feeling', room: 'feelings' },
      { region: 'feelings', at: f.t, what: f.what, state: 'ok', band: f.band }
    );
  }
  for (const trace of out) trace.steps.sort((a, b) => a.at - b.at);
  // A real reply needs no measured step. Keep traces by latest activity, including a late event on an old turn.
  return out
    .filter((t) => t.steps.length || t.reply)
    .sort((a, b) => a.end - b.end || a.start - b.start);
}

export async function GET(req: Request) {
  if (!allowed(req, false)) return new NextResponse('Not from here.', { status: 403 });
  const rows = await tail(path.join(LOGS, 'turns.jsonl'), 6000);
  const all = traces(rows, await feelings());
  return NextResponse.json({ traces: all.slice(-40), now: Date.now() / 1000 }, { headers });
}
