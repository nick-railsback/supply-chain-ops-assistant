"""Seed data constants: SKUs, centers, carriers, categories."""

# ---------------------------------------------------------------------------
# Fulfillment Centers
# ---------------------------------------------------------------------------
FULFILLMENT_CENTERS: list[dict[str, object]] = [
    {
        "id": "FC-ATL-01",
        "name": "Atlanta Hub",
        "region": "southeast",
        "capacity_units": 50_000,
    },
    {
        "id": "FC-LAX-02",
        "name": "Los Angeles Hub",
        "region": "west",
        "capacity_units": 65_000,
    },
    {
        "id": "FC-ORD-01",
        "name": "Chicago Hub",
        "region": "midwest",
        "capacity_units": 45_000,
    },
    {
        "id": "FC-DFW-01",
        "name": "Dallas Hub",
        "region": "south",
        "capacity_units": 40_000,
    },
    {
        "id": "FC-SEA-01",
        "name": "Seattle Hub",
        "region": "northwest",
        "capacity_units": 35_000,
    },
]

# ---------------------------------------------------------------------------
# Helper to build a product entry (keeps catalog readable)
# ---------------------------------------------------------------------------


def _p(
    sku: str,
    name: str,
    category: str,
    min_price: float,
    max_price: float,
) -> dict[str, object]:
    return {
        "sku": sku,
        "name": name,
        "category": category,
        "min_price": min_price,
        "max_price": max_price,
    }


# ---------------------------------------------------------------------------
# Product Catalog — 80 SKUs across 5 categories
# ---------------------------------------------------------------------------
PRODUCT_CATALOG: list[dict[str, object]] = [
    # ── Health & Beauty (16 SKUs) ──────────────────────────────
    _p("AG1-POUCH-30SRV", "Daily Greens Pouch (30 Servings)", "Health & Beauty", 79.99, 89.99),
    _p("HB-RETINOL-SRM", "Retinol Night Serum 1oz", "Health & Beauty", 34.00, 42.00),
    _p("HB-VIT-C-CLNSR", "Vitamin C Brightening Cleanser", "Health & Beauty", 18.00, 24.00),
    _p("HB-HYALUR-MIST", "Hyaluronic Acid Face Mist 4oz", "Health & Beauty", 22.00, 28.00),
    _p("HB-CHAR-MASK", "Activated Charcoal Clay Mask", "Health & Beauty", 16.00, 22.00),
    _p("HB-SPF50-MINRL", "Mineral Sunscreen SPF 50", "Health & Beauty", 24.00, 32.00),
    _p("HB-BIOTIN-GUM", "Biotin Hair Gummies (60ct)", "Health & Beauty", 19.99, 24.99),
    _p("HB-CBD-BALM-2OZ", "CBD Recovery Balm 2oz", "Health & Beauty", 38.00, 48.00),
    _p("HB-PROBIOTIC-60", "Daily Probiotic 60 Capsules", "Health & Beauty", 29.99, 36.99),
    _p("HB-LIP-OIL-RSE", "Rose Petal Lip Oil", "Health & Beauty", 12.00, 16.00),
    _p("HB-DRY-SHMP-AER", "Botanical Dry Shampoo Aerosol", "Health & Beauty", 14.00, 18.00),
    _p("HB-TEETH-WHTE", "LED Teeth Whitening Kit", "Health & Beauty", 44.99, 54.99),
    _p("HB-COLLAGN-PWD", "Marine Collagen Powder 20srv", "Health & Beauty", 36.00, 44.00),
    _p("HB-EYE-CREAM", "Peptide Under-Eye Cream", "Health & Beauty", 28.00, 34.00),
    _p("HB-JADE-ROLLER", "Jade Facial Roller", "Health & Beauty", 18.00, 26.00),
    _p("HB-SCALP-SRM", "Rosemary Scalp Growth Serum", "Health & Beauty", 22.00, 30.00),
    # ── Nutrition (16 SKUs) ────────────────────────────────────
    _p("NTR-WHEY-VAN-2LB", "Vanilla Whey Protein 2lb", "Nutrition", 39.99, 49.99),
    _p("NTR-WHEY-CHOC-2LB", "Chocolate Whey Protein 2lb", "Nutrition", 39.99, 49.99),
    _p("NTR-VEGAN-PEA-2LB", "Plant-Based Pea Protein 2lb", "Nutrition", 34.99, 44.99),
    _p("NTR-CREATINE-300G", "Micronized Creatine 300g", "Nutrition", 24.99, 32.99),
    _p("NTR-PREWORK-BRY", "Pre-Workout Berry Blast 30srv", "Nutrition", 32.00, 42.00),
    _p("NTR-BCAA-MANGO", "BCAA Powder Mango 40srv", "Nutrition", 26.99, 34.99),
    _p("NTR-OMEGA3-120CT", "Omega-3 Fish Oil 120 Softgels", "Nutrition", 22.00, 28.00),
    _p("NTR-ELCTRLYT-PKT", "Electrolyte Mix Packets (30pk)", "Nutrition", 24.99, 29.99),
    _p("NTR-MAGNES-GLY", "Magnesium Glycinate 120ct", "Nutrition", 18.99, 24.99),
    _p("NTR-ASHWA-CAPS", "Ashwagandha Root Extract 90ct", "Nutrition", 19.99, 26.99),
    _p("NTR-MLTIVIT-MEN", "Men's Daily Multivitamin 60ct", "Nutrition", 24.99, 32.99),
    _p("NTR-MLTIVIT-WMN", "Women's Daily Multivitamin 60ct", "Nutrition", 24.99, 32.99),
    _p("NTR-CASEIN-VAN", "Slow-Release Casein Vanilla 2lb", "Nutrition", 42.00, 52.00),
    _p("NTR-GREENS-PWD", "Super Greens Powder 30srv", "Nutrition", 34.99, 44.99),
    _p("NTR-TURMRC-CAPS", "Turmeric Curcumin 120 Capsules", "Nutrition", 18.00, 24.00),
    _p("NTR-FIBER-PREB", "Prebiotic Fiber Blend 30srv", "Nutrition", 22.99, 28.99),
    # ── Apparel (16 SKUs) ─────────────────────────────────────
    _p("APR-HOODIE-BLK-M", "Classic Pullover Hoodie Black M", "Apparel", 58.00, 68.00),
    _p("APR-HOODIE-GRY-L", "Classic Pullover Hoodie Grey L", "Apparel", 58.00, 68.00),
    _p("APR-JOGGER-NVY-M", "Everyday Jogger Navy M", "Apparel", 48.00, 58.00),
    _p("APR-JOGGER-BLK-L", "Everyday Jogger Black L", "Apparel", 48.00, 58.00),
    _p("APR-TEE-WHT-S", "Essential Crew Tee White S", "Apparel", 28.00, 34.00),
    _p("APR-TEE-BLK-M", "Essential Crew Tee Black M", "Apparel", 28.00, 34.00),
    _p("APR-TANK-OLV-M", "Performance Tank Olive M", "Apparel", 24.00, 30.00),
    _p("APR-SHORTS-BLK-M", "Training Shorts Black M", "Apparel", 34.00, 42.00),
    _p("APR-ZIP-JKT-NVY", "Lightweight Zip Jacket Navy", "Apparel", 72.00, 88.00),
    _p("APR-LGGN-BLK-S", "High-Waist Leggings Black S", "Apparel", 52.00, 64.00),
    _p("APR-LGGN-SAGE-M", "High-Waist Leggings Sage M", "Apparel", 52.00, 64.00),
    _p("APR-BRA-BLK-S", "Seamless Sports Bra Black S", "Apparel", 38.00, 46.00),
    _p("APR-CREWNK-OAT-L", "Oversized Crewneck Oatmeal L", "Apparel", 54.00, 64.00),
    _p("APR-BEANIE-BLK", "Ribbed Knit Beanie Black", "Apparel", 22.00, 28.00),
    _p("APR-SOCKSSET-3PK", "Cushioned Ankle Socks 3-Pack", "Apparel", 16.00, 22.00),
    _p("APR-WINDBRK-CLAY", "Windbreaker Half-Zip Clay", "Apparel", 68.00, 82.00),
    # ── Accessories (16 SKUs) ─────────────────────────────────
    _p("ACC-WTRBOTL-32OZ", "Insulated Water Bottle 32oz", "Accessories", 28.00, 36.00),
    _p("ACC-SHAKER-24OZ", "Blender Shaker Bottle 24oz", "Accessories", 14.00, 18.00),
    _p("ACC-GYMBAG-BLK", "Duffle Gym Bag Black", "Accessories", 48.00, 62.00),
    _p("ACC-YOGA-MAT-5MM", "Premium Yoga Mat 5mm", "Accessories", 58.00, 72.00),
    _p("ACC-RESIST-SET", "Resistance Band Set (5pc)", "Accessories", 22.00, 30.00),
    _p("ACC-FOAMROLL-18", "High-Density Foam Roller 18in", "Accessories", 28.00, 36.00),
    _p("ACC-JUMPROPE-SPD", "Speed Jump Rope Adjustable", "Accessories", 16.00, 22.00),
    _p("ACC-MASSGUN-PRO", "Percussion Massage Gun Pro", "Accessories", 128.00, 168.00),
    _p("ACC-WRIST-WRAP", "Weightlifting Wrist Wraps Pair", "Accessories", 14.00, 20.00),
    _p("ACC-KNEESLV-LG", "Compression Knee Sleeve Large", "Accessories", 24.00, 32.00),
    _p("ACC-TOTE-CANVAS", "Canvas Market Tote Natural", "Accessories", 26.00, 34.00),
    _p("ACC-SUNGLASS-BLK", "Polarized Sport Sunglasses", "Accessories", 38.00, 48.00),
    _p("ACC-HEADBAND-3PK", "Moisture-Wicking Headband 3-Pack", "Accessories", 14.00, 18.00),
    _p("ACC-GLOVES-TRNG", "Padded Training Gloves", "Accessories", 22.00, 30.00),
    _p("ACC-BKPK-DYPK", "Daypack Backpack 25L Black", "Accessories", 64.00, 78.00),
    _p("ACC-LACROBALL-2", "Lacrosse Massage Ball 2-Pack", "Accessories", 10.00, 14.00),
    # ── Home (16 SKUs) ────────────────────────────────────────
    _p("HOM-CANDLE-LAV", "Lavender Soy Candle", "Home", 24.00, 32.00),
    _p("HOM-CANDLE-CEDAR", "Cedarwood & Sage Candle", "Home", 24.00, 32.00),
    _p("HOM-DIFFUSR-EUCL", "Eucalyptus Reed Diffuser", "Home", 28.00, 36.00),
    _p("HOM-BLANKET-KNIT", "Chunky Knit Throw Blanket", "Home", 68.00, 88.00),
    _p("HOM-MUG-CERAMIC", "Stoneware Ceramic Mug 14oz", "Home", 18.00, 24.00),
    _p("HOM-COASTERS-4PK", "Marble Coaster Set (4pk)", "Home", 22.00, 30.00),
    _p("HOM-PLANTR-TRRCTA", "Terracotta Planter 6in", "Home", 16.00, 22.00),
    _p("HOM-TRAY-ACACIA", "Acacia Wood Serving Tray", "Home", 34.00, 44.00),
    _p("HOM-PILLOW-LINEN", "Linen Throw Pillow Cover 18in", "Home", 28.00, 36.00),
    _p("HOM-BATHSET-3PC", "Organic Cotton Bath Towel Set", "Home", 48.00, 62.00),
    _p("HOM-WLART-ABSRT", "Abstract Line Art Print 18x24", "Home", 32.00, 42.00),
    _p("HOM-VASE-RIPPLE", "Ripple Glass Vase 10in", "Home", 26.00, 34.00),
    _p("HOM-STORAGE-BSKT", "Woven Seagrass Storage Basket", "Home", 28.00, 38.00),
    _p("HOM-LAMP-DESK", "Minimalist LED Desk Lamp", "Home", 44.00, 56.00),
    _p("HOM-BOARD-OLIVE", "Olive Wood Cutting Board", "Home", 36.00, 48.00),
    _p("HOM-APRON-CANVAS", "Waxed Canvas Apron", "Home", 38.00, 48.00),
]

# ---------------------------------------------------------------------------
# Carriers
# ---------------------------------------------------------------------------
CARRIERS: list[dict[str, object]] = [
    {
        "name": "FedEx",
        "service_levels": ["ground", "express", "2day"],
        "cost_tier": "premium",
    },
    {
        "name": "UPS",
        "service_levels": ["ground", "2day", "next_day"],
        "cost_tier": "standard",
    },
    {
        "name": "USPS",
        "service_levels": ["priority", "first_class", "media"],
        "cost_tier": "economy",
    },
    {
        "name": "OnTrac",
        "service_levels": ["ground", "sunrise"],
        "cost_tier": "economy",
    },
    {
        "name": "LSO",
        "service_levels": ["ground", "priority"],
        "cost_tier": "economy",
    },
]

# ---------------------------------------------------------------------------
# Carrier mix — probability weights (must sum to 1.0)
# ---------------------------------------------------------------------------
CARRIER_MIX: dict[str, float] = {
    "FedEx": 0.35,
    "UPS": 0.30,
    "USPS": 0.20,
    "OnTrac": 0.10,
    "LSO": 0.05,
}

# ---------------------------------------------------------------------------
# Order channels — probability weights
# ---------------------------------------------------------------------------
ORDER_CHANNELS: dict[str, float] = {
    "dtc_web": 0.40,
    "dtc_mobile": 0.25,
    "wholesale_b2b": 0.15,
    "marketplace_amazon": 0.12,
    "marketplace_shopify": 0.08,
}

# ---------------------------------------------------------------------------
# Customer tiers — probability weights
# ---------------------------------------------------------------------------
CUSTOMER_TIERS: dict[str, float] = {
    "standard": 0.60,
    "premium": 0.30,
    "enterprise": 0.10,
}

# ---------------------------------------------------------------------------
# Exception types — probability weights
# ---------------------------------------------------------------------------
EXCEPTION_TYPES: dict[str, float] = {
    "address_invalid": 0.15,
    "payment_failed": 0.12,
    "item_backordered": 0.20,
    "sla_at_risk": 0.18,
    "damaged_in_warehouse": 0.08,
    "wrong_item_picked": 0.10,
    "customer_requested_cancel": 0.12,
    "carrier_rejection": 0.05,
}

# ---------------------------------------------------------------------------
# US Regions — zip prefix ranges for realistic address generation
# ---------------------------------------------------------------------------
US_REGIONS: list[dict[str, object]] = [
    {
        "region": "northeast",
        "states": [
            "CT",
            "DE",
            "MA",
            "MD",
            "ME",
            "NH",
            "NJ",
            "NY",
            "PA",
            "RI",
            "VT",
        ],
        "zip_prefix_ranges": [(10, 19), (20, 21), (60, 69)],
    },
    {
        "region": "southeast",
        "states": [
            "AL",
            "FL",
            "GA",
            "KY",
            "MS",
            "NC",
            "SC",
            "TN",
            "VA",
            "WV",
        ],
        "zip_prefix_ranges": [(22, 27), (29, 39)],
    },
    {
        "region": "midwest",
        "states": [
            "IA",
            "IL",
            "IN",
            "KS",
            "MI",
            "MN",
            "MO",
            "NE",
            "ND",
            "OH",
            "SD",
            "WI",
        ],
        "zip_prefix_ranges": [(40, 49), (50, 58), (60, 62)],
    },
    {
        "region": "south",
        "states": ["AR", "LA", "OK", "TX"],
        "zip_prefix_ranges": [(70, 79)],
    },
    {
        "region": "west",
        "states": [
            "AZ",
            "CA",
            "CO",
            "HI",
            "NV",
            "NM",
            "UT",
        ],
        "zip_prefix_ranges": [(80, 93), (96, 96)],
    },
    {
        "region": "northwest",
        "states": ["AK", "ID", "MT", "OR", "WA", "WY"],
        "zip_prefix_ranges": [
            (59, 59),
            (83, 84),
            (97, 99),
        ],
    },
]
