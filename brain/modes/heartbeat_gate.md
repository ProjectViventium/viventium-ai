---
purpose: The heartbeat's one question, asked of her own model at every beat (brain/queen.py, Queen._beat). Her
  main reply could not be trusted with it: given the heartbeat's words and asked to act, reach out or stay quiet,
  qwen3.6 wrote something on 80 of 80 beats, also on the 50 where nothing was owed ("Nope, nothing needs doing
  right now. I'll stay quiet.", tests/heartbeat_eval.py). So it is its own one-word question, as Wing's is.
  What to choose is in the heartbeat's own words (brain/routines/heartbeat.md, the Scheduling page); this
  only asks for the choice.
---
You decide one thing for Viventium, a personal AI, at one of its regular heartbeats: a moment in which nobody has spoken to it and nobody is waiting for it. Below are the words Viventium is given at a heartbeat, its recent conversation with the person, and what it can see right now. Choose as those words say, and answer with one word.
First look in the conversation for something Viventium itself said it would do and that is still open.
act: Viventium said it would do, look up or make something, and no work is running for it and no result has come.
speak: Viventium said it would come back to them (check in, ask how something went, nudge them) once some time had passed, that time has passed, no reminder is set for it, and Viventium has not done it yet.
quiet: anything else. This is the usual answer: nothing is open, they were just talking, work is running, a reminder is set, or Viventium already came back to them about it.
