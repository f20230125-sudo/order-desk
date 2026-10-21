-- The board: where every order stands in the chain, whose turn it is, and how long it has waited.
--
-- Stages, in order:
--   1 po_received      customer PO booked, our PO not sent yet           -> sales (check and pass to ops)
--   2 po_sent          our PO sent, no distributor confirmation yet      -> ops (chase the distributor)
--   3 confirmed        confirmed, goods not fully received at goods-in  -> ops (track inbound)
--   4 received         all goods in, not fully delivered to the customer -> ops (deliver)
--   5 delivered        delivered and signed for, not passed to finance   -> finance (invoice)
--   6 ready_to_invoice handed to finance
-- An open blocking discrepancy puts the order back with whoever must resolve it (sales for anything about
-- the customer's PO or price, ops for everything about goods).

create view order_quantities as
select
    co.id as customer_order_id,
    (select coalesce(sum(qty), 0) from customer_order_line where order_id = co.id) as ordered_qty,
    (select coalesce(sum(sl.qty), 0) from shipment s join shipment_line sl on sl.shipment_id = s.id
      where s.customer_order_id = co.id and s.direction = 'inbound' and s.received_at is not null) as received_qty,
    (select coalesce(sum(sl.qty), 0) from shipment s join shipment_line sl on sl.shipment_id = s.id
      where s.customer_order_id = co.id and s.direction = 'outbound' and s.received_at is not null) as delivered_qty
from customer_order co;

create view order_chain as
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
        (select bool_or(x.code in ('PRICE_DIFF', 'PO_REF', 'VAT_MATH', 'TOTAL_MATH')) from discrepancy x
          where x.customer_order_id = co.id and x.status = 'open' and x.severity = 'block') as sales_issue
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
select s.*,
    array_position(array['po_received', 'po_sent', 'confirmed', 'received', 'delivered', 'ready_to_invoice'],
                   s.stage) as stage_no,
    case
        when s.open_blocking > 0 and s.sales_issue then 'sales'
        when s.open_blocking > 0 then 'ops'
        when s.stage = 'po_received' then 'sales'
        when s.stage in ('po_sent', 'confirmed', 'received') then 'ops'
        when s.stage = 'delivered' then 'finance'
        else null
    end as whose_turn,
    greatest(0, extract(day from now() - s.stage_since))::int as days_in_stage,
    (s.eta is not null and s.required_by is not null and s.eta > s.required_by) as eta_after_required
from staged s;
