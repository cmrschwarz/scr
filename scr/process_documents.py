from scr import context, chain, document, result


def fetch_doc(ctx: 'context.Context', doc: 'document.Document') -> str:
    pass


def process_documents(ctx: 'context.Context', rc: 'chain.Chain', docs: list['document.Document']) -> list['result.Result']:
    ctx.root_chain = rc
    assert len(ctx.documents) == 0  # TODO: support repl doc reuse in selenium
    ctx.documents.extend(docs)
    while ctx.documents:
        doc = ctx.documents.popleft()
        doc_text = fetch_doc(ctx, doc)
        for c in doc.applied_chains.iter():
            c = 1

    return []
