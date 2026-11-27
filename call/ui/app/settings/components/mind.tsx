'use client';

import { type ReactNode, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import {
  Activity,
  Archive,
  ArrowLeft,
  Calculator,
  ChevronRight,
  CloudMoon,
  HeartPulse,
  Layers,
  Moon,
  Route,
  Scale,
  ScanSearch,
  Shapes,
  Sparkles,
  Swords,
  Telescope,
  Waves,
} from 'lucide-react';
import { AnimatePresence, MotionConfig, motion } from 'motion/react';
import { Mark } from '@/components/app/mark';
import type { Option, Settings } from '../lib/api';
import { goToAccount } from './choices';
import { Field } from './field';
import { Disc, Expand, Segmented, useChoiceKeys } from './glass';

// What the two pages one step from Brain share (Subconscious, Scheduling): their top, a drawn sign, who runs a
// thing and at what thinking effort, a prompt that keeps itself, and more opened in place.

const SIGNS: Record<string, React.ComponentType<{ strokeWidth?: number }>> = {
  'heart-pulse': HeartPulse,
  waves: Waves,
  archive: Archive,
  scale: Scale,
  'scan-search': ScanSearch,
  swords: Swords,
  layers: Layers,
  shapes: Shapes,
  route: Route,
  calculator: Calculator,
  telescope: Telescope,
  sparkles: Sparkles,
  activity: Activity,
  moon: Moon,
  'cloud-moon': CloudMoon,
};
export function Sign({ name }: { name: string }) {
  const Drawn = SIGNS[name] ?? Sparkles;
  return (
    <span className="vsx-sign" aria-hidden="true">
      <Drawn strokeWidth={1.7} />
    </span>
  );
}

// One page: the field, "Saved" where you are looking, the way back, the mark, its name and one line.
export function Sheet({
  title,
  lede,
  note,
  notice,
  saved,
  wide,
  children,
}: {
  title: string;
  lede: string;
  note?: string;
  notice: string;
  saved: number;
  wide?: boolean; // more of a wide screen, for long prompts side by side with their settings
  children: ReactNode;
}) {
  const [flash, setFlash] = useState(false);
  useEffect(() => {
    if (!saved) return;
    setFlash(true);
    const timer = setTimeout(() => setFlash(false), 1800);
    return () => clearTimeout(timer);
  }, [saved]);
  return (
    <MotionConfig reducedMotion="user">
      <Field />
      <AnimatePresence>
        {(notice || flash) && (
          <motion.div
            key={notice || 'saved'}
            className="vs-toast"
            data-tone={notice ? 'warn' : ''}
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
          >
            {notice || 'Saved'}
          </motion.div>
        )}
      </AnimatePresence>
      <main className="vs-col" data-wide={wide || undefined}>
        <Link href="/settings" className="vs-back" aria-label="Back to settings">
          <ArrowLeft size={18} />
        </Link>
        <header className="vs-top">
          <Mark size={96} />
          <span className="vs-word">viventium</span>
          <h1 className="vsx-title">{title}</h1>
          <p className="vsx-lede">{lede}</p>
          {note && (
            <p className="vsx-yet" role="note">
              {note}
            </p>
          )}
        </header>
        {children}
      </main>
    </MotionConfig>
  );
}

// The Worker types ticked in Brain (and the one already chosen here, should it no longer be ticked).
export function workers(settings: Settings, chosen?: string): Option[] {
  const use = settings.choices.hands.use;
  return settings.parts.hands.options.filter((o) => use.includes(o.id) || o.id === chosen);
}

// A cortex can use any Worker. An option that needs a login links to it.
export function allWorkers(settings: Settings): Option[] {
  return settings.parts.hands.options;
}
const label = (o: Option) => (o.where === 'mac' ? `${o.model} · this Mac` : o.model);

// A part asked on this Mac's model directly (a cortex, the coordinator) can think or not, though the Worker of the same
// name sets its own: its levels are this Mac's (the coordinator thought at low while its card said "This model
// has one").
export function onThisMac(
  option: Option | undefined,
  levels: string[] | undefined
): Option | undefined {
  if (!option || option.where !== 'mac' || option.efforts?.length || !levels?.length) return option;
  return { ...option, efforts: levels, effort: 'none' };
}

export function Who({
  name,
  value,
  options,
  onChange,
  aside,
}: {
  name: string;
  value: string;
  options: Option[];
  onChange: (id: string) => void;
  aside?: string;
}) {
  const keys = useChoiceKeys<HTMLSpanElement>();
  return (
    <span className="vsx-set">
      <span className="vsx-lab">Runs on{aside && <em>{aside}</em>}</span>
      <span
        className="vsx-pick"
        role="radiogroup"
        aria-label={`${name} runs on`}
        ref={keys.ref}
        onKeyDown={keys.onKeyDown}
      >
        {options.map((o) =>
          o.needs && o.id !== value ? (
            <button
              key={o.id}
              type="button"
              className="vsx-who"
              data-needs="true"
              aria-label={`${o.provider} ${o.model}: log in first`}
              onClick={() => goToAccount(o.account)}
            >
              <Disc mark={o.mark} size="sm" />
              <span>{label(o)}</span>
              <em>Log in first</em>
            </button>
          ) : (
            <motion.button
              key={o.id}
              type="button"
              role="radio"
              className="vsx-who"
              aria-checked={o.id === value}
              aria-label={`${o.provider} ${o.model}`}
              title={o.detail}
              whileTap={{ scale: 0.96 }}
              onClick={() => o.id !== value && onChange(o.id)}
            >
              <Disc mark={o.mark} size="sm" />
              <span>{label(o)}</span>
            </motion.button>
          )
        )}
      </span>
    </span>
  );
}

export function Thinking({
  name,
  option,
  value,
  names,
  onChange,
}: {
  name: string;
  option?: Option;
  value: string;
  names: Record<string, string>;
  onChange: (level: string) => void;
}) {
  return (
    <span className="vsx-set">
      <span className="vsx-lab">Thinking effort</span>
      {option?.efforts?.length ? (
        <Segmented
          label={`Thinking effort for ${name}`}
          size="sm"
          value={option.efforts.includes(value) ? value : (option.effort ?? option.efforts[0])}
          options={option.efforts.map((id) => ({ id, name: names[id] ?? id }))}
          onChange={onChange}
        />
      ) : (
        <span className="vsx-plain">This model has one.</span>
      )}
    </span>
  );
}

// A prompt that keeps itself as you type. It is as tall as its words, up to a limit; all of it while you are in it.
export function Prompt({
  label,
  value,
  onSave,
  placeholder,
  whole,
  field,
}: {
  label: string;
  value: string;
  onSave: (text: string) => Promise<unknown>;
  placeholder?: string;
  whole?: boolean; // never cut short (a "When" is a few lines)
  field?: string;
}) {
  const [text, setText] = useState(value);
  const box = useRef<HTMLTextAreaElement>(null);
  const typing = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fit = (all: boolean) => {
    const el = box.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight + 2, all || whole ? 4000 : 264)}px`;
  };
  useEffect(() => {
    if (!typing.current) setText(value);
  }, [value]);
  useEffect(() => {
    fit(document.activeElement === box.current);
  });
  const change = (next: string) => {
    typing.current = true;
    setText(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      await onSave(next);
      typing.current = false;
    }, 900);
  };
  return (
    <textarea
      ref={box}
      className="vs-input vsx-prompt"
      value={text}
      aria-label={label}
      placeholder={placeholder}
      data-field={field}
      onChange={(e) => change(e.target.value)}
      onFocus={() => fit(true)}
      onBlur={() => fit(false)}
    />
  );
}

// More of the same thing, opened in place by its own name.
export function Open({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="vsx-open">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
        <ChevronRight />
        {title}
      </button>
      <Expand open={open}>{children}</Expand>
    </div>
  );
}
