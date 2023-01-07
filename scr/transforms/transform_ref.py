from scr import chain
from scr.transforms import transform


class TransformRef:
    cn: 'chain.Chain'
    tf_idx: int

    def __init__(self, cn: 'chain.Chain', tf_idx: int) -> None:
        self.cn = cn
        self.tf_idx = tf_idx

    def get(self) -> 'transform.Transform':
        return self.cn.transforms[self.tf_idx]
