"""Her settings: a small application of its own.

    catalog.py   what can be chosen (data: parts, providers, models, plain words)
    store.py     where a choice is kept (a marked block in the private profile files; her own small memory)
    runtime.py   the adapter to what runs (vx, Keychain, sign-ins, a restart that waits for a calm moment)
    service.py   the two calls the page makes: show() and apply()
    samples.py   a short recording of each voice, to hear before choosing

The page is call/ui/app/settings; it talks to this through one route (call/ui/app/api/settings).
"""
