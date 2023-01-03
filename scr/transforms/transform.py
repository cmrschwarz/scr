from abc import ABC, abstractmethod
import scr.chain
import scr.match


class Transform(ABC):
    label: str

    def __init__(self, label: str) -> None:
        self.label = label

    @staticmethod
    @abstractmethod
    def name_matches(name: str) -> bool:
        raise NotImplementedError

    def is_accepting(self) -> bool:
        raise NotImplementedError

    def apply_single(self, chain: scr.chain.Chain, m: scr.match.Match, res_list: list[scr.match.Match]) -> None:
        raise NotImplementedError

    def apply(self, c: scr.chain.Chain, matches: list[scr.match.Match]) -> list[scr.match.Match]:
        res: list[scr.match.Match] = []
        for m in matches:
            self.apply_single(c, m, res)
        return res
