# .NET Version Upgrade to .NET 9

## Strategy
**Selected**: All-at-Once
**Rationale**: Single project, already on modern .NET (net8.0), straightforward TFM upgrade

### Execution Constraints
- Single atomic upgrade — project updated in one pass
- Validate full solution build after upgrade
- One behavioral change to verify: UseForwardedHeaders() in .NET 9

## Preferences
- **Flow Mode**: Automatic
- **Target Framework**: net9.0

## Source Control
- **Source Branch**: main
- **Working Branch**: upgrade-dotnet-9
- **Commit Strategy**: Single Commit at End
- **Branch Sync**: Auto (Merge)
