# 02-upgrade-project: Update target framework and verify behavioral change

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
