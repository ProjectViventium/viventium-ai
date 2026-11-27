# Changelog

What changed for people who use Viventium AI, one entry per public release, newest first.

## 0.5.0 experimental · release 55 · 27 November 2026

- Viventium's marker for "start a new message here" no longer shows up in your messages. It was split only when it
  stood on its own line, or mid-line with spaces around it on some minds; written glued to the next word it reached
  you as text. Now, outside code and quotes, it starts a new message wherever it stands, on every mind, and is never
  spoken or kept in her history. Checked without a model on three kinds of mind, on real replies where it showed and
  on made-up ones: it never remains (before, the glued ones kept it); in code, quotes or written escaped it stays.
- Each tool Viventium uses while answering on Telegram is now kept in her own log, with when it started and ended,
  as on calls, so a reply that went wrong can be looked into afterwards.
- When you ask about something Viventium found for you before, Deep memory now searches each of your recent messages on
  its own. Before, it searched them as one, and older messages could push what you asked about out of the few
  passages it keeps. Checked without a model, on a real request and its memory: the earlier find moved from just
  outside what Deep memory keeps (sixth, with five kept) to second.
- Deep memory now hands Viventium only what its search found, naming where each find comes from; a thought that names
  none of them is dropped. A search that missed something no longer turns into "that was not found, start fresh".
  Checked on Grok on your subscription, old against new, on that request five times: such a thought 0 times (2 of 5
  before), work started every time as before, and the time to the first words about the same.
- When the search by meaning cannot run (its server too slow or not running, or no index yet), Viventium is told the
  search could not run, never that nothing was there, and recall gives the real reason.
- The first message after a long quiet spell keeps its search by meaning: the request is no longer cut off at 0.15
  seconds (a server waking from idle can take a few tenths of a second), and Viventium waits up to 0.8 seconds for it.
  A warm server answers in tens of milliseconds, so other turns are unchanged.
- When the hand-off check judges a message an answer but Viventium's reply still says work is under way, it now says
  "I didn't start the background job." and keeps your request for its next turn, as it already did when the check gave
  no verdict. Checked on Grok on your subscription: ten everyday messages, no false correction, and first words about as
  fast as before.
- Known limit: Deep memory now finds an earlier list like this one, but it may be shown the part of it that sets out
  the request rather than the part that names the places, so Viventium may still not name them.

## 0.5.0 experimental · release 54 · 27 November 2026

- On a call in Listen only, or in Wing when Viventium takes your words as meant for someone else, the page now says so
  the moment she hears you: one line under the mode switch, with a Talk button. One tap and she answers from then on,
  and Talk is kept for your next call. The mode you choose is still kept between calls; before, a mode chosen in an
  earlier call could leave a call silent with nothing on the screen to say why.
- For a typed or Telegram message, when your chosen mind takes the request and then gives no word in its time, it is
  asked once more, fresh, and the backup is asked alongside; the backup's words wait up to 12 seconds for that fresh
  answer. If your chosen mind answers, you get its words and no notice about a backup; if not, the backup answers with
  the notice as before, at most 12 seconds later than before. A spoken call keeps today's timing. Checked on stand-in
  minds, old against new, with the shapes of real messages: a hung request answered by the chosen mind 3 of 3 (before:
  the backup, 3 of 3).
- When Viventium restarts, each part's log from its last run is kept (the last five), instead of being emptied, so a
  problem can still be looked into afterwards.
- `./vx test-telegram` refuses to run while Viventium is running: it would have stopped her and answered its test
  messages in your own Telegram chat.

## 0.5.0 experimental · release 53 · 26 November 2026

- When your chosen mind gives no word in its time and the backup on your Mac is asked instead, the backup now has a
  whole wait of its own (30 seconds) instead of what was left of the first one, and, with nobody behind it, it is not
  cut at the 15 seconds the first mind had. Before, a backup that first had to load its model could be cut before its
  first word, and you got "Viventium's mind did not answer" with no reply: it happened to a video note on Telegram.
  Checked with stand-in minds, old against new: the slow backup answers (before, it was given up); a chosen mind that
  answers in time changes nothing. If both minds hang, "did not answer" now comes after 45 seconds instead of 30.

## 0.5.0 experimental · release 52 · 26 November 2026

- Viventium's first hello is about you. Besides your name, the Mac and the time, it is given what your Mac shows
  anyone sitting at it, with no permission asked and no file opened: your languages and region, and the names of the
  apps in your Dock and Applications. What those only suggest about you, it asks rather than says. Checked on the same
  mind, old against new, on four made-up Macs: a hello resting on something of yours 15 of 24 (10 of 48 before);
  nothing said about you that the facts do not show 23 of 24 (44 of 48 before). It takes a little longer to write.
- When that hello is written as Viventium opens (none ready from setup), it is waited for up to 45 seconds instead of
  25, so a slow mind's hello with its tour of the controls is no longer dropped for a plain one. If the mind does not
  answer at all, the plain hello now comes after 45 seconds instead of 25.
- A check-in whose decision could not get through (it timed out, or the connection failed) is asked once more two
  minutes later, if nothing has changed meanwhile, instead of waiting for the next half hour. A refusal is never asked
  again.

## 0.5.0 experimental · release 51 · 26 November 2026

- If your chosen mind is refused or not answering and another connection of yours to the same model works (for
  example your Grok subscription beside a Grok API key), that connection answers before the backup on this Mac, and
  the conversation says which one answers and why. Checked on stand-in providers: the chosen one refused, the other
  answers and the backup is never asked; both refused, the backup answers and is named. When both online connections
  hang, the backup's first word comes after two waits instead of one.

## 0.5.0 experimental · release 50 · 26 November 2026

- When the mind answering you changes (your chosen one is refused or not answering and the backup on this Mac answers,
  or it comes back), the conversation says so once, plainly, with why. Before, only Settings said it.
- Settings says "Answering now" only of the mind its finding is about, with when it was found. Right after you chose
  another mind, it could word the old one's failure as the new one's.
- Quit tells your Telegram chat that Viventium is resting and that what you write waits. A restart never does. What you
  write while it rests is answered when you open it again.
- A cancel is said once.

## 0.5.0 experimental · release 49 · 26 November 2026

- When someone may be in danger, Viventium now gives a way to reach a person that works where they are (what they say,
  or else the time zone and region the Mac is set to), instead of one country's number. Checked on the same mind, old
  against new: outside the US and Canada 29 of 29 (20 of 30 before); at home 30 of 30; no false alarm on 35 look-alikes.
- Its mind is told the time zone and region the Mac is set to, beside the time, on every turn.

## 0.5.0 experimental · release 48 · 26 November 2026

The first public release.

**What it does**

- One conversation by voice, typing and Telegram, with a mind that can be interrupted.
- A first greeting in its own words after setup, with a short tour of the menu-bar controls. If the browser keeps the
  page silent, it waits and the page shows **Turn on sound**; it never speaks into silence.
- Background Workers for files, research and long tasks. Each request is one plain question with **Allow** and
  **Deny**, and **Allow commands and file edits for this job** lets a long job finish while you are away. A request
  nobody answers is refused for you and you are told.
- Memory in a Life folder on your Mac: recall, correction and forgetting.
- A Subconscious that thinks between answers, Feelings (a simulated mood that shapes how it talks), reminders, staying
  aware while you are away, and sleep and dreaming at night.
- A brain view where every light is a recorded step.
- Setup on a new Mac without Apple's developer tools: Homebrew's signed installer first, then its tools.
- It says plainly that it is an AI, on screen and in its first greeting, and answers signs of danger with care and a
  way to reach a person.
- On a Mac with no backup mind, a slow mind that has taken the question is waited for, up to 30 seconds.

**Known limits**

- The Mac app is not yet signed with an Apple Developer ID. Install from source for now.
- A Grok subscription is the only connection proven on a fresh Mac. ChatGPT and Claude sign-ins and API keys are less
  tested.
- Most browsers need one click on **Turn on sound** before the first greeting can be heard.
- A greeting written on the spot can take 20 to 35 seconds to start.
- On a spoken call there is no audible sign while a slow mind is thinking.
- A long job still needs one click from you before it can run by itself.
- No automatic updates yet.
- Telegram needs a bot you create yourself.
