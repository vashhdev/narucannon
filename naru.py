#!/usr/bin/env python3
"""
naru.py - stream the NaruCannon Recut in mpv: Naruto and Naruto Shippuden with the
filler cut out, English dub or Japanese audio with English subs.

Pipeline:
  1. list the NaruCannon share on pixeldrain (/api/filesystem/<share>?stat): one
     folder per arc, "1 - Land of Waves" through "12 - Sarada Uchiha"
  2. list every arc folder, in parallel, for its episodes, and its "Extended
     Episode(s)" folder for the longer cuts some episodes have
  3. hand mpv https://pixeldrain.net/api/filesystem/<share>/<arc>/<file>: a plain
     .mp4 it streams with range requests (seeking works, nothing is saved)

Sub and dub are separate shares, and the sub files have the subtitles burned into the
picture, so there are no tracks to pick: --sub / --dub only choose the share. The
links never expire, so one mpv window plays on from arc to arc.

Usage:
  python naru.py                     # INTERACTIVE: continue where you left off, or pick
                                     # audio, arc and episode
  python naru.py pain                # skip the arc picker (any part of the arc's name)
  python naru.py pain 7 --dub        # Pain's Assault 07, then on and on until you quit
  python naru.py pain 3-9 --dub      # just these
  python naru.py pain 3- --dub       # 3 to the end of the arc
  python naru.py 4.5                 # arcs by number work too
  python naru.py --list              # every arc. `naru.py pain --list`: its episodes
  python naru.py pain --m3u          # a playlist of the whole arc, for a phone
  python naru.py --setup             # find or install mpv, then exit

Players:
  desktop : mpv, installed on first run if missing (winget/scoop/choco, brew/port,
            apt/dnf/pacman/zypper/apk/xbps/nix, flatpak as a last resort)
  android : under Termux, the mpv-android app (is.xyz.mpv) gets the episodes as one
            playlist; `naru --mpv-conf` is its opening and ending skipper

Interactive controls:
  pickers : type to narrow the list, up/down arrows to move, Enter to select, Esc to cancel
  menus   : press the number, or just Enter for the default
"""

import argparse
import base64
import codecs
import glob
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import sysconfig
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

__version__ = "1.1.0"

NAME = "NaruCannon"
API = "https://pixeldrain.net/api/filesystem/"
# the NaruCannon Recut shares. pixeldrain.net/d/<id> opens one in a browser
SHARES = {"sub": "CEG3sGRE", "dub": "qqyKh8x5"}
UA = {"User-Agent": "Mozilla/5.0 (naru.py)"}
LANG_LABEL = {"sub": "Japanese audio, English subs", "dub": "English dub"}

ARC_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*-\s*(.+?)\s*$")             # "4.5 - Kakashi Chronicles"
# "[NaruCannon Recut] Five Kage Summit 14 Extended (Sub).mp4" -> 14, extended
EP_RE = re.compile(r"(\d+)(\s+extended)?\s*(?:\([^()]*\))?\s*\.[a-z0-9]+$", re.I)
VIDEO = (".mp4", ".mkv", ".webm", ".m4v", ".avi", ".mov")

# ------------------------------------------------------------------ interactive
# single-key input: msvcrt on Windows, termios/tty on POSIX.
try:
    import msvcrt                       # Windows
except ImportError:
    msvcrt = None
try:
    import termios, tty, select         # POSIX
except ImportError:
    termios = None

CSI = "\x1b["
HL = CSI + "7m"       # reverse video (highlight)
DIM = CSI + "2m"
RST = CSI + "0m"


def interactive_ok():
    """true if we can drive a raw-key TUI on this terminal."""
    return (bool(msvcrt) or bool(termios)) and sys.stdin.isatty() and sys.stdout.isatty()


def _enable_vt():
    """turn on ANSI escape handling in the Windows console (no-op elsewhere)."""
    if msvcrt:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, mode.value | 0x0004)


def _getkey():
    """block for one keypress. return ('char', c) or ('key', name)."""
    if msvcrt:
        c = msvcrt.getwch()
        if c in ("\x00", "\xe0"):        # arrow / function-key prefix
            c2 = msvcrt.getwch()
            return "key", {"H": "up", "P": "down", "K": "left", "M": "right"}.get(c2, "")
        if c in ("\r", "\n"):
            return "key", "enter"
        if c == "\x08":
            return "key", "backspace"
        if c == "\x1b":
            return "key", "esc"
        if c == "\x03":
            raise KeyboardInterrupt
        return "char", c
    # POSIX: read one key in cbreak mode (OPOST kept so \n still maps to \r\n)
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd, termios.TCSANOW)  # not the default TCSAFLUSH: keep keys typed ahead
        b = _byte(fd)
        if b == 0x1b:                    # ESC alone, or the start of an arrow key
            b = _byte(fd, 0.05)
            if b not in (0x5b, 0x4f):    # not "[" or "O": ESC was pressed alone
                if b is not None:
                    _held.insert(0, b)
                return "key", "esc"
            while True:                  # parameters ("1;5" for Ctrl), then a final byte
                b = _byte(fd, 0.05)
                if b is None or 0x40 <= b <= 0x7e:
                    break
            return "key", {0x41: "up", 0x42: "down", 0x43: "right", 0x44: "left"}.get(b, "")
        if b in (0x0d, 0x0a):
            return "key", "enter"
        if b in (0x7f, 0x08):
            return "key", "backspace"
        if b == 0x03:
            raise KeyboardInterrupt
        decode = codecs.getincrementaldecoder(getattr(sys.stdin, "encoding", None) or "utf-8")("replace")
        c = decode.decode(bytes([b]))
        while not c:                     # the rest of a multi-byte character
            b = _byte(fd, 0.05)
            c = decode.decode(b"" if b is None else bytes([b]), final=b is None)
        return "char", c
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


_held = bytearray()                     # bytes read from the terminal, not handled yet


def _byte(fd, wait=None):
    """
    next byte typed, or None if nothing arrives within `wait` seconds. reads the
    file descriptor itself: sys.stdin's buffer would swallow the rest of an arrow
    key's escape sequence, and select() would then report ESC pressed alone.
    """
    if not _held:
        if wait is not None and not select.select([fd], [], [], wait)[0]:
            return None
        _held.extend(os.read(fd, 64))
        if not _held:
            raise EOFError
    return _held.pop(0)


def fold(s):
    """lowercase without accents, so typing "chunin" finds "Chūnin"."""
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def fuzzy_pick(items, label, header, noun="items", initial=0):
    """
    live-filter picker. type letters to narrow, up/down to move, Enter to select.
    `items` = list, `label(item)` -> str shown & searched. returns item or None.
    prefix matches rank above substring matches. `initial` = starting selection.
    """
    if not interactive_ok():
        return _fallback_pick(items, label, header)
    query, sel, drawn = "", initial, 0
    print(header)                       # printed once; only the lines below are redrawn

    def filtered():
        q = fold(query).replace(" ", "")
        if not q:
            return list(items)
        pre, sub = [], []
        for it in items:
            t = fold(label(it)).replace(" ", "")
            if t.startswith(q):
                pre.append(it)
            elif q in t:
                sub.append(it)
        return pre + sub

    while True:
        # the redraw moves the cursor up one line per entry in `out`, so every entry
        # must stay exactly one screen line: clip to the width, and keep the block
        # shorter than the window so it never scrolls
        cols, lines = shutil.get_terminal_size()
        width = max(10, cols - 4)
        max_rows = max(3, min(15, lines - 5))

        view = filtered()
        sel = max(0, min(sel, len(view) - 1)) if view else 0
        # window of rows around selection
        start = max(0, min(sel - max_rows + 1, len(view) - max_rows)) if len(view) > max_rows else 0
        rows = view[start:start + max_rows]

        hint = "type to filter · ↑↓ move · Enter select · Esc cancel"[:cols - 1]
        out = [f"{DIM}{hint}{RST}{CSI}K", f"> {query[-width:]}{CSI}K"]
        for i, it in enumerate(rows):
            real = start + i
            mark = HL + " > " if real == sel else "   "
            out.append(f"{mark}{label(it)[:width]}{RST}{CSI}K")
        if not view:
            out.append(f"{DIM}  (no match){RST}{CSI}K")
        out.append(f"{DIM}  {len(view)}/{len(items)} {noun}{RST}{CSI}K")

        if drawn:
            sys.stdout.write(f"{CSI}{drawn}A")   # move cursor up to redraw
        sys.stdout.write("\r" + "\n".join(out) + f"{CSI}J\n")
        sys.stdout.flush()
        drawn = len(out)

        kind, val = _getkey()
        if kind == "char":
            query += val
            sel = 0
        elif val == "backspace":
            query = query[:-1]
            sel = 0
        elif val == "up":
            sel -= 1
        elif val == "down":
            sel += 1
        elif val == "enter":
            return view[sel] if view else None
        elif val == "esc":
            return None


def menu_pick(options, default_idx, header):
    """numbered menu. press 1-9 to pick, Enter for default. returns index."""
    print(header)
    for i, (lbl, _) in enumerate(options):
        d = f" {DIM}(default){RST}" if i == default_idx else ""
        print(f"  {i + 1}. {lbl}{d}")
    if not interactive_ok():
        raw = input(f"choice [{default_idx + 1}]: ").strip()
        return default_idx if not raw else max(0, min(int(raw) - 1, len(options) - 1))
    sys.stdout.write(f"{DIM}press number, or Enter for default: {RST}")
    sys.stdout.flush()
    while True:
        kind, val = _getkey()
        if kind == "key" and val == "enter":
            idx = default_idx
            break
        if kind == "char" and val.isdigit() and 1 <= int(val) <= len(options):
            idx = int(val) - 1
            break
    print(f"{options[idx][0]}")
    return idx


def _fallback_pick(items, label, header):
    """no-msvcrt fallback: type a substring, plain input()."""
    print(header)
    q = fold(input("filter (substring): ").strip())
    hits = [it for it in items if q in fold(label(it))] or list(items)
    for i, it in enumerate(hits):
        print(f"  {i + 1}. {label(it)}")
    raw = input("number: ").strip()
    return hits[int(raw) - 1] if raw else hits[0]


# ------------------------------------------------------------------ pixeldrain

def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def listing(path):
    """what a pixeldrain folder holds: [{type, name, path, file_size, ...}]."""
    data = json.loads(fetch(API + urllib.parse.quote(path) + "?stat"))
    if not isinstance(data, dict):
        raise ValueError(f"pixeldrain sent no folder listing for {path}")
    return [c for c in data.get("children") or [] if isinstance(c, dict)]


def load_arcs(lang):
    """the arc folders in the lang share, in order: [{number, name, path}]."""
    arcs = []
    for c in listing(SHARES[lang]):
        m = ARC_RE.match(c.get("name") or "")
        if c.get("type") == "dir" and m:
            arcs.append({"number": m.group(1), "name": m.group(2),
                         "path": c.get("path", "").lstrip("/")})
    if not arcs:
        raise ValueError(f"the {lang} share has no arc folders")
    return sorted(arcs, key=lambda a: float(a["number"]))


def arc_files(arc):
    """the episode files in an arc folder -> ({number: file}, {number: extended cut})."""
    children = listing(arc["path"])
    for c in list(children):
        if c.get("type") == "dir" and "extended" in (c.get("name") or "").lower():
            children += [dict(x, _extended=True) for x in listing(c.get("path", "").lstrip("/"))]
    std, ext = {}, {}
    for c in children:
        name = c.get("name") or ""
        m = EP_RE.search(name)
        if c.get("type") != "file" or not m or not name.lower().endswith(VIDEO):
            continue
        extended = c.get("_extended") or bool(m.group(2))
        (ext if extended else std).setdefault(int(m.group(1)), c)
    return std, ext


def load_series(lang, extended=False):
    """every episode in the lang share, in watching order -> (arcs, episodes). an
    episode with an extended cut plays it with `extended`, else the standard one."""
    shown = sys.stderr.isatty()         # a second or two: say so, then erase it
    if shown:
        sys.stderr.write(f"{DIM}reading the {NAME} folders ({lang})...{RST}")
        sys.stderr.flush()
    try:
        arcs = load_arcs(lang)
        with ThreadPoolExecutor(8) as ex:
            files = list(ex.map(arc_files, arcs))
    finally:
        if shown:
            sys.stderr.write(f"\r{CSI}K")
            sys.stderr.flush()
    eps = []
    for arc, (std, ext) in zip(arcs, files):
        for n in sorted(set(std) | set(ext)):
            cut = n in ext and (extended or n not in std)
            f = ext[n] if cut else std[n]
            eps.append({"arc": arc["number"], "arc_name": arc["name"], "number": n,
                        "path": f.get("path", "").lstrip("/"), "size": f.get("file_size") or 0,
                        "extended": cut, "has_extended": n in ext})
    if not eps:
        raise ValueError(f"the {lang} share has no episodes")
    have = {e["arc"] for e in eps}
    return [a for a in arcs if a["number"] in have], eps


def stream_url(ep):
    return API + urllib.parse.quote(ep["path"])


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", fold(s))


def match_arc(arcs, query):
    """arcs that `query` names: by number (4.5), else the whole name, else its start,
    else any part of it. accents, case, spaces and punctuation don't matter."""
    q = query.strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", q):
        hits = [a for a in arcs if float(a["number"]) == float(q)]
        if hits:
            return hits
    q = norm(q)
    if not q:
        return []
    for test in (lambda n: n == q, lambda n: n.startswith(q), lambda n: q in n):
        hits = [a for a in arcs if test(norm(a["name"]))]
        if hits:
            return hits
    return []


def arc_eps(eps, arc):
    """indices into eps of the episodes in arc."""
    return [i for i, e in enumerate(eps) if e["arc"] == arc["number"]]


def select_eps(eps, arc, spec):
    """'7' / '3-9' / '3-' (to the end of the arc) -> (index into eps to start at, index
    to stop at, or None for a single episode)."""
    m = re.fullmatch(r"\s*(\d+)\s*(?:(-)\s*(\d+)?)?\s*", spec)
    if not m:
        sys.exit(f"bad episode '{spec}'. use 7, 3-9, or 3- (to the end of the arc)")
    lo = int(m.group(1))
    hi = int(m.group(3)) if m.group(3) else (float("inf") if m.group(2) else lo)
    mine = arc_eps(eps, arc)
    picked = [i for i in mine if lo <= eps[i]["number"] <= hi]
    if not picked:
        sys.exit(f"{arc['name']} has no episode {spec}. it has "
                 f"{eps[mine[0]]['number']}-{eps[mine[-1]]['number']}")
    return picked[0], (picked[-1] if m.group(2) else None)


# ------------------------------------------------------------------ labels

def human(size):
    return f"{size / 2**30:.1f} GB" if size >= 2**30 else f"{size / 2**20:.0f} MB"


def ep_title(ep):
    return f"{ep['arc_name']} {ep['number']:02}" + (" Extended" if ep["extended"] else "")


def ext_tag(ep):
    if ep["extended"]:
        return "  [extended cut]"
    return "  (extended cut: --extended)" if ep["has_extended"] else ""


def ep_label(ep):
    return f"{ep['number']:>3}  {ep_title(ep)}{ext_tag(ep)}"


def arc_label(arc, eps):
    n = sum(1 for e in eps if e["arc"] == arc["number"])
    return f"{arc['number']:>4}  {arc['name']}  ({n} episode{'s' if n != 1 else ''})"


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", fold(s)).strip("-")


def print_list(arcs, eps, lang, chosen=None):
    """every arc, or the episodes of the `chosen` arcs."""
    if not chosen:
        print(f"{NAME} ({lang}): {len(eps)} episodes in {len(arcs)} arcs")
        for a in arcs:
            mine = [eps[i] for i in arc_eps(eps, a)]
            cuts = [str(e["number"]) for e in mine if e["has_extended"]]
            extra = f"   extended cut: {', '.join(cuts)}" if cuts else ""
            n = len(mine)
            print(f"{a['number']:>4}  {a['name']:<30}{n:>3} episode{'s' if n != 1 else ' '}{extra}")
        return
    for a in chosen:
        print(f"{a['number']} - {a['name']} ({lang}):")
        for e in (eps[i] for i in arc_eps(eps, a)):
            print(f"{e['number']:>5}  {ep_title(e):<36}{human(e['size']):>8}{ext_tag(e)}")


def choose_episode(arcs, eps, lang, initial=0, arc=None):
    """arc picker (unless `arc` is given), then that arc's episodes. opens on
    eps[initial] where it can -> index into eps, or None when cancelled."""
    if arc is None:
        here = eps[initial]["arc"] if 0 <= initial < len(eps) else None
        at = next((i for i, a in enumerate(arcs) if a["number"] == here), 0)
        arc = fuzzy_pick(arcs, lambda a: arc_label(a, eps), f"\n{NAME} ({lang}), pick an arc:",
                         noun="arcs", initial=at)
        if arc is None:
            return None
    mine = arc_eps(eps, arc)
    ep = fuzzy_pick([eps[i] for i in mine], ep_label, f"\n{arc['name']} ({lang}):",
                    noun="episodes", initial=mine.index(initial) if initial in mine else 0)
    return None if ep is None else next(i for i in mine if eps[i] is ep)


# ------------------------------------------------------------------ playback

# many files mark the opening and the ending as chapters, under all sorts of names.
# this mpv script jumps past the opening, and past the ending and preview: to an extra
# after the ending if there is one, else to the next episode. files without chapters
# just play through. Tab skips by hand.
CHAPTER_SKIPPER = """\
-- written by naru: skip openings, and endings and previews (to an extra after the
-- ending if there is one, else to the next episode).
-- Tab skips by hand: to the next chapter, or 85s (an opening) in files without them.
-- NaruCannon's files name theirs "Opening", "Episode" and "Ending". others seen:
-- "Opening Song", "Intro", "To Be Continued & Ending Song", "Credits", "On The Next
-- episode". whole words only, so "Introduction" stays.
-- "Intro" is an opening only in files that name no chapter "Opening" or "OP": some
-- (Jujutsu Kaisen) call the story before the opening "Intro". openings are matched
-- before endings, so "Opening Credits" is an opening
local OPENING = {"opening", "op%d*"}
local INTRO = {"intro"}
local ENDING = {"ending", "credits", "outro", "ed%d*", "preview", "next episode", "next time"}
local KEY, BY_HAND, NEAR = "TAB", 85, 150

local function matches(title, words)
    title = (title or ""):lower()
    for _, w in ipairs(words) do
        if title:find("%f[%w]" .. w .. "%f[%W]") then return true end
    end
    return false
end

local kinds, kinds_of = {}, nil     -- chapter number -> "opening" / "ending", for a file

local function classify(path)
    if kinds_of == path then return kinds end
    local list, named = mp.get_property_native("chapter-list") or {}, false
    kinds, kinds_of = {}, path
    for i, c in ipairs(list) do
        if matches(c.title, OPENING) then
            kinds[i - 1], named = "opening", true
        elseif matches(c.title, ENDING) then
            kinds[i - 1] = "ending"
        end
    end
    for i, c in ipairs(list) do
        if not named and not kinds[i - 1] and matches(c.title, INTRO) then
            kinds[i - 1] = "opening"
        end
    end
    return kinds
end

local at, opened        -- the chapter playing now, and the file it started in
local waiting = false   -- reached an ending before the next episode was queued
local seeking, settled = false, 0

local function next_episode()
    local pos = mp.get_property_number("playlist-pos", 0)
    waiting = pos + 1 >= mp.get_property_number("playlist-count", 0)
    if not waiting then
        mp.msg.info("ending: next episode")
        mp.osd_message("skipped the ending  (< to go back)", 3)
        mp.command("playlist-next")
    end
end

-- past chapter ch to the next one that isn't an opening, ending or preview (after an
-- ending that keeps extras like Jujutsu Kaisen's "Juju Stroll"), else to the next
-- episode once only endings and previews are left
local function skip_from(path, ch, hint)
    local list, kinds = mp.get_property_native("chapter-list") or {}, classify(path)
    local skipped = list[ch + 1] and list[ch + 1].title or "to the next chapter"
    for j = ch + 1, #list - 1 do
        if not kinds[j] then
            mp.osd_message("skipped " .. skipped .. hint, 3)
            return mp.commandv("seek", list[j + 1].time, "absolute+exact")
        end
    end
    for j = math.max(ch, 0), #list - 1 do
        if kinds[j] == "ending" then return next_episode() end
    end
end

local function check()
    local path, ch = mp.get_property("path"), mp.get_property_number("chapter")
    local key = path and ch and (path .. "#" .. ch)
    if key == at then return end
    at, waiting = key, false
    if not key then return end
    local list = mp.get_property_native("chapter-list") or {}
    local c, what, first = list[ch + 1], classify(path)[ch], opened ~= path
    opened = path
    if not (c and what) then return end
    -- skip a chapter playback runs into, or the one a file opens in (a resume). never
    -- one the viewer seeks or jumps to (PgDn back to an opening plays it), but rewind
    -- to before it and it is skipped again
    local pos = mp.get_property_number("time-pos")
    local by_seek = seeking or mp.get_time() - settled < 0.5
    if not first and (by_seek or (pos and pos > c.time + 2)) then return end
    mp.msg.info("skipped " .. c.title)
    skip_from(path, ch, what == "opening" and "  (PgDn to watch it)" or "")
end

-- by hand: past the chapter playing (and any opening, ending or preview right after
-- it), unless the next chapter is far off or there are none: then an opening's worth
mp.add_key_binding(KEY, "skip", function()
    local path, ch = mp.get_property("path"), mp.get_property_number("chapter", -1)
    local pos = mp.get_property_number("time-pos")
    if not (path and pos) then return end
    local list = mp.get_property_native("chapter-list") or {}
    local c, after = list[ch + 1], list[ch + 2]
    if classify(path)[ch] or (after and after.time - pos <= NEAR) then
        mp.msg.info("skip key: " .. (c and c.title or "start"))
        skip_from(path, ch, "")
    else
        mp.msg.info("skip key: " .. BY_HAND .. "s")
        mp.osd_message("skipped " .. BY_HAND .. "s", 2)
        mp.commandv("seek", BY_HAND, "relative+exact")
    end
end)

mp.register_event("seek", function() seeking = true end)
mp.register_event("playback-restart", function() seeking, settled = false, mp.get_time() end)
-- where the ending starts, for naru to count quitting during it as watched
mp.register_event("file-loaded", function()
    local path, start = mp.get_property("path"), 0
    for i, c in ipairs(mp.get_property_native("chapter-list") or {}) do
        if classify(path)[i - 1] == "ending" then start = c.time break end
    end
    mp.set_property_native("user-data/naru/ending", start)
    check()
end)
mp.observe_property("chapter", "number", check)
mp.observe_property("playlist-count", "number", function()
    if waiting then next_episode() end
end)
"""


def cache_dir():
    """per-user cache folder. not the temp folder: other users can write there, and a
    flatpak mpv only sees its own private /tmp."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Caches")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "naru")


def mpv_script(name, source):
    """write an mpv script into the cache folder (only when it changed).
    its path, or None if it can't be written."""
    path = os.path.join(cache_dir(), name)
    try:
        with open(path, encoding="utf-8") as fh:
            if fh.read() == source:
                return path
    except (OSError, ValueError):
        pass
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(source)
    except OSError:
        return None
    return path


def skip_args():
    """mpv options that load CHAPTER_SKIPPER, or none if it can't be written."""
    path = mpv_script("skip-chapters.lua", CHAPTER_SKIPPER)
    return [f"--script={path}"] if path else []


def write_m3u(path, entries, title):
    """write a standard EXTM3U playlist. entries = [(name, url)]."""
    lines = ["#EXTM3U", f"#PLAYLIST:{title}"]
    for name, url in entries:
        lines.append(f"#EXTINF:-1,{name}")
        lines.append(url)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# ------------------------------------------------------------------ history
# where you left off, for sub and dub separately, and the last volume, so plain
# `naru` can offer "Pain's Assault 07 (dub) at 12:34" and mpv reopens as loud as it was.

def state_dir():
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser(r"~\AppData\Roaming")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "naru")


def load_history():
    try:
        with open(os.path.join(state_dir(), "history.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def spot(history, lang):
    """where lang was left off: {arc, arc_name, episode, extended, position}, or None."""
    s = (history.get("spots") if isinstance(history.get("spots"), dict) else {}).get(lang)
    ok = isinstance(s, dict) and isinstance(s.get("arc"), str) and isinstance(s.get("episode"), int)
    return s if ok else None


def remember(ep, lang, pos=None, volume=None):
    """note where lang was left off: pos seconds into ep, or None once ep was watched.
    history is a convenience, so a failed write never stops playback."""
    data = load_history()
    spots = data.get("spots") if isinstance(data.get("spots"), dict) else {}
    spots[lang] = {"arc": ep["arc"], "arc_name": ep["arc_name"], "episode": ep["number"],
                   "extended": ep["extended"],
                   "position": None if pos is None else round(pos, 1),
                   "time": int(time.time())}
    data["spots"], data["last"] = spots, lang
    if isinstance(volume, (int, float)):
        data["volume"] = round(volume)
    path = os.path.join(state_dir(), "history.json")
    try:
        os.makedirs(state_dir(), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        os.replace(path + ".tmp", path)
    except OSError:
        pass


def resume_point(eps, lang, history):
    """(index into eps, start seconds) to carry on in lang, or None. start is None
    when the saved episode was the very last one and it was watched. a position in the
    other cut of an episode (standard or extended) starts it over."""
    s = spot(history, lang)
    if not s:
        return None
    for i, ep in enumerate(eps):
        if ep["arc"] == s["arc"] and ep["number"] == s["episode"]:
            pos = s.get("position")
            if isinstance(pos, (int, float)) and not isinstance(pos, bool):
                return i, float(pos) if ep["extended"] == bool(s.get("extended")) else 0.0
            return (i + 1, 0.0) if i + 1 < len(eps) else (i, None)
    return None


def spot_label(s, lang):
    title = f"{s.get('arc_name') or s['arc']} {s['episode']:02}"
    pos = s.get("position")
    if isinstance(pos, (int, float)) and not isinstance(pos, bool):
        return f"{title} ({lang}) at {clock(pos)}"
    return f"the episode after {title} ({lang})"


def clock(sec):
    sec = int(sec or 0)
    h, m, s = sec // 3600, sec // 60 % 60, sec % 60
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


# ------------------------------------------------------------------ binge sessions
# on desktop one mpv window plays a whole binge. naru talks to it over mpv's JSON IPC
# and appends the next episode while the current one plays, so episodes advance on
# their own (from one arc into the next), Enter or > (mpv's playlist-next) skips
# ahead, < goes back, and volume and fullscreen carry over.

POLL = 1.0       # seconds between looks at mpv's playlist position
DONE_AT = 120    # quitting this close to the end, or once the ending starts (when the
                 # file marks it as a chapter), counts as watched


def finished(pos, dur, ending):
    """watched: within DONE_AT of the end, or into the ending the chapter skipper found."""
    return pos is not None and bool((dur and dur - pos < DONE_AT) or (ending and pos >= ending))


class MpvError(Exception):
    pass


class MpvIpc:
    """mpv's JSON IPC, one request at a time. nothing reads in the background: a
    Windows pipe handle serializes reads and writes, so a pending read would block
    every command."""

    def __init__(self, conn):
        self.conn, self.buf, self.rid = conn, b"", 0
        if isinstance(conn, socket.socket):
            self.send, self.recv = conn.sendall, lambda: conn.recv(65536)
        else:
            self.send, self.recv = conn.write, lambda: conn.read(65536)

    def command(self, *args, **named):
        """run an mpv command, positional (["seek", 10]) or named (name=..., url=...)."""
        self.rid += 1
        cmd = dict(name=args[0], **named) if named else list(args)
        self.send((json.dumps({"command": cmd, "request_id": self.rid}) + "\n").encode())
        while True:
            while b"\n" not in self.buf:
                chunk = self.recv()
                if not chunk:
                    raise EOFError("mpv closed the connection")
                self.buf += chunk
            line, self.buf = self.buf.split(b"\n", 1)
            msg = json.loads(line)
            if msg.get("request_id") == self.rid:
                if msg.get("error") != "success":
                    raise MpvError(msg.get("error"))
                return msg.get("data")

    def get(self, prop):
        try:
            return self.command("get_property", prop)
        except MpvError:                # "property unavailable" while a file loads
            return None

    def close(self):
        try:
            self.conn.close()
        except OSError:
            pass


def ipc_path():
    tag = f"naru-{os.getpid()}-{secrets.token_hex(4)}"
    if os.name == "nt":
        return "\\\\.\\pipe\\" + tag
    # a private folder: whoever can open the socket can make mpv run commands
    os.makedirs(cache_dir(), mode=0o700, exist_ok=True)
    return os.path.join(cache_dir(), tag + ".sock")


def mpv_connect(path, proc, timeout=15):
    """connect to the ipc server of the mpv that proc runs, or None if it never opens
    one (an mpv without ipc, or a flatpak sandbox that can't reach the path)."""
    deadline = time.monotonic() + timeout
    while proc.poll() is None and time.monotonic() < deadline:
        conn = None
        try:
            if os.name == "nt":
                conn = open(path, "r+b", buffering=0)
            else:
                conn = socket.socket(socket.AF_UNIX)
                conn.settimeout(10)
                conn.connect(path)
            ipc = MpvIpc(conn)
            ipc.command("disable_event", "all")     # replies only, no event chatter
            return ipc
        except (OSError, EOFError, MpvError, ValueError):
            if conn is not None:
                conn.close()
            time.sleep(0.1)
    return None


def title_option(title):
    # mpv's %bytes% quoting keeps commas and quotes in the title intact
    return f"force-media-title=%{len(title.encode())}%{title}"


def play_session(cmd, eps, idx, lang, start=0.0, stop=None):
    """play eps[idx] from start seconds in one mpv window, appending every following
    episode (through eps[stop], else the last one) while the one before it plays.

    returns (index, seconds, status) for where the viewer left off. status is "done"
    (watched to the end, or mpv couldn't be followed), "stopped" (quit mid-episode at
    seconds) or "quit" (Ctrl+C)."""
    last = len(eps) - 1 if stop is None else stop
    title = ep_title(eps[idx])
    sys.stderr.write(f"{title}  ({lang}, {human(eps[idx]['size'])})\n")

    path = ipc_path()
    # --idle=no: mpv 0.42's mpv.exe started without a console (pseudo-gui) idles after
    # the last episode instead of closing, and the session only ends when mpv does
    argv = [*cmd, "--idle=no", f"--input-ipc-server={path}"]
    volume = load_history().get("volume")
    if isinstance(volume, (int, float)) and not isinstance(volume, bool):
        argv.append(f"--volume={volume:g}")
    first = [f"--force-media-title={title}"] + ([f"--start={start:.1f}"] if start else [])
    proc = subprocess.Popen([*argv, "--{", *first, stream_url(eps[idx]), "--}"])  # per-file options

    queue = [idx]                     # mpv playlist entry -> index into eps
    cur, pos, dur, vol, status = idx, (start or None), None, None, "done"
    ending = None                     # where the ending starts, from CHAPTER_SKIPPER
    nxt = idx + 1
    ipc = mpv_connect(path, proc)

    def say(msg):                     # mpv prints it to the terminal around its status line
        try:
            ipc.command("print-text", f"naru: {msg}")
        except (EOFError, OSError, ValueError, MpvError):
            pass
    try:
        while ipc and proc.poll() is None:
            try:
                entry = ipc.get("playlist-pos")
                t, d, v = ipc.get("time-pos"), ipc.get("duration"), ipc.get("volume")
                e = ipc.get("user-data/naru/ending")
            except (EOFError, OSError, ValueError):
                break                           # mpv is shutting down
            if isinstance(entry, int) and 0 <= entry < len(queue):
                if queue[entry] != cur:
                    cur, pos, dur, ending = queue[entry], None, None, None
                if t is not None:
                    pos, dur = t, d
                    ending = e if isinstance(e, (int, float)) and e > 0 else None
            if v is not None:
                vol = v
            # keep one episode queued past the one playing
            if entry == len(queue) - 1 and nxt <= last:
                up = eps[nxt]
                try:
                    ipc.command("loadfile", url=stream_url(up), flags="append",
                                options=title_option(ep_title(up)))
                    queue.append(nxt)
                    new_arc = up["arc"] != eps[nxt - 1]["arc"]
                    say(f"up next  {ep_title(up)}" + ("  (a new arc)" if new_arc else ""))
                except MpvError as err:
                    sys.stderr.write(f"skipping {ep_title(up)}: {err}\n")
                except (EOFError, OSError, ValueError):
                    break
                nxt += 1
            time.sleep(POLL)
    except KeyboardInterrupt:
        status = "quit"
    finally:
        if ipc:
            ipc.close()
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.kill()
            status = "quit"
        if os.name != "nt" and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    watched = finished(pos, dur, ending)
    if ipc and status == "done" and pos is not None and not watched:
        status = "stopped"
    seconds = pos if status in ("stopped", "quit") else None
    remember(eps[cur], lang, seconds, vol)
    return cur, seconds, status


def binge(cmd, arcs, eps, idx, lang, start=0.0, stop=None):
    """desktop playback: one mpv window per session, and a menu once it closes, with
    resume as the default after quitting mid-episode and next after finishing one."""
    while True:
        idx, pos, status = play_session(cmd, eps, idx, lang, start, stop)
        if status == "quit":
            return
        ep, start = eps[idx], 0.0
        if status == "done" and stop is not None and idx >= stop:
            sys.stderr.write(f"\n{ep_title(eps[stop])}: end of the range\n")
            return
        opts = []
        if status == "stopped":
            opts.append((f"resume    {ep_title(ep)} at {clock(pos)}", "resume"))
        if idx + 1 < len(eps):
            opts.append((f"next      {ep_title(eps[idx + 1])}", "next"))
        opts.append(("replay" if status == "done" else f"restart   {ep_title(ep)}", "replay"))
        opts += [("pick episode", "pick"), ("quit", "quit")]
        default = 0 if opts[0][1] in ("resume", "next") else len(opts) - 1
        if status == "stopped":
            head = f"stopped at {clock(pos)}"
        else:
            head = "done" if idx + 1 < len(eps) else f"done, the last episode of {NAME}"
        try:
            choice = opts[menu_pick(opts, default, f"\n{ep_title(ep)} {head}:")][1]
        except EOFError:
            return
        if choice == "quit":
            return
        if choice == "resume":
            start = pos
        elif choice == "next":
            idx += 1
        elif choice == "pick":
            got = choose_episode(arcs, eps, lang, idx)
            if got is None:
                return
            idx, stop = got, None


def android_binge(eps, idx, lang, start=0.0, stop=None):
    """Android: mpv-android gets everything from eps[idx] on (to `stop`) as one
    playlist and plays on by itself, the naru-skip profile skipping openings and
    endings. the app reports nothing back, so naru asks where you got to."""
    last = len(eps) - 1 if stop is None else stop
    queue, ep = eps[idx:last + 1], eps[idx]
    upto = f" to {ep_title(queue[-1])}" if len(queue) > 1 else ""
    sys.stderr.write(f"{ep_title(ep)}{upto}  ({lang}), playing in mpv-android\n")
    android_open(android_playlist(queue), start)
    remember(ep, lang, start or 0.0)        # "at 0:00": `naru` reopens it, not the next one
    if len(queue) < 2:
        return
    try:
        got = fuzzy_pick(queue, ep_label, "\nback from mpv-android? pick the episode you "
                                          f"stopped in, so `naru` continues there "
                                          f"(Esc: still {ep_title(ep)})", noun="episodes")
    except EOFError:
        return
    if got is not None:
        remember(got, lang, 0.0)
        sys.stderr.write(f"saved: `naru` continues from {ep_title(got)}\n")


# Termux on Android has no desktop for mpv to open a window on, so episodes go to
# the mpv-android app through an intent instead (the same route ani-cli takes).
ANDROID = bool(os.environ.get("TERMUX_VERSION")) or "com.termux" in os.environ.get("PREFIX", "")
MPV_ANDROID = "is.xyz.mpv/.MPVActivity"
MPV_ANDROID_HELP = ("install the mpv-android app (is.xyz.mpv) from Google Play or F-Droid: "
                    "https://github.com/mpv-android/mpv-android")

# mpv-android takes no --script and has no IPC, so the desktop skipper can't reach it.
# but mpv's built-in auto_profiles runs every profile-cond as Lua, with `mp` in reach:
# this profile, pasted once into the app's mpv.conf, is the Android skipper. like the
# desktop one, it acts only on what playback runs into: an Opening the file starts
# in or plays into is skipped, an Ending goes on to the next episode in the playlist
# (the last one plays out), and one you seek into yourself plays. NaruCannon files only.
# it lives on one line in mpv.conf, so: no -- comments, and no # (mpv.conf comments)
ANDROID_SKIP = """\
(function(_)
  local s = mp.naru_skip or {}
  mp.naru_skip = s
  local path = mp.get_property('path', '')
  local c = mp.get_property_number('chapter', -1)
  if s.path ~= path then s.path, s.prev = path, -1 end
  local prev = s.prev
  s.prev = c
  if c < 0 or c ~= prev + 1 or not path:find('NaruCannon', 1, true) then return false end
  local t = mp.get_property('chapter-list/' .. c .. '/title', '')
  if t == 'Opening' then
    mp.commandv('no-osd', 'add', 'chapter', '1')
    mp.osd_message('skipped the opening', 2)
  elseif t == 'Ending' and mp.get_property_number('playlist-pos', 0) + 1
                           < mp.get_property_number('playlist-count', 1) then
    mp.commandv('playlist-next')
  end
  return false
end)(chapter)"""
ANDROID_HOWTO = """\
for mpv-android to skip openings and endings, give it naru's profile once:
  1. copy what `naru --mpv-conf` prints (or: naru --mpv-conf | termux-clipboard-set)
  2. in mpv-android: Settings > Advanced > Edit mpv.conf, paste it at the very end, save
and to resume inside an episode: Settings > General > Save position on quit"""


def android_conf():
    """the [naru-skip] profile for mpv-android's mpv.conf (ANDROID_SKIP on one line:
    an option can't span lines). the `chapter` it's called with is only there so the
    profile is re-checked whenever the chapter changes; it reads everything live."""
    return "[naru-skip]\nprofile-cond=" + " ".join(
        line.strip() for line in ANDROID_SKIP.splitlines()) + "\n"


def android_playlist(queue):
    """a data: URI of an m3u of these episodes, titles and all. mpv-android plays it as
    one playlist, and a data: URI needs no file the app would need permission to read."""
    lines = ["#EXTM3U"]
    for ep in queue:
        lines += [f"#EXTINF:-1,{ep_title(ep)}", stream_url(ep)]
    blob = base64.b64encode(("\n".join(lines) + "\n").encode("utf-8")).decode("ascii")
    return "data:audio/x-mpegurl;base64," + blob

# os key -> [(package manager, [commands])]. every manager on PATH is offered in
# order; if one fails the next is tried. ids are checked against each repo:
# winget's "mpv.net" is a different player (mpvnet.exe), shinchiro.mpv is real mpv.
MPV_INSTALL = {
    "nt": [("winget", [["winget", "install", "-e", "--id", "shinchiro.mpv",
                        "--accept-source-agreements", "--accept-package-agreements"]]),
           ("scoop", [["scoop", "bucket", "add", "extras"], ["scoop", "install", "extras/mpv"]]),
           ("choco", [["choco", "install", "mpv", "-y"]])],
    "darwin": [("brew", [["brew", "install", "mpv"]]),
               ("port", [["sudo", "port", "install", "mpv"]])],
    "linux": [("apt", [["sudo", "apt-get", "update"], ["sudo", "apt-get", "install", "-y", "mpv"]]),
              ("dnf", [["sudo", "dnf", "install", "-y", "mpv"]]),
              ("pacman", [["sudo", "pacman", "-S", "--needed", "--noconfirm", "mpv"]]),
              ("zypper", [["sudo", "zypper", "install", "-y", "mpv"]]),
              ("apk", [["sudo", "apk", "add", "mpv"]]),
              ("xbps-install", [["sudo", "xbps-install", "-y", "mpv"]]),
              ("pkg", [["sudo", "pkg", "install", "-y", "mpv"]]),           # FreeBSD
              ("nix", [["nix", "profile", "install", "nixpkgs#mpv"]]),
              # immutable distros (Steam Deck, Silverblue): no root needed
              ("flatpak", [["flatpak", "remote-add", "--user", "--if-not-exists", "flathub",
                            "https://dl.flathub.org/repo/flathub.flatpakrepo"],
                           ["flatpak", "install", "--user", "-y", "flathub", "io.mpv.Mpv"]])],
}
# where those installs leave mpv. a fresh install is usually not on this process's
# PATH yet (and winget's shinchiro.mpv never adds itself), so look here directly.
MPV_DIRS = {
    "nt": [r"%ProgramFiles%\MPV Player", r"%ProgramFiles%\mpv", r"%LOCALAPPDATA%\Programs\mpv",
           r"%LOCALAPPDATA%\Microsoft\WinGet\Links", r"%USERPROFILE%\scoop\shims",
           r"%ProgramData%\chocolatey\bin"],
    "darwin": ["/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin",
               "/Applications/mpv.app/Contents/MacOS"],
    "linux": ["/usr/bin", "/usr/local/bin", "~/.nix-profile/bin", "/run/current-system/sw/bin",
              "/snap/bin"],
}


def _os_key():
    return "nt" if os.name == "nt" else ("darwin" if sys.platform == "darwin" else "linux")


def find_mpv(mpv):
    """argv prefix that runs mpv, or None. checks PATH, the usual install dirs, then flatpak."""
    hit = shutil.which(mpv) or (mpv if os.path.isfile(mpv) else None)
    if hit:
        return [hit]
    if mpv != "mpv":
        return None                     # an explicit --mpv path that isn't there
    exe = "mpv.exe" if os.name == "nt" else "mpv"
    for d in MPV_DIRS[_os_key()]:
        path = os.path.join(os.path.expanduser(os.path.expandvars(d)), exe)
        if os.path.isfile(path):
            return [path]
    if os.name == "nt":
        pkgs = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
        for path in glob.glob(os.path.join(pkgs, "*mpv*", "**", "mpv.exe"), recursive=True):
            return [path]
    if shutil.which("flatpak") and subprocess.run(
            ["flatpak", "info", "io.mpv.Mpv"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        return ["flatpak", "run", "io.mpv.Mpv"]
    return None


def _sudo(cmd):
    """drop sudo when already root or when there is none (containers, minimal installs)."""
    root = hasattr(os, "geteuid") and os.geteuid() == 0
    return cmd[1:] if cmd[0] == "sudo" and (root or not shutil.which("sudo")) else cmd


def ensure_player(mpv, assume_yes=False):
    """mpv argv prefix, installing mpv on first run when it is missing (without asking
    when `assume_yes`). returns None on Android, where the mpv-android app plays
    instead. exits if there is no player."""
    if ANDROID:
        return None
    cmd = find_mpv(mpv)
    if cmd:
        return cmd
    if mpv != "mpv":
        sys.exit(f"mpv not found at {mpv}")

    sys.stderr.write("mpv (the video player naru streams into) is not installed.\n")
    candidates = [(mgr, [_sudo(c) for c in steps])
                  for mgr, steps in MPV_INSTALL[_os_key()] if shutil.which(mgr)]
    if not candidates:
        sys.exit("no supported package manager found. install mpv from "
                 "https://mpv.io/installation/ and retry.")
    if not (assume_yes or interactive_ok()):
        sys.exit("install it with: " + " && ".join(" ".join(c) for c in candidates[0][1])
                 + "\nor let naru do it: naru --setup --yes")

    for mgr, steps in candidates:
        shown = " && ".join(" ".join(c) for c in steps)
        if assume_yes:
            sys.stderr.write(f"installing mpv via {mgr}: {shown}\n")
        elif input(f"install mpv now via {mgr}?  ({shown}) [Y/n] ").strip().lower() in ("n", "no"):
            sys.exit("mpv required. aborting.")
        for c in steps:
            subprocess.run(c)           # judged by the result below, not exit codes:
        cmd = find_mpv(mpv)             # "bucket already added" exits non-zero, harmlessly
        if cmd:
            sys.stderr.write(f"mpv ready: {' '.join(cmd)}\n")
            return cmd
        sys.stderr.write(f"{mgr} did not leave a runnable mpv.\n")
    sys.exit("mpv still not available. install it from https://mpv.io/installation/, "
             "open a new terminal, and retry.")


def android_open(url, start=0.0):
    """hand a stream or playlist to the mpv-android app, `start` seconds into the
    first file. returns at once; the app plays on its own."""
    at = ["--ei", "position", str(int(start * 1000))] if start and start > 0 else []
    try:
        r = subprocess.run(["am", "start", "--user", "0", "-a", "android.intent.action.VIEW",
                            "-d", url, "-n", MPV_ANDROID, *at], capture_output=True, text=True)
    except OSError:
        sys.exit("Termux's `am` command is missing: pkg install termux-am")
    if r.returncode or "Error" in r.stdout + r.stderr:
        sys.exit(f"could not open mpv-android. {MPV_ANDROID_HELP}")


def continue_prompt(extended=False):
    """offer to carry on where sub or dub was left off, the last one used first.
    -> (arcs, episodes, index, lang, start seconds) for watch(), or None to pick instead."""
    history = load_history()
    langs = sorted((lg for lg in SHARES if spot(history, lg)), key=lambda lg: lg != history.get("last"))
    if not langs or not interactive_ok():
        return None
    opts = [(spot_label(spot(history, lg), lg), lg) for lg in langs] + [("pick an arc", None)]
    lang = opts[menu_pick(opts, 0, "\ncontinue watching?")][1]
    if lang is None:
        return None
    arcs, eps = load_series(lang, extended)
    point = resume_point(eps, lang, history)
    if not point:
        return None
    i, start = point
    if start is None:
        print(f"that was the last episode of {NAME}. pick one to watch again")
        i = choose_episode(arcs, eps, lang, i)
        if i is None:
            sys.exit("cancelled")
        start = 0.0
    return arcs, eps, i, lang, start


def watch(cmd, arcs, eps, idx, lang, start=0.0, stop=None):
    if cmd is None:
        android_binge(eps, idx, lang, start, stop)  # mpv-android
    else:
        binge(cmd, arcs, eps, idx, lang, start, stop)


# what the one-line installers install, and how to run them again
PACKAGE = "narucannon-mpv @ https://github.com/vashhdev/narucannon/archive/refs/heads/main.zip"
INSTALLER = ("irm https://raw.githubusercontent.com/vashhdev/narucannon/main/install.ps1 | iex"
             if os.name == "nt" else
             "curl -fsSL https://raw.githubusercontent.com/vashhdev/narucannon/main/install.sh | sh")


def update():
    """reinstall naru from main into the environment this copy runs from: uv when
    it's a venv (uv tool, pipx), else pip (Termux, like its installer). not the
    installers' `uv tool install --force`: that deletes the venv first, and Windows
    won't delete the python.exe running this. a git checkout or a lone naru.py is
    left to you."""
    here = os.path.dirname(os.path.abspath(__file__))
    paths = sysconfig.get_paths()
    if os.path.normcase(here) not in {os.path.normcase(os.path.abspath(paths[k]))
                                      for k in ("purelib", "platlib")}:
        if os.path.isdir(os.path.join(here, ".git")):
            sys.exit(f"this naru runs from a git checkout ({here}): update it with git pull")
        sys.exit(f"this naru is a single file ({os.path.abspath(__file__)}), which --update "
                 f"can't replace. install it with:\n  {INSTALLER}")
    pkg = os.environ.get("NARU_PKG") or PACKAGE         # like the installers
    uv = shutil.which("uv")
    if uv and sys.prefix != sys.base_prefix:
        argv = [uv, "pip", "install", "--python", sys.executable, "--reinstall", pkg]
    else:
        argv = [sys.executable, "-m", "pip", "install", "--upgrade", "--force-reinstall", pkg]
    sys.stderr.write(f"updating naru {__version__}: {' '.join(argv)}\n")
    if subprocess.run(argv).returncode:
        sys.exit(f"update failed. run the installer again:\n  {INSTALLER}")
    # -I: not a naru.py in the current folder
    new = subprocess.run([sys.executable, "-I", "-c", "import naru; print(naru.__version__)"],
                         capture_output=True, text=True).stdout.strip()
    if not new:
        sys.exit(f"the update installed, but the new naru doesn't start. run the installer "
                 f"again:\n  {INSTALLER}")
    print(f"naru {new}: already the newest" if new == __version__
          else f"updated naru {__version__} -> {new}")


def run():
    ap = argparse.ArgumentParser(prog="naru", description=f"stream the {NAME} Recut in mpv")
    ap.add_argument("arc", nargs="?",
                    help="arc name (any part of it) or number: pain, 'chunin exams', 4.5")
    ap.add_argument("episode", nargs="?",
                    help="episode in that arc: 7 (and on from there), 3-9, 3- (to the end of the arc)")
    lang_flag = ap.add_mutually_exclusive_group()
    lang_flag.add_argument("--dub", action="store_true", help="English dub")
    lang_flag.add_argument("--sub", action="store_true",
                           help="Japanese audio with English subs (the default, unless you "
                                "watched the dub last)")
    ap.add_argument("--extended", action="store_true",
                    help="play the extended cut of the episodes that have one")
    ap.add_argument("--list", action="store_true",
                    help="list every arc (or an arc's episodes) and exit")
    ap.add_argument("--print", dest="print_only", action="store_true",
                    help="print stream urls instead of launching mpv")
    ap.add_argument("--m3u", nargs="?", const="", metavar="PATH",
                    help="write an .m3u playlist (the whole arc, or the episodes given) "
                         "instead of launching mpv")
    ap.add_argument("--mpv", default="mpv", help="path to mpv binary")
    ap.add_argument("--no-skip", action="store_true",
                    help="don't skip openings and endings")
    ap.add_argument("--setup", action="store_true",
                    help="find or install mpv and exit (the installers run this)")
    ap.add_argument("--mpv-conf", action="store_true",
                    help="print the profile that skips openings and endings in mpv-android, "
                         "for its mpv.conf, and exit")
    ap.add_argument("-y", "--yes", action="store_true",
                    help="install mpv without asking if it is missing (scripts, CI)")
    ap.add_argument("--update", action="store_true",
                    help="update naru to the newest version and exit")
    ap.add_argument("--version", action="version", version=f"naru {__version__}")
    args = ap.parse_args()

    _enable_vt()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")   # "Chūnin" on a codepage that can't show it
        except AttributeError:
            pass

    if args.mpv_conf:
        sys.stdout.write(android_conf())
        return
    if args.setup:
        cmd = ensure_player(args.mpv, args.yes)
        print(f"{MPV_ANDROID_HELP}\n\n{ANDROID_HOWTO}" if cmd is None else f"ready: {' '.join(cmd)}")
        return
    if args.update:
        update()
        return
    # check the player before anything else, so a first run sets everything up front
    playing = not (args.list or args.print_only or args.m3u is not None)
    cmd = ensure_player(args.mpv, args.yes) if playing else None
    if cmd and not args.no_skip:
        cmd = [*cmd, *skip_args()]

    if playing and not (args.arc or args.dub or args.sub):
        cont = continue_prompt(args.extended)
        if cont:
            watch(cmd, *cont)
            return

    history = load_history()
    lang = "dub" if args.dub else "sub" if args.sub else None
    if not lang:
        last = history.get("last") if history.get("last") in SHARES else "sub"
        if args.episode or args.list or not interactive_ok():
            lang = last
        else:
            opts = [(LANG_LABEL[lg], lg) for lg in ("sub", "dub")]
            lang = opts[menu_pick(opts, [lg for _, lg in opts].index(last), f"\n{NAME}, audio:")][1]

    arcs, eps = load_series(lang, args.extended)
    hits = match_arc(arcs, args.arc) if args.arc else []
    if args.arc and not hits:
        sys.exit(f"no arc matches '{args.arc}'. naru --list shows them all")
    if args.list:
        print_list(arcs, eps, lang, hits)
        return
    arc = hits[0] if len(hits) == 1 else None
    if len(hits) > 1:
        if not interactive_ok():
            sys.exit(f"'{args.arc}' matches {', '.join(a['name'] for a in hits)}. "
                     "say which, or use the arc's number")
        arc = fuzzy_pick(hits, lambda a: arc_label(a, eps), f"\n'{args.arc}' matches:", noun="arcs")
        if arc is None:
            sys.exit("cancelled")
    if arc is None and not interactive_ok():
        sys.exit("name an arc, like: naru pain 7. naru --list shows them all")

    listing_only = args.print_only or args.m3u is not None
    start, stop = 0.0, None
    if args.episode:
        idx, stop = select_eps(eps, arc, args.episode)
        if listing_only and stop is None:
            stop = idx
    elif listing_only:
        if arc is None:
            arc = fuzzy_pick(arcs, lambda a: arc_label(a, eps), f"\n{NAME} ({lang}), pick an arc:",
                             noun="arcs")
            if arc is None:
                sys.exit("cancelled")
        mine = arc_eps(eps, arc)
        idx, stop = mine[0], mine[-1]
    else:
        # open the pickers on where this language was left off
        point = resume_point(eps, lang, history)
        initial = point[0] if point else 0
        if interactive_ok():
            idx = choose_episode(arcs, eps, lang, initial, arc)
            if idx is None:
                sys.exit("cancelled")
        else:
            mine = arc_eps(eps, arc)
            idx = initial if initial in mine else mine[0]
        if point and point[0] == idx and point[1]:
            start = point[1]
            sys.stderr.write(f"resuming at {clock(start)}\n")

    if listing_only:
        picked = eps[idx:stop + 1]
        entries = [(ep_title(ep), stream_url(ep)) for ep in picked]
        if args.print_only:
            print("\n".join(url for _, url in entries))
            return
        first, last = picked[0]["number"], picked[-1]["number"]
        span = str(first) if first == last else f"{first}-{last}"
        name = picked[0]["arc_name"]
        path = args.m3u or f"narucannon-{slug(name)}-{span}-{lang}.m3u"
        write_m3u(path, entries, f"{NAME} {name} {span} ({lang})")
        print(os.path.abspath(path))
        return

    watch(cmd, arcs, eps, idx, lang, start, stop)


def main():
    """the naru command, installed or as python naru.py: errors you can act on end in
    one line, not a traceback."""
    try:
        run()
    except KeyboardInterrupt:
        sys.exit("\ncancelled")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            sys.exit(f"pixeldrain can't find the {NAME} share or one of its folders, so it "
                     "may have moved. naru --update gets the newest naru")
        if e.code in (403, 429):
            sys.exit(f"pixeldrain turned the request down (HTTP {e.code}). it limits heavy "
                     "use, so try again later")
        sys.exit(f"pixeldrain error: HTTP {e.code} {e.reason}")
    except (urllib.error.URLError, TimeoutError) as e:
        sys.exit(f"network error: {e}")
    except ValueError as e:
        sys.exit(f"unexpected response from pixeldrain: {e}\n"
                 "naru --update gets the newest naru")


if __name__ == "__main__":
    main()
