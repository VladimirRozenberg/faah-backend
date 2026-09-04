"""Catalogue unique des actifs disponibles dans FAAH."""


TECH_STOCKS = {
    "AAPL": {"name": "Apple", "exchange": "NASDAQ"},
    "MSFT": {"name": "Microsoft", "exchange": "NASDAQ"},
    "NVDA": {"name": "NVIDIA", "exchange": "NASDAQ"},
    "GOOGL": {"name": "Alphabet", "exchange": "NASDAQ"},
    "AMZN": {"name": "Amazon", "exchange": "NASDAQ"},
    "META": {"name": "Meta Platforms", "exchange": "NASDAQ"},
    "TSLA": {"name": "Tesla", "exchange": "NASDAQ"},
    "AVGO": {"name": "Broadcom", "exchange": "NASDAQ"},
    "ORCL": {"name": "Oracle", "exchange": "NYSE"},
    "AMD": {"name": "AMD", "exchange": "NASDAQ"},
}


CRYPTOS = {
    "BTC-USD": {"name": "Bitcoin", "base": "BTC", "quote": "USD", "blockchain": "Bitcoin"},
    "ETH-USD": {"name": "Ethereum", "base": "ETH", "quote": "USD", "blockchain": "Ethereum"},
    "BNB-USD": {"name": "BNB", "base": "BNB", "quote": "USD", "blockchain": "BNB Smart Chain"},
    "XRP-USD": {"name": "XRP", "base": "XRP", "quote": "USD", "blockchain": "XRP Ledger"},
    "SOL-USD": {"name": "Solana", "base": "SOL", "quote": "USD", "blockchain": "Solana"},
    "DOGE-USD": {"name": "Dogecoin", "base": "DOGE", "quote": "USD", "blockchain": "Dogecoin"},
    "ADA-USD": {"name": "Cardano", "base": "ADA", "quote": "USD", "blockchain": "Cardano"},
    "AVAX-USD": {"name": "Avalanche", "base": "AVAX", "quote": "USD", "blockchain": "Avalanche"},
    "LINK-USD": {"name": "Chainlink", "base": "LINK", "quote": "USD", "blockchain": "Ethereum"},
    "LTC-USD": {"name": "Litecoin", "base": "LTC", "quote": "USD", "blockchain": "Litecoin"},
}


FOREX = {
    "EURUSD=X": {"name": "Euro / Dollar", "base": "EUR", "quote": "USD"},
    "GBPUSD=X": {"name": "Livre / Dollar", "base": "GBP", "quote": "USD"},
    "USDJPY=X": {"name": "Dollar / Yen", "base": "USD", "quote": "JPY"},
    "USDCHF=X": {"name": "Dollar / Franc suisse", "base": "USD", "quote": "CHF"},
    "AUDUSD=X": {"name": "Dollar australien / Dollar", "base": "AUD", "quote": "USD"},
    "USDCAD=X": {"name": "Dollar / Dollar canadien", "base": "USD", "quote": "CAD"},
    "NZDUSD=X": {"name": "Dollar néo-zélandais / Dollar", "base": "NZD", "quote": "USD"},
    "EURGBP=X": {"name": "Euro / Livre", "base": "EUR", "quote": "GBP"},
    "EURJPY=X": {"name": "Euro / Yen", "base": "EUR", "quote": "JPY"},
    "GBPJPY=X": {"name": "Livre / Yen", "base": "GBP", "quote": "JPY"},
}


FUTURES = {
    "GC=F": {"name": "Or", "underlying_type": "commodity", "unit": "once troy", "contract_size": 100},
    "SI=F": {"name": "Argent", "underlying_type": "commodity", "unit": "once troy", "contract_size": 5000},
    "CL=F": {"name": "Pétrole WTI", "underlying_type": "commodity", "unit": "baril", "contract_size": 1000},
    "BZ=F": {"name": "Pétrole Brent", "underlying_type": "commodity", "unit": "baril", "contract_size": 1000},
    "NG=F": {"name": "Gaz naturel", "underlying_type": "commodity", "unit": "MMBtu", "contract_size": 10000},
    "HG=F": {"name": "Cuivre", "underlying_type": "commodity", "unit": "livre", "contract_size": 25000},
    "ZC=F": {"name": "Maïs", "underlying_type": "commodity", "unit": "boisseau", "contract_size": 5000},
    "ZW=F": {"name": "Blé", "underlying_type": "commodity", "unit": "boisseau", "contract_size": 5000},
    "ZS=F": {"name": "Soja", "underlying_type": "commodity", "unit": "boisseau", "contract_size": 5000},
    "KC=F": {"name": "Café", "underlying_type": "commodity", "unit": "livre", "contract_size": 37500},
}


ASSET_CATALOG = {
    "stock": TECH_STOCKS,
    "crypto": CRYPTOS,
    "forex": FOREX,
    "future": FUTURES,
}


# Version regroupée utilisée pour les prix, les bougies et le direct.
ALL_ASSETS = {}

for asset_type, assets in ASSET_CATALOG.items():
    for symbol, information in assets.items():
        ALL_ASSETS[symbol] = information.copy()
        ALL_ASSETS[symbol]["type"] = asset_type
