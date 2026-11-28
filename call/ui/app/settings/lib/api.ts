// The page's one adapter to her settings (settings/service.py, through /api/settings).
// Everything the page shows comes from `show`; every change is one small `save`.

export type Where = 'mac' | 'key' | 'plan';
export type PartId = 'listen' | 'talk' | 'mind' | 'manager' | 'hands';

export type Option = {
  id: string;
  provider: string;
  model: string;
  title?: string;
  detail?: string;
  mark: string;
  where: Where;
  words?: string[];
  speed?: 'fast' | 'ok' | 'slow';
  smart?: 'smart' | 'balanced' | 'simple';
  timed?: string;
  efforts?: string[];
  effort?: string;
  sample?: string;
  backup_name?: string;
  alone?: boolean;
  pick?: boolean;
  decides?: boolean; // (a mind) it decides itself when work goes to a Worker; false: a quick check beside it does
  tried: boolean;
  needs: string; // "" | "key:NAME" | "signin:NAME" | "model"
  needs_name?: string;
  account?: string; // the account (System) that would make it ready
  install?: Install | null; // with needs "model": one click gets it
};

// Something not on this Mac yet, and how getting it is going (settings/install.py).
export type Install = {
  id: string;
  name: string;
  size_gb: number; // what is still to download (0: small)
  state: '' | 'running' | 'failed';
  percent: number;
  words: string;
  error: string;
};

export type Part = {
  name: string;
  region: string;
  hint: string;
  many: boolean;
  absent?: Partial<Record<Where, string>>; // why a group offers nothing for this part
  options: Option[];
};
export type One = { id: string; effort?: string };
export type Many = { use: string[]; effort: Record<string, string> };
// One of a feeling's five levels: its word, what it says (main Viventium's words, or yours in their place: `original` is
// main's), and your own words added to it.
export type Level = { word: string; text: string; original: string; yours: string };
export type Band = {
  id: string;
  name: string;
  low: string;
  high: string;
  color: string;
  word: string;
  now: number;
  rest: number;
  on: boolean;
  pace: number; // minutes to come halfway back to where it rests
  trail: { t: string; from: number; to: number }[];
  bounds: number[]; // where levels 1 to 4 begin (as shipped: 20, 40, 60, 80)
  levels: Level[]; // the five levels, lowest first
};
export type Nature = { id: string; name: string; sign: string; line?: string; rests: number[] };
export type Account = {
  id: string;
  name: string;
  product: string;
  mark: string;
  connect?: string;
  background?: boolean;
  // on: kept (the Keychain, or logged in); use: Light uses it (you can turn it off; nothing is logged out or deleted);
  // state: how it was last found when it is not answering ("limited", "sign_in", "down"), else ""
  key: { name: string; on: boolean; use: boolean; state: string };
  plan?: {
    id: string;
    name: string;
    on: boolean;
    installed: boolean;
    use: boolean;
    state: string;
    install?: Install | null;
    accounts: Added[]; // the other accounts you added for it (xPerfect's Connections), each its own sign-in
  };
  // The conscious mind on your subscription: a sign-in Viventium makes itself (in your browser, kept in its Keychain
  // item), apart from the Workers' own. setup: where to approve it and your one-time code, while one waits for you;
  // last: how the last one ended when it did not ("denied", "expired", "failed", "ended")
  mind?: {
    id: string;
    on: boolean;
    use: boolean;
    state: string;
    setup?: { url: string; code: string };
    last?: string;
    checking?: boolean; // the Keychain has not said yet (the page never waits on it; it shows what it last knew)
    account?: string;
    email?: string;
    pending?: boolean;
    usage?: string;
    privacy?: string;
    registrations?: { account: string; email?: string; workspace?: string }[];
  };
};
export type Added = {
  id: string;
  label: string;
  status: string; // "ready" once its sign-in is done
  use: boolean;
  state: string;
  setup?: { url: string; code: string; input: boolean; again?: boolean }; // again: its sign-in ended unfinished
  same?: string; // signed in as the same account as this one ("yours", or another you added): no backup
};
export type MediaKind = 'photos' | 'videos';

export type Settings = {
  profile: string;
  profiles: {
    id: string;
    name: string;
    line: string;
    resources: { memory_gb: number; setup_gb: number; model_gb: number };
  }[];
  mix: boolean;
  voice_available?: boolean;
  voice_need?: string;
  choices: { listen: One; talk: One; mind: One; manager: One; hands: Many };
  parts: Record<PartId, Part>;
  ask: string;
  backup: string; // the mind's declared backup, as named ("" for none)
  backup_now: string; // the backup answers for the mind right now, and why ("key", "limited", "sign_in", "refused", "down"); "" when not
  backup_of?: string; // the mind choice backup_now is about (never another, painted before the answer comes)
  backup_seen?: number; // when its account was last found so (epoch seconds)
  last_mind?: { provider?: string; model?: string };
  paused?: boolean; // the mind runs on your subscription, turned off or not signed in, with no backup: replies pause
  accounts: Account[];
  media: {
    parts: Record<MediaKind, { name: string; hint: string; options: Option[] }>;
    choices: Record<MediaKind, string>;
  };
  where: Record<Where, { name: string; facts: string[]; hint?: string }>;
  speed: Record<string, string>;
  smart: Record<string, string>;
  effort_names: Record<string, string>;
  workers_note: string;
  call_mode: string;
  call_modes: { id: string; name: string; hint: string }[];
  // How Viventium shows above the conversation: its mark and dots (built in), or Soulface, an add-on that is on this Mac
  // only once asked for (settings/install.py ADDONS). chosen: what was asked for; shown: what the page shows now.
  presence: {
    chosen: 'dots' | 'soulface';
    shown: 'dots' | 'soulface';
    soulface: { here: boolean; install?: Install | null; entry?: string | null };
  };
  channels: {
    // voice: the voice switch, a voice message gets a voice reply (off: text only; chat/telegram.py)
    telegram: {
      on: boolean;
      connected: boolean;
      bot: string;
      id: string;
      voice: boolean;
      approvals: boolean;
      paired: boolean;
    };
    web: { on: boolean; address: string; port: string };
    // calling from his phone on the same Wi-Fi: on or off, where the phone opens it, whether this Mac is on a network
    // a phone could reach it on, whether this Mac was renamed since it was turned on, whether it is on another network
    // than the one it was turned on in (the doors stay shut there), and the fingerprint of the certificate the phone
    // trusts, to check on the phone once
    phone: {
      on: boolean;
      page: string;
      network: boolean;
      moved: boolean;
      elsewhere?: boolean;
      fingerprint?: string;
      still?: boolean; // (off, yet something answers where its doors were)
      renewed?: boolean; // (Viventium's root made new: a paired phone needs it, once)
    };
  };
  character: {
    on: boolean;
    nature: string;
    manner: string; // the personality whose way of speaking is kept, also after a resting point is moved by hand
    natures: Nature[];
    bands: Band[];
    inner: { text: string; at: string } | null;
    as_of: string;
    module: boolean;
    tune: boolean; // the engine keeps your thresholds and your words for a level (else they are as shipped)
  };
  // blocked: macOS is not letting it start by itself yet
  system: {
    login: boolean;
    menubar: boolean;
    blocked: boolean;
  };
  // the files you sent, kept on this Mac (settings/files.py): newest first, each with the day it goes ("" past its days,
  // still in use by a job or your notes)
  files: {
    files: { id: string; name: string; size: string; came: string; goes: string }[];
    count: number;
    size: string;
    days: number;
  };
  applying: { state: 'idle' | 'waiting' | 'restarting' | 'failed'; for?: string; why?: string };
  installing: boolean; // something is being installed: the page keeps looking
};

export type Change = Partial<{
  account: {
    id: string;
    line: 'plan' | 'key' | 'account' | 'mind';
    use: boolean;
    account?: string;
  };
  add_account: { id: string };
  remove_account: { id: string; account: string };
  account_input: { account: string; value: string };
  account_signin: { id: string; account: string };
  profile: string;
  listen: One;
  talk: One;
  mind: One;
  manager: One;
  hands: Many;
  media: { kind: MediaKind; id: string };
  telegram: boolean;
  telegram_voice: boolean;
  telegram_approvals: boolean;
  telegram_token: string;
  telegram_revoke: boolean;
  telegram_disconnect: boolean;
  feelings: boolean;
  nature: string;
  band: { id: string; rest?: number; on?: boolean; now?: number; pace?: number };
  words: { band: string; level: number; text: string };
  bounds: { band: string; at: number[] };
  says: { band: string; level: number; text: string };
  reset_feelings: boolean;
  call_mode: string;
  presence: 'dots' | 'soulface';
  workers_note: string;
  login: boolean;
  menubar: boolean;
  key: { name: string; value: string };
  sign_in: string;
  chatgpt: {
    action: 'connect' | 'cancel' | 'disconnect';
    account?: string;
  };
  sign_in_cancel: string; // a sign-in of Viventium's own that waits: ended, nothing kept from it
  show: string; // 'privacy': where macOS lists what may read your folders
  remove_file: string; // one file you sent, by its day and name
  phone: boolean; // calling from the phone on the same Wi-Fi, on or off
  forget_phones: boolean; // every paired phone unpaired
  install: string;
}>;

export type Saved = {
  ok: boolean;
  why?: string;
  state?: Settings;
  telegram_approval_link?: string;
};

export async function show(): Promise<Settings> {
  const reply = await fetch('/api/settings', { cache: 'no-store' });
  if (!reply.ok) throw new Error('The settings could not be read.');
  return reply.json();
}

export async function save(change: Change): Promise<Saved> {
  try {
    const reply = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(change),
    });
    if (!reply.ok) return { ok: false, why: 'That could not be saved.' };
    return reply.json();
  } catch {
    return { ok: false, why: 'That could not be saved.' };
  }
}
