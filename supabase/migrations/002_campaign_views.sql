-- Campaign progress views for the 600-mailer goal (3 cohorts × 200 wave-1 addresses).

CREATE OR REPLACE VIEW campaign_cohort_summary AS
SELECT
    cohort,
    COUNT(*)::int AS assigned,
    COUNT(*) FILTER (WHERE lob_ready IS TRUE)::int AS mail_ready,
    COUNT(*) FILTER (WHERE lob_ready IS TRUE AND mail_wave = 'wave_1')::int AS wave_1_addresses,
    COUNT(*) FILTER (WHERE lob_ready IS TRUE AND mail_wave = 'wave_2')::int AS wave_2_overflow,
    COUNT(*) FILTER (WHERE cohort IN ('cohort_1', 'cohort_2', 'cohort_3') AND (lob_ready IS NOT TRUE))::int AS pending_address
FROM contractors
WHERE cohort IN ('cohort_1', 'cohort_2', 'cohort_3')
GROUP BY cohort
ORDER BY cohort;

CREATE OR REPLACE VIEW campaign_universe_summary AS
SELECT
    COUNT(*)::int AS total_in_db,
    COUNT(*) FILTER (WHERE phase7_timestamp IS NOT NULL)::int AS classified,
    COUNT(*) FILTER (WHERE phase7_timestamp IS NULL AND COALESCE(batch1_excluded, FALSE) = FALSE)::int AS remaining_to_process,
    COUNT(*) FILTER (WHERE lob_ready IS TRUE AND mail_wave = 'wave_1')::int AS wave_1_addresses_total,
    COUNT(*) FILTER (WHERE lob_ready IS TRUE)::int AS mail_ready_total
FROM contractors
WHERE COALESCE(batch1_excluded, FALSE) = FALSE;

COMMENT ON VIEW campaign_cohort_summary IS 'Per-cohort progress toward 200 wave-1 mailing addresses';
COMMENT ON VIEW campaign_universe_summary IS 'Full-universe pipeline progress for dashboard';

-- Allow REST API access (Supabase exposes views in public schema by default when RLS permits service role).
GRANT SELECT ON campaign_cohort_summary TO anon, authenticated, service_role;
GRANT SELECT ON campaign_universe_summary TO anon, authenticated, service_role;
