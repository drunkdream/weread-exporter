"""
WebRead WebPage
"""

import asyncio
import json
import logging
import os
import random
import sys
import time
import urllib.parse

import pyppeteer

from . import utils


class WeReadWebPage(object):
    """WebRead WebPage"""

    root_url = "https://weread.qq.com"
    window_size = (1920, 1080)

    def __init__(self, book_id, webcache_path=None, profile_path=None):
        self._book_id = book_id
        self._cookie = {}
        self._webcache_path = webcache_path or "cache"
        if not os.path.isdir(self._webcache_path):
            os.makedirs(self._webcache_path)
        self._profile_path = profile_path or os.path.join(self._webcache_path, "chrome_profile")
        self._home_url = "%s/web/bookDetail/%s" % (
            self.__class__.root_url,
            book_id,
        )
        self._chapter_root_url = self.__class__.root_url + "/web/reader/"
        self._browser = None
        self._page = None
        self._url = ""

    async def get_book_info(self):
        html = (await utils.fetch(self._home_url)).decode()
        pos1 = html.find("window.__INITIAL_STATE__")
        if pos1 <= 0:
            raise RuntimeError("Unexpected html: %s" % self._html)
        pos1 = html.find("=", pos1)
        pos2 = html.find("};", pos1)
        data = html[pos1 + 1 : pos2 + 1].strip()
        data = json.loads(data)
        book_info = {}
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

    async def get_user_info(self):
        vid = self._cookie.get("wr_vid")
        if not vid:
            raise utils.InvalidUserError("Invalid cookie: %s" % self._format_cookie())
        url = "%s/web/user?userVid=%s" % (self.__class__.root_url, vid)
        headers = {"Referer": self.__class__.root_url, "Cookie": self._format_cookie()}
        rsp = await utils.fetch(url, headers=headers)
        rsp = json.loads(rsp.decode())
        if rsp.get("errCode") == -2012:
            _, rsp_headers, _ = await utils.fetch(
                self.__class__.root_url, headers=headers, respond_with_headers=True
            )
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
            headers["Cookie"] = self._format_cookie()
            rsp = await utils.fetch(url, headers=headers)
            rsp = json.loads(rsp.decode())
        elif rsp.get("errCode") == -2010:
            # 用户不存在
            raise utils.InvalidUserError("User %s not found" % vid)
        elif rsp.get("errCode"):
            raise RuntimeError("Get user info failed: %s" % rsp)
        return rsp

    def _format_cookie(self, cookie=""):
        cookies = []
        if cookie:
            cookies.append(cookie)
        for key in self._cookie:
            cookies.append("%s=%s" % (key, self._cookie[key]))
        return "; ".join(cookies)

    async def _read_cookie(self):
        cookies = await self._page.cookies()
        cookie_map = {}
        for cookie in cookies:
            cookie_map[cookie["name"]] = cookie["value"]
        return cookie_map

    async def _update_cookie(self):
        self._cookie = await self._read_cookie()

    async def check_valid(self):
        html = await utils.fetch(self._home_url)
        if b'"soldout":1' in html:
            return False
        return True

    def has_profile(self):
        """Check if Chrome profile exists (indicates previous login attempt)."""
        cookies_db = os.path.join(self._profile_path, "Default", "Cookies")
        return os.path.isfile(cookies_db)

    def _check_chrome(self):
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

    async def launch(
        self,
        headless=False,
        force_login=False,
        mock_user_agent=False,
        proxy_server=None
    ):
        logging.info("[%s] Launch url %s" % (self.__class__.__name__, self._home_url))
        chrome = self._check_chrome()
        args = ["--no-first-run", "--remote-allow-origins=*"]
        if headless:
            args.append("--headless")
            if sys.platform == "linux" and os.getuid() == 0:
                args.append("--no-sandbox")
        args.append("--user-data-dir=%s" % self._profile_path)
        if not headless:
            args.append("--window-size=%d,%d" % self.__class__.window_size)
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
                        console.trace();
                        return undefined;
                    }
                });
                var _hasOwnProperty = Object.prototype.hasOwnProperty;
                Object.prototype.hasOwnProperty = function (key) {
                    if (key === 'webdriver') {
                        console.log('hasOwnProperty', key, 'is called');
                        console.trace();
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
                "width": 1920,
                "height": 1080,
                "deviceScaleFactor": 1,
            }
        )

        # Navigate to page - Chrome profile handles cookies automatically
        await self._page.goto(self._home_url)

        # Read cookies from browser after navigation
        await self._update_cookie()

        # Check if logged in
        is_logged_in = False
        if self._cookie.get("wr_vid"):
            try:
                user_info = await self.get_user_info()
                logging.info(
                    "[%s] Current login user is %s"
                    % (self.__class__.__name__, user_info.get("name", "Anonymous"))
                )
                is_logged_in = True
            except utils.InvalidUserError as ex:
                logging.warning(
                    "[%s] Get user error: %s" % (self.__class__.__name__, ex)
                )
                self._cookie = {}

        if force_login and not is_logged_in:
            await self.login()
            is_logged_in = True

        self._page.on("console", self.handle_log)
        return is_logged_in

    async def close(self):
        if self._browser:
            await self._browser.close()
            self._browser = self._page = None

    async def get_html(self):
        return await self._page.evaluate("document.documentElement.outerHTML;")

    async def screenshot(self, save_path):
        await self._page.screenshot({"path": save_path})

    async def wait_for_selector(self, selector, timeout=30):
        try:
            return await self._page.waitForSelector(selector, timeout=timeout)
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

    def handle_log(self, message):
        with open("%s.log" % self._book_id, "a+", encoding="utf-8") as fp:
            fp.write("[%s] %s\n" % (self._url, message.text))

    async def wait_for_avatar(self, timeout=30):
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

    async def login(self):
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
                return True
            else:
                raise RuntimeError("Login timeout")
        return False

    async def _get_from_cache_or_server(self, url, headers=None):
        u = urllib.parse.urlparse(url)
        path = os.path.join(
            self._webcache_path, "resources", u.path[1:].replace("/", os.sep)
        )
        if os.path.isfile(path):
            with open(path, "rb") as fp:
                return 200, {}, fp.read()

        dirpath = os.path.dirname(path)
        if not os.path.isdir(dirpath):
            os.makedirs(dirpath)
        status, headers, body = await utils.fetch(
            url, headers=headers, respond_with_headers=True
        )
        if status == 200:
            with open(path, "wb") as fp:
                fp.write(body)
        return status, headers, body

    def _handle_request_headers(self, url, headers):
        for key in ("baggage", "sentry-trace"):
            headers.pop(key, None)
        cookie = ""
        if "/web/reader/" in url:
            cookie = "wr_useHorizonReader=0"
        headers["cookie"] = self._format_cookie(cookie)
        return headers

    def _handle_response_headers(self, url, headers):
        if "oss.weread.qq.com" in url:
            headers["Access-Control-Allow-Origin"] = "*"
            headers["Access-Control-Request-Method"] = "*"
            headers["Access-Control-Allow-Headers"] = "*"
        return headers

    def _handle_http_body(self, url, body):
        if url.startswith(self._chapter_root_url):
            inject_script = (
                "<script src='https://cdn.weread.qq.com/web/1.392ec47a.js'></script>\n"
            )
            return body.replace(b"</head>", inject_script.encode() + b"</head>")
        return body

    async def _handle_request(self, request):
        if request.url.startswith("chrome-extension://"):
            return await request.continue_()

        if "/web/1.392ec47a.js" in request.url:
            with open(
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "hook.js"),
                "rb",
            ) as fp:
                hook_script = fp.read()
                response = {
                    "status": 200,
                    "headers": {"Content-Type": "application/json"},
                    "body": hook_script,
                }
                return await request.respond(response)

        urlobj = urllib.parse.urlparse(request.url)
        is_resource_file = urlobj.path.endswith(
            (".js", ".css", ".jpg", ".png", ".gif", ".svg")
        )
        status = 200
        headers = {
            "Server": "nginx/1.20.2",
        }
        body = b""
        if request.method == "OPTIONS":
            headers = {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Request-Method": "*",
                "Access-Control-Allow-Headers": "*",
            }
        elif request.method == "GET" and is_resource_file:
            status, headers, body = await self._get_from_cache_or_server(request.url)
        elif "/web/book/read" in request.url:
            body = b'{"succ":1,"synckey":%d}' % random.randint(10000000, 100000000)
            headers["Content-Type"] = "application/json; charset=utf-8"
            headers["Content-Length"] = str(len(body))
            logging.info(
                "[%s][%s] Url %s return mock data"
                % (self.__class__.__name__, request.method, request.url)
            )
        elif "sentry_key=" in request.url:
            status = 200
            headers["Content-Type"] = "application/json; charset=utf-8"
            headers["Content-Length"] = str(len(body))
            body = b"{}"
            logging.info(
                "[%s][%s] Url %s return mock data"
                % (self.__class__.__name__, request.method, request.url)
            )
        elif "/hera/logkv" in request.url or "/hera/osslog" in request.url:
            status = 204
        elif "/hera/chlog" in request.url:
            body = b'{"ret":0}'
            headers["Content-Type"] = "application/json; charset=utf-8"
            headers["Content-Length"] = str(len(body))
            logging.info(
                "[%s][%s] Url %s return mock data"
                % (self.__class__.__name__, request.method, request.url)
            )
        elif "hijack_csp_report" in request.url:
            return
        elif "/river/single" in request.url:
            body = b'{"err_code":0,"msg":"suc"}'
            headers["Content-Type"] = "application/json; charset=utf-8"
            headers["Content-Length"] = len(body)
            logging.info(
                "[%s][%s] Url %s return mock data"
                % (self.__class__.__name__, request.method, request.url)
            )
        else:
            logging.info(
                "[%s][%s] Fetch url %s"
                % (self.__class__.__name__, request.method, request.url)
            )
            headers = self._handle_request_headers(request.url, request.headers)
            time0 = time.time()
            status, headers, body = await utils.fetch(
                request.url,
                method=request.method,
                headers=headers,
                data=request.postData,
                respond_with_headers=True,
            )
            headers = dict(headers)
            logging.info(
                "[%s][%s][%.2f] Url %s return %d, body len is %d"
                % (
                    self.__class__.__name__,
                    request.method,
                    time.time() - time0,
                    request.url,
                    status,
                    len(body),
                )
            )
            if "Content-Security-Policy" in headers:
                logging.info(
                    "[%s][%s] Url %s has Content-Security-Policy: %s"
                    % (
                        self.__class__.__name__,
                        request.method,
                        request.url,
                        headers["Content-Security-Policy"],
                    )
                )
                headers.pop("Content-Security-Policy")

        headers = self._handle_response_headers(request.url, headers)
        response = {
            "status": status,
            "headers": headers,
            "body": self._handle_http_body(request.url, body),
        }
        return await request.respond(response)

    def handle_request(self, request):
        asyncio.ensure_future(self._handle_request(request))

    async def pre_load_page(self):
        await self._page.setRequestInterception(True)
        self._page.on("request", self.handle_request)

    async def get_markdown(self, timeout=30):
        script = "canvasContextHandler.data.complete;"
        time0 = time.time()
        while time.time() - time0 < timeout:
            result = await self._page.evaluate(script)
            if result:
                break
            await asyncio.sleep(1)
        else:
            logging.warning("[%s] Timeout waiting for canvasContextHandler.data.complete" % self.__class__.__name__)

        script = "canvasContextHandler.data.markdown;"
        result = await self._page.evaluate(script)
        if not result:
            logging.info("[%s] Trying updateMarkdown fallback" % self.__class__.__name__)
            await self._page.evaluate("canvasContextHandler.updateMarkdown();")
            await asyncio.sleep(2)
            result = await self._page.evaluate(script)
            if not result:
                # Check if canvasContextHandler exists
                exists = await self._page.evaluate("typeof canvasContextHandler !== 'undefined';")
                if not exists:
                    raise RuntimeError("canvasContextHandler not found - hook.js may not be loaded")
                raise RuntimeError("Wait for creating markdown timeout")
        return result

    async def _check_next_page(self):
        while True:
            try:
                await self.wait_for_selector(
                    "button.readerFooter_button", timeout=60000
                )
            except pyppeteer.errors.TimeoutError:
                logging.warning("[%s] Footer button selector timeout - page may not have loaded correctly" % self.__class__.__name__)
                # Check if canvasContextHandler has any data
                has_data = await self._page.evaluate(
                    "typeof canvasContextHandler !== 'undefined' && canvasContextHandler.data.markdown.length > 0;"
                )
                if has_data:
                    logging.info("[%s] canvasContextHandler has data, continuing" % self.__class__.__name__)
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

    def _get_chapter_url(self, chapter_id):
        return "%s%sk%s" % (
            self._chapter_root_url,
            self._book_id,
            utils.wr_hash(str(chapter_id)),
        )

    async def goto_chapter(self, chapter_id, timeout=120):
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

    async def clear_cache(self):
        await self._page.evaluate("canvasContextHandler.clearCanvasCache();")
