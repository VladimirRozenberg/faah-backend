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
    "BTC-USD": {"name": "Bitcoin", "blockchain": "Bitcoin"},
    "ETH-USD": {"name": "Ethereum", "blockchain": "Ethereum"},
    "BNB-USD": {"name": "BNB", "blockchain": "BNB Smart Chain"},
    "XRP-USD": {"name": "XRP", "blockchain": "XRP Ledger"},
    "SOL-USD": {"name": "Solana", "blockchain": "Solana"},
    "DOGE-USD": {"name": "Dogecoin", "blockchain": "Dogecoin"},
    "ADA-USD": {"name": "Cardano", "blockchain": "Cardano"},
    "AVAX-USD": {"name": "Avalanche", "blockchain": "Avalanche"},
    "LINK-USD": {"name": "Chainlink", "blockchain": "Ethereum"},
    "LTC-USD": {"name": "Litecoin", "blockchain": "Litecoin"},
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


COMMODITIES = {
    "GC=F": {"name": "Or", "unit": "once troy", "contract_size": 100},
    "SI=F": {"name": "Argent", "unit": "once troy", "contract_size": 5000},
    "CL=F": {"name": "Pétrole WTI", "unit": "baril", "contract_size": 1000},
    "BZ=F": {"name": "Pétrole Brent", "unit": "baril", "contract_size": 1000},
    "NG=F": {"name": "Gaz naturel", "unit": "MMBtu", "contract_size": 10000},
    "HG=F": {"name": "Cuivre", "unit": "livre", "contract_size": 25000},
    "ZC=F": {"name": "Maïs", "unit": "boisseau", "contract_size": 5000},
    "ZW=F": {"name": "Blé", "unit": "boisseau", "contract_size": 5000},
    "ZS=F": {"name": "Soja", "unit": "boisseau", "contract_size": 5000},
    "KC=F": {"name": "Café", "unit": "livre", "contract_size": 37500},
}


ASSET_CATALOG = {
    "stock": TECH_STOCKS,
    "crypto": CRYPTOS,
    "forex": FOREX,
    "commodity": COMMODITIES,
}


# Version regroupée utilisée pour les prix, les bougies et le direct.
ALL_ASSETS = {}

for asset_type, assets in ASSET_CATALOG.items():
    for symbol, information in assets.items():
        ALL_ASSETS[symbol] = information.copy()
        ALL_ASSETS[symbol]["type"] = asset_type
