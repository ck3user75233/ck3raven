# Active Playset Filtering - Requirements & Task

> **Status:** SUPERSEDED  
> **Superseded By:** [LENSWORLD.md](../LENSWORLD.md)  
> **Created:** December 26, 2025  
> **Archived:** December 28, 2025

---

## Historical Context

This document captured the original requirements for playset filtering before the LensWorld architecture was designed.

The core problem statement and requirements have been addressed by:
- **LENSWORLD.md** - Canonical visibility architecture
- **CK3LENS_POLICY_ARCHITECTURE.md** - Policy enforcement layer
- **WorldAdapter/WorldRouter** - Implementation in `ck3lens/`

---

## Original Problem Statement

> **Critical Safety Issue:** ck3lens agent previously could see ALL mods in `/mod/` folder and nearly damaged mods that weren't in the active playset by trying to "fix" errors that appeared in logs.

### Core Principle (Now Implemented via LensWorld)
> At NO point in time should ck3lens ever see, touch, or query mods that are NOT IN THE ACTIVE PLAYSET.

This is now enforced by LensWorldAdapter returning NOT_FOUND for any reference outside the active playset.

---

## Architecture Decision

The architecture analysis in this document identified:
1. Database-based playsets (deprecated)
2. File-based playsets (intended design)
3. PlaysetLens class for filtering

This led to the WorldAdapter/WorldRouter pattern where:
- PlaysetLens handles DB query filtering
- PlaysetScope handles filesystem path validation
- WorldAdapter composes both as a facade
- WorldRouter provides canonical mode detection

---

## See Also

- [LENSWORLD.md](../LENSWORLD.md) - Canonical architecture
- [CK3LENS_POLICY_ARCHITECTURE.md](../CK3LENS_POLICY_ARCHITECTURE.md) - Policy layer
- `ck3lens/world_adapter.py` - Implementation
- `ck3lens/world_router.py` - Mode detection and adapter injection
