'use client';

import type { Settings } from '../lib/api';
import { Pair, type Save } from './choices';
import { Pane, Segmented } from './glass';

// Ears and voice, side by side, sharing their groups; a recording to hear a voice first; and the call mode.
export function Voice({ settings, save }: { settings: Settings; save: Save }) {
  const mode = settings.call_modes.find((m) => m.id === settings.call_mode);
  const column = (part: 'listen' | 'talk') => ({
    name: settings.parts[part].name,
    hint: settings.parts[part].hint,
    options: settings.parts[part].options,
    chosen: settings.choices[part].id,
    choose: (option: { id: string }) =>
      save({ [part]: { id: option.id } }, (s) => ({
        ...s,
        choices: { ...s.choices, [part]: { id: option.id } },
      })),
  });
  return (
    <Pane title="Voice">
      {settings.voice_need && <p className="vs-hint">{settings.voice_need}</p>}
      <Pair left={column('listen')} right={column('talk')} settings={settings} />
      <div className="vs-foot">
        <span className="vs-kv">
          <span className="vs-h3">On a call</span>
          <span className="vs-hint">{mode?.hint}</span>
        </span>
        <Segmented
          label="On a call"
          value={settings.call_mode}
          options={settings.call_modes}
          onChange={(id) => save({ call_mode: id }, (s) => ({ ...s, call_mode: id }))}
        />
      </div>
    </Pane>
  );
}

// Photos and videos: which tool makes them when you ask. The same table as Voice, on purpose.
export function Media({ settings, save }: { settings: Settings; save: Save }) {
  const column = (kind: 'photos' | 'videos') => ({
    name: settings.media.parts[kind].name,
    hint: settings.media.parts[kind].hint,
    options: settings.media.parts[kind].options,
    chosen: settings.media.choices[kind],
    choose: (option: { id: string }) =>
      save({ media: { kind, id: option.id } }, (s) => ({
        ...s,
        media: { ...s.media, choices: { ...s.media.choices, [kind]: option.id } },
      })),
  });
  return (
    <Pane title="Photos and videos">
      <Pair left={column('photos')} right={column('videos')} settings={settings} />
    </Pane>
  );
}
