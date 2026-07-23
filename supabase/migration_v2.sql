-- TradePilot v2 Migration Script
-- Creates contractors_v2 table for single-source-of-truth progress & Lob exports

create table if not exists contractors_v2 (
  license_number          text primary key,
  license_type            text,
  license_subtype         text,
  license_expiration_date text,
  county                  text,
  business_county         text,

  owner_name              text,
  business_name           text,

  pipeline_status         text default 'pending',
  processed_at            timestamptz,

  website_yn              text,
  website_url             text,
  fb_yn                   text,
  fb_url                  text,

  address_line1           text,
  address_city            text,
  address_state           text,
  address_zip             text,
  address_source          text,

  cohort                  text,

  lob_upload_id           text,
  lob_uploaded_at         timestamptz,

  created_at              timestamptz default now(),
  updated_at              timestamptz default now()
);

-- Enable RLS and simple policy if needed
alter table contractors_v2 enable row level security;
create policy "Allow service_role full access" on contractors_v2 for all using (true);
