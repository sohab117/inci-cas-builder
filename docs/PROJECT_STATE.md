# MJOLNIR — Project State Document

*Last updated: May 9, 2026. This is the canonical record of project state, decisions, and context. Read this on every session restart alongside CLAUDE.md.*

## What This Project Is

MJOLNIR is a personal regulatory + raw material reference tool built for 117 Holdings LLC, a small cosmetic manufacturing operation. The name is a nod to Formula 117 (Sohab's brand). It is intentionally narrow in scope and built to fit Sohab's actual operational scale (~40-50 raw materials, ~10-12 active formulas, 1-2 users).

The tool does three things:
1. **Analyzes INCI panels** — paste an ingredient list, get a regulatory CAS reference document
2. **Stores raw materials** — Sohab's personal database of ingredients he's actually sourced, with INCI, CAS, suppliers, pricing, supplier notes
3. **Generates `.docx` documents** — submission-ready CAS reference docs in the Vitasana / EWG format

The lookup chain prioritizes Sohab's own raw material database first, then falls back to public sources (CosIng → PubChem → Claude API).

## What This Project Is NOT

- Not a contract manufacturer's PLM (Product Lifecycle Management) system
- Not a multi-tenant SaaS product
- Not a public-facing tool
- Not designed for compliance with regulated industries (FDA, GMP) — it produces drafts for human review, not authoritative regulatory submissions
- Not a replacement for Sohab's Excel-based formula sheets or batch records

The trap to actively avoid: scope creep that prevents shipping. Past Sohab projects (Car-App, HTS classifier, ERP plan) followed a pattern of over-planning then dropping. MJOLNIR ships narrow first. Real usage informs the next layer.

## Architecture


```
iPhone Safari (PWA installable)
        │
        ▼
Vercel-hosted Next.js frontend (UI designed in Google Stitch)
        │
        ▼
Vercel Python serverless functions (FastAPI wrapping the engine)
        │
        ▼
┌─────────────┬────────────────┬─────────────┐
│ Supabase DB │ Lookup Engine  │ docx Output │
│ (your data) │ CosIng/PubChem │ Generator   │
│             │ /Claude API    │             │
└─────────────┴────────────────┴─────────────┘
```



**Hosting cost target:** $0/month at current scale (Vercel free + Supabase free).

**Privacy model:** Formulas (the proprietary IP) are encrypted at the application layer using AES-256 before being written to Supabase. The encryption key lives in Vercel environment variables. Even if Supabase is breached, formula compositions are unreadable. Other tables (raw materials, INCI lookups, CAS documents) are NOT encrypted because they're not proprietary information — INCI/CAS data is public regulatory data.

**Threat model addressed:** random cloud breaches, lost devices, casual snooping. NOT designed against state-level adversaries or insider threats at cloud providers.

## Repo State

- **GitHub:** `sohab117/inci-cas-builder`
- **Local clone:** `~/Documents/inci-cas-builder` (Sohab's MacBook Pro)
- **Branch model:** `main` only, push directly (solo project, no PRs)
- **Tests:** 67/67 passing as of last commit

### Folder structure


```
inci-cas-builder/
├── src/                       # core engine (CLI-runnable)
│   ├── parser.py             # INCI string → structured entries
│   ├── lookup.py             # CAS lookup chain
│   ├── document.py           # .docx generator
│   └── cli.py                # CLI entry point
├── api/                       # Vercel serverless functions
│   ├── analyze.py            # POST /api/analyze (FastAPI)
│   └── health.py             # GET /api/health
├── lib/                       # shared API helpers
│   └── schemas.py            # Pydantic models
├── data/
│   ├── cosing.csv            # 28,705 EU regulatory rows (2020-12-30 snapshot)
│   ├── cosing_stub.csv       # test fallback
│   └── lookup_cache.db       # SQLite cache (gitignored)
├── tests/                     # pytest suite (67 tests)
├── docs/
│   └── PROJECT_STATE.md      # this file
├── CLAUDE.md                 # Claude Code project rules
├── pyproject.toml
├── requirements.txt          # for Vercel
├── vercel.json
└── README.md
```


## Phases Completed

### Phase 1.1 — INCI Parser (22 tests)
`src/parser.py` exposes `parse_inci(inci_string) -> list[dict]`. Handles comma-separated lists, parenthetical common names, slash synonyms (Aqua/Water/Eau), organic asterisks, CI numbers, "may contain" markers, newlines, mixed separators. Each entry includes `position`, `inci_name`, `inci_normalized`, `raw`, `synonyms`, `notes`.

### Phase 1.2 — CAS Lookup Chain (5 tests)
`src/lookup.py` exposes `lookup_ingredient(parsed_entry)` and `lookup_panel(entries)`. Lookup priority: CosIng (local CSV) → PubChem REST API → Claude API → not_found. SQLite cache at `data/lookup_cache.db`. Slash-synonym entries retry with the rejoined form (catches cases like "Caprylic/Capric Triglyceride" the parser incorrectly split).

### Phase 1.2.5 — Real CosIng Data (+ slash cache fix + e2e test)
Replaced the 6-row stub with the official EU Commission CosIng database (28,705 rows, 2020-12-30 Wayback Machine snapshot — current EU portal is JS-rendered and no longer offers direct CSV export). Conversion script at `scripts/convert_cosing.py` for re-running if fresher data becomes available. Slash-synonym entries now cache under both canonical and rejoined keys for true cache short-circuit. Added e2e test against the Vitasana panel.

### Phase 1.2.6 — Verification Semantic Refined
Found that CosIng has entries with empty CAS fields (e.g. Sodium Lauroyl Methyl Isethionate — surfactant blends often listed without single CAS). Original behavior: `verified=True` because source is authoritative. New behavior: `verified=True` requires both authoritative source AND non-empty `cas_number`. Introduced new source value `cosing_partial` and `verification_note` field for diagnostic context.

### Phase 1.2.7 — Fallthrough on Partial Hits
`cosing_partial` results now fall through to PubChem and Claude API to attempt CAS resolution from elsewhere. If filled by PubChem, `verification_note` preserves the diagnostic ("CAS resolved via PubChem; CosIng entry exists but its CAS field is empty"). If all sources fail, returns the partial CosIng data with `verified=False`.

### Phase 1.3 — `.docx` Generation + CLI (7 tests)
`src/document.py` exposes `generate_document(parsed_entries, output_path, metadata)`. Output format matches Vitasana CAS Reference: 7-column table (#, INCI Name, Common Name/Function, CAS Number, EINECS, Trade Name/Source, Verified) with metadata header, footnote section, and confidentiality footer. CLI entry point at `src/cli.py` accepts INCI string + optional metadata flags, runs full pipeline, prints summary.

### Phase 1.3.5 — Document Formatting Polish
First-pass `.docx` had column-width and verbose-function issues. Fixed:
- Switched to landscape orientation
- Set explicit column widths (no more mid-word wrapping)
- Added `simplify_function()` — picks single most useful function category from CosIng's verbose list (e.g. "Antistatic, Cleansing, Hair Conditioning, Surfactant - Cleansing" → "Amphoteric Surfactant" based on ingredient name pattern)
- Dropped empty Trade Name / Source column (no supplier data yet)
- Stronger yellow highlight (#FFE699) for `Verified=N` rows
- Page-break protection on table rows

### Phase 3.0 — FastAPI Backend (5 API tests)
Wrapped engine in FastAPI for Vercel serverless deployment. Endpoints:
- `POST /api/analyze` — accepts INCI string + metadata, returns ingredient analysis JSON + base64-encoded `.docx`
- `GET /api/health` — uptime check
Document is returned inline as base64 to avoid Vercel function statelessness issues. CORS open for now (will lock down post-deploy).

## Phases NOT Yet Started

### Phase 3.0.5 — Vercel Deploy (next up)
Deploy the existing FastAPI backend to Vercel. Smoke-test from public URL. Lock CORS to known frontend domains.

### Phase 3.1 — Stitch UI Design
Generate UI mockups in Google Stitch. 4 screens:
1. **Input** — paste INCI / scan label / paste URL — sleek single-screen access to all three
2. **Loading** — "Looking up X ingredients" with progress
3. **Results** — table preview before download, with verified/partial/not-found counts
4. **Recent / Saved** — past panels (later: saved formulas)

Vibe: modern dark mode + editorial refined. Power user (Sohab), not client-facing. Export Stitch design as React/Tailwind code.

### Phase 3.2 — Next.js Frontend
Take Stitch's exported code, integrate with Vercel-deployed backend. Deploy frontend to Vercel. Test end-to-end on iPhone Safari.

### Phase 3.3 — Supabase Setup + Raw Material Tables
- Create Supabase project (free tier)
- Define schema: `raw_materials`, `purchase_orders`, `suppliers`
- Enable Row-Level Security (RLS) policies (only Sohab + future team member can read/write)
- Configure auth (email/password, magic link, or OAuth — TBD)
- Write Python importer script that reads cleaned PO data from Google Sheets and populates Supabase

### Phase 3.4 — Encrypted Formulas Table
- Add `formulas` and `formula_ingredients` tables to Supabase
- Application-level AES-256 encryption on `composition` column
- Encryption key stored in Vercel env vars
- Test that authorized reads decrypt correctly, breached DB exports cannot be read

### Phase 3.5 — Lookup Chain Updates
Modify `src/lookup.py` to query Supabase `raw_materials` BEFORE CosIng. When MJOLNIR finds a match in the user's own data, that becomes the authoritative source (highest priority, full trade name + supplier data populated automatically in the .docx).

### Phase 3.6 — iPhone PWA Polish
- Add PWA manifest, icons, install prompt
- Test add-to-home-screen flow
- Mobile-first layout audit
- Offline-friendly behavior (read-only when offline)

## Phase 4+ Possibilities (NOT scoped)

These are flagged as future possibilities only. They are explicitly out of scope until Sohab has used MJOLNIR for at least 30 days on real client work.

- Photo OCR for label panels (Tesseract or Claude Vision)
- URL scraping for product page INCI extraction
- Bulk ingredient import from Gmail order confirmations
- Formula management (linking raw materials, COGS calculation)
- Batch records / production tracking
- Custom domain (`mjolnir.formula117.com` instead of `*.vercel.app`)
- Supabase substance-endpoint fallback for surfactant mixtures (PubChem coverage gap discovered in Phase 1.2.7)
- **Add a Google Sheets API MCP** so future sessions can edit cells in existing sheets (current Drive MCP is read + create-new only — `spreadsheets.values.update` / `batchUpdate` are not exposed). Discovered while updating the Master List with vendor data on 2026-05-09; had to ship a v2 sheet rather than edit v1 in place.

## Key Decisions Log

### Branding & UX
- **Name:** MJOLNIR (codename, Formula 117 reference)
- **Aesthetic:** Modern dark mode + editorial refined
- **User profile:** Sohab as power user — assume technical fluency, optimize for speed, minimize hand-holding
- **Home screen:** All input methods (paste, photo, URL) accessible in one sleek view, plus recents

### Storage & privacy
- **Database:** Supabase (free tier, includes auth and RLS)
- **Formula encryption:** AES-256 application-level on `composition` column. Sohab is fine with cloud storage as long as the proprietary IP (formulas) is encrypted before transit.
- **What's NOT encrypted:** raw materials, INCI lookups, CAS documents (not proprietary)

### Hosting
- **Frontend + API:** Vercel (free tier handles two-person scale)
- **Database:** Supabase (free tier)
- **Domain:** Vercel subdomain initially. Custom domain (`mjolnir.formula117.com`) deferred until product is proven.

### Tech stack
- **Backend:** Python 3.11+, FastAPI, python-docx, pandas (CosIng parsing), requests (PubChem), anthropic (LLM fallback)
- **Frontend:** Next.js (planned), Tailwind CSS (Stitch default export)
- **Build tool:** Claude Code on local Mac, with Vercel CLI integration
- **Tests:** pytest (67 tests passing)

### Workflow
- **Solo project, push directly to `main`** (no PRs)
- **Tests must be green before push** — never push red tests
- **Dependency tracking enforced** — any new Python import must be added to `pyproject.toml` in the same commit
- **Phase discipline** — don't scaffold for future phases, build only what current phase requires

## Data Migration: PO Extraction Session

**Date:** May 9, 2026. Performed by Claude (this conversation) before any Supabase setup.

**Source:** `Purchase Orders` folder in Sohab's Google Drive (sohab@117holdings.com), plus `Chasing Summer PO's` subfolder.

**Files processed:** 23 POs (20 in main folder + 3 in subfolder, excluding 1 blank template and 1 Proforma PDF).

**Output artifacts:**
1. `MJOLNIR — PO Line Items (Raw Extract)` — 42 line items with PO Number, Date, Vendor, Item Description, Packaging Note, Qty, Unit, Unit Price, Total Price, Source File, Needs Review flag (inside `MJOLNIR — Raw Material Database` folder)
2. `MJOLNIR — Raw Materials Master List (Deduplicated)` — original v1, 22 unique trade names with best-guess INCI mapping and many "UNKNOWN — confirm" vendor entries (inside the folder; superseded by v2)
3. `MJOLNIR — Raw Material Database` (folder) — PO sheets live here (Sohab moved them in manually after initial creation left them in My Drive root)
4. `MJOLNIR — Vendors` — vendor → primary contact → other contacts → phone → address → materials supplied → notes (added 2026-05-09 from Gmail thread search; currently in My Drive root, same Drive permissions issue — move into folder manually when convenient)
5. `MJOLNIR — Raw Materials Master List v2 (Vendor-Resolved)` — v1 with confirmed Vendor column (no more UNKNOWNs) and a new Primary Contact Email column. Currently in My Drive root.
6. `MJOLNIR — Raw Materials Master List v3 (INCI-Verified)` — v2 with INCI corrected against UL Prospector / Knowde / Seppic / Croda / Gattefossé / Barnet sources, plus an `INCI Verification Source` column. **This is the current authoritative master list.** Currently in My Drive root.
7. `MJOLNIR — Prospective Vendors & Sample Partners` — vendors Sohab has talked to but not (yet) ordered from, plus sample-partner relationships, plus alternate contacts for active vendors. Built 2026-05-09 from a deeper Gmail pass. Includes Hallstar (active sample partner — Brad Pentzien, RGA-8 film former for "Wood" project), Essential Ingredients/Lubrizol (account team assigned but no PO yet), Stéarinerie Dubois (DUB 810C manufacturer; currently distributed via Seppic), Greenway Biotech (China; active sample evaluation of Sodium Azulene Sulfonate), and several cold-outreach prospects (Green Jeeva, Raphas, Luxon, Azelis, Omya). Currently in My Drive root.

**Action items resolved during 2026-05-09 Gmail pass (search of sohab@117holdings.com sent + inbox):**

1. **Vendors on the previously-UNKNOWN line items — RESOLVED.** Confirmations:
   - Kraft Chemical (multi-line POs) — primary: Vlad Malevany / Lisa Gilman / Rick (pricing). 708-345-5200, Lake Zurich IL.
   - Phoenix Chemical, Inc. — primary: Filomena De Vita (customerservice@phoenix-chem.com), 908-707-0232. Supplies **Pelemol 9512** (was UNKNOWN).
   - Seppic / Air Liquide — primary: Myra Conde (myra.conde@airliquide.com). Supplies **Montanov 202, 82, 68 MB, Sepimax Zen, DUB 810C** (was guessed "Hallstar/Seppic"; confirmed Seppic specifically).
   - Croda Inc. — primary: Tina Alley (Tina.Alley@croda.com). Supplies **SILVERFREE MBAL** (was UNKNOWN). Account setup completed 2025-07.
   - Belle Aire Creations — primary: Daniela Alvarez (DAlvarez@belleairecreations.com), 708-307-4146. Supplies **Aura Bloom Mod 1 #315643** (was UNKNOWN — confirmed Belle Aire, not Givaudan).
   - Gattefosse Corporation — primary: Ursula Puzio (UPuzio@gattefossecorp.com); IL rep Phil Leith. Supplies **Emulium Dolcea MB**.
   - Barnet Products — primary: Stephanie Valerio / Tobi Scalf. Supplies **Barsil 2001**. (Chris Dotter is no longer at Barnet as of 2025-03.)
   - Carrubba Inc. — primary: Grady Lawlor (gradyl@carrubba.com), 500 Pepper Street, Milford CT. Supplies **Coconut Water Fragrance N71537**.
   - Lotioncrafter — used as occasional small-batch fallback for Sepimax Zen.

**Action items resolved during 2026-05-09 INCI verification pass (UL Prospector / Knowde / Seppic / Croda / Gattefossé / Barnet direct):**

2. **INCI breakdowns — RESOLVED with significant corrections.** v3 sheet captures all of the below:
   - Montanov 202 — was wrongly listed as Cetearyl Alcohol/Cetearyl Glucoside; **actual INCI: Arachidyl Alcohol (and) Behenyl Alcohol (and) Arachidyl Glucoside**
   - DUB 810C — was wrongly listed as Caprylic/Capric Triglyceride (that's MCT Oil); **actual INCI: Coco-Caprylate/Caprate**; manufacturer is Stéarinerie Dubois (Seppic distributes)
   - Pelemol 9512 — was wrongly listed as PPG-3 Benzyl Ether Myristate; **actual INCI: Isoamyl Laurate** (100% vegetable, silicone alternative)
   - Emulium Dolcea MB — was 3-component guess; **actual is 7-component: Cetearyl Alcohol (and) Glyceryl Stearate (and) Jojoba Esters (and) Helianthus Annuus (Sunflower) Seed Wax (and) Sodium Stearoyl Glutamate (and) Water (Aqua) (and) Polyglycerin-3**
   - Barsil 2001 — RESOLVED from UNKNOWN; **actual INCI: Dimethicone** (mixed MW polymer system)
   - SILVERFREE MBAL — RESOLVED from UNKNOWN; **active is Palmitoyl Dipeptide-52** (Pal-Pro-Pro lipopeptide at 6000 ppm; full product INCI may include glycerin/water carrier — still worth confirming via Croda SDS)
   - Kraftiphen Plus — was wrongly guessed as Phenoxyethanol/Caprylyl Glycol/Ethylhexylglycerin; **likely Phenoxyethanol (and) Caprylyl Glycol (and) Sorbic Acid** (Kraft house-brand of Optiphen Plus); confirm via tech sheet
   - Kraftguard Ultra — RESOLVED from UNKNOWN; **likely Gluconolactone (and) Sodium Benzoate** (Kraft house-brand of Geogard Ultra); confirm via tech sheet

3. **Still outstanding (small):**
   - Confirm Kraftiphen Plus / Kraftguard Ultra INCI exactly matches Optiphen Plus / Geogard Ultra (high confidence but unconfirmed via Kraft tech sheet)
   - Confirm full SILVERFREE MBAL product INCI including carrier (active confirmed; carrier system inferred)

4. **Pricing intel preserved** — Pelemol 9512 ordered 7 times at consistent $18.87/lb (stable). Other materials show no significant price drift across orders.

**Catalog / brochure references found in inbox (worth filing in Drive):**
- **Barnet Products** — Chris Dotter sent literature on all ingredients on 2024-07-31 (PDF attachments in that thread)
- **Hallstar** — Sytenol® A / Bakuchiol marketing materials (multiple emails from workwonders@hallstar.com and beautynews@hallstar.com); RGA series TDS shared by Brad Pentzien
- **Belle Aire Creations** — Quote PDFs (PB263619, PB262955), Mood Boards for XP SKIN, regulatory docs for #315643 / #278370 / #318964 fragrances
- **Carrubba** — Regulatory documents for Coconut Water N71537 (paraben/phthalate/formaldehyde-free package)
- **Greenway Biotech** — Sample TDS for Sodium Azulene Sulfonate / Guaiazulene Sulfonate
- **Croda** — Beauty website portal access (online catalog at croda.com)
- **Phoenix Chemical** — Pelemol catalog accessible via phoenix-chem.com (no PDF in inbox)
- **Stéarinerie Dubois** — DUB series TDS available on Knowde / SpecialChem / stearinerie-dubois.com
- **Industry newsletters** (informational, not actionable for sourcing): SpecialChem, Cosmetics & Toiletries, Personal Care Magazine

**Suggested Drive folder structure for catalogs (manual setup):**
```
MJOLNIR — Raw Material Database/
├── 00 — Master Lists/
│   ├── PO Line Items (Raw Extract)
│   └── Raw Materials Master List v3 (INCI-Verified)  ← current
├── 01 — Vendor Directory/
│   ├── Vendors (Active)
│   └── Prospective Vendors & Sample Partners
├── 02 — Catalogs & Brochures/
│   ├── Kraft Chemical/
│   ├── Barnet Products/         (← Chris Dotter literature 2024-07-31)
│   ├── Hallstar/                 (← Sytenol A, RGA series)
│   ├── Seppic/
│   ├── Phoenix Chemical/
│   ├── Stearinerie Dubois/
│   ├── Croda — Sederma/
│   ├── Gattefosse/
│   ├── Belle Aire Creations/    (← fragrance briefs, mood boards, reg docs)
│   ├── Carrubba/                 (← N71537 regulatory package)
│   ├── Essential Ingredients/
│   └── Greenway Biotech/         (← Sodium Azulene Sulfonate TDS)
└── 99 — Archive (superseded versions)/
    ├── Master List v1
    └── Master List v2 (vendor-resolved, INCI not yet verified)
```

## Critical Reminders for Future Sessions

1. **Read CLAUDE.md before any work.** It has the workflow rules.
2. **Read this file (PROJECT_STATE.md) for full context.** Especially when picking up after a long break.
3. **Don't add scope without explicit approval.** If a request feels like it's expanding beyond the current phase, stop and ask.
4. **The 67 tests are the load-bearing wall.** Never push red tests. If a phase breaks tests, fix or stop and report.
5. **Formulas are the crown jewels.** Never log them in plaintext. Never commit them to git. Never include them in error messages or debug output. They live encrypted in Supabase only.
6. **Sohab's time is constrained.** He's running 117 Holdings + Asset Skincare day job + Viscosity Labs + a wedding in Turkey in August. Build sustainable, not heroic. The tool that ships and gets used beats the tool that's perfect and never finishes.

## Notion Page Reference

Primary high-level project view also lives at: 🔨 MJOLNIR — Project Hub (under 🏭 117 Holdings LLC in Notion). The Notion page is for narrative reference and stakeholder summaries. THIS file (PROJECT_STATE.md) is the authoritative working document.
