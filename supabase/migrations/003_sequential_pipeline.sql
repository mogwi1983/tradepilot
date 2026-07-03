-- Sequential pipeline: preserve CSV row order for batch processing.

ALTER TABLE contractors ADD COLUMN IF NOT EXISTS seed_row_order INTEGER;

CREATE INDEX IF NOT EXISTS idx_contractors_seed_row_order ON contractors (seed_row_order);

COMMENT ON COLUMN contractors.seed_row_order IS 'Original CSV row index (0-based) for top-to-bottom batch processing';
