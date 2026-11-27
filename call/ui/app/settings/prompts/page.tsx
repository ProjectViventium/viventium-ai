'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Pane } from '../components/glass';
import { Open, Sheet } from '../components/mind';
import './prompts.css';

// Prompts: every text Viventium is given that the prompt ledger keeps as a file (brain/prompts/ledger.json), by
// category, with the one in force for each: as shipped, or your own saved text. When a saved text of yours cannot be
// used (unreadable, not UTF-8, or one that would break what is given), its own place says why and that the shipped
// text is used instead (settings/prompts.py, from the ledger's own entries()). A text changed on a page of its own
// (Scheduling, Subconscious) is shown as that page keeps it, and names the page. Shown here, not changed here.

type Prompt = {
  id: string;
  title: string;
  category: string;
  about: string;
  text: string;
  file: string;
  yours: boolean;
  set_aside: string; // why your saved text is not used ('' when it is, or when there is none)
  edited_on: string; // the page it is changed on, when it has one of its own ('' when not)
  edited_at: string; // that page's address
  instead: string; // what is used instead
};
type Prompts = {
  status: string;
  categories: { id: string; title: string; about: string }[];
  prompts: Prompt[];
  in_code: number;
};

const kept = (p: Prompt) =>
  p.set_aside ? 'The shipped text, for now' : p.yours ? 'Yours' : 'As shipped';

export default function PromptsPage() {
  const [state, setState] = useState<Prompts | null>(null);
  const [notice, setNotice] = useState('');

  useEffect(() => {
    let here = true;
    const look = async () => {
      try {
        const reply = await fetch('/api/settings/prompts', { cache: 'no-store' });
        if (!reply.ok) throw new Error();
        const fresh = (await reply.json()) as Prompts;
        if (here) {
          setState(fresh);
          setNotice('');
        }
      } catch {
        if (here) setNotice('It could not be read. Is Viventium running?');
      }
    };
    look();
    const again = setInterval(look, 15000);
    return () => {
      here = false;
      clearInterval(again);
    };
  }, []);

  return (
    <Sheet
      title="Prompts"
      lede="Every text Viventium is given, and the one in force for each: as shipped, or your own."
      note={state?.status}
      notice={notice}
      saved={0}
    >
      {state?.categories.map((category) => {
        const texts = state.prompts.filter((p) => p.category === category.id);
        if (!texts.length) return null;
        return (
          <Pane key={category.id} title={category.title}>
            <p className="vs-hint vsp-cat">{category.about}</p>
            <div className="vsp-texts">
              {texts.map((p) => (
                <div key={p.id} className="vsp-text" data-prompt={p.id}>
                  <div className="vsp-head">
                    <span className="vs-h3">{p.title}</span>
                    <span className="vs-hint">{kept(p)}</span>
                  </div>
                  <p className="vs-sub">{p.about}</p>
                  {p.edited_on && (
                    <p className="vs-hint" data-edited-on={p.edited_at}>
                      Changed on <Link href={p.edited_at}>{p.edited_on}</Link>; shown here as it is
                      in force.
                    </p>
                  )}
                  {p.set_aside && (
                    <p className="vsp-aside" role="status" data-set-aside="true">
                      <strong>Your saved text is not used.</strong>
                      <span>{p.set_aside}</span>
                      <span>{p.instead}</span>
                    </p>
                  )}
                  {p.text && (
                    <Open title="The text in force">
                      <pre className="vsx-pre">{p.text}</pre>
                    </Open>
                  )}
                </div>
              ))}
            </div>
          </Pane>
        );
      })}
      {state && state.in_code > 0 && (
        <p className="vs-hint vsp-code">
          {state.in_code} more texts are still written in code; each is named in the prompt ledger,
          where it is placed and why.
        </p>
      )}
    </Sheet>
  );
}
