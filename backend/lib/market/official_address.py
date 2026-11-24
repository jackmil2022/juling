"""Translate the built-in market's public alias to its retained data source."""

from juling_market_core.market.address import OFFICIAL_MARKET_INDEX_ALIAS
from juling_market_core.market.issues import INDEX_FILENAME

from lib.infra.legacy_compat import LEGACY_BRAND, LEGACY_BRAND_LOWER

OFFICIAL_MARKET_INDEX_URL = (
    f"https://raw.githubusercontent.com/{LEGACY_BRAND}/{LEGACY_BRAND_LOWER}-market/HEAD/{INDEX_FILENAME}"
)


def effective_market_index_url(kind: str, index_url: str) -> str:
    if kind == "official" and index_url == OFFICIAL_MARKET_INDEX_ALIAS:
        return OFFICIAL_MARKET_INDEX_URL
    return index_url
