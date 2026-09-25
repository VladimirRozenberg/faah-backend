# Compléter temporairement les logos

Le script `assets/backfill_logos.py` parcourt les actifs sans logo, même si aucune nouvelle actualité ne les mentionne. Il ne crée ni actif ni classification et ne touche pas aux logos existants. Le traitement automatique reste en place.

## Lancement sur le serveur qui héberge la base

Après avoir transféré/déployé ce fichier dans le backend du cloud, ouvrir un terminal dans le dossier contenant `docker-compose.yml` :

```bash
docker compose exec app python -u -m assets.backfill_logos --hours 3
```

Le fichier doit être présent dans le conteneur `app` (volume du projet ou image reconstruite selon votre déploiement). Lancer depuis la copie Windows ne met pas à jour le cloud. Aucune clé à coller dans la commande : le script utilise `TWELVE_DATA_API_KEY` déjà configurée dans le conteneur.

Garder le terminal ouvert. `Ctrl+C` arrête le script ; les logos validés sont conservés. Il s'arrête aussi au bout de trois heures, ou lorsqu'aucun actif n'est éligible. Rien à remettre en place ensuite : l'automatisation n'a pas été remplacée.

## Limites importantes

- Un actif traité toutes les dix secondes au plus ; mêmes limites partagées que le code existant (7 tentatives/minute et 750/24 heures). Les autres programmes utilisant la même clé Twelve Data ne sont pas comptabilisés par ces limites locales.
- Aucun contournement des 24 heures d'attente après une tentative. Un actif en échec aujourd'hui ne sera pas immédiatement retenté, mais les actifs jamais essayés sont prioritaires.
- Pas de garantie de logo pour tous les symboles. Les futures sont exclus ; les initiales restent affichées pour les logos manquants.
- Une erreur de base arrête le script ; les transactions précédentes restent validées. Aucun changement du schéma SQL.
- Une fois les logos ajoutés, actualiser la liste Avalonia. En cas d'échec d'image déjà mis en cache, attendre deux minutes puis actualiser, ou relancer l'application.

Tests isolés (aucun appel réel ni écriture en production) :

```bash
python -m unittest discover -s tests -p test_backfill_logos.py -v
```
