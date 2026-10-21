"""Who trades with the fictional reseller, and what it sells.

Every company here is invented. Product families are real catalogue lines (a reseller in this market sells
these), but part numbers and prices are made up for the demo.
"""

from dataclasses import dataclass
from decimal import Decimal

# The reseller the documents are addressed to. Fictional.
US = {
    "name": "Keystone Data Systems FZ-LLC",
    "address": "Office 214, Building 9, Dubai Internet City, Dubai",
    "trn": "100458213900003",
}


@dataclass(frozen=True)
class Party:
    kind: str
    name: str
    short_code: str
    trn: str | None
    sector: str | None
    address: str
    emirate: str


CUSTOMERS = [
    Party(
        "customer",
        "Al Waha Municipal Services",
        "AWMS",
        "100311740200003",
        "government",
        "Municipality Complex, Sheikh Rashid Street",
        "Ajman",
    ),
    Party(
        "customer",
        "Sahil Ports Authority",
        "SPA",
        "100527904800003",
        "government",
        "Marine Building 2, Port Road",
        "Fujairah",
    ),
    Party(
        "customer",
        "Gulf Crescent Bank",
        "GCB",
        "100274611900003",
        "bank",
        "Crescent Tower, Al Maryah Island",
        "Abu Dhabi",
    ),
    Party(
        "customer",
        "Marjan Commercial Bank",
        "MCB",
        "100690332100003",
        "bank",
        "Level 18, Marjan Business Tower, Business Bay",
        "Dubai",
    ),
    Party(
        "customer",
        "Seven Palms Academy",
        "SPAC",
        "100845120700003",
        "education",
        "Academic Block A, Al Rahmaniya 3",
        "Sharjah",
    ),
    Party(
        "customer",
        "Bayt Al Ilm Schools",
        "BAIS",
        "100163008400003",
        "education",
        "Central Office, Al Qusais 2",
        "Dubai",
    ),
    Party(
        "customer",
        "Darat Medical Centre",
        "DMC",
        "100902774500003",
        "healthcare",
        "Medical District, Khalifa City",
        "Abu Dhabi",
    ),
    Party(
        "customer",
        "Qasr Logistics Group",
        "QLG",
        "100735019600003",
        "enterprise",
        "Warehouse 12, Jebel Ali Free Zone South",
        "Dubai",
    ),
]

DISTRIBUTORS = [
    Party(
        "distributor",
        "Falcon Value Distribution FZE",
        "FVD",
        "100219874300003",
        None,
        "Unit 5, Building 3, Dubai Silicon Oasis",
        "Dubai",
    ),
    Party(
        "distributor",
        "Dune Channel Partners LLC",
        "DCP",
        "100604481200003",
        None,
        "Floor 7, Barsha Heights Tower 2",
        "Dubai",
    ),
    Party(
        "distributor",
        "Corniche Tech Supply LLC",
        "CTS",
        "100377265900003",
        None,
        "Plot 44, Mussafah Industrial Area",
        "Abu Dhabi",
    ),
]

# Each carrier writes its tracking numbers its own way; the email parser learns these shapes.
CARRIERS = [
    Party("carrier", "Swift Gulf Couriers", "SGC", None, None, "Al Garhoud", "Dubai"),
    Party("carrier", "Atlas Air Freight", "AAF", None, None, "Dubai Airport Freezone", "Dubai"),
    Party("carrier", "Sandline Express", "SLX", None, None, "Al Quoz Industrial 3", "Dubai"),
]
TRACKING_FORMATS = {
    "SGC": "SG{d10}",  # SG + 10 digits
    "AAF": "176-{d8}",  # air waybill: airline prefix + 8 digits
    "SLX": "SLX{d9}AE",  # SLX + 9 digits + AE
}


@dataclass(frozen=True)
class Product:
    part_number: str
    brand: str
    description: str
    category: str
    serialised: bool
    list_price: Decimal
    serial_prefix: str = ""  # serialised items: how their serial numbers start


def _p(part, brand, desc, cat, price, serial_prefix=""):
    return Product(part, brand, desc, cat, bool(serial_prefix), Decimal(price), serial_prefix)


PRODUCTS = [
    # Servers and storage (serialised: each unit has a service tag / serial)
    _p(
        "PER760-XS2",
        "Dell",
        "PowerEdge R760 2U server, 2x Xeon Silver 4510, 256 GB, 4x 1.92 TB SSD",
        "server",
        "48250.00",
        "7",
    ),
    _p(
        "PER660-XS1",
        "Dell",
        "PowerEdge R660 1U server, 1x Xeon Silver 4514Y, 128 GB, 2x 960 GB SSD",
        "server",
        "27900.00",
        "6",
    ),
    _p(
        "PER460-T1",
        "Dell",
        "PowerEdge T360 tower server, Xeon E-2434, 32 GB, 2x 2 TB HDD",
        "server",
        "11450.00",
        "5",
    ),
    _p(
        "PST500T-25",
        "Dell",
        "PowerStore 500T base enclosure, 25x NVMe bays, 10 TB usable",
        "storage",
        "131600.00",
        "F",
    ),
    _p("ME5024-12T", "Dell", "PowerVault ME5024 array, 12x 2.4 TB SAS 10K", "storage", "52300.00", "M"),
    _p(
        "DD6400-64T", "Dell", "PowerProtect DD6400 backup appliance, 64 TB usable", "backup", "214800.00", "D"
    ),
    _p("DP4400-24T", "Dell", "PowerProtect DP4400 integrated appliance, 24 TB", "backup", "168400.00", "P"),
    _p("S5248F-ON", "Dell", "PowerSwitch S5248F-ON, 48x 25GbE, 4x 100GbE", "network", "36800.00", "S"),
    _p("SFP28-SR-25G", "Dell", "SFP28 25GbE SR optical transceiver, 85C", "network", "690.00", "X"),
    _p(
        "QLE2772-HBA", "Marvell", "QLogic QLE2772 32Gb dual-port Fibre Channel HBA", "network", "4150.00", "Q"
    ),
    _p(
        "LAT7450-I7",
        "Dell",
        "Latitude 7450 laptop, Core Ultra 7 165U, 16 GB, 512 GB",
        "endpoint",
        "6890.00",
        "L",
    ),
    _p(
        "PRE3680-WS",
        "Dell",
        "Precision 3680 tower workstation, Core i9, 64 GB, RTX 2000 Ada",
        "endpoint",
        "15200.00",
        "W",
    ),
    _p("P2425H-MON", "Dell", "Dell Pro 24 monitor P2425H, 23.8 inch, IPS", "endpoint", "985.00", "N"),
    _p("WD22TB4-DK", "Dell", "Thunderbolt dock WD22TB4", "endpoint", "1290.00", "K"),
    _p(
        "GB10-PMAX",
        "Dell",
        "Dell Pro Max GB10 desk-side AI workstation, 128 GB unified memory",
        "endpoint",
        "18900.00",
        "G",
    ),
    # Software and services (not serialised)
    _p(
        "COH-DP-1TB-3Y",
        "Cohesity",
        "Cohesity DataProtect subscription, per front-end TB, 3 years",
        "software",
        "2140.00",
    ),
    _p(
        "VVF-CORE-1Y",
        "VMware",
        "VMware vSphere Foundation subscription, per core, 1 year",
        "software",
        "640.00",
    ),
    _p(
        "RSA-SID-700-50",
        "RSA",
        "RSA SecurID SID700 hardware tokens, pack of 50, 3 years",
        "security",
        "9800.00",
    ),
    _p(
        "FP-DLP-ENT-1Y",
        "Forcepoint",
        "Forcepoint DLP Endpoint licence, per user, 1 year",
        "security",
        "215.00",
    ),
    _p(
        "SYM-SEP-USR-1Y",
        "Symantec",
        "Symantec Endpoint Security Complete, per user, 1 year",
        "security",
        "182.00",
    ),
    _p("CUP-DEX-USR-1Y", "ControlUp", "ControlUp DEX platform, per user, 1 year", "software", "158.00"),
    _p("PS-PRO-3Y-NBD", "Dell", "ProSupport Plus 3 years, next business day onsite", "service", "6400.00"),
    _p(
        "SVC-INSTALL-D1",
        "Keystone",
        "Installation and configuration, per day, one engineer",
        "service",
        "3200.00",
    ),
]

PRODUCT_BY_PART = {p.part_number: p for p in PRODUCTS}

# What each kind of customer tends to buy, so orders look plausible.
SECTOR_BASKETS = {
    "government": [
        "PER760-XS2",
        "PER660-XS1",
        "PST500T-25",
        "DD6400-64T",
        "S5248F-ON",
        "SFP28-SR-25G",
        "COH-DP-1TB-3Y",
        "VVF-CORE-1Y",
        "PS-PRO-3Y-NBD",
        "SVC-INSTALL-D1",
        "RSA-SID-700-50",
    ],
    "bank": [
        "PER760-XS2",
        "ME5024-12T",
        "DP4400-24T",
        "QLE2772-HBA",
        "RSA-SID-700-50",
        "FP-DLP-ENT-1Y",
        "SYM-SEP-USR-1Y",
        "PS-PRO-3Y-NBD",
        "COH-DP-1TB-3Y",
    ],
    "education": [
        "LAT7450-I7",
        "P2425H-MON",
        "WD22TB4-DK",
        "PER460-T1",
        "SYM-SEP-USR-1Y",
        "CUP-DEX-USR-1Y",
        "PRE3680-WS",
        "GB10-PMAX",
    ],
    "healthcare": [
        "PER660-XS1",
        "ME5024-12T",
        "LAT7450-I7",
        "P2425H-MON",
        "FP-DLP-ENT-1Y",
        "PS-PRO-3Y-NBD",
        "DP4400-24T",
    ],
    "enterprise": [
        "PER660-XS1",
        "S5248F-ON",
        "SFP28-SR-25G",
        "LAT7450-I7",
        "WD22TB4-DK",
        "VVF-CORE-1Y",
        "CUP-DEX-USR-1Y",
        "GB10-PMAX",
        "SVC-INSTALL-D1",
    ],
}

# Substitutions a distributor might offer when a part is short (ordered -> offered).
SUBSTITUTES = {
    "PER660-XS1": "PER760-XS2",
    "P2425H-MON": "P2425H-MON2",
    "LAT7450-I7": "LAT7450-U5",
    "SFP28-SR-25G": "SFP28-SR-25GX",
}
EXTRA_PRODUCTS = [
    _p(
        "P2425H-MON2", "Dell", "Dell Pro 24 monitor P2425HE, 23.8 inch, USB-C hub", "endpoint", "1120.00", "N"
    ),
    _p(
        "LAT7450-U5",
        "Dell",
        "Latitude 7450 laptop, Core Ultra 5 135U, 16 GB, 512 GB",
        "endpoint",
        "6150.00",
        "L",
    ),
    _p(
        "SFP28-SR-25GX",
        "Dell",
        "SFP28 25GbE SR optical transceiver, extended temperature",
        "network",
        "760.00",
        "X",
    ),
]
PRODUCT_BY_PART.update({p.part_number: p for p in EXTRA_PRODUCTS})
