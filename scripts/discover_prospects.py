"""
Découverte automatique de prospects investisseurs/entrepreneurs sur Twitter/X.
Recherche des profils FR correspondant à l'ICP d'un tenant, les importe
en base comme Prospect(status='discovered').

Usage:
    python scripts/discover_prospects.py --tenant-id <UUID> --campaign-id <UUID> --limit 100
"""
import argparse
import asyncio
import uuid as uuid_lib
import sys
import time

sys.path.insert(0, "/app")


SEARCH_QUERIES = [
    # Bio-keyword searches — utilisateurs FR se décrivant comme investisseurs/entrepreneurs
    "(investisseur OR business\ angel OR \"gestion de patrimoine\") lang:fr",
    "(entrepreneur OR fondateur OR \"chef d'entreprise\") (investissement OR patrimoine OR placements) lang:fr",
    "(CEO OR PDG OR dirigeant) (bourse OR immobilier OR capital) lang:fr",
    "(startup OR scale-up) (levée de fonds OR investisseur OR financement) lang:fr",
    "(\"family office\" OR \"wealth management\" OR patrimoine) lang:fr",
]

# Mots-clés exclusion (comptes de médias, bots, spammeurs)
EXCLUDE_TERMS = ["bot", "crypto pump", "forex signal", "gagnez", "revenus passifs faciles"]

# Minimums pour filtrer les comptes peu actifs
MIN_FOLLOWERS = 100
MIN_TWEETS = 50
MAX_FOLLOWING_RATIO = 20  # following/followers — évite les comptes spam


def _is_quality_account(user) -> bool:
    """Filtre basique de qualité pour éviter bots et comptes inactifs."""
    if not user.public_metrics:
        return False
    followers = user.public_metrics.get("followers_count", 0)
    following = user.public_metrics.get("following_count", 1)
    tweet_count = user.public_metrics.get("tweet_count", 0)

    if followers < MIN_FOLLOWERS:
        return False
    if tweet_count < MIN_TWEETS:
        return False
    ratio = following / max(followers, 1)
    if ratio > MAX_FOLLOWING_RATIO:
        return False

    bio = (user.description or "").lower()
    for excl in EXCLUDE_TERMS:
        if excl.lower() in bio:
            return False

    return True


def _extract_name_title(user) -> tuple[str, str | None]:
    """Extrait nom et titre approximatif depuis le nom et la bio Twitter."""
    name = user.name or f"@{user.username}"
    bio = user.description or ""

    title = None
    title_keywords = [
        "CEO", "PDG", "fondateur", "co-fondateur", "investisseur", "business angel",
        "entrepreneur", "dirigeant", "président", "directeur", "DAF", "CFO",
        "gestion de patrimoine", "conseiller", "consultant",
    ]
    bio_lower = bio.lower()
    for kw in title_keywords:
        if kw.lower() in bio_lower:
            title = kw
            break

    return name, title


async def discover_and_import(tenant_id: str, campaign_id: str, limit: int = 100):
    import tweepy
    from config.settings import settings
    from crm.database import async_session_factory
    from crm.models import Prospect
    from sqlalchemy import select

    client = tweepy.Client(
        bearer_token=settings.x_api_bearer_token,
        consumer_key=settings.x_api_key,
        consumer_secret=settings.x_api_secret,
        access_token=settings.x_access_token,
        access_token_secret=settings.x_access_token_secret,
        wait_on_rate_limit=True,
    )

    tenant_uuid = uuid_lib.UUID(tenant_id)
    campaign_uuid = uuid_lib.UUID(campaign_id)

    collected: list[dict] = []
    seen_usernames: set[str] = set()

    # Récupérer les handles déjà en base pour ce tenant (éviter doublons)
    async with async_session_factory() as session:
        existing = await session.execute(
            select(Prospect.twitter_handle).where(Prospect.tenant_id == tenant_uuid)
        )
        for (handle,) in existing.fetchall():
            if handle:
                seen_usernames.add(handle.lstrip("@").lower())

    print(f"[Discovery] {len(seen_usernames)} prospects déjà en base — début de la recherche")

    for query in SEARCH_QUERIES:
        if len(collected) >= limit:
            break

        print(f"[Discovery] Requête: {query[:80]}...")
        try:
            # Recherche de tweets récents correspondant à la requête
            tweets_resp = client.search_recent_tweets(
                query=query + " -is:retweet -is:reply",
                max_results=100,
                expansions=["author_id"],
                user_fields=["name", "username", "description", "public_metrics", "location", "url"],
            )

            if not tweets_resp or not tweets_resp.includes or "users" not in tweets_resp.includes:
                print(f"[Discovery] Aucun résultat pour cette requête")
                time.sleep(2)
                continue

            users = tweets_resp.includes["users"]
            print(f"[Discovery] {len(users)} utilisateurs trouvés")

            for user in users:
                if len(collected) >= limit:
                    break

                username = user.username.lower()
                if username in seen_usernames:
                    continue
                if not _is_quality_account(user):
                    continue

                seen_usernames.add(username)
                name, title = _extract_name_title(user)

                collected.append({
                    "id": uuid_lib.uuid4(),
                    "tenant_id": tenant_uuid,
                    "name": name,
                    "title": title,
                    "company": None,
                    "email": None,
                    "twitter_handle": f"@{user.username}",
                    "linkedin_url": None,
                    "instagram_handle": None,
                    "tiktok_handle": None,
                    "score": 0.0,
                    "status": "discovered",
                    "_bio": user.description or "",
                    "_followers": user.public_metrics.get("followers_count", 0) if user.public_metrics else 0,
                    "_location": getattr(user, "location", "") or "",
                })

        except tweepy.errors.TooManyRequests:
            print("[Discovery] Rate limit atteint — pause 60s")
            time.sleep(60)
        except tweepy.errors.TwitterServerError as e:
            print(f"[Discovery] Erreur serveur Twitter: {e}")
            time.sleep(10)
        except Exception as e:
            print(f"[Discovery] Erreur inattendue: {e}")
            time.sleep(5)

    if not collected:
        print("[Discovery] ATTENTION: aucun prospect trouvé — vérifier les credentials Twitter")
        return 0

    # Import en base
    print(f"\n[Discovery] Import de {len(collected)} prospects en base...")
    async with async_session_factory() as session:
        imported = 0
        for p in collected:
            bio = p.pop("_bio", "")
            p.pop("_followers", 0)
            p.pop("_location", "")

            prospect = Prospect(**p)
            session.add(prospect)
            imported += 1

            if imported % 20 == 0:
                await session.flush()
                print(f"[Discovery] {imported}/{len(collected)} importés...")

        await session.commit()

    print(f"\n[Discovery] DONE — {imported} prospects importés pour tenant {tenant_id}")
    return imported


def main():
    parser = argparse.ArgumentParser(description="Découverte de prospects Twitter/X")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    count = asyncio.run(discover_and_import(args.tenant_id, args.campaign_id, args.limit))
    print(f"[Discovery] {count} prospects prêts au drafting")
    sys.exit(0 if count > 0 else 1)


if __name__ == "__main__":
    main()
