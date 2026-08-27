# .NET 9 Upgrade Plan

## Overview

**Target**: FileServe.csproj — ASP.NET Core web application
**Scope**: Single project, ~640 LOC

## Selected Strategy
**All-At-Once** — Single project upgraded in one atomic operation.
**Rationale**: Single project, already on modern .NET (net8.0), SDK-style, no incompatible packages — straightforward TFM bump.

## Tasks

### 01-prerequisites: Verify SDK and toolchain compatibility

Ensure .NET 9 SDK is installed and any global.json files are compatible with the target framework. This prevents build failures after the TFM update.

**Done when**: .NET 9 SDK is verified installed, global.json compatibility confirmed (or updated if needed), toolchain ready for upgrade

---

### 02-upgrade-project: Update target framework and verify behavioral change

Update FileServe.csproj from net8.0 to net9.0 and verify the one behavioral change identified in the assessment: `UseForwardedHeaders()` behavior change in .NET 9.

The assessment identified:
- 1 behavioral change requiring runtime verification
- 0 incompatible packages
- 0 binary/source incompatible APIs
- Low complexity, minimal code changes expected

Key areas to review:
- Update TargetFramework property to net9.0
- Test UseForwardedHeaders() behavior — .NET 9 changed how this middleware handles forwarded headers
- Verify all 640 lines of code compile successfully

**Done when**: Project targets net9.0, solution builds with 0 errors and 0 warnings, UseForwardedHeaders() behavior verified in runtime context

---

### 03-final-validation: Build and test solution

Execute full solution build and run any available tests to confirm the upgrade is successful and the application functions correctly.

**Done when**: Solution builds successfully, all tests pass (if any), application is ready for deployment
