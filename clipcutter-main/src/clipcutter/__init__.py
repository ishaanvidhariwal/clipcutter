"""ClipCutter: livestream -> viral vertical clips, automatically."""
from __future__ import annotations

import argparse
import sys


def _common(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--clips", type=int, help="clips per video")
    sp.add_argument("--layout", choices=["blur", "crop", "split", "auto"])
    sp.add_argument("--style", choices=["genz", "hype", "clean"])
    sp.add_argument("--llm", choices=["auto", "claude", "ollama", "templates"], help="who writes hooks/titles")
    sp.add_argument("--whisper", help="whisper model, e.g. mlx-community/whisper-base-mlx (faster)")
    sp.add_argument("--config", help="path to config.yaml")


def _enable_hindi_text() -> None:
    """Pillow shapes Hindi (matras, conjuncts) only if it can find libfribidi (brew install fribidi).
    Homebrew's lib folder isn't on the default search path, so restart once with it added."""
    import os
    if sys.platform != "darwin" or os.environ.get("CLIPCUTTER_LIBS"):
        return
    lib = next((d for d in ("/opt/homebrew/lib", "/usr/local/lib") if os.path.exists(f"{d}/libfribidi.0.dylib")), None)
    if not lib:
        return
    env = dict(os.environ, CLIPCUTTER_LIBS="1",
               DYLD_FALLBACK_LIBRARY_PATH=f"{lib}:/usr/local/lib:/usr/lib")
    os.execve(sys.executable, [sys.executable] + sys.argv, env)


def main() -> None:
    _enable_hindi_text()
    p = argparse.ArgumentParser(prog="clipcutter", description="Turn streams into ready-to-post clips.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="clip one link (YouTube, Twitch, Kick, …) or a local video file")
    r.add_argument("target", help="URL or path to a video file")
    r.add_argument("--chat", help="chat log file (optional)")
    _common(r)

    a = sub.add_parser("add", help="track a creator (channel URL)")
    a.add_argument("url")
    a.add_argument("--name")
    a.add_argument("--keyword", help="only clip videos whose title matches, e.g. 'gta'")
    a.add_argument("--permission", action="store_true", help="you have permission to post their clips")

    rm = sub.add_parser("remove", help="stop tracking a creator (name or URL)")
    rm.add_argument("who")

    sub.add_parser("creators", help="list tracked creators and their stats")

    t = sub.add_parser("track", help="check all creators for new videos and clip them")
    t.add_argument("--every", type=float, help="keep running, checking every N minutes")
    t.add_argument("--backfill", type=int, default=1, help="for a newly added creator, clip this many latest videos")
    t.add_argument("--limit", type=int, help="max videos to clip per check")
    t.add_argument("--retry", action="store_true", help="retry failed videos")
    _common(t)

    d = sub.add_parser("discover", help="find top creators for a topic on YouTube")
    d.add_argument("query", nargs="?", default="gta 6 live stream")
    d.add_argument("--limit", type=int, default=50, help="search results to scan")
    d.add_argument("--add-top", type=int, default=0, help="also start tracking the top N channels")

    sub.add_parser("dashboard", help="rebuild the dashboard page")
    sub.add_parser("doctor", help="check that everything needed is installed")

    sv = sub.add_parser("serve", help="open the web app (paste links, tracker, clips)")
    sv.add_argument("--port", type=int, default=8787)
    sv.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to allow phones on your Wi-Fi")
    args = p.parse_args()

    from . import config, tracker

    cfg = config.load(getattr(args, "config", None))
    for key in ("clips", "layout", "style"):
        if getattr(args, key, None):
            cfg[key] = getattr(args, key)
    if getattr(args, "llm", None):
        cfg["llm"]["provider"] = args.llm
    if getattr(args, "whisper", None):
        cfg["whisper_model"] = args.whisper

    try:
        if args.cmd == "run":
            from . import pipeline
            pipeline.run(args.target, cfg, args.chat)
        elif args.cmd == "add":
            c = tracker.add(args.url, args.name, args.keyword, args.permission)
            print(f"tracking {c['name']} ({c['platform']}). run: clipcutter track")
        elif args.cmd == "remove":
            print("removed" if tracker.remove(args.who) else "not found")
        elif args.cmd == "creators":
            rows = tracker.summary(cfg)
            if not rows:
                print("no creators yet: clipcutter add <channel url>")
            for c in rows:
                perm = "✓" if c.get("permission") else "✗"
                print(f"{c['name'][:28]:28} {c['platform']:8} perm {perm}  clipped {c['done']:3}  "
                      f"clips {c['clips']:4}  queue {c['new']:2}  failed {c['failed']:2}")
        elif args.cmd == "track":
            if args.retry:
                print(f"retrying {tracker.retry_failed(cfg)} failed videos")
            tracker.run(cfg, backfill=args.backfill, every=args.every, limit=args.limit,
                        log=lambda m: print(m, flush=True))
        elif args.cmd == "discover":
            chans = tracker.discover(args.query, args.limit)
            print(f"top channels for {args.query!r}:\n")
            for i, c in enumerate(chans[:20], 1):
                print(f"{i:2}. {c['name'][:30]:30} {c['views']:>13,} views  {c['videos']} vids  {c['url']}")
            for c in chans[: args.add_top]:
                try:
                    tracker.add(c["url"], c["name"], None, False)
                    print(f"   + tracking {c['name']}")
                except SystemExit:
                    pass
        elif args.cmd == "serve":
            from . import server
            server.serve(args.port, args.host, getattr(args, "config", None))
        elif args.cmd == "doctor":
            sys.exit(doctor())
        elif args.cmd == "dashboard":
            from . import dashboard
            print(dashboard.build(cfg, tracker.db(cfg), tracker.load_creators()))
    except KeyboardInterrupt:
        sys.exit(130)


def doctor() -> int:
    """Print what's installed and what's missing. Exit code 1 if something required is missing."""
    import shutil
    import subprocess

    from . import system

    ok = True

    def line(good: bool, name: str, detail: str, required: bool = True) -> None:
        nonlocal ok
        mark = "✅" if good else ("❌" if required else "⚠️ ")
        print(f"{mark} {name:22} {detail}")
        if required and not good:
            ok = False

    print(f"ClipCutter doctor  ({sys.platform}, python {sys.version.split()[0]})\n")
    ff = shutil.which("ffmpeg")
    line(bool(ff), "ffmpeg", ff or "missing: install ffmpeg (see docs/SETUP.md)")
    if ff:
        enc = system.encoder_args("8M")[1]
        line(True, "video encoder", enc + ("  (hardware, fast)" if enc != "libx264" else "  (CPU)"))
    js = system.js_runtimes()
    line(bool(js), "JS runtime (YouTube)", ", ".join(js) or "missing: install Node.js or Deno, else YouTube gives HTTP 403")
    try:
        bf = system.bold_font()
        line(True, "caption font", bf)
    except SystemExit as e:
        line(False, "caption font", str(e))
    hf = system.hindi_font()
    line(bool(hf), "Hindi font", hf[0] if hf else "missing: Hindi captions will show boxes (install Noto Sans Devanagari)", False)
    line(system.text_shaping_ok(), "Hindi text shaping", "ok" if system.text_shaping_ok()
         else "missing libfribidi: Hindi matras may look wrong (mac: brew install fribidi, linux: apt install libfribidi0)", False)
    ef = system.emoji_font()
    line(bool(ef), "emoji font", ef or "missing: emoji left out of captions (linux: apt install fonts-noto-color-emoji)", False)
    backend = system.whisper_backend()
    try:
        __import__("mlx_whisper" if backend == "mlx" else "faster_whisper")
        line(True, "speech-to-text", backend + ("  (Apple GPU)" if backend == "mlx" else "  (CPU/CUDA)"))
    except ImportError:
        line(False, "speech-to-text", f"{backend} not installed: run `uv sync`")
    try:
        import cv2
        line(hasattr(cv2, "CascadeClassifier"), "facecam detection", f"opencv {cv2.__version__}", False)
    except ImportError:
        line(False, "facecam detection", "opencv missing: run `uv sync`", False)
    import os
    key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    line(key, "AI hooks (optional)", "ANTHROPIC_API_KEY set" if key else "not set: built-in Gen Z hook lines are used", False)
    print("\n" + ("All required parts are installed. Run: uv run clipcutter serve" if ok
                  else "Fix the ❌ items above, then run this again."))
    return 0 if ok else 1
