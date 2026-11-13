# narucanon

[![CI](https://github.com/vashhdev/narucanon/actions/workflows/ci.yml/badge.svg)](https://github.com/vashhdev/narucanon/actions/workflows/ci.yml)

Stream the **NaruCannon Recut** straight into [mpv](https://mpv.io): Naruto and Naruto Shippuden with the filler cut out, 242 episodes over 13 arcs, in English dub or Japanese with English subs. Pick an arc and an episode, and one mpv window plays on from there, arc after arc, hands-free. The command is `naru`.

The NaruCannon Recut has no website or player, just two pixeldrain folders ([sub](https://pixeldrain.net/d/CEG3sGRE), [dub](https://pixeldrain.net/d/qqyKh8x5)) of big `.mp4` files. naru turns them into something you can actually binge, the way [onepace](https://github.com/vashhdev/onepace) does for One Pace and [reanime](https://github.com/vashhdev/reanime) for everything else.

- **One-line install** - sets up Python (if needed), naru, and mpv for you.
- **Runs everywhere** - Windows, macOS, Linux, Steam Deck, and Android (Termux + mpv-android).
- **Zero dependencies** - pure Python standard library.
- **Interactive picker** - type to filter, `↑`/`↓` to move, `Enter` to select. Accents don't matter: `chunin` finds Chūnin Exams.
- **Binge mode** - one mpv window keeps going, from the end of one arc into the next. Volume and fullscreen stay put.
- **Skips openings and endings** - NaruCannon's files mark their Opening and Ending as chapters, so mpv jumps past the opening and from the ending straight into the next episode. `Tab` skips by hand.
- **Picks up where you left off** - for sub and dub separately. Plain `naru` offers "Pain's Assault 07 (dub) at 12:34", and mpv reopens at your last volume.
- **Extended cuts** - 7 episodes have a longer cut. `--extended` plays those instead.
- **Playlists that keep working** - the links never expire, so an `--m3u` made on your computer plays on your phone next week.

## Install

**Windows** (PowerShell):

```powershell
irm https://raw.githubusercontent.com/vashhdev/narucanon/main/install.ps1 | iex
```

**macOS / Linux / Steam Deck / Android (Termux)**:

```bash
curl -fsSL https://raw.githubusercontent.com/vashhdev/narucanon/main/install.sh | sh
```

The installer:

1. installs [uv](https://docs.astral.sh/uv/), which downloads its own Python if you don't have one (Termux uses its own `python` package instead),
2. installs naru as a global `naru` command,
3. runs `naru --setup`, which finds mpv or offers to install it with your system's package manager.

Then open a new terminal and run `naru`. To update later, run `naru --update` (or the same command again).

### Manual install

If you already have Python 3.8+:

```bash
uv tool install git+https://github.com/vashhdev/narucanon     # or: pipx install git+https://github.com/vashhdev/narucanon
naru --setup                                                   # find or install mpv
```

Or just grab the single file and run `python naru.py`. It works without installing, and offers to install mpv the first time you play something.

## Platforms

| Platform | Player | How mpv gets installed |
| --- | --- | --- |
| Windows 10/11 | mpv | `winget` (falls back to `scoop`, then `choco`) |
| macOS | mpv | `brew` (or MacPorts) |
| Linux | mpv | `apt`, `dnf`, `pacman`, `zypper`, `apk`, `xbps`, or `nix` |
| Steam Deck, Fedora Silverblue, other immutable distros | mpv (flatpak) | `flatpak install --user io.mpv.Mpv`, no root needed |
| Android | [mpv-android](https://github.com/mpv-android/mpv-android) app | install it yourself from Google Play or F-Droid; naru runs in [Termux](https://termux.dev) and opens each episode in the app |
| iOS | none | `--m3u` a playlist on your computer and open it in VLC or Outplayer |

## Usage

```bash
naru                        # continue where you left off, or pick audio, arc and episode
naru pain                   # skip the arc picker: any part of the arc's name works
naru pain 7 --dub           # Pain's Assault 07, then on and on, arc after arc, until you quit
naru pain 3-9 --dub         # just these
naru pain 3- --dub          # 3 to the end of the arc
naru 4.5                    # arcs by number too (a number on its own is the arc, not an episode)
naru chunin 16 --extended   # the extended cut
naru --list                 # every arc
naru war --list             # the episodes of an arc, with file sizes
naru pain --m3u             # a playlist of the whole arc, for your phone
naru pain 7 --print         # print the stream url instead of playing
```

### The arcs

| # | Arc | Episodes | Extended cut |
| --- | --- | --- | --- |
| 1 | Land of Waves | 13 | |
| 2 | Chūnin Exams | 38 | 16 |
| 3 | Search for Tsunade | 12 | 12 |
| 4 | Sasuke Retrieval Mission | 22 | |
| 4.5 | Kakashi Chronicles | 1 | |
| 5 | Kazekage Rescue Mission | 13 | |
| 6 | Tenchi Bridge Mission | 11 | |
| 7 | Akatsuki Suppression Mission | 12 | |
| 8 | Itachi Pursuit Mission | 16 | |
| 9 | Pain's Assault | 15 | |
| 10 | Five Kage Summit | 14 | 14 |
| 11 | Fourth Great Ninja War | 71 | 13, 33, 70, 71 |
| 12 | Sarada Uchiha | 4 | |

That's the shares as of November 2026. naru reads the folders every time it starts, so new arcs and re-uploads show up on their own; `naru --list` shows what's there now.

### Interactive controls

| Where                  | Keys                                                                   |
| ---------------------- | ---------------------------------------------------------------------- |
| Arc / episode picker   | type to narrow · `↑`/`↓` move · `Enter` select · `Esc` cancel          |
| Audio, after-mpv menu  | press the number · `Enter` for the default (your last audio, resume or next episode) |
| In mpv                 | `Enter` or `>` next episode · `<` previous · `Tab` skip the opening (or this chapter) · `PgDn` watch a skipped opening · `q` stop (naru then offers to resume) |

### Flags

| Flag            | Description                                                       |
| --------------- | ----------------------------------------------------------------- |
| `--dub`         | English dub                                                       |
| `--sub`         | Japanese audio, English subs (the default, unless you watched the dub last) |
| `--extended`    | play the extended cut of the episodes that have one               |
| `--list`        | list every arc (or, with an arc, its episodes) and exit           |
| `--print`       | print stream urls, don't launch a player                          |
| `--m3u [PATH]`  | write an `.m3u` playlist instead: the whole arc, or the episodes you give |
| `--mpv PATH`    | path to the mpv binary (default: found automatically)             |
| `--no-skip`     | play openings and endings instead of skipping them                |
| `--setup`       | find or install mpv, then exit                                    |
| `-y`, `--yes`   | install mpv without asking if it's missing (scripts, CI)          |
| `--update`      | update naru to the newest version (a git checkout says to `git pull` instead) |

## Sub, dub and extended cuts

- **Sub and dub are two separate folders**, laid out the same way. The sub files have the English subtitles burned into the picture, over the Japanese audio, so there's no subtitle track to pick or resize. `--sub` and `--dub` just choose the folder.
- **Your place is kept for each separately.** Watching the dub doesn't move where you were in the sub, and plain `naru` offers both, the one you used last first.
- **Extended cuts** live in an `Extended Episode(s)` folder inside their arc. naru plays the standard cut unless you pass `--extended`, and the picker marks the episodes that have one. Resuming a position from one cut in the other starts that episode over, since the times don't line up.

## mpv tips

- The opening and ending skip goes by chapter names. NaruCannon's files are marked "Opening" (when the episode has one), "Episode" and "Ending", so the opening is skipped and the ending goes straight to the next episode. Quitting during an ending counts the episode as watched.
- Only what playback runs into is skipped. Jump or seek to an opening or ending yourself (`PgDn` right after a skip goes back to the opening) and it plays; rewind to before it and it's skipped again.
- `Tab` skips by hand: past the chapter that's playing (the ending goes to the next episode), or 85 seconds when the next chapter is more than 2.5 minutes away. To use another key, add `KEY script-binding skip_chapters/skip` to your mpv `input.conf`.
- Episodes queue up one at a time, so `Enter` right after an episode starts may need a second press once the next one is in (a second or so).
- Where you left off is kept in `%APPDATA%\naru\history.json` on Windows (`~/Library/Application Support/naru` on macOS, `~/.local/state/naru` on Linux). Delete it to forget everything.
- The episodes are big (roughly 400 MB to 1 GB each) and stream from pixeldrain, which is free and can slow down or turn away very heavy use. If an episode stalls, give it a while and try again.
- **mpv-android:** naru opens one episode at a time and asks what's next. Or skip Termux: make a playlist on your computer with `naru pain --m3u`, send it to your phone, and open it in mpv-android or VLC.

## How it works

1. Lists the NaruCannon share on pixeldrain (`/api/filesystem/<share>?stat`): one folder per arc, `1 - Land of Waves` through `12 - Sarada Uchiha`.
2. Lists every arc folder in parallel for its episode files, plus the `Extended Episode(s)` folder where there is one. About two seconds for the whole series.
3. Hands mpv `https://pixeldrain.net/api/filesystem/<share>/<arc>/<file>`, which it streams with range requests, so seeking works and nothing is saved to disk.

The links are plain file paths that never expire, but naru still runs one mpv window per session and talks to it over its JSON IPC (a named pipe on Windows, a socket elsewhere): it adds each next episode while the one before it plays, and reads where you are so it can offer to resume. mpv-android can't be driven that way, so on Android naru opens one episode at a time.

## Development

The tests run offline against a fixture folder tree shaped like the real shares (an accented arc name, a 4.5 arc, an extended folder, a stray `.mkv`), so they need no network. Three of them also drive a real mpv (a whole binge session, and two for the opening and ending skip) when one is installed, and are skipped otherwise:

```bash
python -m unittest discover -s tests -v
uvx ruff check .
```

Every push and pull request runs the [CI pipeline](.github/workflows/ci.yml) in stages. Each stage only runs if the one before it passed:

| Stage | What it checks |
| --- | --- |
| 1 · lint | ruff on the Python, shellcheck on `install.sh`, `install.ps1` parses |
| 2 · test | the offline suite on Windows, macOS and Linux, with Python 3.8 and 3.13 |
| 3 · build | the package builds and its metadata is valid |
| 4 · install | the real one-line installers on fresh Windows, macOS and Linux machines: uv, naru, mpv through the system package manager, then mpv plays a test clip. Termux runs in Docker as an experimental job |
| 5 · live | the NaruCannon shares still read: every arc of both, and mpv opens real episodes (an accented arc, an extended cut) and finds their chapters |
| 6 · release | on a `v*` tag: checks the tag matches the version, then publishes a GitHub release with the changelog notes |

The pipeline also runs daily, so if the shares move or change shape, the **live** stage fails.

To release: bump `__version__` in `naru.py` and `version` in `pyproject.toml`, add a CHANGELOG section, then `git tag v1.0.1 && git push --tags`.

## Disclaimer

The NaruCannon Recut is an unofficial fan edit. naru only automates reading the public pixeldrain folders it's shared in; it hosts nothing and stores nothing but your place in the series. If you can, support the official release (Naruto and Naruto Shippuden stream on Crunchyroll, among others). You are responsible for how you use this software and for complying with the terms of the services it talks to.

## License

[MIT](LICENSE)
