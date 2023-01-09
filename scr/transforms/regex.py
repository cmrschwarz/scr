from scr.transforms import transform
from scr import match, chain_spec, chain_prototype
import re
from typing import Optional, Type


class Regex(transform.TransformEager):
    regex: re.Pattern[str]

    @staticmethod
    def name_matches(name: str) -> bool:
        return "regex".startswith(name)

    def input_match_types(self) -> Optional[set[Type[match.MatchConcrete]]]:
        return set([match.MatchText])

    def output_match_types(self) -> Optional[set[Type[match.MatchConcrete]]]:
        return set([match.MatchText])

    @staticmethod
    def create(label: str, value: Optional[str], current: 'chain_prototype.ChainPrototype', chainspec: 'chain_spec.ChainSpec') -> 'transform.Transform':
        if value is None:
            raise transform.TransformCreationError("missing regex argument")
        try:
            regex = re.compile(value, re.DOTALL | re.MULTILINE)
            return Regex(label, regex)
        except re.error as err:
            raise transform.TransformCreationError(f"invalid regex: {err.msg}")

    def __init__(self, label: str, regex: re.Pattern[str]) -> None:
        super().__init__(label)
        self.regex = regex

    def apply_concrete(self, m: 'match.MatchConcrete') -> 'match.MatchEager':
        if not isinstance(m, match.MatchText):
            raise ValueError("the regex transform only works on text")
        mmb = match.MultiMatchBuilder(m)
        for re_match in self.regex.finditer(m.text):
            text = re_match.group(0)
            mres = match.MatchText(m, text if text is not None else "")
            for k, v in re_match.groupdict().items():
                mres.args[k] = match.MatchText(m, v if v is not None else "")
            for i, g in enumerate(re_match.groups()):
                mres.args[self.label + str(i)] = match.MatchText(m, g if g is not None else "")
            mmb.append(mres)
        return mmb.result()
