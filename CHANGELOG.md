# Changelog

All notable changes to this project are documented here. This project follows
[Semantic Versioning](https://semver.org).

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
