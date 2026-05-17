import json
import httpx
from datetime import datetime
from channels.email.handler import EmailHandler
from config.settings import settings
from utils.logger import logger


class HumanNotifier:
    def __init__(self):
        self._email = EmailHandler()

    async def notify_handoff(
        self,
        prospect: dict,
        reason: str,
        urgency: str = "medium",
        context: dict | None = None,
    ) -> None:
        urgency_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴", "critical": "🚨"}.get(urgency, "🟡")

        subject = f"{urgency_emoji} [Handoff {urgency.upper()}] {prospect.get('full_name')} — {prospect.get('company', 'Unknown')}"

        body_lines = [
            f"Un prospect est prêt pour un contact humain.",
            "",
            f"NOM: {prospect.get('full_name')}",
            f"ENTREPRISE: {prospect.get('company', 'N/A')}",
            f"TITRE: {prospect.get('title', 'N/A')}",
            f"EMAIL: {prospect.get('email', 'N/A')}",
            f"CANAL SOURCE: {prospect.get('source_channel', 'N/A')}",
            f"SCORE: {prospect.get('score', 'N/A')}/100",
            "",
            f"RAISON DU HANDOFF:",
            reason,
            "",
        ]

        if context:
            if context.get("signals"):
                body_lines += ["SIGNAUX D'ACHAT DÉTECTÉS:"] + [f"  • {s}" for s in context["signals"]] + [""]
            if context.get("talking_points"):
                body_lines += ["POINTS DE DISCUSSION RECOMMANDÉS:"] + [f"  • {p}" for p in context["talking_points"]] + [""]
            if context.get("recommended_action"):
                body_lines += [f"ACTION RECOMMANDÉE: {context['recommended_action']}", ""]
            if context.get("risk_of_loss"):
                body_lines += [f"RISQUE DE PERTE SI PAS CONTACTÉ: {context['risk_of_loss'].upper()}", ""]

        body_lines += [
            f"Horodatage: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "— Agent de Prospection Autonome",
        ]

        body = "\n".join(body_lines)
        await self._email.send_email(settings.human_alert_email, subject, body)
        await self._send_webhook({"type": "handoff", "urgency": urgency, "prospect": prospect, "reason": reason})
        logger.info(f"[Notifier] Handoff notification sent for {prospect.get('full_name')} (urgency={urgency})")

    async def notify_daily_summary(self, stats: dict) -> None:
        subject = f"📊 Résumé Quotidien — {datetime.utcnow().strftime('%d/%m/%Y')}"

        lines = [
            "RÉSUMÉ DE L'ACTIVITÉ DES AGENTS (dernières 24h)",
            "",
            f"Prospects découverts:    {stats.get('discovered', 0)}",
            f"Prospects qualifiés:     {stats.get('qualified', 0)}",
            f"Messages envoyés:        {stats.get('contacted', 0)}",
            f"Réponses reçues:         {stats.get('responding', 0)}",
            f"Handoffs vers humains:   {stats.get('handoff', 0)}",
            f"Convertis/Rejetés:       {stats.get('rejected', 0)}",
            "",
            f"Taux de réponse:         {stats.get('response_rate', '0')}%",
            f"Score moyen ICP:         {stats.get('avg_score', '0')}/100",
            "",
            f"Rapport généré: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        ]

        await self._email.send_email(settings.human_alert_email, subject, "\n".join(lines))
        logger.info("[Notifier] Daily summary sent")

    async def _send_webhook(self, payload: dict) -> None:
        if not settings.webhook_url:
            return

        slack_payload = {
            "text": f"*[{payload.get('type', 'alert').upper()}]* {payload.get('prospect', {}).get('full_name', 'Unknown')} — {payload.get('reason', '')}",
            "attachments": [{"color": {"low": "good", "medium": "warning", "high": "danger", "critical": "danger"}.get(payload.get("urgency", "medium"), "warning")}],
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(settings.webhook_url, json=slack_payload)
        except Exception as e:
            logger.warning(f"[Notifier] Webhook failed: {e}")
