-- Core operations schema: who we trade with, what we sell, and the order chain
-- customer PO (incoming) -> our PO to the distributor (outgoing) -> confirmation -> shipments.

create table party (
    id          bigint generated always as identity primary key,
    kind        text not null check (kind in ('customer', 'distributor', 'carrier')),
    name        text not null,
    short_code  text not null unique check (short_code ~ '^[A-Z0-9]{2,8}$'),
    -- UAE tax registration number: 15 digits starting 100. Carriers usually have none on our documents.
    trn         text check (trn ~ '^100[0-9]{12}$'),
    sector      text check (sector in ('government', 'bank', 'education', 'healthcare', 'enterprise')),
    address     text,
    emirate     text check (emirate in ('Abu Dhabi', 'Dubai', 'Sharjah', 'Ajman', 'Umm Al Quwain',
                                        'Ras Al Khaimah', 'Fujairah')),
    created_at  timestamptz not null default now(),
    unique (kind, name)
);

create table product (
    id           bigint generated always as identity primary key,
    part_number  text not null unique check (part_number = upper(part_number) and length(part_number) between 4 and 40),
    brand        text not null,
    description  text not null,
    category     text not null check (category in ('server', 'storage', 'backup', 'security', 'endpoint',
                                                     'network', 'software', 'service')),
    -- Hardware is tracked by serial number; licences and services are not.
    serialised   boolean not null,
    list_price   numeric(12, 2) not null check (list_price >= 0)
);

-- Incoming: a purchase order a customer sends us.
create table customer_order (
    id                bigint generated always as identity primary key,
    po_number         text not null,
    customer_id       bigint not null references party (id),
    po_date           date not null,
    received_at       timestamptz not null default now(),
    required_by       date,
    currency          text not null default 'AED' check (currency ~ '^[A-Z]{3}$'),
    vat_rate          numeric(5, 4) not null default 0.05 check (vat_rate between 0 and 1),
    subtotal          numeric(14, 2) check (subtotal >= 0),
    vat_amount        numeric(14, 2) check (vat_amount >= 0),
    total             numeric(14, 2) check (total >= 0),
    deliver_to        text,
    contact_name      text,
    -- Set when the order is ready for finance; project 2 (e-invoicing) picks it up from here.
    ready_to_invoice_at timestamptz,
    unique (customer_id, po_number),
    check (required_by is null or required_by >= po_date)
);

create table customer_order_line (
    id           bigint generated always as identity primary key,
    order_id     bigint not null references customer_order (id) on delete cascade,
    line_no      int not null check (line_no > 0),
    part_number  text not null,
    description  text not null,
    qty          int not null check (qty > 0),
    unit_price   numeric(12, 2) not null check (unit_price >= 0),
    unique (order_id, line_no)
);

-- Outgoing: the purchase order we place with a distributor to fulfil a customer order.
-- One distributor PO per customer order in this version (a split order is two customer orders).
create table purchase_order (
    id                 bigint generated always as identity primary key,
    our_po_number      text not null unique check (our_po_number ~ '^PO-[0-9]{4}-[0-9]{4}$'),
    customer_order_id  bigint not null unique references customer_order (id) on delete cascade,
    distributor_id     bigint not null references party (id),
    sent_at            timestamptz not null default now(),
    currency           text not null default 'AED' check (currency ~ '^[A-Z]{3}$')
);

create table purchase_order_line (
    id           bigint generated always as identity primary key,
    po_id        bigint not null references purchase_order (id) on delete cascade,
    line_no      int not null check (line_no > 0),
    part_number  text not null,
    description  text not null,
    qty          int not null check (qty > 0),
    unit_cost    numeric(12, 2) not null check (unit_cost >= 0),
    unique (po_id, line_no)
);

-- The distributor's answer to our PO: what they will actually supply, at what price, and when.
create table vendor_confirmation (
    id               bigint generated always as identity primary key,
    po_id            bigint not null references purchase_order (id) on delete cascade,
    confirmation_no  text not null,
    confirmed_at     timestamptz not null default now(),
    referenced_po    text not null,  -- the PO number printed on their document; checked against ours
    eta              date,
    unique (po_id, confirmation_no)
);

create table vendor_confirmation_line (
    id                bigint generated always as identity primary key,
    confirmation_id   bigint not null references vendor_confirmation (id) on delete cascade,
    line_no           int not null check (line_no > 0),
    part_number       text not null,
    description       text not null,
    qty               int not null check (qty >= 0),
    unit_cost         numeric(12, 2) not null check (unit_cost >= 0),
    substitutes_part  text,  -- set when the distributor offers a different part for one we ordered
    unique (confirmation_id, line_no)
);

-- Goods moving: inbound from the distributor to us, outbound from us to the customer.
create table shipment (
    id                 bigint generated always as identity primary key,
    direction          text not null check (direction in ('inbound', 'outbound')),
    customer_order_id  bigint not null references customer_order (id) on delete cascade,
    po_id              bigint references purchase_order (id) on delete cascade,
    carrier_id         bigint references party (id),
    tracking_number    text,
    delivery_note_no   text,
    shipped_at         timestamptz,
    received_at        timestamptz,  -- inbound: booked in at our goods-in; outbound: signed for by the customer
    check (direction = 'outbound' or po_id is not null),
    check (received_at is null or shipped_at is null or received_at >= shipped_at)
);

create table shipment_line (
    id           bigint generated always as identity primary key,
    shipment_id  bigint not null references shipment (id) on delete cascade,
    part_number  text not null,
    qty          int not null check (qty > 0)
);

create table serial (
    id                bigint generated always as identity primary key,
    shipment_line_id  bigint not null references shipment_line (id) on delete cascade,
    serial_no         text not null check (serial_no = upper(serial_no) and length(serial_no) between 5 and 30),
    -- One physical unit goes inbound once and outbound once.
    direction         text not null check (direction in ('inbound', 'outbound')),
    unique (serial_no, direction)
);
