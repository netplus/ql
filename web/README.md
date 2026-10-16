# ql interactive page

This is the first working **private, self-contained browser page**, not a mock
screenshot or a live market feed. Build from the repository root:

```bash
python tools/build_page.py
# Open dist/index.html in a browser; no Node, server or CDN is required by the app.
python -m unittest discover -s tests -v
# Optional browser test dependency: Playwright and a compatible Chromium binary.
python tools/test_page_browser.py --browser /usr/bin/chromium --mode http
```

`dist/index.html` embeds CSS, JavaScript and a versioned data payload. The adjacent
manifest records input/output SHA256 hashes. It works by design as a single file
and under a Pages project subpath, using hash routing. Direct file/HTTP navigation
could NOT be validated in the current sandbox because its managed browser blocks
all URL navigation; see the recorded test limitations below.

## Implemented

- Overview, product comparison heatmap, details, local watchlist/notes, provenance.
- Six frozen ETF NAV series and one six-date share series from P0 evidence.
- Date selection; 1/5/20/60-trading-interval controls with strict missing history.
- SVG series toggles and click/keyboard point readouts; accessible evidence dialog.
- Desktop tables; mobile product cards; horizontally scrollable comparison matrix.
- Local favorites/notes, JSON export/import with validation and destructive-action
  confirmation. Storage errors are surfaced; notes are escaped plain text.
- Network-free loading. Only user-activated source links leave the page.

## Not implemented or verified

No live acquisition, daily automatic update, canonical industry funding ranking,
position/trade tracking, report revision replay, cross-device synchronization,
strategy backtest, native account authentication or trading. Notes are editable
current text, not an immutable research diary.

The original Vue/Vite/ECharts proposal is not a completed dependency baseline.
This limited P1 slice uses plain HTML/CSS/JS and native SVG to deliver a portable
page without package-network requirements. It is not a decision to prohibit a
later framework or chart-library migration.

## Evidence and publication

Read `docs/P1_PAGE_20261016.md`. Data dates are 2026-10-08 through 2026-10-15;
source excerpts were recorded previously, not reacquired during UI development.
The 510030 flow is explicitly conditional and hidden behind an explanatory
control. Admitted flow remains null. Missing fields never become zero.

This build is **private review only**. `--audience public` fails closed. It is not
sufficient to remove a UI warning to publish; a reviewed field/source release
policy and actual Pages capability are required. Do not publish the repository
root or the private samples automatically. No workflow was installed or run.

## Test modes

`--mode injected` loads the exact generated HTML into an existing Chromium
about:blank document with `set_content`, without navigating blocked URLs. It uses
an explicitly injected in-memory storage adapter for persistence tests. This
validates the application rendering and interaction code, not native storage or
hosting. `--mode http` is intended for a permitted environment with a loopback
server and native storage; it has not passed in this sandbox.

Chromium viewport/touch emulation is not a physical iPad or vivo device test.
WebKit, Safari, native file opening, hosted deep-link refresh and public deployment
remain unverified. Test outputs record mode, engine, navigation failures and
which persistence adapter was used. No browser policy was changed.
