import httpx
# noinspection PyProtectedMember
from httpx._types import QueryParamTypes

server_list_url = "https://api.steampowered.com/IGameServersService/GetServerList/v1/"


async def web_api_request(
        client: httpx.AsyncClient,
        url: str,
        params: QueryParamTypes | None = None,
) -> httpx.Response:
    # TODO: keep track of how many API requests we make!

    resp = await client.get(
        url,
        params=params,
    )
    return resp
