from scr import chain_options, context_options, document


def print_help() -> None:
    print("")


def parse(args: list[str]) -> tuple[chain_options.ChainOptions, list[document.Document], context_options.ContextOptions]:
    root_chain = chain_options.ChainOptions()
    docs: list[document.Document] = []
    instance_opts = context_options.ContextOptions()
    for arg in args:
        pass  # TODO
    return (root_chain, docs, instance_opts)
