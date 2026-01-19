-- Documents we received, uploads waiting for a person to confirm them, check results, and rate limiting.

create table document (
    id                 bigint generated always as identity primary key,
    kind               text not null check (kind in ('customer_po', 'vendor_confirmation', 'delivery_note',
                                                     'shipment_email')),
    filename           text not null,
    mime               text not null check (mime in ('application/pdf', 'message/rfc822')),
    sha256             text not null unique check (sha256 ~ '^[0-9a-f]{64}$'),  -- same file twice is refused
    size_bytes         int not null check (size_bytes between 1 and 2097152),
    content            bytea not null,
    extracted          jsonb not null,  -- what the extractor read, with page boxes, before any human edit
    extractor_version  text not null,
    customer_order_id  bigint references customer_order (id) on delete cascade,
    uploaded_by_role   text not null check (uploaded_by_role in ('sales', 'ops', 'finance', 'system')),
    uploaded_at        timestamptz not null default now()
);

-- Vercel instances share no disk, so an upload waits here between "read it" and "confirm it".
create table pending_upload (
    id          uuid primary key default gen_random_uuid(),
    kind        text not null,
    filename    text not null,
    mime        text not null,
    sha256      text not null,
    size_bytes  int not null check (size_bytes between 1 and 2097152),
    content     bytea not null,
    extracted   jsonb not null,
    created_at  timestamptz not null default now(),
    expires_at  timestamptz not null default now() + interval '2 hours'
);

create table check_run (
    id                 bigint generated always as identity primary key,
    customer_order_id  bigint not null references customer_order (id) on delete cascade,
    engine_version     text not null,
    ran_at             timestamptz not null default now()
);

create table discrepancy (
    id                 bigint generated always as identity primary key,
    check_run_id       bigint not null references check_run (id) on delete cascade,
    customer_order_id  bigint not null references customer_order (id) on delete cascade,
    code               text not null check (code in (
                           'QTY_SHORT', 'QTY_OVER', 'PART_MISMATCH', 'SUBSTITUTION', 'PRICE_DIFF',
                           'MISSING_LINE', 'EXTRA_LINE', 'SERIAL_COUNT', 'DUPLICATE_SERIAL',
                           'VAT_MATH', 'TOTAL_MATH', 'PO_REF', 'ETA_LATE', 'PARTIAL_SHIPMENT')),
    severity           text not null check (severity in ('block', 'warn', 'info')),
    stage              text not null,     -- which link in the chain the problem sits on
    part_number        text,
    expected           text,
    found              text,
    explanation        text not null,
    -- The same problem found again by a later run keeps its identity (and its resolution).
    fingerprint        text not null,
    status             text not null default 'open' check (status in ('open', 'accepted', 'fixed')),
    resolution_note    text,
    resolved_by_role   text check (resolved_by_role in ('sales', 'ops', 'finance')),
    resolved_at        timestamptz,
    unique (customer_order_id, fingerprint),
    check ((status = 'open') = (resolved_at is null)),
    check (status = 'open' or (resolution_note is not null and length(trim(resolution_note)) >= 3
                                and resolved_by_role is not null))
);

-- Serverless instances share no memory, so request counting lives in the database.
create table rate_limit (
    client_key    text not null,
    window_start  timestamptz not null,
    hits          int not null default 1,
    primary key (client_key, window_start)
);
