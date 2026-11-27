import { promises as fs } from 'node:fs';
import path from 'node:path';

// Her mind as the last start found it, read as her channels read it (core/accounts.py mind_down, by the same rule: one
// table of cases runs through both, tests/call_page_test.py). vx mind_answers keeps its verdict in logs/mind-answer:
// what happened on its first line, the profile it is of on its second. It says her mind cannot answer until something
// is changed only when this Mac could not run its model ("load"), or her provider refused it or needs a key or a
// sign-in (its own status, as core/accounts.failure_of classes it: 401, 403). A server error, a limit, no connection,
// no word or no answer in time may pass by itself, and never counts (a startup 503 left the
// page saying to choose another mind after the provider came back). It counts only while it is of the profile running
// now (logs/profile), no older than her agent's start (logs/agent.pid) and newer than her last answer on any channel
// (state/core/mind-answered). Paths are read at each ask, as the rest of the page reads them.
const NEEDS_CHANGE = new Set([401, 403]);

function folders(): { logs: string; state: string } {
  const cwd = process.cwd();
  const root =
    process.env.VX_ROOT ??
    (cwd.endsWith(path.join('call', 'ui')) ? path.resolve(cwd, '..', '..') : cwd);
  return {
    logs: path.join(process.env.VX_SETTINGS_ROOT ?? root, 'logs'),
    state: process.env.VX_STATE ?? path.join(root, 'state'),
  };
}

async function changed(file: string): Promise<number | null> {
  try {
    return (await fs.stat(file)).mtimeMs;
  } catch {
    return null;
  }
}

export async function mindDown(): Promise<boolean> {
  const { logs, state } = folders();
  let said: string[];
  let profile: string;
  let written: number;
  try {
    said = (await fs.readFile(path.join(logs, 'mind-answer'), 'utf8')).split('\n');
    written = (await fs.stat(path.join(logs, 'mind-answer'))).mtimeMs;
    profile = (await fs.readFile(path.join(logs, 'profile'), 'utf8')).trim();
  } catch {
    return false;
  }
  const what = said[0].trim().split(' ').filter(Boolean);
  if (!what.length || !profile || (said[1] ?? '').trim() !== profile) return false;
  const definite =
    what[0] === 'load' || (what[0] === 'refused' && NEEDS_CHANGE.has(Number(what[1])));
  if (!definite) return false;
  const started = await changed(path.join(logs, 'agent.pid'));
  const answered = await changed(path.join(state, 'core', 'mind-answered'));
  return !(started !== null && started > written) && !(answered !== null && answered >= written);
}
