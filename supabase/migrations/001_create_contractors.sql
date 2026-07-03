-- TradePilot working table — replaces the single working CSV file.
-- Column names use snake_case; CSV columns with / or % map via scripts/seed_supabase_from_csv.py.

CREATE TABLE IF NOT EXISTS contractors (
    license_number TEXT PRIMARY KEY,

    -- Source columns (TDLR export — read-only for phases 1+)
    license_subtype TEXT,
    county TEXT,
    owner_name_raw TEXT,
    business_name_raw TEXT,

    -- Name variation columns (pre-generated — read-only for phases 1+)
    owner_var_1 TEXT,
    owner_var_2 TEXT,
    biz_var_1 TEXT,
    biz_var_2 TEXT,
    biz_var_3 TEXT,
    biz_var_4 TEXT,
    combo_var_1 TEXT,
    combo_var_2 TEXT,
    combo_var_3 TEXT,
    combo_var_4 TEXT,

    -- Phase 0
    run_id TEXT,
    batch1_excluded BOOLEAN,
    phase0_timestamp TIMESTAMPTZ,

    -- Phase 1 — website detection
    website_yn TEXT CHECK (website_yn IS NULL OR website_yn IN ('Y', 'N', 'UNCERTAIN')),
    website_url TEXT,
    website_confidence_pct SMALLINT CHECK (website_confidence_pct IS NULL OR website_confidence_pct BETWEEN 0 AND 100),
    website_search_notes TEXT,
    phase1_timestamp TIMESTAMPTZ,

    -- Phase 2 — Facebook detection
    fb_yn TEXT CHECK (fb_yn IS NULL OR fb_yn IN ('Y', 'N', 'UNCERTAIN')),
    fb_url TEXT,
    fb_page_name TEXT,
    fb_last_post_date TEXT,
    fb_confidence_pct SMALLINT CHECK (fb_confidence_pct IS NULL OR fb_confidence_pct BETWEEN 0 AND 100),
    fb_search_notes TEXT,
    phase2_timestamp TIMESTAMPTZ,

    -- Phase 3 — other presence
    gbp_found TEXT CHECK (gbp_found IS NULL OR gbp_found IN ('Y', 'N')),
    gbp_claimed TEXT CHECK (gbp_claimed IS NULL OR gbp_claimed IN ('Y', 'N', 'UNKNOWN')),
    gbp_review_count INTEGER,
    yelp_found TEXT CHECK (yelp_found IS NULL OR yelp_found IN ('Y', 'N')),
    angi_found TEXT CHECK (angi_found IS NULL OR angi_found IN ('Y', 'N')),
    other_presence_types TEXT,
    other_presence_notes TEXT,
    other_presence_yn TEXT,
    other_confidence_pct SMALLINT,
    phase3_timestamp TIMESTAMPTZ,

    -- Phase 4 — address resolution
    address_found TEXT CHECK (address_found IS NULL OR address_found IN ('Y', 'N', 'UNCERTAIN')),
    address_raw TEXT,
    address_source TEXT,
    address_source_url TEXT,
    address_confidence_pct SMALLINT CHECK (address_confidence_pct IS NULL OR address_confidence_pct BETWEEN 0 AND 100),
    address_type_guess TEXT,
    address_is_pobox BOOLEAN,
    address_attempt_log TEXT,
    address_source_count INTEGER,
    address_conflict_detected BOOLEAN,
    phase4_timestamp TIMESTAMPTZ,

    -- Phase 5 — Lob verification
    lob_verified BOOLEAN,
    lob_deliverability TEXT,
    lob_standardized_address TEXT,
    lob_address_type TEXT,
    lob_vacancy TEXT,
    lob_verification_timestamp TIMESTAMPTZ,

    -- Phase 7 — batch classification
    cohort TEXT,
    mail_wave TEXT,
    batch_assignment TEXT,
    lob_ready BOOLEAN,
    exclusion_reason TEXT,
    unresolved_reason TEXT,
    confidence_score SMALLINT,
    confidence_tier TEXT CHECK (confidence_tier IS NULL OR confidence_tier IN ('A', 'B', 'C')),
    phase7_timestamp TIMESTAMPTZ,

    -- Legacy combined notes from seed CSV
    search_notes TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_contractors_county ON contractors (county);
CREATE INDEX IF NOT EXISTS idx_contractors_run_id ON contractors (run_id);
CREATE INDEX IF NOT EXISTS idx_contractors_batch_assignment ON contractors (batch_assignment);
CREATE INDEX IF NOT EXISTS idx_contractors_cohort ON contractors (cohort);

CREATE OR REPLACE FUNCTION set_contractors_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS contractors_updated_at ON contractors;
CREATE TRIGGER contractors_updated_at
    BEFORE UPDATE ON contractors
    FOR EACH ROW
    EXECUTE FUNCTION set_contractors_updated_at();

COMMENT ON TABLE contractors IS 'Pipeline working records — replaces data/output working CSV';
