# Changelog

What changed for people who use Viventium AI, one entry per public release, newest first.

## 0.5.0 experimental · release 61 · 28 November 2026

- A background result whose file went with Viventium's reply is no longer told a second time. Before, a result saying a
  Worker could not send anything, beside a reply that came with its file, could be judged not yet told and told again.
  Now the check that decides it is given the names of the files that went with the reply. When two requests are under
  way at once, each Worker's instructions also name the other requests already handed off, so each does only its own.
  Checked old against new on the same judge models, on 21 shapes of a result given with its files: 21 of 21 right on
  the Mac's own model (15 before) and on Grok (2 before), with every other case still right.
- When the mind you chose is refused or has used up its plan, a check-in is decided by the backup on your Mac instead
  of failing, so a planned wake-up still comes. A mind that is only slow is still skipped, as before. Checked with
  stand-in minds that refuse, are at their limit or cannot be reached.
- A conversation page left open while Viventium updated reads the new version's list of offered files, and asks for it
  once. Before, such a page asked again every half second for about four minutes, then drew file links the old way.
  Checked with the previous release's page against this version.
- The note saying which mind is answering no longer says "again" about a mind you just chose. On Telegram it is sent
  once and is not kept as part of the conversation; before, the conversation page showed it twice, and Viventium could
  read it back as its own words.
- Right after you approve the Grok sign-in, its row in Settings says Signed in. Before, for about 18 seconds it still
  offered Connect.
- Settings can disconnect the Telegram bot, so another one can be connected.
- On Telegram, a file sent with a reply no longer comes with a dead Download line above it: the file's name stays in
  the sentence, and the file itself follows.
- A background account found needing a log-in is tried last for a day, and one at its limit for 30 minutes, so jobs no
  longer wait on it first; it is still tried when nothing else answers. Its row in Settings now has Sign in, and
  signing in again ends the wait.
- A call set to use your ChatGPT plan now uses it while Viventium's Sign in with ChatGPT is connected. Before, that
  choice was always refused and the call used your chosen mind. Signed out or expired, the call keeps your chosen mind,
  and its log says why.
- The README says what Light, Ears and Wing are, where to paste the install command, and how to update a source
  install. The install guide describes the first hello as it is now: it sends only your name on the Mac, with the
  time, time zone and region every request carries, and asks one short question by name. The picture of an earlier
  greeting is out until it is retaken.
- Check-ins keep a pace of their own. Each check-in now also decides when Viventium looks in next, from 10 minutes to
  3 hours, as the moment and your day suggest; when it gives no time, the pace set in Settings holds, as before. A
  wake-up check-in in the morning is followed by another look 10 to 30 minutes later, then another within the hour.
  Checked on Grok, old against new, five runs a case: the next look was chosen and in range in 14 of 15 morning runs
  (it could not be chosen before), the morning word was spoken as often as before, and no other check-in decided
  worse.
- Known limits: a conversation page open during an update still shows the previous version's page until it is reloaded
  (it no longer keeps asking for its files meanwhile). Updating a source install over its folder keeps any file a later
  release removes, and Viventium reads some folders by name, so such a file could still be used; a release that removes
  one names it here, with what to delete (this release removes none). A call on your ChatGPT plan is checked with
  stand-in sign-ins only, not yet on a real call. A morning wake-up word can be abrupt, and a later check-in can
  guess wrongly when your day began. A check-in's next look, decided by the backup on your Mac, is checked with
  stand-ins only.

## 0.5.0 experimental · release 60 · 28 November 2026

- A result of background work comes back where you asked for it, once. Before, while the backup on your Mac answered
  for your chosen mind, a result asked for on Telegram could be held for the conversation page instead: a file, a
  picture or an answer never reached Telegram until you asked again, and the page then told it a second time. Now a
  reply from the backup is known as the backup's from its first word, a place to tell a result is one of telegram,
  call or the page (or, when none is named, where you asked), and an answer that gives a result marks it told.
  Checked with stand-in minds on the same path: the result is told on Telegram, and never again on the page. A
  reminder set the same way comes where it was asked for too, never only on the page.
- Viventium's first words after setup are now one short question to you by name, and it waits for your answer; it no
  longer opens with the time, the Mac or what it is. When you answer, it reacts to what you said, then tells you about
  Wing and Settings in a line each, lighting each in the panel as it speaks, and asks whether you want to see more or
  jump into something. Those lines are written during setup with the first question, so they play at once; if your
  answer starts work, they are left out. Checked on Grok on your subscription, old against new, with the greeting
  written as it opens (no setup draft), on made-up first answers: its first words in about 3 seconds (about 75 before,
  when most often nothing came), and its reply about 8 to 10 seconds after you began answering (about 78 before).
- When the conversation page catches up on results told while it was closed, each file is offered once, a picture is
  shown as a picture (with its download link), and a file link that points at nothing is no longer drawn. Checked on
  the page with results held the same way.
- GPT-6.2 Sol can be chosen as Viventium's mind on your own OpenAI key. If your OpenAI provider does not offer it yet,
  Settings says so plainly and nothing changes. Background Workers on a Codex sign-in stay on GPT-6.1 Sol until
  GPT-6.2 Sol is measured on ordinary Worker jobs.
- A mind whose key or subscription is refused, or has reached its limit, at the moment Viventium starts no longer stops
  it from starting: the backup on your Mac answers meanwhile, as it does during a conversation. Only a model your
  provider does not have at all is refused, with one plain sentence. Checked with a stand-in provider answering each
  of those ways.
- The install guide matches the app as it is now: the menu bar's power control is Turn off, and its pictures show the
  current panel.
- Known limits: GPT-6.2 Sol's speed and quality as Viventium's mind are not measured here yet. Asking on Telegram for a
  result to be shown on the conversation page instead is not understood yet: it comes back where you asked. A longer
  first answer after setup can take 11 to 30 seconds to be answered on Grok, and after answering a question you asked
  first, Viventium still tells you about Wing and Settings. If a conversation page was open while Viventium updated,
  reload that page once to get this version's page; until then it shows files as the previous version did, and asks
  for the list of offered files again for a few minutes.

## 0.5.0 experimental · release 59 · 28 November 2026

- In Settings on a phone's width, the Brain section's View live and Speed and smarts stay side by side on their own
  line under the heading. Checked on the settings page at a phone's width and on a desk.
- Checked again on the conversation page: Stop ends an answer at once and the rest never comes, and in Wing or Listen
  only each new thing said brings one short note that leaves by itself.

## 0.5.0 experimental · release 58 · 28 November 2026

- Background work looks around before it starts. A Worker's instructions now ask it to take in the situation first: the
  tools, apps, accounts and AI apps on the computer, and the history they keep, so it learns how you like things done,
  follows your request the way you would, and owns the request through to a useful result.
- Viventium no longer announces that it is an AI or describes the machine: its first greeting no longer says so (the
  line under the message box went in the last release). Asked directly, it still answers truthfully.
- Talk, Wing or Listen only chosen on the conversation page is kept for your next call again, the way the menu bar and
  Settings keep it. Each choice carries when it was made, so a choice on the page never undoes a later one from the
  menu bar, and settings are written one at a time, so changes made at the same moment from different places are all
  kept. Checked without a page: a late save from the page left the menu bar's later choice in place, and changes from
  three places at once were all kept (before, the late save undid the later choice and most of those changes were
  lost); on the page, a choice made there carries into a new call.
- Known limit: in Settings, on a phone's width, the Brain section's View live and Speed and smarts could land on
  separate lines.

## 0.5.0 experimental · release 57 · 27 November 2026

- Calls can have their own mind. With a call's mind configured (for example GPT-6.1 Sol on your own OpenAI key), the
  words Viventium speaks on a call are asked of that mind, and your chosen mind is its cloud fallback: if the call's
  mind has given no word after a few seconds, your chosen mind is asked beside it and the first of the two to speak
  answers. The backup on your Mac answers only when both stay silent for their whole wait. Your typed replies, on the
  page and on Telegram, keep your chosen mind. Checked with stand-in minds: a spoken turn answered by the call's mind,
  typed and Telegram turns by your chosen mind, a silent call mind covered by your chosen mind before the backup's
  time, both silent answered by the backup, and every reply ending as answered in its own record.
- When both cloud minds stay silent on a call, or a read reply's first ask hangs and is asked again, the backup model
  on your Mac starts loading right away, in a request of its own, so it is ready if it is needed and a reply answered
  from the cloud meanwhile no longer cuts its load short. It is never loaded for one slow mind, and it stays loaded
  only for the backup server's own keep-alive.
- A result's reply is now written knowing what was said on your other channels since: your latest words there, and a
  reply there that already gave the result, reach it, so it decides itself whether to tell it briefly or hold it.
- Adding an account while another account of the same service is still signing in is refused with a plain note to
  finish it in the browser. A sign-in left unfinished ends by itself after ten minutes, so it never blocks the next
  one.
- Recall's two searches, by words and by meaning, now run at the same time, each inside recall's wait. Before, a word
  search slowed by a busy Mac could use all of recall's time and the search by meaning never ran. Now what each found
  is given, and a search that did not finish in time says so instead of reading as if nothing was found.
- Writing where you are and starting a quick helper no longer pause Viventium's voice and replies while the disk or
  the Mac is slow.
- When your ChatGPT plan reaches its limit in the middle of a reply, Viventium now reads it as that limit: the plan
  rests and is asked again only after its rest, each rest longer than the last, while the backup answers. Before, the
  reply ended with "Connection error." and every new turn asked the plan again. The note that the backup is answering
  is said again when you choose another mind, and it no longer comes back at the start of the backup's later replies.
  Checked on a development copy's page, typed turn by turn, and with stand-in minds.
- When the backup on your Mac tells you a finished result, it is asked as a backup: it never speaks a tool's name or
  its arguments. Before, after a telling that could not be confirmed, it could read a tool call out loud on a call.
- When Viventium's own words said it would look into your ask, and the check that decides on background work came in
  after those words, the work now starts. Checked with made-up turns on the configured helper, old wording against
  new: the work followed 17 times in 18 (9 before); a refusal or a question back never started work (as before); and
  where Viventium's reply had already answered in full, work that was not needed started 4 times in 15 (13 before), a
  known limit.

- While Wing or Listen only is on, each new thing you say brings one small toast under the mode switch for a few
  seconds: "Listen only: I'm listening, not talking." or "Wing mode: I'll answer when you talk to me." So when no
  answer comes, you know why. It replaces the line that showed after a turn kept quiet.
- A Stop button in the chat: while Viventium is thinking or answering, the send button becomes Stop (with nothing
  typed). It ends that answer at once; work already handed off goes on.
- The line "Viventium is an AI." under the message box is gone.
- Settings: Brain has "View live" (its live brain) beside "Speed and smarts".
- The menu-bar panel says what each control is: Listen only is "Listen but don't talk"; Local is "Run everything
  locally: maximum privacy, works fully offline"; Hybrid is "Hybrid: a good balance of privacy, speed and
  intelligence"; Cloud is "Use online cloud AI". The power button and the app menu say "Turn off".
- The app runs once per Viventium folder. A copy started before the app was updated or renamed is ended when the new
  one starts (it no longer stays as a second mark in the menu bar), and a copy you opened gives its mark to the one
  that starts with your Mac. The development copy shows a small </> sign on its menu-bar mark.

## 0.5.0 experimental · release 56 · 27 November 2026

- Continuous awareness now comes alive the way a close friend would, not only when something is owed. With nothing
  pending, the first moment of your morning can be a hello of its own, and after a long quiet day it may reach out.
  It still gives you room: right after you talked, while work runs, when you are busy, or when its last words went
  unanswered. Checked on the same mind (GPT-6.1 Sol), old words against new: a word after a long quiet day 10 of 10
  (0 of 10 before), room given every time (as before), promised check-ins and retries as before, and a promise made
  further back in the conversation is now taken up. A morning hello with nothing pending: 20 of 20 with Feelings on
  (0 before), because a check-in now chooses with how it feels, as its words ask. With Feelings off it comes less
  often.
- What a check-in sees now includes, from its own records: work that ended lately and was told to you (what was asked
  and how it ended), and whether the last words between you were its own. On Grok, it now leaves work it already
  finished for you alone far more often, instead of coming back to it.
- A check-in is decided and written by the mind answering you. While your chosen mind is in place, it alone is asked,
  and it is waited for up to 30 seconds, since nobody is waiting on a check-in; it is never handed to the backup on
  your Mac. While the backup answers your turns, it decides the check-in too, and the check-in's record names the mind
  that decided it.
- A check-in that chose to say something is told what that message can do: what it sees is its look around, and the
  message uses no tool. Before, on Grok, it could say it would look around first, a look it could not take.
- A check-in whose reply came back empty from your chosen mind (no word in its wait) is asked once more at once, fresh,
  of the same mind. Before, that moment passed in silence. If it is empty again, the check-in passes and says so ("its
  reply was empty twice"), and the next one may try again. It is never handed to the backup on your Mac while your
  chosen mind is in place. Checked with stand-in minds on both ways a check-in decides: empty then words, it speaks;
  empty twice, it passes after the second ask; your own words meanwhile, it is not asked again; staying quiet by
  choice is never asked again.
- When Deep memory or recall finds a summary of an earlier conversation, Viventium is now also shown what came of it:
  what was decided, what was promised and what was found or suggested there, as it stands after your corrections and
  forgets. Before, it was shown only the part that matched your words, often what you had asked for back then, so it
  could wrongly say an earlier list was incomplete. Checked without a model, on a real
  request and its memory: the earlier list now reaches recall every time it is asked for (once in six before), and
  Deep memory names it on Grok on your subscription five times out of five (never before). Everyday turns are shown
  exactly what they were.
- What Viventium suggested in a conversation no longer reaches its standing knowledge of you as if you had said it,
  whichever way the summary writes its sections. Checked on a real set of summaries: only Viventium's own suggestions
  moved out, and nothing you said, decided or stated was lost.
- When Viventium's chosen mind takes your message and then ends with nothing at all, no words and no action, that no
  longer ends in silence. It goes as a request that hung goes: on a typed or Telegram message the mind is asked once
  more, fresh, and the backup answers if it still has nothing; on a call the backup answers; and if no mind answers,
  you are told plainly that Viventium's mind did not answer. A silence Viventium chooses stays silent, and a reply
  stopped because the work already started is not treated as a failure. Checked without a model on Telegram and on a
  call: before, such a reply left nothing at all; now it is answered or you are told. This guards against a case
  first seen in a test run, before it can reach you.
- Live, the brain view, now shows every light of a turn when the computer is busy. A part that lit twice in quick
  succession could lose its first light, so Coordinator or Conscious mind sometimes lit once where the turn had them
  twice. Checked without a model, with the page's own clock held and every step then run at once: before, those first
  lights were lost every time; now each shows.
- Known limits:
  - On minds that make a check-in's choice in one word, such as Grok on your subscription and the model on your Mac,
    a check-in can say something or stay quiet but does not yet start work it promised you. On GPT-6.1 Sol it can.
  - On Grok, after you call off something it had promised, a later check-in may still mention it lightly. It does not
    take it up again.
  - On Grok, after it offered you something and you have not answered yet, the next check-in may speak again before
    you do.

## 0.5.0 experimental · release 55 · 27 November 2026

- Viventium's marker for "start a new message here" no longer shows up in your messages. It was split only when it
  stood on its own line, or mid-line with spaces around it on some minds; written glued to the next word it reached
  you as text. Now, outside code and quotes, it starts a new message wherever it stands, on every mind, and is never
  spoken or kept in its history. Checked without a model on three kinds of mind, on real replies where it showed and
  on made-up ones: it never remains (before, the glued ones kept it); in code, quotes or written escaped it stays.
- Each tool Viventium uses while answering on Telegram is now kept in its own log, with when it started and ended,
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
  the moment it hears you: one line under the mode switch, with a Talk button. One tap and it answers from then on,
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
- `./vx test-telegram` refuses to run while Viventium is running: it would have stopped Viventium and answered its test
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
