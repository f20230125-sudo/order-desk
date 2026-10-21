-- The audit log, the triggers that write it, and rules that span tables.

create table event (
    id           bigint generated always as identity primary key,
    at           timestamptz not null,
    actor_role   text not null,
    table_name   text not null,
    row_id       bigint not null,
    customer_order_id bigint,  -- every event is filed under the order it belongs to, for the order timeline
    action       text not null check (action in ('insert', 'update', 'delete')),
    before       jsonb,
    after        jsonb
);

-- The role comes from set_config('app.role', ..., true) inside the writing transaction (see conn.write_tx).
-- app.ts lets the seed backdate history; normal requests leave it unset and get now().
create function audit_row() returns trigger language plpgsql as $$
declare
    v_at    timestamptz := coalesce(nullif(current_setting('app.ts', true), '')::timestamptz, now());
    v_role  text := coalesce(nullif(current_setting('app.role', true), ''), 'system');
    v_row   jsonb := to_jsonb(coalesce(new, old));
    v_order bigint;
begin
    v_order := case tg_table_name
        when 'customer_order' then (v_row ->> 'id')::bigint
        when 'purchase_order' then (v_row ->> 'customer_order_id')::bigint
        when 'shipment' then (v_row ->> 'customer_order_id')::bigint
        when 'discrepancy' then (v_row ->> 'customer_order_id')::bigint
        when 'document' then (v_row ->> 'customer_order_id')::bigint
        when 'vendor_confirmation' then
            (select customer_order_id from purchase_order where id = (v_row ->> 'po_id')::bigint)
    end;
    insert into event (at, actor_role, table_name, row_id, customer_order_id, action, before, after)
    values (v_at, v_role, tg_table_name, (v_row ->> 'id')::bigint, v_order, lower(tg_op),
            case when tg_op in ('UPDATE', 'DELETE') then to_jsonb(old) - 'content' end,
            case when tg_op in ('INSERT', 'UPDATE') then to_jsonb(new) - 'content' end);
    return null;
end $$;

create trigger audit_customer_order after insert or update or delete on customer_order
    for each row execute function audit_row();
create trigger audit_purchase_order after insert or update or delete on purchase_order
    for each row execute function audit_row();
create trigger audit_vendor_confirmation after insert or update or delete on vendor_confirmation
    for each row execute function audit_row();
create trigger audit_shipment after insert or update or delete on shipment
    for each row execute function audit_row();
create trigger audit_discrepancy after insert or update or delete on discrepancy
    for each row execute function audit_row();
create trigger audit_document after insert or delete on document
    for each row execute function audit_row();

-- A serial's direction must match the shipment it was booked on.
create function serial_direction_matches() returns trigger language plpgsql as $$
begin
    if new.direction <> (select s.direction from shipment_line sl join shipment s on s.id = sl.shipment_id
                         where sl.id = new.shipment_line_id) then
        raise exception 'serial % is booked as % but its shipment is %', new.serial_no, new.direction,
            (select s.direction from shipment_line sl join shipment s on s.id = sl.shipment_id
             where sl.id = new.shipment_line_id)
            using errcode = 'check_violation';
    end if;
    return new;
end $$;

create trigger serial_direction before insert or update on serial
    for each row execute function serial_direction_matches();

-- A customer order must come from a customer, a PO we send must go to a distributor, and a shipment's
-- carrier must be a carrier. Check constraints may not look at other tables, so these are triggers.
create function require_party_kind() returns trigger language plpgsql as $$
declare
    v_col  text := tg_argv[0];
    v_kind text := tg_argv[1];
    v_id   bigint := (to_jsonb(new) ->> v_col)::bigint;
begin
    if v_id is not null and not exists (select 1 from party where id = v_id and kind = v_kind) then
        raise exception '%.% must point to a % (got party %)', tg_table_name, v_col, v_kind, v_id
            using errcode = 'check_violation';
    end if;
    return new;
end $$;

create trigger customer_order_party before insert or update on customer_order
    for each row execute function require_party_kind('customer_id', 'customer');
create trigger purchase_order_party before insert or update on purchase_order
    for each row execute function require_party_kind('distributor_id', 'distributor');
create trigger shipment_carrier before insert or update on shipment
    for each row execute function require_party_kind('carrier_id', 'carrier');
