"""Her first hello is never spoken into a page that cannot play it.

A browser keeps a page silent until the person has clicked or typed on it (Safari: "Stop Media with Sound", the default
for every site; Chrome: no sound on a site never used before). Her page opens by itself after setup, so nothing the
person did allows sound on it. On a clean Mac she spoke her whole first greeting, the page showed every
word and lit each control, and the browser played none of it; LiveKit knew (its playback state was false) and its
"Start Audio" control sat below the full-height page where nobody sees it.

So before she speaks her first greeting she asks the page (RPC "viv.sound"): it makes a real try to play her own track
and answers "on" only when that track is playing. On "off" the page shows one plain control ("Turn on sound"; any
first click or key press on the page does the same) and tells her when sound is on (text stream "viv.sound"); she
waits for that, or for the person to say something first, and then greets. Nothing is claimed while she waits
(core/live.first_conversation(claim=False); call/agent.py first_hello): a page closed meanwhile leaves the greeting whole for the next one."""
import asyncio
import contextlib

ASK_AGAIN = 5.0  # while she waits for the page's "on", she also asks again this often (a lost message costs 5 s at most)


async def page_sound(ask, told: asyncio.Event, said, note, *, tries: int = 3, pause: float = 1.0) -> str:
    """Wait until her voice can be heard on the page. ask() -> "on" | "off" (may raise; .code = LiveKit's RPC code);
    told: set when the page says sound is on; said() -> the person spoke or typed first.
    "on": the page played her track. "said": the person went first (she follows their lead; no greeting over them).
    "unknown": the page could not be asked (three asks a second apart failed, an older page's "no such method"
    included): she greets as she did before
    this existed, and the log says so: a greeting nobody can be asked about is better than none."""
    held = False
    failed = 0
    while True:
        if said():
            return "said"
        if told.is_set():
            return "on"
        try:
            answer = await ask()
        except Exception as e:  # noqa: BLE001 (every failure is counted; none stops the conversation)
            failed += 1
            if failed >= tries:  # (an unknown method too: a page still mounting answers it, so it is asked again)
                if not held:  # (once the page has answered "off" she keeps waiting: it is known to be silent)
                    note("greeting_sound_unknown", error=f"{type(e).__name__}: {str(e)[:120]}")
                    return "unknown"
            await asyncio.sleep(pause)
            continue
        failed = 0
        if answer == "on":
            return "on"
        if not held:
            held = True
            note("greeting_held", reason="the page cannot play sound until the person clicks or types")
        for _ in range(int(ASK_AGAIN)):  # (her 1 s look at whether the person went first; asked again after ASK_AGAIN s)
            if told.is_set() or said():
                break
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(told.wait(), 1.0)
