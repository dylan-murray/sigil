from dataclasses import dataclass, field


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    calls: int = 0
    cost_usd: float = 0.0
    by_model: dict[str, "TokenUsage"] = field(default_factory=dict)

    def record(
        self,
        model: str,
        prompt_tok: int,
        completion_tok: int,
        cache_read_tok: int,
        cache_creation_tok: int,
        call_cost: float,
    ) -> None:
        self.prompt_tokens += prompt_tok
        self.completion_tokens += completion_tok
        self.cache_read_tokens += cache_read_tok
        self.cache_creation_tokens += cache_creation_tok
        self.calls += 1
        self.cost_usd += call_cost

        if model not in self.by_model:
            self.by_model[model] = TokenUsage()
        m = self.by_model[model]
        m.prompt_tokens += prompt_tok
        m.completion_tokens += completion_tok
        m.cache_read_tokens += cache_read_tok
        m.cache_creation_tokens += cache_creation_tok
        m.calls += 1
        m.cost_usd += call_cost


@dataclass
class CallTrace:
    timestamp: str
    label: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_usd: float
    task: str | None = None
    content: str | None = None
