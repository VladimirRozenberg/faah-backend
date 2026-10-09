# Utilisation de l’IA — passages techniques de Dylan

Mise à jour : 9 octobre 2026. Périmètre : `assets`, `live_market`, `portfolio` et les routes associées.

Les repères IA-01 à IA-06 reprennent le document précédent. Les nouveaux repères signalent l’aide de l’IA à la relecture et à l’explication de passages techniques dans cette mise à jour ; ils ne permettent pas d’affirmer qui a écrit le code initial. Les prompts ci-dessous sont des résumés reconstitués de l’aide, pas des citations exactes.

Seuls les commentaires et ce document ont été modifiés. Les en-têtes de fichiers et les opérations simples ne reçoivent pas de mention générale d’IA.

## Les passages à préparer en priorité pour l’oral

- **IA-10** : les deux scripts Lua qui fusionnent les cours dans Redis.
- **IA-04, IA-08 et IA-09** : tâches parallèles, secours historique et reconnexion du worker.
- **IA-11 et IA-14** : conversion en USD, prix choisi par le serveur et écritures du portefeuille.
- **IA-17 et IA-20** : filtres SQL avec pagination et demande d’analyse sans doublon.

## Évolutions importantes depuis la première version

- Le worker lit désormais tous les symboles de la table `assets` ; les routes live vérifient encore `ast_is_tracked`.
- Redis peut contenir un cours `live` ou une clôture `daily` utilisée en secours ; leurs dates et leurs sources restent importantes.
- Le portefeuille prend en charge plusieurs portefeuilles par utilisateur, un solde de compte et la conversion des cours en USD.
- Les scripts Lua, les taux de change et la pagination nécessitent désormais des explications supplémentaires.

## Repères dans le code

### IA-01 — Jointures et regroupement des actifs

**Emplacement :** [assets/detection.py](assets/detection.py#L111), `get_classification_niche_context`.

**À expliquer :** Les jointures relient les tables. outerjoin garde les actifs sans fiche Stock ; le dictionnaire regroupe les niches d’un même actif.

**Prompt reconstitué :** « Explique comment retrouver les actifs liés aux niches d’une actualité sans les répéter. »

### IA-02 — Colonnes pandas à plusieurs niveaux

**Emplacement :** [assets/market_data.py](assets/market_data.py#L36), `get_symbol_data`.

**À expliquer :** MultiIndex représente plusieurs niveaux de colonnes. Ici, on choisit d’abord le symbole, puis ses champs comme Close ou Volume.

**Prompt reconstitué :** « Explique comment isoler les colonnes d’un symbole dans le tableau Yahoo. »

### IA-03 — Appel Yahoo dans un thread

**Emplacement :** [assets/repository.py](assets/repository.py#L180), `save_detected_assets`.

**À expliquer :** L’appel Yahoo est synchrone. Le thread le prend en charge ; await attend son résultat en laissant les autres tâches avancer.

**Prompt reconstitué :** « Explique pourquoi appeler Yahoo avec asyncio.to_thread évite de bloquer l’API. »

### IA-04 — Écoute Yahoo et abonnements en parallèle

**Emplacement :** [live_market/worker.py](live_market/worker.py#L320), `stream_quotes`.

**À expliquer :** create_task lance la surveillance des nouveaux actifs pendant l’écoute. Le finally demande son arrêt avec cancel puis attend sa fin avec gather.

**Prompt reconstitué :** « Explique comment écouter les cours et ajouter de nouveaux symboles en même temps, puis arrêter la tâche. »

### IA-05 — Connexion WebSocket vers Avalonia

**Emplacement :** [routers/live_market.py](routers/live_market.py#L70), `market_websocket`.

**À expliquer :** La connexion reste ouverte. La route relit Redis toutes les trois secondes, même sans nouveau cours ; model_dump(mode="json") convertit notamment les dates.

**Prompt reconstitué :** « Explique comment envoyer le cours Redis toutes les trois secondes par WebSocket. »

### IA-06 — Limitation des appels entre plusieurs traitements

**Emplacement :** [assets/logos.py](assets/logos.py#L84), `fill_missing_logo`.

**À expliquer :** Le verrou PostgreSQL est partagé par les traitements utilisant la même base. Il est libéré au commit ou rollback ; les dates servent aux limites et au délai de 24 h par actif.

**Prompt reconstitué :** « Explique comment éviter des téléchargements simultanés et respecter les délais entre tentatives de logo. »

### IA-07 — Téléchargement progressif du logo

**Emplacement :** [assets/logos.py](assets/logos.py#L54), `download_logo`.

**À expliquer :** stream ouvre le téléchargement sans tout charger d’un coup. aiter_bytes fournit les morceaux ; le code accepte certains formats annoncés et arrête au-delà de 1 Mo. Cette fonction ne fait pas l’écriture en base.

**Prompt reconstitué :** « Explique le téléchargement par morceaux, le contrôle du format et la taille maximale du logo. »

### IA-08 — Secours par les cours historiques

**Emplacement :** [live_market/worker.py](live_market/worker.py#L88), `refresh_stale_historical_quotes`.

**À expliquer :** La boucle examine le cache chaque minute. Elle demande des clôtures journalières pour les cours absents, trop anciens ou incomplets ; les tentatives récentes limitent certaines répétitions. La source daily permet de distinguer ces prix du direct.

**Prompt reconstitué :** « Explique comment compléter le cache quand un cours est ancien ou incomplet sans présenter une clôture comme du direct. »

### IA-09 — Suivi du worker et reconnexion progressive

**Emplacement :** [live_market/worker.py](live_market/worker.py#L363), `listen_to_yfinance`.

**À expliquer :** Deux tâches accompagnent l’écoute : statut toutes les 15 s et secours historique. En cas de reconnexions rapides, le délai passe de 3 à 6, 12… jusqu’à 60 s ; une connexion d’au moins 60 s remet le délai à 3 s.

**Prompt reconstitué :** « Explique le signal de vie du worker et pourquoi le délai de reconnexion augmente. »

### IA-10 — Fusion atomique des cours dans Redis

**Emplacement :** [live_market/redis_client.py](live_market/redis_client.py#L19), `scripts Lua`.

**À expliquer :** Redis exécute chaque script sans intercaler une autre commande : la lecture, le choix des champs et l’écriture forment une seule opération. Ils préservent le prix plus récent et complètent certains champs absents. Les dates sont comparées comme des chaînes : leur format doit rester cohérent.

**Prompt reconstitué :** « Explique pourquoi les deux scripts Lua comparent et fusionnent les cours directement dans Redis. »

### IA-11 — Conversion des devises et cache des taux

**Emplacement :** [portfolio/exchange_rates.py](portfolio/exchange_rates.py#L59), `get_usd_rate`.

**À expliquer :** normalize_currency convertit notamment GBp en GBP avec un facteur 0,01. Un verrou asyncio par devise protège le cache local : taux gardé une heure, pause de 60 s après erreur. parse_rate refuse un taux incohérent ou trop ancien.

**Prompt reconstitué :** « Explique comment convertir en USD, gérer les prix en pence et éviter des appels identiques au service de change. »

### IA-12 — Mise à jour partielle du portefeuille

**Emplacement :** [portfolio/repository.py](portfolio/repository.py#L201), `update_user_portfolio`.

**À expliquer :** exclude_unset conserve uniquement les champs fournis. Un champ absent reste inchangé ; une liste vide efface les préférences correspondantes. Le code remplace les lignes de liaison puis valide la transaction.

**Prompt reconstitué :** « Explique comment modifier seulement les champs envoyés et remplacer les préférences sans doublons. »

### IA-13 — Valorisation de plusieurs portefeuilles

**Emplacement :** [portfolio/repository.py](portfolio/repository.py#L423), `read_user_asset_value`.

**À expliquer :** Le dictionnaire regroupe quantités et montants investis par actif sur les portefeuilles de l’utilisateur. gather récupère les prix de manière concurrente. Si un prix manque, le total actuel reste inconnu plutôt que partiellement calculé.

**Prompt reconstitué :** « Explique comment regrouper les positions d’un même actif et calculer leur valeur totale. »

### IA-14 — Prix serveur et enregistrement des opérations

**Emplacement :** [portfolio/repository.py](portfolio/repository.py#L582), `buy_asset`.

**À expliquer :** Le prix exécuté vient du backend, même si la demande d’achat contient purchase_price. Decimal sert aux montants enregistrés. L’achat débite le compte, la vente le crédite ; save_portfolio_transaction valide aussi la position et l’historique dans le même commit.

**Prompt reconstitué :** « Explique comment le serveur choisit le prix en USD et enregistre ensemble le solde, la position et l’historique. »

### IA-15 — Verrouillage du compte lors d’un dépôt

**Emplacement :** [portfolio/repository.py](portfolio/repository.py#L988), `deposit_cash`.

**À expliquer :** Le SELECT verrouille la ligne du compte jusqu’à la fin de la transaction. Les autres écritures concurrentes sur cette ligne doivent attendre. Le dépôt et la hausse du solde sont validés ensemble ; ce verrou se trouve ici dans deposit_cash.

**Prompt reconstitué :** « Explique pourquoi le dépôt utilise with_for_update avant de modifier le solde. »

### IA-16 — Historique paginé et compteurs par actif

**Emplacement :** [portfolio/repository.py](portfolio/repository.py#L896), `read_transactions`.

**À expliquer :** offset/limit ne prennent qu’une page. La seconde requête parcourt l’historique du portefeuille : GROUP BY rassemble les opérations par actif, CASE et SUM comptent séparément achats et ventes.

**Prompt reconstitué :** « Explique la différence entre la page de transactions et les compteurs regroupés par actif. »

### IA-17 — Filtres SQL, favoris et pagination

**Emplacement :** [routers/assets.py](routers/assets.py#L234), `list_assets`.

**À expliquer :** Les filtres SQL sont appliqués avant le comptage et la pagination. Les sous-requêtes sélectionnent niches et types spécialisés sans multiplier les lignes. CASE place les favoris en premier, puis un tri stable précède offset/limit.

**Prompt reconstitué :** « Explique comment combiner les filtres, placer les favoris en premier et paginer les actifs. »

### IA-18 — Lecture concurrente des cours pour une page

**Emplacement :** [routers/assets.py](routers/assets.py#L160), `add_market_information`.

**À expliquer :** gather fait avancer les lectures Redis ensemble. Le dictionnaire rattache chaque cours à son symbole. Un cours absent laisse les informations de marché manquantes ; cette fonction ne contacte pas Yahoo.

**Prompt reconstitué :** « Explique comment compléter les actifs affichés avec Redis sans refaire des appels à Yahoo. »

### IA-19 — Actualités liées à un actif

**Emplacement :** [routers/assets.py](routers/assets.py#L504), `get_asset_news`.

**À expliquer :** La requête suit les clés entre ClassificationAsset, SourceClassification et DataSource. DISTINCT évite de répéter un article lié par plusieurs classifications ; la pagination s’applique aux sources ainsi trouvées.

**Prompt reconstitué :** « Explique comment retrouver les actualités d’un actif sans chercher son nom dans les articles. »

### IA-20 — Demande d’analyse sans doublon

**Emplacement :** [routers/portfolios.py](routers/portfolios.py#L578), `request_portfolio_strategist_review`.

**À expliquer :** _owned_strategist vérifie le lien avec l’utilisateur et verrouille la ligne. La route réutilise une analyse complète pending/running ou en met une en attente ; HTTP 202 signifie acceptée, pas terminée. Le traitement IA est réalisé ailleurs.

**Prompt reconstitué :** « Explique comment vérifier le propriétaire et éviter de créer deux demandes d’analyse du même portefeuille. »

### IA-21 — Ajout d’un favori sans doublon

**Emplacement :** [routers/favorites.py](routers/favorites.py#L24), `add_favorite`.

**À expliquer :** on_conflict_do_nothing utilise l’unicité du couple utilisateur/actif. Si le favori existe, PostgreSQL ignore l’ajout au lieu de créer un doublon ; l’utilisateur vient du jeton.

**Prompt reconstitué :** « Explique comment gérer deux demandes d’ajout du même favori sans erreur. »
