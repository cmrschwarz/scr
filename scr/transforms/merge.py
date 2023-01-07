from scr.transforms import transform, transform_ref
from scr import chain_spec, chain, chain_options, match, range_spec
from typing import Optional, cast


class Merge(transform.Transform):
    sources_cs: 'chain_spec.ChainSpec'
    sources: list['chain.Chain'] = []
    targets: list['transform_ref.TransformRef']

    @staticmethod
    def name_matches(name: str) -> bool:
        return "merge".startswith(name)

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
        self.sources_cs = sources
        self.targets = []

    def setup(self, cn: 'chain.Chain', transform_index: int) -> 'transform.Transform':
        if not len(self.sources):
            self.sources = [*self.sources_cs.iter(cn.root())]
        tr = transform_ref.TransformRef(cn, transform_index)
        for cn in self.sources:
            cn.aggregation_targets.append(tr)
        self.targets.append(tr)
        return self

    def apply(self, c: 'chain.Chain', m: 'match.Match') -> 'match.Match':
        if not isinstance(m, match.MatchMultiChainAggregate):
            raise ValueError("the merge transform only works on multi chain aggregates")
        all_lists = None
        length: Optional[int] = None
        for cn in self.sources:
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
            for cn in self.sources:
                if all_lists:
                    mtch = cast(match.MatchList, m.results[c]).matches[i]
                else:
                    mtch = m.results[c]
                mn.args.update(mtch.args.items())
            mmb.append(mn)
        return mmb.result()
