"""
Découverte de prospects investisseurs/entrepreneurs FR via DuckDuckGo → LinkedIn.
Recherche des profils publics LinkedIn correspondant à l'ICP,
les importe en base comme Prospect(status='discovered').

Usage:
    python scripts/discover_linkedin.py --tenant-id <UUID> --campaign-id <UUID> --limit 100
"""
import argparse
import asyncio
import re
import time
import uuid as uuid_lib
import sys

sys.path.insert(0, "/app")

SEARCH_QUERIES = [
    "site:linkedin.com/in investisseur France",
    "site:linkedin.com/in business angel France",
    "site:linkedin.com/in entrepreneur gestion patrimoine France",
    "site:linkedin.com/in fondateur investissement France",
    "site:linkedin.com/in dirigeant investissements financiers France",
    "site:linkedin.com/in family office France",
    "site:linkedin.com/in investisseur immobilier France",
    "site:linkedin.com/in capital risque France",
    "site:linkedin.com/in business angel startup France",
    "site:linkedin.com/in conseiller en gestion de patrimoine France",
    "site:linkedin.com/in PDG investisseur France",
    "site:linkedin.com/in fondateur CEO levee fonds France",
]

LI_URL_RE = re.compile(r"linkedin\.com/in/([a-zA-Z0-9\-_%]+)")


def _extract_profile(result: dict) -> dict | None:
    """Transforme un résultat DuckDuckGo en données prospect structurées."""
    href = result.get("href", "")
    title = result.get("title", "")
    body = result.get("body", "")

    m = LI_URL_RE.search(href)
    if not m:
        return None

    slug = m.group(1)
    linkedin_url = f"https://www.linkedin.com/in/{slug}"

    # Format LinkedIn title: "Prénom NOM - Titre | Entreprise | LinkedIn"
    name = title.split(" - ")[0].strip() if " - " in title else title.split("|")[0].strip()
    name = re.sub(r"\s*\|\s*LinkedIn\s*$", "", name).strip()
    name = re.sub(r"\s*-\s*LinkedIn\s*$", "", name).strip()

    if not name or len(name) < 3:
        return None

    job_title = None
    company = None

    parts = title.split(" - ", 1)
    if len(parts) > 1:
        rest = parts[1]
        sub_parts = [p.strip() for p in rest.split("|")]
        if sub_parts:
            raw_title = re.sub(r"\s*LinkedIn\s*$", "", sub_parts[0]).strip()
            # Stop at first newline or ellipsis — avoid concatenated entries
            raw_title = re.split(r"[.\n]|\.\.\.", raw_title)[0].strip()
            job_title = raw_title[:120] if raw_title else None
        if len(sub_parts) > 1:
            raw_company = re.sub(r"\s*LinkedIn\s*$", "", sub_parts[1]).strip()
            raw_company = re.split(r"[.\n]|\.\.\.", raw_company)[0].strip()
            company = raw_company[:120] if raw_company else None

    if not job_title and body:
        for kw in ["investisseur", "entrepreneur", "fondateur", "business angel", "dirigeant",
                   "CEO", "PDG", "directeur", "consultant", "gestionnaire de patrimoine", "CGP"]:
            if kw.lower() in body.lower():
                job_title = kw.capitalize()
                break

    return {
        "name": name[:255],
        "title": job_title[:255] if job_title else None,
        "company": company[:255] if company else None,
        "linkedin_url": linkedin_url[:500],
    }


async def discover_and_import(tenant_id: str, campaign_id: str, limit: int = 100):
    from ddgs import DDGS
    from crm.database import async_session_factory
    from crm.models import Prospect
    from sqlalchemy import select

    tenant_uuid = uuid_lib.UUID(tenant_id)

    # Profils déjà en base pour ce tenant
    async with async_session_factory() as session:
        existing_q = await session.execute(
            select(Prospect.linkedin_url).where(Prospect.tenant_id == tenant_uuid)
        )
        seen_urls: set[str] = {row[0] for row in existing_q.fetchall() if row[0]}

    print(f"[Discovery] {len(seen_urls)} prospects déjà en base — début de la recherche")

    collected: list[dict] = []
    ddgs = DDGS()

    for query in SEARCH_QUERIES:
        if len(collected) >= limit:
            break

        print(f"[Discovery] Requête: {query[:75]}...")
        try:
            results = list(ddgs.text(query, max_results=15))
            found_in_query = 0

            for r in results:
                if len(collected) >= limit:
                    break
                profile = _extract_profile(r)
                if not profile:
                    continue
                if profile["linkedin_url"] in seen_urls:
                    continue
                seen_urls.add(profile["linkedin_url"])
                collected.append(profile)
                found_in_query += 1

            print(f"[Discovery] → {found_in_query} nouveaux profils ({len(collected)} total)")
            time.sleep(3)  # Respecter les rate limits DDG

        except Exception as e:
            print(f"[Discovery] Erreur: {e} — pause 8s")
            time.sleep(8)

    if not collected:
        print("[Discovery] Aucun prospect trouvé")
        return 0

    # Import en base
    print(f"\n[Discovery] Import de {len(collected)} prospects en base...")
    async with async_session_factory() as session:
        imported = 0
        for p in collected:
            prospect = Prospect(
                id=uuid_lib.uuid4(),
                tenant_id=tenant_uuid,
                name=p["name"],
                title=p["title"],
                company=p["company"],
                email=None,
                linkedin_url=p["linkedin_url"],
                twitter_handle=None,
                score=0.0,
                status="discovered",
            )
            session.add(prospect)
            imported += 1

            if imported % 25 == 0:
                await session.flush()
                print(f"[Discovery] {imported}/{len(collected)} importés...")

        await session.commit()

    print(f"\n[Discovery] DONE — {imported} prospects importés pour tenant {tenant_id}")
    return imported


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    count = asyncio.run(discover_and_import(args.tenant_id, args.campaign_id, args.limit))
    sys.exit(0 if count > 0 else 1)


if __name__ == "__main__":
    main()
