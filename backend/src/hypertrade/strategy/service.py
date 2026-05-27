from typing import Any

from sqlalchemy import desc, select

from hypertrade.db import Database, StrategyResearch
from hypertrade.strategy.sdk import StrategySpec, builtin_strategy_spec


class StrategyResearchService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, prompt: str) -> dict[str, Any]:
        spec = builtin_strategy_spec()
        markdown = _render_research_markdown(prompt, spec)
        with self.db.session() as session:
            research = StrategyResearch(
                prompt=prompt,
                strategy_key=spec.key,
                title=spec.title,
                report_markdown=markdown,
                spec_json={
                    "key": spec.key,
                    "title": spec.title,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            )
            session.add(research)
            session.flush()
            return _research_to_dict(research)

    def latest(self) -> dict[str, Any] | None:
        with self.db.session() as session:
            research = session.scalar(
                select(StrategyResearch).order_by(desc(StrategyResearch.created_at)).limit(1)
            )
            return _research_to_dict(research) if research else None

    def list_recent(self, *, limit: int = 10) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(StrategyResearch).order_by(desc(StrategyResearch.created_at)).limit(limit)
            ).all()
            return [_research_to_dict(row) for row in rows]

    def get(self, research_id: str) -> dict[str, Any] | None:
        with self.db.session() as session:
            research = session.get(StrategyResearch, research_id)
            return _research_to_dict(research) if research else None


def _render_research_markdown(prompt: str, spec: StrategySpec) -> str:
    return "\n".join(
        [
            f"# {spec.title}",
            "",
            f"**Strategy Key**: `{spec.key}`",
            "",
            "## 研究假设",
            f"- 用户研究问题：{prompt}",
            "- 趋势行情中，突破短期均线可能代表短线动量延续。",
            "- 回测结果只用于研究流程演示，不构成投资建议。",
            "",
            "## 参数",
            *[f"- {key}: {value}" for key, value in spec.parameters.items()],
        ]
    )


def _research_to_dict(research: StrategyResearch) -> dict[str, Any]:
    return {
        "id": research.id,
        "prompt": research.prompt,
        "strategy_key": research.strategy_key,
        "title": research.title,
        "report_markdown": research.report_markdown,
        "spec_json": research.spec_json,
        "created_at": research.created_at.isoformat(),
    }
