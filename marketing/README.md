# Marketing Automation — LuxuryWeb SaaS

**Produit**: SaaS de mise en relation premium (startups ↔ services privilégiés)
**Cible**: Startups Series A/B, scale-ups 50-500 employés
**Ticket**: 5 000€ - 20 000€/an
**Canaux**: LinkedIn · Email Cold · Instagram · TikTok

## Structure

| Dossier | Contenu |
|---|---|
| `outreach/` | ICP, séquences LinkedIn & Email, scoring |
| `linkedin/` | Calendrier éditorial 30j, templates, stratégie commentaires |
| `social-media/` | Stratégie TikTok + Instagram, scripts vidéo, calendrier |
| `campaigns/` | Configurations JSON pour les agents autonomes |
| `templates/` | Templates réutilisables tous canaux |

## Démarrage rapide

### 1. Lancer la première campagne (agents autonomes)
```bash
# Démarrer les services
docker-compose up -d

# Créer la campagne via l'API
curl -X POST http://localhost:8000/campaigns \
  -H "Content-Type: application/json" \
  -d @marketing/campaigns/campaign-01-startup-founders.json

# Déclencher le premier cycle complet
curl -X POST http://localhost:8000/agents/run/full \
  -H "Content-Type: application/json" \
  -d '{"campaign_id": 1}'
```

### 2. Monitorer l'activité
- **API Dashboard**: http://localhost:8000/docs
- **Celery Flower**: http://localhost:5555
- **Stats en temps réel**: http://localhost:8000/agents/stats

### 3. Gérer les handoffs humains
```bash
# Voir les prospects prêts pour contact humain
curl http://localhost:8000/handoffs

# Marquer comme traité
curl -X POST http://localhost:8000/handoffs/{id}/resolve
```
