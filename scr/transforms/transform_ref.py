from scr import chain_spec, chain
from scr.transforms import transform


class TransformRef:
    chainspec: 'chain_spec.ChainSpec'
    transform_idx: int

    def __init__(self, chainspec: 'chain_spec.ChainSpec', transform_idx: int) -> None:
        self.chainspec = chainspec
        self.transform_idx = transform_idx

    def get_chain(self, base: 'chain.Chain') -> 'chain.Chain':
        res = None
        for c in self.chainspec.iter(base):
            assert res is None
            res = c
        assert res is not None
        return res

    def get_transform(self, target_chain: 'chain.Chain') -> 'transform.Transform':
        return target_chain.transforms[self.transform_idx]
