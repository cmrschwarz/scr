from typing import Optional
from scr.transforms import transform
from scr import match
import re


class Regex(transform.TransformEager):
    regex: re.Pattern[str]

    @staticmethod
    def name_matches(name: str) -> bool:
        return "regex".startswith(name)

    def __init__(self, name: str, label: Optional[str], arg: str) -> None:
        super().__init__(label if label is not None else name)
        try:
            self.regex = re.compile(arg, re.DOTALL | re.MULTILINE)
        except re.error as err:
            raise ValueError(f"invalid regex: {err.msg}")

    def apply_concrete(self, m: match.MatchConcrete) -> match.MatchEager:
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
