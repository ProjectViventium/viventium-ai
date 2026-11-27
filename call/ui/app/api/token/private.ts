import { execFile, execFileSync } from 'node:child_process';
import { constants, promises as fs, readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { ROOT } from '../settings/carry';

// Her state folder (VX_STATE, as the rest of Light reads it), and how this page writes a file in it: his alone from
// the start (0600, in folders made 0700), never through a link and never into a file that also has another name, as
// core/state.py private_file() does for her Python parts; never in a folder core/state.py refuses (his home or a
// folder above it, this checkout or a folder above it, a folder that holds his Life or lies inside it, wherever his
// settings put it); never on a disk that will not keep it closed. A refused write throws: it does not happen.
export const STATE = process.env.VX_STATE ?? path.join(ROOT, 'state');

// Whether her state folder may be written at all, asked once of core/state.py itself, the one owner of that rule. It
// runs as this checkout's own interpreter, isolated (-I: no PYTHONPATH, no user site, not the working folder), on the
// exact file VX_ROOT/core/state.py loaded by its path, with only what it needs in its environment: his home, PATH (for
// git), the run's LIFE and the variables his private settings use (profiles/*.local.env). It is asked as soon as this
// module loads; a call's click never waits for it (wait: false takes its answer only if it is in). No answer within a
// few seconds, or none at all: refused.
const ASK = [
  'import importlib.util, sys',
  'spec = importlib.util.spec_from_file_location("viventium_core_state", sys.argv[1])',
  'state = importlib.util.module_from_spec(spec)',
  'spec.loader.exec_module(state)',
  'print(state._unsafe(sys.argv[2]) or "ok")',
].join('\n');

// This checkout, and the one it is a git worktree of (whose private settings core/state.py reads too).
const GIT_ENV: Record<string, string | undefined> = {
  PATH: process.env.PATH,
  HOME: process.env.HOME,
};
function checkouts(): string[] {
  const found = [ROOT];
  try {
    const common = execFileSync(
      'git',
      ['-C', ROOT, 'rev-parse', '--path-format=absolute', '--git-common-dir'],
      {
        encoding: 'utf8',
        timeout: 5_000,
        env: GIT_ENV as NodeJS.ProcessEnv,
        stdio: ['ignore', 'pipe', 'ignore'],
      }
    ).trim();
    if (path.basename(common) === '.git' && path.dirname(common) !== ROOT)
      found.push(path.dirname(common));
  } catch {
    /* (not a checkout) */
  }
  return found;
}

// Null when a private settings file of either checkout cannot be read: it could name his Life, so nothing is written.
function askEnv(): NodeJS.ProcessEnv | null {
  const names = new Set(['HOME', 'PATH', 'LIFE']);
  for (const checkout of checkouts()) {
    const folder = path.join(checkout, 'profiles');
    let files: string[];
    try {
      files = readdirSync(folder).filter((name) => name.endsWith('.local.env'));
    } catch (error) {
      if ((error as NodeJS.ErrnoException)?.code === 'ENOENT') continue; // (no private settings there)
      return null;
    }
    for (const file of files) {
      let text: string;
      try {
        text = readFileSync(path.join(folder, file), 'utf8');
      } catch {
        return null;
      }
      for (const used of text.matchAll(/\$\{?([A-Za-z_][A-Za-z0-9_]*)/g)) names.add(used[1]);
    }
  }
  const env: Record<string, string | undefined> = {};
  for (const name of names)
    if (!/^(PYTHON|DYLD_|LD_)/.test(name) && process.env[name] !== undefined)
      env[name] = process.env[name];
  return env as NodeJS.ProcessEnv;
}

let answer: string | undefined; // (undefined: not in yet)
let verdict: Promise<string> | null = null;
function unsafe(): Promise<string> {
  verdict ??= new Promise<string>((done) => {
    const env = askEnv();
    if (!env) return done('his private settings could not be read');
    execFile(
      path.join(ROOT, '.venv', 'bin', 'python'),
      ['-I', '-c', ASK, path.join(ROOT, 'core', 'state.py'), STATE],
      { cwd: ROOT, env, timeout: 5_000 },
      (error, stdout) => {
        const said = String(stdout ?? '').trim();
        done(error || !said ? 'its safety could not be checked' : said === 'ok' ? '' : said);
      }
    );
  }).then((said) => (answer = said));
  return verdict;
}
void unsafe();

// A folder of hers, made his alone: every folder from her state down to it real (a link refuses), made 0700 when
// missing and closed to others when open.
export async function privateFolder(folder: string, wait = true): Promise<void> {
  const rel = path.relative(STATE, folder);
  if (rel.startsWith('..') || path.isAbsolute(rel))
    throw new Error(`${folder} is not in her state`);
  const why = wait ? await unsafe() : (answer ?? 'its safety is not known yet');
  if (why) throw new Error(`her state is not kept in ${STATE}: ${why}`);
  let at = STATE;
  for (const part of ['', ...rel.split(path.sep).filter((p) => p && p !== '.')]) {
    at = part ? path.join(at, part) : at;
    if (!(await fs.lstat(at).catch(() => null))) {
      if (at === STATE) await fs.mkdir(path.dirname(at), { recursive: true }); // (above her state: not hers)
      await fs.mkdir(at, { mode: 0o700 }).catch((error) => {
        if (error?.code !== 'EEXIST') throw error; // (made meanwhile: looked at below)
      });
    }
    const st = await fs.lstat(at);
    if (st.isSymbolicLink() || !st.isDirectory())
      throw new Error(`${at} is a link or not a folder`);
    if (st.mode & 0o077) {
      await fs.chmod(at, st.mode & 0o700);
      if ((await fs.lstat(at)).mode & 0o077)
        throw new Error(`${at} cannot be kept private on this disk`);
    }
  }
}

// exclusive: only if the file is not there yet. wait: false never waits for the safety answer (refused until it is in).
export async function writePrivate(
  file: string,
  data: string,
  { exclusive = false, wait = true }: { exclusive?: boolean; wait?: boolean } = {}
): Promise<void> {
  if (!path.relative(STATE, file)) throw new Error(`${file} is not a file in her state`);
  await privateFolder(path.dirname(file), wait);
  const flags = constants.O_WRONLY | constants.O_CREAT | constants.O_NOFOLLOW;
  const handle = await fs.open(file, exclusive ? flags | constants.O_EXCL : flags, 0o600);
  try {
    const st = await handle.stat();
    if (st.nlink > 1) throw new Error(`${file} also has another name`);
    if (st.mode & 0o077) {
      await handle.chmod(st.mode & 0o700);
      if ((await handle.stat()).mode & 0o077)
        throw new Error(`${file} cannot be kept private on this disk`);
    }
    await handle.truncate(0);
    if (data) await handle.write(data, 0);
    const now = new Date();
    await handle.utimes(now, now); // (an empty mark still says "just now")
  } finally {
    await handle.close();
  }
}
