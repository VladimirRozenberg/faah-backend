# Statut des sources externes

`GET /health/external` renvoie `yfinance` et `twelve_data`, chacun avec
`status`, `detail`, `checked_at` (UTC) et `cache_seconds`.

- Yahoo : lecture des cinq derniers jours d'AAPL via yfinance, cache 5 minutes.
  Un cours reçu prouve que ce test fonctionne, pas que tous les symboles sont disponibles.
- Twelve Data : appel authentifié à `/api_usage`, cache 30 minutes. Ce contrôle
  vérifie l'accès API et les quotas, pas la présence d'un logo pour chaque actif.
  La clé `TWELVE_DATA_API_KEY` reste uniquement côté serveur.
- Réseau limité à 5 secondes par requête, contrôle global limité à 10 secondes.
  Le thread yfinance peut finir après ce délai ; les échecs sont aussi mis en cache.
- Cache en mémoire par processus, partagé entre utilisateurs, perdu au redémarrage.
  Le Dockerfile actuel lance un seul worker. Ajouter des workers multiplie les contrôles.
- Aucun téléchargement de logo ni écriture en BDD. `/health` et son indicateur LIVE
  restent dédiés aux composants internes ; les sources externes ont leurs propres statuts.

Twelve Data indique qu'un appel `/api_usage` consomme un crédit :
https://support.twelvedata.com/en/articles/5713553-control-over-api-usage
Avec un processus continuellement sollicité : au plus 48 contrôles par 24 h,
hors redémarrages. Le bouton Refresh ne contourne pas le cache.

Déployer ce backend avant d'utiliser les nouveaux statuts dans Avalonia.
Un ancien backend affiche « Backend update required », sans prétendre que les fournisseurs sont en panne.

Tests sans réseau : `python -m unittest discover -s tests -p test_external_health.py`.
