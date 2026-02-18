# ck3_exec Keystone Migration — Final Execution Policy

> **Issued:** February 17, 2026 — Nate  
> **Status:** Active  
> **Parent Directive:** Phase 2 Keystone Migration Directive  
> **Tool:** ck3_exec

---

## 0) Classification

- `ck3_exec` is a **privileged break-glass execution tool** requiring explicit human authorization.
- It is **not sandboxed**.

---

## 1) Inline Execution Disabled

The following are **prohibited**:

- `python -c`
- `python -m`
- Arbitrary shell strings
- Pipelines
- Multiple commands

**Only allowed execution form:**

```
python <script_path>
```

---

## 2) Script Location Restriction (Mandatory)

The script must:

- Resolve via WA2 with `require_exists=True`
- Be under: `root:ck3raven_data/wip/`

Any script outside this subtree:
→ **Invalid**
→ Do not execute

**No exceptions.**

---

## 3) Approval Token (HMAC)

Execution requires a valid approval token binding:

- Canonical `session_abs` script path
- SHA256 script hash
- Session-bound expiration (existing system behavior)

Server must verify:

- HMAC valid
- Path matches
- Hash matches current contents
- Session valid

Any failure:
→ **Invalid**
→ Do not execute

**Implementation note:** Uses the same HMAC shield-click signing mechanism used for protected file operations in the CK3 Lens Explorer extension sidebar.

---

## 4) Working Directory

If provided:

- Must resolve via WA2
- Must be within canonical roots
- Must not escape

If omitted:

- Default to script's parent directory (derived via WA2)
- **Never** default silently to process cwd

---

## 5) Output Leak Protection

Before returning reply:

- Leak-scan stdout/stderr
- Block if host paths detected

---

## 6) Explicit Non-Goals

We are **NOT** implementing:

- Filesystem syscall interception
- CPython audit hooks
- I/O API enforcement
- Sandboxing
- AST script inspection

This remains a privileged tool requiring human oversight.

---

## Strategic Note

This provides:

- Addressing governance (WA2)
- Execution location restriction
- Human approval binding
- Leak protection

This is strong for an interim break-glass model. It is not security sandboxing. But it is **honest governance**.
