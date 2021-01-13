from src.api.server import on_server_ready
from src.api.packet import handle_packet


@handle_packet('handshaking', 0x00)
async def example_handle_handshake(r, w, packet, remote):
    print('Hello this is the example packet handler speaking how may I take your order sir')

    return True, r, w


@on_server_ready
async def on_server_ready():
    print('AYYY SERVER DO BE WORKING THO NGL')
