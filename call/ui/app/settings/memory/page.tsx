'use client';

import { useEffect, useRef, useState } from 'react';
import { BookOpen, Brain, ChevronRight, Clock, MessagesSquare, Search } from 'lucide-react';
import { Expand, Pane } from '../components/glass';
import { Sheet } from '../components/mind';
import { useKept } from '../lib/kept';
import './memory.css';

// Memory: what Viventium remembers about you, where it comes from, and putting it right. Every line can be corrected in
// place (click it, type, Enter) or forgotten (one click, and an undo); the same changes her voice tools make
// (brain/memory_tools.py), listed once. A change is kept in Viventium's own list and never edits your notes. Read and
// changed by settings/memory.py, through /api/settings/memory.

type Item = {
  id: string; // file:line, or row:number:digest for a message: the place a change names
  kind: string; // core, saved, summary, sensitive, original, history, conversation, correction (still kept: its Undo)
  change?: string; // (a correction still in force: its change, which its Undo takes back)
  path: string;
  source: string;
  date: string;
  text: string; // as Viventium reads it (what you forgot is not in it)
  mark?: string; // stands for the line as your file has it (never its words): what a change from this page names
};
type Standing = {
  id: string;
  section: string;
  text: string;
  mark: string;
  now?: string;
  corrected?: number;
};
type Conversation = {
  id: string;
  title: string;
  source: string;
  date: string;
  facts: string[];
  unreadable?: string;
};
type Change = {
  id: string;
  at: number;
  kind: 'correct' | 'forget';
  said: string;
  words: string;
  title: string;
  places: number;
  undone: boolean;
  where: '' | 'moved' | 'edited' | 'gone' | 'stale'; // a saved reference no longer names the same message
};
type Status = {
  life: boolean;
  index: { passages?: number };
  meaning: boolean;
  model: boolean;
  record: number;
  carried: number;
  core: string;
  core_due: boolean;
};
type Memory = {
  life: boolean;
  status: Status;
  standing: Standing[];
  conversations: Conversation[];
  changes: Change[];
  unreadable?: string; // (its list of changes cannot be read: nothing of memory is shown)
};
type Receipt = {
  id: string;
  places: number;
  still?: Item[]; // Other places that still hold the old words.
  from?: Item[]; // (a line of a summary forgotten: the messages it may have come from, to forget too)
};
type Answer = {
  ok: boolean;
  why?: string;
  warning?: string;
  state?: Memory;
  receipt?: Receipt;
  found?: Item[];
  look?: Item[]; // (an older conversation's forget: its messages first, nothing changed yet)
  all?: string; // (and the one reference that names all of them)
};
type Save = (change: Record<string, unknown>, now?: (s: Memory) => Memory) => Promise<Answer>;

const PAGE = 'memory';

// The line a change names, as this page showed it: a line edited since is refused, never the one there now.
const named = (item: { id: string; mark?: string }) => (item.mark ? { [item.id]: item.mark } : {});
// A place forgotten where the page shows no list of where else it is kept (a look's line, a place offered under a
// forget): none is asked for (finding one asks her helper to read every place found).
const offered = (item: Item) => ({
  what: item.text,
  passages: [item.id],
  shown: named(item),
  still: false,
});
// (a line of a summary forgotten: its words are the summary's, so the message it came from is offered too)
const FROM = 'That line is in the summary’s own words. It may have come from what was said:';

const day = (iso: string) =>
  iso
    ? new Date(`${iso}T12:00`).toLocaleDateString([], {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
      })
    : '';
const when = (at: number) =>
  new Date(at * 1000).toLocaleDateString([], { day: 'numeric', month: 'short' });
// What a change does, said plainly: Viventium's own list changes, your notes do not.
const KEPT = 'Viventium goes by this from now on. Your own notes are not changed.';
const GONE =
  "Forgotten here: Viventium won't bring it up again. Your notes and backups stay as they are, and a Worker you send can still read your notes.";

// One line of memory. Click its words to put them right. Forget applies to this line.
function Line({
  text,
  source,
  hint,
  title,
  change,
  forget,
  forgetFrom,
  undo,
  onGone,
}: {
  text: string;
  source?: string;
  hint?: string;
  title?: string;
  change?: (next: string) => Promise<Answer>;
  forget?: () => Promise<Answer>;
  forgetFrom?: (item: Item) => Promise<Answer>; // (a summary's line gone: forget a message it may have come from)
  undo: (id: string) => Promise<Answer>;
  onGone?: (answer: Answer) => void; // (a line of the page's own state leaves it: the page shows it gone, with its undo)
}) {
  const [editing, setEditing] = useState(false);
  const [shown, setShown] = useState(text);
  const [done, setDone] = useState<(Receipt & { words: string; warning?: string }) | null>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  useEffect(() => setShown(text), [text]);
  useEffect(() => {
    if (!editing || !field.current) return;
    field.current.focus();
    field.current.setSelectionRange(field.current.value.length, field.current.value.length);
  }, [editing]);
  const keep = async (next: string) => {
    setEditing(false);
    if (!change || !next.trim() || next.trim() === text.trim()) return setShown(text);
    setShown(next.trim());
    const answer = await change(next.trim());
    if (!answer.ok) return setShown(text);
    if (answer.receipt) setDone({ ...answer.receipt, words: KEPT, warning: answer.warning });
  };
  if (done?.words === GONE)
    return (
      <>
        <div className="vsm-line" data-gone="true">
          <span className="vs-hint">{GONE}</span>
          <button
            type="button"
            className="vs-missing"
            data-link="true"
            onClick={() => undo(done.id).then(() => setDone(null))}
          >
            Undo
          </button>
        </div>
        {done.warning && (
          <p className="vs-hint" role="status">
            {done.warning}
          </p>
        )}
        {forgetFrom && done.from && done.from.length > 0 && (
          <div className="vsm-still" data-from="true">
            <span className="vs-hint">{FROM}</span>
            {done.from.map((left) => (
              <Line
                key={left.id}
                text={left.text}
                source={left.source}
                forget={() => forgetFrom(left)}
                undo={undo}
              />
            ))}
          </div>
        )}
      </>
    );
  return (
    <div className="vsm-line" title={title}>
      <div className="vsm-words">
        {editing ? (
          <textarea
            ref={field}
            className="vs-input vsm-edit"
            defaultValue={shown}
            aria-label="What it should say"
            rows={Math.min(6, Math.ceil(shown.length / 70) + 1)}
            onBlur={(e) => keep(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                (e.target as HTMLTextAreaElement).blur();
              }
              if (e.key === 'Escape') {
                (e.target as HTMLTextAreaElement).value = text;
                setEditing(false);
              }
            }}
          />
        ) : change ? (
          <button
            type="button"
            className="vsm-text"
            onClick={() => setEditing(true)}
            aria-label={`Correct: ${shown}`}
          >
            {shown}
          </button>
        ) : (
          <span className="vsm-text" data-still="true">
            {shown}
          </span>
        )}
        {(source || hint || done) && (
          <span className="vsm-from">
            {source}
            {hint && <span className="vsm-hint">{hint}</span>}
            {done && (
              <span className="vsm-done">
                {done.words}
                {done.id && (
                  <button
                    type="button"
                    className="vs-missing"
                    data-link="true"
                    onClick={() => undo(done.id).then(() => setDone(null))}
                  >
                    Undo
                  </button>
                )}
              </span>
            )}
          </span>
        )}
        {done?.warning && (
          <p className="vs-hint" role="status">
            {done.warning}
          </p>
        )}
        {!!done?.still?.length && (
          <div className="vsm-still">
            <span className="vs-hint">Still kept in other words:</span>
            <ul>
              {done.still.map((item) => (
                <li key={item.id}>
                  {item.text} · {item.source}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      {forget && !editing && (
        <button
          type="button"
          className="vs-missing vsm-forget"
          data-link="true"
          onClick={async () => {
            const answer = await forget();
            if (!answer.ok) return;
            if (onGone) onGone(answer);
            else if (answer.receipt)
              setDone({ ...answer.receipt, words: GONE, warning: answer.warning });
          }}
        >
          Forget
        </button>
      )}
    </div>
  );
}

// How memory runs right now, each part on its own: one fact each, said once.
function HowItRuns({ status }: { status: Status }) {
  const facts: { icon: typeof Brain; words: string; low?: boolean }[] = [
    status.life
      ? { icon: BookOpen, words: 'Reads your Life folder, where it is, and never edits your notes' }
      : { icon: BookOpen, words: 'No Life folder yet: only the conversation it is in', low: true },
    status.meaning
      ? {
          icon: Search,
          words: `Finds things by meaning, not only by words (${(status.index.passages ?? 0).toLocaleString()} passages)`,
        }
      : {
          icon: Search,
          words: status.model
            ? 'Finds things by words; by meaning once its index is built'
            : 'Finds things by words only: its meaning model is not running',
          low: true,
        },
    {
      icon: MessagesSquare,
      words: `Each new conversation picks up from the last ${status.carried} messages`,
    },
    status.core
      ? {
          icon: Brain,
          words: status.core_due
            ? 'What it keeps in mind is being brought up to date with your changes'
            : `What it keeps in mind was last brought up to date ${day(status.core.slice(0, 10))}`,
        }
      : { icon: Brain, words: 'What it keeps in mind is written after the first conversations' },
  ];
  return (
    <ul className="vsm-facts">
      {facts.map(({ icon: Icon, words, low }) => (
        <li key={words} data-low={low || undefined}>
          <Icon strokeWidth={1.7} aria-hidden="true" />
          {words}
        </li>
      ))}
    </ul>
  );
}

function Look({ save, undo }: { save: Save; undo: (id: string) => Promise<Answer> }) {
  const [about, setAbout] = useState('');
  const [found, setFound] = useState<Item[] | null>(null);
  const [why, setWhy] = useState(''); // (a look that could not be made says so; never "nothing holds those words")
  const [looked, setLooked] = useState('');
  const look = async (words = about) => {
    if (!words.trim()) return setFound(null);
    const reply = await fetch('/api/settings/memory', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ look: words.trim() }),
    }).catch(() => null);
    const answer = (reply?.ok ? await reply.json() : { ok: false }) as Answer;
    setWhy(answer.ok ? answer.warning || '' : answer.why || 'The look could not be made just now.');
    setFound(answer.ok ? (answer.found ?? []) : []);
    setLooked(words.trim());
  };
  return (
    <>
      <form
        className="vsm-look"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          look();
        }}
      >
        <Search aria-hidden="true" strokeWidth={1.7} />
        <input
          className="vs-input"
          type="search"
          value={about}
          placeholder="Someone, a place, a plan…"
          aria-label="Look for something it remembers"
          onChange={(e) => setAbout(e.target.value)}
        />
      </form>
      {found && (
        <div className="vsm-found" aria-live="polite">
          {why && (
            <p className="vsx-empty" role="alert">
              {why}
            </p>
          )}
          {found.length ? (
            found.map((item) => (
              <Line
                key={item.id}
                text={item.text}
                source={[item.source, item.kind === 'summary' ? '' : day(item.date)]
                  .filter(Boolean)
                  .join(', ')}
                title={item.path || undefined}
                change={(next) =>
                  save({
                    correct: { old: item.text, new: next, passages: [item.id], shown: named(item) },
                  })
                }
                forget={() => save({ forget: { ...offered(item) } })}
                forgetFrom={(left) => save({ forget: { ...offered(left) } })}
                undo={(id) => undo(id).then((a) => (look(looked), a))}
              />
            ))
          ) : !why ? (
            <p className="vsx-empty">Nothing it keeps holds those words.</p>
          ) : null}
        </div>
      )}
    </>
  );
}

function Talk({
  talk,
  save,
  onGone,
}: {
  talk: Conversation;
  save: Save;
  onGone: (answer: Answer) => void;
}) {
  const [open, setOpen] = useState(false);
  // An older summary cannot say which messages it was written from: its forget first shows them (the conversation's
  // own messages, as Viventium has them), then one click forgets all of them. Nothing is changed before that click.
  const [look, setLook] = useState<{ items: Item[]; all: string } | null>(null);
  const forget = async (passages?: string[]) => {
    const answer = await save({ forget: { what: talk.id, ...(passages ? { passages } : {}) } });
    if (answer.ok) {
      setLook(null);
      onGone(answer);
    } else if (answer.look) setLook({ items: answer.look, all: answer.all ?? '' });
  };
  // Her own summaries are forgotten in one click; an older one shows its messages first (a look: nothing changes).
  const start = async () => {
    const reply = await fetch('/api/settings/memory', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ older: talk.id }),
    }).catch(() => null);
    const found = (reply?.ok ? await reply.json() : null) as Answer | null;
    if (found?.ok && found.look?.length)
      return setLook({ items: found.look, all: found.all ?? '' });
    return forget();
  };
  return (
    <div className="vsx-row vsm-talk">
      <button
        type="button"
        className="vsm-talk-top"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span className="vsx-what">
          <b className="vs-name">{talk.title}</b>
          <span className="vs-sub">
            {talk.source.replace(/^summary of a /, '')}, {day(talk.date)}
          </span>
          {talk.unreadable && <span className="vs-sub">This summary cannot be read.</span>}
        </span>
        <ChevronRight className="vsm-chev" aria-hidden="true" />
      </button>
      <Expand open={open}>
        <div className="vsm-talk-more">
          {talk.unreadable ? (
            <p className="vs-hint" role="status">
              This summary cannot be read: {talk.unreadable}. Other memory is still available.
            </p>
          ) : talk.facts.length ? (
            <ul className="vsm-said">
              {talk.facts.map((fact) => (
                <li key={fact}>{fact}</li>
              ))}
            </ul>
          ) : (
            <p className="vs-hint">Nothing about you was said in it.</p>
          )}
          {look ? (
            <div className="vsm-look-of" aria-live="polite">
              <span className="vs-hint">
                Its summary does not say which messages it was written from. These are that
                conversation’s messages, as Viventium has them:
              </span>
              <ul className="vsm-said">
                {look.items.map((item) => (
                  <li key={item.id}>
                    {item.text}
                    <span className="vsm-from">{item.source}</span>
                  </li>
                ))}
              </ul>
              <button
                type="button"
                className="vs-missing"
                data-link="true"
                onClick={() => forget([look.all])}
              >
                Forget all {look.items.length}
              </button>
            </div>
          ) : (
            <button type="button" className="vs-missing" data-link="true" onClick={start}>
              Forget this conversation
            </button>
          )}
        </div>
      </Expand>
    </div>
  );
}

// What was just forgotten, where it was (its row has left the page's state): one line each, with its undo, and what
// still bears on it in other words, until it is undone or the page is opened again.
type Gone = {
  id: string;
  words: string;
  where: 'line' | 'talk';
  still: Item[];
  from: Item[];
  warning?: string;
};
function Forgotten({
  gone,
  save,
  undo,
}: {
  gone: Gone[];
  save: Save;
  undo: (id: string) => Promise<unknown>;
}) {
  return (
    <>
      {gone.map((item) => (
        <div key={item.id} className="vsm-gone">
          <div className={item.where === 'talk' ? 'vsx-row vsm-talk' : 'vsm-line'} data-gone="true">
            <span className="vs-hint">
              {item.words}: {GONE}
            </span>
            <button
              type="button"
              className="vs-missing"
              data-link="true"
              onClick={() => undo(item.id)}
            >
              Undo
            </button>
          </div>
          {item.warning && (
            <p className="vs-hint" role="status">
              {item.warning}
            </p>
          )}
          {item.from.length > 0 && (
            <div className="vsm-still" data-from="true">
              <span className="vs-hint">{FROM}</span>
              {item.from.map((left) => (
                <Line
                  key={left.id}
                  text={left.text}
                  source={left.source}
                  forget={() => save({ forget: { ...offered(left) } })}
                  undo={(id) => save({ undo: id })}
                />
              ))}
            </div>
          )}
          {item.still.length > 0 && (
            <div className="vsm-still">
              <span className="vs-hint">Still kept in other words:</span>
              {item.still.map((left) =>
                left.kind === 'correction' ? (
                  <StillCorrection key={left.id} item={left} undo={(id) => save({ undo: id })} />
                ) : (
                  <Line
                    key={left.id}
                    text={left.text}
                    source={left.source}
                    title={left.path || undefined}
                    forget={() => save({ forget: { ...offered(left) } })}
                    undo={(id) => save({ undo: id })}
                  />
                )
              )}
            </div>
          )}
        </div>
      ))}
    </>
  );
}

// A correction Viventium still goes by, in its own words: she is told it in every conversation, so a fact you forgot
// that it holds is still kept there. Its Undo (the same as in the changes) stops that.
function StillCorrection({ item, undo }: { item: Item; undo: (id: string) => Promise<Answer> }) {
  const [undone, setUndone] = useState(false);
  return (
    <div className="vsm-line" data-gone={undone || undefined}>
      <div className="vsm-words">
        <span className="vsm-text" data-still="true">
          {item.text}
        </span>
        <span className="vsm-from">
          {undone ? 'Undone: Viventium no longer goes by it.' : item.source}
        </span>
      </div>
      {!undone && (
        <button
          type="button"
          className="vs-missing vsm-forget"
          data-link="true"
          onClick={async () => {
            const answer = await undo(item.change ?? '');
            if (answer.ok) setUndone(true);
          }}
        >
          Undo
        </button>
      )}
    </div>
  );
}

function Changed({ change, undo }: { change: Change; undo: (id: string) => Promise<Answer> }) {
  const words =
    change.kind === 'correct' ? (
      <>
        Corrected: <q>{change.said}</q>
        {change.words && (
          <span className="vs-hint">
            {' '}
            instead of <q>{change.words}</q>
          </span>
        )}
      </>
    ) : change.title ? (
      <>
        Forgot the conversation <q>{change.title}</q>
      </>
    ) : (
      <>
        Forgot <q>{change.said}</q>
      </>
    );
  return (
    <tr data-undone={change.undone || undefined}>
      <td>{when(change.at)}</td>
      <td>
        {words}
        {change.undone && <span className="vs-hint"> · Undone</span>}
        {!change.undone && change.where === 'moved' && (
          <span className="vs-hint">
            {' '}
            · The line it named was edited since; it now goes by its words in that note.
          </span>
        )}
        {!change.undone && change.where === 'edited' && (
          <span className="vs-hint">
            {' '}
            · The line it named was edited since and shows again as it is now: forget or correct it
            once more.
          </span>
        )}
        {!change.undone && change.where === 'gone' && (
          <span className="vs-hint"> · The line it named is no longer in your notes.</span>
        )}
        {!change.undone && change.where === 'stale' && (
          <span className="vs-hint">
            {' '}
            · The conversation record changed. This stale reference does not apply to a different
            message.
          </span>
        )}
      </td>
      <td>
        {!change.undone && (
          <button
            type="button"
            className="vs-missing"
            data-link="true"
            onClick={() => undo(change.id)}
          >
            Undo
          </button>
        )}
      </td>
    </tr>
  );
}

export default function MemoryPage() {
  const { state: kept, save: keep, notice, saved } = useKept<Memory>(PAGE);
  const state = kept as Memory | null;
  const save = keep as unknown as Save;
  const undo = (id: string) => save({ undo: id });
  const [gone, setGone] = useState<Gone[]>([]);
  const forgot = (where: Gone['where'], words: string) => (answer: Answer) =>
    setGone((had) => [
      {
        id: answer.receipt?.id ?? '',
        words,
        where,
        still: answer.receipt?.still ?? [],
        from: answer.receipt?.from ?? [],
        warning: answer.warning,
      },
      ...had,
    ]);
  const unforget = (id: string) =>
    undo(id).then((answer) => answer.ok && setGone((had) => had.filter((g) => g.id !== id)));
  const sections = (state?.standing ?? []).reduce<Record<string, Standing[]>>((all, line) => {
    (all[line.section || 'Kept in mind'] ??= []).push(line);
    return all;
  }, {});
  return (
    <Sheet
      title="Memory"
      lede="What Viventium remembers about you, where it comes from, and how to put it right. Or just say it: “that’s wrong, my sister lives in Porto now”."
      notice={notice}
      saved={saved}
    >
      {state && (
        <>
          <Pane
            title="Kept in mind"
            aside={
              <span className="vs-hint">In every conversation. Click a line to correct it.</span>
            }
          >
            <Forgotten gone={gone.filter((g) => g.where === 'line')} save={save} undo={unforget} />
            {state.standing.length ? (
              Object.entries(sections).map(([section, lines]) => (
                <div key={section} className="vsm-group">
                  <div className="vs-grp-head">
                    <span className="vs-grp-name">{section}</span>
                    <span className="vs-grp-line" />
                  </div>
                  {lines.map((line) => (
                    <Line
                      key={line.id}
                      text={line.now ?? line.text}
                      hint={
                        line.corrected ? `Corrected by you, ${when(line.corrected)}` : undefined
                      }
                      change={(next) =>
                        save({
                          correct: {
                            old: line.now ?? line.text,
                            new: next,
                            passages: [line.id],
                            shown: named(line),
                          },
                        })
                      }
                      forget={() =>
                        save({
                          forget: { what: line.text, passages: [line.id], shown: named(line) },
                        })
                      }
                      undo={undo}
                      onGone={forgot('line', `“${line.now ?? line.text}”`)}
                    />
                  ))}
                </div>
              ))
            ) : gone.some((g) => g.where === 'line') ? null : state.unreadable ? (
              <p className="vsx-empty" role="alert">
                Nothing it remembers can be shown right now: {state.unreadable}. It shows nothing
                rather than something you asked it to forget.
              </p>
            ) : (
              <p className="vsx-empty">
                {state.life
                  ? 'Nothing yet. It learns who you are from your Life folder and your conversations, and this fills in after the first ones.'
                  : 'There is no Life folder yet, so it remembers only the conversation it is in.'}
              </p>
            )}
            <HowItRuns status={state.status} />
          </Pane>
          {state.life && (
            <Pane
              title="Look for anything"
              aside={<span className="vs-hint">Everything it keeps that holds those words.</span>}
            >
              <Look save={save} undo={undo} />
            </Pane>
          )}
          {(state.conversations.length > 0 || gone.some((g) => g.where === 'talk')) && (
            <Pane
              title="Conversations"
              aside={<span className="vs-hint">The latest it remembers.</span>}
            >
              <div className="vsx-rows">
                <Forgotten
                  gone={gone.filter((g) => g.where === 'talk')}
                  save={save}
                  undo={unforget}
                />
                {state.conversations.map((talk) => (
                  <Talk key={talk.id} talk={talk} save={save} onGone={forgot('talk', talk.title)} />
                ))}
              </div>
            </Pane>
          )}
          {state.changes.length > 0 && (
            <Pane title="Changes" aside={<Clock className="vsm-aside-icon" aria-hidden="true" />}>
              <table className="vsx-hist vsm-changes">
                <tbody>
                  {state.changes.map((change) => (
                    <Changed key={change.id} change={change} undo={undo} />
                  ))}
                </tbody>
              </table>
            </Pane>
          )}
        </>
      )}
    </Sheet>
  );
}
