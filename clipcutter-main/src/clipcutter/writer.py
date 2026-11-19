"""Hook text, title, description and hashtags, in Gen Z voice.

Providers (config llm.provider):
  claude    - Anthropic API (best quality; needs ANTHROPIC_API_KEY or `ant auth login`)
  ollama    - local model via Ollama (free, offline)
  templates - built-in Gen Z lines, no AI at all (free, instant)
  auto      - claude if credentials exist, else ollama if running, else templates
"""
from __future__ import annotations

import json
import os
import random
import re
import urllib.request
from pathlib import Path

BANNED = ["epic", "awesome", "check this out", "amazing", "incredible", "you won't believe"]

STYLE_GUIDE = {
    "genz": (
        "Write like a Gen Z TikTok clipper. all lowercase, short, chaotic, funny. "
        "Use slang naturally (bro, fr, ong, nah, lowkey, cooked, aura, crashing out, "
        "built different, he's him, the way he—). Use 1-2 emoji max from 💀😭🔥😳🫠🫡. "
        f"Never use these cringe words: {', '.join(BANNED)}."
    ),
    "hype": "Write like a high-energy gaming highlights channel. CAPS for impact, 1 emoji max.",
    "clean": "Write clear, punchy, professional titles. No slang, no emoji.",
}

# keyword -> hook lines (templates fallback)
TEMPLATES = [
    (r"cop|police|wanted|star|chase|arrest", [
        "nah these cops are NOT real 😭", "bro had 5 stars in 0.2 seconds 💀",
        "the cops in gta 6 are built different fr", "he really tried to outrun them 😭"]),
    (r"crash|car|drive|drift|bike|plane|heli", [
        "bro cannot drive to save his life 💀", "the way he crashed— 🫠",
        "gta 6 physics got me crying 😭", "who gave him a license fr 💀"]),
    (r"die|dead|died|kill|shot|wasted", [
        "he's so cooked 💀", "bro did NOT see that coming 😭",
        "wasted in record time fr", "the aura loss here is crazy 💀"]),
    (r"heist|bank|money|rob|store", [
        "worst heist of all time ong 😭", "bro thought he was in a movie 💀",
        "the heist went left real quick 🫠"]),
    (r"lucia|jason|vice|leonida|miami", [
        "gta 6 is actually unreal fr 🔥", "vice city really said welcome back 😳"]),
]
GENERIC = [
    "wait for it… 💀", "bro really thought he was him 😭", "nah this is crazy 😳",
    "the way he just— 🫠", "he's cooked fr 💀", "i can't believe this happened 😭",
    "nobody was ready for this 😭", "this part goes crazy fr 🔥",
]
GTA_GENERIC = ["this is why i love gta 6 🔥", "gta 6 is actually unreal fr 🔥", "rockstar cooked with this one 🔥"]

# Hinglish (Roman Hindi) Gen Z hooks for Hindi videos
HI_TEMPLATES = [
    (r"cop|police|पुलिस|wanted|chase", ["bhai police ne toh hila diya 😭", "ye cops real hai kya 💀"]),
    (r"crash|car|गाड़ी|गाडी|drive", ["bhai ye driving dekho 💀", "physics ne toh pagal kar diya 😭"]),
    (r"detail|feature|फीचर|डिटेल|realistic|रियलिस्टिक", [
        "ye detail kisi ne notice nahi ki 😳", "rockstar ne pagalpan kar diya 🔥",
        "bhai ye feature sach mein hai?? 😳", "GTA 6 ka ye detail dekh ke hil gaya 🫠"]),
]
HI_GTA = ["bhai GTA 6 mein ye bhi hai?? 😳", "GTA 6 ka level hi alag hai 🔥", "rockstar ne bawaal kar diya 💀",
          "ye dekh ke GTA 5 bhool jaoge 😭"]
HI_GENERIC = ["bhai ye kya ho gaya 💀", "end tak dekhna 😳", "ye toh bawaal hai 🔥", "koi isko roko 😭",
              "bhai ne toh hila diya 🫠", "ye part sabse best hai 🔥"]
HI_QUESTIONS = ["tumhe kya laga? comment karo 👇", "GTA 6 ke liye ready ho? 😳", "1-10 rating do 🔥",
                "isse better kuch dekha hai? 💀"]

GTA_RE = re.compile(r"gta|grand theft|vice city|leonida|rockstar|जीटीए|ग्तिया|जीटीए|रॉकस्टार", re.I)
DEVANAGARI = re.compile(r"[\u0900-\u097F]")
BASE_TAGS = ["#fyp", "#viral", "#clips", "#trending"]
GTA_TAGS = ["#gta6", "#gtavi", "#gta", "#gaming"]

CAPTION_EMOJI_HI = [
    ("भाई", "💀"), ("पागल", "🤯"), ("बवाल", "🔥"), ("गज़ब", "🔥"), ("गजब", "🔥"), ("क्या", "😳"),
    ("हाहा", "😭"), ("मज़ा", "🔥"), ("रियलिस्टिक", "😳"), ("बाप", "😭"),
]
CAPTION_EMOJI = [
    (r"^(lol|lmao|haha+|hahaha+)$", "😭"), (r"^(dead|died|cooked|rip)$", "💀"),
    (r"^(fire|insane|crazy)$", "🔥"), (r"^(what|how|wait)\??$", "😳"),
    (r"^(bro|bruh)$", "💀"), (r"^(no way|omg)$", "😳"),
]


def caption_emoji(word: str) -> str:
    for hw, emo in CAPTION_EMOJI_HI:
        if hw in word:
            return emo
    w = re.sub(r"[^\w' ]", "", word.lower())
    for pat, emo in CAPTION_EMOJI:
        if re.match(pat, w):
            return emo
    return ""


def _clean(text: str, style: str) -> str:
    text = text.strip().strip('"').strip()
    for b in BANNED:
        text = re.sub(re.escape(b), "", text, flags=re.I)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text.lower() if style == "genz" else text


# ---------- providers ----------

_FAILED: set[str] = set()  # providers that failed this run; don't retry them per clip


def _has_claude_creds() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY")) or (Path.home() / ".config" / "anthropic").exists()


def _ollama_up() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=0.5)
        return True
    except Exception:
        return False


def _prompt(transcript: str, chat: list[str], title: str) -> str:
    chat_part = "\n".join(f"- {c}" for c in chat[:25]) or "(no chat)"
    lang = ("The speaker talks in Hindi: write hooks in Hinglish (Hindi in Roman letters, "
            "like 'bhai ye kya ho gaya 💀'). " if is_hindi(transcript) else "")
    return (
        f"A clip from the video \"{title}\". {lang}Transcript of what the speaker says:\n\"\"\"{transcript}\"\"\"\n\n"
        f"Chat reactions at the peak moment:\n{chat_part}\n\n"
        "Return ONLY a JSON object with keys:\n"
        '  "hooks": 3 different on-screen hook texts (max 8 words each) shown in the first 2 seconds. '
        "Create a curiosity gap; don't spoil the ending.\n"
        '  "best": index (0-2) of the strongest hook\n'
        '  "title": video title (max 70 chars)\n'
        '  "description": one short line for the post caption, ending with a question that baits comments\n'
        '  "hashtags": 5-8 hashtags'
    )


def _claude(prompt: str, system: str, model: str) -> dict | None:
    import anthropic

    client = anthropic.Anthropic()
    kwargs = {}
    if model in ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-2", "claude-fable-5-1"):
        kwargs = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    resp = client.beta.messages.create(
        model=model,
        max_tokens=2000,
        system=system,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )
    if resp.stop_reason == "refusal":
        return None
    text = "".join(b.text for b in resp.content if b.type == "text")
    return _json(text)


def _ollama(prompt: str, system: str, model: str) -> dict | None:
    body = json.dumps({"model": model, "system": system, "prompt": prompt,
                       "format": "json", "stream": False}).encode()
    req = urllib.request.Request("http://localhost:11434/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return _json(json.loads(r.read())["response"])


def _json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def is_hindi(text: str) -> bool:
    return len(DEVANAGARI.findall(text)) > 0.3 * max(1, len(re.sub(r"\s", "", text)))


def _templates(transcript: str, chat: list[str], seed: int, title: str = "", avoid: set | None = None) -> dict:
    rnd = random.Random(seed)
    blob = (title + " " + transcript + " " + " ".join(chat)).lower()
    gta = bool(GTA_RE.search(blob))
    hindi = is_hindi(transcript)
    pool: list[str] = []
    if hindi:
        for pat, lines in HI_TEMPLATES:
            if re.search(pat, blob):
                pool += lines
        pool += HI_GTA if gta else HI_GENERIC
        questions = HI_QUESTIONS
    else:
        if gta:
            for pat, lines in TEMPLATES:
                if re.search(pat, blob):
                    pool += lines
            pool += GTA_GENERIC
        pool += GENERIC
        questions = ["who's fault was this 💀", "rate this 1-10 😭", "would you have survived this?",
                     "be honest… 💀", "tag someone who needs to see this 😭"]
    fresh = [h for h in pool if h.lower() not in (avoid or set())]  # every clip of a video gets its own hook
    hook = rnd.choice(fresh or pool)
    tags = (GTA_TAGS if gta else []) + (["#hindi", "#india"] if hindi else []) + BASE_TAGS
    return {"hooks": [hook], "best": 0, "title": hook if len(hook) < 60 else hook[:57] + "…",
            "description": rnd.choice(questions), "hashtags": tags}


def write(transcript: str, chat: list[str], cfg: dict, seed: int, title: str = "", avoid: set | None = None) -> dict:
    style = cfg["style"]
    llm = cfg["llm"]
    provider = llm["provider"]
    if provider == "auto":
        provider = "claude" if _has_claude_creds() else ("ollama" if _ollama_up() else "templates")
    if provider in _FAILED:
        provider = "templates"

    system = "You write viral short-form video hooks and captions for gaming clips. " + STYLE_GUIDE[style]
    data = None
    used = provider
    try:
        if provider == "claude":
            data = _claude(_prompt(transcript, chat, title), system, llm["model"])
        elif provider == "ollama":
            data = _ollama(_prompt(transcript, chat, title), system, llm["ollama_model"])
    except Exception as e:  # network down, no credits, etc. -> never block the pipeline
        print(f"   ! {provider} failed ({type(e).__name__}: {e}); using templates for the rest of this run")
        _FAILED.add(provider)
    if not data or not data.get("hooks"):
        data = _templates(transcript, chat, seed, title, avoid)
        used = "templates"

    hooks = [str(h) for h in data["hooks"]]
    best = data.get("best", 0)
    hook = hooks[best if isinstance(best, int) and 0 <= best < len(hooks) else 0]
    tags = [t if t.startswith("#") else "#" + t for t in data.get("hashtags") or BASE_TAGS]
    if "#fyp" not in tags:
        tags.append("#fyp")
    return {
        "hook": _clean(hook, style),
        "title": _clean(str(data.get("title", hook)), style),
        "description": _clean(str(data.get("description", "")), style),
        "hashtags": tags[:10],
        "writer": used,
    }
