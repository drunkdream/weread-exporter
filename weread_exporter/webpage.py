"""
WebRead WebPage
"""

import asyncio
import json
import logging
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
from typing import Dict, List, Optional, Union, Any, Tuple, cast

import pyppeteer

from . import webproxy
from . import utils

if sys.version_info >= (3, 8):
    from typing import TYPE_CHECKING
else:
    from typing_extensions import TYPE_CHECKING


DETECT_HEADLESS_SCRIPT = """
const webdriver = navigator.webdriver === true;
const chromeObj = typeof window.chrome !== "undefined";
const pluginCount = navigator.plugins.length;
const languageCount = navigator.languages ? navigator.languages.length : 0;
const headlessUA = /HeadlessChrome/.test(navigator.userAgent);
const zeroOuterSize = (window.outerWidth === 0 && window.outerHeight === 0);
webdriver || !chromeObj || pluginCount === 0 || languageCount === 0  || headlessUA || zeroOuterSize;
"""


class WeReadWebPage(object):
    """WebRead WebPage"""

    root_url: str = "https://weread.qq.com"
    window_size: Tuple[int, int] = (1920, 1080)

    def __init__(
        self,
        book_id: str,
        cookie_path: Optional[str] = None,
        webcache_path: Optional[str] = None,
    ) -> None:
        self._book_id: str = book_id
        self._cookie_path: Optional[str] = cookie_path
        self._cookie: Dict[str, str] = {}
        self._webcache_path: str = webcache_path or "cache"
        if not os.path.isdir(self._webcache_path):
            os.makedirs(self._webcache_path)
        self._home_url: str = "%s/web/bookDetail/%s" % (
            self.__class__.root_url,
            book_id,
        )
        self._chapter_root_url: str = self.__class__.root_url + "/web/reader/"
        self._hook_script_name: str = "1.%s.js" % "".join(
            [random.choice("0123456789abcdef") for _ in range(8)]
        )
        self._browser: Optional[pyppeteer.browser.Browser] = None
        self._page: Optional[pyppeteer.page.Page] = None
        self._load_cookie()
        self._url: str = ""
        self._proxy_installed: bool = False

    async def get_book_info(self) -> Dict[str, Any]:
        html = (await utils.fetch(self._home_url)).decode()
        pos1 = html.find("window.__INITIAL_STATE__")
        if pos1 <= 0:
            raise RuntimeError("Unexpected html: %s" % html)
        pos1 = html.find("=", pos1)
        pos2 = html.find("};", pos1)
        data = html[pos1 + 1 : pos2 + 1].strip()
        data = json.loads(data)
        book_info: Dict[str, Any] = {}
        book_info["title"] = data["reader"]["bookInfo"]["title"]
        book_info["author"] = data["reader"]["bookInfo"]["author"]
        book_info["cover"] = data["reader"]["bookInfo"]["cover"]
        book_info["intro"] = data["reader"]["bookInfo"]["intro"]
        book_info["chapters"] = []
        for chapter in data["reader"]["chapterInfos"]:
            chap = {
                "id": chapter["chapterUid"],
                "title": chapter["title"],
                "level": chapter["level"],
                "words": chapter["wordCount"],
                "anchors": [],
            }
            if chapter["anchors"]:
                for it in chapter["anchors"]:
                    chap["anchors"].append({"title": it["title"], "level": it["level"]})
            book_info["chapters"].append(chap)
        return book_info

    async def get_user_info(self) -> Dict[str, Any]:
        vid: str = self._cookie.get("wr_vid", "")
        if not vid:
            raise utils.InvalidUserError("Invalid cookie: %s" % self._format_cookie())
        url: str = "%s/web/user?userVid=%s" % (self.__class__.root_url, vid)
        headers: Dict[str, str] = {
            "Referer": self.__class__.root_url,
            "Cookie": self._format_cookie(),
        }
        rsp: bytes = await utils.fetch(url, headers=headers)
        rsp_data = json.loads(rsp.decode())
        if rsp_data.get("errCode") == -2012:
            result = await utils.fetch(
                self.__class__.root_url, headers=headers, respond_with_headers=True
            )
            _, rsp_headers, _ = cast(Tuple[int, Dict[str, str], bytes], result)
            for it in rsp_headers.getall("Set-Cookie", []):
                cookie = it.split("; ")[0]
                if "=" not in cookie:
                    logging.warning(
                        "[%s] Ignore invalid cookie: %s"
                        % (self.__class__.__name__, cookie)
                    )
                    continue
                key, value = cookie.split("=", 1)
                self._cookie[key] = value
                logging.info(
                    "[%s] Update cookie %s" % (self.__class__.__name__, cookie)
                )
            self._save_cookie()
            headers["Cookie"] = self._format_cookie()
            rsp = await utils.fetch(url, headers=headers)
            rsp_data = json.loads(rsp.decode())
        elif rsp_data.get("errCode") == -2010:
            # 用户不存在
            raise utils.InvalidUserError("User %s not found" % vid)
        elif rsp_data.get("errCode"):
            raise RuntimeError("Get user info failed: %s" % rsp_data)
        return rsp_data

    def _load_cookie(self) -> None:
        self._cookie = {}
        if not self._cookie_path or not os.path.isfile(self._cookie_path):
            return
        with open(self._cookie_path) as fp:
            cookie = fp.read()
            try:
                cookie_data: Dict[str, str] = json.loads(cookie)
            except:
                for it in cookie.split(";"):
                    it = it.strip()
                    if "=" not in it:
                        continue
                    key, value = it.split("=", 1)
                    self._cookie[key] = value
            else:
                for key in cookie_data:
                    self._cookie[key] = cookie_data[key]

    def _save_cookie(self) -> None:
        if not self._cookie_path:
            return
        with open(self._cookie_path, "w") as fp:
            fp.write(json.dumps(self._cookie))

    def _format_cookie(self, cookie: str = "") -> str:
        cookies: List[str] = []
        if cookie:
            cookies.append(cookie)
        for key in self._cookie:
            cookies.append("%s=%s" % (key, self._cookie[key]))
        return "; ".join(cookies)

    async def _read_cookie(self) -> Dict[str, str]:
        cookies = await self._page.cookies()
        cookie_map = {}
        for cookie in cookies:
            cookie_map[cookie["name"]] = cookie["value"]
        return cookie_map

    async def _update_cookie(self) -> None:
        self._cookie = await self._read_cookie()

    async def check_valid(self) -> bool:
        html = await utils.fetch(self._home_url)
        if b'"soldout":1' in html:
            return False
        return True

    def _check_chrome(self) -> str:
        path_list = os.environ["PATH"].split(";" if sys.platform == "win32" else ":")
        for chrome in ("chrome", "google-chrome"):
            if sys.platform == "win32":
                chrome += ".exe"
            for path in path_list:
                if os.path.isfile(os.path.join(path, chrome)):
                    return chrome

        if sys.platform == "darwin":
            chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            if os.path.isfile(chrome):
                return chrome

        if sys.platform == "win32":
            command = "where chrome"
        else:
            command = "which chrome"
        raise utils.ChromeNotInstalledError(
            "Please make sure `chrome` is installed, and the install path is added to PATH environment. \nYou can test that with `%s` command."
            % command
        )

    def _get_chrome_version(self, chrome_path: str) -> Optional[int]:
        """获取 Chrome 版本号的主版本号"""
        try:
            # 尝试获取 Chrome 版本
            result = subprocess.run(
                [chrome_path, "--version"], capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                # 解析版本号，格式通常是 "Google Chrome 136.0.6776.0" 或 "Chromium 136.0.6776.0"
                version_match = re.search(r"(\d+)\.", result.stdout)
                if version_match:
                    return int(version_match.group(1))
        except (
            subprocess.TimeoutExpired,
            subprocess.SubprocessError,
            FileNotFoundError,
            ValueError,
        ):
            # 如果获取版本失败，返回 None
            pass
        return None

    async def launch(
        self,
        headless: bool = False,
        force_login: bool = False,
        use_default_profile: bool = False,
        mock_user_agent: bool = False,
        proxy_server: Optional[str] = None,
    ) -> None:
        logging.info("[%s] Launch url %s" % (self.__class__.__name__, self._home_url))
        chrome: str = self._check_chrome()

        # 检查 Chrome 版本并在使用默认 profile 时发出警告
        if use_default_profile:
            chrome_version = self._get_chrome_version(chrome)
            if chrome_version is not None and chrome_version >= 136:
                logging.warning(
                    "[%s] Chrome %d detected. Chrome 136+ no longer supports using default profile. Consider using --use-default-profile=false to avoid potential issues."
                    % (self.__class__.__name__, chrome_version)
                )

        args = ["--no-first-run", "--remote-allow-origins=*"]
        if headless:
            args.append("--headless=new")
            if sys.platform == "linux" and os.getuid() == 0:
                args.append("--no-sandbox")
        if use_default_profile:
            args.append("--user-data-dir")
        else:
            args.append("--window-size=%d,%d" % self.__class__.window_size)
            args.append("--user-data-dir=%s" % tempfile.mkdtemp())
        if mock_user_agent:
            args.append('--user-agent="%s"' % utils.generate_user_agent())
        if proxy_server:
            args.append("--proxy-server=%s" % proxy_server)
        args.append("about:blank")
        logging.info(
            "[%s] Chrome args: chrome %s" % (self.__class__.__name__, " ".join(args))
        )
        self._browser = await pyppeteer.launch(
            executablePath=chrome,
            ignoreDefaultArgs=True,
            args=args,
            defaultViewport=None,
            logLevel=logging.INFO,
        )
        self._page = (await self._browser.pages())[0]
        await self._page.evaluateOnNewDocument(
            """() => {
            if (navigator.webdriver) {
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => {
                        console.log('navigator.webdriver is called');
                        console.log(new Error().stack);
                        return undefined;
                    }
                });
                var _hasOwnProperty = Object.prototype.hasOwnProperty;
                Object.prototype.hasOwnProperty = function (key) {
                    if (key === 'webdriver') {
                        console.log('hasOwnProperty', key, 'is called');
                        console.log(new Error().stack);
                        return false;
                    }
                    return _hasOwnProperty.call(this, key);
                };
                const originalQuery = navigator.permissions.query;
                navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
                );
            }
            if (navigator.plugins.length === 0) {
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5],
                });
                Object.defineProperty(window, 'PluginArray', {
                    get: () => Array,
                });
            }
            if (navigator.languages.length === 0) {
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en'],
                });
            }
            window.chrome = window.chrome || {
                runtime: {},
            };
        }
        """
        )

        await self._page.setViewport(
            {
                "width": 0,
                "height": 0,
                "deviceScaleFactor": 0.3,
            }
        )
        detect_headless_result = await self._page.evaluate(DETECT_HEADLESS_SCRIPT)
        if detect_headless_result:
            key = input("浏览器检测到Headless模式，继续执行可能导致帐号被封禁，是否继续执行？Y/n\n")
            if key != "Y":
                raise utils.BreakExportingError()

        if self._cookie.get("wr_vid"):
            try:
                user_info = await self.get_user_info()
            except utils.InvalidUserError as ex:
                logging.warning(
                    "[%s] Get user error: %s" % (self.__class__.__name__, ex)
                )
                self._cookie = {}
            else:
                logging.info(
                    "[%s] Current login user is %s"
                    % (self.__class__.__name__, user_info.get("name", "Anonymous"))
                )
        if self._cookie:
            await self._inject_cookie()

        await self._page.goto(self._home_url)
        # await self.wait_for_selector("div.readerFooter a")
        if force_login:
            await self.login()
        if self._cookie:
            await self.wait_for_avatar()
        self._page.on("console", self.handle_log)

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = self._page = None

    async def get_html(self) -> str:
        return await self._page.evaluate("document.documentElement.outerHTML;")

    async def screenshot(self, save_path: str) -> None:
        await self._page.screenshot({"path": save_path})

    async def wait_for_selector(self, selector: str, timeout: int = 30) -> Any:
        try:
            return await self._page.waitForSelector(selector, timeout=timeout * 1000)
        except pyppeteer.errors.TimeoutError as ex:
            html = await self.get_html()
            html_path = "webpage.html"
            with open(html_path, "wb") as fp:
                if not isinstance(html, bytes):
                    html = html.encode("utf8")
                fp.write(html)
            logging.info(
                "[%s] Current html saved to %s" % (self.__class__.__name__, html_path)
            )
            screenshot_path = "screenshot.jpg"
            await self.screenshot(screenshot_path)
            logging.info(
                "[%s] Current screenshot saved to %s"
                % (self.__class__.__name__, screenshot_path)
            )
            raise ex

    def handle_log(self, message: Any) -> None:
        text = message.text
        logging.info("[%s][Console] %s" % (self.__class__.__name__, text))
        with open("%s.log" % self._book_id, "a+", encoding="utf-8") as fp:
            fp.write("[%s] %s\n" % (self._url, text))

    async def wait_for_avatar(self, timeout: int = 30) -> None:
        time0 = time.time()
        while time.time() - time0 < timeout:
            avatar_url = await self._page.evaluate(
                "document.querySelector('img.wr_avatar_img') && document.querySelector('img.wr_avatar_img').getAttribute('src');"
            )
            if avatar_url is None or not avatar_url.endswith("Default.svg"):
                break
            await asyncio.sleep(5)
        else:
            raise RuntimeError("Wait for avatar timeout")

    async def _inject_cookie(self) -> None:
        for key in self._cookie:
            logging.info(
                "[%s] Inject cookie %s=%s"
                % (self.__class__.__name__, key, self._cookie[key])
            )
            await self._page.setCookie(
                {
                    "url": self.__class__.root_url,
                    "name": key,
                    "value": self._cookie[key],
                    "secure": True,
                }
            )

    async def login(self) -> bool:
        selectors = [
            "button.navBar_link_Login",
            "div.readerTopBar_right button.actionItem",
        ]
        for selector in selectors:
            script = (
                "var elem = document.querySelector('%s'); elem && elem.innerText"
                % (selector)
            )
            result = await self._page.evaluate(script)
            if not result:
                continue
            if "登录" not in result:
                continue
            await self._page.click(selector)
            script = "document.querySelector('div.menu_container img.wr_avatar_img')"
            time0 = time.time()
            while time.time() - time0 < 300:
                logging.info("[%s] Waiting for login" % self.__class__.__name__)
                await asyncio.sleep(10)
                result = await self._page.evaluate(script)
                if not result:
                    continue
                logging.info("[%s] Login success" % self.__class__.__name__)
                await self._update_cookie()
                self._save_cookie()
                return True
            else:
                raise RuntimeError("Login timeout")
        return False

    async def _get_from_cache_or_server(
        self, url: str, headers: Optional[Dict[str, str]] = None
    ) -> Tuple[int, Dict[str, str], bytes]:
        u: urllib.parse.ParseResult = urllib.parse.urlparse(url)
        path = os.path.join(
            self._webcache_path, "resources", u.path[1:].replace("/", os.sep)
        )
        if os.path.isfile(path):
            logging.info(
                "[%s] Url %s hit cache %d"
                % (self.__class__.__name__, url, os.path.getsize(path))
            )
            with open(path, "rb") as fp:
                return 200, {}, fp.read()

        dirpath = os.path.dirname(path)
        if not os.path.isdir(dirpath):
            os.makedirs(dirpath)
        result = await utils.fetch(url, headers=headers, respond_with_headers=True)
        # 当 respond_with_headers=True 时，返回类型确定是 Tuple[int, Dict[str, str], bytes]
        status, headers_resp, body = cast(Tuple[int, Dict[str, str], bytes], result)
        logging.info("[%s] Url %s return %d" % (self.__class__.__name__, url, status))
        if status == 200:
            with open(path, "wb") as fp:
                fp.write(body)
        return status, headers_resp, body

    def _log_request(self, request: "webproxy.WebRequest") -> None:
        if request.method == "POST":
            message = "[%s] %s %s" % (
                self.__class__.__name__,
                request.method,
                request.url,
            )
            if request.body:
                message += " %s" % request.content
            logging.info(message)

    def on_document_request(self, request: "webproxy.WebRequest") -> Dict[str, Any]:
        """ """
        cookie = request.headers.get("cookie", "")
        cookie += "; wr_useHorizonReader=0"
        request.headers["cookie"] = cookie
        return {"type": webproxy.EnumProxyType.Continue, "headers": request.headers}

    def on_document_response(self, response: "webproxy.WebResponse") -> Dict[str, Any]:
        content = response.content
        inject_script = (
            "<script src='https://cdn.weread.qq.com/web/%s'></script>\n"
            % self._hook_script_name
        )
        content = content.replace("</head>", inject_script + "</head>")
        return {
            "status": response.status,
            "headers": response.headers,
            "body": content.encode("utf-8"),
        }

    def on_hook_script_request(self, request: "webproxy.WebRequest") -> Dict[str, Any]:
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "hook.js"),
            "rb",
        ) as fp:
            hook_script = fp.read()
            return {
                "type": webproxy.EnumProxyType.Mock,
                "status": 200,
                "headers": {"Content-Type": "application/json"},
                "body": hook_script,
            }

    def on_log_request(self, request: "webproxy.WebRequest") -> Dict[str, Any]:
        self._log_request(request)
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Request-Method": "*",
            "Access-Control-Allow-Headers": "*",
        }
        if request.method == "OPTIONS":
            return {
                "type": webproxy.EnumProxyType.Mock,
                "status": 200,
                "headers": headers,
            }
        if "/hera/logkv" in request.url or "/hera/osslog" in request.url:
            return {
                "type": webproxy.EnumProxyType.Mock,
                "status": 204,
                "headers": headers,
            }
        elif "chlog" in request.url:
            logging.info("[%s] Url %s return mock result" % (self.__class__.__name__, request.url))
            return {
                "type": webproxy.EnumProxyType.Mock,
                "status": 200,
                "headers": headers,
            }
        return {"type": webproxy.EnumProxyType.Block}

    def on_sentry_request(self, request: "webproxy.WebRequest") -> Dict[str, Any]:
        self._log_request(request)
        return {
            "type": webproxy.EnumProxyType.Mock,
            "status": 200,
        }

    def on_single_report_request(
        self, request: "webproxy.WebRequest"
    ) -> Dict[str, Any]:
        self._log_request(request)
        return {
            "type": webproxy.EnumProxyType.Mock,
            "status": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Request-Method": "*",
                "Access-Control-Allow-Headers": "*",
            },
            "body": '{"err_code":0,"msg":"suc"}',
        }

    def on_chapter_request(self, request: "webproxy.WebRequest") -> Dict[str, Any]:
        return {"type": webproxy.EnumProxyType.Continue}

    async def pre_load_page(self) -> None:
        if self._proxy_installed:
            return
        self._proxy_installed = True
        # await self._page.setRequestInterception(True)
        rules = [
            webproxy.ProxyRule("*/hera/*", self.on_log_request),
            webproxy.ProxyRule("*/sentry/*", self.on_sentry_request),
            webproxy.ProxyRule("*/web/book/chapter/*", self.on_chapter_request),
            webproxy.ProxyRule("*/river/single*", self.on_single_report_request),
            webproxy.ProxyRule(
                "*/web/reader/*", self.on_document_request, resource_type="Document"
            ),
            webproxy.ProxyRule(
                "*/web/reader/*",
                self.on_document_response,
                resource_type="Document",
                stage=webproxy.EnumProxyStage.Response,
            ),
            webproxy.ProxyRule(
                "*/web/%s" % self._hook_script_name,
                self.on_hook_script_request,
                resource_type="Script",
            ),
        ]
        proxy = webproxy.WebProxy(self._page, rules)
        await proxy.setup_interception()
        # self._page.on("request", self.handle_request)

    async def get_markdown(self) -> str:
        script = "canvasContextHandler.data.complete;"
        time0 = time.time()
        while time.time() - time0 < 10:
            result = await self._page.evaluate(script)
            if result:
                break
            await asyncio.sleep(1)
        script = "canvasContextHandler.data.markdown;"
        result = await self._page.evaluate(script)
        if not result:
            await self._page.evaluate("canvasContextHandler.updateMarkdown();")
            result = await self._page.evaluate(script)
            if not result:
                raise RuntimeError("Wait for creating markdown timeout")
        return result

    async def _check_next_page(self) -> None:
        while True:
            try:
                await self.wait_for_selector("button.readerFooter_button", timeout=60)
            except pyppeteer.errors.TimeoutError:
                logging.info("[%s] load selector timeout " % self.__class__.__name__)
                break
            result = await self._page.evaluate(
                "document.getElementsByClassName('readerFooter_button')[0].innerText;"
            )
            if result == "下一页":
                logging.info("[%s] Go to next page" % self.__class__.__name__)
                await self._page.evaluate(
                    r"canvasContextHandler.data.markdown += '\n\n';"
                )
                await self.pre_load_page()
                await self._page.click("button.readerFooter_button")
                await asyncio.sleep(1)
            elif result == "下一章":
                break
            elif result.startswith("登录"):
                raise utils.LoginRequiredError()
            else:
                raise NotImplementedError(result)

    def _get_chapter_url(self, chapter_id: str) -> str:
        return "%s%sk%s" % (
            self._chapter_root_url,
            self._book_id,
            utils.wr_hash(str(chapter_id)),
        )

    async def goto_chapter(self, chapter_id: str, timeout: int = 120) -> None:
        logging.info("[%s] Go to chapter %s" % (self.__class__.__name__, chapter_id))
        # await self.clear_cache()
        await self.pre_load_page()
        self._url = self._get_chapter_url(chapter_id)
        await self._page.goto(self._url, timeout=1000 * timeout)
        try:
            await self._check_next_page()
        except utils.LoginRequiredError:
            await self.login()
            return await self.goto_chapter(chapter_id, timeout=timeout)

    async def clear_cache(self) -> None:
        await self._page.evaluate("canvasContextHandler.clearCanvasCache();")
