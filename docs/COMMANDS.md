<div align="center">

[![Header](https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,3,30&height=160&section=header&text=Commands%20Reference&fontSize=38&fontColor=ffffff&animation=twinkling&fontAlignY=50)](.)

[![Commands](https://img.shields.io/badge/Commands-Full%20Reference-0066FF?style=for-the-badge)](.)
[![Updated](https://img.shields.io/badge/Status-Up%20to%20Date-00C853?style=for-the-badge)](.)

</div>

> **Tip:** JARVIS understands natural language. These examples show the phrase patterns that trigger each capability — you do not need to use exact wording.

---

## 🌦️ Weather

| Command | What It Does |
|---|---|
| `weather in delhi` | Current conditions for Delhi |
| `weather in mumbai` | Current conditions for Mumbai |
| `weather?` | Current conditions for your last used city |
| `what's the temperature in bangalore` | Temperature for a specific city |
| `forecast for tomorrow` | Tomorrow's min/max temp + condition + rain chance |
| `will it rain today` | Today's precipitation probability |
| `will it rain tomorrow` | Tomorrow's precipitation probability |

**Session location:** After saying `i am in pune`, bare `weather?` queries will use Pune automatically.

---

## 📍 Location & Session Context

| Command | What It Does |
|---|---|
| `i am in greater noida` | Sets session location for weather queries |
| `i'm in delhi` | Same — short form |
| `my location is bangalore` | Same — explicit form |
| `currently in mumbai` | Same — alternate phrasing |

---

## 🌐 Internet Search & News

| Command | What It Does |
|---|---|
| `latest ai news` | Web search for recent AI news |
| `technology news` | Recent tech headlines |
| `search for python frameworks` | Web search for a specific topic |
| `who is the PM of India` | Factual query via web evidence |
| `who won ipl 2025 season` | Sports result via web search |
| `what happened with the fed rate` | Current events query |
| `search on internet latest india news` | Explicit search command |

> All factual and current-events queries use **live web evidence** — not LLM training data.

---

## 🌍 Network Diagnostics

| Command | What It Does |
|---|---|
| `what is my ip` | Current public IP address |
| `public ip` | Same — short form |
| `external ip address` | Same — alternate form |
| `where am i` | Approximate location from IP geolocation |
| `network location` | IP-derived city, region, country, coordinates |
| `check internet connectivity` | Deterministic probe — confirms online/offline |
| `am i online` | Same — alternate form |
| `check network connectivity` | Same — alternate form |

---

## ⚡ Speed Test

| Command | What It Does |
|---|---|
| `run speed test` | Runs synchronous speed test and reports results |
| `test internet speed` | Same |
| `internet speed` | Same |
| `speedtest` | Same |
| `show speed results` | Returns last measured results (no re-test) |
| `are the results out` | Same — checks for cached result |
| `is my internet speed good` | Assessment vs. regional average |
| `below average speed?` | Same |
| `run speed test in background` | Starts async test; ask for results later |

---

## ⚙️ System Status & Time

| Command | What It Does |
|---|---|
| `system status` | CPU % · RAM % · Uptime · Time snapshot |
| `device status` | Same |
| `pc status` | Same |
| `what time is it` | Current local time |
| `local time` | Same |
| `what's today's date` | Full date |
| `what day is it` | Day of week |
| `what month is this` | Current month |
| `what year is it` | Current year |
| `system update status` | JARVIS version + update tracking info |

---

## 🔊 Volume Control

| Command | What It Does |
|---|---|
| `max volume` | Sets volume to 100% |
| `min volume` | Sets volume to 0% |
| `set volume to 60` | Sets volume to a specific level (0–100) |
| `increase volume` | Increases by 10% |
| `decrease volume` | Decreases by 10% |
| `raise volume by 20` | Increases by a specific step |
| `lower volume by 15` | Decreases by a specific step |
| `mute` | Mutes audio |
| `unmute` | Unmutes audio |

---

## ☀️ Brightness Control

| Command | What It Does |
|---|---|
| `max brightness` | Sets brightness to 100% |
| `min brightness` | Sets brightness to 0% |
| `set brightness to 75` | Sets brightness to a specific level (0–100) |
| `increase brightness` | Increases by 10% |
| `decrease brightness` | Decreases by 10% |
| `dim the screen` | Decreases brightness |
| `brighten the screen` | Increases brightness |

---

## 🪟 Window & Desktop Control

| Command | What It Does |
|---|---|
| `switch window` | Alt-Tab to next window |
| `minimize window` | Minimizes the active window |
| `restore window` | Restores the active window |
| `show desktop` | Win+D — minimizes all windows |
| `minimize all windows` | Minimizes all windows |
| `restore all windows` | Restores all minimized windows |
| `focus chrome window` | Brings Chrome to the foreground |
| `close notes window` | Closes the matching window |

---

## 🖥️ App Control

| Command | What It Does |
|---|---|
| `open chrome` | Launches Google Chrome |
| `launch vscode` | Launches Visual Studio Code |
| `open spotify` | Launches Spotify |
| `start calculator` | Launches Calculator |
| `open file explorer` | Opens Windows File Explorer (NOT document picker) |
| `open file manager` | Same — alternate phrasing |
| `close spotify` | Closes Spotify |
| `close it` | Closes the last app you opened |
| `terminate chrome` | Force-closes Chrome |

> **Disambiguation:** `open file explorer` / `open file manager` → OS file browser. `open file picker` / `open document selector` → document analysis workflow.

---

## 📄 Document Intelligence

### Triggering Analysis

| Command | What It Does |
|---|---|
| `analyze document` | Opens file picker → full pipeline analysis |
| `summarize this pdf` | Same |
| `read this docx file` | Same |
| `open file picker` | Same — explicit picker phrasing |
| `open document selector` | Same |
| `select a document` | Same |

**Supported formats:** PDF · DOCX · DOC (with guidance) · PNG · JPG · JPEG · TIFF · BMP · WEBP

### Follow-up Q&A (after analysis)

| Command | What It Does |
|---|---|
| `what is the pricing in this document` | Extracts pricing from active document |
| `list key risks` | Lists identified risks |
| `what are the plans mentioned` | Lists plan names |
| `list all entities` | Lists names, companies, dates, prices |
| `what does this say about the API` | Targeted content question |
| `find all price mentions` | Entity-focused extraction |

### Multi-Document Compare

| Command | What It Does |
|---|---|
| `compare these documents` | Comparison across all active documents (≥2) |
| `compare these two files for pricing and risks` | Targeted comparison |
| `which plan is cheaper` | Cost-focused comparison |
| `what are the differences` | General difference summary |
| `compare these documents` | Opens picker for 2+ files if no active documents |

---

## 🔐 System Actions

| Command | What It Does |
|---|---|
| `lock screen` | Locks the workstation |
| `lock workstation` | Same |

> **Restricted:** `sleep`, `shutdown`, `restart` are blocked for safety.

---

## 💬 Conversational

| Command | What It Does |
|---|---|
| `who are you` | JARVIS identity response |
| `what can you do` | Capabilities summary |
| `help` | Quick command reference |
| `how are you` | Wellbeing response |
| `hi` / `hello` / `hey` | Greeting |
| `my name is Deepak` | Stores your name in memory |
| `what is my name` | Recalls your stored name |

---

## 🔁 Correction & Refinement

| Command | What It Does |
|---|---|
| `that's wrong` | Re-checks last answer from available sources |
| `incorrect` | Same |
| `wrong answer` | Same |
| `search on internet` | Repeats last factual query via web search |
| `search internet` | Same |

---

## 🚫 Restricted Commands

| Command | Why Restricted |
|---|---|
| `weather without using tools` | Tool-forbidden real-time requests are refused |
| `shutdown` | Blocked system action |
| `restart` | Blocked system action |
| `delete files` | Blocked system action |

---

## 🎯 Multi-Intent Queries

JARVIS supports combining multiple information requests in a single turn:

```
weather in delhi and latest ai news
what is my ip and latest ai updates
system status and what time is it
```

The agent planner decomposes these into parallel tool calls and synthesizes a unified response.

---

## 🎤 Voice UX Controls

| Action | How |
|---|---|
| **Skip current reply** | Click the **SKIP** button in the desktop UI |
| **Voice input** | Speak naturally — Web Speech API is always listening in GUI mode |
| **Interrupt TTS** | Any new voice input while JARVIS is speaking uses the skip mechanism automatically |

---

<div align="center">

[![Footer](https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,3,30&height=100&section=footer)](.)

</div>