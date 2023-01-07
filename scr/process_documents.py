from collections import deque
from scr import context, chain, document, match
from scr.transforms import transform_ref
import itertools


def process_documents(ctx: 'context.Context', rc: 'chain.Chain', docs: list['document.Document']) -> list['match.Match']:
    ctx.root_chain = rc
    assert len(ctx.documents) == 0  # TODO: support repl doc reuse in selenium
    ctx.documents.extend(docs)
    results: list[match.Match] = []
    match_queue = deque[tuple[transform_ref.TransformRef, match.Match]]()
    while True:
        while ctx.documents:
            doc = ctx.documents.popleft()
            origin_match = doc.source.get_content(ctx)
            for cn in doc.applied_chains.iter(rc):
                match_queue.append((transform_ref.TransformRef(cn, 0), origin_match))
        while match_queue:
            tgt, m = match_queue.popleft()
            cn = tgt.cn
            for tf in itertools.islice(cn.transforms, tgt.tf_idx, None):
                m = tf.apply(cn, m)
                if isinstance(m, match.MatchControlFlowRedirect):
                    assert m.parent is not None
                    match_queue.extend(m.matches)
                    break
            else:
                if cn.aggregation_targets:
                    for tgt in cn.aggregation_targets:
                        match_queue.append((tgt, m))
                else:
                    results.append(m)
        if not match_queue and not ctx.documents:
            break
    results_eager = []
    for r in results:
        results_eager.append(r.result())
    return results
