# INCI to CAS Document Builder

## Project Purpose
A regulatory documentation tool for the cosmetic industry. Takes an INCI panel (text, photo, or product URL) and outputs a verified CAS reference document matching regulatory submission standards (EWG Verified, supplier disclosure, customs documentation).

## Target Output Format
A `.docx` table with these columns:
| # | INCI Name | Common Name / Function | CAS Number | EINECS | HTS Code | Trade Name / Source | Verified (Y/N) |

Verified = Y when CAS pulled from authoritative source (CosIng, PubChem). Verified = N when AI-inferred and requires manual confirmation.

## Build Philosophy — READ BEFORE EVERY SESSION

### Phase Discipline
Build in strict phases. Do not skip ahead. Do not scaffold for future phases.

- **Phase 1:** CLI tool. Input = INCI string. Output = .docx file. No auth, no DB, no frontend, no API server.
- **Phase 2:** Add input handlers — photo OCR, URL scraping.
- **Phase 3:** Web app wrapper (Next.js) with login and saved projects. Only after Phase 1 + 2 are proven working.

### Hard Rules
- Never add authentication, user accounts, or session management before Phase 3.
- Never add a database before Phase 3. Local CSV/SQLite files for ingredient lookup are fine and expected.
- Never add a frontend, mobile app, or API server before Phase 3.
- Never add packages without justifying why in the commit message.
- Never assume an ingredient's CAS number from training data alone — always check local data sources first, mark unverified if falling back to LLM.
- Stop and confirm with the user before moving between phases.

## Data Sources (Phase 1)
1. **CosIng** — EU Commission cosmetic ingredient database. Public domain. Primary source for INCI → CAS + EINECS + function.
2. **PubChem REST API** — Free, no key. Fallback CAS verification.
3. **USITC HTS schedule** — Public JSON. HTS code lookup for ingredients and finished products.
4. **Anthropic API (Claude)** — Last-resort fallback for ingredients not found in 1–3. Always flag results as Verified=N.

## Tech Stack
- **Language:** Python 3.11+
- **Key libraries:** `python-docx` (output), `pandas` (CosIng CSV parsing), `requests` (PubChem/HTS), `anthropic` (LLM fallback)
- **Storage (Phase 1):** Local SQLite for cached lookups, CSV files for source data in `data/`

## Folder Conventions
- `src/` — application code
- `data/` — reference databases (CosIng, HTS, cache)
- `tests/` — pytest tests, especially for parsing edge cases
- `output/` — generated .docx files (gitignored)

## Testing Standard
Every parsing function and lookup function must have a test before it ships. Real-world INCI lists have weird formatting (parentheses, slashes, line breaks, CI numbers, asterisks for organic). Test cases must include actual product label panels.

## When in Doubt
Ask the user before adding scope. The previous attempt at this project failed because scope ballooned past the core engine before it was proven. The core engine is: INCI string in → verified .docx out. Everything else is wrapping paper.
