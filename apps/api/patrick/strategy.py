import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .schemas import STRATEGY_IDS


class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    lookback: int = Field(ge=3, le=60)
    threshold: float = Field(gt=0, le=0.1)
    max_allocation: float = Field(gt=0, le=0.95)
    rebalance_threshold: float = Field(gt=0, le=0.1)


class Strategy(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    name: str
    description: str
    markdown: str
    version: str
    config: StrategyConfig


def load_strategies() -> dict[str, Strategy]:
    result = {}
    for strategy_id in STRATEGY_IDS:
        markdown = (Path(__file__).parent / "strategies" / f"{strategy_id}.md").read_text()
        matches = re.findall(r"```json\s*(.*?)\s*```", markdown, re.DOTALL)
        if len(matches) != 1:
            raise ValueError(f"Strategy {strategy_id} requires exactly one JSON configuration block")
        result[strategy_id] = Strategy(
            id=strategy_id,
            name=markdown.splitlines()[0].removeprefix("# "),
            description=" ".join(markdown.split("```", 1)[0].splitlines()[2:]).strip(),
            markdown=markdown,
            version=hashlib.sha256(markdown.encode()).hexdigest(),
            config=StrategyConfig.model_validate(json.loads(matches[0])),
        )
    return result
