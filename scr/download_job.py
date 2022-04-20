from .definitions import (
    DocumentType, URL_FILENAME_MAX_LEN, Verbosity, InteractiveResult,
    SeleniumDownloadStrategy, ScrFetchError, SeleniumVariant, DEFAULT_CWF
)
from .input_sequences import (
    YES_INDICATING_STRINGS, NO_INDICATING_STRINGS, EDIT_INDICATING_STRINGS,
    CHAIN_SKIP_INDICATING_STRINGS, DOC_SKIP_INDICATING_STRINGS
)
from typing import Optional, BinaryIO, Union, cast, Iterator
import os
import urllib
import time
import sys
from tbselenium.tbdriver import TorBrowserDriver
from selenium.common.exceptions import WebDriverException as SeleniumWebDriverException
from selenium.webdriver.remote.webdriver import WebDriver as SeleniumWebDriver
import binascii
import requests
from . import (
    progress_report, content_match, scr, utils, scr_context, selenium_setup
)
from collections import OrderedDict
import threading
import concurrent.futures
from abc import ABC, abstractmethod
from enum import Enum

DEFAULT_MAX_PRINT_BUFFER_CAPACITY = 2**20 * 100  # 100 MiB
DEFAULT_RESPONSE_BUFFER_SIZE = 32768


class ContentFormat(Enum):
    STRING = 0,
    BYTES = 1,
    STREAM = 2,
    FILE = 3,
    TEMP_FILE = 4,
    UNNEEDED = 5,


class PrintOutputManager:
    printing_buffers: OrderedDict[int, list[bytes]]
    finished_queues: set[int]
    lock: threading.Lock
    size_blocked: threading.Condition
    size_limit: int
    dl_ids: int = 0
    active_id: int = 0
    main_thread_id: Optional[int] = None

    def __init__(self, max_buffer_size: int = DEFAULT_MAX_PRINT_BUFFER_CAPACITY) -> None:
        self.lock = threading.Lock()
        self.printing_buffers = OrderedDict()
        self.finished_queues = set()
        self.size_limit = max_buffer_size
        self.size_blocked = threading.Condition(self.lock)

    def reset(self) -> None:
        self.active_id = 0
        self.dl_ids = 0
        self.main_thread_id = self.request_print_access()

    def main_thread_done(self) -> None:
        if self.main_thread_id is not None:
            self.declare_done(self.main_thread_id)
            self.main_thread_id = None

    def print(self, id: int, buffer: bytes) -> None:
        is_active = False
        with self.lock:
            while True:
                if id == self.active_id:
                    is_active = True
                    stored_buffers = self.printing_buffers.pop(id, [])
                    self.size_limit += sum(
                        map(lambda b: len(b), stored_buffers)
                    )
                    break
                elif self.size_limit > len(buffer):
                    self.size_limit -= len(buffer)
                    self.printing_buffers[id].append(buffer)
                    break
                self.size_blocked.wait()
        if is_active:
            for b in stored_buffers:
                sys.stdout.buffer.write(b)
            sys.stdout.buffer.write(buffer)
            if(stored_buffers):
                self.size_blocked.notifyAll()

    def request_print_access(self) -> int:
        with self.lock:
            id = self.dl_ids
            self.dl_ids += 1
            if id != self.active_id:
                self.printing_buffers[id] = []
        return id

    def try_reaquire_main_thread_print_access(self) -> bool:
        with self.lock:
            if self.dl_ids != self.active_id:
                return False
            self.main_thread_id = self.dl_ids
            self.dl_ids += 1
        return True

    def declare_done(self, id: int) -> None:
        new_active_id = None
        buffers_to_print: list[list[bytes]] = []
        with self.lock:
            if self.active_id != id:
                self.finished_queues.add(id)
                return

            new_active_id = self.active_id + 1
            while new_active_id in self.finished_queues:
                self.finished_queues.remove(new_active_id)
                buffers_to_print.append(
                    self.printing_buffers.pop(new_active_id)
                )
                new_active_id += 1
        while True:
            for bl in buffers_to_print:
                for b in bl:
                    sys.stdout.buffer.write(b)
            # after we printed and reacquire the lock, the job
            # that we want to give the active_id token to
            # might have finished already, in which case we have to print him too
            buffers_to_print.clear()
            with self.lock:
                self.active_id = new_active_id
                if new_active_id not in self.finished_queues:
                    new_active_id = None
                    break
                while True:
                    self.finished_queues.remove(new_active_id)
                    buffers_to_print.append(
                        self.printing_buffers.pop(new_active_id)
                    )
                    new_active_id += 1
                    if new_active_id not in self.finished_queues:
                        break
            if new_active_id is None:
                break

    def flush(self, id: int) -> None:
        with self.lock:
            if not id != self.active_id:
                return
        sys.stdout.flush()


class PrintOutputStream:
    pom: PrintOutputManager
    id: int

    def __init__(self, pom: PrintOutputManager) -> None:
        self.pom = pom
        self.id = pom.request_print_access()

    def write(self, buffer: bytes) -> int:
        self.pom.print(self.id, buffer)
        return len(buffer)

    def flush(self) -> None:
        self.pom.flush(self.id)

    def close(self) -> None:
        self.pom.declare_done(self.id)


class MinimalInputStream(ABC):
    @abstractmethod
    def read(self, size: Optional[int]) -> bytes:
        pass

    @abstractmethod
    def close(self) -> None:
        pass

    @abstractmethod
    def __enter__(self) -> None:
        pass

    @abstractmethod
    def __exit__(self) -> None:
        pass


class ResponseStreamWrapper(MinimalInputStream):
    _bytes_buffer: bytearray
    _request_response: requests.models.Response
    _iterator: Iterator[bytes]
    _pos: int = 0

    def __init__(
        self, request_response: requests.models.Response,
        buffer_size: int = DEFAULT_RESPONSE_BUFFER_SIZE
    ) -> None:
        self._bytes_buffer = bytearray()
        self._request_response = request_response
        self._iterator = self._request_response.iter_content(buffer_size)

    def read(self, size: Optional[int] = None) -> bytes:
        if size is None:
            goal_position = float("inf")
        else:
            goal_position = self._pos + size

        loaded_until = self._pos + len(self._bytes_buffer)
        while loaded_until < goal_position:
            try:
                buf = next(self._iterator)
            except StopIteration:
                goal_position = loaded_until
                break
            loaded_until += len(buf)
            if self._bytes_buffer:
                self._bytes_buffer.extend(buf)
            else:
                self._bytes_buffer = bytearray(buf)
        if loaded_until <= goal_position:
            self._pos = loaded_until
            res = self._bytes_buffer
            self._bytes_buffer = bytearray()
            return res
        assert type(goal_position) is int
        buf_pos = goal_position - self._pos
        self._pos = goal_position
        res = self._bytes_buffer[0:buf_pos]
        self._bytes_buffer = self._bytes_buffer[buf_pos:]
        return res

    def close(self) -> None:
        self._request_response.close()

    def __enter__(self) -> None:
        pass

    def __exit__(self) -> None:
        self.close()


class DownloadJob:
    save_file: Optional[BinaryIO] = None
    temp_file: Optional[BinaryIO] = None
    temp_file_path: Optional[str] = None
    multipass_file: Optional[BinaryIO] = None
    print_stream: Optional[PrintOutputStream] = None
    content_stream: Union[BinaryIO, MinimalInputStream, None] = None
    content: Union[str, bytes, BinaryIO, MinimalInputStream, None] = None
    content_format: Optional[ContentFormat] = None
    filename: Optional[str] = None
    status_report: Optional['progress_report.DownloadStatusReport'] = None

    cm: 'content_match.ContentMatch'
    save_path: Optional[str] = None
    context: str
    output_formatters: list['scr.OutputFormatter']

    def __init__(self, cm: content_match.ContentMatch) -> None:
        self.cm = cm
        self.context = (
            f"{utils.truncate(self.cm.doc.path)}{scr.get_ci_di_context(self.cm)}"
        )
        self.output_formatters = []

    def requires_download(self) -> bool:
        return self.cm.mc.need_content and not self.cm.mc.content_raw

    def setup_print_stream(self, pom: 'PrintOutputManager') -> None:
        if self.cm.mc.content_print_format is not None:
            self.print_stream = PrintOutputStream(pom)

    def request_status_report(self, download_manager: 'DownloadManager') -> None:
        self.status_report = progress_report.DownloadStatusReport(
            download_manager
        )

    def gen_fallback_filename(self, dont_use_url: bool = False) -> bool:
        if self.filename is not None or not self.cm.mc.need_filename:
            return True
        if not dont_use_url:
            path = cast(urllib.parse.ParseResult, self.cm.url_parsed).path
            self.filename = scr.sanitize_filename(urllib.parse.unquote(path))
            if self.filename is not None and len(self.filename) < URL_FILENAME_MAX_LEN:
                return True
        try:
            self.filename = scr.gen_final_content_format(
                cast(str, self.cm.mc.filename_default_format), self.cm, None
            ).decode("utf-8", errors="surrogateescape")
            return True
        except UnicodeDecodeError:
            scr.log(
                self.cm.mc.ctx, Verbosity.ERROR,
                f"{self.cm.doc.path}{scr.get_ci_di_context(self.cm)}: "
                + "generated default filename not valid utf-8"
            )
            return False

    def handle_save_path(self) -> 'InteractiveResult':
        if self.save_path is not None:
            # this was already done during for interactive filename determination
            return InteractiveResult.ACCEPT
        cm = self.cm
        if not cm.mc.content_save_format:
            return InteractiveResult.ACCEPT
        if cm.llm and not cm.mc.is_valid_label(cm.llm.result):
            scr.log(cm.mc.ctx, Verbosity.WARN,
                    f"matched label '{cm.llm.result}' would contain a slash, skipping this content from: {cm.doc.path}"
                    )
            save_path = None
        if cm.mc.need_filename:
            if not self.fetch_content():
                return InteractiveResult.ERROR
        save_path_bytes = scr.gen_final_content_format(
            cm.mc.content_save_format, cm, self.filename
        )
        try:
            save_path = save_path_bytes.decode(
                "utf-8", errors="surrogateescape"
            )
        except UnicodeDecodeError:
            scr.log(
                cm.mc.ctx, Verbosity.ERROR,
                f"{cm.doc.path}{scr.get_ci_di_context(cm)}: generated save path is not valid utf-8"
            )
            save_path = None
        while True:
            if save_path and not os.path.exists(os.path.dirname(os.path.abspath(save_path))):
                scr.log(cm.mc.ctx, Verbosity.ERROR,
                        f"{cm.doc.path}{scr.get_ci_di_context(cm)}: directory of generated save path does not exist"
                        )
                save_path = None
            if not save_path and not cm.mc.save_path_interactive:
                return InteractiveResult.ERROR
            if not cm.mc.save_path_interactive:
                break
            if save_path:
                res = scr.prompt(
                    f'{cm.doc.path}{scr.get_ci_di_context(cm)}: accept save path "{save_path}" [Yes/no/edit/chainskip/docskip]? ',
                    [
                        (InteractiveResult.ACCEPT, YES_INDICATING_STRINGS),
                        (InteractiveResult.REJECT, NO_INDICATING_STRINGS),
                        (InteractiveResult.EDIT, EDIT_INDICATING_STRINGS),
                        (InteractiveResult.SKIP_CHAIN,
                         CHAIN_SKIP_INDICATING_STRINGS),
                        (InteractiveResult.SKIP_DOC, DOC_SKIP_INDICATING_STRINGS)
                    ],
                    InteractiveResult.ACCEPT
                )
                if res == InteractiveResult.ACCEPT:
                    break
                if res != InteractiveResult.EDIT:
                    return res
            save_path = input("enter new save path: ")
        if save_path is None:
            return InteractiveResult.REJECT
        self.save_path = save_path
        return InteractiveResult.ACCEPT

    def selenium_download_from_local_file(self) -> bool:
        path = self.cm.clm.result
        self.content_format = ContentFormat.FILE
        if cast(urllib.parse.ParseResult, self.cm.url_parsed).scheme == "file":
            offs = len("file:")
            for i in range(2):
                if path[offs] == "/":
                    offs += 1
            path = path[offs:]
        self.content = path
        self.filename = os.path.basename(path)
        return True

    def selenium_download_external(self) -> bool:
        proxies = None
        if self.cm.mc.ctx.selenium_variant == SeleniumVariant.TORBROWSER:
            tbdriver = cast(TorBrowserDriver, self.cm.mc.ctx.selenium_driver)
            proxies = {
                "http": f"socks5h://localhost:{tbdriver.socks_port}",
                "https": f"socks5h://localhost:{tbdriver.socks_port}",
                "data": None
            }
        try:
            try:
                req = scr.request_raw(
                    self.cm.mc.ctx, self.cm.clm.result, cast(
                        urllib.parse.ParseResult, self.cm.url_parsed),
                    selenium_setup.load_selenium_cookies(self.cm.mc.ctx),
                    proxies=proxies, stream=True
                )
                self.content = ResponseStreamWrapper(req)
                self.content_format = ContentFormat.STREAM
                self.filename = scr.request_try_get_filename(req)
                if self.status_report:
                    self.status_report.expected_size = (
                        scr.request_try_get_filesize(req)
                    )
                return True
            except requests.exceptions.RequestException as ex:
                raise scr.request_exception_to_scr_fetch_error(ex)
        except ScrFetchError as ex:
            scr.log(
                self.cm.mc.ctx, Verbosity.ERROR,
                f"{utils.truncate(self.cm.doc.path)}{scr.get_ci_di_context(self.cm)}: "
                + f"failed to download '{utils.truncate(self.cm.clm.result)}': {str(ex)}"
            )
            return False

    def selenium_download_internal(self) -> bool:
        doc_url_str = selenium_setup.selenium_get_url(self.cm.mc.ctx)
        if doc_url_str is None:
            return False
        doc_url = urllib.parse.urlparse(doc_url_str)

        if doc_url.netloc != cast(urllib.parse.ParseResult, self.cm.url_parsed).netloc:
            scr.log(
                self.cm.mc.ctx, Verbosity.ERROR,
                f"{self.cm.clm.result}{scr.get_ci_di_context(self.cm)}: "
                + "failed to download: seldl=internal does not work across origins"
            )
            return False

        tmp_path, tmp_filename = scr.gen_dl_temp_name(self.cm.mc.ctx, None)
        script_source = """
            const url = arguments[0];
            const filename = arguments[1];
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        """
        try:
            selenium_setup.selenium_exec_script(self.cm.mc.ctx, script_source,
                                                self.cm.clm.result, tmp_filename)
        except SeleniumWebDriverException as ex:
            if selenium_setup.selenium_has_died(self.cm.mc.ctx):
                selenium_setup.report_selenium_died(self.cm.mc.ctx)
            else:
                scr.log(
                    self.cm.mc.ctx, Verbosity.ERROR,
                    f"{self.cm.clm.result}{scr.get_ci_di_context(self.cm)}: "
                    + f"selenium download failed: {str(ex)}"
                )
            return False
        i = 0
        while True:
            if os.path.exists(tmp_path):
                time.sleep(0.1)
                break
            if i < 10:
                time.sleep(0.01)
            else:
                time.sleep(0.1)
                if i > 15:
                    i = 10
                    if selenium_setup.selenium_has_died(self.cm.mc.ctx):
                        return False

            i += 1
        self.content = tmp_path
        self.content_format = ContentFormat.TEMP_FILE
        # TODO: maybe support filenames here ?
        return True

    def selenium_download_fetch(self) -> bool:
        script_source = """
            const url = arguments[0];
            var content_disposition = null;
            return (async () => {
                return await fetch(url, {
                    method: 'GET',
                })
                .then(res => {
                    content_disposition = res.headers.get(
                        'Content-Disposition');
                    return res.blob();
                })
                .then((blob, cd) => new Promise((resolve, reject) => {
                    const reader = new FileReader();
                    reader.readAsDataURL(blob);
                    reader.onload = () => (resolve(reader.result.substr(reader.result.indexOf(',') + 1)), cd);
                    reader.onerror = error => reject(error);
                }))
                .then(result => {
                    return {
                        "ok": result,
                        "content_disposition": content_disposition,
                    };
                })
                .catch(ex => {
                    return {
                        "error": ex.message
                    };
                });
            })();
        """
        err = None
        driver = cast(SeleniumWebDriver, self.cm.mc.ctx.selenium_driver)
        try:
            doc_url = driver.current_url
            res = selenium_setup.selenium_exec_script(
                self.cm.mc.ctx, script_source, self.cm.clm.result)
        except SeleniumWebDriverException as ex:
            if selenium_setup.selenium_has_died(self.cm.mc.ctx):
                selenium_setup.report_selenium_died(self.cm.mc.ctx)
                return False
            err = str(ex)
        if "error" in res:
            err = res["error"]
        if err is not None:
            cors_warn = ""
            if urllib.parse.urlparse(doc_url).netloc != urllib.parse.urlparse(self.cm.clm.result).netloc:
                cors_warn = " (potential CORS issue)"
            scr.log(
                self.cm.mc.ctx, Verbosity.ERROR,
                f"{utils.truncate(self.cm.doc.path)}{scr.get_ci_di_context(self.cm)}: "
                + f"selenium download of '{self.cm.clm.result}' failed{cors_warn}: {err}"
            )
            return False
        self.content = binascii.a2b_base64(res["ok"])
        if self.status_report:
            self.status_report.expected_size = len(self.content)
        self.filename = scr.try_get_filename_from_content_disposition(
            res.get("content_disposition", "")
        )
        self.content_format = ContentFormat.BYTES
        return True

    def selenium_download(self) -> bool:
        if (
            self.cm.doc.document_type == DocumentType.FILE
            and cast(urllib.parse.ParseResult, self.cm.url_parsed).scheme in ["", "file"]
        ):
            if not self.selenium_download_from_local_file():
                return False
        elif self.cm.mc.selenium_download_strategy == SeleniumDownloadStrategy.EXTERNAL:
            if not self.selenium_download_external():
                return False
        elif self.cm.mc.selenium_download_strategy == SeleniumDownloadStrategy.INTERNAL:
            if not self.selenium_download_internal():
                return False
        else:
            assert self.cm.mc.selenium_download_strategy == SeleniumDownloadStrategy.FETCH
            if not self.selenium_download_fetch():
                return False
        if not self.gen_fallback_filename():
            return False
        return True

    def fetch_content(self) -> bool:
        if self.content_format is not None:
            # this was already done during filename determination
            return True
        if self.cm.mc.content_raw:
            self.content = self.cm.clm.result
            self.content_format = ContentFormat.STRING
            if not self.gen_fallback_filename():
                return False
        else:
            if not self.cm.mc.need_content:
                self.content_format = ContentFormat.UNNEEDED
                # even if we don't need the content, somebody might want the filename
                # although we don't use Content-Disposition deduction here,
                # which is debatable because it is somewhat inconsistent
                # especially for data urls, this is quite terrible
                if not self.gen_fallback_filename():
                    return False
            else:
                if self.cm.mc.ctx.selenium_variant.enabled():
                    if not self.selenium_download():
                        return False
                else:
                    data = scr.try_read_data_url(self.cm)
                    if data is not None:
                        self.content = data
                        self.content_format = ContentFormat.BYTES
                        if self.status_report:
                            self.status_report.expected_size = len(data)
                        if not self.gen_fallback_filename(dont_use_url=True):
                            return False
                    elif self.cm.doc.document_type.derived_type() is DocumentType.FILE:
                        self.content = self.cm.clm.result
                        self.content_format = ContentFormat.FILE
                        if self.status_report:
                            try:
                                self.status_report.expected_size = os.path.getsize(
                                    self.content)
                            except IOError:
                                pass
                        if not self.gen_fallback_filename():
                            return False
                    else:
                        try:
                            res = scr.request_raw(
                                self.cm.mc.ctx, self.cm.clm.result,
                                cast(
                                    urllib.parse.ParseResult,
                                    self.cm.url_parsed
                                ),
                                stream=True
                            )
                            self.content = ResponseStreamWrapper(res)
                            self.filename = scr.request_try_get_filename(res)
                            if self.status_report:
                                self.status_report.expected_size = (
                                    scr.request_try_get_filesize(res)
                                )
                            self.content_format = ContentFormat.STREAM
                            if not self.gen_fallback_filename():
                                return False
                        except requests.exceptions.RequestException as ex:
                            fe = scr.request_exception_to_scr_fetch_error(ex)
                            scr.log(self.cm.mc.ctx, Verbosity.ERROR,
                                    f"{self.context}: failed to download '{utils.truncate(self.cm.clm.result)}': {str(fe)}")
                            return False
        return True

    def setup_save_file(self) -> bool:
        if not self.save_path:
            return True
        try:
            use_as_multipass = (
                self.cm.mc.need_output_multipass
                and self.multipass_file is None
                and self.cm.mc.content_write_format == DEFAULT_CWF
            )
            save_file = cast(BinaryIO, open(
                self.save_path,
                ("w" if self.cm.mc.overwrite_files else "x")
                + "b"
                + ("+" if use_as_multipass else "")
            ))
            if use_as_multipass:
                self.multipass_file = save_file
        except FileExistsError:
            scr.log(self.cm.mc.ctx, Verbosity.ERROR,
                    f"{self.context}: file already exists: {self.save_path}")
            return False
        except OSError as ex:
            scr.log(
                self.cm.mc.ctx, Verbosity.ERROR,
                f"{self.context}: failed to write to file '{self.save_path}': {str(ex)}"
            )
            return False

        self.output_formatters.append(scr.OutputFormatter(
            cast(str, self.cm.mc.content_write_format),
            self.cm, save_file, self.content, self.filename
        ))
        return True

    def setup_content_file(self) -> bool:
        if self.content_format not in [ContentFormat.FILE, ContentFormat.TEMP_FILE]:
            return True
        assert type(self.content) is str
        try:
            self.content_stream = cast(BinaryIO, scr.fetch_file(
                self.cm.mc.ctx, self.content, stream=True)
            )
        except ScrFetchError as ex:
            scr.log(self.cm.mc.ctx, Verbosity.ERROR,
                    f"{self.context}: failed to open file '{utils.truncate(self.content)}': {str(ex)}")
            return False
        if self.content_format == ContentFormat.TEMP_FILE:
            self.temp_file_path = self.content
        self.content = self.content_stream
        if self.cm.mc.need_output_multipass:
            self.multipass_file = self.content_stream
        return True

    def setup_print_output(self) -> bool:
        if self.cm.mc.content_print_format is None:
            return True
        if self.print_stream is not None:
            stream: Union[PrintOutputStream, BinaryIO] = self.print_stream
        else:
            stream = sys.stdout.buffer
        self.output_formatters.append(scr.OutputFormatter(
            self.cm.mc.content_print_format, self.cm,
            stream, self.content, self.filename
        ))
        return True

    def check_abort(self) -> None:
        if self.cm.mc.ctx.abort:
            raise InterruptedError

    def run_job(self) -> bool:
        if self.status_report:
            self.status_report.gen_display_name(
                self.cm.url_parsed, self.filename, self.save_path
            )
            self.status_report.enqueue()
        success = False
        try:
            if self.handle_save_path() != InteractiveResult.ACCEPT:
                return False
            if not self.fetch_content():
                return False

            self.check_abort()
            self.content_stream: Union[BinaryIO, MinimalInputStream, None] = (
                cast(Union[BinaryIO, MinimalInputStream], self.content)
                if self.content_format == ContentFormat.STREAM
                else None
            )

            if not self.setup_content_file():
                return False
            if not self.setup_save_file():
                return False
            if self.status_report:
                # try to generate a better name now that we have more information
                self.status_report.gen_display_name(
                    self.cm.url_parsed, self.filename, self.save_path
                )
            if not self.setup_print_output():
                return False
            self.check_abort()

            if self.content_stream is None:
                if self.status_report and self.content:
                    self.status_report.submit_update(
                        len(cast(Union[str, bytes], self.content)))
                for of in self.output_formatters:
                    res = of.advance()
                    assert not res
                    self.check_abort()
                success = True
                return True

            if self.cm.mc.need_output_multipass and self.multipass_file is None:
                try:
                    self.temp_file_path, _filename = scr.gen_dl_temp_name(
                        self.cm.mc.ctx, self.save_path)
                    self.temp_file = open(self.temp_file_path, "xb+")
                except IOError:
                    return False
                self.multipass_file = self.temp_file
                self.check_abort()

            if self.content_stream is not None:
                while True:
                    buf = self.content_stream.read(
                        DEFAULT_RESPONSE_BUFFER_SIZE)
                    self.check_abort()
                    if buf is None:
                        continue
                    if self.status_report:
                        self.status_report.submit_update(len(buf))
                    advance_output_formatters(self.output_formatters, buf)
                    if self.temp_file:
                        self.temp_file.write(buf)
                    if len(buf) < DEFAULT_RESPONSE_BUFFER_SIZE:
                        if self.content_stream is not self.multipass_file:
                            self.content_stream.close()
                            self.content_stream = None
                        break

            if self.multipass_file:
                while self.output_formatters:
                    self.multipass_file.seek(0)
                    while True:
                        buf = self.multipass_file.read(
                            DEFAULT_RESPONSE_BUFFER_SIZE)
                        self.check_abort()
                        advance_output_formatters(self.output_formatters, buf)
                        if len(buf) < DEFAULT_RESPONSE_BUFFER_SIZE:
                            break
            success = True
            return True
        except InterruptedError:
            return False
        finally:
            if self.status_report:
                self.status_report.finished()
            if self.print_stream is not None:
                self.print_stream.close()
            if self.content_stream is not None:
                self.content_stream.close()
            if self.temp_file is not None:
                self.temp_file.close()
            if self.temp_file_path is not None:
                os.remove(self.temp_file_path)
            if self.save_file is not None:
                self.save_file.close()
            path = self.cm.clm.result
            if self.requires_download():
                scr.log(self.cm.mc.ctx, Verbosity.DEBUG,
                        f"finished downloading {path}" if success else f"failed to download {path}"
                        )


class DownloadManager:
    ctx: 'scr_context.ScrContext'
    max_threads: int
    pending_jobs: set[concurrent.futures.Future[bool]]
    pom: PrintOutputManager
    executor: concurrent.futures.ThreadPoolExecutor
    status_report_lock: threading.Lock
    download_status_reports: list['progress_report.DownloadStatusReport']
    enable_status_reports: bool

    def __init__(self, ctx: 'scr_context.ScrContext', max_threads: int, enable_status_reports: bool) -> None:
        self.ctx = ctx
        self.pending_jobs = set()
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_threads
        )
        self.pom = PrintOutputManager()
        self.status_report_lock = threading.Lock()
        self.download_status_reports = []
        self.enable_status_reports = enable_status_reports

    def submit(self, dj: DownloadJob) -> None:
        scr.log(
            self.ctx, Verbosity.DEBUG,
            f"enqueuing download for {dj.cm.clm.result}"
        )
        dj.setup_print_stream(self.pom)
        if self.enable_status_reports:
            dj.request_status_report(self)
        self.pending_jobs.add(self.executor.submit(dj.run_job))

    def wait_until_jobs_done(self) -> None:
        if not self.pending_jobs:
            return
        may_print = False
        if self.pom:
            may_print = self.pom.try_reaquire_main_thread_print_access()
        if not self.enable_status_reports or not may_print:
            results = concurrent.futures.wait(self.pending_jobs)
            for x in results.done:
                x.result()
            self.pending_jobs.clear()
        self.pom.request_print_access()
        prm = progress_report.ProgressReportManager()
        while True:
            results = concurrent.futures.wait(
                self.pending_jobs,
                timeout=0 if not prm.prev_report_line_count
                else progress_report.DOWNLOAD_STATUS_REFRESH_INTERVAL
            )
            for x in results.done:
                x.result()
            self.pending_jobs = results.not_done
            prm.load_status(self)
            if not prm.updates_remaining():
                if not self.pending_jobs:
                    # this happens when we got main thread print access
                    # but everybody is already done and never downloaded anything
                    # we don't want any progress reports here
                    break
                continue
            prm.print_status_report()
            if not self.pending_jobs:
                break

    def terminate(self, cancel_running: bool = False) -> None:
        try:
            if not cancel_running:
                cancel_running = True
                self.wait_until_jobs_done()
                cancel_running = False
        finally:
            if cancel_running:
                self.ctx.abort = True
            self.executor.shutdown(wait=True, cancel_futures=cancel_running)


def advance_output_formatters(output_formatters: list['scr.OutputFormatter'], buf: Optional[bytes]) -> None:
    i = 0
    while i < len(output_formatters):
        if output_formatters[i].advance(DEFAULT_RESPONSE_BUFFER_SIZE, buf):
            i += 1
        else:
            del output_formatters[i]
