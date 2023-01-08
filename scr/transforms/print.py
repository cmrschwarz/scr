from scr.transforms import transform
from scr.match import MatchConcrete, MatchEager
from scr import chain_spec, chain, match, utils
from typing import Optional, Type
import io
import sys

PRINT_BUFFER_CHAR_COUNT = 1024


class Print(transform.Transform):
    sleep_time_seconds: float
    newline: bool

    @staticmethod
    def name_matches(name: str) -> bool:
        return "print".startswith(name)

    def input_match_types(self) -> Optional[set[Type[match.MatchConcrete]]]:
        return set([match.MatchText, match.MatchData])

    def output_match_types(self) -> Optional[set[Type[match.MatchConcrete]]]:
        return set([match.MatchNone])

    @staticmethod
    def create(label: str, value: Optional[str], chainspec: 'chain_spec.ChainSpec') -> 'transform.Transform':
        if value is not None:
            newline = utils.try_parse_bool(value)
            if newline is None:
                raise transform.TransformCreationError("failed to parse 'print' argument as boolean")
        else:
            newline = True
        return Print(label, newline)

    def __init__(self, label: str, newline: bool = True) -> None:
        super().__init__(label)
        self.newline = newline

    def apply_concrete(self, cn: 'chain.Chain', m: MatchConcrete, text_enc: str) -> MatchEager:
        if isinstance(m, match.MatchDataStream):
            with io.TextIOWrapper(m.take_stream(), text_enc) as text_stream:
                while True:
                    buf = text_stream.read(PRINT_BUFFER_CHAR_COUNT)
                    sys.stdout.write(buf)
                    if len(buf) < PRINT_BUFFER_CHAR_COUNT:
                        break
        elif isinstance(m, match.MatchText):
            sys.stdout.write(m.text)
        elif isinstance(m, match.MatchData):
            sys.stdout.write(str(m.data, text_enc))
        else:
            raise transform.TransformApplicationError(cn, self, f"cannot print match type '{m.name()}'")
        if self.newline:
            # TODO: maybe support \r\n on windows?
            sys.stdout.write("\n")
        return match.MatchNone(m)

    def apply(self, cn: 'chain.Chain', m: 'match.Match') -> 'match.Match':
        m.add_stream_user(cn.ctx.executor)
        text_enc = cn.default_text_encoding  # TODO: improve this
        return m.apply_lazy(cn.ctx.print_executor, lambda m: self.apply_concrete(cn, m, text_enc))
