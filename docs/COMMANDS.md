# 📜 Commands Reference

![Commands](https://img.shields.io/badge/Commands-Supported-blue)

---

## 🌦️ Weather

```text
weather in delhi
weather in mumbai
i am in pune
weather?
will it rain today
forecast for tomorrow
```

---

## 🌐 Internet Search

```text
search on internet latest ai news
who is the PM of India
who won ipl 2025 season
```

---

## 📰 News-Style Queries

```text
latest ai news
technology news
latest india headlines
```

News prompts are routed through internet search evidence.

---

## 🌍 Network

```text
what is my ip
network location
check internet connectivity
am i online
```

---

## ⚙️ System

```text
system status
run speed test
what time is it
what is today's date
max volume
min volume
max brightness
min brightness
```

---

## 🧠 Context / Memory

```text
i am in greater noida
what is my location
my name is deepak
what is my name
```

---

## 📄 Document Intelligence

```text
analyze document
summarize this pdf
read this docx file
extract key points from this file
compare these documents
compare these two files for pricing and risks
what is the pricing in this document
list key entities from this file
which plan has the highest cost
open file picker
open document selector
```

When triggered, Jarvis opens a system file selector, validates the path, then runs the document pipeline.
After successful analysis, follow-up document questions are answered from active document context.

---

## 🖥️ App Control

```text
open chrome
open file explorer
open file manager
launch vscode
close spotify
close it
```

File explorer/manager requests route to app control and never trigger document picker flow.

---

## 💬 Conversational

```text
who are you
how r u
explain how internet works
```

---

## 🚫 Restricted Cases

```text
weather without using tools
```

Jarvis refuses live-data answers when tools are explicitly disallowed.

---

## 🎯 Multi-Intent Queries

```text
weather in delhi and latest ai news
what is my ip and latest ai updates
```

Handled through agent planning and synthesis.

---

## 🎤 Voice UX Control

Desktop UI includes a **SKIP** button that safely interrupts current TTS playback.

---

## 🧠 Tip

> Combine related queries for richer answers with fewer turns.