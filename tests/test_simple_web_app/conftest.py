import os
import unittest.mock
from collections.abc import AsyncGenerator

import pytest


@pytest.fixture()
def test_env() -> dict[str, str]:
    return {
        "DEBUG": "true",
        "DATABASE_PATH": ":memory:",
    }


import typing
import anyio
import httpx
import math
import io
import contextlib
from urllib.parse import unquote, urljoin
from anyio.streams.stapled import StapledObjectStream
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.testclient import ASGI3App, _RequestData, _is_asgi3


class AsyncWebSocketTestSession:
    def __init__(
        self,
        app: ASGI3App,
        scope: Scope,
    ) -> None:
        self.app = app
        self.scope = scope
        self.accepted_subprotocol = None
        self.extra_headers = None

    async def __aenter__(self) -> "AsyncWebSocketTestSession":
        async with contextlib.AsyncExitStack() as stack:
            task_group = await stack.enter_async_context(anyio.create_task_group())
            self.done = anyio.Event()

            async def run(*, task_status: anyio.abc.TaskStatus[anyio.CancelScope]) -> None:
                await self._run(task_status=task_status)
                self.done.set()

            await task_group.start(run)
            stack.push_async_callback(self.done.wait)
            stack.callback(task_group.cancel_scope.cancel)
            await self.send({"type": "websocket.connect"})
            message = await self.receive()
            await self._raise_on_close(message)
            self.accepted_subprotocol = message.get("subprotocol", None)
            self.extra_headers = message.get("headers", None)
            stack.push_async_callback(self.aclose, 1000)
            self.exit_stack = stack.pop_all()
        return self

    async def __aexit__(self, *args: typing.Any) -> bool | None:
        return await self.exit_stack.__aexit__(*args)

    async def _run(self, *, task_status: anyio.abc.TaskStatus[anyio.CancelScope]) -> None:
        send: anyio.create_memory_object_stream[Message] = anyio.create_memory_object_stream(math.inf)
        send_tx, send_rx = send
        receive: anyio.create_memory_object_stream[Message] = anyio.create_memory_object_stream(math.inf)
        receive_tx, receive_rx = receive
        with send_tx, send_rx, receive_tx, receive_rx, anyio.CancelScope() as cs:
            self._receive_tx = receive_tx
            self._send_rx = send_rx
            task_status.started(cs)
            await self.app(self.scope, receive_rx.receive, send_tx.send)

            # wait for cs.cancel to be called before closing streams
            await anyio.sleep_forever()

    async def _raise_on_close(self, message: Message) -> None:
        if message["type"] == "websocket.close":
            raise WebSocketDisconnect(code=message.get("code", 1000), reason=message.get("reason", ""))
        elif message["type"] == "websocket.http.response.start":
            status_code: int = message["status"]
            headers: list[tuple[bytes, bytes]] = message["headers"]
            body: list[bytes] = []
            while True:
                message = await self.receive()
                assert message["type"] == "websocket.http.response.body"
                body.append(message["body"])
                if not message.get("more_body", False):
                    break
            raise WebSocketDenialResponse(status_code=status_code, headers=headers, content=b"".join(body))

    async def send(self, message: Message) -> None:
        await self._receive_tx.send(message)

    async def send_text(self, data: str) -> None:
        await self.send({"type": "websocket.receive", "text": data})

    async def send_bytes(self, data: bytes) -> None:
        await self.send({"type": "websocket.receive", "bytes": data})

    async def send_json(self, data: typing.Any, mode: typing.Literal["text", "binary"] = "text") -> None:
        text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        if mode == "text":
            await self.send({"type": "websocket.receive", "text": text})
        else:
            await self.send({"type": "websocket.receive", "bytes": text.encode("utf-8")})

    async def aclose(self, code: int = 1000, reason: str | None = None) -> None:
        await self.send({"type": "websocket.disconnect", "code": code, "reason": reason})

    async def receive(self) -> Message:
        return await self._send_rx.receive()

    async def receive_text(self) -> str:
        message = await self.receive()
        await self._raise_on_close(message)
        return typing.cast(str, message["text"])

    async def receive_bytes(self) -> bytes:
        message = await self.receive()
        await self._raise_on_close(message)
        return typing.cast(bytes, message["bytes"])

    async def receive_json(self, mode: typing.Literal["text", "binary"] = "text") -> typing.Any:
        message = await self.receive()
        await self._raise_on_close(message)
        if mode == "text":
            text = message["text"]
        else:
            text = message["bytes"].decode("utf-8")
        return json.loads(text)


class _AsyncTestClientTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        app: ASGI3App,
        raise_server_exceptions: bool = True,
        root_path: str = "",
        *,
        client: tuple[str, int],
        app_state: dict[str, typing.Any],
    ) -> None:
        self.app = app
        self.raise_server_exceptions = raise_server_exceptions
        self.root_path = root_path
        self.app_state = app_state
        self.client = client

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        scheme = request.url.scheme
        netloc = request.url.netloc.decode(encoding="ascii")
        path = request.url.path
        raw_path = request.url.raw_path
        query = request.url.query.decode(encoding="ascii")

        default_port = {"http": 80, "ws": 80, "https": 443, "wss": 443}[scheme]

        if ":" in netloc:
            host, port_string = netloc.split(":", 1)
            port = int(port_string)
        else:
            host = netloc
            port = default_port

        # Include the 'host' header.
        if "host" in request.headers:
            headers: list[tuple[bytes, bytes]] = []
        elif port == default_port:  # pragma: no cover
            headers = [(b"host", host.encode())]
        else:  # pragma: no cover
            headers = [(b"host", (f"{host}:{port}").encode())]

        # Include other request headers.
        headers += [(key.lower().encode(), value.encode()) for key, value in request.headers.multi_items()]

        scope: dict[str, typing.Any]

        if scheme in {"ws", "wss"}:
            subprotocol = request.headers.get("sec-websocket-protocol", None)
            if subprotocol is None:
                subprotocols: typing.Sequence[str] = []
            else:
                subprotocols = [value.strip() for value in subprotocol.split(",")]
            scope = {
                "type": "websocket",
                "path": unquote(path),
                "raw_path": raw_path.split(b"?", 1)[0],
                "root_path": self.root_path,
                "scheme": scheme,
                "query_string": query.encode(),
                "headers": headers,
                "client": self.client,
                "server": [host, port],
                "subprotocols": subprotocols,
                "state": self.app_state.copy(),
                "extensions": {"websocket.http.response": {}},
            }
            session = AsyncWebSocketTestSession(self.app, scope)
            raise _AsyncUpgrade(session)

        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": request.method,
            "path": unquote(path),
            "raw_path": raw_path.split(b"?", 1)[0],
            "root_path": self.root_path,
            "scheme": scheme,
            "query_string": query.encode(),
            "headers": headers,
            "client": self.client,
            "server": [host, port],
            "extensions": {"http.response.debug": {}},
            "state": self.app_state.copy(),
        }

        request_complete = False
        response_started = False
        response_complete: anyio.Event
        raw_kwargs: dict[str, typing.Any] = {"stream": io.BytesIO()}
        template = None
        context = None

        async def receive() -> Message:
            nonlocal request_complete

            if request_complete:
                if not response_complete.is_set():
                    await response_complete.wait()
                return {"type": "http.disconnect"}

            body = request.read()
            if isinstance(body, str):
                body_bytes: bytes = body.encode("utf-8")  # pragma: no cover
            elif body is None:
                body_bytes = b""  # pragma: no cover
            elif isinstance(body, GeneratorType):
                try:  # pragma: no cover
                    chunk = body.send(None)
                    if isinstance(chunk, str):
                        chunk = chunk.encode("utf-8")
                    return {"type": "http.request", "body": chunk, "more_body": True}
                except StopIteration:  # pragma: no cover
                    request_complete = True
                    return {"type": "http.request", "body": b""}
            else:
                body_bytes = body

            request_complete = True
            return {"type": "http.request", "body": body_bytes}

        async def send(message: Message) -> None:
            nonlocal raw_kwargs, response_started, template, context

            if message["type"] == "http.response.start":
                assert not response_started, 'Received multiple "http.response.start" messages.'
                raw_kwargs["status_code"] = message["status"]
                raw_kwargs["headers"] = [(key.decode(), value.decode()) for key, value in message.get("headers", [])]
                response_started = True
            elif message["type"] == "http.response.body":
                assert response_started, 'Received "http.response.body" without "http.response.start".'
                assert not response_complete.is_set(), 'Received "http.response.body" after response completed.'
                body = message.get("body", b"")
                more_body = message.get("more_body", False)
                if request.method != "HEAD":
                    raw_kwargs["stream"].write(body)
                if not more_body:
                    raw_kwargs["stream"].seek(0)
                    response_complete.set()
            elif message["type"] == "http.response.debug":
                template = message["info"]["template"]
                context = message["info"]["context"]

        try:
            response_complete = anyio.Event()
            await self.app(scope, receive, send)
        except BaseException as exc:
            if self.raise_server_exceptions:
                raise exc

        if self.raise_server_exceptions:
            assert response_started, "TestClient did not receive any response."
        elif not response_started:
            raw_kwargs = {
                "status_code": 500,
                "headers": [],
                "stream": io.BytesIO(),
            }

        raw_kwargs["stream"] = httpx.ByteStream(raw_kwargs["stream"].read())

        response = httpx.Response(**raw_kwargs, request=request)
        if template is not None:
            response.template = template  # type: ignore[attr-defined]
            response.context = context  # type: ignore[attr-defined]
        return response


class _AsyncUpgrade(Exception):
    def __init__(self, session: AsyncWebSocketTestSession) -> None:
        self.session = session


class AsyncTestClient(httpx.AsyncClient):
    __test__ = False

    def __init__(
        self,
        app: ASGIApp,
        base_url: str = "http://testserver",
        raise_server_exceptions: bool = True,
        root_path: str = "",
        cookies: httpx._types.CookieTypes | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = True,
        client: tuple[str, int] = ("testclient", 50000),
    ) -> None:
        if _is_asgi3(app):
            asgi_app = app
        else:
            app = typing.cast(ASGI2App, app)  # type: ignore[assignment]
            asgi_app = _WrapASGI2(app)  # type: ignore[arg-type]
        self.app = asgi_app
        self.app_state: dict[str, typing.Any] = {}
        transport = _AsyncTestClientTransport(
            self.app,
            raise_server_exceptions=raise_server_exceptions,
            root_path=root_path,
            app_state=self.app_state,
            client=client,
        )
        if headers is None:
            headers = {}
        headers.setdefault("user-agent", "testclient")
        super().__init__(
            base_url=base_url,
            headers=headers,
            transport=transport,
            follow_redirects=follow_redirects,
            cookies=cookies,
        )

    async def request(  # type: ignore[override]
        self,
        method: str,
        url: httpx._types.URLTypes,
        *,
        content: httpx._types.RequestContent | None = None,
        data: _RequestData | None = None,
        files: httpx._types.RequestFiles | None = None,
        json: typing.Any = None,
        params: httpx._types.QueryParamTypes | None = None,
        headers: httpx._types.HeaderTypes | None = None,
        cookies: httpx._types.CookieTypes | None = None,
        auth: httpx._types.AuthTypes | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        follow_redirects: bool | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        timeout: httpx._types.TimeoutTypes | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        extensions: dict[str, typing.Any] | None = None,
    ) -> httpx.Response:
        if timeout is not httpx.USE_CLIENT_DEFAULT:
            warnings.warn(
                "You should not use the 'timeout' argument with the TestClient. "
                "See https://github.com/encode/starlette/issues/1108 for more information.",
                DeprecationWarning,
            )
        url = self._merge_url(url)
        return await super().request(
            method,
            url,
            content=content,
            data=data,
            files=files,
            json=json,
            params=params,
            headers=headers,
            cookies=cookies,
            auth=auth,
            follow_redirects=follow_redirects,
            timeout=timeout,
            extensions=extensions,
        )

    async def get(  # type: ignore[override]
        self,
        url: httpx._types.URLTypes,
        *,
        params: httpx._types.QueryParamTypes | None = None,
        headers: httpx._types.HeaderTypes | None = None,
        cookies: httpx._types.CookieTypes | None = None,
        auth: httpx._types.AuthTypes | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        follow_redirects: bool | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        timeout: httpx._types.TimeoutTypes | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        extensions: dict[str, typing.Any] | None = None,
    ) -> httpx.Response:
        return await super().get(
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            auth=auth,
            follow_redirects=follow_redirects,
            timeout=timeout,
            extensions=extensions,
        )

    async def options(  # type: ignore[override]
        self,
        url: httpx._types.URLTypes,
        *,
        params: httpx._types.QueryParamTypes | None = None,
        headers: httpx._types.HeaderTypes | None = None,
        cookies: httpx._types.CookieTypes | None = None,
        auth: httpx._types.AuthTypes | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        follow_redirects: bool | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        timeout: httpx._types.TimeoutTypes | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        extensions: dict[str, typing.Any] | None = None,
    ) -> httpx.Response:
        return await super().options(
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            auth=auth,
            follow_redirects=follow_redirects,
            timeout=timeout,
            extensions=extensions,
        )

    async def head(  # type: ignore[override]
        self,
        url: httpx._types.URLTypes,
        *,
        params: httpx._types.QueryParamTypes | None = None,
        headers: httpx._types.HeaderTypes | None = None,
        cookies: httpx._types.CookieTypes | None = None,
        auth: httpx._types.AuthTypes | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        follow_redirects: bool | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        timeout: httpx._types.TimeoutTypes | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        extensions: dict[str, typing.Any] | None = None,
    ) -> httpx.Response:
        return await super().head(
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            auth=auth,
            follow_redirects=follow_redirects,
            timeout=timeout,
            extensions=extensions,
        )

    async def post(  # type: ignore[override]
        self,
        url: httpx._types.URLTypes,
        *,
        content: httpx._types.RequestContent | None = None,
        data: _RequestData | None = None,
        files: httpx._types.RequestFiles | None = None,
        json: typing.Any = None,
        params: httpx._types.QueryParamTypes | None = None,
        headers: httpx._types.HeaderTypes | None = None,
        cookies: httpx._types.CookieTypes | None = None,
        auth: httpx._types.AuthTypes | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        follow_redirects: bool | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        timeout: httpx._types.TimeoutTypes | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        extensions: dict[str, typing.Any] | None = None,
    ) -> httpx.Response:
        return await super().post(
            url,
            content=content,
            data=data,
            files=files,
            json=json,
            params=params,
            headers=headers,
            cookies=cookies,
            auth=auth,
            follow_redirects=follow_redirects,
            timeout=timeout,
            extensions=extensions,
        )

    async def put(  # type: ignore[override]
        self,
        url: httpx._types.URLTypes,
        *,
        content: httpx._types.RequestContent | None = None,
        data: _RequestData | None = None,
        files: httpx._types.RequestFiles | None = None,
        json: typing.Any = None,
        params: httpx._types.QueryParamTypes | None = None,
        headers: httpx._types.HeaderTypes | None = None,
        cookies: httpx._types.CookieTypes | None = None,
        auth: httpx._types.AuthTypes | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        follow_redirects: bool | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        timeout: httpx._types.TimeoutTypes | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        extensions: dict[str, typing.Any] | None = None,
    ) -> httpx.Response:
        return await super().put(
            url,
            content=content,
            data=data,
            files=files,
            json=json,
            params=params,
            headers=headers,
            cookies=cookies,
            auth=auth,
            follow_redirects=follow_redirects,
            timeout=timeout,
            extensions=extensions,
        )

    async def patch(  # type: ignore[override]
        self,
        url: httpx._types.URLTypes,
        *,
        content: httpx._types.RequestContent | None = None,
        data: _RequestData | None = None,
        files: httpx._types.RequestFiles | None = None,
        json: typing.Any = None,
        params: httpx._types.QueryParamTypes | None = None,
        headers: httpx._types.HeaderTypes | None = None,
        cookies: httpx._types.CookieTypes | None = None,
        auth: httpx._types.AuthTypes | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        follow_redirects: bool | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        timeout: httpx._types.TimeoutTypes | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        extensions: dict[str, typing.Any] | None = None,
    ) -> httpx.Response:
        return await super().patch(
            url,
            content=content,
            data=data,
            files=files,
            json=json,
            params=params,
            headers=headers,
            cookies=cookies,
            auth=auth,
            follow_redirects=follow_redirects,
            timeout=timeout,
            extensions=extensions,
        )

    async def delete(  # type: ignore[override]
        self,
        url: httpx._types.URLTypes,
        *,
        params: httpx._types.QueryParamTypes | None = None,
        headers: httpx._types.HeaderTypes | None = None,
        cookies: httpx._types.CookieTypes | None = None,
        auth: httpx._types.AuthTypes | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        follow_redirects: bool | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        timeout: httpx._types.TimeoutTypes | httpx._client.UseClientDefault = httpx._client.USE_CLIENT_DEFAULT,
        extensions: dict[str, typing.Any] | None = None,
    ) -> httpx.Response:
        return await super().delete(
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            auth=auth,
            follow_redirects=follow_redirects,
            timeout=timeout,
            extensions=extensions,
        )

    async def websocket_connect(
        self,
        url: str,
        subprotocols: typing.Sequence[str] | None = None,
        **kwargs: typing.Any,
    ) -> AsyncWebSocketTestSession:
        url = urljoin("ws://testserver", url)
        headers = kwargs.get("headers", {})
        headers.setdefault("connection", "upgrade")
        headers.setdefault("sec-websocket-key", "testserver==")
        headers.setdefault("sec-websocket-version", "13")
        if subprotocols is not None:
            headers.setdefault("sec-websocket-protocol", ", ".join(subprotocols))
        kwargs["headers"] = headers
        try:
            await super().request("GET", url, **kwargs)
        except _AsyncUpgrade as exc:
            session = exc.session
        else:
            raise RuntimeError("Expected WebSocket upgrade")  # pragma: no cover

        return session

    async def __aenter__(self) -> "AsyncTestClient":
        async with contextlib.AsyncExitStack() as stack:
            task_group = await stack.enter_async_context(anyio.create_task_group())
            send: anyio.create_memory_object_stream[typing.MutableMapping[str, typing.Any] | None] = (
                anyio.create_memory_object_stream(math.inf)
            )
            receive: anyio.create_memory_object_stream[typing.MutableMapping[str, typing.Any]] = (
                anyio.create_memory_object_stream(math.inf)
            )
            for channel in (*send, *receive):
                stack.push_async_callback(channel.aclose)
            self.stream_send = StapledObjectStream(*send)
            self.stream_receive = StapledObjectStream(*receive)
            self.task_done = anyio.Event()

            async def lifespan() -> None:
                await self.lifespan()
                self.task_done.set()

            task_group.start_soon(lifespan)
            await self.wait_startup()

            @stack.push_async_callback
            async def wait_shutdown() -> None:
                await self.wait_shutdown()

            self.exit_stack = stack.pop_all()

        return self

    async def __aexit__(self, *args: typing.Any) -> None:
        await self.exit_stack.aclose()

    async def lifespan(self) -> None:
        scope = {"type": "lifespan", "state": self.app_state}
        try:
            await self.app(scope, self.stream_receive.receive, self.stream_send.send)
        finally:
            try:
                await self.stream_send.send(None)
            except anyio.ClosedResourceError:
                pass

    async def wait_startup(self) -> None:
        await self.stream_receive.send({"type": "lifespan.startup"})

        async def receive() -> typing.Any:
            message = await self.stream_send.receive()
            if message is None:
                await self.task_done.wait()
            return message

        message = await receive()
        assert message["type"] in (
            "lifespan.startup.complete",
            "lifespan.startup.failed",
        )
        if message["type"] == "lifespan.startup.failed":
            await receive()

    async def wait_shutdown(self) -> None:
        async def receive() -> typing.Any:
            message = await self.stream_send.receive()
            if message is None:
                await self.task_done.wait()
            return message

        await self.stream_receive.send({"type": "lifespan.shutdown"})
        message = await receive()
        assert message["type"] in (
            "lifespan.shutdown.complete",
            "lifespan.shutdown.failed",
        )
        if message["type"] == "lifespan.shutdown.failed":
            await receive()


@pytest.fixture()
async def async_test_client(test_env):
    with unittest.mock.patch.dict(os.environ, test_env, clear=True):
        from simple_web_app.app import app
        return AsyncTestClient(app)

