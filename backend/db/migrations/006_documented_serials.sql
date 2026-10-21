-- What the paper says versus what we booked.
--
-- `serial` holds physical units, and a unit can only arrive once (unique per direction). A delivery note can
-- still list a serial we already have, which is exactly the problem worth catching. So each shipment line
-- keeps the serial list as documented; the check engine compares it with the booked units, and only
-- serials that are not already booked become `serial` rows.

alter table shipment_line add column serials_as_documented text[] not null default '{}';
alter table shipment add column marked_partial boolean not null default false;
