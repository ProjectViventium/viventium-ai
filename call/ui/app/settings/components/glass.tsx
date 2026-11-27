'use client';

import { type ReactNode, useEffect, useId, useRef, useState } from 'react';
import {
  AudioLines,
  BadgeCheck,
  Check as CheckIcon,
  Cloud,
  CreditCard,
  Ear,
  Eye,
  Globe,
  Lock,
  Pause,
  Play as PlayIcon,
  Smartphone,
  WifiOff,
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { cn } from '@/lib/shadcn/utils';
import type { Where } from '../lib/api';

// The page's small parts. Each is plain: a pane of glass, a choice between a few, a switch, a check, a mark.
// Motion comes from one package (motion) with one spring, so everything answers the same way.

export const spring = { type: 'spring', visualDuration: 0.22, bounce: 0.22 } as const;

export function Pane({
  title,
  aside,
  children,
  className,
  ...rest
}: {
  title?: string;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
} & React.ComponentProps<'section'>) {
  const ref = useRef<HTMLElement>(null);
  // Light follows the pointer across the glass (two CSS numbers; no layout, no React state).
  const follow = (e: React.PointerEvent) => {
    const el = ref.current;
    if (!el) return;
    const box = el.getBoundingClientRect();
    el.style.setProperty('--mx', `${e.clientX - box.left}px`);
    el.style.setProperty('--my', `${e.clientY - box.top}px`);
  };
  return (
    <section ref={ref} className={cn('vs-pane', className)} onPointerMove={follow} {...rest}>
      {(title || aside) && (
        <div className="vs-head">
          <h2 className="vs-title">{title}</h2>
          {aside}
        </div>
      )}
      {children}
    </section>
  );
}

// A group of choices is one stop for Tab: the chosen one (else the first that can be chosen). The arrow keys and Home
// and End move between its choices; Space or Enter chooses. Moving never chooses by itself: a choice here applies at
// once (some restart Viventium), so it waits for the key that says so.
function choicesOf(group: HTMLElement) {
  return [...group.querySelectorAll<HTMLElement>('[role=radio]')].filter(
    (r) => r.closest('[role=radiogroup]') === group
  );
}
const usable = (r: HTMLElement) =>
  !r.hasAttribute('disabled') && r.getAttribute('aria-disabled') !== 'true';
export function useChoiceKeys<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    if (!ref.current) return;
    const all = choicesOf(ref.current);
    const stop =
      all.find((r) => r.getAttribute('aria-checked') === 'true') ?? all.find(usable) ?? all[0];
    for (const r of all) r.tabIndex = r === stop ? 0 : -1;
  });
  const onKeyDown = (e: React.KeyboardEvent<T>) => {
    const step = (
      { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 } as Record<string, number>
    )[e.key];
    if (!step && e.key !== 'Home' && e.key !== 'End') return;
    const all = choicesOf(e.currentTarget).filter(usable);
    if (!all.length) return;
    const at = all.indexOf(document.activeElement as HTMLElement);
    if (at < 0) return; // (the key was meant for something else inside the group)
    e.preventDefault();
    const next =
      e.key === 'Home'
        ? 0
        : e.key === 'End'
          ? all.length - 1
          : (at + step + all.length) % all.length;
    all[next].focus();
  };
  return { ref, onKeyDown };
}

export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  size,
}: {
  label: string;
  value: T | '';
  options: { id: T; name: string }[];
  onChange: (id: T) => void;
  size?: 'sm';
}) {
  const id = useId();
  const keys = useChoiceKeys<HTMLDivElement>();
  return (
    <div
      className="vs-seg"
      role="radiogroup"
      aria-label={label}
      data-size={size}
      ref={keys.ref}
      onKeyDown={keys.onKeyDown}
    >
      {options.map((o) => (
        <motion.button
          key={o.id}
          type="button"
          role="radio"
          aria-checked={o.id === value}
          onClick={() => o.id !== value && onChange(o.id)}
          whileTap={{ scale: 0.96 }}
        >
          {o.id === value && (
            <motion.div
              layoutId={id}
              className="vs-thumb"
              transition={spring}
              style={{ borderRadius: 999 }}
            />
          )}
          <span>{o.name}</span>
        </motion.button>
      ))}
    </div>
  );
}

export function Switch({
  label,
  on,
  onChange,
}: {
  label: string;
  on: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      className="vs-switch"
      onClick={() => onChange(!on)}
    >
      <motion.span layout className="vs-knob" transition={spring} />
    </button>
  );
}

// A provider's or channel's own mark, so a choice is recognised before it is read. A mark that is already a
// full disc (Telegram, WhatsApp) fills the whole circle; the others sit on a light disc.
const DRAWN: Record<string, React.ComponentType<{ strokeWidth?: number }>> = {
  whisper: Ear,
  chatterbox: AudioLines,
  waveform: AudioLines,
  web: Globe,
  phone: Smartphone,
};
const FULL = new Set(['telegram', 'whatsapp']);
export function Disc({ mark, size }: { mark: string; size?: 'lg' | 'sm' }) {
  const Drawn = DRAWN[mark];
  return (
    <span className="vs-disc" data-size={size} data-full={FULL.has(mark)} aria-hidden="true">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      {Drawn ? <Drawn strokeWidth={1.7} /> : <img src={`/marks/${mark}.svg`} alt="" />}
    </span>
  );
}

// What a place means, said once with icons: offline, private, free; or online and how it is paid.
function FreeIcon() {
  // a coin, struck through: it costs nothing
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M14.8 9.6c-.4-1-1.400-1.600-2.800-1.600-1.700 0-2.900.8-2.900 2 0 2.700 5.800 1.200 5.800 4 0 1.200-1.200 2-2.900 2-1.400 0-2.500-.6-2.900-1.600M12 6.200v11.600" />
      <path d="M4.200 19.800 19.800 4.200" />
    </svg>
  );
}
const FACT_ICON: Record<string, React.ComponentType> = {
  Offline: WifiOff,
  Private: Lock,
  Free: FreeIcon,
  Online: Cloud,
  'Not private': Eye,
  'Billed per use': CreditCard,
  'Already paid for': BadgeCheck,
};
export function Facts({ where, facts, said }: { where: Where; facts: string[]; said?: boolean }) {
  // said: already said beside it (the other column of a pair): its icons only, the words when you point at one
  return (
    <span className="vs-facts" data-where={where} data-said={said || undefined}>
      {facts.map((fact) => {
        const Icon = FACT_ICON[fact];
        return said && Icon ? (
          <span key={fact} title={fact} aria-label={fact} role="img">
            <Icon />
          </span>
        ) : (
          <span key={fact}>
            {Icon && <Icon />}
            {fact}
          </span>
        );
      })}
    </span>
  );
}

// A group of choices, named once: a few plain facts with an icon each, then one thin line.
export function GroupHead({
  where,
  place,
  said,
  table,
}: {
  where: Where;
  place: { name: string; facts: string[]; hint?: string };
  said?: boolean;
  table?: number; // in a table: a row of its own, its name the header of the columns it spans
}) {
  return (
    <div className="vs-grp-head" data-where={where} role={table ? 'row' : undefined}>
      <span
        className="vs-grp-name"
        role={table ? 'rowheader' : undefined}
        aria-colspan={table || undefined}
      >
        {place.name}
      </span>
      {table ? (
        <span role="cell" className="vs-grp-facts">
          <Facts where={where} facts={place.facts} said={said} />
        </span>
      ) : (
        <Facts where={where} facts={place.facts} said={said} />
      )}
      <span className="vs-grp-line" aria-hidden="true" />
    </div>
  );
}

// An empty place that says why when you point at it, focus it or tap it.
export function Why({ text }: { text: string }) {
  return (
    <span className="vs-why" tabIndex={0} role="note" aria-label={text}>
      <span className="vs-why-mark" aria-hidden="true" />
      <span className="vs-tip" role="tooltip">
        {text}
      </span>
    </span>
  );
}

// The one check on the page: a choice is made by ticking it, wherever it is.
export function Check({
  on,
  label,
  onChange,
  role = 'checkbox',
  disabled,
}: {
  on: boolean;
  label: string;
  onChange: () => void;
  role?: 'checkbox' | 'radio';
  disabled?: boolean;
}) {
  return (
    <motion.button
      type="button"
      role={role}
      aria-checked={on}
      aria-label={label}
      aria-disabled={disabled || undefined}
      className="vs-check"
      data-on={on}
      whileTap={disabled ? undefined : { scale: 0.88 }}
      onClick={(e) => {
        e.stopPropagation();
        if (!disabled) onChange();
      }}
    >
      <AnimatePresence initial={false}>
        {on && (
          <motion.span
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0, opacity: 0 }}
            transition={spring}
          >
            <CheckIcon strokeWidth={3.2} />
          </motion.span>
        )}
      </AnimatePresence>
    </motion.button>
  );
}

// One short recording per voice, played from the page itself (settings/samples.py made them).
let playing: HTMLAudioElement | null = null;
export function Play({ sample, name }: { sample: string; name: string }) {
  const [on, setOn] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);
  useEffect(() => () => audio.current?.pause(), []);
  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (on) {
      audio.current?.pause();
      return;
    }
    playing?.pause();
    const a = (audio.current ??= new Audio(`/samples/${sample}.wav`));
    a.currentTime = 0;
    a.onended = a.onpause = () => setOn(false);
    a.onplay = () => setOn(true);
    playing = a;
    a.play().catch(() => setOn(false));
  };
  return (
    <motion.span
      role="button"
      tabIndex={0}
      className="vs-play"
      data-playing={on}
      aria-label={on ? `Stop ${name}` : `Hear ${name}`}
      onClick={toggle}
      onKeyDown={(e) =>
        (e.key === 'Enter' || e.key === ' ') && toggle(e as unknown as React.MouseEvent)
      }
      whileTap={{ scale: 0.9 }}
    >
      {on ? <Pause fill="currentColor" /> : <PlayIcon fill="currentColor" />}
    </motion.span>
  );
}

// More of the same thing, opened in place (never a modal, never another page).
export function Expand({ open, children }: { open: boolean; children: ReactNode }) {
  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.div
          className="vs-more"
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// A few words that keep themselves as you type: no button, a quiet "Saved" when they are kept.
export function Words({
  value,
  onSave,
  placeholder,
  label,
  rows = 2,
  max = 600,
}: {
  value: string;
  onSave: (text: string) => Promise<boolean>;
  placeholder?: string;
  label: string;
  rows?: number;
  max?: number;
}) {
  const [text, setText] = useState(value);
  const [kept, setKept] = useState(false);
  const typing = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!typing.current) setText(value);
  }, [value]);
  const change = (next: string) => {
    typing.current = true;
    setText(next);
    setKept(false);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      const ok = await onSave(next);
      typing.current = false;
      setKept(ok);
    }, 900);
  };
  return (
    <span className="vs-words">
      <textarea
        className="vs-input"
        rows={rows}
        maxLength={max}
        value={text}
        aria-label={label}
        placeholder={placeholder}
        onChange={(e) => change(e.target.value)}
      />
      <span className="vs-saved" data-on={kept} aria-live="polite">
        {kept ? 'Saved' : ''}
      </span>
    </span>
  );
}
