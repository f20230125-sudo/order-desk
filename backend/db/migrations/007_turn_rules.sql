-- Who has to act on a blocking problem.
-- Sales: anything that needs the customer or a commercial decision (their PO's arithmetic, a price change
-- that eats the margin, a substitute part the customer must approve).
-- Ops: everything about goods and paperwork with the distributor (including a confirmation that quotes the
-- wrong PO number, which 004 had sent to sales).

create or replace function blocking_issue_owner(p_order bigint) returns text language sql stable as $$
    select case
        when bool_or(code in ('VAT_MATH', 'TOTAL_MATH', 'PRICE_DIFF', 'SUBSTITUTION')) then 'sales'
        when count(*) > 0 then 'ops'
    end
    from discrepancy
    where customer_order_id = p_order and status = 'open' and severity = 'block'
$$;

create or replace view order_chain as
with facts as (
    select
        co.id, co.po_number, co.customer_id, co.po_date, co.received_at, co.required_by, co.total,
        co.currency, co.ready_to_invoice_at,
        p.name as customer_name, p.sector,
        po.id as po_id, po.our_po_number, po.sent_at, d.name as distributor_name,
        (select max(vc.confirmed_at) from vendor_confirmation vc where vc.po_id = po.id) as confirmed_at,
        (select min(vc.eta) from vendor_confirmation vc where vc.po_id = po.id) as eta,
        q.ordered_qty, q.received_qty, q.delivered_qty,
        (select max(s.received_at) from shipment s where s.customer_order_id = co.id
           and s.direction = 'inbound') as last_received_at,
        (select max(s.received_at) from shipment s where s.customer_order_id = co.id
           and s.direction = 'outbound') as last_delivered_at,
        (select count(*) from discrepancy x where x.customer_order_id = co.id and x.status = 'open') as open_issues,
        (select count(*) from discrepancy x where x.customer_order_id = co.id and x.status = 'open'
           and x.severity = 'block') as open_blocking,
        blocking_issue_owner(co.id) as blocking_owner
    from customer_order co
    join party p on p.id = co.customer_id
    left join purchase_order po on po.customer_order_id = co.id
    left join party d on d.id = po.distributor_id
    join order_quantities q on q.customer_order_id = co.id
),
staged as (
    select f.*,
        case
            when ready_to_invoice_at is not null then 'ready_to_invoice'
            when ordered_qty > 0 and delivered_qty >= ordered_qty then 'delivered'
            when ordered_qty > 0 and received_qty >= ordered_qty then 'received'
            when confirmed_at is not null then 'confirmed'
            when po_id is not null then 'po_sent'
            else 'po_received'
        end as stage,
        case
            when ready_to_invoice_at is not null then ready_to_invoice_at
            when ordered_qty > 0 and delivered_qty >= ordered_qty then last_delivered_at
            when ordered_qty > 0 and received_qty >= ordered_qty then last_received_at
            when confirmed_at is not null then confirmed_at
            when po_id is not null then sent_at
            else received_at
        end as stage_since
    from facts f
)
select s.id, s.po_number, s.customer_id, s.po_date, s.received_at, s.required_by, s.total, s.currency,
    s.ready_to_invoice_at, s.customer_name, s.sector, s.po_id, s.our_po_number, s.sent_at, s.distributor_name,
    s.confirmed_at, s.eta, s.ordered_qty, s.received_qty, s.delivered_qty, s.last_received_at,
    s.last_delivered_at, s.open_issues, s.open_blocking,
    (s.blocking_owner = 'sales') as sales_issue,
    s.stage, s.stage_since,
    array_position(array['po_received', 'po_sent', 'confirmed', 'received', 'delivered', 'ready_to_invoice'],
                   s.stage) as stage_no,
    case
        when s.blocking_owner is not null then s.blocking_owner
        when s.stage = 'po_received' then 'sales'
        when s.stage in ('po_sent', 'confirmed', 'received') then 'ops'
        when s.stage = 'delivered' then 'finance'
        else null
    end as whose_turn,
    greatest(0, extract(day from now() - s.stage_since))::int as days_in_stage,
    (s.eta is not null and s.required_by is not null and s.eta > s.required_by) as eta_after_required
from staged s;
