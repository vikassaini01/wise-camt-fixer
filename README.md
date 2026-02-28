# wise-camt-fixer

Fix Wise bank statement exports (ISO 20022 `camt.053.001.10`) to be more compatible with strict accounting importers (e.g., SimpleBooks) by rewriting them into a more widely supported shape (`camt.053.001.02`) and normalizing a few structures.

## What it does

For typical Wise `camt.053.001.10` statement XMLs, this tool:

- Rewrites namespace/version `camt.053.001.10` → `camt.053.001.02`
- Normalizes entry status:
  - `<Sts><Cd>BOOK</Cd></Sts>` → `<Sts>BOOK</Sts>`
- Removes statement totals block `<TtlNtries>` (some importers reject it)
- Moves `<AddtlNtryInf>` into transaction remittance:
  - `NtryDtls/TxDtls/RmtInf/Ustrd`
- Ensures `AcctSvcrRef` exists (best-effort fallback)
- Normalizes dates to `<Dt>` (date-only) if given as `<DtTm>`

> The output remains ISO 20022 camt.053 and is designed to be "importer-friendly", not to invent missing financial data.

## Requirements

- Python 3.10+ (3.8+ usually works, but 3.10+ recommended)
- No external dependencies (uses only the standard library)

## Usage

### Fix one file (writes `*_FIXED.xml`)

```bash
python fix_wise_camt053.py statement.xml
