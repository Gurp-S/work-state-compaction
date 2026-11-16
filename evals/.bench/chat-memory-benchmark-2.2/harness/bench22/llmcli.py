# -*- coding: utf-8 -*-
"""Small helper for question-writing / review scripts: calls go through the metering gateway (phase gen/review)."""
import json, re, os
from .systems import Gateway

def gw(run="gen21"):
    return Gateway(os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:18877/v1"), run=run, system="authoring")

def ask(model, prompt, phase="gen", tag="", system=None, max_tokens=3000, temperature=0.2, g=None):
    g = g or gw()
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    r = g.chat(model, msgs, phase, tag, temperature=temperature, max_tokens=max_tokens)
    return r["choices"][0]["message"].get("content") or ""

def ask_json(model, prompt, phase="gen", tag="", tries=3, **kw):
    last = None
    for _ in range(tries):
        t = ask(model, prompt, phase, tag, **kw)
        m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
        s = m.group(1) if m else t
        try:
            return json.loads(s)
        except ValueError:
            a, b = s.find("{"), s.rfind("}")
            c, d = s.find("["), s.rfind("]")
            for x, y in ((a, b), (c, d)):
                if x != -1 and y > x:
                    try:
                        return json.loads(s[x:y + 1])
                    except ValueError:
                        pass
            last = t
    raise ValueError("no json: " + str(last)[:200])
