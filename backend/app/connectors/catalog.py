"""A fixed, realistic-looking mock catalogue.

Every record here is synthetic. The mock source is flagged ``is_synthetic`` and
the UI must label it as demo data.
"""

from __future__ import annotations

from dataclasses import dataclass

CATEGORIES: list[tuple[str, str]] = [
    ("electronics", "Electronics and gadgets"),
    ("home-kitchen", "Home and kitchen"),
    ("home-improvement", "Home improvement"),
    ("fashion", "Fashion and accessories"),
    ("beauty", "Beauty and personal care"),
    ("health-fitness", "Health and fitness"),
    ("pets", "Pet products"),
    ("sports-outdoors", "Sports and outdoors"),
    ("toys-games", "Toys and games"),
    ("books-stationery", "Books and stationery"),
    ("automotive", "Automotive accessories"),
    ("travel", "Travel accessories"),
    ("baby-kids", "Baby and children"),
    ("hobbies", "Hobbies and collectibles"),
    ("food-beverage", "Food and beverages"),
    ("seasonal-gifts", "Seasonal and gift products"),
]


@dataclass(frozen=True)
class MockProduct:
    slug: str
    name: str
    category_slug: str
    brand: str
    price: float
    archetype: str  # rising | declining | stable | seasonal | emerging | new
    base_level: float
    peak_month: int = 12


def _p(
    slug: str,
    name: str,
    category: str,
    brand: str,
    price: float,
    archetype: str,
    base: float,
    peak: int = 12,
) -> MockProduct:
    return MockProduct(slug, name, category, brand, price, archetype, base, peak)


MOCK_PRODUCTS: list[MockProduct] = [
    # Electronics
    _p("wireless-earbuds-anc", "Wireless Earbuds with Active Noise Cancelling", "electronics", "Nimbus Audio", 89.95, "rising", 42),
    _p("magnetic-phone-charger", "Magnetic Wireless Phone Charger", "electronics", "Volt & Co", 39.95, "stable", 38),
    _p("mini-projector", "Portable Mini Projector", "electronics", "Nimbus Audio", 149.0, "seasonal", 34, 11),
    # Home and kitchen
    _p("silicone-kitchen-tray", "Silicone Kitchen Organisation Tray", "home-kitchen", "Aurora Home", 34.5, "rising", 46),
    _p("electric-milk-frother", "Electric Milk Frother", "home-kitchen", "Aurora Home", 44.0, "stable", 35),
    _p("bamboo-drawer-divider", "Bamboo Drawer Divider Set", "home-kitchen", "Paperbark", 29.95, "emerging", 28),
    # Home improvement
    _p("led-motion-strip", "LED Motion Sensor Light Strip", "home-improvement", "Harbour Goods", 27.99, "rising", 40),
    _p("cordless-screwdriver", "Cordless Precision Screwdriver", "home-improvement", "Harbour Goods", 59.0, "stable", 36),
    _p("wall-tool-organiser", "Wall Mount Tool Organiser", "home-improvement", "Harbour Goods", 49.0, "seasonal", 30, 9),
    # Fashion
    _p("waterproof-crossbody", "Waterproof Crossbody Bag", "fashion", "Coastline", 69.0, "rising", 44),
    _p("merino-crew-socks", "Merino Blend Crew Socks", "fashion", "Wattle & Co", 24.95, "seasonal", 32, 6),
    _p("linen-oversized-shirt", "Oversized Linen Shirt", "fashion", "Coastline", 79.0, "declining", 48),
    # Beauty
    _p("gua-sha-set", "Gua Sha Facial Tool Set", "beauty", "Lumen Skin", 32.0, "declining", 52),
    _p("scalp-massage-brush", "Scalp Massage Brush", "beauty", "Lumen Skin", 19.95, "rising", 38),
    _p("vitamin-c-serum", "Vitamin C Brightening Serum", "beauty", "Lumen Skin", 49.0, "stable", 45),
    # Health and fitness
    _p("resistance-band-set", "Resistance Band Set", "health-fitness", "Tidewell", 36.0, "seasonal", 40, 1),
    _p("smart-jump-rope", "Smart Jump Rope with Counter", "health-fitness", "Tidewell", 45.0, "rising", 33),
    _p("vibration-foam-roller", "Foam Roller with Vibration", "health-fitness", "Tidewell", 89.0, "stable", 30),
    # Pets
    _p("slow-feeder-bowl", "Slow Feeder Dog Bowl", "pets", "Kookaburra Co", 26.0, "rising", 47),
    _p("cat-window-hammock", "Cat Window Hammock", "pets", "Kookaburra Co", 39.0, "emerging", 29),
    _p("portable-pet-bottle", "Portable Pet Water Bottle", "pets", "Kookaburra Co", 22.0, "stable", 36),
    # Sports and outdoors
    _p("collapsible-lantern", "Collapsible Camping Lantern", "sports-outdoors", "Outback Supply", 34.0, "seasonal", 38, 12),
    _p("trekking-pole-pair", "Trekking Pole Pair", "sports-outdoors", "Outback Supply", 79.0, "stable", 31),
    _p("waterproof-dry-bag", "Waterproof Dry Bag 20L", "sports-outdoors", "Outback Supply", 42.0, "seasonal", 35, 1),
    # Toys and games
    _p("magnetic-building-tiles", "Magnetic Building Tiles", "toys-games", "Bright Nest", 59.0, "seasonal", 44, 12),
    _p("wooden-balance-board", "Wooden Balance Board", "toys-games", "Bright Nest", 69.0, "rising", 34),
    _p("family-card-game", "Family Card Game", "toys-games", "Bright Nest", 24.0, "seasonal", 39, 12),
    # Books and stationery
    _p("dot-grid-journal", "Dot Grid Hardback Journal", "books-stationery", "Paperbark", 28.0, "stable", 37),
    _p("ergonomic-desk-pad", "Ergonomic Desk Pad", "books-stationery", "Paperbark", 39.0, "rising", 32),
    _p("fineliner-pen-set", "Fineliner Pen Set", "books-stationery", "Paperbark", 21.0, "seasonal", 30, 1),
    # Automotive
    _p("magnetic-car-mount", "Magnetic Phone Mount for Cars", "automotive", "Volt & Co", 29.95, "stable", 43),
    _p("seat-gap-filler", "Car Seat Gap Filler", "automotive", "Harbour Goods", 19.95, "declining", 39),
    _p("tyre-pressure-gauge", "Digital Tyre Pressure Gauge", "automotive", "Volt & Co", 32.0, "stable", 34),
    # Travel
    _p("packing-cube-set", "Packing Cube Set", "travel", "Coastline", 49.0, "rising", 41),
    _p("travel-neck-pillow", "Memory Foam Travel Neck Pillow", "travel", "Coastline", 39.0, "declining", 46),
    _p("universal-adapter", "Universal Travel Adapter", "travel", "Volt & Co", 44.0, "seasonal", 37, 12),
    # Baby and children
    _p("silicone-feeding-set", "Silicone Baby Feeding Set", "baby-kids", "Little Wattle", 54.0, "rising", 36),
    _p("white-noise-machine", "Portable White Noise Machine", "baby-kids", "Little Wattle", 49.0, "stable", 33),
    _p("baby-bath-support", "Baby Bath Support", "baby-kids", "Little Wattle", 39.0, "declining", 35),
    # Hobbies
    _p("resin-casting-kit", "Resin Casting Starter Kit", "hobbies", "Ember & Oak", 64.0, "emerging", 27),
    _p("model-paint-organiser", "Model Paint Organiser", "hobbies", "Ember & Oak", 44.0, "stable", 26),
    _p("crochet-yarn-bowl", "Crochet Yarn Bowl", "hobbies", "Ember & Oak", 36.0, "rising", 31),
    # Food and beverages
    _p("matcha-whisk-set", "Matcha Whisk Set", "food-beverage", "Wattle & Co", 38.0, "rising", 40),
    _p("cold-brew-maker", "Cold Brew Coffee Maker", "food-beverage", "Wattle & Co", 52.0, "seasonal", 42, 1),
    _p("reusable-produce-bags", "Reusable Produce Bags", "food-beverage", "Paperbark", 18.5, "declining", 29),
    # Seasonal and gifts
    _p("fairy-curtain-lights", "LED Fairy Curtain Lights", "seasonal-gifts", "Aurora Home", 26.0, "seasonal", 45, 12),
    _p("advent-calendar", "Personalised Advent Calendar", "seasonal-gifts", "Wattle & Co", 59.0, "seasonal", 32, 12),
    _p("gift-wrap-organiser", "Gift Wrapping Organiser", "seasonal-gifts", "Aurora Home", 34.0, "new", 24, 12),
]

CATEGORY_NAMES = dict(CATEGORIES)
