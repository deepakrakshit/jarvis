# 🔐 Security Policy

![Security](https://img.shields.io/badge/Security-Policy-blue)
![Status](https://img.shields.io/badge/Status-Active-success)

---

## 🧠 Overview

Jarvis interacts with:

* external APIs
* system-level tools
* user inputs

Security and reliability are **critical priorities**.

---

## 🚨 Reporting Vulnerabilities

If you discover a security issue:

1. **Do NOT open a public issue**
2. Contact privately via:

   * GitHub Issues (marked sensitive)
   * or direct communication

Include:

* clear description
* steps to reproduce
* potential impact

---

## ⚠️ Sensitive Areas

Pay special attention to:

* API key handling (`.env`)
* system command execution
* tool execution safety
* external API responses

---

## 🔑 Secrets Management

* Never commit `.env` files
* Use `.env.example` as reference
* Rotate compromised keys immediately

---

## 🛡️ Safe Usage Guidelines

* Validate all tool outputs
* Do not trust external APIs blindly
* Avoid executing unsafe system commands
* Ensure proper error handling

---

## 🚫 Known Limitations

* Depends on third-party APIs
* No full sandboxing for system tools
* Requires user supervision for critical actions

---

## 🧭 Policy Principle

> **Assume all inputs are untrusted. Validate everything.**

---

## 👤 Maintainer

**Deepak Rakshit**