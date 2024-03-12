"""Dispatch emails as .eml files, the way a distributor's warehouse system sends them.

Two habits, as in real life: some put the serial numbers in the body of the email, others attach a CSV.
Addresses use the reserved .example domain.
"""

from datetime import datetime, time, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime

from synth.catalogue import PRODUCT_BY_PART, US
from synth.scenario import SynthOrder

GST = timezone(timedelta(hours=4))


def dispatch_email(o: SynthOrder, k: int = 0) -> bytes:
    ship = o.inbound[k]
    tracking = o.tracking[ship.reference]
    domain = o.distributor.short_code.lower() + "-distribution.example"
    sent = datetime.combine(o.today - timedelta(days=o.days_ago.get("received", 0) + 1), time(10, 42), GST)

    msg = EmailMessage()
    msg["From"] = f"{o.distributor.name} Dispatch <dispatch@{domain}>"
    msg["To"] = "orders@keystone-data.example"
    msg["Subject"] = f"Dispatch notice {ship.reference} for your order {o.our_po.our_po_number}"
    msg["Date"] = format_datetime(sent)
    msg["Message-ID"] = f"<{ship.reference.lower()}.{tracking.lower()}@{domain}>"

    rows = [
        f"  {sl.part_number:<16} qty {sl.qty:>3}  {PRODUCT_BY_PART[sl.part_number].description[:46]}"
        for sl in ship.lines
    ]
    attach_csv = o.carrier.short_code == "AAF"
    body = [
        f"Dear {US['name']} team,",
        "",
        f"Your order {o.our_po.our_po_number} has been dispatched"
        + (" in part. The balance will follow." if ship.marked_partial else "."),
        "",
        f"Carrier: {o.carrier.name}",
        f"Tracking number: {tracking}",
        f"Delivery note: {ship.reference}",
        "",
        "Items:",
        *rows,
        "",
    ]
    if attach_csv:
        body.append("Serial numbers are in the attached file.")
    else:
        body.append("Serial numbers:")
        for sl in ship.lines:
            if sl.serials:
                body.append(f"  {sl.part_number}: " + ", ".join(sl.serials))
    body += ["", "Regards,", "Dispatch desk", o.distributor.name]
    msg.set_content("\n".join(body))

    if attach_csv:
        csv = ["part_number,serial_number"]
        csv += [f"{sl.part_number},{s}" for sl in ship.lines for s in sl.serials]
        msg.add_attachment("\n".join(csv) + "\n", subtype="csv", filename=f"serials-{ship.reference}.csv")
    return bytes(msg)
