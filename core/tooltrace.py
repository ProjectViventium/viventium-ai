"""Her tool calls in her turn log, the same rows on every channel (a call: call/agent.py; Telegram: chat/telegram.py):
each call's start and end as LiveKit reports them (tool_event: its update, its name, its call id), and the call itself
once it has run (tool: its name, arguments, output), each end and each call with the seconds it took from its start.
So a turn that went wrong can be traced afterwards, whichever channel it came on."""
import time


def follow(session, note) -> None:
    """Note every tool call of this session (an AgentSession) with `note(kind, **fields)`, the channel's own."""
    started: dict[str, tuple[float, str]] = {}  # call id -> (when it started, its name)

    def took(call_id) -> dict:
        began = started.get(call_id)
        return {"seconds": round(time.time() - began[0], 3)} if began else {}

    @session.on("tool_execution_updated")
    def _updated(ev) -> None:  # started / progress (silent or spoken) / ended / reply status
        update = ev.update
        fields = update.model_dump(mode="json", exclude={"function_call"})
        if getattr(update, "function_call", None) is not None:
            fields["name"], fields["call_id"] = update.function_call.name, update.function_call.call_id
        if fields.get("type") == "tool_call_started" and fields.get("call_id"):
            started[fields["call_id"]] = (time.time(), fields.get("name", ""))
        elif fields.get("type") == "tool_call_ended" and fields.get("call_id"):
            fields.setdefault("name", (started.get(fields["call_id"]) or (0, ""))[1])
            fields.update(took(fields["call_id"]))
        note("tool_event", update=type(update).__name__, **fields)

    @session.on("function_tools_executed")
    def _executed(ev) -> None:
        for call_, output in ev.zipped():
            note("tool", name=call_.name, call_id=call_.call_id, args=call_.arguments,
                 output=getattr(output, "output", None), **took(call_.call_id))
            started.pop(call_.call_id, None)
