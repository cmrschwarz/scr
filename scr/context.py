import concurrent.futures
from typing import Optional
from scr import progress_report, chain, document
from collections import deque


class Context:
    executor: concurrent.futures.Executor
    progress_reporter: Optional[progress_report.ProgressReporter] = None
    docs: deque[document.Document]
    root_chain: chain.Chain

    def __init__(
        self,
        root_chain: chain.Chain,
        docs: list[document.Document],
        report_progress: bool,
        parallel_jobs: int
    ) -> None:
        if report_progress:
            self.progress_reporter = progress_report.ProgressReporter()
        if parallel_jobs > 1:
            self.executor = concurrent.futures.ProcessPoolExecutor(max_workers=parallel_jobs)
        else:
            self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.docs = deque(docs)
        self.root_chain = root_chain
