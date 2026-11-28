'use client';

import { useState } from 'react';
import { ArrowRight, Check as CheckIcon, Plus, X } from 'lucide-react';
import type { Account, Added, Settings } from '../lib/api';
import type { Save } from './choices';
import { Disc, Expand, Pane, Switch } from './glass';
import { Install } from './install';

// System: this Mac (the menu bar, starting with it), and every account in one place. A provider is shown once,
// with the two ways it can be used: the subscription you already pay for (its own log-in, in your browser) and
// an API key (kept in this Mac's Keychain; never shown again, never written to a file).

// How an account was last found when it is not answering (core/accounts.py), in a word or two.
const FOUND: Record<string, string> = {
  limited: 'Limited',
  sign_in: 'Log in again',
  refused: 'Refused',
  down: 'Not answering',
};

function Found({ on, state, ok }: { on: boolean; state: string; ok: string }) {
  if (!on) return <span className="vs-off">Not used</span>;
  if (state) return <span className="vs-warn">{FOUND[state] ?? 'Not answering'}</span>;
  return (
    <span className="vs-ok">
      <CheckIcon strokeWidth={3} />
      {ok}
    </span>
  );
}

// Another account you added for a provider: its sign-in until it is done, then like any account (a switch, how it
// was last found), and removed with one click (xPerfect's own copy of it; nothing of this Mac's).
function AddedLine({ account, added, save }: { account: Account; added: Added; save: Save }) {
  const [code, setCode] = useState('');
  const ready = added.status === 'ready';
  return (
    <>
      <div className="vs-account-line">
        <span className="vs-sub">{added.label}</span>
        <span className="vs-account-end">
          {ready ? (
            <>
              <Found on={added.use} state={added.state} ok="Logged in" />
              {/* (found needing a log-in by Viventium, though its home still says ready: the way to do it, here) */}
              {added.use && added.state === 'sign_in' && (
                <button
                  type="button"
                  className="vs-act"
                  aria-label={`Sign in to ${added.label}`}
                  onClick={() => save({ account_signin: { id: account.id, account: added.id } })}
                >
                  Sign in
                </button>
              )}
            </>
          ) : added.setup?.url ? (
            <a className="vs-act" href={added.setup.url} target="_blank" rel="noreferrer">
              {added.setup.code ? added.setup.code : 'Finish in your browser'}
            </a>
          ) : added.setup?.again ? (
            <button
              type="button"
              className="vs-act"
              aria-label={`Sign in to ${added.label}`}
              onClick={() => save({ account_signin: { id: account.id, account: added.id } })}
            >
              Sign in
            </button>
          ) : (
            <span className="vs-off">Signing in</span>
          )}
          {ready && (
            <Switch
              label={`Use ${added.label}`}
              on={added.use}
              onChange={(on) =>
                save({ account: { id: account.id, line: 'account', account: added.id, use: on } })
              }
            />
          )}
          <button
            type="button"
            className="vs-x"
            aria-label={`Remove ${added.label}`}
            title="Remove"
            onClick={() => save({ remove_account: { id: account.id, account: added.id } })}
          >
            <X />
          </button>
        </span>
      </div>
      {ready && added.same && (
        <p className="vs-hint vs-same">Same account as {added.same}, so it is no backup.</p>
      )}
      <Expand open={!ready && !!added.setup?.input}>
        <form
          className="vs-keyform"
          onSubmit={(e) => {
            e.preventDefault();
            if (code.trim()) save({ account_input: { account: added.id, value: code.trim() } });
            setCode('');
          }}
        >
          <input
            className="vs-input"
            autoComplete="off"
            aria-label={`The code for ${added.label}`}
            placeholder="Paste the code it shows you"
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          <button type="submit" className="vs-play" aria-label="Send this code">
            <ArrowRight />
          </button>
        </form>
      </Expand>
    </>
  );
}

// How the last sign-in for the conscious mind ended, when it did not.
const LAST: Record<string, string> = {
  denied: 'The sign-in was refused.',
  expired: 'The code expired before it was approved.',
  failed: 'The sign-in could not finish.',
  ended: 'The sign-in ended at its provider.',
  keychain_locked:
    'Your Mac’s Keychain is locked. Unlock it by logging in to your Mac, then try again.',
};

// Light's Grok sign-in serves the mind and Grok Workers. The browser opens with the approval code filled in.
function MindLine({
  account,
  save,
  use,
}: {
  account: Account;
  save: Save;
  use: (on: boolean) => void;
}) {
  const mind = account.mind!;
  // (signed in but refused, or its sign-in needed again: one click signs in again, beside its switch)
  const locked = mind.last === 'keychain_locked';
  const again = mind.on && (mind.state === 'sign_in' || mind.state === 'refused' || locked);
  const signIn = (
    <button
      type="button"
      className="vs-act"
      aria-label={`Connect ${account.product}`}
      onClick={() => save({ sign_in: mind.id })}
    >
      {mind.last || again ? 'Retry' : 'Connect'}
    </button>
  );
  return (
    <>
      <div className="vs-account-line">
        <span className="vs-account-end vs-account-connected">
          {mind.setup?.url ? (
            <>
              <a className="vs-act" href={mind.setup.url} target="_blank" rel="noreferrer">
                {mind.setup.code || 'Finish in your browser'}
              </a>
              <button
                type="button"
                className="vs-x"
                aria-label="Cancel this sign-in"
                title="Cancel"
                onClick={() => save({ sign_in_cancel: mind.id })}
              >
                <X />
              </button>
            </>
          ) : mind.on ? (
            <>
              <Found on={mind.use} state={mind.state} ok="Signed in" />
              {again && signIn}
              <Switch
                label={`Use your ${account.name} subscription for the mind and Grok Workers`}
                on={mind.use}
                onChange={use}
              />
            </>
          ) : mind.checking ? (
            <span className="vs-off">Checking</span>
          ) : (
            signIn
          )}
        </span>
      </div>
      {mind.setup?.url && <p className="vs-hint">Approve it in your browser with this code.</p>}
      {(!mind.on || locked) && !mind.setup && mind.last && (
        <p className="vs-hint">{LAST[mind.last] ?? LAST.failed}</p>
      )}
    </>
  );
}

const dayWords = (iso: string) => {
  const d = new Date(`${iso}T12:00:00`);
  const days = Math.round((d.setHours(0, 0, 0, 0) - new Date().setHours(0, 0, 0, 0)) / 86_400_000);
  if (days === 0) return 'today';
  if (days === -1) return 'yesterday';
  if (days === 1) return 'tomorrow';
  return new Date(`${iso}T12:00:00`).toLocaleDateString([], { day: 'numeric', month: 'short' });
};

// The files you sent, kept on this Mac: the rule in one line, the newest few, and one click to remove one now.
function Files({ settings, save }: { settings: Settings; save: Save }) {
  const kept = settings.files;
  const [all, setAll] = useState(false);
  const shown = all ? kept.files : kept.files.slice(0, 4);
  if (!kept.count) return null; // (nothing kept: nothing to see or remove, and no words at rest)
  return (
    <div className="vs-files">
      <div className="vs-col-head">
        <span className="vs-h3">Files you sent</span>
        <span className="vs-hint">
          Kept {kept.days} days, unless a job or your notes still use them.
        </span>
      </div>
      {kept.count > 0 && (
        <ul className="vs-file-list" aria-label="Files you sent">
          {shown.map((file) => (
            <li key={file.id}>
              <span className="vs-file-name" title={file.name}>
                {file.name}
              </span>
              <span className="vs-sub">
                {file.size} · {dayWords(file.came)} ·{' '}
                {file.goes ? `goes ${dayWords(file.goes)}` : 'still in use'}
              </span>
              <button
                type="button"
                className="vs-x"
                aria-label={`Remove ${file.name}`}
                title="Remove now"
                onClick={() =>
                  save({ remove_file: file.id }, (s) => ({
                    ...s,
                    files: {
                      ...s.files,
                      files: s.files.files.filter((f) => f.id !== file.id),
                      count: s.files.count - 1,
                    },
                  }))
                }
              >
                <X />
              </button>
            </li>
          ))}
        </ul>
      )}
      {kept.files.length > 4 && (
        <button
          type="button"
          className="vs-quiet-btn"
          aria-expanded={all}
          onClick={() => setAll(!all)}
        >
          {all
            ? 'Fewer'
            : kept.count > kept.files.length
              ? `The newest ${kept.files.length} of ${kept.count} (${kept.size})`
              : `All ${kept.count} (${kept.size})`}
        </button>
      )}
    </div>
  );
}

const CHATGPT_STATE: Record<string, string> = {
  limited: 'Plan limit reached',
  unavailable: 'Not responding',
  refresh_unavailable: 'Sign-in could not refresh',
  session_expired: 'Sign-in expired',
  unauthorized: 'Sign-in rejected',
  scope_missing: 'Plan access missing',
  sign_in: 'Log in again',
  refused: 'Plan access refused',
  revoked: 'Disconnected',
  revocation_unconfirmed: 'Revocation unconfirmed',
  revoking: 'Disconnecting',
};

function ChatGPTConnection({ mind, save }: { mind: NonNullable<Account['mind']>; save: Save }) {
  const [connecting, setConnecting] = useState(false);
  const [registration, setRegistration] = useState('');
  if (mind.pending) {
    return (
      <div className="vs-account-line">
        <span className="vs-hint">Finish in browser</span>
        <button
          className="vs-act"
          type="button"
          onClick={() => save({ chatgpt: { action: 'cancel' } })}
        >
          Cancel
        </button>
      </div>
    );
  }
  if (connecting) {
    return (
      <div className="vs-account-line">
        <div className="vs-kv">
          <span className="vs-hint">{mind.privacy}</span>
          {!!mind.registrations?.length && (
            <select
              aria-label="ChatGPT account"
              value={registration}
              onChange={(event) => setRegistration(event.target.value)}
            >
              {mind.registrations.map((row) => (
                <option key={row.account} value={row.account}>
                  {[row.workspace, row.email].filter(Boolean).join(' · ') || 'ChatGPT account'}
                </option>
              ))}
              <option value="">Use another account</option>
            </select>
          )}
          <div className="vs-account-actions">
            <button
              className="vs-act"
              type="button"
              onClick={async () => {
                if (
                  await save({
                    chatgpt: {
                      action: 'connect',
                      account: registration || undefined,
                    },
                  })
                ) {
                  setConnecting(false);
                }
              }}
            >
              Continue with ChatGPT
            </button>
            <button
              className="vs-act"
              type="button"
              data-quiet="true"
              onClick={() => setConnecting(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="vs-account-line">
      <span className="vs-kv">
        {(mind.on || mind.state === 'scope_missing') && (
          <span className="vs-hint">{mind.email || 'ChatGPT plan'}</span>
        )}
        {mind.state === 'limited' && mind.usage && (
          <a className="vs-act" target="_blank" rel="noreferrer" href={mind.usage}>
            ChatGPT Usage
          </a>
        )}
      </span>
      <span className="vs-account-end vs-account-actions">
        <button
          className="vs-act"
          type="button"
          onClick={() => {
            setRegistration(mind.account || '');
            setConnecting(true);
          }}
        >
          {mind.on && mind.state !== 'sign_in' && mind.state !== 'refused'
            ? 'Switch account'
            : mind.account
              ? 'Reconnect'
              : 'Connect'}
        </button>
        {(mind.on || mind.state === 'scope_missing') && (
          <button
            className="vs-act"
            type="button"
            data-quiet="true"
            onClick={() => save({ chatgpt: { action: 'disconnect' } })}
          >
            Disconnect
          </button>
        )}
      </span>
    </div>
  );
}

function AccountTile({ account, save }: { account: Account; save: Save }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState('');
  const [asked, setAsked] = useState<string>();
  const [failed, setFailed] = useState(false);
  // Turned off, Light stops using it (her Workers, her mind, her voice); the log-in and the Keychain item stay.
  const use = (line: 'plan' | 'key' | 'mind', on: boolean) =>
    save({ account: { id: account.id, line, use: on } }, (s) => ({
      ...s,
      accounts: s.accounts.map((a) =>
        a.id !== account.id
          ? a
          : line === 'key'
            ? { ...a, key: { ...a.key, use: on } }
            : line === 'mind'
              ? { ...a, mind: a.mind && { ...a.mind, use: on } }
              : { ...a, plan: a.plan && { ...a.plan, use: on } }
      ),
    }));
  const keep = async (key: string) => {
    if (key.trim().length < 16) return;
    if (await save({ key: { name: account.key.name, value: key.trim() } })) setOpen(false);
    setValue('');
  };
  const connect = async (id: string) => {
    setFailed(false);
    setAsked(id);
    if (!(await save({ sign_in: id }))) {
      setFailed(true);
      setAsked(undefined);
    } else if (id === account.mind?.id) {
      setAsked(undefined);
    }
  };
  const primary = account.mind ?? account.plan;
  const chatgpt = account.mind?.id === 'chatgpt_mind' ? account.mind : undefined;
  const connectHere =
    primary &&
    !chatgpt &&
    !primary.on &&
    !account.mind?.setup &&
    !account.mind?.checking &&
    (account.mind || account.plan?.installed);
  return (
    <div className="vs-account" id={`account-${account.id}`}>
      <div className="vs-account-top">
        <Disc mark={account.mark} />
        <span className="vs-kv">
          <b className="vs-name">{account.product || account.name}</b>
          {chatgpt ? (
            <span className="vs-hint">
              {(chatgpt.last && LAST[chatgpt.last]) ||
                CHATGPT_STATE[chatgpt.state] ||
                'Conversation mind'}
            </span>
          ) : failed ? (
            <span className="vs-hint">Could not connect.</span>
          ) : account.mind?.last && !account.mind.on && !account.mind.setup ? (
            <span className="vs-hint">{LAST[account.mind.last] ?? LAST.failed}</span>
          ) : account.mind ? (
            <span className="vs-hint">Mind and Grok Workers</span>
          ) : (
            account.background &&
            !account.key.on && <span className="vs-hint">Background work</span>
          )}
        </span>
        <span className="vs-account-end vs-account-actions">
          {connectHere && (
            <button
              type="button"
              className="vs-act"
              aria-label={`Connect ${account.product}`}
              onClick={() => connect(primary.id)}
              disabled={asked === primary.id}
            >
              {asked === primary.id
                ? 'Finish in browser'
                : failed || account.mind?.last
                  ? 'Retry'
                  : 'Connect'}
            </button>
          )}
          {account.plan && !account.mind && !account.plan.installed && !account.plan.on && (
            <Install item={account.plan.install} quiet={false} />
          )}
          {!account.key.on && !open && (
            <button
              type="button"
              className="vs-act"
              data-quiet="true"
              onClick={() => setOpen(true)}
            >
              {account.connect ? 'or API key' : 'Add API key'}
            </button>
          )}
        </span>
      </div>
      {chatgpt && <ChatGPTConnection mind={chatgpt} save={save} />}
      {account.plan && (account.plan.on || account.mind) && (
        <div className="vs-account-line">
          {account.plan.on ? (
            <>
              <span className="vs-account-end vs-account-connected">
                <Found on={account.plan.use} state={account.plan.state} ok="Subscription" />
                <Switch
                  label={`Use your ${account.name} subscription`}
                  on={account.plan.use}
                  onChange={(on) => use('plan', on)}
                />
                <button
                  type="button"
                  className="vs-x"
                  aria-label={`Add another ${account.name} account`}
                  title="Add another account"
                  onClick={() => save({ add_account: { id: account.id } })}
                >
                  <Plus />
                </button>
              </span>
            </>
          ) : account.plan.installed ? (
            <button
              type="button"
              className="vs-act"
              data-quiet="true"
              aria-label={chatgpt ? 'Connect native Codex' : undefined}
              onClick={() => connect(account.plan!.id)}
            >
              {asked === account.plan.id
                ? 'Finish in browser'
                : chatgpt
                  ? 'Connect Codex'
                  : 'Connect Workers'}
            </button>
          ) : (
            <>
              {chatgpt && <span className="vs-hint">Native Codex</span>}
              <Install item={account.plan.install} quiet={false} />
            </>
          )}
        </div>
      )}
      {account.plan?.accounts?.map((added) => (
        <AddedLine key={added.id} account={account} added={added} save={save} />
      ))}
      {!chatgpt &&
        account.mind &&
        (account.mind.on || account.mind.setup || account.mind.checking) && (
          <MindLine account={account} save={save} use={(on) => use('mind', on)} />
        )}
      {account.key.on && (
        <div className="vs-account-line">
          <span className="vs-account-end vs-account-connected">
            <Found on={account.key.use} state={account.key.state} ok="API key" />
            <Switch
              label={`Use your ${account.name} API key`}
              on={account.key.use}
              onChange={(on) => use('key', on)}
            />
          </span>
        </div>
      )}
      <Expand open={open && !account.key.on}>
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
            autoFocus
            aria-label={`Your ${account.name} API key`}
            placeholder="Paste API key"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onPaste={(e) => {
              const pasted = e.clipboardData.getData('text');
              if (pasted.trim().length >= 16) {
                e.preventDefault();
                keep(pasted);
              }
            }}
          />
          <button type="submit" className="vs-play" aria-label="Keep this key">
            <ArrowRight />
          </button>
          <button
            type="button"
            className="vs-x"
            aria-label="Cancel API key"
            onClick={() => {
              setValue('');
              setOpen(false);
            }}
          >
            <X />
          </button>
        </form>
      </Expand>
    </div>
  );
}

export function System({ settings, save }: { settings: Settings; save: Save }) {
  const row = (name: 'login' | 'menubar', title: string) => (
    <label className="vs-toggle">
      <Switch
        label={title}
        on={settings.system[name]}
        onChange={(on) =>
          save({ [name]: on }, (s) => ({ ...s, system: { ...s.system, [name]: on } }))
        }
      />
      <span className="vs-name">{title}</span>
    </label>
  );
  return (
    <Pane title="System">
      <div className="vs-system">
        <div>
          <div className="vs-col-head">
            <span className="vs-h3">This Mac</span>
          </div>
          <div className="vs-toggles">
            {row('menubar', 'Show in the menu bar')}
            {row('login', 'Start when this Mac starts')}
          </div>
          {/* macOS asks once before a background program may read Documents, Desktop or Downloads */}
          <Expand open={settings.system.blocked}>
            <p className="vs-blocked" role="status">
              <span>
                macOS is asking whether Viventium AI may read its own folder. Until you allow it,
                Viventium cannot start by itself.
              </span>
              <button type="button" className="vs-act" onClick={() => save({ show: 'privacy' })}>
                Show me where
              </button>
            </p>
          </Expand>
          <Files settings={settings} save={save} />
        </div>
        <div id="accounts">
          <div className="vs-col-head">
            <span className="vs-h3">Accounts and connections</span>
          </div>
          <div className="vs-accounts">
            {settings.accounts.map((account) => (
              <AccountTile key={account.id} account={account} save={save} />
            ))}
          </div>
        </div>
      </div>
    </Pane>
  );
}
