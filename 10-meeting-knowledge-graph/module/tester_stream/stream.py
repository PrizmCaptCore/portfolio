import os
"""KakaoTalk export -> time-ordered message stream."""

import re

CHAT = os.environ.get("CHAT_LOG", "chat_log.txt")
_DATE = re.compile(r"^-+\s*\d{4}년\s*(\d{1,2})월\s*(\d{1,2})일")
_MSG = re.compile(r"^\[([^\]]+)\] \[(?:오전|오후) ?\d+:\d+\] (.*)$")
_SYSL = re.compile(r"(님이.*초대|방장이 되어|삭제되었습니다|님이 (나갔|들어왔))")


def parse_stream(d0=(4, 15), d1=(5, 9), path=CHAT):
    """Time-ordered list of (day_tuple, '[actor] text') within [d0, d1]."""
    out, cur = [], None
    for ln in open(path, encoding="utf-8"):
        ln = ln.rstrip("\n")
        m = _DATE.match(ln)
        if m:
            cur = (int(m[1]), int(m[2]))
            continue
        if _SYSL.search(ln):
            continue
        mm = _MSG.match(ln)
        if mm and cur and d0 <= cur <= d1:
            out.append((cur, f"[{mm[1]}] {mm[2]}"))
    return out
