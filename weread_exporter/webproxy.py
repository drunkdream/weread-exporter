"""
Web Proxy
"""

import asyncio
import json
import logging
import re
import traceback

import aiohttp
import pyppeteer


class EnumResourceType(object):
    """资源类型"""

    Document = "Document"
    Stylesheet = "Stylesheet"
    Image = "Image"
    Media = "Media"
    Font = "Font"
    Script = "Script"
    TextTrack = "TextTrack"
    XHR = "XHR"
    Fetch = "Fetch"
    Prefetch = "Prefetch"
    EventSource = "EventSource"
    WebSocket = "WebSocket"
    Manifest = "Manifest"
    SignedExchange = "SignedExchange"
    Ping = "Ping"
    CSPViolationReport = "CSPViolationReport"
    Preflight = "Preflight"
    FedCM = "FedCM"
    Other = "Other"


class EnumProxyStage(object):
    """代理阶段"""

    Request = "request"
    Response = "response"


class EnumProxyType(object):
    """代理类型"""

    Block = 1
    Continue = 2
    Mock = 3


class ProxyRule(object):
    """代理规则基类

    用于定义请求拦截规则和响应处理逻辑
    """

    def __init__(
        self, url_pattern, callback, resource_type=None, stage=None, methods=None
    ):
        """初始化代理规则

        Args:
            url_pattern: URL 匹配模式，支持通配符 *
            resource_type: 资源类型，如 'Document', 'Script', 'Stylesheet', 'Image', 'XHR', 'Fetch', 'WebSocket' 等
            methods: HTTP 方法列表，如 ['GET', 'POST']，None 表示匹配所有方法
        """
        self._url_pattern = url_pattern
        self._callback = callback
        self._resource_type = resource_type
        self._stage = stage or EnumProxyStage.Request
        self._methods = methods or []

    @property
    def stage(self):
        """拦截阶段"""
        return self._stage

    def matches(self, request):
        """检查请求是否匹配此规则

        Args:
            request: pyppeteer 的 Request 对象（用于匹配）或 WebRequest 对象

        Returns:
            bool: 是否匹配
        """
        # 支持 pyppeteer Request 和 WebRequest 两种类型
        if hasattr(request, "_url"):
            # WebRequest 对象
            url = request.url
            method = request.method
        else:
            # pyppeteer Request 对象
            url = request.url
            method = request.method

        # 检查 URL 模式
        if not self._match_url(url):
            return False

        # 检查 HTTP 方法
        if self._methods and method not in self._methods:
            return False

        return True

    def _match_url(self, url):
        """匹配 URL 模式

        支持 * 通配符，如 '*/web/book/read*' 或 '*/weread.qq.com/*'

        Args:
            url: 实际的 URL

        Returns:
            bool: 是否匹配
        """
        pattern = self._url_pattern.replace("*", ".*")
        # 确保模式匹配完整字符串
        if not pattern.startswith(".*"):
            pattern = "^.*" + pattern
        if not pattern.endswith(".*"):
            pattern = pattern + ".*$"

        return re.match(pattern, url) is not None

    async def handle_request(self, request):
        """处理请求，返回响应

        调用 callback 函数并返回其结果。支持同步和异步 callback。

        Args:
            request (WebRequest): WebRequest 请求对象

        Returns:
            dict: 包含响应信息的字典，格式为 {
                'status': int,
                'headers': dict,
                'body': bytes
            }
            或者 None 表示不处理此请求（继续原请求）
        """
        # 调用 callback 函数
        try:
            result = self._callback(request)

            # 如果 callback 是协程，等待其完成
            if asyncio.iscoroutine(result):
                result = await result
        except Exception as ex:
            logging.warning(
                "[%s] Handle request [%s]%s failed: \n%s"
                % (
                    self.__class__.__name__,
                    request.method,
                    request.url,
                    traceback.format_exc(),
                )
            )
            return {"type": EnumProxyType.Continue}
        return result

    async def handle_response(self, response):
        """处理响应

        调用 callback 函数处理响应。支持同步和异步 callback。

        Args:
            response (WebResponse): WebResponse 响应对象

        Returns:
            dict: 包含自定义响应信息的字典，格式为 {
                'status': int,
                'headers': dict,
                'body': bytes
            }
            或者 None 表示不修改响应
        """
        try:
            result = self._callback(response)

            # 如果 callback 是协程，等待其完成
            if asyncio.iscoroutine(result):
                result = await result
        except Exception as ex:
            logging.warning(
                "[%s] Handle response for %s failed: \n%s"
                % (self.__class__.__name__, response.url, traceback.format_exc())
            )
            return None

        return result

    def get_interception_pattern(self):
        """获取用于 CDP Network.setRequestInterception 的模式

        Returns:
            dict: CDP 拦截模式
        """
        pattern = {"urlPattern": self._url_pattern}
        if self._resource_type:
            pattern["resourceType"] = self._resource_type
        if self._stage != EnumProxyStage.Request:
            pattern["interceptionStage"] = "Response"
        return pattern


class WebRequest:
    """Web请求封装类

    封装HTTP请求的基本信息，包括URL、方法、请求头和请求体。
    用于在代理处理中传递请求信息。
    """

    def __init__(self, url, method, headers, body):
        """初始化 WebRequest

        Args:
            url (str): 请求的URL地址
            method (str): HTTP请求方法（GET、POST等）
            headers (dict): 请求头字典
            body (bytes): 请求体内容
        """
        self._url = url
        self._method = method
        self._headers = headers
        self._body = body

    @staticmethod
    def from_request(request):
        """从 pyppeteer 的 Request 对象创建 WebRequest 对象

        Args:
            request: pyppeteer 的 Request 对象

        Returns:
            WebRequest: 新创建的 WebRequest 对象
        """
        # 获取请求 URL
        url = request.url

        # 获取请求方法
        method = request.method if request.method else "GET"

        # 获取请求头
        headers = dict(request.headers) if request.headers else {}

        # 获取请求体（POST 数据）
        body = None
        if request.postData:
            if isinstance(request.postData, bytes):
                body = request.postData
            else:
                body = request.postData.encode("utf-8")

        return WebRequest(url=url, method=method, headers=headers, body=body)

    @property
    def url(self):
        """获取请求URL"""
        return self._url

    @property
    def method(self):
        """获取HTTP请求方法"""
        return self._method

    @property
    def headers(self):
        """获取请求头字典"""
        return self._headers

    @property
    def body(self):
        """获取请求体内容"""
        return self._body

    @property
    def content(self):
        if self._body:
            return self._body.decode("utf-8")
        return ""


class WebResponse:
    """Web请求响应类"""

    def __init__(self, request, status, headers, body):
        """初始化

        Args:
            request: WebRequest 对象
            status (int): HTTP 状态码
            headers (dict): 响应头字典
            body (bytes): 响应体内容
        """
        self._request = request
        self._status = status
        self._headers = {k.lower(): v for k, v in headers.items()}
        self._body = body

    @property
    def url(self):
        """获取响应对应的URL"""
        return self._request.url

    @property
    def status(self):
        """HTTP状态码"""
        return self._status

    @property
    def ok(self):
        """判断响应是否成功

        Returns:
            bool: 如果状态码在200-299范围内返回True，否则返回False
        """
        return self._status == 0 or 200 <= self._status <= 299

    @property
    def status(self):
        """获取HTTP状态码"""
        return self._status

    @property
    def headers(self):
        """获取响应头字典

        所有header名称都是小写的。
        """
        return self._headers

    @property
    def body(self):
        return self._body

    @property
    def content(self):
        if self._body:
            return self._body.decode("utf-8")
        return ""

    @property
    def request(self):
        """获取关联的 Request 对象"""
        return self._request


class WebProxy(object):
    """Web Proxy

    使用代理规则处理网络请求拦截和响应
    """

    def __init__(self, page, proxy_rules):
        """初始化 Web 代理

        Args:
            page: pyppeteer.page.Page 实例
            proxy_rules: ProxyRule 对象列表
        """
        self._page = page
        self._client = page._client
        self._proxy_rules = proxy_rules

    async def setup_interception(self):
        """启用网络请求拦截

        使用 CDP API 直接拦截网络请求，不依赖 pyppeteer 的内部实现。
        这样可以：
        1. 自定义匹配模式（避免 '*' 硬编码）
        2. 直接接收 requestIntercepted 事件（确保 requestId 可见）
        """
        logging.info("[%s] Setup interception" % self.__class__.__name__)
        self._page._networkManager._userRequestInterceptionEnabled = True
        self._page._networkManager._protocolRequestInterceptionEnabled = True
        patterns = []
        for rule in self._proxy_rules:
            patterns.append(rule.get_interception_pattern())

        await asyncio.gather(
            self._client.send(
                "Network.setCacheDisabled",
                {"cacheDisabled": True},
            ),
            self._client.send(
                "Network.setRequestInterception",
                {"patterns": patterns},
            ),
            # 启用 Fetch domain 以支持 Response 阶段的拦截
            # self._client.send(
            #     'Fetch.enable',
            #     {
            #         'patterns': patterns
            #     }
            # )
        )

        self._page.on(
            "request", lambda req: asyncio.ensure_future(self.handle_request(req))
        )
        # self._page.on('response', lambda res: asyncio.ensure_future(
        #     self.handle_response(res)
        # ))

    async def get_http_response(self, request):
        """通过aiohttp获取http返回包，返回WebResponse对象

        Args:
            request (WebRequest): WebRequest 请求对象

        Returns:
            WebResponse 对象
        """
        # 获取请求 URL
        print("get_http_response", request.url)
        url = request.url

        # 获取请求头并转换为字典
        headers = {}
        for key, value in request.headers.items():
            headers[key] = value

        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method=request.method,
                    url=url,
                    headers=headers,
                    allow_redirects=True,
                ) as response:
                    # 获取响应头
                    response_headers = {}
                    for key, value in response.headers.items():
                        response_headers[key] = value

                    # 读取响应体
                    body = await response.read()

                    # 返回 WebResponse 对象
                    return WebResponse(
                        request=request,
                        status=response.status,
                        headers=response_headers,
                        body=body,
                    )
        except Exception as ex:
            logging.warning(
                "[WebProxy] Get HTTP response failed for %s: %s" % (url, str(ex))
            )
            return None

    def get_rule(self, request):
        """获取与request匹配的规则

        Args:
            request: pyppeteer 的 Request 对象

        Returns:
            tuple: (request_rule, response_rule)
        """
        request_rule = None
        response_rule = None

        # 遍历所有规则，查找匹配的规则
        for rule in self._proxy_rules:
            if rule.matches(request):
                if rule.stage == EnumProxyStage.Request and request_rule is None:
                    request_rule = rule
                elif rule.stage == EnumProxyStage.Response and response_rule is None:
                    response_rule = rule

        return request_rule, response_rule

    async def handle_request(self, request):
        """处理请求

        遍历所有代理规则，找到第一个匹配的规则并调用其 handle 方法

        Args:
            request: pyppeteer 的 Request 对象
        """
        if request._interceptionHandled:
            logging.warning(
                "[%s] Ignore handled request %s %s %s"
                % (
                    self.__class__.__name__,
                    request.method,
                    request.resourceType,
                    request.url,
                )
            )
            return
        logging.info(
            "[%s] Handle request %s %s %s"
            % (
                self.__class__.__name__,
                request.method,
                request.resourceType,
                request.url,
            )
        )
        request_rule, response_rule = self.get_rule(request)
        if request_rule:
            # 将 pyppeteer Request 转换为 WebRequest
            web_request = WebRequest.from_request(request)
            result = await request_rule.handle_request(web_request)
            if not isinstance(result, dict):
                logging.warning(
                    "[WebProxy] Unexpected return type %s from callback, continuing request: %s"
                    % (type(result), request.url)
                )
                await request.continue_()
                return
            proxy_type = result.pop("type", 0)
            if proxy_type == EnumProxyType.Mock:
                await request.respond(result)
                return
            elif proxy_type == EnumProxyType.Block:
                await request.abort()
                return
            elif not response_rule:
                await request.continue_()
                return

            response = await self.get_http_response(web_request)
            if not response:
                # 没有获取到回包
                await request.continue_()
                return
            result = await response_rule.handle_response(response)
            if result:
                await request.respond(result)
            else:
                await request.continue_()
            return

        # 没有匹配的 request 规则，继续原请求
        logging.info(
            "[WebProxy] No request rule matched, continue request: %s" % request.url
        )
        await request.continue_()

    def get_interception_patterns(self):
        """获取所有规则的拦截模式

        Returns:
            list: CDP 拦截模式列表
        """
        patterns = []
        for rule in self._rules:
            patterns.append(rule.get_interception_pattern())
        return patterns
