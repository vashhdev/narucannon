# naru installer for Windows:
#   irm https://raw.githubusercontent.com/vashhdev/narucannon/main/install.ps1 | iex
# installs uv (which fetches its own Python if you have none), then naru, then mpv.
# re-run it any time to update.
#
# env overrides (used by CI):
#   NARU_PKG=<path, url or requirement>   install this instead of the latest main
#   NARU_YES=1                            install mpv without asking
& {
    # judge every step by its exit code. "Stop" would make Windows PowerShell 5.1 treat
    # uv's normal progress output on stderr as fatal whenever output is redirected
    $ErrorActionPreference = "Continue"
    $pkg = "narucannon-mpv @ https://github.com/vashhdev/narucannon/archive/refs/heads/main.zip"
    if ($env:NARU_PKG) { $pkg = $env:NARU_PKG }

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        powershell -NoProfile -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
        if ($LASTEXITCODE) { throw "uv install failed" }
    }
    $env:Path = (Join-Path $env:USERPROFILE ".local\bin") + ";" + $env:Path

    uv tool install --force --reinstall $pkg
    if ($LASTEXITCODE) { throw "naru install failed" }

    if ($env:NARU_YES) { naru --setup --yes } else { naru --setup }
    if ($LASTEXITCODE) { throw "mpv setup failed" }
    Write-Host ""
    Write-Host "done. run: naru   (open a new terminal first if the command is not found)"
}
