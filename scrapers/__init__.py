"""Scrapers package — now backed by the MarketCheck API."""

from scrapers.marketcheck import search_marketcheck, count_marketcheck

__all__ = ["search_marketcheck", "count_marketcheck"]
