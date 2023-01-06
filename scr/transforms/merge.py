from scr.transforms import transform
from scr import chain_spec, chain, chain_options, match, range_spec
from typing import Optional, cast


class Merge(transform.Transform):
    sources: 'chain_spec.ChainSpec'

    @staticmethod
    def name_matches(name: str) -> bool:
        return "next".startswith(name)

    @staticmethod
    def create(label: str, value: Optional[str], chainspec: 'chain_spec.ChainSpec') -> 'transform.Transform':
        if value is None:
            return Merge(
                label,
                chainspec.clone().append(
                    chain_spec.ChainSpecSubrange(
                        range_spec.RangeSpecBounds(None, None),
                        chain_spec.ChainSpecCurrent()
                    )
                )
            )
        try:
            return Merge(label, chain_spec.parse_chain_spec(value))
        except chain_spec.ChainSpecParseException as ex:
            raise transform.TransformValueError(f"invalid range for 'next': {ex}")

    def __init__(self, label: str, sources: 'chain_spec.ChainSpec') -> None:
        super().__init__(label)
        self.sources = sources

    def apply(self, c: 'chain.Chain', m: 'match.Match') -> 'match.Match':
        if not isinstance(m, match.MatchMultiChainAggregate):
            raise ValueError("the merge transform only works on multi chain aggregates")
        all_lists = None
        length: Optional[int] = None
        for c in self.sources.iter(c):
            mtch = m.results[c]
            if isinstance(mtch, match.MatchList):
                if all_lists is None:
                    all_lists = True
                elif not all_lists:
                    raise ValueError("subchains for merge must have same number of argument")
                if length is None:
                    length = len(mtch.matches)
                elif length != len(mtch.matches):
                    raise ValueError("subchains for merge must have same number of argument")
            else:
                if all_lists is None:
                    all_lists = False
                    length = 1
                elif all_lists:
                    raise ValueError("subchains for merge must have same number of argument")
        length_ = cast(int, length)
        mmb = match.MultiMatchBuilder(m)
        i = 0
        for i in range(0, length_):
            mn = match.MatchNone(m)
            for c in self.sources.iter(c):
                if all_lists:
                    mtch = cast(match.MatchList, m.results[c]).matches[i]
                else:
                    mtch = m.results[c]
                mn.args.update(mtch.args.items())
            mmb.append(mn)
