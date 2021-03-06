import importlib
import asyncio
import uuid
import os

from pymine.util.stop import stop

from pymine.api.errors import ParsingError
from pymine.api.abc import AbstractParser

from pymine.logic import parsers


class CommandHandler:
    def __init__(self, server):
        self.server = server
        self.console = server.console
        self._commands = {}  # {name: (func, node)}

    # loads default built in commands
    @staticmethod
    def load_commands():  # only loads commands inside cmds folder, not subfolders
        for file in os.listdir("pymine/logic/cmds"):
            if file.endswith(".py"):
                importlib.import_module(f"pymine.logic.cmds.{file[:-3]}")

    def on_command(self, name: str, node: str):
        if name in self._commands:
            raise ValueError("Command name is already in use.")

        if " " in name:
            raise ValueError("Command name may not contain spaces.")

        def deco(func):
            if not asyncio.iscoroutinefunction(func):
                raise ValueError("Decorated object must be a coroutine function.")

            # checks to see if there are enough typehints for the number of args
            if not len(func.__annotations__) >= func.__code__.co_argcount - 1:
                raise ValueError(f"Missing required argument typehints/annotations for {func.__module__}.{func.__qualname__}.")

            self._commands[name] = func, node
            return func

        return deco

    async def handle_command(self, uuid_: uuid.UUID, full: str):
        split = full.split(" ")
        command = self._commands.get(split[0])
        args_text = " ".join(split[1:])  # basically the text excluding the actual command name and the space following it

        if command is None:  # user error
            self.console.warn(f"Invalid/unknown command: {split[0]}")
            return

        command = command[0]  # we don't need the permission node for now so yeah

        parsed_to = 0
        args = []

        for arg in command.__code__.co_varnames[1 : command.__code__.co_argcount]:  # go through args skipping the first arg
            parser = command.__annotations__.get(arg)  # get parser from annotations

            if isinstance(parser, bool):  # allow for primitive bool type to be used as a typehint
                parser = parsers.Bool()
            elif isinstance(parser, float):  # allow for primitive float type to be used as a typehint
                parser = parsers.Double()
            elif isinstance(parser, int):  # allow for primitive int type to be used as a typehint
                parser = parsers.Integer()
            elif isinstance(parser, str):  # allow for primitive str type to be used as a typehint
                parser = parsers.String(0)  # a single word
            elif not isinstance(parser, AbstractParser):  # dev error
                raise ValueError(f"{parser} is not an instance of AbstractParser or a compatible primitive type.")

            try:
                just_parsed_to, parsed = parser.parse(args_text[parsed_to:])
            except ParsingError:  # either devs did a bad or user didn't put in the right arguments
                self.console.warn(f"Invalid input for command {split[0]}: {repr(args_text[parsed_to:])}")
                return

            parsed_to += just_parsed_to + 1  # +1 to account for space which differentiates arguments

            args.append(parsed)

        try:
            await command(uuid_, *args)
        except BaseException as e:  # dev error
            self.console.error(f"Error while executing command {split[0]}: {self.console.f_traceback(e)}")

    async def handle_console_commands(self):
        eoferr = False

        try:
            while True:
                in_ = await self.console.fetch_input()

                if in_ == "":
                    continue

                try:
                    await self.handle_command("server", in_)
                except BaseException as e:  # pymine devs did an oopsie?
                    self.console.error(f"Error while handling command {repr(in_)}: {self.console.f_traceback(e)}")
                    continue

                if in_.startswith("stop"):
                    break

                await asyncio.sleep(0)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        except EOFError:
            eoferr = True
        except BaseException as e:
            self.console.error(self.console.f_traceback(e))

        if eoferr:
            await stop(self.server)
