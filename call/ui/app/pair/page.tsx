'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';

// His phone, on the same Wi-Fi as his Mac. Once: trust Viventium's own certificate (so the page and the call are
// private on his network), then type the code his Mac shows (Settings, Channels, Phone). Paired, the call page works
// from here as it does on the Mac (app/api/token: only the phone address, and only a phone paired this way).
// (mac: this page opened on his Mac itself, which needs no pairing: app/api/token answers who asks)
type Seen = 'looking' | 'mac' | 'unpaired' | 'paired' | 'wrong' | 'away';

const LETTERS = /[^23456789ABCDEFGHJKMNPQRSTVWXYZ]/g; // (the code's own letters: app/api/token/pairing.ts)

// Viventium's root made new since this phone trusted one (app/api/token: a new name for the Mac, a new rule, its years
// run out): its new fingerprint, and the call's door, which this phone reaches only once it trusts the new root.
type Renewal = { fingerprint: string; door: string | null };

export default function PairPage() {
  const [seen, setSeen] = useState<Seen>('looking');
  const [code, setCode] = useState('');
  const [renewal, setRenewal] = useState<Renewal | null>(null);
  // (does this phone trust the new root yet? its browser reaching the call's door says so; then its cookie marks it)
  const check = useCallback(async (now: Renewal) => {
    if (!now.door) return;
    try {
      await fetch(now.door, { mode: 'no-cors', cache: 'no-store' });
    } catch {
      return; // (not yet: the steps stay)
    }
    const reply = await fetch('/api/token/pair', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trusted: true }),
    }).catch(() => null);
    if (reply?.status === 204) setRenewal(null);
  }, []);
  useEffect(() => {
    fetch('/api/token', { cache: 'no-store' })
      .then(async (r) => {
        const said = r.ok ? await r.json() : {};
        if (said.here === 'mac') return setSeen('mac');
        setSeen(r.ok ? 'paired' : r.status === 403 ? 'unpaired' : 'away');
        if (said.renewed) {
          const now = { fingerprint: String(said.fingerprint ?? ''), door: said.door ?? null };
          setRenewal(now);
          await check(now);
        }
      })
      .catch(() => setSeen('away'));
  }, [check]);
  const pair = async () => {
    try {
      const reply = await fetch('/api/token/pair', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      });
      if (reply.status !== 204) return setSeen('wrong');
      setSeen('paired');
      setTimeout(() => window.location.assign('/'), 900);
    } catch {
      setSeen('away');
    }
  };
  const shown = code.length > 4 ? `${code.slice(0, 4)} ${code.slice(4)}` : code;
  if (seen === 'mac')
    return (
      <main className="mx-auto flex min-h-svh max-w-md flex-col justify-center gap-8 px-6 py-16">
        <h1 className="text-3xl font-semibold tracking-tight">
          This is your Mac: calls start here
        </h1>
        <section className="flex flex-col gap-4">
          <Link
            href="/"
            className="bg-foreground text-background w-fit rounded-full px-6 py-3 font-semibold"
          >
            Start a call
          </Link>
          <p className="text-muted-foreground text-sm">
            To call from your phone: Settings, Channels, Phone on this Mac.
          </p>
        </section>
      </main>
    );
  return (
    <main className="mx-auto flex min-h-svh max-w-md flex-col justify-center gap-8 px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">Call Viventium from this phone</h1>
      {seen === 'paired' ? (
        <section className="flex flex-col gap-4">
          {renewal ? (
            <>
              <p>
                Viventium&rsquo;s certificate on your Mac is new. Trust it on this phone once more.
              </p>
              <a
                href="/pair/certificate"
                className="bg-foreground/10 w-fit rounded-full px-5 py-2.5 font-medium"
              >
                Get the certificate
              </a>
              <p className="text-muted-foreground text-sm leading-relaxed">
                Then in Settings: General, VPN &amp; Device Management, install it, after checking
                its SHA-256 fingerprint is this one, as your Mac shows it:{' '}
                <span className="font-mono break-all">{renewal.fingerprint}</span>. Then General,
                About, Certificate Trust Settings, turn on Viventium. Come back to this page.
              </p>
              <button
                type="button"
                className="bg-foreground/10 w-fit rounded-full px-5 py-2.5 font-medium"
                onClick={() => check(renewal)}
              >
                Check again
              </button>
            </>
          ) : (
            <p className="text-muted-foreground">This phone is paired.</p>
          )}
          <Link
            href="/"
            className="bg-foreground text-background w-fit rounded-full px-6 py-3 font-semibold"
          >
            Start a call
          </Link>
        </section>
      ) : (
        <>
          <section className="flex flex-col gap-3" aria-labelledby="trust">
            <h2 id="trust" className="text-lg font-semibold">
              1. Trust Viventium on this phone, once
            </h2>
            <a
              href="/pair/certificate"
              className="bg-foreground/10 w-fit rounded-full px-5 py-2.5 font-medium"
            >
              Get the certificate
            </a>
            <p className="text-muted-foreground text-sm leading-relaxed">
              Then in Settings: General, VPN &amp; Device Management, install it, after checking its
              SHA-256 fingerprint is the one your Mac shows (Settings, Channels, Phone). Then
              General, About, Certificate Trust Settings, turn on Viventium. Come back and reload
              this page.
            </p>
          </section>
          <section className="flex flex-col gap-3" aria-labelledby="code">
            <h2 id="code" className="text-lg font-semibold">
              2. Type the code your Mac shows
            </h2>
            <p className="text-muted-foreground text-sm">
              On your Mac: Settings, Channels, Phone, Show a code.
            </p>
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (code.length === 8) pair();
              }}
            >
              <input
                aria-label="The code your Mac shows"
                inputMode="text"
                autoCapitalize="characters"
                autoComplete="one-time-code"
                spellCheck={false}
                className="bg-foreground/5 w-44 rounded-full px-5 py-3 font-mono text-lg tracking-widest"
                value={shown}
                onChange={(e) => {
                  setCode(e.target.value.toUpperCase().replace(LETTERS, '').slice(0, 8));
                  if (seen === 'wrong') setSeen('unpaired');
                }}
              />
              <button
                type="submit"
                disabled={code.length !== 8}
                className="bg-foreground text-background rounded-full px-6 py-3 font-semibold disabled:opacity-40"
              >
                Pair
              </button>
            </form>
            <p role="status" aria-live="polite" className="text-sm">
              {seen === 'wrong' && 'That code did not work. Ask your Mac for a new one.'}
              {seen === 'away' && 'Viventium could not be reached. Is your Mac on the same Wi-Fi?'}
            </p>
          </section>
        </>
      )}
    </main>
  );
}
