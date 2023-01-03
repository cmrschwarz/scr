import concurrent.futures
from typing import Optional
from scr import chain, document
import scr.progress_report
from collections import deque
from scr import result


class Context:
    executor: concurrent.futures.Executor
    progress_reporter: Optional['scr.progress_report.ProgressReporter'] = None
    docs: deque['document.Document']
    root_chain: 'chain.Chain'

    def __init__(
        self,
        parallel_jobs: int,
        progress_report: bool,
    ) -> None:
        if parallel_jobs > 1:
            self.executor = concurrent.futures.ProcessPoolExecutor(max_workers=parallel_jobs)
        else:
            self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        if progress_report:
            self.progress_reporter = scr.progress_report.ProgressReporter()
        self.docs = deque()

    def run(self, root_chain: 'chain.Chain', docs: list[document.Document]) -> list['result.Result']:
        self.root_chain = root_chain
        self.docs.extend(docs)
        raise NotImplementedError
