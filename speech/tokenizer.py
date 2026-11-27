"""LiveKit sentence boundaries, with the voice's declared tags kept with their words."""
import re

from livekit.agents import tokenize
from livekit.agents.tokenize import token_stream


class SentenceTokenizer(tokenize.SentenceTokenizer):
    def __init__(self, tags, *, context_sentences=0):
        self._tags = tuple(tags)
        self._context_sentences = context_sentences
        self._base = tokenize.blingfire.SentenceTokenizer(retain_format=True, xml_aware=True)

    def _split(self, text):
        parts = self._base.tokenize(text)
        merged, following = [], 0
        for part in parts:
            start = part.lstrip().lower()
            # A complete or arriving tag after a sentence belongs to that sentence's request.
            marked = start.startswith("[") and any(
                start.startswith(f"[{tag}]") or f"[{tag}]".startswith(start) for tag in self._tags
            )
            if merged and (marked or not start or following):
                merged[-1] += part
                following = max(0, following - 1)
            else:
                merged.append(part)
            # Blingfire can already join a tag after punctuation to the sentence on each side.
            # Only an internal tag still needs the next sentence's context.
            tag = re.search(r"\[(?:" + "|".join(map(re.escape, self._tags)) + r")\]", part, re.I) \
                if self._context_sentences and self._tags else None
            between = tag and re.search(r"[.!?]\s*$", part[:tag.start()])
            if tag and not marked and not between:
                following = self._context_sentences
        pos, result = 0, []
        for part in merged:
            at = text.find(part, pos)
            at = pos if at < 0 else at
            result.append((part, at, at + len(part)))
            pos = at + len(part)
        return result

    def tokenize(self, text, *, language=None):
        return [part for part, _, _ in self._split(text)]

    def stream(self, *, language=None):
        return token_stream.BufferedSentenceStream(tokenizer=self._split, min_token_len=20, min_ctx_len=10,
                                                   xml_aware=True)
