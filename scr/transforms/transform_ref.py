from scr import chain
from scr.transforms import transform
from dataclasses import dataclass


@dataclass(slots=True, frozen=True, init=True)
class TransformRef:
    cn: 'chain.Chain'
    tf_idx: int

    def get_transform(self) -> 'transform.Transform':
        return self.cn.transforms[self.tf_idx]
