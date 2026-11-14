# Changelog

All notable changes to this project are documented here. This project follows
[Semantic Versioning](https://semver.org).

## [1.1.0] - 2026-11-14

### Added

- **Android binges too.** mpv-android now gets everything from your episode on as
  one playlist, arc after arc (or just the range you asked for), so it plays on by
  itself instead of stopping after each episode. When you're back in Termux, naru
  asks which episode you stopped in, so plain `naru` continues from there.
- **Opening and ending skip on Android.** `naru --mpv-conf` prints a profile for
  mpv-android's mpv.conf (Settings > Advanced > Edit mpv.conf) that skips the
  opening and goes from the ending to the next episode, like on desktop. Seek into
  either yourself and it plays. `naru --setup` on Termux explains how.

### Changed

- On Android, a resume position and an episode range (`naru pain 3-9`) are passed on
  to mpv-android. They used to be ignored there.

## [1.0.0] - 2026-11-13

### Added

- **Stream the NaruCannon Recut in mpv.** Pick sub or dub, an arc and an episode,
  and one mpv window plays on from there, from arc to arc, until you quit. Arcs come
  straight from the NaruCannon shares on pixeldrain, so new arcs show up on their own.
- **Arcs by name or number.** `naru pain 7`, `naru chunin` (no accent needed),
  `naru 4.5`. Ranges: `3-9`, or `3-` to the end of the arc.
- **Skips openings and endings** using the files' own chapters, straight into the
  next episode. `Tab` skips by hand, `--no-skip` turns it off.
- **Picks up where you left off**, for sub and dub separately. Plain `naru` offers
  "Pain's Assault 07 (dub) at 12:34", and mpv reopens at your last volume.
- **`--extended`** plays the extended cut of the 7 episodes that have one.
- `--list`, `--print`, `--m3u` (the links never expire, so playlists keep working on
  a phone), `--setup`, `--update`.
- One-line installers for Windows, macOS, Linux and Android (Termux + mpv-android).
