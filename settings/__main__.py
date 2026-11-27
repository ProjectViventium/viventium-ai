"""python -m settings show | apply < JSON | menu [apply < JSON] | applier | sample [voice] | install ID | recognize
                      | phone-off | own-sign-in NAME
                      | subconscious show|apply | scheduling show|apply | prompts show   (the pages of their own)"""
import json
import os
import sys

from settings import runtime, service

action = sys.argv[1] if len(sys.argv) > 1 else "show"
if action == "applier":
    runtime.applier()
elif action == "first-run-key":  # the native window, before the page is running
    name = sys.argv[2] if len(sys.argv) > 2 else "OPENAI_API_KEY"
    why = runtime.first_run_key(sys.stdin.read(301).strip(), os.environ, name)
    if why:
        print(why)
        sys.exit(1)
    print("API key saved.")
elif action == "setup-accounts":
    print(json.dumps(service.setup_accounts(os.environ)))
elif action == "setup-mind":
    sys.exit(0 if service.setup_mind(os.environ) else 1)
elif action == "own-sign-in":  # a sign-in Light makes itself, from start to end (the page starts it: runtime.sign_in)
    runtime.own_sign_in_done(sys.argv[2] if len(sys.argv) > 2 else "")
elif action == "chatgpt-connect":
    runtime.finish_chatgpt(sys.argv[2])
elif action == "install":  # one thing this Mac lacks, from start to end (settings/install.py)
    from settings import install
    sys.exit(install.run(sys.argv[2] if len(sys.argv) > 2 else ""))
elif action == "recognize":  # at each start (vx up): photo and video models already here, proved with no download
    from settings import install
    for item in install.recognize():
        print(f"{install.name(item)} was already on this Mac: its files are checked, and it is ready.", flush=True)
elif action in ("subconscious", "scheduling", "prompts"):  # a page of its own: its own two calls (prompts: shown only)
    import importlib
    page = importlib.import_module(f"settings.{action}")
    print(json.dumps(page.apply(json.load(sys.stdin)) if sys.argv[2:3] == ["apply"] else page.show()))
elif action == "menu":  # the menu bar's panel (tools/menubar/main.swift): what it shows, or one change from it
    print(json.dumps(service.menu_apply(json.load(sys.stdin)) if sys.argv[2:3] == ["apply"] else service.menu()))
elif action == "phone-off":  # ./vx restore: calling from the phone off until it is paired on this Mac again (no restart)
    if service.phone_off():
        print("Calling from your phone is off: its pairing never travels in a backup. Turn it on and pair it again in "
              "Settings, Channels, Phone.")
elif action == "sample":
    from settings import samples
    samples.main(sys.argv[2:])
else:
    print(json.dumps(service.apply(json.load(sys.stdin)) if action == "apply" else service.show()))
