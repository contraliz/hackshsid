GridShift for macOS
===================

1. Extract the complete GridShift-macOS folder from the ZIP.
2. Double-click GridShift.command. If macOS blocks it the first time, Control-click
   the file, choose Open, and confirm.
3. On first launch, the script downloads Python 3.12 and GridShift's Python
   packages into your user Library. This requires an internet connection; it does
   not require Node.js, Homebrew, or administrator access. Later launches reuse
   the installed runtime.
4. GridShift opens in your default browser. Keep the Terminal window open while
   using it; press Control-C there to stop the local server.

The server listens only on this Mac at a 127.0.0.1 address. The workload, energy
prices, renewable supply, and emissions are synthetic demo data, not live
datacenter telemetry.
