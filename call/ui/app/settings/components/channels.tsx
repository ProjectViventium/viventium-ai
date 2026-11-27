'use client';

import { useEffect, useState } from 'react';
import { type Settings, save as apply } from '../lib/api';
import type { Save } from './choices';
import { Disc, Expand, Pane, Switch } from './glass';

// Where you reach Viventium. A channel opens in place to show what it is connected to; nothing here is a secret
// (a bot's token lives in the Keychain and never comes to the page).
// A code his phone types once (app/api/token/pair: this computer only; five minutes, a few tries), shown on request.
function PhoneCode() {
  const [code, setCode] = useState<{ code: string; until: number } | null>(null);
  const [why, setWhy] = useState('');
  const ask = async () => {
    setWhy('');
    try {
      const reply = await fetch('/api/token/pair', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
      if (reply.ok) setCode(await reply.json());
      else setWhy(await reply.text());
    } catch {
      setWhy('Viventium could not be reached.');
    }
  };
  if (code && code.until > Date.now())
    return (
      <span className="vs-kv">
        <span className="vs-hint">Type this on your phone, within five minutes</span>
        <b className="vs-code" aria-label={`The code: ${code.code.split('').join(' ')}`}>
          {code.code.slice(0, 4)} {code.code.slice(4)}
        </b>
      </span>
    );
  return (
    <span className="vs-kv">
      <button type="button" className="vs-act" onClick={ask}>
        Show a code
      </button>
      {why && <span className="vs-warn">{why}</span>}
    </span>
  );
}

function TelegramToken({ save }: { save: Save }) {
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const keep = async (token: string) => {
    if (busy || !token.trim()) return;
    setValue('');
    setBusy(true);
    try {
      await save({ telegram_token: token.trim() });
    } finally {
      setBusy(false);
    }
  };
  return (
    <form
      className="vs-keyform"
      onSubmit={(e) => {
        e.preventDefault();
        keep(value);
      }}
    >
      <input
        className="vs-input"
        type="password"
        autoComplete="off"
        aria-label="Telegram bot token"
        placeholder="Paste bot token from BotFather"
        value={value}
        disabled={busy}
        onChange={(e) => setValue(e.target.value)}
        onPaste={(e) => {
          e.preventDefault();
          keep(e.clipboardData.getData('text'));
        }}
      />
      <button type="submit" className="vs-act" disabled={busy || !value.trim()}>
        {busy ? 'Connecting…' : 'Connect bot'}
      </button>
    </form>
  );
}

function TelegramPairing({ paired, save }: { paired: boolean; save: Save }) {
  const [link, setLink] = useState('');
  const [why, setWhy] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (paired) setLink('');
    if (!link) return;
    const timer = setTimeout(() => setLink(''), 300_000);
    return () => clearTimeout(timer);
  }, [paired, link]);
  const begin = async () => {
    setBusy(true);
    setWhy('');
    try {
      const reply = await apply({ telegram_approvals: true });
      setLink(reply.telegram_approval_link || '');
      setWhy(reply.ok ? '' : reply.why || 'Telegram could not be reached.');
    } catch {
      setWhy('Viventium could not be reached.');
    } finally {
      setBusy(false);
    }
  };
  const forget = async () => {
    setBusy(true);
    try {
      await save({ telegram_revoke: true });
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="vs-kv">
      <span className="vs-hint">{paired ? 'Chat paired' : 'Not paired'}</span>
      {paired ? (
        <button type="button" className="vs-quiet-btn" onClick={forget} disabled={busy}>
          {busy ? 'Forgetting…' : 'Forget this chat'}
        </button>
      ) : link ? (
        <a className="vs-quiet-btn" href={link} target="_blank" rel="noreferrer">
          Open your bot and press Start within five minutes
        </a>
      ) : (
        <button type="button" className="vs-act" onClick={begin} disabled={busy}>
          Pair this chat
        </button>
      )}
      {why && <span className="vs-warn">{why}</span>}
    </span>
  );
}

export function Channels({ settings, save }: { settings: Settings; save: Save }) {
  const [open, setOpen] = useState<'telegram' | 'web' | 'phone' | ''>('');
  const [forgot, setForgot] = useState(false); // (every paired phone unpaired just now: at once, no restart)
  const tg = settings.channels.telegram;
  const web = settings.channels.web;
  const phone = settings.channels.phone;
  const tile = (
    id: 'telegram' | 'web' | 'phone',
    name: string,
    mark: string,
    on: boolean,
    state: string
  ) => (
    <button
      type="button"
      className="vs-tile"
      aria-expanded={open === id}
      onClick={() => setOpen(open === id ? '' : id)}
    >
      <Disc mark={mark} size="lg" />
      <span className="vs-name">{name}</span>
      <span className="vs-state">
        <span className="vs-dot" data-on={on} />
        {state}
      </span>
    </button>
  );
  return (
    <Pane title="Channels">
      <div className="vs-channels">
        {tile(
          'telegram',
          'Telegram',
          'telegram',
          tg.on && tg.connected && tg.paired,
          !tg.connected ? 'Not connected' : !tg.paired ? 'Not paired' : tg.on ? 'On' : 'Off'
        )}
        {tile('web', 'Web', 'web', web.on, 'On')}
        {tile('phone', 'Phone', 'phone', phone.on, phone.on ? 'On' : 'Off')}
      </div>
      <Expand open={open === 'telegram'}>
        <div className="vs-more-in">
          {tg.connected ? (
            <>
              <span className="vs-kv">
                <span className="vs-hint">Your bot</span>
                <b>{tg.bot || 'Connected'}</b>
              </span>
              {tg.id && (
                <span className="vs-kv">
                  <span className="vs-hint">Bot id</span>
                  <b>{tg.id}</b>
                </span>
              )}
              <span className="vs-kv">
                <span className="vs-hint">Its token</span>
                <b>In your Keychain</b>
              </span>
              <Switch
                label="Telegram"
                on={tg.on}
                onChange={(on) =>
                  save({ telegram: on }, (s) => ({
                    ...s,
                    channels: { ...s.channels, telegram: { ...s.channels.telegram, on } },
                  }))
                }
              />
              {/* The voice switch: a voice message gets a voice reply; off, every reply is text. */}
              <span className="vs-kv">
                <span className="vs-hint">A voice message gets a voice reply</span>
                <Switch
                  label="Voice replies"
                  on={tg.voice}
                  onChange={(voice) =>
                    save({ telegram_voice: voice }, (s) => ({
                      ...s,
                      channels: { ...s.channels, telegram: { ...s.channels.telegram, voice } },
                    }))
                  }
                />
              </span>
              {tg.id && (tg.on || tg.paired) && <TelegramPairing paired={tg.paired} save={save} />}
            </>
          ) : (
            <TelegramToken save={save} />
          )}
        </div>
      </Expand>
      <Expand open={open === 'phone'}>
        <div className="vs-more-in">
          <span className="vs-kv">
            <span className="vs-hint">Call from your phone, on this Wi-Fi</span>
            <Switch
              label="Call from your phone"
              on={phone.on}
              onChange={(on) =>
                save({ phone: on }, (s) => ({
                  ...s,
                  channels: { ...s.channels, phone: { ...s.channels.phone, on } },
                }))
              }
            />
          </span>
          {phone.on && (
            <>
              <span className="vs-kv">
                <span className="vs-hint">On your phone, open</span>
                <b className="vs-select">{phone.page}</b>
              </span>
              {phone.renewed && (
                <span className="vs-warn">
                  Viventium&rsquo;s certificate is new: your phone needs it once more. On your
                  phone, open the address above, get the certificate and check its fingerprint is
                  this one; or save it here and AirDrop it.
                </span>
              )}
              {phone.fingerprint && (
                <span className="vs-kv">
                  <span className="vs-hint">
                    Before your phone trusts Viventium, check it shows this fingerprint
                  </span>
                  <code className="vs-select vs-print">{phone.fingerprint}</code>
                  <a className="vs-quiet-btn" href="/pair/certificate" download>
                    Or save the certificate, to AirDrop it
                  </a>
                </span>
              )}
              <PhoneCode />
              <button
                type="button"
                className="vs-quiet-btn"
                onClick={async () => setForgot(await save({ forget_phones: true }))}
              >
                Forget paired phones
              </button>
              {forgot && <span className="vs-hint">No phone is paired now.</span>}
            </>
          )}
          {!phone.on && phone.still && (
            <span className="vs-warn">
              Something still answers where the phone&rsquo;s doors were: ./vx status says what.
            </span>
          )}
          {phone.on && phone.elsewhere && (
            <span className="vs-warn">
              Another network: the doors open again on the one you turned this on in.
            </span>
          )}
          {!phone.network && (
            <span className="vs-warn">This Mac is not on a network your phone could reach.</span>
          )}
          {phone.moved && (
            <span className="vs-warn">This Mac has a new name: turn this off and on again.</span>
          )}
        </div>
      </Expand>
      <Expand open={open === 'web'}>
        <div className="vs-more-in">
          <span className="vs-kv">
            <span className="vs-hint">Address</span>
            <b>{web.address}</b>
          </span>
          <span className="vs-kv">
            <span className="vs-hint">Port</span>
            <b>{web.port}</b>
          </span>
          <span className="vs-kv">
            <span className="vs-hint">Reachable from</span>
            <b>This Mac only</b>
          </span>
        </div>
      </Expand>
    </Pane>
  );
}
