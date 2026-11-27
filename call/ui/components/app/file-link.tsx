'use client';

import { type ComponentProps, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import {
  type ByteStreamReader,
  ParticipantKind,
  type Room,
  RoomEvent,
  RpcError,
} from 'livekit-client';
import { useSessionContext } from '@livekit/components-react';
import { NOT_YET, type Offered, add, ask, drawn, healer, unknown } from '@/lib/offered-files';

// One handler per file's topic, shared by every link to that file. LiveKit allows one per topic and throws on a second,
// so a reply that showed the same file twice (her retelling a reply that was only its link) took the page down.
// The bytes go to the link that asked for them.
type DownloadRequest = { id: number; reading: boolean };
type Waiter = {
  waiting: () => DownloadRequest | undefined;
  receive: (reader: ByteStreamReader, request: DownloadRequest) => Promise<void>;
  retry: () => void;
};
const shared = new WeakMap<Room, Map<string, Set<Waiter>>>();
let nextRequest = 0;

function listen(room: Room, topic: string, waiter: Waiter): () => void {
  let topics = shared.get(room);
  if (!topics) shared.set(room, (topics = new Map()));
  let waiters = topics.get(topic);
  if (!waiters) {
    const fresh = new Set<Waiter>();
    waiters = fresh;
    topics.set(topic, fresh);
    room.registerByteStreamHandler(topic, async (reader, sender) => {
      if (room.remoteParticipants.get(sender.identity)?.kind !== ParticipantKind.AGENT) return;
      const requestId = reader.info.attributes?.request_id;
      const waiting = [...fresh].flatMap((link) => {
        const request = link.waiting();
        return request ? [{ link, request }] : [];
      });
      // An older agent sends the same file without an ID. Give its stream to the oldest request.
      const [first, ...others] =
        requestId === undefined
          ? waiting.sort((a, b) => a.request.id - b.request.id)
          : waiting.filter(({ request }) => String(request.id) === requestId);
      if (!first) return;
      for (const { link } of others) link.retry();
      await first.link.receive(reader, first.request);
    });
  }
  const mine = waiters;
  mine.add(waiter);
  return () => {
    mine.delete(waiter);
    if (mine.size === 0) {
      topics.delete(topic);
      room.unregisterByteStreamHandler(topic);
    }
  };
}

// Which files she offered, per room, as her agent tells this page (lib/offered-files.ts: how a link is drawn).
const offeredIn = new WeakMap<Room, Offered>();
const healers = new WeakMap<Room, ReturnType<typeof healer>>();
const watching = new Set<() => void>();
function watch(changed: () => void) {
  watching.add(changed);
  return () => {
    watching.delete(changed);
  };
}

/** Her agent's word on which files she offered, for this page's room: asked for once the page listens (again until she
 *  answers: a word sent before it listened is never needed), after every reconnect, and whenever a link names an id it
 *  does not know (her answer is the truth); her own words as they come (the whole set when she joins, each new one). */
export function useOfferedFiles(on: boolean) {
  const { room } = useSessionContext();
  useEffect(() => {
    if (!on || !room) return;
    let here = true;
    const update = (ids: unknown, whole: boolean) => {
      offeredIn.set(room, add(offeredIn.get(room) ?? NOT_YET, ids, whole));
      watching.forEach((changed) => changed());
    };
    room.registerTextStreamHandler('viv.files', async (reader, sender) => {
      try {
        const told: { ids?: unknown; whole?: unknown } = JSON.parse(await reader.readAll());
        if (here && room.remoteParticipants.get(sender.identity)?.kind === ParticipantKind.AGENT)
          update(told.ids, told.whole === true);
      } catch {
        // (only her agent's list of ids: anything else is left alone)
      }
    });
    const answer = async () => {
      const agent = [...room.remoteParticipants.values()].find(
        (person) => person.kind === ParticipantKind.AGENT
      );
      if (!agent) throw new Error('her agent is not in the room yet');
      return room.localParticipant.performRpc({
        destinationIdentity: agent.identity,
        method: 'viv.files',
        payload: '',
        responseTimeout: 10_000,
      });
    };
    const heal = healer(() =>
      ask(
        answer,
        (ids) => update(ids, true),
        () => here,
        500,
        20
      )
    );
    healers.set(room, heal);
    const reconnected = () => heal.fresh();
    room.on(RoomEvent.Reconnected, reconnected);
    void ask(
      answer,
      (ids) => update(ids, true),
      () => here
    );
    return () => {
      here = false;
      heal.stop();
      if (healers.get(room) === heal) healers.delete(room);
      room.off(RoomEvent.Reconnected, reconnected);
      room.unregisterTextStreamHandler('viv.files');
    };
  }, [on, room]);
}

/** A reference in the conversation, downloaded through LiveKit, never an arbitrary HTTP file path. */
export function FileLink({ href, children, title }: ComponentProps<'a'>) {
  const { room } = useSessionContext();
  const offered = useSyncExternalStore(
    watch,
    () => (room && offeredIn.get(room)) || NOT_YET,
    () => NOT_YET
  );
  const how = drawn(href, offered);
  const id = how === 'file' ? href?.slice('#viv-file-'.length) : undefined;
  const missing = unknown(href, offered);
  useEffect(() => {
    if (missing && room) healers.get(room)?.unknown(missing); // (her set again: perhaps a word of hers was missed)
  }, [missing, room]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef<DownloadRequest | undefined>(undefined);

  useEffect(() => {
    if (!id || !room) return;
    const topic = `viv.file.${id}`;
    const abort = new AbortController();
    let url: string | undefined;
    const stop = listen(room, topic, {
      waiting: () => (pending.current?.reading ? undefined : pending.current),
      retry: () => {
        pending.current = undefined;
        setBusy(false);
        setError('Download failed. Try again.');
      },
      receive: async (reader, request) => {
        request.reading = true;
        try {
          const chunks = await reader.readAll({ signal: abort.signal });
          if (abort.signal.aborted || pending.current !== request) return;
          const blob = new Blob(
            chunks.map((chunk) => chunk.slice().buffer),
            { type: reader.info.mimeType }
          );
          if (url) URL.revokeObjectURL(url);
          url = URL.createObjectURL(blob);
          const download = document.createElement('a');
          download.href = url;
          download.download = reader.info.name;
          download.click();
        } catch {
          if (!abort.signal.aborted && pending.current === request)
            setError('Download failed. Try again.');
        } finally {
          if (pending.current === request) {
            pending.current = undefined;
            setBusy(false);
          }
        }
      },
    });
    return () => {
      abort.abort();
      pending.current = undefined;
      stop();
      if (url) URL.revokeObjectURL(url);
    };
  }, [id, room]);

  if (how === 'label') return <>{children}</>; // (a file she never offered: her label, plain)
  if (!id)
    return (
      <a title={title} href={href} target="_blank" rel="noreferrer noopener">
        {children}
      </a>
    );
  return (
    <span>
      <a
        title={title}
        href={href}
        aria-disabled={busy}
        className="underline underline-offset-2"
        onClick={async (event) => {
          event.preventDefault();
          if (pending.current || !room) return;
          const agent = [...room.remoteParticipants.values()].find(
            (person) => person.kind === ParticipantKind.AGENT
          );
          if (!agent) {
            setError('Reconnect to Viventium to download this file.');
            return;
          }
          const request = { id: ++nextRequest, reading: false };
          pending.current = request;
          setBusy(true);
          setError('');
          try {
            await room.localParticipant.performRpc({
              destinationIdentity: agent.identity,
              method: 'viv.file.download',
              payload: JSON.stringify({ id, request_id: String(request.id) }),
              responseTimeout: 30_000,
            });
          } catch (error) {
            if (pending.current === request) {
              pending.current = undefined;
              setBusy(false);
              setError(
                error instanceof RpcError && error.code === 2000
                  ? error.message
                  : 'File unavailable. Ask Viventium to send it again.'
              );
            }
          }
        }}
      >
        {busy ? 'Downloading…' : children}
      </a>
      {error && (
        <span role="status" className="ml-2 text-sm">
          {error}
        </span>
      )}
    </span>
  );
}
