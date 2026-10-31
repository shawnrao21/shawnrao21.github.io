# shawnrao21.github.io

Personal site. Static HTML, no build step.

    index.html          main page
    resume.html         resume, with print styles
    games.html          co-op game finder
    data/               Steam store and SteamSpy snapshot, October 2026
    analysis.R          regressions behind the figures on games.html
    PROJECT_README.md   build notes for the game finder

`games.html` fetches JSON from `data/`, which browsers block over `file://`.
Serve the folder instead of opening the file directly:

    python3 -m http.server 8000

shawnrao@umich.edu
