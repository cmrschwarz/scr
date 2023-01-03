import concurrent.futures
from typing import Optional
from scr import chain, document
import scr.progress_report
from collections import deque
from scr import result


class Context:
    parallel_jobs: int = -1
    executor: concurrent.futures.Executor
    progress_reporter: Optional['scr.progress_report.ProgressReporter'] = None
    docs: deque['document.Document']
    root_chain: 'chain.Chain'

    def __init__(
        self,
        parallel_jobs: int,
        progress_report: bool,
    ) -> None:
        assert parallel_jobs >= 0
        self.set_parallel_job_count(parallel_jobs)
        if progress_report:
            self.progress_reporter = scr.progress_report.ProgressReporter()
        self.docs = deque()

    def set_parallel_job_count(self, parallel_jobs: int) -> None:
        if self.parallel_jobs == parallel_jobs:
            return
        self.parallel_jobs = parallel_jobs
        if parallel_jobs > 1:
            self.executor = concurrent.futures.ProcessPoolExecutor(max_workers=parallel_jobs)
        else:
            self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def run(self, root_chain: 'chain.Chain', docs: list[document.Document]) -> list['result.Result']:
        self.root_chain = root_chain
        self.docs.extend(docs)
        raise NotImplementedError
