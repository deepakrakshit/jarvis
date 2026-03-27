# 🛠️ Troubleshooting

![Debug](https://img.shields.io/badge/Debug-Guide-yellow)

---

## 🌦️ Wrong Weather Location

**Cause:**

* IP mismatch or tool error

**Fix:**

* explicitly provide location
* verify session memory

---

## 🌐 Search Not Working

**Cause:**

* invalid `SERPER_API_KEY`

**Fix:**

* update `.env`
* check network

---

## ⚙️ Tool Not Executing

**Cause:**

* routing failure

**Fix:**

* verify planner output
* check tool registry

---

## 🧠 Wrong Response Type

**Cause:**

* routing misclassification

**Fix:**

* inspect `core/runtime.py`
* refine intent patterns

---

## 🎤 Voice Delay

**Fix:**

* tune TTS config
* reduce chunk size

---

## 🚨 Golden Rule

> If output looks correct but feels wrong — debug it.