# Utilisation de l’IA — passages techniques

Ces repères identifient les passages techniques accompagnés d’une aide de l’IA. Les prompts ci-dessous sont des résumés reconstitués, les formulations originales n’ayant pas été conservées.

## IA-01 Jointures entre classifications, niches et actifs

**Emplacement :** `assets/detection.py`, fonction `get_classification_niche_context`.

**Prompt reconstitué :** « Montre comment les jointures SQLAlchemy qui retrouvent les actifs liés aux niches d’une classification, sans doublons. »

## IA-02  Colonnes pandas à plusieurs niveaux

**Emplacement :** `assets/market_data.py`, fonction `get_symbol_data`.

**Prompt reconstitué :** « Montre comment récupérer les données d’un seul actif dans les colonnes à plusieurs niveaux renvoyées par yfinance. »

## IA-03  Appel Yahoo sans bloquer l’API

**Emplacement :** `assets/repository.py`, fonction `save_detected_assets`.

**Prompt reconstitué :** « Montre comment utiliser asyncio.to_thread pour appeler Yahoo sans bloquer les autres requêtes de l’API. »

## IA-04  Tâches asynchrones exécutées en parallèle

**Emplacement :** `live_market/worker.py`, fonction `stream_quotes`.

**Prompt reconstitué :** « Montre comment écouter les cours et rechercher de nouveaux actifs en parallèle avec asyncio.create_task, puis arrêter la tâche proprement. »

## IA-05  Envoi des cours par WebSocket

**Emplacement :** `routers/live_market.py`, fonction `market_websocket`.

**Prompt reconstitué :** « Montre comment envoyer régulièrement le cours présent dans Redis par WebSocket et convertir sa date au format JSON. »

## IA-06 — Limiter les appels de logos entre plusieurs workers

**Emplacement :** `assets/logos.py`, fonction `fill_missing_logo`.

**Demande résumée :** « Récupérer un logo seulement pour les actifs rencontrés sans image, sans multiplier les appels à Twelve Data. »

Le verrou PostgreSQL empêche deux traitements de réserver simultanément les mêmes crédits. Les dates des tentatives permettent de limiter les appels et d’attendre 24 heures avant de réessayer un actif.
