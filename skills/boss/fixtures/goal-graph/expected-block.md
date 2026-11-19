<!-- ticket-graph:start (written by claude-boss from the Tickets source; edits here are overwritten) -->
```mermaid
flowchart TD
  t01["01 · Paths come from the track store<br/>done"]
  t02["02 · The pulse reads the graph frontier.py gives,…<br/>Farid"]
  t03["03 · A claim updates the graph<br/>ready"]
  t04["04 · The sweep runs every minute<br/>waiting"]
  t05["05 · Checked on a live goal page<br/>waiting"]
  x1["the owner opens the page in sheaf<br/>external"]
  t01 --> t02
  t01 --> t03
  t02 --> t04
  t03 --> t04
  t04 --> t05
  x1 -.-> t05
  classDef done fill:#d4f0da,stroke:#2e7d32,color:#16361c
  classDef claimed fill:#d6e5fa,stroke:#1f5fb4,color:#0e2a52
  classDef ready fill:#fbe8c0,stroke:#b7791f,color:#46300a
  classDef waiting fill:#e4e4e4,stroke:#777777,color:#2b2b2b
  classDef external fill:#f9dada,stroke:#c62828,color:#560f0f,stroke-dasharray:5 3
  class t01 done
  class t02 claimed
  class t03 ready
  class t04,t05 waiting
  class x1 external
```

5 tickets: 1 done, 1 in progress, 1 ready, 2 waiting · read 11:00
<!-- ticket-graph:end -->
