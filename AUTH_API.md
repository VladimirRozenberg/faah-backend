# Authentication changes

New access tokens expire after **60 seconds**. Existing tokens retain the expiry
encoded when they were issued. There is no refresh-token endpoint; clients must
sign in again when the token expires.

Send `Authorization: Bearer <token>` to every protected endpoint below. Login
(`POST /auth/login`) stays public so a client can obtain its first token.
Missing bearer credentials return 403 with the existing HTTPBearer behavior;
invalid or expired tokens and disabled accounts return 401.

## Personal account and portfolio routes

The server obtains the account ID from `CurrentUser`, validated from the token.
Replace `/api/users/{uid}/...` with `/api/users/me/...` in the client. Numeric user
paths have been removed. Supplied `uid` or `user_id` query parameters do not select
another account. Portfolio IDs still identify the portfolio, and the server
checks that it belongs to the authenticated user.

| Method | Path |
| --- | --- |
| GET | `/auth/me` |
| PUT | `/auth/me/password` |
| GET | `/api/users/me/portfolios` |
| GET, PATCH | `/api/users/me/portfolios/{pid}` |
| POST | `/api/users/me/portfolio/create` |
| GET | `/api/users/me/portfolio` |
| GET | `/api/users/me/portfolios/{pid}/transactions` |
| GET | `/api/users/me/portfolios/{pid}/recommendations` |
| GET | `/api/users/me/recommendations` |
| GET | `/api/users/me/available-cash` |
| GET | `/api/users/me/asset-value` |
| POST | `/api/users/me/portfolios/{pid}/assets/buy` |
| POST | `/api/users/me/portfolios/{pid}/assets/sell` |

Related personal routes follow the same rule:
`/api/users/me/portfolio/assets/buy`, `/api/users/me/portfolio/assets/sell`, and
`/api/users/me/portfolio/transactions`, as well as portfolio `/strategist` and
`/strategist/reviews` (GET/POST).

## Shared routes requiring a valid token

| Method | Path |
| --- | --- |
| GET | `/health` |
| GET | `/health/external` |
| GET | `/api/assets` |
| GET | `/api/assets/{symbol}/market` |
| GET | `/api/assets/{symbol}/usd-quote` |
| GET | `/api/assets/{symbol}/candles` |
| GET | `/api/assets/{symbol}/news` |
| GET | `/api/history-options` |
| GET | `/api/niches` |
| GET | `/api/favorites` |
| POST, PUT, DELETE | `/api/favorites/{assetId}` |
| GET | `/api/data-sources` |
| GET | `/api/data-sources/{id}` |
| GET | `/api/orchestrator/decisions` |

Favorites already use the token's account ID. POST is now supported alongside the
existing PUT for adding a favorite, matching the reported client call.

## Administration

These routes retain their existing authenticated admin-role dependency. The ID
in the path identifies the **target account**, so it remains in the URL. The
acting administrator's ID comes from the token.

| Method | Path |
| --- | --- |
| GET | `/admin/utilisateurs` |
| PUT | `/admin/utilisateurs/{id}/role` |
| PUT | `/admin/utilisateurs/{id}/statut` |
| POST | `/admin/utilisateurs/{id}/deposit` |
| POST | `/admin/utilisateurs` (create a user) |

The backend password route is PUT. The Avalonia files `SettingsView.axaml.cs`,
`AssetListViewModel`, and `UserCreateViewModel` are absent from this workspace, so
frontend method/path changes must be applied in that project.

## Validation

HTTP integration coverage checks all listed protected routes against missing,
invalid, and expired tokens; login and its 60-second expiry; token-derived account
identity; rejection of another user's portfolio for reads, updates, trades, and
strategist reviews; disabled accounts; and admin-only access with target-account
deposits. Existing portfolio, asset-news, and orchestration tests use the updated
paths or an explicit authenticated-user dependency override.

Run the suite with a dummy key for the existing LLM client's import-time setup:

```sh
FAAH_API_KEY=test-placeholder .venv/bin/python -m unittest discover -s tests
```
