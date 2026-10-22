-- Complete each customer part separately; only an accepted substitute counts for the original.
create function order_fulfilled(p_order bigint, p_direction text) returns boolean language sql stable as $$
    with required as (
        select part_number, sum(qty) as qty from customer_order_line
        where order_id = p_order group by part_number
    ),
    latest as (
        select vc.id from vendor_confirmation vc join purchase_order po on po.id = vc.po_id
        where po.customer_order_id = p_order order by vc.confirmed_at desc, vc.id desc limit 1
    ),
    substitutes as (
        select distinct x.found as part_number, x.expected as customer_part
        from discrepancy x join vendor_confirmation_line vl on vl.part_number = x.found
        join latest on latest.id = vl.confirmation_id
        where x.customer_order_id = p_order and x.code = 'SUBSTITUTION'
          and x.stage = 'confirmed' and x.status = 'accepted'
          and x.check_run_id = (select max(id) from check_run where customer_order_id = p_order)
          and (vl.substitutes_part = x.expected or vl.substitutes_part is null)
    ),
    arrived as (
        select coalesce(sub.customer_part, sl.part_number) as part_number, sum(sl.qty) as qty
        from shipment s join shipment_line sl on sl.shipment_id = s.id
        left join substitutes sub on sub.part_number = sl.part_number
        where s.customer_order_id = p_order and s.direction = p_direction and s.received_at is not null
        group by coalesce(sub.customer_part, sl.part_number)
    )
    select exists (select 1 from required)
       and not exists (select 1 from required r left join arrived a using (part_number)
                       where r.qty > coalesce(a.qty, 0))
$$;

-- Usage survives pending-upload expiry and is reserved atomically with each accepted upload.
create table upload_usage (
    day         date primary key,
    size_bytes  bigint not null check (size_bytes >= 0)
);

insert into upload_usage (day, size_bytes)
select day, sum(size_bytes) from (
    select (created_at at time zone 'UTC')::date as day, size_bytes from pending_upload
    union all
    select (uploaded_at at time zone 'UTC')::date as day, size_bytes from document
    where uploaded_by_role <> 'system'
) uploads group by day;

create or replace view order_chain as
with facts as (
    select
        co.id, co.po_number, co.customer_id, co.po_date, co.received_at, co.required_by, co.total,
        co.currency, co.ready_to_invoice_at,
        p.name as customer_name, p.sector,
        po.id as po_id, po.our_po_number, po.sent_at, d.name as distributor_name,
        (select max(vc.confirmed_at) from vendor_confirmation vc where vc.po_id = po.id) as confirmed_at,
        (select vc.eta from vendor_confirmation vc where vc.po_id = po.id
           order by vc.confirmed_at desc, vc.id desc limit 1) as eta,
        q.ordered_qty, q.received_qty, q.delivered_qty,
        order_fulfilled(co.id, 'inbound') as received_complete,
        order_fulfilled(co.id, 'outbound') as delivered_complete,
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
            when delivered_complete then 'delivered'
            when received_complete then 'received'
            when confirmed_at is not null then 'confirmed'
            when po_id is not null then 'po_sent'
            else 'po_received'
        end as stage,
        case
            when ready_to_invoice_at is not null then ready_to_invoice_at
            when delivered_complete then last_delivered_at
            when received_complete then last_received_at
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
