# This is the base class for Chain and ChainOptions so we can work on both
# in ChainSpec and Transform.get_next_chain.

# Since base classes are needed at declaration time and can easily cause
# circular imports, this is a seperate file.

from typing import Optional, Sequence
from scr.transforms import transform


class ChainPrototype:
    parent: Optional['ChainPrototype']
    subchains: Sequence['ChainPrototype']  # can't use list since it's not covariant
    transforms: list['transform.Transform']

    def root(self) -> 'ChainPrototype':
        c = self
        while c.parent is not None:
            c = c.parent
        return c
