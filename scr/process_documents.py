from scr import context, chain, document, match


def fetch_doc(ctx: 'context.Context', doc: 'document.Document') -> str:
    pass


def process_documents(ctx: 'context.Context', rc: 'chain.Chain', docs: list['document.Document']) -> list['match.Match']:
    ctx.root_chain = rc
    assert len(ctx.documents) == 0  # TODO: support repl doc reuse in selenium
    ctx.documents.extend(docs)
    while ctx.documents:
        doc = ctx.documents.popleft()
        doc_text = fetch_doc(ctx, doc)
        matches = []
        for cn in doc.applied_chains.iter(rc):
            m = match.MatchText(None, doc_text)
            for tf in cn.transforms:
                m = tf.apply(m)
            matches.append(m)
    return []
