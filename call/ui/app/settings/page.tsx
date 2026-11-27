'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { AnimatePresence, MotionConfig, motion } from 'motion/react';
import { Mark } from '@/components/app/mark';
import { Brain } from './components/brain';
import { Channels } from './components/channels';
import { Character } from './components/character';
import { goToAccount } from './components/choices';
import { Field } from './components/field';
import { Segmented } from './components/glass';
import { System } from './components/system';
import { Media, Voice } from './components/voice';
import { useSettings } from './lib/use-settings';

// Settings. One calm column under the mark: where Viventium runs, then channels, voice, photos and videos, the
// brain, character and system. There is no Edit and no Save: a setting is its own editor, and a change keeps itself.

const WAITING: Record<string, string> = {
  settling: 'Saved.',
  call: 'Saved. It switches over when your call ends.',
  work: 'Saved. It switches over when the work in progress is done.',
};

export default function SettingsPage() {
  const { settings, save, notice, saved } = useSettings();
  const [flash, setFlash] = useState(false);
  useEffect(() => {
    if (!saved) return;
    setFlash(true);
    const timer = setTimeout(() => setFlash(false), 1800);
    return () => clearTimeout(timer);
  }, [saved]);
  // Opened at one part (/settings#brain: the app's "Choose another mind"; #accounts: a place that needs a key): taken
  // there once the page is drawn, which is after it has read the settings, so the browser's own jump finds nothing.
  const drawn = !!settings;
  useEffect(() => {
    if (!drawn) return;
    const target = window.location.hash.slice(1);
    if (target === 'accounts' || target.startsWith('account-'))
      goToAccount(target === 'accounts' ? undefined : target.slice(8));
    else if (target) document.getElementById(target)?.scrollIntoView({ block: 'start' });
  }, [drawn]);
  const applying = settings?.applying;
  const profile = settings?.profiles.find((p) => p.id === settings.profile);
  const line = notice
    ? { tone: 'warn', text: notice }
    : applying?.state === 'failed'
      ? { tone: 'warn', text: applying.why || 'It could not switch over.' }
      : applying?.state === 'restarting'
        ? { tone: 'busy', text: 'Switching over. Up to half a minute.' }
        : applying?.state === 'waiting'
          ? { tone: 'busy', text: WAITING[applying.for ?? 'settling'] ?? 'Saved.' }
          : {
              tone: '',
              text: settings?.mix ? 'Your own choice for each part.' : (profile?.line ?? ''),
            };

  return (
    <MotionConfig reducedMotion="user">
      <Field />
      <AnimatePresence>
        {(line.tone || flash) && (
          <motion.div
            key={line.tone ? line.text : 'saved'}
            className="vs-toast"
            data-tone={line.tone}
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
          >
            {line.tone ? line.text : 'Saved'}
          </motion.div>
        )}
      </AnimatePresence>
      <main className="vs-col">
        <Link href="/" className="vs-back" aria-label="Back to the call">
          <ArrowLeft size={18} />
        </Link>
        <header className="vs-top">
          <Mark busy={applying?.state === 'restarting'} />
          <span className="vs-word">Viventium AI</span>
          {settings && (
            <>
              {/* (parts moved off a profile's places are "Custom": always one of these is lit) */}
              <Segmented
                label="Where Viventium runs"
                value={settings.mix ? 'mix' : settings.profile}
                options={[
                  ...settings.profiles,
                  ...(settings.mix ? [{ id: 'mix', name: 'Custom' }] : []),
                ]}
                onChange={(id) =>
                  id !== 'mix' && save({ profile: id }, (s) => ({ ...s, profile: id, mix: false }))
                }
              />
              <p className="vs-line" data-tone={line.tone} role="status" aria-live="polite">
                {line.text}
              </p>
            </>
          )}
          {!settings && (
            <p className="vs-line" data-tone={notice ? 'warn' : ''} role="status">
              {notice}
            </p>
          )}
        </header>
        {settings && (
          <>
            <Channels settings={settings} save={save} />
            <Voice settings={settings} save={save} />
            <Media settings={settings} save={save} />
            <Brain settings={settings} save={save} />
            <Character settings={settings} save={save} />
            <System settings={settings} save={save} />
          </>
        )}
      </main>
    </MotionConfig>
  );
}
