"""Contrato base para providers de precos."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderResult:
    origem: str
    dados: dict


class BaseProvider:
    nome = "base"

    def buscar(self, *args, **kwargs):
        raise NotImplementedError
