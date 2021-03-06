import random
import time
import uuid

from pymine.types.bitfield import BitField
from pymine.types.buffer import Buffer
from pymine.types.packet import Packet
from pymine.types.player import Player
from pymine.types.stream import Stream
from pymine.types.world import World
from pymine.types.chat import Chat
import pymine.types.nbt as nbt

from pymine.data.default_nbt.dimension_codec import new_dim_codec_nbt, get_dimension_data
from pymine.data.recipes import RECIPES
from pymine.data.tags import TAGS

from pymine.util.misc import seed_hash
import pymine.net.packets as packets
from pymine.server import server


# Used to finish the process of allowing a client to actually enter the server
async def join(stream: Stream, uuid_: uuid.UUID, username: str, props: list) -> None:
    server.cache.uuid[stream.remote] = int(uuid_)  # update uuid cache

    player = await server.playerio.fetch_player(uuid_)  # fetch player data from disk
    player.props = props
    player.stream = stream
    player.username = username

    world = server.worlds[player["Dimension"].data]  # the world player *should* be spawning into

    await send_join_game_packet(stream, world, player)

    # send server brand via plugin channels
    await server.send_packet(
        stream, packets.play.plugin_msg.PlayPluginMessageClientBound("minecraft:brand", Buffer.pack_string(server.meta.pymine))
    )

    # sends info about the server difficulty
    await server.send_packet(
        stream,
        packets.play.difficulty.PlayServerDifficulty(world["Difficulty"].data, world["DifficultyLocked"].data),
    )

    await send_player_abilities(stream, player)


async def join_2(stream: Stream, player: Player) -> None:
    world = server.worlds[player["Dimension"].data]  # the world player *should* be spawning into

    # change held item to saved last held item
    await server.send_packet(stream, packets.play.player.PlayHeldItemChangeClientBound(player["SelectedItemSlot"].data))

    # send recipes
    await server.send_packet(stream, packets.play.crafting.PlayDeclareRecipes(RECIPES))

    # send tags (data about the different blocks and items)
    await server.send_packet(stream, packets.play.tags.PlayTags(TAGS))

    # send entity status packet, apparently this is required, for now it'll just set player to op lvl 4 (value 28)
    await server.send_packet(stream, packets.play.entity.PlayEntityStatus(player.entity_id, 28))

    # tell the client the commands, since proper commands + arg parsing hasn't been added yet, we send an empty list.
    await server.send_packet(stream, packets.play.command.PlayDeclareCommands([]))

    # send unlocked recipes to the client
    await send_unlocked_recipes(stream, player)

    # update player position and rotation
    # await server.send_packet(  # wiki.vg says to send twice?? (see normal login sequence page)
    #     stream, packets.play.player.PlayPlayerPositionAndLookClientBound(player, 0, random.randint(1, 999999))
    # )

    # update tab list, maybe sent to all clients?
    await broadcast_player_info(player)

    # see here: https://wiki.vg/Protocol#Update_View_Position
    await server.send_packet(stream, packets.play.player.PlayUpdateViewPosition(player.x // 32, player.z // 32))

    # send_update_view_distance, unsure if needed, see here: https://wiki.vg/Protocol#Update_View_Distance
    # await send_update_view_distance(stream, player)

    await send_world_info(stream, world, player)

    await send_positional_data(stream, world, player)


# crucial info pertaining to the world and player status
async def send_join_game_packet(stream: Stream, world: World, player: Player) -> None:
    level_name = server.conf["level_name"]  # level name, i.e. Xenon

    await server.send_packet(
        stream,
        packets.play.player.PlayJoinGame(
            player.entity_id,
            server.conf["hardcore"],  # whether world is hardcore or not
            player["playerGameType"].data,  # gamemode
            player["previousPlayerGameType"].data,  # previous gamemode
            [level_name, f"{level_name}_nether", f"{level_name}_the_end"],  # world names
            new_dim_codec_nbt(),  # Shouldn't change unless CUSTOM DIMENSIONS are added fml
            # This is like the the dimension data for the dim the player is currently spawning into
            get_dimension_data(player["Dimension"].data),  # player['Dimension'] should be like minecraft:overworld
            server.conf["level_name"],  # level name of the world the player is spawning into
            seed_hash(server.conf["seed"]),
            server.conf["max_players"],
            server.conf["view_distance"],
            (not server.conf["debug"]),
            (world["GameRules"]["doImmediateRespawn"].data != "true"),  # (not doImmediateRespawn gamerule)
            False,  # If world is a debug world iirc
            False,  # ShouFld be true if world is superflat
        ),
    )


# send what the player can/can't do
async def send_player_abilities(stream: Stream, player: Player) -> None:
    abilities = player["abilities"]
    flags = BitField.new(4)

    flags.add(0x01, abilities["invulnerable"].data)
    flags.add(0x02, abilities["flying"].data)
    flags.add(0x04, abilities["mayfly"].data)
    flags.add(0x08, abilities["instabuild"].data)

    await server.send_packet(  # yes the last arg is supposed to be fov, but the values are actually the same
        stream,
        packets.play.player.PlayPlayerAbilitiesClientBound(
            flags.field, abilities["flySpeed"].data, abilities["walkSpeed"].data
        ),
    )


# sends the previously unlocked + unviewed unlocked recipies to the client
async def send_unlocked_recipes(stream: Stream, player: Player) -> None:
    await server.send_packet(
        stream,
        packets.play.crafting.PlayUnlockRecipes(
            0,  # init
            player["recipeBook"]["isGuiOpen"],  # refers to the regular crafting bench/table
            player["recipeBook"]["isFilteringCraftable"],  # refers to the regular crafting bench/table
            player["recipeBook"]["isFurnaceGuiOpen"],
            player["recipeBook"]["isFurnaceFilteringCraftable"],
            player["recipeBook"]["isBlastingFurnaceGuiOpen"],
            player["recipeBook"]["isBlastingFurnaceFilteringCraftable"],
            player["recipeBook"]["isSmokerGuiOpen"],
            player["recipeBook"]["isSmokerFilteringCraftable"],
            player["recipeBook"]["recipes"],  # all unlocked recipes
            player["recipeBook"]["toBeDisplayed"],  # ones which will be displayed as newly unlocked
        ),
    )


# broadcasts the player's info to the other clients, this is needed to support skins and update the tab list
async def broadcast_player_info(player: Player) -> None:
    display_name = player.get("CustomName")

    if not player.get("CustomNameVisible"):
        display_name = None

    # Unsure whether these should broadcast to all clients or not
    # Also unsure whether they should include all player data or just that for the connecting player

    await server.broadcast_packet(
        packets.play.player.PlayPlayerInfo(
            0,  # the action, add player
            [
                {
                    "uuid": player.uuid,
                    "name": player.name,
                    "properties": player.props,
                    "gamemode": player["playerGameType"],
                    "ping": 0,
                    "display_name": Chat(display_name),
                }
            ],
        )
    )

    # I don't know why latency isn't just updated in the first packet broadcasted, mc do be weird
    await server.broadcast_packet(
        packets.play.player.PlayPlayerInfo(
            2,  # the action, update latency
            [{"uuid": player.uuid, "ping": 0}],
        )
    )


# updates client view distance, unsure if needed, see here: https://wiki.vg/Protocol#Update_View_Distance
async def send_update_view_distance(stream: Stream, player: Player) -> None:
    view_distance = player.view_distance

    if view_distance > server.conf["view_distance"]:
        view_distance = server.conf["view_distance"]

    await server.send_packet(stream, packets.play.player.PlayUpdateViewDistance(view_distance))


# sends information about the world to the client, like chunk data and other stuff
async def send_world_info(stream: Stream, world: World, player: Player) -> None:
    chunks = {}  # cache chunks here because they're used multiple times and shouldn't be garbage collected

    for x in range(-player.view_distance - 1, player.view_distance + 1):
        for z in range(-player.view_distance - 1, player.view_distance + 1):
            chunks[x, z] = await world.fetch_chunk(x, z)

    for chunk in chunks.values():  # send update light packet for each chunk in the player's view distance
        await server.send_packet(stream, packets.play.chunk.PlayUpdateLight(chunk))

    for chunk in chunks.values():  # send chunk data packet for each chunk in player's view distance
        await server.send_packet(stream, packets.play.chunk.PlayChunkData(chunk, True))

    del chunks  # no longer needed so free the memoryyyy

    # send the world border data to the client
    await server.send_packet(
        stream,
        packets.play.world.PlayWorldBorder(
            3,
            {
                "x": world["BorderCenterX"],
                "z": world["BorderCenterZ"],
                "old_diameter": world["BorderSize"],
                "new_diameter": world["BorderSize"],
                "speed": 0,
                "portal_teleport_boundary": world["BorderSize"],
                "warning_blocks": world["BorderWarningBlocks"],
                "warning_time": world["BorderWarningTime"],
            },
        ),
    )


# update the player's position and rotation, as well as the world spawn
async def send_positional_data(stream: Stream, world: World, player: Player) -> None:
    flags = BitField.new(5, (0x01, False), (0x02, False), (0x04, False), (0x08, False), (0x10, False))

    await server.send_packet(
        stream,
        packets.play.player.PlayPlayerPositionAndLookClientBound(
            player, flags.field, random.randint(0, 999999)  # the tp id, should be verified later
        ),
    )

    await server.send_packet(stream, packets.play.spawn.PlaySpawnPosition(world["SpawnX"], world["SpawnY"], world["SpawnZ"]))
