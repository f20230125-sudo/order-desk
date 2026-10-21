-- Foreign keys are not indexed automatically in Postgres; these are the joins and lookups the app makes.

create index customer_order_line_order on customer_order_line (order_id);
create index purchase_order_customer_order on purchase_order (customer_order_id);
create index purchase_order_line_po on purchase_order_line (po_id);
create index vendor_confirmation_po on vendor_confirmation (po_id);
create index vendor_confirmation_line_conf on vendor_confirmation_line (confirmation_id);
create index shipment_customer_order on shipment (customer_order_id, direction);
create index shipment_line_shipment on shipment_line (shipment_id);
create index serial_shipment_line on serial (shipment_line_id);
create index document_customer_order on document (customer_order_id);
create index discrepancy_order_status on discrepancy (customer_order_id, status);
create index event_order_at on event (customer_order_id, at desc);
create index pending_upload_expires on pending_upload (expires_at);

-- Search box: PO numbers (theirs and ours) and tracking numbers, case-insensitive prefix match.
create index customer_order_po_lower on customer_order (lower(po_number) text_pattern_ops);
create index purchase_order_po_lower on purchase_order (lower(our_po_number) text_pattern_ops);
create index shipment_tracking_lower on shipment (lower(tracking_number) text_pattern_ops);
-- serial_no is already covered by its unique index (serial_no, direction).
