# 🔐 Security Policy

![Security](https://img.shields.io/badge/Security-Policy-blue)
![Status](https://img.shields.io/badge/Status-Active-success)

---

## 🧠 Overview

Jarvis interacts with:

* external APIs
* system-level tools
* local user-selected documents
* user inputs

Security and reliability are **critical priorities**.

---

## 🚨 Reporting Vulnerabilities

If you discover a security issue:

1. **Do NOT open a public issue**
2. Report privately via:

   * GitHub Security Advisory (preferred)
   * or trusted direct maintainer contact

Include:

* clear description
* steps to reproduce
* potential impact
* affected files/modules (if known)

---

## ⚠️ Sensitive Areas

Pay special attention to:

* API key handling (`.env`)
* system command execution
* tool execution safety
* external API responses
* document file validation and parser pipeline behavior

---

## 🔑 Secrets Management

* Never commit `.env` files
* Use `.env.example` as reference
* Rotate compromised keys immediately
* Treat `GROQ_API_KEY`, `SERPER_API_KEY`, and `HF_TOKEN` as sensitive

---

## 🛡️ Safe Usage Guidelines

* Validate all tool outputs
* Do not trust external APIs blindly
* Avoid executing unsafe system commands
* Ensure proper error handling
* Keep fallback messaging human-readable to avoid exposing internal tool payloads
* Keep file-picking and path validation in system code, never model-controlled logic
* Restrict document inputs to supported file types and sane size limits

---

## 📄 Document Pipeline Security Notes

Current hardening expectations:

* File selection remains user/system initiated
* Paths are validated before parsing
* Unsupported or oversized files are rejected
* Fail-open behavior should return safe errors, not partial unsafe execution
* Document cache stores derived intelligence locally; protect host access and clear cache on sensitive systems

Operational hardening expectations:

* Connectivity checks should remain deterministic and probe-backed
* Forecast/rain weather responses should use daily weather payloads where available

---

## 🚫 Known Limitations

* Depends on third-party APIs
* No full sandboxing for system tools
* Requires user supervision for critical actions
* OCR/vision quality depends on external models and network conditions

---

## 🧭 Policy Principle

> **Assume all inputs are untrusted. Validate everything.**

---

## 👤 Maintainer

**Deepak Rakshit**