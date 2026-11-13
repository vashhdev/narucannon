"""
offline tests for naru.py: no network, stdlib only.

    python -m unittest discover -s tests -v

pixeldrain is replaced by a fixture folder tree shaped like the real NaruCannon
shares (arc folders numbered 1 to 12 with a 4.5, an "Extended Episode(s)" folder,
an accented arc name, a stray .mkv in the dub), so every step runs without touching
pixeldrain. three tests drive a real mpv when one is installed (a whole binge session
and two for the chapter skipper), and are skipped otherwise.
"""

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import naru  # noqa: E402

# every test writes naru's cache (the chapter skipper, ipc sockets) and its watch
# history here, never into the real folders
CACHE = None


def setUpModule():
    global CACHE
    CACHE = tempfile.TemporaryDirectory()
    for name, sub in (("cache_dir", "naru"), ("state_dir", "state")):
        patcher = mock.patch.object(naru, name, lambda sub=sub: os.path.join(CACHE.name, sub))
        patcher.start()
        unittest.addModuleCleanup(patcher.stop)
    unittest.addModuleCleanup(CACHE.cleanup)


# ------------------------------------------------------------------ fixtures

MB = 2 ** 20


def share(sid, tag, odd=".mp4"):
    """one NaruCannon share as {folder path: children}, like pixeldrain's listing."""
    def d(name):
        return {"type": "dir", "name": name, "file_size": 0}

    def f(name, size=500 * MB):
        return {"type": "file", "name": name, "file_size": size}

    def ep(arc, n, extended=False, ext=".mp4", size=500 * MB):
        return f(f"[NaruCannon Recut] {arc} {n:02}{' Extended' if extended else ''} ({tag}){ext}", size)

    folders = {
        "": [f(".search_index.gz", 1165), d("1 - Land of Waves"), d("10 - Five Kage Summit"),
             d("2 - Chūnin Exams"), d("4.5 - Kakashi Chronicles"), d("Extras")],
        "1 - Land of Waves": [ep("Land of Waves", 1), ep("Land of Waves", 2),
                              ep("Land of Waves", 3, ext=odd, size=3 * 2 ** 30), f("cover.jpg")],
        "2 - Chūnin Exams": [d("Extended Episode(s)"), ep("Chunin Exams", 1), ep("Chunin Exams", 2)],
        "2 - Chūnin Exams/Extended Episode(s)": [ep("Chunin Exams", 2, extended=True, size=900 * MB)],
        "4.5 - Kakashi Chronicles": [ep("Kakashi Chronicles", 1)],
        "10 - Five Kage Summit": [ep("Five Kage Summit", 2), ep("Five Kage Summit", 1)],
        "Extras": [f("trailer.mp4")],
    }
    out = {}
    for folder, kids in folders.items():
        base = sid + ("/" + folder if folder else "")
        out[base] = [dict(k, path=f"/{base}/{k['name']}") for k in kids]
    return out


TREE = {**share("CEG3sGRE", "Sub"), **share("qqyKh8x5", "Dub", odd=".mkv")}
EXTENDED_URL = ("https://pixeldrain.net/api/filesystem/CEG3sGRE/2%20-%20Ch%C5%ABnin%20Exams/"
                "Extended%20Episode%28s%29/%5BNaruCannon%20Recut%5D%20Chunin%20Exams%2002%20"
                "Extended%20%28Sub%29.mp4")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def fake_fetch(url):
    assert url.startswith(naru.API) and url.endswith("?stat") and " " not in url, url
    path = urllib.parse.unquote(url[len(naru.API):-len("?stat")])
    if path not in TREE:
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    return json.dumps({"path": [{"type": "dir", "path": "/" + path}], "base_index": 0,
                       "children": TREE[path]})


@contextlib.contextmanager
def offline():
    """swap pixeldrain for the fixture tree."""
    with mock.patch.object(naru, "fetch", fake_fetch):
        yield


def series(lang="sub", extended=False):
    with offline():
        return naru.load_series(lang, extended)


ARCS, EPS = series()      # 0-2 Land of Waves 1-3, 3-4 Chūnin 1-2, 5 Kakashi 1, 6-7 Kage 1-2


def run_main(*argv):
    """run naru.main() with argv; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with mock.patch.object(sys, "argv", ["naru", *argv]), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            naru.main()
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


def forget():
    with contextlib.suppress(FileNotFoundError):
        os.remove(os.path.join(naru.state_dir(), "history.json"))


class Terminal:
    """just enough of a VT100 to replay the picker: \\r \\n, CSI nA / K / J / m, wrapping."""

    def __init__(self, cols):
        self.cols, self.rows, self.y, self.x = cols, [[]], 0, 0

    def feed(self, raw):
        i = 0
        while i < len(raw):
            m = re.match(r"\x1b\[(\d*)([A-Za-z])", raw[i:])
            if m:
                n, cmd = int(m.group(1) or 1), m.group(2)
                if cmd == "A":
                    self.y = max(0, self.y - n)
                elif cmd == "K":
                    del self.rows[self.y][self.x:]
                elif cmd == "J":
                    del self.rows[self.y][self.x:]
                    del self.rows[self.y + 1:]
                i += len(m.group(0))
                continue
            c = raw[i]
            if c == "\r":
                self.x = 0
            elif c == "\n":
                self._down()
            else:
                if self.x >= self.cols:
                    self._down()
                row = self.rows[self.y]
                row.extend(" " * (self.x - len(row)))
                if self.x < len(row):
                    row[self.x] = c
                else:
                    row.append(c)
                self.x += 1
            i += 1
        return ["".join(r).rstrip() for r in self.rows]

    def _down(self):
        self.y, self.x = self.y + 1, 0
        while len(self.rows) <= self.y:
            self.rows.append([])


# ------------------------------------------------------------------ the shares

class Shares(unittest.TestCase):
    def test_arcs_in_number_order_and_only_episode_files(self):
        self.assertEqual([(a["number"], a["name"]) for a in ARCS],
                         [("1", "Land of Waves"), ("2", "Chūnin Exams"),
                          ("4.5", "Kakashi Chronicles"), ("10", "Five Kage Summit")])
        self.assertEqual([naru.ep_title(e) for e in EPS], [
            "Land of Waves 01", "Land of Waves 02", "Land of Waves 03",
            "Chūnin Exams 01", "Chūnin Exams 02", "Kakashi Chronicles 01",
            "Five Kage Summit 01", "Five Kage Summit 02"])          # no cover.jpg, Extras
        self.assertEqual(EPS[0]["path"],
                         "CEG3sGRE/1 - Land of Waves/[NaruCannon Recut] Land of Waves 01 (Sub).mp4")

    def test_extended_cuts_only_with_the_flag(self):
        std = EPS[4]
        self.assertEqual((std["extended"], std["has_extended"], std["size"]), (False, True, 500 * MB))
        self.assertEqual(naru.ep_label(std), "  2  Chūnin Exams 02  (extended cut: --extended)")
        _, eps = series(extended=True)
        ext = eps[4]
        self.assertEqual((ext["extended"], ext["size"]), (True, 900 * MB))
        self.assertEqual(naru.ep_title(ext), "Chūnin Exams 02 Extended")
        self.assertEqual(naru.stream_url(ext), EXTENDED_URL)
        self.assertEqual(len(eps), len(EPS))                    # swapped in, not added

    def test_dub_share_and_its_odd_mkv(self):
        _, eps = series("dub")
        self.assertEqual(len(eps), len(EPS))
        self.assertTrue(eps[2]["path"].endswith("Land of Waves 03 (Dub).mkv"))
        self.assertTrue(eps[0]["path"].startswith("qqyKh8x5/"))

    def test_stream_url_quotes_every_odd_character(self):
        ep = {"path": "CEG3sGRE/9 - Pain's Assault/[NaruCannon Recut] Pain's Assault 01 (Sub).mp4"}
        self.assertEqual(naru.stream_url(ep),
                         "https://pixeldrain.net/api/filesystem/CEG3sGRE/9%20-%20Pain%27s%20Assault/"
                         "%5BNaruCannon%20Recut%5D%20Pain%27s%20Assault%2001%20%28Sub%29.mp4")

    def test_episode_numbers_from_file_names(self):
        for name, want in [("[NaruCannon Recut] Land of Waves 01 (Sub).mp4", ("01", None)),
                           ("[NaruCannon Recut] Five Kage Summit 14 Extended (Dub).mp4", ("14", " Extended")),
                           ("[NaruCannon Recut] Land of Waves 09 (Dub).mkv", ("09", None)),
                           ("Episode 7.mp4", ("7", None))]:
            self.assertEqual(naru.EP_RE.search(name).groups(), want, name)

    def test_match_arc(self):
        def names(q):
            return [a["name"] for a in naru.match_arc(ARCS, q)]
        self.assertEqual(names("chunin"), ["Chūnin Exams"])            # no accent needed
        self.assertEqual(names("CHŪNIN EXAMS"), ["Chūnin Exams"])
        self.assertEqual(names("land-of-waves"), ["Land of Waves"])
        self.assertEqual(names("4.5"), ["Kakashi Chronicles"])
        self.assertEqual(names("10"), ["Five Kage Summit"])
        self.assertEqual(names("ka"), ["Kakashi Chronicles"])          # the start beats any part
        self.assertEqual(names("kage"), ["Five Kage Summit"])
        self.assertEqual(names("es"), ["Land of Waves", "Kakashi Chronicles", "Five Kage Summit"])
        self.assertEqual(names("zzz"), [])
        self.assertEqual(names("7"), [])                                # no arc 7 here

    def test_select_eps(self):
        land = ARCS[0]
        self.assertEqual(naru.select_eps(EPS, land, "2"), (1, None))
        self.assertEqual(naru.select_eps(EPS, land, "1-2"), (0, 1))
        self.assertEqual(naru.select_eps(EPS, land, "2-"), (1, 2))     # to the end of the arc
        self.assertEqual(naru.select_eps(EPS, ARCS[3], "1"), (6, None))
        with self.assertRaisesRegex(SystemExit, "Land of Waves has no episode 9. it has 1-3"):
            naru.select_eps(EPS, land, "9")
        with self.assertRaisesRegex(SystemExit, "bad episode"):
            naru.select_eps(EPS, land, "two")

    def test_labels(self):
        self.assertEqual(naru.human(3 * 2 ** 30), "3.0 GB")
        self.assertEqual(naru.human(538 * MB), "538 MB")
        self.assertEqual(naru.arc_label(ARCS[2], EPS), " 4.5  Kakashi Chronicles  (1 episode)")
        self.assertEqual(naru.slug("Pain's Assault"), "pain-s-assault")
        self.assertEqual(naru.slug("Chūnin Exams"), "chunin-exams")


class Main(unittest.TestCase):
    def setUp(self):
        forget()

    def test_list_every_arc(self):
        with offline():
            code, out, err = run_main("--list")
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertEqual(lines[0], "NaruCannon (sub): 8 episodes in 4 arcs")
        self.assertEqual(lines[2], "   2  Chūnin Exams                    2 episodes   extended cut: 2")
        self.assertEqual(lines[3].rstrip(), " 4.5  Kakashi Chronicles              1 episode")

    def test_list_the_episodes_of_the_arcs_named(self):
        with offline():
            code, out, _ = run_main("chunin", "--list", "--dub")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0], "2 - Chūnin Exams (dub):")
        self.assertIn("2  Chūnin Exams 02                       500 MB  (extended cut: --extended)", out)
        with offline():
            _, out, _ = run_main("es", "--list")
        self.assertEqual(len([s for s in out.splitlines() if s.endswith("(sub):")]), 3)

    def test_print(self):
        with offline():
            code, out, err = run_main("land", "2", "--print")
            self.assertEqual(code, 0, err)
            self.assertEqual(out.split(), [naru.stream_url(EPS[1])])
            _, out, _ = run_main("land", "2-", "--print")
            self.assertEqual(out.split(), [naru.stream_url(e) for e in EPS[1:3]])
            _, out, _ = run_main("chunin", "--print")                  # no episode: the arc
            self.assertEqual(out.split(), [naru.stream_url(e) for e in EPS[3:5]])
            _, out, _ = run_main("chunin", "2", "--print", "--extended")
            self.assertEqual(out.strip(), EXTENDED_URL)
            _, out, _ = run_main("4.5", "1", "--print", "--dub")
            self.assertIn("/qqyKh8x5/4.5%20-%20Kakashi%20Chronicles/", out)

    def test_the_language_watched_last_is_the_default(self):
        _, dub = series("dub")
        naru.remember(dub[0], "dub", 10.0)
        with offline():
            _, out, _ = run_main("land", "1", "--print")
            self.assertIn("/qqyKh8x5/", out)
            _, out, _ = run_main("land", "1", "--print", "--sub")
            self.assertIn("/CEG3sGRE/", out)

    def test_m3u(self):
        with offline(), tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.m3u")
            code, out, err = run_main("land", "--m3u", path)
            self.assertEqual(code, 0, err)
            text = read(path)
            here = os.getcwd()
            os.chdir(tmp)
            try:
                code, out, err = run_main("chunin", "1-2", "--dub", "--m3u")
            finally:
                os.chdir(here)
            self.assertEqual(code, 0, err)
            self.assertTrue(out.strip().endswith("narucanon-chunin-exams-1-2-dub.m3u"))
        self.assertTrue(text.startswith("#EXTM3U\n#PLAYLIST:NaruCannon Land of Waves 1-3 (sub)\n"))
        self.assertIn("#EXTINF:-1,Land of Waves 02\n" + naru.stream_url(EPS[1]), text)
        self.assertEqual(text.count("#EXTINF"), 3)

    def test_unknown_ambiguous_or_missing_arc(self):
        with offline():
            code, _, _ = run_main("zzz", "--print")
            self.assertIn("no arc matches 'zzz'", code)
            code, _, _ = run_main("es", "--print")
            self.assertIn("matches Land of Waves, Kakashi Chronicles, Five Kage Summit", code)
            code, _, _ = run_main("--print")
            self.assertIn("name an arc", code)

    def test_the_installed_command_ends_in_one_line_not_a_traceback(self):
        """the naru command calls main(), so main() itself turns these into a message."""
        def http(code):
            return urllib.error.HTTPError("https://pixeldrain.net/x", code, "Nope", {}, None)
        for raised, said in [(http(404), "can't find the NaruCannon share"),
                             (http(429), "try again later"),
                             (http(500), "pixeldrain error: HTTP 500"),
                             (None, "unexpected response from pixeldrain"),
                             (urllib.error.URLError("no route"), "network error: <urlopen error no route>"),
                             (KeyboardInterrupt(), "cancelled")]:
            def fetch(url, raised=raised):
                if raised:
                    raise raised
                return "<!doctype html>\n<html>"
            with mock.patch.object(naru, "fetch", fetch):
                code, out, err = run_main("--list")
            self.assertIsInstance(code, str)
            self.assertIn(said, code)

    def test_setup_reports_player(self):
        with mock.patch.object(naru, "find_mpv", return_value=["/usr/bin/mpv"]):
            code, out, _ = run_main("--setup")
        self.assertEqual((code, out.strip()), (0, "ready: /usr/bin/mpv"))

    def test_chapter_skipper_loads_unless_no_skip(self):
        played = []
        with offline(), mock.patch.object(naru, "ensure_player", lambda mpv, yes: ["mpv"]), \
                mock.patch.object(naru, "watch", lambda cmd, *rest: played.append((cmd, *rest))):
            run_main("land", "2", "--dub")
            run_main("land", "2", "--dub", "--no-skip")
        skipper = os.path.join(CACHE.name, "naru", "skip-chapters.lua")
        self.assertEqual([p[0] for p in played], [["mpv", f"--script={skipper}"], ["mpv"]])
        self.assertEqual(played[0][3:], (1, "dub", 0.0, None))      # 2, then on and on
        self.assertEqual(read(skipper), naru.CHAPTER_SKIPPER)

    def test_version_matches_pyproject_and_changelog(self):
        pyproject = read(os.path.join(ROOT, "pyproject.toml"))
        changelog = read(os.path.join(ROOT, "CHANGELOG.md"))
        self.assertEqual(re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1),
                         naru.__version__)
        self.assertIn(f"## [{naru.__version__}]", changelog)


# ------------------------------------------------------------------ terminal UI

class Picker(unittest.TestCase):
    def pick(self, keys, cols=120, lines=40, header="\nNaruCannon (sub), pick an arc:"):
        items = [f"{n:>4}  Arc number {n} " + "long name " * (8 if n % 7 == 0 else 0)
                 for n in range(1, 301)] + ["  2  Chūnin Exams"]
        keys = iter(keys)
        out = io.StringIO()
        with mock.patch.object(naru, "interactive_ok", return_value=True), \
                mock.patch.object(naru, "_getkey", lambda: next(keys)), \
                mock.patch.object(naru.shutil, "get_terminal_size",
                                  return_value=os.terminal_size((cols, lines))), \
                contextlib.redirect_stdout(out):
            picked = naru.fuzzy_pick(items, str, header, noun="arcs", initial=len(items) - 2)
        return picked, Terminal(cols).feed(out.getvalue())

    def test_redraw_never_duplicates_header_or_hint(self):
        moves = [("key", "up")] * 30 + [("key", "down")] * 5 + [("key", "enter")]
        for cols, lines in ((120, 40), (60, 14), (30, 8)):
            picked, screen = self.pick(moves, cols, lines)
            self.assertTrue(picked.startswith(" 275  Arc number 275"), picked)
            self.assertEqual(sum("pick an arc:" in s for s in screen), 1, (cols, screen))
            self.assertEqual(sum(s.startswith("type to filter") for s in screen), 1, (cols, screen))
            self.assertLessEqual(len(screen), lines + 2)   # header block + one redraw region

    def test_typing_filters_and_ignores_accents(self):
        picked, screen = self.pick([("char", c) for c in "chunin"] + [("key", "enter")])
        self.assertEqual(picked, "  2  Chūnin Exams")
        self.assertIn("1/301 arcs", screen[-2])

    def test_escape_cancels(self):
        self.assertIsNone(self.pick([("key", "esc")])[0])

    def test_choose_episode_opens_on_the_arc_and_episode_given(self):
        seen = []

        def pick(items, label, header, noun="items", initial=0):
            seen.append((noun, label(items[initial])))
            return items[initial]
        with mock.patch.object(naru, "fuzzy_pick", pick):
            self.assertEqual(naru.choose_episode(ARCS, EPS, "sub", 4), 4)
            self.assertEqual(naru.choose_episode(ARCS, EPS, "sub", 4, arc=ARCS[0]), 0)
        self.assertEqual(seen, [("arcs", "   2  Chūnin Exams  (2 episodes)"),
                                ("episodes", "  2  Chūnin Exams 02  (extended cut: --extended)"),
                                ("episodes", "  1  Land of Waves 01")])


@unittest.skipUnless(hasattr(os, "openpty") and naru.termios, "needs a POSIX terminal")
class Keys(unittest.TestCase):
    """keys typed into a real pseudo-terminal, sent the way Linux and macOS terminals send them."""

    def setUp(self):
        self.master, slave = os.openpty()
        self.addCleanup(os.close, self.master)
        self.addCleanup(os.close, slave)
        naru.tty.setcbreak(slave)               # keys written below are readable at once
        # what a terminal looks like to Python: a text wrapper over a buffered reader
        tty_in = io.TextIOWrapper(io.BufferedReader(io.FileIO(slave, "rb", closefd=False)),
                                  encoding="utf-8")
        for patch in (mock.patch.object(sys, "stdin", tty_in),
                      mock.patch.object(naru, "_held", bytearray())):
            patch.start()
            self.addCleanup(patch.stop)

    def test_escape_sequences_arrive_whole(self):
        cases = [
            (b"\x1b[A", [("key", "up")]),
            (b"\x1b[B", [("key", "down")]),
            (b"\x1bOA", [("key", "up")]),               # application cursor mode
            (b"\x1b[1;5B", [("key", "down")]),          # Ctrl+Down
            (b"\x1b[3~", [("key", "")]),                # Delete: ignored, not typed as "~"
            (b"\x1b", [("key", "esc")]),
            (b"\x1b[Ax", [("key", "up"), ("char", "x")]),
            (b"ab", [("char", "a"), ("char", "b")]),
            ("ū".encode(), [("char", "ū")]),
            (b"\r", [("key", "enter")]),
            (b"\x7f", [("key", "backspace")]),
        ]
        for typed, want in cases:
            with self.subTest(typed=typed):
                os.write(self.master, typed)
                self.assertEqual([naru._getkey() for _ in want], want)

    def test_arrows_move_the_picker_instead_of_closing_it(self):
        os.write(self.master, b"\x1b[B\x1b[B\x1b[A\r")
        with mock.patch.object(naru, "interactive_ok", return_value=True), \
                contextlib.redirect_stdout(io.StringIO()):
            picked = naru.fuzzy_pick(["one", "two", "three"], str, "\npick:")
        self.assertEqual(picked, "two")


# ------------------------------------------------------------------ playback

class FakeMpv:
    """one mpv process plus its IPC connection. the playlist starts with the urls on
    the command line; every file lasts `length` polls of `duration` seconds, then the
    next one plays, or mpv exits after the last. `actions` maps a poll number to
    "next" (Enter in mpv) or "quit" (q). `ending` is where the chapter skipper says
    every file's ending starts (None: no chapters, or no skipper)."""

    def __init__(self, argv, length=3, actions=None, duration=1400.0, volume=55.0, ending=None):
        self.argv = argv
        self.playlist = [a for a in argv if a.startswith("https://")]
        self.titles = [a.split("=", 1)[1] for a in argv if a.startswith("--force-media-title=")]
        self.length, self.actions, self.duration, self.volume = length, actions or {}, duration, volume
        self.ending = ending
        self.pos, self.tick, self.polls, self.exited, self.printed = 0, 0, 0, False, []

    # the process
    def poll(self):
        return 0 if self.exited else None

    def wait(self):
        self.exited = True
        return 0

    def kill(self):
        self.exited = True

    # the ipc connection
    def get(self, prop):
        if prop == "playlist-pos":
            self.polls += 1
            self.tick += 1
            action = self.actions.get(self.polls)
            if action == "next" or self.tick > self.length:
                if self.pos + 1 >= len(self.playlist):
                    self.exited = True
                    raise EOFError
                self.pos, self.tick = self.pos + 1, 1
            if action == "quit":
                self.exited = True
                raise EOFError
            return self.pos
        return {"time-pos": self.duration * self.tick / self.length, "duration": self.duration,
                "volume": self.volume, "user-data/naru/ending": self.ending}[prop]

    def command(self, *args, **named):
        if args[:1] == ("loadfile",):
            self.playlist.append(named["url"])
            self.titles.append(named["options"].split("%", 2)[2])
        elif args[:1] == ("print-text",):
            self.printed.append(args[1])

    def close(self):
        pass


class Session(unittest.TestCase):
    """the desktop binge: one mpv window, next episode appended while one plays."""

    def setUp(self):
        forget()

    def run_session(self, idx=0, stop=None, start=0.0, eps=EPS, lang="sub", **fake):
        mpvs = []

        def popen(argv):
            mpvs.append(FakeMpv(argv, **fake))
            return mpvs[-1]
        with mock.patch.object(naru.subprocess, "Popen", popen), \
                mock.patch.object(naru, "mpv_connect", lambda path, proc: proc), \
                mock.patch.object(naru, "POLL", 0.001), \
                contextlib.redirect_stderr(io.StringIO()):
            out = naru.play_session(["mpv"], eps, idx, lang, start, stop)
        self.assertEqual(len(mpvs), 1)          # one window for the whole session
        return out, mpvs[0]

    def test_plays_on_from_arc_to_arc_in_one_window(self):
        (idx, pos, status), mpv = self.run_session(idx=2)
        self.assertEqual(mpv.playlist, [naru.stream_url(e) for e in EPS[2:]])
        self.assertEqual(mpv.titles, [naru.ep_title(e) for e in EPS[2:]])
        self.assertEqual((idx, pos, status), (7, None, "done"))
        self.assertIn("--{", mpv.argv)          # first file's title is file-local
        self.assertTrue(any(a.startswith("--input-ipc-server=") for a in mpv.argv))
        self.assertIn("naru: up next  Chūnin Exams 01  (a new arc)", mpv.printed)
        self.assertIn("naru: up next  Chūnin Exams 02", mpv.printed)
        h = naru.load_history()
        self.assertEqual((h["last"], h["volume"]), ("sub", 55))
        self.assertEqual(h["spots"]["sub"], dict(h["spots"]["sub"], arc="10", episode=2,
                                                 position=None, arc_name="Five Kage Summit"))

    def test_quit_mid_episode_is_remembered_with_position_and_volume(self):
        (idx, pos, status), _ = self.run_session(actions={5: "quit"}, volume=72.0)
        self.assertEqual((idx, status), (1, "stopped"))          # quit 1/3 into episode 2
        self.assertAlmostEqual(pos, 1400 / 3, places=1)
        h = naru.load_history()
        self.assertEqual((h["spots"]["sub"]["episode"], h["volume"]), (2, 72))
        # the next run opens mpv at that volume, and a resume starts at the position
        _, mpv = self.run_session(idx=1, start=466.7, actions={2: "quit"})
        self.assertIn("--volume=72", mpv.argv)
        self.assertIn("--start=466.7", mpv.argv)

    def test_quitting_during_the_ending_counts_as_watched(self):
        # quit 2/3 into episode 1 (933s of 1400): past an ending marked at 900s...
        (idx, pos, status), _ = self.run_session(actions={3: "quit"}, ending=900.0)
        self.assertEqual((idx, pos, status), (0, None, "done"))
        self.assertIsNone(naru.load_history()["spots"]["sub"]["position"])
        # ...but not before it
        (idx, pos, status), _ = self.run_session(actions={3: "quit"}, ending=1000.0)
        self.assertEqual((idx, status), (0, "stopped"))

    def test_enter_skips_ahead_and_range_stops_at_its_end(self):
        (idx, _, status), mpv = self.run_session(stop=1, actions={3: "next"})
        self.assertEqual(mpv.playlist, [naru.stream_url(e) for e in EPS[:2]])     # nothing past 2
        self.assertEqual((idx, status), (1, "done"))

    def test_without_ipc_it_still_plays_the_first_episode(self):
        with mock.patch.object(naru, "mpv_connect", lambda path, proc: None), \
                mock.patch.object(naru.subprocess, "Popen", lambda argv: FakeMpv(argv)), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(naru.play_session(["mpv"], EPS, 0, "sub"), (0, None, "done"))

    def binge(self, sessions, idx=0):
        menus, calls = [], []

        def session(cmd, eps, idx, lang, start, stop):
            calls.append((idx, start))
            return sessions.pop(0)

        def menu(opts, default, header):
            menus.append((opts, default, header))
            return default
        with mock.patch.object(naru, "play_session", session), \
                mock.patch.object(naru, "menu_pick", menu):
            naru.binge(["mpv"], ARCS, EPS, idx, "sub")
        return menus, calls

    def test_menu_resumes_by_default_after_quitting_mid_episode(self):
        menus, calls = self.binge([(1, 754.0, "stopped"), (1, None, "quit")])
        opts, default, header = menus[0]
        self.assertEqual(opts[default][1], "resume")
        self.assertEqual(header, "\nLand of Waves 02 stopped at 12:34:")
        self.assertEqual(calls, [(0, 0.0), (1, 754.0)])

    def test_menu_after_the_very_last_episode_defaults_to_quit(self):
        menus, _ = self.binge([(7, None, "done")], idx=7)
        opts, default, header = menus[0]
        self.assertEqual(opts[default][1], "quit")
        self.assertNotIn("next", [v for _, v in opts])
        self.assertIn("the last episode of NaruCannon", header)

    def test_resume_point(self):
        spot = {"arc": "2", "arc_name": "Chūnin Exams", "episode": 1, "extended": False,
                "position": 754.0}
        hist = {"last": "sub", "spots": {"sub": spot}}
        self.assertEqual(naru.resume_point(EPS, "sub", hist), (3, 754.0))
        self.assertIsNone(naru.resume_point(EPS, "dub", hist))
        spot["position"] = None                                   # watched: the next one
        self.assertEqual(naru.resume_point(EPS, "sub", hist), (4, 0.0))
        spot.update(arc="10", episode=2)                          # the very last: done
        self.assertEqual(naru.resume_point(EPS, "sub", hist), (7, None))
        # a position in the extended cut starts the standard one over, and back
        spot.update(arc="2", episode=2, extended=True, position=100.0)
        self.assertEqual(naru.resume_point(EPS, "sub", hist), (4, 0.0))
        self.assertEqual(naru.resume_point(series(extended=True)[1], "sub", hist), (4, 100.0))
        spot["episode"] = "2"                                     # damaged: ignored
        self.assertIsNone(naru.resume_point(EPS, "sub", hist))

    def test_continue_prompt_offers_sub_and_dub_last_used_first(self):
        _, dub = series("dub")
        naru.remember(EPS[3], "sub", 754.0)
        naru.remember(dub[0], "dub")
        menus = []

        def menu(opts, default, header):
            menus.append([label for label, _ in opts])
            return 1                                              # the sub spot
        with offline(), mock.patch.object(naru, "interactive_ok", lambda: True), \
                mock.patch.object(naru, "menu_pick", menu):
            arcs, eps, idx, lang, start = naru.continue_prompt()
        self.assertEqual(menus[0], ["the episode after Land of Waves 01 (dub)",
                                    "Chūnin Exams 01 (sub) at 12:34", "pick an arc"])
        self.assertEqual((lang, idx, start, eps), ("sub", 3, 754.0, EPS))

    def test_plain_naru_continues_where_it_left_off(self):
        # the whole path from `naru` with no arguments to mpv: Enter on "continue"
        # plays the saved episode from the saved position
        naru.remember(EPS[5], "sub", 1181.0)
        played = []
        with offline(), mock.patch.object(naru, "ensure_player", lambda mpv, yes: ["mpv"]), \
                mock.patch.object(naru, "interactive_ok", lambda: True), \
                mock.patch.object(naru, "menu_pick", lambda opts, default, header: default), \
                mock.patch.object(naru, "play_session",
                                  lambda *a: played.append(a) or (0, None, "quit")):
            code, _, err = run_main("--no-skip")
        self.assertEqual(code, 0, err)
        self.assertEqual(played, [(["mpv"], EPS, 5, "sub", 1181.0, None)])

    def test_history_survives_a_corrupt_file(self):
        os.makedirs(naru.state_dir(), exist_ok=True)
        with open(os.path.join(naru.state_dir(), "history.json"), "w") as fh:
            fh.write("{not json")
        self.assertEqual(naru.load_history(), {})
        naru.remember(EPS[0], "dub", 10.0)
        self.assertEqual(naru.load_history()["spots"]["dub"]["position"], 10.0)

    def test_clock(self):
        self.assertEqual([naru.clock(s) for s in (0, 754, 3723)], ["0:00", "12:34", "1:02:03"])

    def test_real_mpv_plays_a_whole_session_in_one_window(self):
        # three generated 2s "episodes" through a real mpv and its IPC (pipe or socket).
        # NARU_TEST_MPV makes this mandatory (CI's install stage)
        forced = os.environ.get("NARU_TEST_MPV")
        cmd = [forced] if forced else naru.find_mpv("mpv")
        if not cmd:
            self.skipTest("mpv not installed")
        sent = []
        real_command = naru.MpvIpc.command

        def spy(ipc, *args, **named):
            sent.append(named.get("name") or args[0])
            return real_command(ipc, *args, **named)

        def lavfi(ep):
            return f"av://lavfi:testsrc=duration=2:size=64x64:rate={10 + ep['number']}"
        with mock.patch.object(naru, "stream_url", lavfi), \
                mock.patch.object(naru.MpvIpc, "command", spy), \
                mock.patch.object(naru, "POLL", 0.1), \
                contextlib.redirect_stderr(io.StringIO()):
            # --idle=yes: what mpv 0.42's mpv.exe does with no console. naru has to
            # override it, or mpv idles after the last episode and the session never ends
            got = naru.play_session([*cmd, "--no-config", "--vo=null", "--ao=null",
                                     "--really-quiet", "--idle=yes"], EPS[:3], 0, "sub")
        self.assertEqual(got, (2, None, "done"))
        self.assertEqual(sent.count("loadfile"), 2)                    # 2 and 3 appended


class Loop(unittest.TestCase):
    """mpv-android: one episode at a time, then a menu."""

    def run_loop(self, start, script):
        launched, menus = [], []

        def menu(opts, default, header):
            menus.append((opts, default, header))
            return [v for _, v in opts].index(script.pop(0))
        with mock.patch.object(naru, "launch", lambda c, u, t: launched.append((u, t))), \
                mock.patch.object(naru, "menu_pick", menu), \
                contextlib.redirect_stderr(io.StringIO()):
            naru.play_loop(None, ARCS, EPS, start, "sub")
        return launched, menus

    def test_next_replay_previous(self):
        forget()
        launched, menus = self.run_loop(2, ["next", "replay", "prev", "quit"])
        self.assertEqual([u for u, _ in launched], [naru.stream_url(EPS[i]) for i in (2, 3, 3, 2)])
        self.assertEqual(launched[1][1], "Chūnin Exams 01")
        opts, default, header = menus[0]
        self.assertEqual(opts[default][1], "next")
        self.assertEqual(header, "\nLand of Waves 03 opened in mpv-android:")
        self.assertEqual(naru.load_history()["spots"]["sub"]["episode"], 3)   # counted watched

    def test_defaults_to_quit_on_the_last_episode(self):
        _, menus = self.run_loop(7, ["quit"])
        opts, default, _ = menus[0]
        self.assertEqual(opts[default][1], "quit")
        self.assertNotIn("next", [v for _, v in opts])


class ChapterSkip(unittest.TestCase):
    """the mpv script that skips openings and goes from the ending to the next episode."""

    def kind(self, title):
        """CHAPTER_SKIPPER's matching, in Python: whole words, %d* = digits. "intro" is
        an opening only in files with no chapter named like one."""
        for kind, table in (("opening", "OPENING"), ("ending", "ENDING"), ("intro", "INTRO")):
            words = re.findall(r'"([^"]+)"', re.search(rf"local {table} = \{{(.*)\}}",
                                                       naru.CHAPTER_SKIPPER)[1])
            if any(re.search(r"(?<![a-z0-9])" + w.replace("%d*", "[0-9]*") + r"(?![a-z0-9])",
                             title.lower()) for w in words):
                return kind
        return None

    def test_chapter_titles(self):
        # NaruCannon's files name theirs Opening, Episode and Ending
        for kind, titles in {
            "opening": ["Opening", "Opening Song", "OP", "OP2", "Opening Credits"],
            "intro": ["Intro"],
            "ending": ["Ending", "To Be Continued & Ending Song", "Credits", "ED", "Preview"],
            None: ["Episode", "Part A", "Episode Name", "Scene 5", "Introduction", "Edward"],
        }.items():
            for title in titles:
                self.assertEqual(self.kind(title), kind, title)

    # real mpv. episodes are built from the fixture with mpv's edl://, one segment (and
    # so one chapter) per part. NARU_TEST_MPV makes these mandatory (CI's install stage)

    def mpv(self):
        forced = os.environ.get("NARU_TEST_MPV")
        cmd = [forced] if forced else naru.find_mpv("mpv")
        if not cmd:
            self.skipTest("mpv not installed")
        return [*cmd, "--no-config", "--vo=null", "--ao=null", "--really-quiet"]

    def edl(self, *parts):
        """an episode of (chapter title, seconds) parts. mpv drops an edl's last segment
        from this fixture, so a short tail goes after them, named like a preview so
        the skipper never stops there."""
        fixture = os.path.join(ROOT, "tests", "fixtures", "clip.mkv")
        source = f"%{len(fixture.encode())}%{fixture}"
        return "edl://" + ";".join(f"{source},start=0,length={n},title={t}"
                                   for t, n in parts + (("Preview", 0.5),))

    def said(self, log, script="skip_chapters"):
        # (some mpv versions end each log line with a space)
        return re.findall(rf"\[i\]\[{script}\] (.*?) *$", read(log), re.M)

    def test_real_mpv_skips_the_opening_and_the_ending(self):
        # 1 is laid out like NaruCannon's files: Opening from the start, Episode, Ending.
        # 2 like other releases: story first, an "Intro" as its opening, and "Scene 5"
        # after the credits, the chapter after them that isn't an ending or a preview
        layouts = {1: (("Opening", 1.5), ("Episode", 1.5), ("Ending", 1.5)),
                   2: (("Scene 1", 1), ("Intro", 1.5), ("Scene 3", 1.5), ("Credits", 1.5),
                       ("Scene 5", 1.5))}
        ending = []
        real_get = naru.MpvIpc.get

        def spy(ipc, prop):
            got = real_get(ipc, prop)
            if prop == "user-data/naru/ending" and got:
                ending.append(got)
            return got
        log = os.path.join(CACHE.name, "skip.log")
        with mock.patch.object(naru, "stream_url", lambda ep: self.edl(*layouts[ep["number"]])), \
                mock.patch.object(naru.MpvIpc, "get", spy), \
                mock.patch.object(naru, "POLL", 0.1), \
                contextlib.redirect_stderr(io.StringIO()):
            got = naru.play_session([*self.mpv(), f"--log-file={log}", *naru.skip_args()],
                                    EPS, 0, "sub", stop=1)
        said = self.said(log)
        self.assertEqual(said[:5], ["skipped Opening", "skipped Ending", "ending: next episode",
                                    "skipped Intro", "skipped Credits"])
        self.assertLessEqual(set(said[5:]), {"skipped Preview"})     # if mpv plays the tail
        self.assertEqual(got, (1, None, "done"))
        self.assertIn(3.0, ending)          # where the ending starts, read over the IPC

    def test_real_mpv_rewind_pgdn_and_the_skip_key(self):
        # episode 1 is laid out like Jujutsu Kaisen: the story before the opening is
        # "Intro", and "Juju Stroll" (an extra) sits between the ending and the preview.
        # a driver script does what a viewer would: rewind to the start once the opening
        # is skipped, then PgDn back to the opening, then Tab. episode 2 has no chapters,
        # and gets Tab once
        driver = os.path.join(CACHE.name, "driver.lua")
        with open(driver, "w", encoding="utf-8") as fh:
            fh.write("""
local parts, pressed = 0, false
mp.add_timeout(20, function() mp.command("quit") end)        -- the skipper broke
mp.observe_property("chapter", "number", function(_, ch)
    local c = ch and (mp.get_property_native("chapter-list") or {})[ch + 1]
    if not c then return end
    if c.title == "Part A" then
        parts = parts + 1
        if parts == 1 then mp.commandv("seek", "0", "absolute") end     -- rewind
        if parts == 2 then mp.commandv("add", "chapter", "-1") end      -- PgDn
    elseif c.title == "Opening" and parts == 2 then
        mp.add_timeout(0.5, function() mp.commandv("script-binding", "skip_chapters/skip") end)
    end
end)
mp.register_event("file-loaded", function()
    if mp.get_property_number("chapter-list/count", 0) > 0 then return end
    mp.add_timeout(0.5, function()
        pressed = true
        mp.commandv("script-binding", "skip_chapters/skip")
    end)
end)
mp.register_event("playback-restart", function()
    if not pressed then return end
    mp.msg.info(string.format("at %.1f", mp.get_property_number("time-pos", -1)))
    mp.command("quit")
end)
""")
        fixture = os.path.join(ROOT, "tests", "fixtures", "clip.mkv")
        long = "edl://!no_chapters" + f";%{len(fixture.encode())}%{fixture}" * 60     # 120s
        log = os.path.join(CACHE.name, "keys.log")
        subprocess.run([*self.mpv(), f"--log-file={log}", *naru.skip_args(),
                        f"--script={driver}",
                        self.edl(("Intro", 1), ("Opening", 2), ("Part A", 3), ("Ending", 1.5),
                                 ("Juju Stroll", 1), ("Preview", 1)),
                        long], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        self.assertEqual(self.said(log), [
            "skipped Opening",          # "Intro" played: this file names its opening
            "skipped Opening",          # rewound before it: skipped again
            "skip key: Opening",        # PgDn brought it back, Tab skipped it
            "skipped Ending",           # to the extra after it, which plays
            "skipped Preview",
            "ending: next episode",
            "skip key: 85s",            # no chapters: an opening's worth
        ])
        at = float(self.said(log, "driver")[0].split()[1])
        self.assertTrue(85 <= at < 88, at)


# ------------------------------------------------------------------ setup

class Setup(unittest.TestCase):
    def patches(self, found, managers=("apt", "flatpak"), tty=False, answer=""):
        """mpv missing until a run of a manager listed in `found` completes."""
        state = {"installed": False, "ran": []}

        def run(cmd, **kw):
            state["ran"].append(cmd)
            if any(m in cmd for m in found):
                state["installed"] = True
            return subprocess.CompletedProcess(cmd, 0)

        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(naru, "ANDROID", False))
        stack.enter_context(mock.patch.object(naru, "_os_key", return_value="linux"))
        stack.enter_context(mock.patch.object(
            naru, "find_mpv", lambda mpv: ["/usr/bin/mpv"] if state["installed"] else None))
        stack.enter_context(mock.patch.object(
            naru.shutil, "which", lambda c: f"/usr/bin/{c}" if c in managers + ("sudo",) else None))
        stack.enter_context(mock.patch.object(naru.os, "geteuid", create=True, return_value=1000))
        stack.enter_context(mock.patch.object(naru.subprocess, "run", run))
        stack.enter_context(mock.patch.object(naru, "interactive_ok", return_value=tty))
        stack.enter_context(mock.patch("builtins.input", return_value=answer))
        stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        return stack, state

    def test_noninteractive_without_yes_explains(self):
        stack, state = self.patches(found=())
        with stack, self.assertRaises(SystemExit) as cm:
            naru.ensure_player("mpv")
        self.assertIn("sudo apt-get update && sudo apt-get install -y mpv", str(cm.exception))
        self.assertIn("naru --setup --yes", str(cm.exception))
        self.assertEqual(state["ran"], [])

    def test_yes_installs_and_falls_back_to_next_manager(self):
        stack, state = self.patches(found=("io.mpv.Mpv",))      # apt "fails", flatpak works
        with stack:
            self.assertEqual(naru.ensure_player("mpv", assume_yes=True), ["/usr/bin/mpv"])
        self.assertEqual(state["ran"][:2], [["sudo", "apt-get", "update"],
                                            ["sudo", "apt-get", "install", "-y", "mpv"]])
        self.assertEqual(state["ran"][-1][:3], ["flatpak", "install", "--user"])

    def test_prompt_yes_and_no(self):
        stack, _ = self.patches(found=("mpv",), tty=True, answer="")
        with stack:
            self.assertEqual(naru.ensure_player("mpv"), ["/usr/bin/mpv"])
        stack, state = self.patches(found=("mpv",), tty=True, answer="n")
        with stack, self.assertRaises(SystemExit):
            naru.ensure_player("mpv")
        self.assertEqual(state["ran"], [])

    def test_explicit_missing_path_and_no_manager(self):
        stack, _ = self.patches(found=())
        with stack, self.assertRaisesRegex(SystemExit, "mpv not found at /opt/x/mpv"):
            naru.ensure_player("/opt/x/mpv")
        stack, _ = self.patches(found=(), managers=())
        with stack, self.assertRaisesRegex(SystemExit, "no supported package manager"):
            naru.ensure_player("mpv", assume_yes=True)

    def test_sudo_is_dropped_for_root_or_when_missing(self):
        cmd = ["sudo", "apt-get", "install", "-y", "mpv"]
        with mock.patch.object(naru.os, "geteuid", create=True, return_value=0), \
                mock.patch.object(naru.shutil, "which", return_value="/usr/bin/sudo"):
            self.assertEqual(naru._sudo(cmd), cmd[1:])
        with mock.patch.object(naru.os, "geteuid", create=True, return_value=1000), \
                mock.patch.object(naru.shutil, "which", return_value="/usr/bin/sudo"):
            self.assertEqual(naru._sudo(cmd), cmd)
        with mock.patch.object(naru.os, "geteuid", create=True, return_value=1000), \
                mock.patch.object(naru.shutil, "which", return_value=None):
            self.assertEqual(naru._sudo(cmd), cmd[1:])

    def test_find_mpv_in_install_dir_and_flatpak(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = os.path.join(tmp, "mpv.exe" if os.name == "nt" else "mpv")
            open(exe, "w").close()
            with mock.patch.object(naru.shutil, "which", return_value=None), \
                    mock.patch.dict(naru.MPV_DIRS, {naru._os_key(): [tmp]}):
                self.assertEqual(naru.find_mpv("mpv"), [exe])
        with mock.patch.object(naru.shutil, "which",
                               lambda c: "/usr/bin/flatpak" if c == "flatpak" else None), \
                mock.patch.dict(naru.MPV_DIRS, {naru._os_key(): []}), \
                mock.patch.object(naru.glob, "glob", return_value=[]), \
                mock.patch.object(naru.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 0)):
            self.assertEqual(naru.find_mpv("mpv"), ["flatpak", "run", "io.mpv.Mpv"])
        with mock.patch.object(naru.shutil, "which", return_value=None):
            self.assertIsNone(naru.find_mpv("/definitely/not/here/mpv"))


class Update(unittest.TestCase):
    """--update reinstalls from main into the environment naru runs from."""

    def update(self, layout="site", venv=True, uv="/bin/uv", new="9.0.0", fail=False, pkg=None):
        """`naru --update` with naru.py in site-packages ("site"), a git checkout
        ("git") or on its own ("file"). -> (exit code, output, commands run)"""
        ran = []

        def run(argv, **kw):
            ran.append(argv)
            if "-c" in argv:                            # asking the new naru its version
                return subprocess.CompletedProcess(argv, 0, stdout=new + "\n")
            return subprocess.CompletedProcess(argv, 1 if fail else 0)
        with tempfile.TemporaryDirectory() as tmp:
            if layout == "git":
                os.mkdir(os.path.join(tmp, ".git"))
            site = tmp if layout == "site" else os.path.join(tmp, "site-packages")
            with mock.patch.object(naru, "__file__", os.path.join(tmp, "naru.py")), \
                    mock.patch.object(naru.sysconfig, "get_paths",
                                      lambda: {"purelib": site, "platlib": site}), \
                    mock.patch.object(naru.sys, "prefix", "/venv" if venv else "/usr"), \
                    mock.patch.object(naru.sys, "base_prefix", "/usr"), \
                    mock.patch.object(naru.shutil, "which", lambda c: uv if c == "uv" else None), \
                    mock.patch.object(naru.subprocess, "run", run), \
                    mock.patch.dict(os.environ):
                os.environ.pop("NARU_PKG", None)
                if pkg:
                    os.environ["NARU_PKG"] = pkg
                code, out, err = run_main("--update")
        return code, out + err, ran

    def test_a_uv_tool_or_pipx_venv_is_reinstalled_in_place(self):
        # in place with uv pip: `uv tool install --force` deletes the venv first, and
        # Windows can't delete the python.exe running naru
        code, out, ran = self.update()
        self.assertEqual(ran[0], ["/bin/uv", "pip", "install", "--python", sys.executable,
                                  "--reinstall", naru.PACKAGE])
        self.assertIn("-I", ran[1])                     # not a naru.py in this folder
        self.assertIn(f"updated naru {naru.__version__} -> 9.0.0", out)
        self.assertFalse(code)
        self.assertIn("already the newest", self.update(new=naru.__version__)[1])

    def test_termux_or_no_uv_uses_pip_like_the_installer(self):
        pip = [sys.executable, "-m", "pip", "install", "--upgrade", "--force-reinstall"]
        self.assertEqual(self.update(venv=False)[2][0], pip + [naru.PACKAGE])
        self.assertEqual(self.update(uv=None)[2][0], pip + [naru.PACKAGE])
        self.assertEqual(self.update(pkg="/tmp/naru.whl")[2][0][-1], "/tmp/naru.whl")

    def test_a_failed_update_says_to_run_the_installer(self):
        code, _, ran = self.update(fail=True)
        self.assertIn("update failed", code)
        self.assertIn(naru.INSTALLER, code)
        self.assertEqual(len(ran), 1)
        self.assertIn("doesn't start", self.update(new="")[0])

    def test_a_git_checkout_or_a_single_file_is_left_alone(self):
        code, _, ran = self.update("git")
        self.assertIn("git pull", code)
        self.assertEqual(ran, [])
        code, _, ran = self.update("file")
        self.assertIn("single file", code)
        self.assertIn(naru.INSTALLER, code)
        self.assertEqual(ran, [])


class Android(unittest.TestCase):
    def test_no_mpv_needed_and_setup_points_to_app(self):
        with mock.patch.object(naru, "ANDROID", True):
            self.assertIsNone(naru.ensure_player("mpv"))
            code, out, _ = run_main("--setup")
        self.assertEqual(code, 0)
        self.assertIn("is.xyz.mpv", out)

    def test_intent_and_errors(self):
        seen = []
        ok = subprocess.CompletedProcess([], 0, "Starting: Intent", "")
        with mock.patch.object(naru.subprocess, "run", lambda c, **k: seen.append(c) or ok):
            naru.android_open("https://x/ep.mp4")
        self.assertEqual(seen[0], ["am", "start", "--user", "0", "-a", "android.intent.action.VIEW",
                                   "-d", "https://x/ep.mp4", "-n", "is.xyz.mpv/.MPVActivity"])
        bad = subprocess.CompletedProcess([], 0, "", "Error: Activity class does not exist")
        with mock.patch.object(naru.subprocess, "run", return_value=bad), \
                self.assertRaisesRegex(SystemExit, "mpv-android"):
            naru.android_open("https://x")
        with mock.patch.object(naru.subprocess, "run", side_effect=FileNotFoundError), \
                self.assertRaisesRegex(SystemExit, "termux-am"):
            naru.android_open("https://x")


if __name__ == "__main__":
    unittest.main()
