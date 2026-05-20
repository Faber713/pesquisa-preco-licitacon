"""Contrato base para providers de precos."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderResult:
    origem: str
    dados: dict


class BaseProvider:
    nome = "base"
    confiabilidade = 0.50

    def buscar(self, *args, **kwargs):
        raise NotImplementedError

    def pesquisar(self, criterios):
        return self.buscar(criterios)
