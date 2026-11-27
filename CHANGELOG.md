# Changelog

What changed for people who use Viventium AI, one entry per public release, newest first.

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
