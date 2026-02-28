# Changelog

## 0.1.0 - 2026-02-28

### Added
- Initial CLI script to fix Wise `camt.053.001.10` statements for strict importers:
  - Downgrade namespace to `camt.053.001.02`
  - Normalize `<Sts>` structure
  - Remove `<TtlNtries>`
  - Move `<AddtlNtryInf>` to `RmtInf/Ustrd`
  - Ensure `AcctSvcrRef`
  - Normalize date nodes to `<Dt>`
