from aiohttp import web


async def data_handler(request):
    resp = web.StreamResponse(status=200,
                              reason='OK',
                              headers={'Content-Type': 'text/html'})

    await resp.prepare(request)
    return resp


def init():
    app = web.Application()
    app.router.add_post("/data", data_handler)
    return app


if __name__ == "__main__":
    web.run_app(init())


