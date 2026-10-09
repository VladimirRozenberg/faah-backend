# Utilisation de l’IA — Laura

## Périmètre de travail
Je me suis principalement occupée des parties admin et auth du backend.
J’ai utilisé l’IA pour adapter le code et vérifier certains comportements.
Les demandes concernaient les comptes, les mots de passe et la connexion.

## Limitation des tentatives de connexion
J’ai demandé l’ajout d’une limitation sur la route de connexion.
La règle souhaitée était de compter les échecs par IP et identifiant.
Après cinq échecs, les tentatives suivantes doivent retourner 429.
La fenêtre de suivi des échecs est de cinq minutes.
Une connexion réussie doit effacer les échecs précédents.

## Validation des mots de passe
J’ai demandé une règle commune pour les trois opérations suivantes :
- création publique d’un compte ;
- création d’un utilisateur par un administrateur ;
- changement du mot de passe.
Le mot de passe doit contenir au moins huit caractères.
Il ne doit pas dépasser 72 octets une fois encodé en UTF-8.
J’ai finalement demandé au moins un chiffre, sans majuscule ni caractère spécial obligatoire.
J’ai demandé l’adaptation des tests à cette règle définitive.

## Validation de la création par un administrateur
J’ai demandé de réutiliser les règles existantes du nom d’utilisateur.
L’adresse e-mail doit être validée avec le type EmailStr.
Le rôle doit obligatoirement être admin ou employe.

## Relecture et corrections
J’ai demandé une vérification des parties admin et auth.
J’ai demandé des explications sur les problèmes et leur comportement antérieur.
J’ai validé la correction des mots de passe trop longs à la connexion.
J’ai validé la gestion des identifiants JWT mal formés.
J’ai validé le remplacement des compteurs en mémoire par Redis.
L’IA a ajouté des tests et actualisé la documentation.
Les 24 tests exécutés ont réussi, dont ceux utilisant Redis.
