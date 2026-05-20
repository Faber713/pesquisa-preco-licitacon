from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class SearchResult:
    fonte: str
    descricao: str
    valor_unitario: float = 0.0
    unidade: str = ""
    fornecedor: str = ""
    orgao: str = ""
    data: str = ""
    score: float = 0.0
    url: str = ""
    metadados: dict = field(default_factory=dict)

    def to_dict(self):
        dados = asdict(self)
        dados["valor"] = self.valor_unitario
        dados["link_origem"] = self.url
        return dados


def item_valido(item):
    if item is None:
        return False
    if isinstance(item, SearchResult):
        return item.score > 0 and not item.metadados.get("item_descartado")
    score = item.get("score", 0) if isinstance(item, dict) else getattr(item, "score", 0)
    descartado = (
        item.get("item_descartado", False)
        if isinstance(item, dict)
        else getattr(item, "item_descartado", False)
    )
    try:
        score = float(score or 0)
    except (TypeError, ValueError):
        score = 0
    return score > 0 and not descartado
