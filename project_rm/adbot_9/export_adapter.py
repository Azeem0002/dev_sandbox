"""Campaign export adapter for adbot_9."""

from __future__ import annotations

try:
    from .models import CampaignPlan, ExportedCampaign
except ImportError:
    from models import CampaignPlan, ExportedCampaign


# ============================================
# Export adapter - reusable mental map
# ============================================

# ============================================
# Shared private skeleton - start reading here
# ============================================
def _format_money(value: float) -> str:
    """Format a budget number for plain-text campaign notes."""
    return f"{value:,.2f}"


def _format_signal_rows(plan: CampaignPlan) -> str:
    """Build the demand-signal section of the export."""
    lines = []
    for signal in plan.demand_signals:
        location = signal.city or signal.region
        lines.append(f"- {location}: {signal.score:.1f}/100 via {signal.source.value} | {signal.query} | {signal.search_url}")
    return "\n".join(lines)


def _format_creative_rows(plan: CampaignPlan) -> str:
    """Build the ad-copy section of the export."""
    lines = []
    for creative in plan.creatives:
        location = creative.city or plan.region
        lines.append(
            "\n".join(
                [
                    f"## {location}",
                    f"Headline: {creative.headline}",
                    f"Primary text: {creative.primary_text}",
                    f"CTA: {creative.call_to_action}",
                    f"Landing page: {creative.landing_page_hint}",
                ]
            )
        )
    return "\n\n".join(lines)


def _build_campaign_export(plan: CampaignPlan) -> str:
    """Build copyable campaign notes for a human ad launch."""
    return "\n".join(
        [
            f"# AdBot Campaign Plan: {plan.product}",
            "",
            f"Plan ID: {plan.id}",
            f"Region: {plan.region}",
            f"Platform: {plan.platform.value}",
            f"Goal: {plan.goal.value}",
            f"Audience: {plan.audience}",
            f"Daily budget: {_format_money(plan.daily_budget)}",
            "",
            "## Safety",
            "This MVP prepares ad strategy and copy. Launch manually inside the ad platform after checking policy, targeting, billing, and landing page claims.",
            "",
            "## Demand Signals",
            _format_signal_rows(plan),
            "",
            "## Campaign Copy",
            _format_creative_rows(plan),
        ]
    )


# ============================================
# Public adapter API - stable reusable surface
# ============================================
def export_campaign_plan(plan: CampaignPlan) -> ExportedCampaign:
    """Return a plain-text export for one campaign plan."""
    return ExportedCampaign(plan_id=plan.id, content=_build_campaign_export(plan))
